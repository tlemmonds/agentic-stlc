"""Run one staged testmu Playwright export and emit the framework's result artifacts.

Framework-owned. Stage 3a (ci/collect_kane_exports.py) stages every
`export_kind == "testmu"` scenario verbatim into tests/playwright/native/<sc_id_lower>/
(test.py + requirements.txt). Those exports are generated code — `kane-cli testmd
export` rewrites test.py wholesale — and they use the async `testmu` SDK, so they
can't be embedded into the sync conftest. The reporting shim therefore lives here,
one level above the staged folders, where a re-export cannot clobber it.

Contract (ci/run_selected.py does `cd tests/playwright/native/<sc_id_lower>` first):
  cwd            tests/playwright/native/<sc_id_lower>   (sc_013 → SC-013)
  runs           python test.py   with TESTMU_HEADLESS=true (existing env respected)
  writes         reports/native_<SC-ID>.xml               JUnit, testcase name = SC-ID, classname = "native"
                 reports/kane_result_<SC-ID>_chrome.json  same schema conftest.py writes, source = "native"
  exit code      the test's exit code (77 = skip sentinel from the collect-time stub → exit 0)

Both artifacts are written even when test.py crashes on import (e.g. `testmu` not
installed) so Stage 6 resolves the scenario to `failed` rather than `data_unavailable`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

SKIP_EXIT_CODE = 77          # written by the collect-time stub when the export was missing
BROWSER = "chrome"           # testmu exports drive their own (chromium) session
LT_BROWSER = "Chrome"
OUTPUT_TAIL = 8000           # JUnit failure body — tail, the traceback is at the end
ERROR_TAIL = 500             # matches conftest's longrepr[:500]

HERE = Path(__file__).resolve().parent                # tests/playwright/native
REPO_ROOT = HERE.parent.parent.parent                 # repo root
REPORTS = REPO_ROOT / "reports"

_LINK_RE = re.compile(r"https?://[\w.-]*lambdatest\.com/[^\s'\"<>]+")


def _sc_id_from_folder(folder: str) -> str:
    """sc_013 → SC-013. Anything else is upper-cased with '_' → '-' as a best effort."""
    m = re.fullmatch(r"sc[_-](\d+)", folder, re.IGNORECASE)
    if m:
        return f"SC-{int(m.group(1)):03d}"
    return folder.upper().replace("_", "-")


def _build_name() -> str:
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"Agentic STLC #{run_number} | {today}" if run_number else f"Agentic STLC | {today}"


def _requirement_id(sc_id: str) -> str:
    """Best-effort lookup in scenarios/scenarios.json; '' when unavailable."""
    try:
        data = json.loads((REPO_ROOT / "scenarios" / "scenarios.json").read_text(encoding="utf-8"))
        for sc in data:
            if isinstance(sc, dict) and sc.get("id") == sc_id:
                return sc.get("requirement_id") or ""
    except Exception:
        pass
    return ""


def _run_test(env: dict) -> tuple[int, str]:
    """Stream test.py's combined output to stdout while capturing it."""
    proc = subprocess.Popen(
        [sys.executable, "test.py"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    chunks: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        chunks.append(line)
    proc.wait()
    return proc.returncode, "".join(chunks)


def _write_junit(sc_id: str, status: str, duration: float, message: str, output: str) -> Path:
    if status == "failed":
        body = "    <failure message={}>{}</failure>\n".format(quoteattr(message), escape(output[-OUTPUT_TAIL:]))
    elif status == "skipped":
        body = "    <skipped message={}/>\n".format(quoteattr(message))
    else:
        body = ""
    path = REPORTS / f"native_{sc_id}.xml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuite name="native" tests="1" failures="{failures}" errors="0" skipped="{skipped}" time="{time:.3f}">\n'
        '  <testcase classname="native" name={name} time="{time:.3f}">\n'
        '{body}'
        '  </testcase>\n'
        '</testsuite>\n'.format(
            failures=1 if status == "failed" else 0,
            skipped=1 if status == "skipped" else 0,
            time=duration,
            name=quoteattr(sc_id),
            body=body,
        ),
        encoding="utf-8",
    )
    return path


def _write_result_json(sc_id: str, status: str, start: datetime, end: datetime,
                       duration_ms: int, error_message: str | None, session_link: str) -> Path:
    tc_id = f"TC-{sc_id.split('-')[1]}" if "-" in sc_id else "TC-000"
    build = _build_name()
    record = {
        "requirement_id": _requirement_id(sc_id) or "unknown",
        "scenario_id": sc_id,
        "test_case_id": tc_id,
        "function_name": "test.py",
        "browser": BROWSER,
        "lt_browser": LT_BROWSER,
        "status": status,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_ms": duration_ms,
        "error_message": error_message,
        "session_name": f"{sc_id} | {tc_id} | native | {BROWSER}",
        "session_link": session_link,
        "build": build,
        "source": "native",
    }
    path = REPORTS / f"kane_result_{sc_id}_{BROWSER}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def main() -> int:
    cwd = Path.cwd()
    sc_id = _sc_id_from_folder(cwd.name)
    REPORTS.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.setdefault("TESTMU_HEADLESS", "true")
    env.setdefault("PYTHONUNBUFFERED", "1")

    print(f"[native] {sc_id}: running {cwd / 'test.py'} (TESTMU_HEADLESS={env['TESTMU_HEADLESS']})")
    start = datetime.now(timezone.utc)
    start_mono = time.monotonic()

    if not (cwd / "test.py").is_file():
        rc, output = 2, f"[native] {sc_id}: test.py not found in {cwd}\n"
        sys.stdout.write(output)
    else:
        rc, output = _run_test(env)

    duration = time.monotonic() - start_mono
    end = datetime.now(timezone.utc)
    duration_ms = round(duration * 1000)

    if rc == 0:
        status, message, error_message = "passed", "", None
    elif rc == SKIP_EXIT_CODE:
        status, message, error_message = "skipped", "skipped by native stub (export missing)", None
    else:
        status = "failed"
        message = f"exit code {rc}"
        tail = output.strip()[-ERROR_TAIL:]
        error_message = f"{message}: {tail}" if tail else message

    link_match = _LINK_RE.search(output)
    session_link = link_match.group(0) if link_match else ""

    xml_path = _write_junit(sc_id, status, duration, message, output)
    json_path = _write_result_json(sc_id, status, start, end, duration_ms, error_message, session_link)
    print(f"[native] {sc_id}: {status.upper()} in {duration_ms} ms (exit {rc}) -> "
          f"{xml_path.relative_to(REPO_ROOT).as_posix()}, {json_path.relative_to(REPO_ROOT).as_posix()}")

    # Propagate the verdict — HyperExecute gates the task on the exit code. A skip is not a failure.
    return 0 if status == "skipped" else rc


if __name__ == "__main__":
    sys.exit(main())
