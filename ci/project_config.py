"""
Shared project-level helpers for the ci/ stage scripts.

Deliberately self-contained (no astlc import) so every stage script keeps
working as a standalone `python ci/<stage>.py` invocation. Reads
agentic-stlc.config.yaml once and exposes:

  load_config()                      → dict (empty when the file is absent)
  cfg(path, default)                 → dotted lookup, e.g. cfg("scenarios.auto_create", True)
  feature_taxonomy()                 → (criticality, keywords, expected_scenarios)
  classify_feature(text, explicit)   → feature name
  criticality_for(feature)           → "HIGH" | "MEDIUM" | "LOW"
  group_scenarios_by_requirement()   → dict[req_id, list[scenario]]  (many-to-one)
  rollup_kane_status(statuses)       → "passed" | "failed" | "skipped" | "not_run"

See docs/MANY_TO_ONE.md for the contract these helpers implement.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = Path(os.environ.get("AGENTIC_STLC_CONFIG", REPO_ROOT / "agentic-stlc.config.yaml"))

# ── Fallback taxonomy (TaskFlow) — used only when config has no `features:` ──
_FALLBACK_CRITICALITY: dict[str, str] = {
    "TASK_CRUD": "HIGH",
    "TASK_LIST": "HIGH",
    "ARCHIVE":   "HIGH",
    "FILTER":    "MEDIUM",
    "LABELS":    "MEDIUM",
}
_FALLBACK_KEYWORDS: dict[str, list[str]] = {
    "ARCHIVE":   ["archive", "restore", "archived"],
    "LABELS":    ["label", "colored label", "color label", "tag"],
    "FILTER":    ["filter", "status filter", "active / done", "active/done"],
    "TASK_LIST": ["list all tasks", "ordered by due date", "task list", "overdue", "pinned", "sort by due"],
    "TASK_CRUD": ["create a task", "add a task", "new task", "edit a task", "edit task", "update a task",
                  "delete a task", "remove a task", "mark a task as complete", "complete a task",
                  "task title", "due date"],
}
_FALLBACK_EXPECTED: dict[str, list[dict]] = {
    "TASK_CRUD": [
        {"type": "happy_path", "description": "Create a task with a title and due date"},
        {"type": "happy_path", "description": "Edit a task's title or due date"},
        {"type": "happy_path", "description": "Mark a task as complete"},
        {"type": "happy_path", "description": "Delete a task"},
        {"type": "negative",   "description": "Submit task form with empty title"},
        {"type": "edge_case",  "description": "Create a task with a past-due date"},
    ],
    "TASK_LIST": [
        {"type": "happy_path", "description": "List all tasks ordered by due date"},
        {"type": "happy_path", "description": "Overdue tasks appear pinned at the top"},
        {"type": "edge_case",  "description": "List view when no tasks exist"},
    ],
    "ARCHIVE": [
        {"type": "happy_path", "description": "Archive a task and confirm it moves to Archive page"},
        {"type": "happy_path", "description": "Restore an archived task back to the active list"},
        {"type": "edge_case",  "description": "Archive page is empty"},
    ],
    "FILTER": [
        {"type": "happy_path", "description": "Filter task list by status (active / done / all)"},
        {"type": "negative",   "description": "Apply filter that produces no results"},
    ],
    "LABELS": [
        {"type": "happy_path", "description": "Attach a colored label to a task"},
        {"type": "happy_path", "description": "Filter tasks by label"},
        {"type": "negative",   "description": "Filter by a label with no tasks attached"},
    ],
}

DEFAULT_FEATURE = "GENERAL"
DEFAULT_CRITICALITY = "MEDIUM"


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Parse agentic-stlc.config.yaml. Returns {} when missing or unparsable."""
    if not _CONFIG_PATH.exists():
        return {}
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Silent fallback here once re-scored a whole baseline against the
            # TaskFlow taxonomy (every requirement LOW/GENERAL). Say so.
            import sys
            print(f"[project_config] WARNING: PyYAML missing and {_CONFIG_PATH.name} is not JSON — "
                  f"config ignored, falling back to built-in defaults", file=sys.stderr)
            return {}
    except Exception:
        return {}


def cfg(path: str, default: Any = None) -> Any:
    """Dotted lookup into the config, e.g. cfg('kaneai.auto_record', True)."""
    node: Any = load_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def cfg_bool(path: str, default: bool) -> bool:
    """Bool lookup with an env-var override of the same dotted name upper-cased
    (e.g. KANEAI_AUTO_RECORD=false)."""
    env_key = path.replace(".", "_").upper()
    raw = os.environ.get(env_key)
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes")
    val = cfg(path, default)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes")
    return bool(val)


