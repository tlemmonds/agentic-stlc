"""Kane recorder — authors a new _test.md from a free-text objective.

This is the "slow path": Kane plans and executes a test from scratch, then
the resulting steps are persisted as a markdown asset that future runs
replay (kane_replay.py) without re-planning.

Strategy: prefer Kane's own --name auto-save when present. If the headless
agent mode does not write the asset to disk (the docs only confirm TUI
auto-save), fall back to synthesizing a _test.md from the captured run.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
KANE_TUI_TESTS_DIR = REPO_ROOT / ".testmuai" / "tests"

EXIT_STATUS = {0: "passed", 1: "failed", 2: "error", 3: "timeout"}


def _kane_exe() -> str:
    exe = shutil.which("kane-cli")
    if exe is None and sys.platform == "win32":
        exe = shutil.which("kane-cli.cmd")
    return exe or "kane-cli"


def _slugify(value: str) -> str:
    """Slug for kane-cli --name; spec is [a-zA-Z0-9_-]+."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug[:60] or "scenario"


def _build_caps(session_name: str, build_name: str, *, username: str, access_key: str) -> str:
    playwright_version = ""
    try:
        result = subprocess.run(
            ["playwright", "--version"], capture_output=True, text=True, check=False
        )
        parts = result.stdout.strip().split()
        playwright_version = parts[1] if len(parts) >= 2 else ""
    except Exception:
        pass
    caps = {
        "browserName": "Chrome",
        "browserVersion": "latest",
        "LT:Options": {
            "platform": "Windows 10",
            "build": build_name,
            "name": session_name,
            "user": username,
            "accessKey": access_key,
            "network": True,
            "video": True,
            "console": True,
            "tunnel": False,
            "tunnelName": "",
            "playwrightClientVersion": playwright_version,
        },
    }
    return (
        "wss://cdp.lambdatest.com/playwright?capabilities="
        + urllib.parse.quote(json.dumps(caps))
    )


def record(
    objective: str,
    *,
    sc_id: str,
    requirement_id: str,
    description: str,
    description_hash: str,
    feature: str,
    asset_path: Path,
    build_name: str,
    username: str,
    access_key: str,
    timeout_seconds: int = 180,
    code_export_dir: Path | None = None,
) -> dict[str, Any]:
    """Author a Kane session for the given objective and persist it as
    asset_path. Returns a result dict matching run_kane()'s shape so the
    Stage 1 dispatcher can consume it uniformly."""

    if not username or not access_key:
        return {
            "status": "skipped",
            "summary": "LT credentials not available — cannot record",
            "one_liner": "", "steps": [], "final_state": {},
            "duration": None, "test_url": "",
            "session_id": "", "code_export_dir": "",
            "asset_written": False,
        }

    cli = _kane_exe()
    name_slug = _slugify(f"{sc_id}_{asset_path.stem.replace('_test', '')}")
    session_name = f"Record {sc_id} | {description[:60].strip()}"
    ws_endpoint = _build_caps(session_name, build_name, username=username, access_key=access_key)

    command = [
        cli, "run", objective,
        "--name", name_slug,
        "--username", username,
        "--access-key", access_key,
        "--ws-endpoint", ws_endpoint,
        "--agent",
        "--headless",
        "--timeout", str(timeout_seconds),
        "--max-steps", "30",
    ]
    if code_export_dir is not None:
        code_export_dir.mkdir(parents=True, exist_ok=True)
        command.extend(["--code-export", "--code-language", "python", "--skip-code-validation"])

    started = time.time()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            timeout=timeout_seconds + 60,  # see kane_replay.py for rationale
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "summary": f"kane-cli run wedged past {timeout_seconds + 60}s — killed",
            "one_liner": "", "steps": [], "final_state": {},
            "duration": round(time.time() - started, 2),
            "test_url": "", "session_id": "",
            "code_export_dir": str(code_export_dir) if code_export_dir else "",
            "asset_written": False,
        }
    duration = time.time() - started
    parsed = _parse_kane_output(completed, duration, code_export_dir)

    asset_written = _persist_asset(
        asset_path=asset_path,
        sc_id=sc_id,
        requirement_id=requirement_id,
        description=description,
        description_hash=description_hash,
        feature=feature,
        objective=objective,
        kane_result=parsed,
        name_slug=name_slug,
    )
    parsed["asset_written"] = asset_written
    parsed["asset_path"] = str(asset_path)
    return parsed


