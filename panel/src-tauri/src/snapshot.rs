use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunStatusDto {
    pub run_id: String,
    pub workflow_id: String,
    pub state: String,
    pub step_id: Option<String>,
    pub pid: Option<i64>,
    pub started_at: String,
    pub updated_at: String,
    pub last_error: Option<String>,
    pub dirty: bool,
    #[serde(default)]
    pub lives_total: Option<i64>,
    #[serde(default)]
    pub lives_left: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModelUsage {
    pub input_uncached: i64,
    pub cache_read: i64,
    pub cache_write: i64,
    pub output: i64,
    pub dirty: i64,
    pub events: i64,
    pub mismatch_events: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageLogItem {
    pub at: String,
    pub run_id: String,
    pub step_id: String,
    pub agent: String,
    pub model: String,
    pub input_uncached: i64,
    pub cache_read: i64,
    pub cache_write: i64,
    pub output: i64,
    pub usd: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryItem {
    pub run_id: String,
    pub state: String,
    pub workflow_id: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub repo_root: String,
    pub current_run_id: Option<String>,
    pub selected_run_id: Option<String>,
    pub status: Option<RunStatusDto>,
    pub usage_by_model: HashMap<String, ModelUsage>,
    pub usage_log: Vec<UsageLogItem>,
    pub history: Vec<HistoryItem>,
    pub workflows: Vec<String>,
    pub error: Option<String>,
    #[serde(default)]
    pub workflow_steps: Vec<String>,
}

fn runs_root(repo: &Path) -> PathBuf {
    repo.join("runs")
}

pub fn read_current_run_id(repo: &Path) -> Option<String> {
    let path = runs_root(repo).join("current.json");
    let text = fs::read_to_string(path).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    v.get("run_id")?.as_str().map(|s| s.to_string())
}

pub fn read_status(repo: &Path, run_id: &str) -> Option<RunStatusDto> {
    let path = runs_root(repo).join(run_id).join("status.json");
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn summarize_usage(repo: &Path, run_id: &str) -> HashMap<String, ModelUsage> {
    let path = runs_root(repo).join(run_id).join("usage_events.jsonl");
    let Ok(text) = fs::read_to_string(path) else {
        return HashMap::new();
    };
    let mut by_model: HashMap<String, ModelUsage> = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let model = v
            .get("model_actual")
            .and_then(|x| x.as_str())
            .unwrap_or("unknown")
            .to_string();
        let row = by_model.entry(model).or_default();
        row.input_uncached += v.get("input_uncached").and_then(|x| x.as_i64()).unwrap_or(0);
        row.cache_read += v.get("cache_read").and_then(|x| x.as_i64()).unwrap_or(0);
        row.cache_write += v.get("cache_write").and_then(|x| x.as_i64()).unwrap_or(0);
        row.output += v.get("output").and_then(|x| x.as_i64()).unwrap_or(0);
        row.dirty += i64::from(v.get("dirty").and_then(|x| x.as_bool()).unwrap_or(false));
        row.mismatch_events +=
            i64::from(v.get("mismatch").and_then(|x| x.as_bool()).unwrap_or(false));
        row.events += 1;
    }
    by_model
}

pub fn list_history(repo: &Path, limit: usize) -> Vec<HistoryItem> {
    let root = runs_root(repo);
    let Ok(entries) = fs::read_dir(&root) else {
        return Vec::new();
    };
    let mut items: Vec<HistoryItem> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with('.') {
            continue;
        }
        let Some(status) = read_status(repo, &name) else {
            continue;
        };
        items.push(HistoryItem {
            run_id: status.run_id.clone(),
            state: status.state.clone(),
            workflow_id: status.workflow_id.clone(),
            updated_at: status.updated_at.clone(),
        });
    }
    items.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
    items.truncate(limit);
    items
}

pub fn build_snapshot(repo_root: &str, selected_run_id: Option<String>) -> Snapshot {
    let repo = PathBuf::from(repo_root);
    if !repo.is_dir() {
        return Snapshot {
            repo_root: repo_root.to_string(),
            current_run_id: None,
            selected_run_id: None,
            status: None,
            usage_by_model: HashMap::new(),
            usage_log: Vec::new(),
            history: Vec::new(),
            workflows: Vec::new(),
            error: Some(format!("repo root is not a directory: {repo_root}")),
            workflow_steps: Vec::new(),
        };
    }
    let current = read_current_run_id(&repo);
    let history = list_history(&repo, 20);
    let selected = selected_run_id
        .filter(|id| !id.is_empty())
        .or_else(|| current.clone())
        .or_else(|| history.first().map(|h| h.run_id.clone()));
    let status = selected.as_ref().and_then(|id| read_status(&repo, id));
    let usage = selected
        .as_ref()
        .map(|id| summarize_usage(&repo, id))
        .unwrap_or_default();
    let workflow_steps = status
        .as_ref()
        .map(|s| get_workflow_steps(&repo, &s.workflow_id))
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| {
            list_workflows(&repo)
                .first()
                .map(|wf| {
                    let stem = Path::new(wf)
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .unwrap_or("");
                    get_workflow_steps(&repo, stem)
                })
                .unwrap_or_default()
        });
    Snapshot {
        repo_root: repo_root.to_string(),
        current_run_id: current,
        selected_run_id: selected,
        status,
        usage_by_model: usage,
        usage_log: collect_usage_log(&repo),
        history,
        workflows: list_workflows(&repo),
        error: None,
        workflow_steps,
    }
}

pub fn collect_usage_log(repo: &Path) -> Vec<UsageLogItem> {
    // Prefer the shared sqlite ledger (same path as the browser snapshot server).
    if let Some(rows) = collect_usage_log_from_ledger(repo) {
        return rows;
    }
    collect_usage_log_from_jsonl(repo)
}

fn collect_usage_log_from_ledger(repo: &Path) -> Option<Vec<UsageLogItem>> {
    let python = std::env::var("PYTHON").unwrap_or_else(|_| "python".into());
    // Uses AIWORK_USAGE_DB when set (tests); otherwise the shared data/usage.sqlite.
    let out = Command::new(python)
        .args([
            "-c",
            "import json,os; from pathlib import Path; from aiwork.usage_view import collect_usage_log; print(json.dumps(collect_usage_log(Path(os.environ['AIWORK_USAGE_REPO']))))",
        ])
        .env("AIWORK_USAGE_REPO", repo)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8(out.stdout).ok()?;
    serde_json::from_str(text.trim()).ok()
}

fn collect_usage_log_from_jsonl(repo: &Path) -> Vec<UsageLogItem> {
    let root = runs_root(repo);
    let Ok(entries) = fs::read_dir(&root) else {
        return Vec::new();
    };
    let mut pending: Vec<(Option<i64>, i64, UsageLogItem)> = Vec::new();
    let mut seq = 0i64;
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with('.') {
            continue;
        }
        let started = read_started_unix(&path);
        let Ok(text) = fs::read_to_string(path.join("usage_events.jsonl")) else {
            continue;
        };
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let Ok(v) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            seq += 1;
            let recorded = v
                .get("recorded_at")
                .and_then(|x| x.as_str())
                .and_then(parse_unix);
            let instant = recorded.or(started);
            let run_id = v
                .get("run_id")
                .and_then(|x| x.as_str())
                .unwrap_or(&name)
                .to_string();
            let model = v
                .get("model_actual")
                .and_then(|x| x.as_str())
                .unwrap_or("unknown")
                .to_string();
            let input_uncached = json_i64(&v, "input_uncached");
            let cache_read = json_i64(&v, "cache_read");
            let cache_write = json_i64(&v, "cache_write");
            let output = json_i64(&v, "output");
            pending.push((
                instant,
                seq,
                UsageLogItem {
                    at: instant.map(format_taipei).unwrap_or_default(),
                    run_id,
                    step_id: v
                        .get("step_id")
                        .and_then(|x| x.as_str())
                        .unwrap_or("")
                        .to_string(),
                    agent: v
                        .get("agent")
                        .and_then(|x| x.as_str())
                        .unwrap_or("")
                        .to_string(),
                    model: model.clone(),
                    input_uncached,
                    cache_read,
                    cache_write,
                    output,
                    usd: quote_usd(&model, input_uncached, cache_read, cache_write, output),
                },
            ));
        }
    }
    pending.sort_by(|a, b| match (a.0, b.0) {
        (Some(x), Some(y)) => y.cmp(&x).then(b.1.cmp(&a.1)),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => b.1.cmp(&a.1),
    });
    pending.into_iter().map(|(_, _, row)| row).collect()
}

