# Migration — Inline objectives → Kane CLI `_test.md` assets

This guide explains the architectural change introduced on the
`kane-testmd-migration` branch. Read it once before adding new acceptance
criteria so you understand which path your work will take.

---

## Why we changed the model

The pre-migration pipeline regenerated everything from scratch on every run:

- Each AC's Kane objective lived inline in a Python dict
  (`_KANE_TASK_OVERRIDES` in `ci/analyze_requirements.py`).
- Each AC's Playwright body lived inline in another Python dict
  (`PLAYWRIGHT_BODIES` in `ci/agent.py`).
- Kane planned the run from the objective text every time — costing tokens
  and producing slightly different step plans run-to-run.
- A change to a single AC's wording forced re-running every other AC.

The new model treats each AC as a **durable test asset** authored once and
replayed forever. Kane CLI 0.3.1's `_test.md` format is the unit of reuse;
`@import` lets multiple scenarios share helper flows.

---

## Mental model in one sentence

> **Requirements → durable `_test.md` assets → replay forever; re-author
> only when the AC's description hash changes.**

---

## Where things live now

| Concern | Before | After |
|---|---|---|
| AC text → Kane objective | inline dict in `analyze_requirements.py` | `objective` field of `tests/kane/<feat>/sc_*_test.md` frontmatter |
| AC text → Playwright body | inline dict in `agent.py` | Kane `--code-export` writes Playwright into `tests/playwright/exported/<sc>/` per run; `ci/collect_kane_exports.py` assembles them |
| "Has the AC changed?" | recomputed every Stage 2 from `source_description` | persisted as `description_hash` in the `_test.md` frontmatter |
| Reusable helper flows | none — pasted into objective strings | `tests/kane/helpers/*_test.md`, pulled in via `@import` |
| Bootstrap a new AC | edit two Python dicts | Kane records the asset on first run (CI hands the recorder the AC text) |

---

## Components added on this branch

| File | Role |
|---|---|
| [`ci/replay_policy.py`](ci/replay_policy.py) | Per-AC decision: `replay` / `record` / `rerecord` / `skip`. Hash function lives here. CLI: `python ci/replay_policy.py` previews the next run's decisions. |
| [`ci/kane_replay.py`](ci/kane_replay.py) | Wraps `kane-cli run <file>_test.md`. Result shape matches the legacy `run_kane()` so it slots into existing reporting. |
| [`ci/kane_record.py`](ci/kane_record.py) | Wraps `kane-cli run "<objective>" --name <slug>`. Persists the resulting `_test.md` to the canonical asset path; merges pipeline metadata into the frontmatter. |
| [`ci/kane_dispatch.py`](ci/kane_dispatch.py) | Stage 1 entrypoint. Reads `scenarios.json` + asset directory, computes decisions, fans out across the 5-worker pool, writes `reports/replay_decisions.json`. |
| `tests/kane/helpers/*_test.md` | Reusable building blocks. Validated as helpers — Kane refuses to import non-helper assets. |
| `tests/kane/<feature>/sc_*_test.md` | One asset per scenario. Frontmatter is the durable record of what the AC means; markdown body is the replayable script. |
| `tests/playwright/exported/<sc>/` | Per-scenario Kane Playwright export. Re-written every run (replay or record). |

---

## What still works exactly as before

- **HyperExecute Stage 5** — same `hyperexecute.yaml`, same browser matrix
  (chrome + firefox), same Python conftest, same `pytest_selection.txt`.
- **Traceability matrix + release verdict** — same scoring logic, same
  GREEN/YELLOW/RED thresholds, same Stage 8 verdict format.
- **Scenario IDs** — `SC-001` still maps to the same AC. `scenarios.json`
  gains a `description_hash` field on next sync but no IDs change.
- **GitHub Actions structure** — still two jobs (`analyze` + `orchestrate`)
  feeding a `summary` job. Two new artifacts published: `kane-test-md-assets`
  and `replay-decisions`.

---

## What changes for the AC author

### Adding a new acceptance criterion