def _persist_asset(
    *,
    asset_path: Path,
    sc_id: str,
    requirement_id: str,
    description: str,
    description_hash: str,
    feature: str,
    objective: str,
    kane_result: dict[str, Any],
    name_slug: str,
) -> bool:
    """Try Kane's TUI auto-save first; if that file isn't there, synthesize
    one from the run we just captured. Returns True if asset_path now exists.
    """
    asset_path.parent.mkdir(parents=True, exist_ok=True)

    # Path 1: Kane wrote the asset itself (TUI behavior; may also fire in
    # newer agent-mode versions). Look in .testmuai/tests/<slug>_test.md and
    # in the per-session sessions dir.
    candidates = [
        KANE_TUI_TESTS_DIR / f"{name_slug}_test.md",
    ]
    session_id = kane_result.get("session_id", "")
    if session_id:
        candidates.append(Path.home() / ".testmuai" / "kaneai" / "sessions" / session_id / f"{name_slug}_test.md")
        candidates.append(Path.home() / ".testmuai" / "kaneai" / "sessions" / session_id / "test.md")

    for candidate in candidates:
        if candidate.exists():
            shutil.copyfile(candidate, asset_path)
            _inject_metadata_block(
                asset_path,
                sc_id=sc_id,
                requirement_id=requirement_id,
                description=description,
                description_hash=description_hash,
                feature=feature,
                objective=objective,
            )
            return True

    # Path 2: synthesize a minimal _test.md from the parsed Kane run.
    body = _synthesize_test_md(
        sc_id=sc_id,
        requirement_id=requirement_id,
        description=description,
        description_hash=description_hash,
        feature=feature,
        objective=objective,
        steps=kane_result.get("steps", []) or [],
        one_liner=kane_result.get("one_liner", ""),
        summary=kane_result.get("summary", ""),
        kane_session_id=kane_result.get("session_id", ""),
        kane_test_url=kane_result.get("test_url", ""),
    )
    asset_path.write_text(body, encoding="utf-8")
    return asset_path.exists()


_SECRETS_FIELDS = {
    # Auth-bearing fields Kane embeds in the saved asset's frontmatter that
    # would leak if the file were committed to git. The endpoint URL contains
    # an URL-encoded access_key.
    "ws_endpoint", "wsendpoint",
    "cdp_endpoint", "cdpendpoint",
    "username", "user",
    "access_key", "accesskey",
}


def _strip_keys(frontmatter_lines: list[str], keys_lower: set[str]) -> list[str]:
    """Drop top-level YAML keys (and any indented continuation lines such as
    `>-` block scalars) whose name appears in keys_lower."""
    result = []
    skip_continuation = False
    for line in frontmatter_lines:
        if skip_continuation:
            if line.startswith((" ", "\t")) or line.lstrip().startswith(">"):
                continue
            skip_continuation = False
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if m and m.group(1).lower() in keys_lower:
            skip_continuation = True
            continue
        result.append(line)
    return result


def _scrub_asset_secrets(asset_path: Path) -> None:
    """Remove auth-bearing fields from the asset's frontmatter so the file
    is safe to commit. Kane CLI 0.3.1 owns the rest of the schema and
    rejects unknown keys, so we ONLY strip — never add."""
    text = asset_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    end = text.find("\n---", 3)
    if end == -1:
        return
    head_lines = text[3:end].strip("\n").splitlines()
    cleaned = _strip_keys(head_lines, _SECRETS_FIELDS)
    if cleaned == head_lines:
        return  # nothing to strip
    tail = text[end + 4:].lstrip("\n")
    rebuilt = "---\n" + "\n".join(cleaned) + ("\n" if cleaned else "") + "---\n" + tail
    asset_path.write_text(rebuilt, encoding="utf-8")


