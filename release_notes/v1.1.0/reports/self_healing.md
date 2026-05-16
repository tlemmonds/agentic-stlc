# Self-Healing Report

_1 patches applied — 1 scenario(s) require pipeline rerun_

_Generated: 2026-05-16T06:44:31.365810+00:00_

## Patches Applied

### SC-002 — KANE_WRONG_TASK → Kane Objective

**Patched:** Navigate directly to https://ecommerce-playground.lambdatest.io/ — User can list all tasks ordered by due date, with overdue tasks pinned to the top. Stop immediately once confirmed. Do not navigate further.
**File:** `scenarios/scenarios.json`

---

## Patches Skipped

- **SC-005** (UNKNOWN_FAILURE): Failure type 'UNKNOWN_FAILURE' requires manual investigation.
- **SC-006** (UNKNOWN_FAILURE): Failure type 'UNKNOWN_FAILURE' requires manual investigation.
- **SC-007** (DATA_UNAVAILABLE): Failure type 'DATA_UNAVAILABLE' requires manual investigation.

## Rerun Required

The following scenarios were patched and must be re-executed in the next pipeline run:

- `SC-002`

> Set `FULL_RUN=false` and push — the pipeline will run only these updated scenarios via incremental selection.