fn read_started_unix(run_dir: &Path) -> Option<i64> {
    let text = fs::read_to_string(run_dir.join("status.json")).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    v.get("started_at").and_then(|x| x.as_str()).and_then(parse_unix)
}

fn json_i64(v: &Value, key: &str) -> i64 {
    v.get(key).and_then(|x| x.as_i64()).unwrap_or(0)
}

fn parse_unix(raw: &str) -> Option<i64> {
    let text = raw.trim();
    let (date, rest) = text.split_once('T')?;
    let mut date_parts = date.split('-');
    let year: i32 = date_parts.next()?.parse().ok()?;
    let month: u32 = date_parts.next()?.parse().ok()?;
    let day: u32 = date_parts.next()?.parse().ok()?;
    if date_parts.next().is_some() {
        return None;
    }
    let (time, offset) = if let Some(clock) = rest.strip_suffix('Z') {
        (clock, 0i64)
    } else {
        let idx = rest.rfind(['+', '-'])?;
        if idx == 0 {
            return None;
        }
        let off = &rest[idx..];
        let sign = if off.starts_with('-') { -1 } else { 1 };
        let mut hm = off[1..].split(':');
        let hours: i64 = hm.next()?.parse().ok()?;
        let mins: i64 = hm.next()?.parse().ok()?;
        (&rest[..idx], sign * (hours * 3600 + mins * 60))
    };
    let time = time.split('.').next().unwrap_or(time);
    let mut clock = time.split(':');
    let hour: i64 = clock.next()?.parse().ok()?;
    let min: i64 = clock.next()?.parse().ok()?;
    let sec: i64 = clock.next()?.parse().ok()?;
    let days = days_from_civil(year, month, day)?;
    Some(days * 86400 + hour * 3600 + min * 60 + sec - offset)
}