1. Edit `requirements/*.txt` — add the new AC line under `Acceptance Criteria:`.
2. Push.
3. The pipeline:
   - Stage 2 syncs the AC into `scenarios.json` with a fresh `SC-xxx` ID.
   - Stage 1 sees no asset on disk → records one via Kane (one Kane authoring
     run for that AC; everything else still replays).
   - The recorded asset is uploaded as the `kane-test-md-assets` artifact —
     download it, commit it under `tests/kane/<feature>/`, and push to the
     branch so subsequent runs replay instead of re-record.

### Editing an existing AC's wording

1. Edit the AC line in `requirements/*.txt`.
2. Push.
3. Stage 1's policy sees the description hash drift, marks the asset
   `rerecord`, and Kane authors a fresh `_test.md`. Replace the on-disk
   asset with the freshly recorded one and commit the updated hash.

### Forcing a full re-record (e.g. AUT shape change)

Use `workflow_dispatch` with `regenerate_tests: true`. This sets
`FORCE_RE_AUTHOR=true`, which forces every `replay` decision to flip to
`rerecord` for that one run.

### Editing a helper

Edit `tests/kane/helpers/<name>_test.md` directly. All scenarios that
`@import` it pick up the change on next replay; no recording needed because
the scenarios themselves haven't changed.

---

## Token / cost model

| Run type | Kane authoring tokens | Browser sessions |
|---|---|---|
| All assets present, no AC changes | **~0** | 1 per AC (replay) |
| 1 AC added or edited | 1× authoring | 1 per AC (1 record + N–1 replay) |
| `regenerate_tests` forced | N× authoring | 1 per AC (all record) |

Compare to the pre-migration pipeline: **N× authoring on every run**,
unconditionally.

---

## Verifying the migration locally

```bash
# Preview what the next run will do for every scenario
python ci/replay_policy.py

# Sample output:
#   SC-001  replay     hash=b8b5eb1d31c4  hash matches recorded asset
#   SC-003  record     hash=8062407e775a  no asset on disk yet
#   …
```

Then run Stage 1 normally:

```bash
LT_USERNAME=… LT_ACCESS_KEY=… DEMO_MODE=false \
  python ci/analyze_requirements.py --requirements requirements
```

The output `requirements/analyzed_requirements.json` gains two new fields
per AC: `kane_asset_path` and `kane_replay_decision`. The decisions are
also dumped to `reports/replay_decisions.json`.

---

## Known limitations / open questions

1. **Auto-save in agent mode.** Kane CLI 0.3.1's docs only confirm that
   TUI sessions auto-save to `.testmuai/tests/<name>_test.md`. In
   `--agent --headless` mode the behavior is unconfirmed. `kane_record.py`
   handles both: if Kane writes the asset, we copy it to the canonical
   path; otherwise we synthesize one from the captured run output. The
   synthesized variant captures step summaries verbatim, which is enough
   for replay but may need cleanup before commit.
2. **`@import` only allows helper files.** This is enforced by Kane
   itself (error message: *"only helpers may be imported"*). To make a
   file importable, set `helper: true` in its frontmatter and place it
   under `tests/kane/helpers/`.
3. **Description hash sensitivity.** The hash is computed against a
   whitespace-normalized lowercased AC string. Editing wording (e.g.
   "and" → "&") triggers re-authoring. This is intentional — a wording
   change implies a possible semantic change.
4. **Cart inventory dependency.** All cart helpers point at
   `product_id=47` (HP LP3065) because `product_id=28` (HTC Touch HD)
   went out of stock. If 47 also goes out of stock, edit
   `tests/kane/helpers/open_product_test.md` — every dependent scenario
   picks up the change automatically.

---

## Rollback

The legacy paths (`_KANE_TASK_OVERRIDES`, `PLAYWRIGHT_BODIES`,
`_OBJECTIVE_OVERRIDES`) are still present in source. To revert:

```bash
git checkout product -- ci/analyze_requirements.py ci/agent.py ci/manage_scenarios.py
```

The `tests/kane/` directory and the new `ci/kane_*.py` modules can stay —
they have no effect unless `analyze_requirements.py` calls into
`kane_dispatch`.
