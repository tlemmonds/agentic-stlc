# Many-to-one — requirement ↔ scenarios contract

Branch `feature/many-to-one`. This document is the **binding data contract** for
the refactor: every stage script must conform to it. One-to-one (the TaskFlow
project) is the N=1 special case and must keep working unchanged.

## Why

Customers arrive with an existing Kane / Test Manager suite. The BRD acceptance
criterion is the contract; the suite is the asset. One AC is typically covered
by several existing cases (EverDemo: 11 BRD ACs, 24 cases). The pipeline must
ingest and **reuse** those cases, roll their results up to the AC, and only ever
propose a new test where an AC has zero coverage.

## Identifiers

| Thing | Format | Notes |
|---|---|---|
| Requirement | `AC-001` … | Sequential from the requirements file(s), as today. `brd_ref` preserves the customer's own label (`AC-02`, `FR-S4`). |
| Scenario | `SC-001` … | Immutable, append-only, as today. |
| Feature | UPPER_SNAKE (`ORIGINATION`) | Explicit on the scenario; keyword classification is the fallback only. |

## `scenarios/scenarios.json` record

Existing keys are unchanged. New keys (all optional; absence == legacy 1:1 generated scenario):

```jsonc
{
  "id": "SC-013",
  "test_case_id": "TC-013",
  "requirement_id": "AC-002",           // MANY scenarios may share one requirement_id
  "brd_ref": "AC-02",                   // customer's own label for the requirement
  "feature": "SERVICING",
  "title": "Complete cash advance wizard and reconcile receipt",
  "description": "<asset H1 + first paragraph>",
  "status": "active",                   // new | updated | active | deprecated
  "source": "ingested",                 // ingested | generated   (default generated)
  "kane_asset": "tests/kane/servicing/complete-cash-advance-wizard-and_test.md",
  "kane_testcase_id": "01KWT064375JRKG0PSFMS40C5E",
  "kane_folder_id": "01KWMPVDY320N7N9B1RMK8G3C3",
  "kane_session_name": "complete-cash-advance-wizard-and",
  "tags": ["servicing", "cash-advance", "positive"],
  "export_kind": "testmu",              // testmu | vanilla   (default vanilla)
  "playwright_export": "tests/kane/servicing/output-complete-cash-advance-wizard-and/playwright-python-code",
  "function_name": null                 // vanilla only
}
```

Rules
- `kane_asset` set ⇒ the asset path is authoritative; `replay_policy.asset_path_for()` naming is **not** applied.
- Ingested assets keep their original file stem. Kane CLI's `testmd run` walker
  reuses the TMS test case through the sibling `output-<stem>/meta.json`; renaming
  the stem or dropping the sidecar dir creates a *new* TMS case on every run.
- Pipeline sidecar `<asset>.meta.json` (existing convention) gains
  `hash_source: "asset" | "description"`. For ingested scenarios
  `description_hash` is the SHA-256[:12] of the **asset file body** (drift = the
  test was edited), not of the AC text.

## `requirements/analyzed_requirements.json` (Stage 1 output)

Per requirement, existing keys unchanged; `kane_status` becomes the **roll-up**; add:

```jsonc
{
  "id": "AC-002",
  "brd_ref": "AC-02",
  "description": "...",
  "kane_status": "passed",              // roll-up, see below
  "kane_links": ["...", "..."],         // union of scenario links
  "kane_code_export_dir": "...",        // first scenario's (legacy consumers)
  "scenarios": [
    { "scenario_id": "SC-013", "kane_status": "passed", "kane_links": ["..."],
      "kane_one_liner": "...", "kane_summary": "...", "kane_duration": 88.1,
      "kane_asset_path": "...", "kane_code_export_dir": "...",
      "kane_replay_decision": "replay", "kane_session_id": "..." }
  ]
}
```

Roll-up (`ci/project_config.py::rollup_kane_status`):
- any scenario `failed` / `error` / `timeout` → `failed`
- ≥1 `passed` and no failures → `passed`
- all `skipped` → `skipped`
- none executed → `not_run`

`reports/kane_results.json` becomes **one entry per scenario** and carries both
`scenario_id` and `requirement_id`.

## Stage-by-stage

