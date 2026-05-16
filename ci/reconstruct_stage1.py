"""Recover Stage 1 outputs from completed Kane recordings on disk.

Used when ci/analyze_requirements.py's wrapper hangs on subprocess teardown
even though Kane already finished and persisted assets under .testmuai/tests/.
Picks the best-status recording per SC, copies the _test.md into the
pipeline asset dir, writes the meta.json sidecar, and emits
analyzed_requirements.json so Stages 2-7 can proceed.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ci"))
from replay_policy import asset_path_for, hash_description
from kane_record import _scrub_asset_secrets

TESTMUAI = REPO_ROOT / ".testmuai" / "tests"
REQUIREMENTS = REPO_ROOT / "requirements" / "taskflow.txt"
TARGET_URL = "https://nosecretformula.vercel.app/"
TODAY = datetime.now(timezone.utc).date().isoformat()

STATUS_RANK = {"passed": 3, "failed": 2, "timeout": 1, "error": 0}


def parse_requirements() -> list[str]:
    """Pull AC lines from taskflow.txt — everything after 'Acceptance Criteria:'."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    in_acs = False
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not in_acs:
            if s.lower().startswith("acceptance criteria"):
                in_acs = True
            continue
        if s and not s.startswith("#"):
            lines.append(s)
    return lines


def parse_result_md(result_path: Path) -> dict:
    """Pull status / duration_s / session_id from the YAML frontmatter."""
    text = result_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def discover_recordings() -> dict[int, dict]:
    """Index recordings under .testmuai/tests/ keyed by SC index (1..6).

    Returns one chosen recording per SC, but with the test_md picked by
    best status (passed > failed) and the code_dir picked independently
    by whichever attempt actually emitted Playwright code (Kane only
    exports on first authoring runs, not re-records, so the highest-status
    re-record may have no code_dir while the first failed attempt does).
    """
    by_sc: dict[int, list[dict]] = {}
    for output_dir in TESTMUAI.glob("output-SC-*"):
        m = re.match(r"output-SC-(\d{3})_", output_dir.name)
        if not m:
            continue
        idx = int(m.group(1))
        result_md = output_dir / "Result.md"
        if not result_md.exists():
            continue
        meta = parse_result_md(result_md)
        sibling = TESTMUAI / (output_dir.name[len("output-"):] + "_test.md")
        if not sibling.exists():
            continue
        code_dir = output_dir / "playwright-python-code"
        has_code = (code_dir / "test.py").exists()
        by_sc.setdefault(idx, []).append({
            "test_md": sibling,
            "result_md": result_md,
            "code_dir": code_dir,
            "has_code": has_code,
            "status": meta.get("status", "error"),
            "duration_s": float(meta.get("duration_s", "0") or 0),
            "session_id": meta.get("session_id", ""),
            "started": meta.get("started", ""),
        })

    chosen = {}
    for idx, recs in by_sc.items():
        # Pick the test_md by best status (ties: most recent).
        by_status = sorted(
            recs,
            key=lambda r: (STATUS_RANK.get(r["status"], 0), r["started"]),
            reverse=True,
        )
        primary = dict(by_status[0])
        # Pick code_dir independently: prefer passed+has_code, else any has_code,
        # else fall back to primary's (possibly missing) code_dir.
        with_code = [r for r in recs if r["has_code"]]
        if with_code:
            with_code.sort(
                key=lambda r: (STATUS_RANK.get(r["status"], 0), r["started"]),
                reverse=True,
            )
            primary["code_dir"] = with_code[0]["code_dir"]
            primary["has_code"] = True
        chosen[idx] = primary
    return chosen


def copy_asset(idx: int, description: str, recording: dict) -> Path:
    """Copy the recorded _test.md into tests/kane/general/ and write sidecar."""
    sc_id = f"SC-{idx:03d}"
    title_for_path = description
    target = asset_path_for(sc_id, "general", title_for_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(recording["test_md"], target)
    _scrub_asset_secrets(target)  # Kane's auto-saved frontmatter embeds the LT access key

    sidecar = target.with_suffix(".meta.json")
    sidecar.write_text(json.dumps({
        "sc_id": sc_id,
        "requirement_id": f"AC-{idx:03d}",
        "feature": "general",
        "description_hash": hash_description(description),
        "description": description,
        "objective": f"On {TARGET_URL} — {description}",
        "asset": target.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "recorded_session_id": recording["session_id"],
    }, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    descriptions = parse_requirements()
    recordings = discover_recordings()

    out: list[dict] = []
    for i, desc in enumerate(descriptions, start=1):
        rec = recordings.get(i)
        ac_id = f"AC-{i:03d}"
        if rec is None:
            out.append({
                "id": ac_id,
                "title": desc[:40],
                "description": desc,
                "url": TARGET_URL,
                "kane_status": "skipped",
                "kane_one_liner": "",
                "kane_summary": "no recording found on disk",
                "kane_steps": [],
                "kane_final_state": {},
                "kane_duration": None,
                "kane_links": [],
                "kane_session_id": "",
                "kane_code_export_dir": "",
                "kane_asset_path": "",
                "kane_replay_decision": "skip",
                "last_analyzed": TODAY,
            })
            continue

        asset_path = copy_asset(i, desc, rec)
        out.append({
            "id": ac_id,
            "title": desc[:40],
            "description": desc,
            "url": TARGET_URL,
            "kane_status": rec["status"],
            "kane_one_liner": "",
            "kane_summary": f"reconstructed from .testmuai recording (status={rec['status']})",
            "kane_steps": [],
            "kane_final_state": {},
            "kane_duration": rec["duration_s"],
            "kane_links": [
                f"https://automation.lambdatest.com/test?testID={rec['session_id']}"
            ] if rec["session_id"] else [],
            "kane_session_id": rec["session_id"],
            "kane_code_export_dir": str(rec["code_dir"]),
            "kane_asset_path": str(asset_path),
            "kane_replay_decision": "record",
            "last_analyzed": TODAY,
        })

    out_path = REPO_ROOT / "requirements" / "analyzed_requirements.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path.relative_to(REPO_ROOT)} with {len(out)} entries")
    for entry in out:
        print(f"  {entry['id']}  {entry['kane_status']:8}  {entry['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
