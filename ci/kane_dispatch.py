"""Stage 1 dispatcher — replaces the inline `_KANE_TASK_OVERRIDES` lookup
in analyze_requirements.py with a replay-first policy.

For each AC the pipeline asks: replay an existing _test.md, record a new
one, or skip? See ci/replay_policy.py for the decision algorithm.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from replay_policy import (
    REPO_ROOT,
    ReplayDecision,
    asset_path_for,
    decide,
    hash_description,
)
import kane_record
import kane_replay

CODE_EXPORT_CACHE = REPO_ROOT / "tests" / "playwright" / "exported"
DECISIONS_LOG = REPO_ROOT / "reports" / "replay_decisions.json"


def build_name() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "")
    return f"Agentic STLC #{run_number} | {today}" if run_number else f"Agentic STLC | {today}"


def _scenario_for(requirement_id: str, scenarios: list[dict]) -> dict | None:
    for sc in scenarios:
        if sc.get("requirement_id") == requirement_id:
            return sc
    return None


def _objective_for(requirement_id: str, scenarios: list[dict], description: str) -> str:
    """Reuse the canonical objective baked into scenarios.json
    (kane_objective) if present; fall back to the AC description prefixed
    with TARGET_URL so Kane lands on the right site.

    The URL prefix is critical: without it, Kane defaults to its own demo
    site (kaneai-playground.lambdatest.io) instead of the AUT. We only
    inject TARGET_URL when the objective doesn't already mention it, to
    avoid double-prefixing custom objectives."""
    sc = _scenario_for(requirement_id, scenarios)
    if sc and sc.get("kane_objective"):
        return sc["kane_objective"]
    target_url = os.environ.get("TARGET_URL", "").strip()
    if target_url and target_url.rstrip("/") not in description:
        return f"On {target_url} — {description}"
    return description


def _description_for(sc: dict) -> str:
    """Tolerate both the current `description` key and the legacy
    `source_description` key emitted by older Stage 2 runs."""
    return sc.get("description") or sc.get("source_description") or ""


def _export_subdir_for(sc_id: str) -> Path:
    return CODE_EXPORT_CACHE / sc_id.lower().replace("-", "_")


def _scenarios_from(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def dispatch_one(
    *,
    index: int,
    description: str,
    scenarios: list[dict],
    username: str,
    access_key: str,
    force_re_author: bool,
) -> tuple[ReplayDecision, dict[str, Any]]:
    """Decide + execute for a single AC. Returns (decision, kane_result).

    The kane_result shape matches analyze_requirements.run_kane() so
    Stage 1 emits the same analyzed_requirements.json schema."""
    requirement_id = f"AC-{index:03d}"
    sc = _scenario_for(requirement_id, scenarios) or {}
    sc_id = sc.get("id", f"SC-{index:03d}")
    feature = sc.get("feature", "general")
    title = sc.get("title", description[:60])

    decision = decide(
        sc_id=sc_id,
        requirement_id=requirement_id,
        description=description,
        feature=feature,
        title=title,
        force_re_author=force_re_author,
        deprecated=(sc.get("status") == "deprecated"),
    )

    if decision.decision == "skip":
        result = {
            "status": "skipped",
            "summary": f"skipped: {decision.reason}",
            "one_liner": "", "steps": [], "final_state": {},
            "duration": None, "test_url": "",
            "session_id": "", "code_export_dir": "",
            "asset_path": str(decision.asset_path) if decision.asset_path else "",
            "replay_decision": decision.decision,
        }
        return decision, result

    objective = _objective_for(requirement_id, scenarios, description)
    export_dir = _export_subdir_for(sc_id)
    bn = build_name()

    # First-record on a new AUT (Vercel cold start, large React bundle, etc.)
    # often needs more headroom than replays of an already-mapped flow.
    record_timeout = int(os.environ.get("KANE_RECORD_TIMEOUT", "300"))
    replay_timeout = int(os.environ.get("KANE_REPLAY_TIMEOUT", "180"))

    if decision.decision == "replay":
        result = kane_replay.replay(
            decision.asset_path,
            session_name=f"Replay {sc_id} | {description[:60]}",
            build_name=bn,
            username=username,
            access_key=access_key,
            timeout_seconds=replay_timeout,
            code_export_dir=export_dir,
        )
    else:
        # record (new asset) or rerecord (asset exists but stale).
        target_asset = decision.asset_path or asset_path_for(sc_id, feature, title)
        result = kane_record.record(
            objective,
            sc_id=sc_id,
            requirement_id=requirement_id,
            description=description,
            description_hash=decision.description_hash,
            feature=feature,
            asset_path=target_asset,
            build_name=bn,
            username=username,
            access_key=access_key,
            timeout_seconds=record_timeout,
            code_export_dir=export_dir,
        )

    result["asset_path"] = str(decision.asset_path or "")
    result["replay_decision"] = decision.decision
    return decision, result


def dispatch_all(
    descriptions: list[str],
    *,
    username: str,
    access_key: str,
    scenarios_path: Path | None = None,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """Dispatch every AC in parallel (mirrors the ThreadPoolExecutor pattern
    from analyze_requirements.main). Returns a list of kane-result dicts in
    the same order as descriptions."""
    from concurrent.futures import ThreadPoolExecutor

    scenarios_path = scenarios_path or REPO_ROOT / "scenarios" / "scenarios.json"
    scenarios = _scenarios_from(scenarios_path)
    force = os.environ.get("FORCE_RE_AUTHOR", "false").lower() == "true"

    decisions: list[ReplayDecision] = []
    results: list[dict[str, Any]] = [None] * len(descriptions)  # type: ignore[list-item]

    def _work(arg):
        idx, desc = arg
        return dispatch_one(
            index=idx,
            description=desc,
            scenarios=scenarios,
            username=username,
            access_key=access_key,
            force_re_author=force,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for i, (decision, result) in enumerate(pool.map(_work, list(enumerate(descriptions, start=1)))):
            decisions.append(decision)
            results[i] = result

    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "force_re_author": force,
        "decisions": [d.to_dict() for d in decisions],
        "summary": {
            label: sum(1 for d in decisions if d.decision == label)
            for label in ("replay", "record", "rerecord", "skip")
        },
    }
    DECISIONS_LOG.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return results
