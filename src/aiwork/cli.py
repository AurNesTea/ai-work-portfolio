import json
import re
from pathlib import Path

import typer

from aiwork.adapters.claude import run_claude
from aiwork.adapters.codex import run_codex
from aiwork.adapters.cursor import run_cursor
from aiwork.adapters.gemini import run_gemini
from aiwork.dispatch import DispatchError, load_resolved, re_resolve_run, resolve_workflow
from aiwork.models import StepSpec
from aiwork.profiles import ProfileError, resolve_profile, validate_workflow_profiles
from aiwork.runner import RunnerError, run_single_step, run_workflow
from aiwork.status_store import get_current, read_status, set_current, write_status
from aiwork.usage_report import summarize_run
from aiwork.workflow import load_workflow

app = typer.Typer(help="aiwork — local agent workflow runner (no model HTTP)")

# run_id / step_id become path components under runs/<run_id>/..., so they must be one
# plain component. Checked here, at the sink, so the panel (HTTP or Tauri) cannot bypass it.
_PLAIN_ID = re.compile(r"\w[\w.-]{0,127}")


def _require_plain_id(kind: str, value: str | None) -> None:
    if value is not None and _PLAIN_ID.fullmatch(value) is None:
        typer.secho(f"invalid {kind}: {value!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)


def _build_adapters(root: Path):
    runners = {
        "cursor": run_cursor,
        "claude": run_claude,
        "codex": run_codex,
        "gemini": run_gemini,
    }

    def make(agent: str):
        def run_fn(**kwargs):
            step: StepSpec = kwargs["step"]
            run_dir: Path = kwargs.get("run_dir") or Path(kwargs["cwd"])
            write_dir = Path(run_dir) / "steps" / step.id
            resolved = resolve_profile(
                root=root,
                mcp_profile=step.mcp_profile,
                skills=[],
                write_dir=write_dir,
            )
            return runners[agent](
                model=kwargs["model"],
                prompt=kwargs["prompt"],
                cwd=kwargs["cwd"],
                timeout_sec=kwargs["timeout_sec"],
                env=resolved.env,
                effort=step.effort,
            )

        return run_fn

    return {name: make(name) for name in runners}


@app.command("run-step")
def run_step(
    prompt_file: str,
    model: str = "composer-2",
    runs_root: str = "runs",
    workdir: str = ".",
    timeout_sec: int = 600,
):
    """P0: run a single Cursor step and write status + usage."""
    step = StepSpec(
        id="step",
        agent="cursor",
        model=model,
        prompt_file=prompt_file,
        timeout_sec=timeout_sec,
    )
    try:
        run_dir = run_single_step(
            runs_root=Path(runs_root),
            workflow_id="adhoc",
            step=step,
            workdir=Path(workdir),
            run_fn=lambda **kw: run_cursor(
                model=kw["model"],
                prompt=kw["prompt"],
                cwd=kw["cwd"],
                timeout_sec=kw["timeout_sec"],
            ),
        )
    except RunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(run_dir))
    st = read_status(run_dir)
    if st.state != "succeeded":
        raise typer.Exit(code=1)