fn format_taipei(unix: i64) -> String {
    let local = unix + 8 * 3600;
    let days = local.div_euclid(86400);
    let sod = local.rem_euclid(86400);
    let (year, month, day) = civil_from_days(days);
    let hour = sod / 3600;
    let min = (sod % 3600) / 60;
    let sec = sod % 60;
    format!("{year:04}-{month:02}-{day:02} {hour:02}:{min:02}:{sec:02}")
}

fn days_from_civil(mut year: i32, month: u32, day: u32) -> Option<i64> {
    if !(1..=12).contains(&month) || day == 0 || day > 31 {
        return None;
    }
    if month <= 2 {
        year -= 1;
    }
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let yoe = (year - era * 400) as u32;
    let month_adj = if month > 2 { month - 3 } else { month + 9 };
    let doy = (153 * month_adj + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Some(era as i64 * 146097 + doe as i64 - 719468)
}

fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { y + 1 } else { y };
    (year as i32, month, day)
}

fn quote_usd(
    model: &str,
    input_uncached: i64,
    cache_read: i64,
    cache_write: i64,
    output: i64,
) -> Option<f64> {
    let table: Value = serde_json::from_str(include_str!(
        "../../../src/aiwork/public_prices.json"
    ))
    .ok()?;
    let rates = table.get("models")?.get(model_key(model))?;
    let mut total = 0.0;
    for (name, count) in [
        ("input", input_uncached),
        ("cache_read", cache_read),
        ("cache_write", cache_write),
        ("output", output),
    ] {
        if let Some(rate) = rates.get(name).and_then(|value| value.as_f64()) {
            total += rate * count as f64;
        }
    }
    Some((total / 1_000_000.0 * 100_000_000.0).round() / 100_000_000.0)
}

fn model_key(model: &str) -> String {
    let mut out = String::new();
    let mut prev_dash = false;
    for ch in model.trim().chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            prev_dash = false;
        } else if !prev_dash && !out.is_empty() {
            out.push('-');
            prev_dash = true;
        }
    }
    if let Some(idx) = out.rfind('-') {
        let tail = &out[idx + 1..];
        if tail.len() == 8 && tail.chars().all(|ch| ch.is_ascii_digit()) {
            out.truncate(idx);
        }
    }
    out
}

pub fn list_workflows(repo: &Path) -> Vec<String> {
    let dir = repo.join("workflows");
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut names: Vec<String> = entries
        .flatten()
        .filter(|e| e.path().is_file())
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            if name.ends_with(".yaml") || name.ends_with(".yml") {
                Some(format!("workflows/{name}"))
            } else {
                None
            }
        })
        .collect();
    names.sort();
    names
}