# ── Feature taxonomy ──────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def feature_taxonomy() -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[dict]]]:
    """(criticality_by_feature, keywords_by_feature, expected_scenarios_by_feature).
    Config `features:` wins entirely when present; otherwise the TaskFlow fallback."""
    features = cfg("features")
    if not isinstance(features, dict) or not features:
        return dict(_FALLBACK_CRITICALITY), dict(_FALLBACK_KEYWORDS), dict(_FALLBACK_EXPECTED)
    crit: dict[str, str] = {}
    kws: dict[str, list[str]] = {}
    expected: dict[str, list[dict]] = {}
    for name, spec in features.items():
        key = str(name).upper()
        spec = spec or {}
        crit[key] = str(spec.get("criticality", DEFAULT_CRITICALITY)).upper()
        kws[key] = [str(k).lower() for k in (spec.get("keywords") or [])]
        expected[key] = [
            {"type": str(e.get("type", "happy_path")), "description": str(e.get("description", ""))}
            for e in (spec.get("expected_scenarios") or [])
            if isinstance(e, dict)
        ]
    return crit, kws, expected


def classify_feature(text: str, explicit: str | None = None) -> str:
    """Explicit feature (from the scenario record) always wins. Otherwise the
    first feature whose keyword list matches the text, in config order."""
    if explicit:
        return str(explicit).upper()
    lowered = (text or "").lower()
    _, kws, _ = feature_taxonomy()
    # The feature whose keyword appears EARLIEST wins, not the first feature in
    # config order: "Sign-in — … (decision: no lockout)" is AUTH, not ORIGINATION.
    best_feature, best_pos = DEFAULT_FEATURE, None
    for feature, words in kws.items():
        positions = [lowered.find(w) for w in words if w and w in lowered]
        if positions:
            pos = min(positions)
            if best_pos is None or pos < best_pos:
                best_feature, best_pos = feature, pos
    return best_feature


def criticality_for(feature: str, *, requirement_id: str | None = None, brd_ref: str | None = None) -> str:
    """Feature default, unless `criticality_overrides:` in the config names the
    requirement. Keys are matched against the requirement id and its brd_ref —
    exact match first, then fnmatch globs (e.g. `NEG-1[2-6]`, `BRD-AC-0[7-8]`) in
    config order. Lets a baseline say "hard-stop boundaries are HIGH, tier
    boundaries MEDIUM, 'no lockout in the demo' LOW" without a feature per tier."""
    crit, _, _ = feature_taxonomy()
    default = crit.get(str(feature or "").upper(), DEFAULT_CRITICALITY)
    overrides = cfg("criticality_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return default
    keys = [k for k in (requirement_id, brd_ref) if k]
    if not keys:
        return default
    for key in keys:
        if key in overrides:
            return str(overrides[key]).upper()
    from fnmatch import fnmatchcase
    for pattern, level in overrides.items():
        if any(fnmatchcase(k, str(pattern)) for k in keys):
            return str(level).upper()
    return default


# ── Many-to-one helpers ───────────────────────────────────────────────────────

def group_scenarios_by_requirement(scenarios: Iterable[dict], *, include_deprecated: bool = False) -> dict[str, list[dict]]:
    """requirement_id → [scenario, ...] preserving scenarios.json order."""
    grouped: dict[str, list[dict]] = {}
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        rid = sc.get("requirement_id")
        if not rid:
            continue
        if not include_deprecated and sc.get("status") == "deprecated":
            continue
        grouped.setdefault(rid, []).append(sc)
    return grouped


def deprecated_by_requirement(scenarios: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for sc in scenarios:
        if isinstance(sc, dict) and sc.get("status") == "deprecated" and sc.get("requirement_id"):
            out.setdefault(sc["requirement_id"], []).append(sc)
    return out


_FAIL_STATUSES = {"failed", "error", "timeout"}


def rollup_kane_status(statuses: Iterable[str]) -> str:
    """Roll scenario-level Kane statuses up to the requirement.
    any failed/error/timeout → failed; ≥1 passed → passed; all skipped → skipped; else not_run."""
    seen = [str(s or "").lower() for s in statuses]
    if not seen:
        return "not_run"
    if any(s in _FAIL_STATUSES for s in seen):
        return "failed"
    if any(s == "passed" for s in seen):
        return "passed"
    if all(s == "skipped" for s in seen):
        return "skipped"
    return "not_run"


def rollup_playwright_status(statuses: Iterable[str]) -> str:
    """Roll scenario-level Playwright statuses up to the requirement.
    any failed → failed; ≥1 passed and none failed → passed; else data_unavailable."""
    seen = [str(s or "").lower() for s in statuses]
    if any(s == "failed" for s in seen):
        return "failed"
    if any(s == "passed" for s in seen):
        return "passed"
    return "data_unavailable"


def is_ingested(scenario: dict) -> bool:
    return (scenario or {}).get("source") == "ingested" or bool((scenario or {}).get("kane_asset"))


def scenario_asset_path(scenario: dict) -> Path | None:
    """Explicit `kane_asset` (repo-relative) → absolute Path, else None."""
    rel = (scenario or {}).get("kane_asset")
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def auto_create_scenarios() -> bool:
    return cfg_bool("scenarios.auto_create", True)


def auto_record() -> bool:
    return cfg_bool("kaneai.auto_record", True)


def adaptive_heal() -> bool:
    return cfg_bool("kaneai.adaptive_heal", False)