@app.command("run")
def run_cmd(
    workflow: str,
    runs_root: str = "runs",
    workdir: str = ".",
    root: str = ".",
    resume: str | None = None,
    force: bool = False,
    re_resolve: bool = typer.Option(
        False, "--re-resolve", help="Re-resolve incomplete steps with current roles/models table"
    ),
):
    """Run a sequential workflow YAML."""
    _require_plain_id("run_id", resume)
    root_path = Path(root).resolve()
    spec = load_workflow(Path(workflow), root=root_path)
    try:
        validate_workflow_profiles(root_path, spec)
    except ProfileError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    resolved = None
    if resume:
        run_dir = Path(runs_root) / resume
        if not run_dir.is_dir():
            typer.secho(f"run not found: {resume}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if re_resolve:
            try:
                resolved = re_resolve_run(spec, run_dir)
            except DispatchError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1) from exc
        else:
            if (run_dir / "resolved.json").is_file():
                resolved = load_resolved(run_dir)
            else:
                has_role = any(s.role for s in spec.steps)
                if has_role:
                    typer.secho(
                        f"run {resume} has role steps but resolved.json is missing",
                        fg=typer.colors.RED,
                        err=True,
                    )
                    raise typer.Exit(code=1)
    else:
        # Pre-resolve entire workflow before creating runs/<id> or touching current.json
        try:
            resolved = resolve_workflow(spec)
        except DispatchError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc

    try:
        run_dir = run_workflow(
            workflow=spec,
            runs_root=Path(runs_root),
            workdir=Path(workdir),
            root=root_path,
            adapters=_build_adapters(root_path),
            resume_run_id=resume,
            force=force,
            resolved=resolved,
        )
    except RunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(run_dir))
    st = read_status(run_dir)
    typer.echo(f"state={st.state} step={st.step_id}")
    if st.state != "succeeded":
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd(runs_root: str = "runs"):
    root = Path(runs_root)
    current = get_current(root)
    if not current:
        typer.echo("no active run")
        raise typer.Exit()
    run_dir = root / current
    st = read_status(run_dir)
    role_info = ""
    if st.step_id and (run_dir / "resolved.json").is_file():
        try:
            resolved = load_resolved(run_dir)
            if st.step_id in resolved.steps:
                r_step = resolved.steps[st.step_id]
                if r_step.role:
                    role_info = f" role={r_step.role}->{r_step.agent}/{r_step.model}"
                else:
                    role_info = f" role={r_step.agent}/{r_step.model}"
        except Exception:
            pass
    typer.echo(
        f"run_id={st.run_id} workflow={st.workflow_id} state={st.state} "
        f"step={st.step_id}{role_info} dirty={st.dirty} error={st.last_error}"
    )



