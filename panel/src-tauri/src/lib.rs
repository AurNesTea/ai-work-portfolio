mod snapshot;

use snapshot::{build_snapshot, Snapshot};
use serde::Deserialize;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[derive(Debug, serde::Serialize)]
struct ActionResult {
    ok: bool,
    detail: String,
}

fn python_bin() -> String {
    std::env::var("PYTHON").unwrap_or_else(|_| "python".into())
}

fn spawn_aiwork(root: &str, args: &[&str], wait: bool) -> ActionResult {
    let repo = PathBuf::from(root);
    if !repo.is_dir() {
        return ActionResult {
            ok: false,
            detail: format!("not a directory: {root}"),
        };
    }
    let mut cmd = Command::new(python_bin());
    cmd.arg("-m")
        .arg("aiwork")
        .args(args)
        .current_dir(&repo)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if wait {
        match cmd.output() {
            Ok(out) => {
                let mut detail = String::from_utf8_lossy(&out.stdout).into_owned();
                if detail.trim().is_empty() {
                    detail = String::from_utf8_lossy(&out.stderr).into_owned();
                }
                ActionResult {
                    ok: out.status.success(),
                    detail: detail.trim().to_string(),
                }
            }
            Err(e) => ActionResult {
                ok: false,
                detail: e.to_string(),
            },
        }
    } else {
        match cmd.spawn() {
            Ok(child) => ActionResult {
                ok: true,
                detail: format!("started pid={}", child.id()),
            },
            Err(e) => ActionResult {
                ok: false,
                detail: e.to_string(),
            },
        }
    }
}

fn safe_rel_workflow(root: &str, workflow: &str) -> Result<String, String> {
    let rel = Path::new(workflow);
    if rel.is_absolute() || workflow.contains("..") {
        return Err("workflow must be a relative path".into());
    }
    let joined = PathBuf::from(root).join(rel);
    let canon = joined.canonicalize().map_err(|e| e.to_string())?;
    let root_c = PathBuf::from(root).canonicalize().map_err(|e| e.to_string())?;
    if !canon.starts_with(&root_c) {
        return Err("workflow outside repo".into());
    }
    if !canon.is_file() {
        return Err("not a file".into());
    }
    Ok(rel.to_string_lossy().replace('\\', "/"))
}

#[tauri::command]
fn get_snapshot(repo_root: String, selected_run_id: Option<String>) -> Snapshot {
    build_snapshot(&repo_root, selected_run_id)
}

#[tauri::command]
fn pick_repo_root(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    app.dialog()
        .file()
        .set_title("Select ai-work repo root")
        .blocking_pick_folder()
        .map(|p| p.to_string())
}

#[derive(Deserialize)]
struct RunArgs {
    repo_root: String,
    workflow: String,
}

#[tauri::command]
fn start_run(args: RunArgs) -> ActionResult {
    match safe_rel_workflow(&args.repo_root, &args.workflow) {
        Ok(wf) => spawn_aiwork(
            &args.repo_root,
            &["run", &wf, "--root", ".", "--workdir", ".", "--runs-root", "runs"],
            false,
        ),
        Err(detail) => ActionResult { ok: false, detail },
    }
}

#[derive(Deserialize)]
struct ContinueArgs {
    repo_root: String,
    workflow: String,
    run_id: String,
}

#[tauri::command]
fn continue_run(args: ContinueArgs) -> ActionResult {
    if args.run_id.contains('/') || args.run_id.contains('\\') || args.run_id == "." || args.run_id == ".." {
        return ActionResult {
            ok: false,
            detail: "invalid run_id".into(),
        };
    }
    let status_path = PathBuf::from(&args.repo_root)
        .join("runs")
        .join(&args.run_id)
        .join("status.json");
    let raw = match std::fs::read_to_string(&status_path) {
        Ok(text) => text,
        Err(_) => {
            return ActionResult {
                ok: false,
                detail: "沒有可繼續的執行".into(),
            };
        }
    };
    let status: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(_) => {
            return ActionResult {
                ok: false,
                detail: "沒有可繼續的執行".into(),
            };
        }
    };
    if status.get("state").and_then(|v| v.as_str()) != Some("waiting") {
        return ActionResult {
            ok: false,
            detail: "沒有可繼續的執行".into(),
        };
    }
    match safe_rel_workflow(&args.repo_root, &args.workflow) {
        Ok(wf) => spawn_aiwork(
            &args.repo_root,
            &[
                "run",
                &wf,
                "--root",
                ".",
                "--workdir",
                ".",
                "--runs-root",
                "runs",
                "--resume",
                &args.run_id,
            ],
            false,
        ),
        Err(detail) => ActionResult { ok: false, detail },
    }
}

#[derive(Deserialize)]
struct ApproveArgs {
    repo_root: String,
    run_id: String,
    step_id: String,
}

#[tauri::command]
fn approve_step(args: ApproveArgs) -> ActionResult {
    if args.run_id.contains('/') || args.run_id.contains('\\') {
        return ActionResult {
            ok: false,
            detail: "invalid run_id".into(),
        };
    }
    spawn_aiwork(
        &args.repo_root,
        &["approve", &args.run_id, &args.step_id, "--runs-root", "runs"],
        true,
    )
}

#[derive(Deserialize)]
struct CancelArgs {
    repo_root: String,
    run_id: Option<String>,
}

#[tauri::command]
fn cancel_run(args: CancelArgs) -> ActionResult {
    let mut argv = vec!["cancel".to_string(), "--runs-root".into(), "runs".into()];
    if let Some(id) = args.run_id.as_deref().filter(|s| !s.is_empty()) {
        if id.contains('/') || id.contains('\\') {
            return ActionResult {
                ok: false,
                detail: "invalid run_id".into(),
            };
        }
        argv.insert(1, id.to_string());
    }
    let refs: Vec<&str> = argv.iter().map(|s| s.as_str()).collect();
    spawn_aiwork(&args.repo_root, &refs, true)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            get_snapshot,
            pick_repo_root,
            start_run,
            continue_run,
            approve_step,
            cancel_run
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
