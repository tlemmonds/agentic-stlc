# Agentic Release Notes — Author & Operator Guide

The pipeline understands releases. When a new release is shipping, you write
Keep-a-Changelog markdown for it; the pipeline turns the bullets into
**ADD / EDIT / DELETE** operations on the test pool, runs Stage 1 only on
the affected scenarios, and scores the delta in Stage 2b.

This guide covers (1) authoring conventions, (2) the pipeline contract,
(3) a worked R1 → R2 example, and (4) how to roll back.

---

## TL;DR

| You do | Pipeline does |
|---|---|
| Edit `release_notes/v1.1.0.md` (Keep-a-Changelog format) and push | Runs `python ci/release_diff.py` in **propose** mode; renders the proposed delta in the GH summary as **Stage 0**. Mutates nothing. |
| Review the proposal. Re-run the workflow with `apply_release_delta = true` | Runs `python ci/release_diff.py --apply`: mutates `scenarios.json`, freezes `release_notes/v1.1.0.lock.json`, then runs the rest of the pipeline. Stage 1 records new ADD scenarios + re-records EDITs (cheap because it's only the delta, not the whole pool). |
| Commit the resulting changes | `scenarios.json` + `release_notes/v1.1.0.lock.json` + any new `tests/kane/<feature>/sc_*_test.md` assets become the v1.1.0 baseline. |

---

## File layout

```
release_notes/
├── v1.0.0.md              ← human-authored release notes
├── v1.0.0.lock.json       ← frozen scenarios.json snapshot at v1.0.0 ship
├── v1.1.0.md              ← release notes for the next release
└── v1.1.0.lock.json       ← (written by `--apply` when v1.1.0 ships)
```

Everything in `release_notes/` is committed. The `*.lock.json` is the
authoritative "this is what was in release X" record — `release_diff.py`
reads it, not the live `scenarios.json`, when computing operations.

---

## Authoring `release_notes/<version>.md`

Use the [Keep a Changelog](https://keepachangelog.com/) format. The parser
recognizes four section names that map to operations; every other section
is reported but ignored:

| Section | What it means | Operation |
|---|---|---|
| `### Added`     | New capability shipped this release      | **ADD** — new AC + scenario provisioned |
| `### Changed`   | Existing behavior changed                | **EDIT** — best-matching scenario updated; description_hash invalidated → Stage 1 re-records the asset |
| `### Removed`   | Capability was retired                   | **DELETE** — best-matching scenario marked `deprecated` (assets preserved) |
| `### Fixed`     | Bug fix; no user-visible behavior change | (no operation — covered by next replay run) |

Bullet conventions:

- One bullet = one capability change.
- Optional issue ref in parens: `(#PROJ-123)` or `(PROJ-123)`. Captured
  into the operation record so QA can correlate.
- The bullet text is what the matcher Jaccards against. Stay close to the
  AC wording in `scenarios.json` so EDIT/DELETE matches above the
  threshold (default 0.5).

Sample (also see [release_notes/v1.1.0.md](release_notes/v1.1.0.md)):

```markdown
# v1.1.0 — 2026-06-01

### Added
- User can share a wishlist via email (#PROJ-123)
- User can pay with Apple Pay at checkout (#PROJ-145)

### Changed
- User can sort products by price low to high or high to low (#PROJ-138)

### Removed
- User can add a product to the wish list (#PROJ-150)

### Fixed
- Cart counter updates immediately on slow networks (#PROJ-160)
```

---

## CLI

`python ci/release_diff.py` — defaults to **propose** mode.

| Flag | Effect |
|---|---|
| (none) / `--propose` | Compute the delta and write `reports/release_delta.json` + `.md`. **No mutations.** |
| `--apply` | Same compute, then mutate `scenarios.json` and write `release_notes/<to>.lock.json`. |
| `--notes <path>` | Override the auto-picked release-notes file (default: highest-versioned `release_notes/*.md`). |
| `--threshold <0..1>` | Override the Jaccard match threshold for EDIT/DELETE (default `0.5`). Lower = more aggressive matching, higher = more items land in `unmatched_items`. |

Outputs:

| Path | Contents |
|---|---|
| `reports/release_delta.json` | Machine-readable delta: `from_release`, `to_release`, threshold, full operations list, unmatched items, applied flag. Consumed by `write_github_summary.py` to render Stage 0. |
| `reports/release_delta.md` | Human-readable preview. Tables for ops + unmatched. |
| `release_notes/<to>.lock.json` | Written **only on `--apply`**. Frozen scenarios snapshot for the new release. |

---

## Worked example — `v1.0.0 → v1.1.0`

**Step 1.** v1.0.0 has shipped. `release_notes/v1.0.0.lock.json` is frozen
(15 scenarios). The QA team is preparing v1.1.0.

**Step 2.** Author `release_notes/v1.1.0.md`:

```markdown
# v1.1.0 — 2026-06-01

### Added
- User can share a wishlist via email (#PROJ-123)
- User can pay with Apple Pay at checkout (#PROJ-145)

### Changed
- User can sort products by price low to high or high to low (#PROJ-138)
- User can register a new account with phone number verification (#PROJ-130)

### Removed
- User can add a product to the wish list (#PROJ-150)
```

**Step 3.** Push. Pipeline runs in default **propose** mode. The GH
summary's **Stage 0** section shows:

| Operation | Count |
|---|---|
| 🟢 ADD       | 2 |
| 🟡 EDIT      | 1 |
| 🔴 DELETE    | 1 |
| ⚠️ Unmatched | 1 |

| Op | Scenario | Requirement | Score | Item |
|---|---|---|---|---|
| 🟢 ADD     | —      | AC-016 | —    | User can share a wishlist via email |
| 🟢 ADD     | —      | AC-017 | —    | User can pay with Apple Pay at checkout |
| 🟡 EDIT    | SC-013 | AC-013 | 0.62 | User can sort products by price low to high or high to low |
| 🔴 DELETE  | SC-014 | AC-014 | 0.50 | User can add a product to the wish list |

Plus one **Unmatched item**:

| Section | Best score | Reason | Item |
|---|---|---|---|
| Changed | 0.21 | no scenario cleared similarity threshold 0.5 | User can register a new account with phone number verification |

The "register with phone verification" wording shares too few tokens with
the existing AC-008 wording ("User can register a new account by filling
in first name last name email telephone and password fields") to clear
0.5. Two ways to handle it:

1. **Fix the wording in v1.1.0.md** to be closer to the existing AC ("User can register a new account with first name, last name, email, telephone, password, **and phone verification**").
2. **Lower the threshold** for this run: `python ci/release_diff.py --threshold 0.2`.

**Step 4.** Re-run with `apply_release_delta = true` (workflow_dispatch input). The pipeline:

1. Runs `python ci/release_diff.py --apply` first
2. Mutates `scenarios.json`:
   - SC-016 + SC-017 appended (status `new`, `release_added: v1.1.0`, issue `PROJ-123`/`PROJ-145`)
   - SC-013 description rewritten to the new wording, status `updated`, `last_changed_in_release: v1.1.0`
   - SC-014 status flipped to `deprecated`, `deprecated_in_release: v1.1.0`
3. Writes `release_notes/v1.1.0.lock.json` (frozen 17-scenario snapshot)
4. Runs the rest of the pipeline. Stage 1 (replay-first dispatch) sees the EDIT (SC-013 hash drift → re-record), the two ADDs (no asset → record), and replays the rest. Total Kane authoring cost ≈ 3 × Kane sessions, not 17.

**Step 5.** Commit the now-modified `scenarios.json`, the new `release_notes/v1.1.0.lock.json`, any new `tests/kane/<feat>/sc_*_test.md` assets, and the updated test_powerapps.py. v1.1.0 is now the new baseline.

---

## Adding a new acceptance criterion mid-release (no release notes change)

If you're not bumping the release version yet — just iterating between
releases — the existing flow still works: edit `requirements/*.txt`, push,
`manage_scenarios.py` adds the new AC. The release-notes flow is for
**versioned** changes that need to be tracked across releases.

---

## Rollback

`--apply` is the only step that mutates state. To roll back:

```bash
git checkout HEAD~1 -- scenarios/scenarios.json release_notes/<version>.lock.json
git checkout HEAD~1 -- tests/kane/   # if assets were recorded
```

The previous release's lock file is untouched, so `release_diff.py` will
re-propose the same operations on the next push.

---

## How Stage 0 interacts with Stage 2b

**Stage 0** decides *what changes*; **Stage 2b** scores the *confidence*
that the resulting test pool covers the release. The two are independent:
Stage 0 can produce `0` operations (release with no changes) and Stage 2b
will still score the existing pool. They appear in this order in the GH
summary:

```
Stage 0 · Agentic Release Notes        ← what changed
Stage 1 · Kane AI Functional Verification ← did the verifier still pass
Stage 2 · Scenario Catalog
Stage 2b · Scenario Confidence Analysis ← do we have enough coverage?
Stage 3+ · Test generation, regression, traceability, verdict
```

A release that proposes a lot of DELETEs but no ADDs/EDITs will lower the
Stage 2b confidence count (fewer scenarios). A release with many ADDs but
no Stage 1 verification on those new flows yet will show as `LOW`
confidence in Stage 2b until Kane records the new assets.

---

## Known limitations

1. **Jaccard matching is wording-sensitive.** A reworded AC that says the
   same thing in different words may not match — flag will land in
   `unmatched_items`. Either reword to align or lower the threshold.
2. **No release deletion.** Deleting a `release_notes/<version>.md` file
   doesn't roll the release back. Ship a new release that explicitly
   reverses the change.
3. **Lock files are tied to the commit.** A force-push that rewrites the
   lock file's commit will desync the diff engine. Treat
   `release_notes/*.lock.json` as immutable once committed.
4. **Stage 0 runs as advisory.** It does not block the pipeline if the
   diff fails. The `--apply` mutation is gated by the workflow_dispatch
   input, not by the release-notes file alone.