@app.command("usage")
def usage_cmd(run_id: str | None = None, runs_root: str = "runs"):
    root = Path(runs_root)
    if run_id is None:
        run_id = get_current(root)
        if run_id is None:
            dirs = sorted(
                [p for p in root.iterdir() if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
            )
            if not dirs:
                typer.echo("no runs")
                raise typer.Exit()
            run_id = dirs[-1].name
    summary = summarize_run(root / run_id)
    typer.echo(f"run_id={run_id}")
    for model, row in summary.items():
        typer.echo(
            f"  {model}: in={row['input_uncached']} cache_r={row['cache_read']} "
            f"cache_w={row['cache_write']} out={row['output']} "
            f"dirty={row['dirty']} n={row['events']}"
        )


@app.command("approve")
def approve_cmd(run_id: str, step_id: str, runs_root: str = "runs"):
    _require_plain_id("run_id", run_id)
    _require_plain_id("step_id", step_id)
    path =Path(runs_root) / run_id / "approvals" / f"{step_id}.approved"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("approved", encoding="utf-8")
    pending = path.with_name(f"{step_id}.pending")
    if pending.exists():
        pending.unlink()
    typer.echo(
        f"approved {run_id}/{step_id}; resume with: "
        f"aiwork run <workflow> --resume {run_id}"
    )


@app.command("cancel")
def cancel_cmd(
    run_id: str | None = typer.Argument(None, help="Run to cancel (default: the current run)"),
    runs_root: str = "runs",
    run_id_option: str | None = typer.Option(None, "--run-id", hidden=True),
):
    from datetime import datetime, timezone

    from aiwork.models import RunStatus

    # The panel (Python and Rust) passes the id positionally; --run-id is the older form.
    run_id = run_id or run_id_option
    _require_plain_id("run_id", run_id)
    root = Path(runs_root)
    run_id = run_id or get_current(root)
    if not run_id:
        typer.echo("no run to cancel")
        raise typer.Exit(code=1)
    run_dir = root / run_id
    st = read_status(run_dir)
    write_status(
        run_dir,
        RunStatus(
            run_id=st.run_id,
            workflow_id=st.workflow_id,
            state="cancelled",
            step_id=st.step_id,
            started_at=st.started_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            last_error="cancelled by user",
            dirty=st.dirty,
        ),
    )
    # Cancelling an old run must not clear the pointer to a different run that is live.
    if get_current(root) == run_id:
        set_current(root, None)
    typer.echo(f"cancelled {run_id}")


@app.command("roles")
def roles_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    check: bool = typer.Option(False, "--check", help="Check roles configuration validity"),
):
    import json
    import shutil
    from aiwork.dispatch import (
        CLI_BY_AGENT,
        load_models_catalog,
        load_roles,
        validate_roles,
    )
    from aiwork.packs import find_role_definition, get_role_delivery_status

    try:
        roles, tables_meta = load_roles()
        catalog, _, _ = load_models_catalog()
    except Exception as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    errors, warnings = validate_roles(roles, catalog)

    if check:
        for w in warnings:
            typer.secho(f"Warning: {w}", fg=typer.colors.YELLOW)
        if errors:
            for err in errors:
                typer.secho(f"Error: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        typer.secho("Roles check passed.", fg=typer.colors.GREEN)
        return

    cli_status = {}
    delivery_status = {}
    for r_id, r in roles.items():
        cli_name = CLI_BY_AGENT.get(r.agent, r.agent)
        cli_status[r_id] = bool(shutil.which(cli_name))
        role_file = find_role_definition(r_id)
        defined_str, delivery_str = get_role_delivery_status(role_file)
        delivery_status[r_id] = (defined_str, delivery_str)

    if json_output:
        out = {
            "tables": {k: v.model_dump() for k, v in tables_meta.items()},
            "roles": {
                r_id: {
                    "agent": r.agent,
                    "model": r.model,
                    "effort": r.effort or "medium",
                    "description": r.description,
                    "source": r.source,
                    "cli": CLI_BY_AGENT.get(r.agent, r.agent),
                    "cli_in_path": cli_status[r_id],
                    "defined": delivery_status[r_id][0],
                    "delivery": delivery_status[r_id][1],
                }
                for r_id, r in roles.items()
            },
        }
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    for name, meta in tables_meta.items():
        typer.echo(f"Table ({name}): {meta.path} (sha256: {meta.sha256[:12]}...)")
    typer.echo()
    for r_id, r in sorted(roles.items()):
        cli_name = CLI_BY_AGENT.get(r.agent, r.agent)
        path_str = "in PATH" if cli_status[r_id] else "NOT in PATH"
        defined_str, delivery_str = delivery_status[r_id]
        typer.echo(f"Role: {r_id}")
        typer.echo(f"  Agent: {r.agent} ({cli_name}, {path_str})")
        typer.echo(f"  Model: {r.model}")
        typer.echo(f"  Effort: {r.effort or 'medium'}")
        typer.echo(f"  Source: {r.source}")
        typer.echo(f"  Description: {r.description}")
        typer.echo(f"  Defined: {defined_str}")
        typer.echo(f"  Delivery: {delivery_str}")


@app.command("models")
def models_cmd(
    check: bool = typer.Option(False, "--check", help="Check live CLI models against catalog"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    import json
    from aiwork.dispatch import check_models_catalog, load_models_catalog

    try:
        catalog, target_path, sha256 = load_models_catalog()
    except Exception as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if check:
        results = check_models_catalog(catalog)
        if json_output:
            typer.echo(json.dumps(results, indent=2, ensure_ascii=False))
            return
        for agent, res in sorted(results.items()):
            typer.secho(f"[{agent}]", bold=True)
            status = res.get("status")
            if status == "notice":
                typer.echo(f"  提示: {res.get('message')}")
            elif status == "error":
                typer.secho(f"  錯誤: {res.get('message')}", fg=typer.colors.RED)
            else:
                extra = res.get("extra_in_cli", [])
                missing = res.get("missing_in_cli", [])
                if not extra and not missing:
                    typer.secho(f"  已同步 (共 {res.get('total_catalog')} 個模型)", fg=typer.colors.GREEN)
                else:
                    if extra:
                        typer.secho(f"  CLI 有、清單沒有 ({len(extra)}):", fg=typer.colors.YELLOW)
                        for m in extra:
                            typer.echo(f"    + {m}")
                    if missing:
                        typer.secho(f"  清單有、CLI 沒有 ({len(missing)}):", fg=typer.colors.YELLOW)
                        for m in missing:
                            typer.echo(f"    - {m}")
        return

    if json_output:
        out = {
            "path": str(target_path),
            "sha256": sha256,
            "models": catalog,
        }
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    typer.echo(f"Models Catalog: {target_path} (sha256: {sha256[:12]}...)")
    for agent, mlist in sorted(catalog.items()):
        typer.echo(f"\n[{agent}] ({len(mlist)} models)")
        for m in mlist:
            typer.echo(f"  - {m}")


@app.command("rules-path")
def rules_path_cmd():
    from aiwork.resources import dispatch_rules_path

    try:
        p = dispatch_rules_path()
        if not p.is_file():
            typer.secho("dispatch-rules.md not found", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        typer.echo(str(p))
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


packs_app = typer.Typer(help="Manage, validate, apply, and undo packs")
app.add_typer(packs_app, name="packs")


@packs_app.command("list")
def packs_list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List packs in configured libraries and their enabled status."""
    from aiwork.packs import list_packs, load_machine_profile

    try:
        profile = load_machine_profile()
        packs = list_packs(libraries=profile.libraries)
    except Exception as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        out = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "enabled": p.id in profile.enabled_packs,
                "has_scripts": p.has_scripts,
                "items_count": len(p.items),
                "path": str(p.path) if p.path else "",
            }
            for p in packs
        ]
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    if not packs:
        typer.echo("No packs found in configured libraries:")
        for lib in profile.libraries:
            typer.echo(f"  - {lib}")
        return

    typer.echo(f"Found {len(packs)} pack(s) in libraries:")
    for p in packs:
        status_tag = (
            typer.style("[ENABLED]", fg=typer.colors.GREEN, bold=True)
            if p.id in profile.enabled_packs
            else typer.style("[DISABLED]", fg=typer.colors.WHITE)
        )
        scripts_tag = typer.style(" (has scripts)", fg=typer.colors.YELLOW) if p.has_scripts else ""
        typer.echo(f"\n{status_tag} {p.id} (v{p.version}){scripts_tag}")
        typer.echo(f"  Name: {p.name}")
        typer.echo(f"  Description: {p.description}")
        typer.echo(f"  Items: {len(p.items)} items")


@packs_app.command("validate")
def packs_validate_cmd(
    path: str = typer.Argument(..., help="Path to pack directory or zip file"),
):
    """Validate a pack directory structure or zip archive."""
    import tempfile
    from aiwork.packs import (
        PackSecurityError,
        PackValidationError,
        safe_extract_zip,
        validate_pack,
    )

    p = Path(path).resolve()
    if not p.exists():
        typer.secho(f"Path does not exist: {p}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        if p.is_file() and p.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory(prefix="aiwork_val_") as td:
                safe_extract_zip(p, td)
                pack = validate_pack(td)
        elif p.is_dir():
            pack = validate_pack(p)
        else:
            typer.secho(f"Target must be a directory or .zip file: {p}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
    except (PackValidationError, PackSecurityError) as exc:
        typer.secho(f"Validation failed:\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(f"Error during validation: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"[OK] Pack '{pack.id}' (v{pack.version}) is valid.", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  Name: {pack.name}")
    typer.echo(f"  Description: {pack.description}")
    typer.echo(f"  Items: {len(pack.items)} total")
    for item in pack.items:
        script_str = " (script)" if item.has_scripts else ""
        typer.echo(f"    - [{item.kind}] {item.name}{script_str}")


@packs_app.command("apply")
def packs_apply_cmd(
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Simulate apply (default: True)"),
    replace: bool = typer.Option(False, "--replace", help="Replace existing files and create backups"),
    pack_id: list[str] | None = typer.Option(None, "--pack", help="Specific pack ID(s) to apply (defaults to all enabled)"),
):
    """Apply packs to CLI environments. Defaults to dry-run."""
    from aiwork.packs import PackError, apply_packs, load_machine_profile

    try:
        profile = load_machine_profile()
        packs_to_apply = pack_id if pack_id else profile.enabled_packs
        if not packs_to_apply:
            typer.secho("No packs specified or enabled in machine.yaml.", fg=typer.colors.YELLOW)
            typer.echo("Enable a pack with 'aiwork packs enable <id>' or specify --pack <id>.")
            return

        result = apply_packs(packs=packs_to_apply, dry_run=dry_run, replace=replace, profile=profile)
    except PackError as exc:
        typer.secho(f"Apply failed:\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if dry_run:
        typer.secho("=== Dry Run Plan (no files modified) ===", bold=True)
        typer.echo(f"將新增 (to add): {len(result.plans['add'])}")
        for item in result.plans["add"]:
            typer.echo(f"  + [{item['kind']}] {item['target_path']} ({item['mode']})")
        typer.echo(f"將取代 (to replace): {len(result.plans['replace'])}")
        for item in result.plans["replace"]:
            typer.echo(f"  ~ [{item['kind']}] {item['target_path']} ({item['mode']})")
        typer.echo(f"衝突 (conflicts): {len(result.plans['conflicts'])}")
        for item in result.plans["conflicts"]:
            typer.secho(f"  ! {item['target_path']}: {item['reason']}", fg=typer.colors.RED)
        typer.echo(f"將建立目錄 (dirs to create): {len(result.plans['dirs_to_create'])}")
        for d in result.plans["dirs_to_create"]:
            typer.echo(f"  dir: {d}")

        if result.plans["conflicts"]:
            typer.secho("\nCannot apply due to conflicts. Resolve them or pass --replace if applicable.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
    else:
        typer.secho("[OK] Packs applied successfully.", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Total entries applied: {len(result.applied_entries)}")
        for entry in result.applied_entries:
            bak_info = f" (backup: {entry.backup_path})" if entry.backup_path else ""
            typer.echo(f"  - [{entry.mode}] {entry.target_path}{bak_info}")


@packs_app.command("undo")
def packs_undo_cmd(
    pack_id: list[str] | None = typer.Option(None, "--pack", help="Specific pack ID(s) to undo (defaults to all)"),
):
    """Restore applied packs based on applied manifest."""
    from aiwork.packs import PackError, undo_packs

    try:
        result = undo_packs(pack_ids=pack_id)
    except PackError as exc:
        typer.secho(f"Undo failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho("=== Packs Undo Summary ===", bold=True)
    typer.echo(f"已刪除 (removed): {len(result.removed)}")
    for r in result.removed:
        typer.echo(f"  - {r}")
    typer.echo(f"已還原備份 (restored): {len(result.restored)}")
    for r in result.restored:
        typer.echo(f"  - {r}")
    if result.modified:
        typer.secho(f"已手改保留 (modified, retained): {len(result.modified)}", fg=typer.colors.YELLOW)
        for r in result.modified:
            typer.echo(f"  ! {r}")
    if result.missing:
        typer.echo(f"未找到 (missing): {len(result.missing)}")


@packs_app.command("status")
def packs_status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show machine profile, enabled packs, manifest, and CLI directory status."""
    from aiwork.packs import packs_status

    try:
        st = packs_status()
    except Exception as exc:
        typer.secho(f"Failed to get status: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(st, indent=2, ensure_ascii=False))
        return

    typer.secho(f"Machine: {st['machine_name']} (scope: {st['scope']})", bold=True)
    typer.echo(f"Libraries: {', '.join(st['libraries'])}")
    typer.echo(f"Enabled packs: {', '.join(st['enabled_packs']) if st['enabled_packs'] else '(none)'}")
    typer.echo(f"Applied entries: {st['applied_count']} (manifest: {st['manifest_path']})")

    typer.secho("\n[CLI Directories]", bold=True)
    for name, info in st["cli_dirs"].items():
        link_str = " (junction/symlink)" if info.get("is_link") else ""
        exists_str = "exists" if info.get("exists") else "missing"
        typer.echo(f"  {name}: {info['path']} [{exists_str}]{link_str}")
        if info.get("exists") and info["realpath"] != info["path"]:
            typer.echo(f"    -> realpath: {info['realpath']}")

    if st["entries"]:
        typer.secho("\n[Applied Entries Status]", bold=True)
        for entry in st["entries"]:
            tag = typer.style(
                f"[{entry['status'].upper()}]",
                fg=typer.colors.GREEN if entry["status"] == "intact" else typer.colors.YELLOW,
            )
            typer.echo(f"  {tag} {entry['target_path']} ({entry['mode']}, pack: {entry['source_pack']})")


@packs_app.command("doctor")
def packs_doctor_cmd():
    """Check machine environment, git contamination, and manifest consistency."""
    from aiwork.packs import doctor_check

    try:
        checks = doctor_check()
    except Exception as exc:
        typer.secho(f"Doctor failed to run checks: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    has_errors = False
    typer.secho("=== Packs Environment & Health Check ===", bold=True)
    for c in checks:
        status = c.get("status", "ok")
        if status == "ok":
            tag = typer.style("[OK]", fg=typer.colors.GREEN, bold=True)
        elif status == "warning":
            tag = typer.style("[!]", fg=typer.colors.YELLOW, bold=True)
        elif status == "notice":
            tag = typer.style("[i]", fg=typer.colors.CYAN)
        else:
            tag = typer.style("[FAIL]", fg=typer.colors.RED, bold=True)
            has_errors = True
        typer.echo(f"{tag} {c['message']}")

    if has_errors:
        typer.secho("\nDoctor detected critical errors.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    else:
        typer.secho("\nDoctor check completed.", fg=typer.colors.GREEN)


@packs_app.command("enable")
def packs_enable_cmd(
    pack_id: str = typer.Argument(..., help="Pack ID to enable"),
):
    """Enable a pack in machine.yaml."""
    from aiwork.packs import enable_pack

    enable_pack(pack_id)
    typer.secho(f"Pack '{pack_id}' enabled.", fg=typer.colors.GREEN)


@packs_app.command("disable")
def packs_disable_cmd(
    pack_id: str = typer.Argument(..., help="Pack ID to disable"),
):
    """Disable a pack in machine.yaml."""
    from aiwork.packs import disable_pack

    disable_pack(pack_id)
    typer.secho(f"Pack '{pack_id}' disabled.", fg=typer.colors.YELLOW)


@packs_app.command("probe")
def packs_probe_cmd(
    agent: str | None = typer.Option(
        None, "--agent", help="Probe a specific agent CLI (cursor, claude, gemini)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Probe agent CLIs to verify role prompt delivery."""
    from aiwork.packs import run_probe

    if agent and agent not in ("cursor", "claude", "gemini"):
        typer.secho(f"Invalid agent '{agent}'. Choose from cursor, claude, gemini.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        results = run_probe(agent=agent)
    except Exception as exc:
        typer.secho(f"Probe execution failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(results, indent=2, ensure_ascii=False))
        return

    typer.secho("=== Packs Probe Results ===", bold=True)
    res_map = results.get("results", results)
    for ag_id, r in res_map.items():
        if ag_id in ("updated_at", "timestamp"):
            continue
        if not isinstance(r, dict):
            continue
        label = r.get("label", r.get("status", "unknown"))
        model_str = f" ({r['model']})" if r.get("model") else ""
        if r.get("passed"):
            tag = typer.style("[OK]", fg=typer.colors.GREEN, bold=True)
        elif r.get("status") == "not_logged_in":
            tag = typer.style("[!]", fg=typer.colors.YELLOW, bold=True)
        elif r.get("status") == "missing":
            tag = typer.style("[-]", fg=typer.colors.WHITE)
        else:
            tag = typer.style("[FAIL]", fg=typer.colors.RED, bold=True)
        detail = f" - {r['detail']}" if r.get("detail") else ""
        typer.echo(f"  {tag} {ag_id}{model_str}: {label}{detail}")


if __name__ == "__main__":
    app()


