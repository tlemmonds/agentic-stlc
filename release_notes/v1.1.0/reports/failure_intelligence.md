# Failure Intelligence Report

_Generated: 2026-05-16T06:44:31.294929+00:00_

## Executive Summary

- Total failures: **4**
- Classified: **2** / 4
- Auto-remediable: **1** (25%)

- Failure clusters:
  - `KANE_WRONG_TASK`: SC-002
  - `UNKNOWN_FAILURE`: SC-005, SC-006
  - `DATA_UNAVAILABLE`: SC-007

## Failure Analysis

### SC-002 — KANE_WRONG_TASK (AC-002)

**Kane result:** failed — "checked task ordering on nosecretformula.vercel.app"
**Playwright result:** chrome: passed | firefox: passed
**Evidence:** Goal: open the Tasks list and confirm that overdue tasks are pinned to the top and the remaining tasks are sorted by due date.
The run reached the site and reviewed the tasks list view through the poi
**Sessions:** [Session 1](https://automation.lambdatest.com/test?testID=KXOJM-KIDJM-FIQZB-FPKIS) | [Session 2](https://automation.lambdatest.com/test?testID=OJX20-CJQRD-YMSNU-NTJXX)
**Auto-remediation:**
> Add explicit URL navigation to the Kane task override for this requirement. Start with the exact product/page URL instead of the homepage.
> For SC-002: begin the Kane objective with a direct URL (e.g. https://ecommerce-playground.lambdatest.io/index.php?route=product/product&product_id=28) so Kane lands on the correct page immediately. The current one_liner was: "checked task ordering on nosecretformula.vercel.app". Objective should reflect: "User can list all tasks ordered by due date, with overdue tasks pinned to the to".
**Patch target:** `kane_task_override`

---

### SC-005 — UNKNOWN_FAILURE (AC-005)

**Kane result:** skipped — ""
**Playwright result:** chrome: passed | firefox: passed
**Evidence:** skipped: scenario marked deprecated
**Sessions:** [Session 1](https://automation.lambdatest.com/test?testID=KY2OO-C5P8D-KNU75-ND2RT) | [Session 2](https://automation.lambdatest.com/test?testID=P6Z7H-SUTCG-NVWTO-RJHRZ)
**Auto-remediation:**
> Manual investigation required. Failure type could not be classified automatically. Review session logs and screenshots.
> For SC-005: no classification matched. Inspect the LambdaTest session video, HyperExecute task logs, and Kane session link for clues.
**Patch target:** `none`

---

### SC-006 — UNKNOWN_FAILURE (AC-006)

**Kane result:** failed — "tested task status filtering on nosecretformula.vercel.app"
**Playwright result:** chrome: passed | firefox: passed
**Evidence:** The run attempted to verify that the Tasks page can filter the task list by status (Active / Done / All).
It successfully opened the No Secret Formula TaskFlow app and entered a new task title (“Test 
**Sessions:** [Session 1](https://automation.lambdatest.com/test?testID=KQN37-E8KWB-GCKDS-U7SOV) | [Session 2](https://automation.lambdatest.com/test?testID=QG1IY-IHWJA-MTG2C-1ICBB)
**Auto-remediation:**
> Manual investigation required. Failure type could not be classified automatically. Review session logs and screenshots.
> For SC-006: no classification matched. Inspect the LambdaTest session video, HyperExecute task logs, and Kane session link for clues.
**Patch target:** `none`

---

### SC-007 — DATA_UNAVAILABLE (AC-007)

**Kane result:** failed — "filled in login details on kaneai-playground.lambdatest.io."
**Playwright result:** chrome: data_unavailable | firefox: data_unavailable
**Evidence:** The run appeared to be walking through the KaneAI Playground guided flow (enable notifications → choose environment → switch to Mobile App → enter login details).
It successfully reached the “Choose E
**Auto-remediation:**
> No execution data. Verify HyperExecute received this test in pytest_selection.txt and BROWSERS env var is set correctly.
> For SC-007: check reports/pytest_selection.txt contains the test node ID. Re-run with FULL_RUN=true to force inclusion. Ensure BROWSERS env var is populated in hyperexecute.yaml.
**Patch target:** `none`

---