pub fn get_workflow_steps(repo: &Path, workflow_id: &str) -> Vec<String> {
    if workflow_id.is_empty() {
        return Vec::new();
    }
    let dir = repo.join("workflows");
    let candidates = [
        dir.join(format!("{workflow_id}.yaml")),
        dir.join(format!("{workflow_id}.yml")),
    ];
    for c in &candidates {
        if let Ok(text) = fs::read_to_string(c) {
            let mut steps = Vec::new();
            let mut in_steps = false;
            for line in text.lines() {
                let trimmed = line.trim();
                if trimmed.starts_with("steps:") {
                    in_steps = true;
                    continue;
                }
                if in_steps {
                    if !line.starts_with(' ') && !line.starts_with('\t') && !trimmed.is_empty() {
                        in_steps = false;
                        continue;
                    }
                    if trimmed.starts_with("- id:") {
                        let id = trimmed
                            .trim_start_matches("- id:")
                            .trim()
                            .trim_matches('"')
                            .trim_matches('\'');
                        if !id.is_empty() {
                            steps.push(id.to_string());
                        }
                    }
                }
            }
            if !steps.is_empty() {
                return steps;
            }
        }
    }
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn snapshot_reads_fixture_run() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("aiwork-panel-test-{stamp}"));
        let runs = dir.join("runs");
        let run = runs.join("abc123");
        fs::create_dir_all(&run).unwrap();
        fs::write(runs.join("current.json"), r#"{"run_id":"abc123"}"#).unwrap();
        fs::write(
            run.join("status.json"),
            r#"{
              "run_id":"abc123",
              "workflow_id":"smoke",
              "state":"running",
              "step_id":"step1",
              "pid":null,
              "started_at":"2026-09-21T00:00:00Z",
              "updated_at":"2026-09-21T00:01:00Z",
              "last_error":null,
              "dirty":false
            }"#,
        )
        .unwrap();
        let mut f = fs::File::create(run.join("usage_events.jsonl")).unwrap();
        writeln!(
            f,
            r#"{{"run_id":"abc123","step_id":"step1","agent":"cursor","model_requested":"composer-2","model_actual":"Composer 2.5","input_uncached":10,"cache_read":2,"cache_write":0,"output":5,"dirty":false,"mismatch":true}}"#
        )
        .unwrap();

        let snap = build_snapshot(dir.to_str().unwrap(), None);
        let _ = fs::remove_dir_all(&dir);
        assert_eq!(snap.current_run_id.as_deref(), Some("abc123"));
        assert_eq!(snap.status.as_ref().unwrap().state, "running");
        assert_eq!(
            snap.status.as_ref().unwrap().step_id.as_deref(),
            Some("step1")
        );
        let u = snap.usage_by_model.get("Composer 2.5").unwrap();
        assert_eq!(u.input_uncached, 10);
        assert_eq!(u.output, 5);
        assert_eq!(u.mismatch_events, 1);
        assert_eq!(snap.history.len(), 1);
    }

    #[test]
    fn usage_log_is_one_row_per_task() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("aiwork-panel-log-{stamp}"));
        let runs = dir.join("runs");
        write_run(
            &runs.join("aaa11111"),
            "aaa11111",
            Some("2026-09-20T16:00:00Z"),
            &[
                r#"{"run_id":"aaa11111","step_id":"step1","agent":"cursor","model_actual":"Composer 2.5","input_uncached":100,"cache_read":1,"output":10}"#,
                r#"{"run_id":"aaa11111","step_id":"step2","agent":"claude","model_actual":"claude-sonnet","input_uncached":5,"output":6,"recorded_at":"2026-10-01T10:30:00Z"}"#,
            ],
        );
        write_run(
            &runs.join("bbb22222"),
            "bbb22222",
            Some("2026-09-20T15:59:59Z"),
            &[r#"{"run_id":"bbb22222","step_id":"step1","agent":"gemini","model_actual":"gemini-2.5","input_uncached":40,"cache_read":4,"output":5}"#],
        );

        let db = dir.join("usage.sqlite");
        std::env::set_var("AIWORK_USAGE_DB", &db);
        let snap = build_snapshot(dir.to_str().unwrap(), None);
        std::env::remove_var("AIWORK_USAGE_DB");
        let _ = fs::remove_dir_all(&dir);
        assert_eq!(snap.usage_log.len(), 3);
        assert_eq!(snap.usage_log[0].at, "2026-10-01 18:30:00");
        assert_eq!(snap.usage_log[0].model, "claude-sonnet");
        assert_eq!(snap.usage_log[0].output, 6);
        assert_eq!(snap.usage_log[1].at, "2026-09-21 00:00:00");
        assert_eq!(snap.usage_log[1].agent, "cursor");
        assert_eq!(snap.usage_log[1].model, "Composer 2.5");
        assert_eq!(snap.usage_log[1].input_uncached, 100);
        assert_eq!(snap.usage_log[2].at, "2026-09-20 23:59:59");
        assert_eq!(snap.usage_log[2].agent, "gemini");
    }

    fn write_run(dir: &Path, run_id: &str, started_at: Option<&str>, events: &[&str]) {
        fs::create_dir_all(dir).unwrap();
        let started = started_at
            .map(|s| format!(r#""started_at":"{s}","#))
            .unwrap_or_default();
        fs::write(
            dir.join("status.json"),
            format!(
                r#"{{"run_id":"{run_id}","workflow_id":"smoke","state":"succeeded","step_id":null,"pid":null,{started}"updated_at":"2026-10-01T00:00:00Z","last_error":null,"dirty":false}}"#
            ),
        )
        .unwrap();
        let mut body = String::new();
        for ev in events {
            body.push_str(ev);
            body.push('\n');
        }
        fs::write(dir.join("usage_events.jsonl"), body).unwrap();
    }
}
