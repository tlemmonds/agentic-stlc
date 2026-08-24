"""
Skill 3: Scenario Generation

Deterministic diff-based sync between analyzed requirements and the
scenario pool. Assigns stable SC-NNN IDs. New requirements → new scenarios,
changed → updated, removed → deprecated, unchanged → active.

Many-to-one (docs/MANY_TO_ONE.md): a requirement may own several scenarios.
Every existing record is kept. Ingested scenarios (`source: ingested` /
`kane_asset`) are "updated" only when the asset body hash drifted from the
sidecar; generated scenarios use the description comparison. A requirement
with zero scenarios gets one generated scenario only when
`scenarios.auto_create` is true (default).

Scenario IDs are immutable once assigned. Deprecated scenarios are never
deleted — they remain as historical record with status="deprecated".
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import AgentSkill

_CI_DIR = Path(__file__).resolve().parent.parent / "ci"
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))

try:  # shared many-to-one helpers (ci/project_config.py)
    from project_config import (  # type: ignore
        auto_create_scenarios,
        group_scenarios_by_requirement,
        is_ingested,
        scenario_asset_path,
    )
except ImportError:  # pragma: no cover — standalone fallback
    def auto_create_scenarios() -> bool:
        return True

    def group_scenarios_by_requirement(scenarios, *, include_deprecated=False):
        grouped: dict[str, list[dict]] = {}
        for sc in scenarios:
            rid = sc.get("requirement_id")
            if rid and (include_deprecated or sc.get("status") != "deprecated"):
                grouped.setdefault(rid, []).append(sc)
        return grouped

    def is_ingested(sc: dict) -> bool:
        return sc.get("source") == "ingested" or bool(sc.get("kane_asset"))

    def scenario_asset_path(sc: dict):
        rel = sc.get("kane_asset")
        if not rel:
            return None
        p = Path(rel)
        return p if p.is_absolute() else _CI_DIR.parent / p


def _hash_asset_body(text: str) -> str:
    try:
        from replay_policy import hash_asset_body  # type: ignore
        return hash_asset_body(text)
    except (ImportError, AttributeError):
        lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        normalized = "\n".join(lines).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _sidecar_hash(asset_path: Path) -> str | None:
    try:
        from replay_policy import read_asset_hash  # type: ignore
        return read_asset_hash(asset_path)
    except (ImportError, AttributeError):
        pass
    sidecar = asset_path.with_suffix(".meta.json")
    if not sidecar.exists():
        return None
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8")).get("description_hash")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def asset_drifted(scenario: dict) -> bool:
    """True when the ingested asset body no longer matches its sidecar hash.
    Missing asset / sidecar → not drifted (Stage 1 reports asset_missing)."""
    path = scenario_asset_path(scenario)
    if path is None or not path.exists():
        return False
    recorded = _sidecar_hash(path)
    if not recorded:
        return False
    try:
        return _hash_asset_body(path.read_text(encoding="utf-8")) != recorded
    except OSError:
        return False


class ScenarioGenerationSkill(AgentSkill):
    name = "scenario_generation"
    description = "Sync requirements → scenario pool with deterministic ID assignment"
    version = "1.1.0"

    def run(self, **inputs: Any) -> dict:
        req_path = Path(
            inputs.get("requirements_path")
            or (self.config.requirements_output if self.config else "requirements/analyzed_requirements.json")
        )
        sc_path = Path(
            inputs.get("scenarios_path")
            or (self.config.scenarios_path if self.config else "scenarios/scenarios.json")
        )

        requirements: list[dict] = []
        if req_path.exists():
            requirements = json.loads(req_path.read_text(encoding="utf-8"))

        scenarios: list[dict] = []
        if sc_path.exists():
            scenarios = json.loads(sc_path.read_text(encoding="utf-8"))

        updated, stats = self._sync(requirements, scenarios)

        sc_path.parent.mkdir(parents=True, exist_ok=True)
        sc_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")

        return {
            "success": True,
            "scenarios_path": str(sc_path),
            "total_scenarios": len(updated),
            "new": stats["new"],
            "updated": stats["updated"],
            "deprecated": stats["deprecated"],
            "active": stats["active"],
            "uncovered": stats["uncovered"],
            "uncovered_requirements": stats["uncovered_requirements"],
        }

    # ── Core sync logic ───────────────────────────────────────────────────────

    def _sync(self, requirements: list[dict], scenarios: list[dict]) -> tuple[list[dict], dict]:
        # requirement_id → [scenario, ...]; deprecated included so tombstones
        # are kept (never dropped, never renumbered).
        grouped = group_scenarios_by_requirement(scenarios, include_deprecated=True)
        new_scenarios: list[dict] = list(scenarios)
        cfg_sc = self.config.scenarios if self.config else None
        prefix = (cfg_sc.id_prefix if cfg_sc else None) or "SC"
        id_start = int((cfg_sc.id_start if cfg_sc else None) or 1)
        auto_create = auto_create_scenarios()
        now = datetime.now(timezone.utc).isoformat()

        stats: dict[str, Any] = {"new": 0, "updated": 0, "deprecated": 0, "active": 0,
                                 "uncovered": 0, "uncovered_requirements": []}
        current_req_ids = {r["id"] for r in requirements if r.get("id")}

        # Deprecate scenarios of removed requirements
        for sc in new_scenarios:
            if sc.get("requirement_id") not in current_req_ids:
                if sc.get("status") != "deprecated":
                    sc["status"] = "deprecated"
                    sc["deprecated_at"] = now
                    stats["deprecated"] += 1

        # Add or update
        for req in requirements:
            rid = req.get("id")
            if not rid:
                continue
            desc = req.get("description", "")
            brd_ref = req.get("brd_ref")
            existing = grouped.get(rid, [])

            if not existing:
                if not auto_create:
                    stats["uncovered"] += 1
                    stats["uncovered_requirements"].append(rid)
                    continue
                sc_id = self._next_id(new_scenarios, prefix, id_start)
                feature = self._infer_feature(desc)
                new_sc = {
                    "id": sc_id,
                    "requirement_id": rid,
                    "description": desc,
                    "feature": feature,
                    "status": "new",
                    "created_at": now,
                    "kane_objective": self._default_objective(desc, req.get("target_url", "")),
                }
                if brd_ref:
                    new_sc["brd_ref"] = brd_ref
                new_scenarios.append(new_sc)
                stats["new"] += 1
                continue

            for sc in existing:
                if brd_ref and not sc.get("brd_ref"):
                    sc["brd_ref"] = brd_ref
                if sc.get("status") == "deprecated":
                    continue  # tombstone stays a tombstone
                if is_ingested(sc):
                    # The asset is authoritative: never rewrite its description
                    # from the AC; drift == the test itself was edited.
                    if asset_drifted(sc):
                        sc["status"] = "updated"
                        sc["updated_at"] = now
                        stats["updated"] += 1
                    else:
                        sc["status"] = "active"
                        stats["active"] += 1
                    continue
                changed = False
                # Backfill description from requirement if missing
                source_desc = sc.get("description") or sc.get("source_description", "")
                if source_desc != desc and desc:
                    sc["description"] = desc
                    changed = True
                elif not sc.get("description") and source_desc:
                    sc["description"] = source_desc
                # Backfill feature if missing or GENERAL
                if not sc.get("feature") or sc.get("feature") == "GENERAL":
                    sc["feature"] = self._infer_feature(sc.get("description", desc))
                # Backfill kane_objective if missing
                if not sc.get("kane_objective"):
                    sc["kane_objective"] = self._default_objective(
                        sc.get("description", desc),
                        req.get("target_url", ""),
                    )
                if changed:
                    sc["status"] = "updated"
                    sc["updated_at"] = now
                    stats["updated"] += 1
                else:
                    sc["status"] = "active"
                    stats["active"] += 1

        return new_scenarios, stats

    def _next_id(self, scenarios: list[dict], prefix: str, start: int) -> str:
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
        max_n = start - 1
        for sc in scenarios:
            m = pattern.match(sc.get("id", ""))
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"{prefix}-{max_n + 1:03d}"

    def _infer_feature(self, description: str) -> str:
        desc_lower = description.lower()
        # Ordered most-specific → most-general so ARCHIVE wins over TASK_CRUD
        # when a requirement mentions "archive a task".
        keywords = {
            "ARCHIVE":   ["archive", "restore", "archived"],
            "LABELS":    ["label", "colored label", "color label", "tag"],
            "FILTER":    ["filter", "status filter", "active / done", "active/done"],
            "TASK_LIST": ["list all tasks", "ordered by due date", "task list",
                          "overdue", "pinned", "sort by due"],
            "TASK_CRUD": ["create a task", "add a task", "new task",
                          "edit a task", "edit task", "update a task",
                          "delete a task", "remove a task",
                          "mark a task as complete", "complete a task",
                          "task title", "due date"],
        }
        for feature, kws in keywords.items():
            if any(kw in desc_lower for kw in kws):
                return feature
        return "GENERAL"

    def _default_objective(self, description: str, target_url: str = "") -> str:
        base = f"Verify: {description}"
        if target_url:
            base += f" on {target_url}"
        return base
