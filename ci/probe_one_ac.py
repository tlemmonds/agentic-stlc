"""Diagnostic probe: invoke Kane for ONE AC with live streaming output.

Bypasses the dispatcher and thread pool entirely so we can observe Kane's
actual behavior on a single recording — does it start, does it print
progress, does it hang at a specific phase, does --timeout get respected?

Usage: python ci/probe_one_ac.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ci"))
from kane_record import _kane_exe, _build_caps, _slugify

SC_ID = "SC-001"
DESCRIPTION = "User can create a task with a title and a due date"
TARGET_URL = "https://nosecretformula.vercel.app/"
OBJECTIVE = f"On {TARGET_URL} — {DESCRIPTION}"
NAME_SLUG = _slugify(f"{SC_ID}_user_can_create_a_task_with_a_title_and_a_due_date")
TIMEOUT_SEC = 300
WALL_TIMEOUT = 420  # subprocess.run timeout = Kane --timeout + 2 min slack

USERNAME = os.environ["LT_USERNAME"]
ACCESS_KEY = os.environ["LT_ACCESS_KEY"]
BUILD_NAME = f"Agentic STLC probe | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
SESSION_NAME = f"Probe {SC_ID} | {DESCRIPTION[:60]}"

ws_endpoint = _build_caps(SESSION_NAME, BUILD_NAME, username=USERNAME, access_key=ACCESS_KEY)
cli = _kane_exe()

cmd = [
    cli, "run", OBJECTIVE,
    "--name", NAME_SLUG,
    "--username", USERNAME,
    "--access-key", ACCESS_KEY,
    "--ws-endpoint", ws_endpoint,
    "--agent",
    "--headless",
    "--timeout", str(TIMEOUT_SEC),
    "--max-steps", "30",
]

print(f"[probe] cli={cli}", flush=True)
print(f"[probe] objective={OBJECTIVE}", flush=True)
print(f"[probe] name_slug={NAME_SLUG}", flush=True)
print(f"[probe] starting kane-cli (kane --timeout={TIMEOUT_SEC}s, wall={WALL_TIMEOUT}s)", flush=True)
print(f"[probe] elapsed=0s — launching subprocess", flush=True)

start = time.time()
try:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
except FileNotFoundError as exc:
    print(f"[probe] FATAL: {exc}", flush=True)
    sys.exit(2)

print(f"[probe] subprocess pid={proc.pid}", flush=True)
print("[probe] --- KANE LIVE OUTPUT BELOW ---", flush=True)

deadline = start + WALL_TIMEOUT
try:
    for line in proc.stdout:
        elapsed = time.time() - start
        line = line.rstrip()
        if not line:
            continue
        print(f"[+{elapsed:6.1f}s] {line}", flush=True)
        if time.time() > deadline:
            print(f"[probe] WALL TIMEOUT — killing", flush=True)
            proc.kill()
            break
    rc = proc.wait(timeout=10)
    print(f"[probe] subprocess exited rc={rc} after {time.time()-start:.1f}s", flush=True)
except KeyboardInterrupt:
    print("[probe] interrupted — killing", flush=True)
    proc.kill()
    sys.exit(130)

testmuai_dir = REPO_ROOT / ".testmuai" / "tests"
if testmuai_dir.exists():
    artifacts = sorted(testmuai_dir.iterdir())
    print(f"[probe] .testmuai/tests/ contains {len(artifacts)} entries:", flush=True)
    for a in artifacts:
        print(f"  {a.name}", flush=True)
else:
    print("[probe] .testmuai/tests/ does not exist", flush=True)