| Stage | Script | Change |
|---|---|---|
| 0 | `release_diff.py` | Match `Changed`/`Removed` bullets against **requirement** descriptions (lock now stores `requirements` alongside `scenarios`; fall back to scenario descriptions for legacy locks). Ops carry `requirement_id`; `sc_id` may be a list. DELETE → deprecate every scenario of that requirement. EDIT → update the requirement text and set `review_required: true` on its scenarios; **never** auto-rerecord ingested assets. ADD → creates the requirement; creates a scenario only when `scenarios.auto_create` is true. |
| 1 | `kane_dispatch.py`, `analyze_requirements.py`, `replay_policy.py`, `kane_replay.py` | Iterate **scenarios** (non-deprecated), not requirements. `decide()` honours `kane_asset` + `hash_source`; an ingested scenario with a missing asset → `skip` (reason `asset_missing`), never `record`. `kaneai.auto_record: false` blocks `record`/`rerecord` for all scenarios (gaps are reported, not filled). Replay runs with `cwd=repo root` so `.testmuai/variables/*.json` loads; adds `--no-adaptive-heal` unless `kaneai.adaptive_heal: true`. Build the per-requirement roll-up described above. |
| 2 | `agent.py::sync_scenarios`, `manage_scenarios.py`, `skills/scenario_generation.py` | Group existing scenarios by requirement (**list**). Keep every existing scenario. Ingested: `active`, or `updated` when the asset hash drifted from the sidecar. Generated: today's description comparison. Requirement with zero scenarios → create one generated scenario only if `scenarios.auto_create` (default `true` for backward compat); otherwise leave uncovered. |
| 2b | `scenario_confidence.py` | One record per requirement; `scenario_ids: []`; coverage dimensions are the **union** across its scenarios (tags `negative`/`edge`/`boundary`/`mobile` count, plus keyword detection). Zero scenarios → existing `CRITICAL_GAP` path. |
| 3 | `collect_kane_exports.py` | Per scenario. `export_kind == "testmu"` → copy `playwright_export` dir to `tests/playwright/native/<sc_id_lower>/` (test.py, requirements.txt) and ensure `tests/playwright/native/run_with_junit.py` exists (framework-owned; JUnit fragment `reports/native_<SC-ID>.xml`, testcase name = `SC-ID`). Vanilla → existing assembly into `test_powerapps.py`. |
| 4 | `select_tests.py` | Selection line per scenario: vanilla → `tests/playwright/test_powerapps.py::<fn>`; testmu → `tests/playwright/native/<sc_id_lower>`. |
| 5 | `hyperexecute.yaml`, new `ci/run_selected.py` | `testRunnerCommand: python ci/run_selected.py "$test"` — directory → `cd` + `run_with_junit.py`; otherwise the existing pytest invocation. `pre:` also installs `tests/playwright/native/requirements.txt` when present. |
| 6 | `normalize_artifacts.py` | New source `native_junit`: `reports/native_<SC>.xml` → one record `{scenario_id, browser: "chrome", status, source: "native_junit"}`. |
| 7 | `build_traceability.py` | `rows` stay **one per scenario** (same schema + `brd_ref`, `source`). New `requirements` list: `{requirement_id, brd_ref, scenario_ids, kane_status, playwright_status, overall}`. Requirement `overall = passed` iff every executed scenario passed, ≥1 executed, and Kane roll-up passed. `summary.requirements_covered` = requirements with ≥1 non-deprecated scenario; `summary.untested_requirements` = requirements with no executed scenario (includes uncovered); `executed/passed/pass_rate` stay scenario-level. |
| 7b | `coverage_analysis.py` | Already list-based; use explicit `scenario.feature`; taxonomy from config. |
| 8 | `release_recommendation.py` | Unchanged semantics; reads the new summary. |
| 8a | `failure_intelligence.py` | `trace_by_ac` → `dict[str, list[row]]`; classify per scenario. |
| 9 | `write_github_summary.py` | Requirement tables show `SC-013, SC-014`; per-scenario rows in the matrix. |
| — | `validate_report.py`, `notify_agent.py` | Tolerate the new fields; counts from `summary`. |

## Feature taxonomy from config

`agentic-stlc.config.yaml`:

```yaml
features:
  ORIGINATION:
    criticality: HIGH
    keywords: [apply, application, decision, underwriting, approve, counter-offer, decline, rfai]
    expected_scenarios:
      - {type: happy_path, description: "Approve at requested amount"}
      - {type: negative,   description: "Decline on hard stop"}
  SERVICING: { criticality: HIGH, keywords: [cash advance, payment, schedule, balance] }
  AUTH:      { criticality: HIGH, keywords: [sign in, login, disabled, 403] }

scenarios:
  auto_create: false          # never fabricate a scenario for an uncovered requirement

kaneai:
  auto_record: false          # never spend authoring tokens; report gaps instead
  adaptive_heal: false        # a replay miss is a finding, not something to heal silently
```

`ci/project_config.py` exposes `feature_taxonomy()` returning
`(criticality: dict, keywords: dict, expected: dict)` with the hardcoded TaskFlow
tables as the fallback when the config has no `features:` block. All three
consumers (`build_traceability`, `scenario_confidence`, `coverage_analysis`)
must go through it. `classify_feature(text, explicit=None)` returns `explicit`
when set.

## Ingest

`ci/ingest_kane_pack.py --source <dir> --map <yaml> [--apply]` walks a Kane
CLI pack (`<stem>_test.md` + `output-<stem>/`), copies each pair verbatim into
`tests/kane/<feature>/`, and appends scenario records per the mapping file:

```yaml
target_url: https://everdemo.onrender.com/
folders:                       # source folder → feature
  Origination: ORIGINATION
  Servicing:   SERVICING
  Auth:        AUTH
cases:                         # glob on the source path → requirement
  "Origination/**":                       {requirement: AC-001, brd_ref: AC-01}
  "Servicing/Svc-CashAdv-Validate/**":    {requirement: AC-003, brd_ref: AC-03}
exclude:
  - "Origination/Orig-Pairwise-Covaric/**"
```

Without `--apply` it prints the proposed scenario table and the list of
**uncovered requirements**. It never writes a `_test.md`.
