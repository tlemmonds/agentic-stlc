"""Kane replay runner — executes a saved _test.md asset against the AUT.

Replay is the "fast path" of the new architecture: Kane re-walks the recorded
steps without re-planning, so each run consumes very few tokens. Token cost
is only paid during recording (kane_record.py).

Returns the same shape as analyze_requirements.py's run_kane(), so it can
be a drop-in replacement at the dispatch layer.
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
sys.path.insert(0, str(Path(__file__).parent))
import project_config  # noqa: E402  (kaneai.adaptive_heal)

# Mirror of the EXIT_STATUS map in analyze_requirements.py — kept local so
# this module stays self-contained.
EXIT_STATUS = {0: "passed", 1: "failed", 2: "error", 3: "timeout"}

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _kane_exe() -> str:
    """Resolve the kane-cli launcher (Windows ships the .cmd shim)."""
    exe = shutil.which("kane-cli")
    if exe is None and sys.platform == "win32":
        exe = shutil.which("kane-cli.cmd")
    return exe or "kane-cli"


def _build_caps(session_name: str, build_name: str, *, username: str, access_key: str) -> str:
    """Build the LambdaTest Playwright caps URL — same pattern as
    analyze_requirements.run_kane()."""
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


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def _frontmatter_int(asset_path: Path, key: str) -> int | None:
    """Read an integer key (max_steps, timeout) from the asset's YAML frontmatter, if any."""
    try:
        m = _FM_RE.match(asset_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not m:
        return None
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() == key:
            try:
                return int(v.strip())
            except ValueError:
                return None
    return None


def _effective_timeout(asset_path: Path, pipeline_timeout: int) -> int:
    """Never cut an asset shorter than its own declared timeout."""
    declared = _frontmatter_int(asset_path, "timeout")
    return max(pipeline_timeout, declared or 0)


def replay(
    asset_path: Path,
    *,
    session_name: str,
    build_name: str,
    username: str,
    access_key: str,
    timeout_seconds: int = 180,
    variables_file: Path | None = None,
    code_export_dir: Path | None = None,
) -> dict[str, Any]:
    """Replay a saved _test.md and return a dict matching run_kane()'s shape.

    code_export_dir: when provided, Kane writes a Python Playwright export
    into that directory. Used by Stage 3 to derive the regression test.
    """
    if not asset_path.exists():
        return _make_skipped_result(f"asset not found: {asset_path}")

    if not username or not access_key:
        return _make_skipped_result("LT credentials not available")

    ws_endpoint = _build_caps(session_name, build_name, username=username, access_key=access_key)
    cli = _kane_exe()
    # Kane CLI 0.3.1 split test.md replay onto its own subcommand:
    #   kane-cli testmd run <path>     ← replay
    #   kane-cli run "<objective>"     ← inline authoring (used by kane_record.py)
    command = [
        cli, "testmd", "run", str(asset_path),
        "--username", username,
        "--access-key", access_key,
        "--ws-endpoint", ws_endpoint,
        "--agent",
        "--headless",
        "--timeout", str(_effective_timeout(asset_path, timeout_seconds)),
    ]
    # Ingested assets declare their own step budget in frontmatter (everdemo:
    # 30–80). Only impose the pipeline default when the asset is silent.
    if _frontmatter_int(asset_path, "max_steps") is None:
        command += ["--max-steps", os.environ.get("KANE_REPLAY_MAX_STEPS", "30")]
    command += [
        # Note: --retry and --on-lock-conflict were removed because Kane 0.3.1
        # on Windows rejects them with "--retry requires basic auth credentials
        # for the lock API" even when --username/--access-key are passed
        # inline. Pipeline-level retry happens via re-record on hash drift, and
        # each worker writes to its own per-sc output dir so lock collisions
        # don't occur in practice.
    ]
    if variables_file is not None and variables_file.exists():
        command.extend(["--variables-file", str(variables_file)])
    if code_export_dir is not None:
        code_export_dir.mkdir(parents=True, exist_ok=True)
        command.extend(["--code-export", "--code-language", "python", "--skip-code-validation"])
    # A replay miss is a finding, not something to heal silently — unless the
    # project opts in via `kaneai.adaptive_heal: true`.
    if not project_config.adaptive_heal():
        command.append("--no-adaptive-heal")

    started = time.time()
    # Subprocess-level timeout = Kane's --timeout + a 60s safety margin so
    # a hung CLI doesn't pin a worker thread forever (the smoke-test on
    # 2026-05-15 ran for an hour with --timeout=180 set on Kane itself,
    # confirming Kane can ignore its own timeout flag).
    #
    # cwd=REPO_ROOT so kane-cli auto-loads `{cwd}/.testmuai/variables/*.json`
    # and resolves the asset's sibling `output-<stem>/` sidecar (TMS reuse).
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            timeout=_effective_timeout(asset_path, timeout_seconds) + 60,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "summary": f"kane-cli testmd run wedged past {timeout_seconds + 60}s — killed by subprocess.TimeoutExpired",
            "one_liner": "", "steps": [], "final_state": {},
            "duration": round(time.time() - started, 2),
            "test_url": "", "session_id": "",
            "code_export_dir": str(code_export_dir) if code_export_dir else "",
        }
    duration = time.time() - started
    return _parse_kane_output(completed, duration, code_export_dir)


def _make_skipped_result(message: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "summary": message,
        "one_liner": "",
        "steps": [],
        "final_state": {},
        "duration": None,
        "test_url": "",
        "session_id": "",
        "code_export_dir": "",
    }


def _parse_kane_output(completed: subprocess.CompletedProcess, duration: float, code_export_dir: Path | None) -> dict[str, Any]:
    """Parse Kane's NDJSON + plain-text output into the run_kane() result
    shape. This is a deliberate copy of the parsing logic in
    analyze_requirements.run_kane() so kane_replay can be a drop-in
    substitute without importing back into that module."""
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
        diagnostic = combined.strip()[:500] or "Kane CLI produced no output."
        return {
            "status": exit_status,
            "summary": diagnostic,
            "one_liner": "",
            "steps": step_summaries,
            "final_state": {},
            "duration": round(duration, 2),
            "test_url": "",
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


def main() -> int:
    """CLI: replay a single _test.md and print the parsed result."""
    if len(sys.argv) < 2:
        print("usage: kane_replay.py <path/to/foo_test.md>", file=sys.stderr)
        return 2
    asset = Path(sys.argv[1]).resolve()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "")
    build_name = f"Agentic STLC #{run_number} | {today}" if run_number else f"Agentic STLC | {today}"

    result = replay(
        asset,
        session_name=f"Replay | {asset.name}",
        build_name=build_name,
        username=os.environ.get("LT_USERNAME", ""),
        access_key=os.environ.get("LT_ACCESS_KEY", ""),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
