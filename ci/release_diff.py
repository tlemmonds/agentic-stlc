"""Agentic Release Notes — Stage 0.

Given the most recent release lock (`release_notes/<prev>.lock.json`,
which is a frozen scenarios.json snapshot from the last shipped release)
and a new release-notes markdown file (`release_notes/<next>.md`),
produce an Add / Edit / Delete operations list against the current test
pool.

Two modes:

    python ci/release_diff.py --propose
        Default. Compute the delta and write reports/release_delta.{json,md}.
        Mutates nothing. Used by CI on every push to release_notes/.

    python ci/release_diff.py --apply
        Apply the operations: mutate scenarios.json, write the new lock
        file, and emit a one-line audit record. Use after a human has
        reviewed the propose output.

Decision algorithm (pure rules, deterministic):

    Section "Added"   → ADD    : always create a new AC + scenario.
    Section "Changed" → EDIT   : match release item text to existing scenario
                                 by token Jaccard similarity (default ≥ 0.5).
                                 No match → unmatched_items[].
    Section "Removed" → DELETE : same matching, marks scenario deprecated.
    Section "Fixed"   → noted only; no scenario op (bug fixes get
                                 covered by the existing replay run; if a
                                 fix changes user-visible behavior the
                                 author should also list it under Changed).

Match threshold is conservative on purpose: it's better to surface an
"unmatched" warning to the author than to silently retitle the wrong
scenario.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from release_notes_parser import parse_file, parse_version_from_filename, ReleaseItem
from stage_utils import print_stage_header, print_stage_result

REPO_ROOT      = Path(__file__).resolve().parent.parent
RELEASE_DIR    = REPO_ROOT / "release_notes"
SCENARIOS_PATH = REPO_ROOT / "scenarios" / "scenarios.json"
DELTA_JSON     = REPO_ROOT / "reports" / "release_delta.json"
DELTA_MD       = REPO_ROOT / "reports" / "release_delta.md"

DEFAULT_MATCH_THRESHOLD = 0.5

# ── Token similarity (Jaccard) ─────────────────────────────────────────────
# Stop words removed before tokenization so "the user can add" doesn't
# perfectly match "the user can remove" by the shared filler tokens.
_STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "can", "for", "from", "in",
    "is", "it", "of", "on", "or", "so", "that", "the", "their", "this",
    "to", "user", "users", "want", "wants", "with", "see", "sees",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS and len(t) > 2}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── Operation model ────────────────────────────────────────────────────────
@dataclass
class Operation:
    op: str               # ADD | EDIT | DELETE
    item_text: str
    item_section: str
    issue: str | None
    sc_id: str | None     # populated for EDIT/DELETE
    requirement_id: str | None
    match_score: float    # 0.0 for ADD; jaccard for EDIT/DELETE
    rationale: str
    prev_text: str | None = None  # the previous-release description; populated for EDIT/DELETE

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "item_text": self.item_text,
            "item_section": self.item_section,
            "issue": self.issue,
            "sc_id": self.sc_id,
            "requirement_id": self.requirement_id,
            "match_score": round(self.match_score, 3),
            "rationale": self.rationale,
            "prev_text": self.prev_text,
        }


@dataclass
class DiffResult:
    from_release: str
    to_release: str
    from_lock_path: str
    to_lock_path: str
    operations: list[Operation] = field(default_factory=list)
    unmatched_items: list[dict] = field(default_factory=list)
    threshold: float = DEFAULT_MATCH_THRESHOLD
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def summary(self) -> dict:
        return {
            label: sum(1 for o in self.operations if o.op == label)
            for label in ("ADD", "EDIT", "DELETE")
        } | {"UNMATCHED": len(self.unmatched_items)}

    def to_dict(self) -> dict:
        return {
            "from_release": self.from_release,
            "to_release": self.to_release,
            "from_lock_path": self.from_lock_path,
            "to_lock_path": self.to_lock_path,
            "threshold": self.threshold,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "operations": [o.to_dict() for o in self.operations],
            "unmatched_items": self.unmatched_items,
        }


# ── Inputs ─────────────────────────────────────────────────────────────────

# Release versions are sorted as tuples of integers so v1.10.0 > v1.2.0.
_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?$")


def _version_key(stem: str) -> tuple[int, ...]:
    m = _VERSION_RE.match(stem)
    if not m:
        return (0,)
    return tuple(int(g) if g else 0 for g in m.groups())


def _release_files() -> tuple[list[Path], list[Path]]:
    """Return (notes, locks) sorted ascending by version."""
    if not RELEASE_DIR.exists():
        return [], []
    notes = sorted(
        (p for p in RELEASE_DIR.glob("*.md") if not p.name.lower().startswith("readme")),
        key=lambda p: _version_key(p.stem),
    )
    locks = sorted(RELEASE_DIR.glob("*.lock.json"), key=lambda p: _version_key(p.stem.replace(".lock", "")))
    return notes, locks


def resolve_release_pair(target: Path | None = None) -> tuple[Path, Path | None]:
    """Pick the release-notes file to diff and its predecessor lock file.

    target  — explicit path to the new release notes (overrides auto-pick)
    Returns (notes_path, prev_lock_path or None for the very first release).
    """
    notes, locks = _release_files()
    if target is not None:
        notes_path = target
    elif notes:
        notes_path = notes[-1]
    else:
        raise FileNotFoundError(
            f"No release notes found under {RELEASE_DIR.relative_to(REPO_ROOT)}/. "
            f"Author release_notes/v1.0.0.md to bootstrap the first release."
        )
    target_key = _version_key(notes_path.stem)
    prev_locks = [p for p in locks if _version_key(p.stem.replace(".lock", "")) < target_key]
    return notes_path, (prev_locks[-1] if prev_locks else None)


def _load_scenarios_for_diff(prev_lock: Path | None) -> tuple[list[dict], str]:
    """Return (scenarios_list, source_label).

    If a prev_lock is supplied it's the canonical R(n-1) snapshot; otherwise
    we fall back to the current scenarios.json (first-release case)."""
    if prev_lock is not None and prev_lock.exists():
        data = json.loads(prev_lock.read_text(encoding="utf-8"))
        return data.get("scenarios", []), str(prev_lock.relative_to(REPO_ROOT))
    if SCENARIOS_PATH.exists():
        return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8")), str(SCENARIOS_PATH.relative_to(REPO_ROOT))
    return [], "<empty>"


# ── Matching + diff ────────────────────────────────────────────────────────
def _description_of(scenario: dict) -> str:
    return scenario.get("description") or scenario.get("source_description") or scenario.get("title") or ""


def _best_match(item_text: str, candidates: list[dict], threshold: float) -> tuple[dict | None, float]:
    best: dict | None = None
    best_score = 0.0
    for c in candidates:
        score = jaccard(item_text, _description_of(c))
        if score > best_score:
            best, best_score = c, score
    return (best, best_score) if best_score >= threshold else (None, best_score)


def _next_ac_id(scenarios: list[dict]) -> str:
    max_n = 0
    for sc in scenarios:
        m = re.match(r"AC-(\d+)", sc.get("requirement_id", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"AC-{max_n + 1:03d}"


def diff(
    notes_path: Path,
    prev_lock: Path | None,
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> DiffResult:
    items = parse_file(notes_path)
    prev_scenarios, source_label = _load_scenarios_for_diff(prev_lock)

    next_ac_index = int(_next_ac_id(prev_scenarios).split("-")[1])
    deletion_targets = [s for s in prev_scenarios if s.get("status") != "deprecated"]
    edit_targets = list(deletion_targets)  # same pool; matched scenarios excluded as we go

    result = DiffResult(
        from_release=Path(source_label).stem.replace(".lock", "") if prev_lock else "<initial>",
        to_release=parse_version_from_filename(notes_path),
        from_lock_path=source_label,
        to_lock_path=str((RELEASE_DIR / f"{parse_version_from_filename(notes_path)}.lock.json").relative_to(REPO_ROOT)),
        threshold=threshold,
    )

    for item in items:
        if item.section == "Added":
            ac_id = f"AC-{next_ac_index:03d}"
            next_ac_index += 1
            result.operations.append(Operation(
                op="ADD", item_text=item.text, item_section=item.section,
                issue=item.issue, sc_id=None, requirement_id=ac_id,
                match_score=0.0,
                rationale=f"new requirement; will allocate {ac_id} and let Stage 1 record the asset",
            ))
        elif item.section == "Changed":
            best, score = _best_match(item.text, edit_targets, threshold)
            if best is None:
                result.unmatched_items.append({
                    "section": item.section, "text": item.text, "issue": item.issue,
                    "best_score": round(score, 3),
                    "reason": f"no scenario cleared similarity threshold {threshold}",
                })
                continue
            edit_targets.remove(best)
            # Capture the v(prev) text so the Stage 0 summary can render
            # before → after for the EDIT op. Both schemas seen in locks:
            # `description` (current) and `source_description` (legacy).
            prev_text = best.get("description") or best.get("source_description")
            result.operations.append(Operation(
                op="EDIT", item_text=item.text, item_section=item.section,
                issue=item.issue, sc_id=best.get("id"), requirement_id=best.get("requirement_id"),
                match_score=score,
                rationale=f"matched on description similarity ({score:.2f}); EDIT will rewrite description and invalidate description_hash so Stage 1 re-records the asset",
                prev_text=prev_text,
            ))
        elif item.section == "Removed":
            best, score = _best_match(item.text, edit_targets, threshold)
            if best is None:
                result.unmatched_items.append({
                    "section": item.section, "text": item.text, "issue": item.issue,
                    "best_score": round(score, 3),
                    "reason": f"no scenario cleared similarity threshold {threshold}",
                })
                continue
            edit_targets.remove(best)
            prev_text = best.get("description") or best.get("source_description")
            result.operations.append(Operation(
                op="DELETE", item_text=item.text, item_section=item.section,
                issue=item.issue, sc_id=best.get("id"), requirement_id=best.get("requirement_id"),
                match_score=score,
                rationale=f"matched on description similarity ({score:.2f}); will mark scenario deprecated (asset preserved)",
                prev_text=prev_text,
            ))
        # Fixed / Deprecated / Security: noted in markdown but no scenario op.
    return result


# ── Application ────────────────────────────────────────────────────────────
def apply(result: DiffResult) -> dict:
    """Mutate scenarios.json per the operations list and write the new lock."""
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in scenarios}
    today = datetime.now(timezone.utc).date().isoformat()
    summary = {"ADD": 0, "EDIT": 0, "DELETE": 0}
    next_sc_n = max(
        (int(re.match(r"SC-(\d+)", s["id"]).group(1))  # type: ignore[union-attr]
         for s in scenarios if re.match(r"SC-\d+", s["id"])),
        default=0,
    ) + 1
    for op in result.operations:
        if op.op == "ADD":
            sc_id = f"SC-{next_sc_n:03d}"
            next_sc_n += 1
            scenarios.append({
                "id": sc_id,
                "test_case_id": sc_id.replace("SC-", "TC-"),
                "requirement_id": op.requirement_id,
                "title": op.item_text[:80],
                "description": op.item_text,
                "feature": "general",
                "status": "new",
                "kane_objective": op.item_text,
                "added_in_release": result.to_release,
                "added_at": today,
                "issue": op.issue,
            })
            summary["ADD"] += 1
        elif op.op == "EDIT" and op.sc_id and op.sc_id in by_id:
            sc = by_id[op.sc_id]
            sc["description"] = op.item_text
            sc["source_description"] = op.item_text
            sc["status"] = "updated"
            sc["last_changed_in_release"] = result.to_release
            sc["last_changed_at"] = today
            if op.issue:
                sc.setdefault("issues", []).append(op.issue)
            summary["EDIT"] += 1
        elif op.op == "DELETE" and op.sc_id and op.sc_id in by_id:
            sc = by_id[op.sc_id]
            sc["status"] = "deprecated"
            sc["deprecated_in_release"] = result.to_release
            sc["deprecated_at"] = today
            if op.issue:
                sc.setdefault("issues", []).append(op.issue)
            summary["DELETE"] += 1

    SCENARIOS_PATH.write_text(json.dumps(scenarios, indent=2) + "\n", encoding="utf-8")

    # Write the lock file for the new release.
    lock_path = RELEASE_DIR / f"{result.to_release}.lock.json"
    lock_path.write_text(
        json.dumps({
            "release": result.to_release,
            "released_at": today,
            "from_release": result.from_release,
            "delta_summary": result.summary,
            "scenarios": scenarios,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"summary": summary, "lock_path": str(lock_path.relative_to(REPO_ROOT))}


# ── Reporting ──────────────────────────────────────────────────────────────
def write_reports(result: DiffResult, *, applied: bool, applied_summary: dict | None = None) -> None:
    DELTA_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    payload["applied"] = applied
    if applied_summary:
        payload["applied_summary"] = applied_summary
    DELTA_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines: list[str] = [
        f"# Release Delta — {result.from_release} → {result.to_release}",
        "",
        f"_Generated: {result.generated_at}_",
        f"_Match threshold: {result.threshold}_",
        f"_Mode: {'APPLIED' if applied else 'PROPOSE (no mutations)'}_",
        "",
        "## Summary",
        "",
        f"- ADD: **{result.summary['ADD']}**",
        f"- EDIT: **{result.summary['EDIT']}**",
        f"- DELETE: **{result.summary['DELETE']}**",
        f"- UNMATCHED: **{result.summary['UNMATCHED']}**",
        "",
    ]
    if result.operations:
        lines += [
            "## Operations",
            "",
            "| Op | SC | Req | Issue | Score | Item |",
            "|---|---|---|---|---|---|",
        ]
        for op in result.operations:
            lines.append(
                f"| **{op.op}** | `{op.sc_id or '—'}` | `{op.requirement_id or '—'}` | "
                f"{op.issue or '—'} | {op.match_score:.2f} | {op.item_text} |"
            )
        lines.append("")
    if result.unmatched_items:
        lines += [
            "## Unmatched items (require manual scenario assignment)",
            "",
            "| Section | Best score | Reason | Item |",
            "|---|---|---|---|",
        ]
        for u in result.unmatched_items:
            lines.append(
                f"| {u['section']} | {u['best_score']:.2f} | {u['reason']} | {u['text']} |"
            )
        lines.append("")
    DELTA_MD.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────────────
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Agentic Release Notes — Stage 0")
    p.add_argument("--notes", type=Path, help="Explicit release notes file (default: latest under release_notes/)")
    p.add_argument("--threshold", type=float, default=DEFAULT_MATCH_THRESHOLD,
                   help=f"Jaccard similarity threshold for matching (default {DEFAULT_MATCH_THRESHOLD})")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--propose", action="store_true",
                     help="Default: write reports/release_delta.{json,md}; mutate nothing")
    grp.add_argument("--apply", action="store_true",
                     help="Apply operations to scenarios.json + write the new lock file")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print_stage_header("0", "RELEASE_DIFF",
                       "Compute Add/Edit/Delete operations from release notes diff")
    try:
        notes, prev_lock = resolve_release_pair(args.notes)
    except FileNotFoundError as exc:
        print(f"[release_diff] {exc}", file=sys.stderr)
        return 1

    print(
        f"[release_diff] notes={notes.relative_to(REPO_ROOT)} "
        f"prev_lock={prev_lock.relative_to(REPO_ROOT) if prev_lock else '<none — first release>'} "
        f"threshold={args.threshold}"
    )

    result = diff(notes, prev_lock, threshold=args.threshold)
    applied = bool(args.apply)
    applied_summary: dict | None = None
    if applied:
        applied_summary = apply(result)
    write_reports(result, applied=applied, applied_summary=applied_summary)

    print_stage_result("0", "RELEASE_DIFF", {
        "From release":   result.from_release,
        "To release":     result.to_release,
        "ADD":            result.summary["ADD"],
        "EDIT":           result.summary["EDIT"],
        "DELETE":         result.summary["DELETE"],
        "UNMATCHED":      result.summary["UNMATCHED"],
        "Mode":           "APPLIED" if applied else "PROPOSE",
        "Delta JSON":     str(DELTA_JSON.relative_to(REPO_ROOT)),
        "Delta MD":       str(DELTA_MD.relative_to(REPO_ROOT)),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