def _write_metadata_sidecar(
    asset_path: Path,
    *,
    sc_id: str,
    requirement_id: str,
    description: str,
    description_hash: str,
    feature: str,
    objective: str,
) -> None:
    """Write a sidecar `<asset>.meta.json` carrying the pipeline-specific
    metadata (sc_id, hash, etc) that doesn't fit in Kane's strict
    frontmatter schema. Stage 1 + replay_policy read from this file."""
    sidecar = asset_path.with_suffix(".meta.json")
    payload = {
        "sc_id": sc_id,
        "requirement_id": requirement_id,
        "feature": feature,
        "description_hash": description_hash,
        "description": description,
        "objective": objective,
        "asset": asset_path.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# Backwards-compatible alias — older callers use _inject_metadata_block.
def _inject_metadata_block(asset_path: Path, **kwargs) -> None:
    _scrub_asset_secrets(asset_path)
    _write_metadata_sidecar(asset_path, **kwargs)


def _synthesize_test_md(
    *,
    sc_id: str,
    requirement_id: str,
    description: str,
    description_hash: str,
    feature: str,
    objective: str,
    steps: list[str],
    one_liner: str,
    summary: str,
    kane_session_id: str,
    kane_test_url: str,
) -> str:
    """Fallback _test.md body when Kane didn't auto-persist. Uses ## headings
    per-step so kane-cli replay treats each as a discrete objective."""
    title = one_liner or description[:80]
    lines = [
        "---",
        f'sc_id: "{sc_id}"',
        f'requirement_id: "{requirement_id}"',
        f'feature: "{feature}"',
        f'description_hash: "{description_hash}"',
        f'title: "{title.replace(chr(34), chr(39))}"',
        "description: |",
        f"  {description}",
        "objective: |",
        *("  " + line for line in objective.splitlines()),
        f'recorded_session_id: "{kane_session_id}"',
        f'recorded_session_url: "{kane_test_url}"',
        f'recorded_at: "{datetime.now(timezone.utc).isoformat()}"',
        "---",
        "",
        f"# {sc_id} — {title}",
        "",
        "> Generated from a Kane recording run. Re-record by deleting this file or",
        "> by setting `FORCE_RE_AUTHOR=true`. The pipeline will replay this asset",
        "> on every subsequent run until the AC description changes.",
        "",
    ]
    if not steps:
        lines.extend([
            "## Step 1 — Execute objective",
            "",
            objective.strip(),
            "",
        ])
    else:
        for i, step in enumerate(steps, start=1):
            lines.append(f"## Step {i}")
            lines.append("")
            lines.append(step.strip())
            lines.append("")
    if summary:
        lines.extend([
            "## Recording summary",
            "",
            summary.strip(),
            "",
        ])
    return "\n".join(lines)


_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _parse_kane_output(completed: subprocess.CompletedProcess, duration: float, code_export_dir: Path | None) -> dict[str, Any]:
    """Same parser as kane_replay._parse_kane_output — duplicated to keep
    these modules independent."""
    exit_status = EXIT_STATUS.get(completed.returncode, "error")
    combined = completed.stdout + "\n" + completed.stderr

    run_end: dict | None = None
    step_summaries: list[str] = []
    session_id = ""
    discovered_export_dir = ""

    for raw in combined.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            event = None
        if event is not None:
            event_type = event.get("type", "")
            if event_type in ("step_end", "stepEnd") and event.get("summary"):
                step_summaries.append(event["summary"])
            elif event_type in ("run_end", "runEnd"):
                run_end = event
                session_id = (
                    event.get("session_id")
                    or event.get("sessionId")
                    or event.get("data", {}).get("session_id", "")
                    or ""
                )
            elif event_type in ("code_export", "codeExport"):
                raw_path = event.get("path") or event.get("directory") or ""
                if raw_path:
                    discovered_export_dir = raw_path
            if not session_id:
                session_id = event.get("session_id") or event.get("sessionId") or ""
            continue
        if not session_id and "sessions" in stripped.lower():
            m = _UUID_RE.search(stripped)
            if m:
                session_id = m.group(0)

    if not run_end:
        return {
            "status": exit_status,
            "summary": combined.strip()[:500] or "Kane CLI produced no output.",
            "one_liner": "", "steps": step_summaries, "final_state": {},
            "duration": round(duration, 2), "test_url": "",
            "session_id": session_id,
            "code_export_dir": discovered_export_dir or (str(code_export_dir) if code_export_dir else ""),
        }
    return {
        "status": run_end.get("status", exit_status),
        "summary": run_end.get("summary", ""),
        "one_liner": run_end.get("one_liner", ""),
        "steps": step_summaries,
        "final_state": run_end.get("final_state", {}),
        "duration": run_end.get("duration") or round(duration, 2),
        "test_url": run_end.get("test_url", ""),
        "session_id": session_id,
        "code_export_dir": discovered_export_dir or (str(code_export_dir) if code_export_dir else ""),
    }
