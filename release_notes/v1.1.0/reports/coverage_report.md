# Requirement Coverage Analysis Report

_Generated: 2026-05-18 04:45 UTC_

## Coverage Summary

| Metric | Value |
|--------|-------|
| Total Requirements | 8 |
| Fully Covered | 7 (87.5%) |
| Partially Covered | 0 |
| Uncovered | 1 |
| Negative Test Coverage | 12.5% |
| Mobile Coverage | 0.0% |
| Android Coverage | 0.0% |
| HyperExecute Coverage | 87.5% |
| Flaky Requirements | 0 |
| High-Risk Requirements | 1 |
| Missing Scenario Types | 2 |

## Feature Coverage Heatmap

| Feature | Criticality | Total | Covered | Partial | Uncovered | Failed | Flaky |
|---------|-------------|-------|---------|---------|-----------|--------|-------|
| GENERAL | MEDIUM | 6 | 5 | 0 | 1 | 0 | 0 |
| FILTER | LOW | 2 | 2 | 0 | 0 | 0 | 0 |

## Requirement Coverage Detail

| Requirement | Coverage | Tests | Pass | Fail | Missing | Risk |
|-------------|----------|-------|------|------|---------|------|
| `AC-001` | FULL | 2 | 2 | 0 | 0 | LOW |
| `AC-002` | FULL | 2 | 2 | 0 | 0 | LOW |
| `AC-003` | FULL | 2 | 2 | 0 | 0 | LOW |
| `AC-004` | FULL | 2 | 2 | 0 | 0 | LOW |
| `AC-005` | NONE | 0 | 0 | 0 | 0 | HIGH |
| `AC-006` | FULL | 2 | 2 | 0 | 1 | LOW |
| `AC-007` | FULL | 2 | 2 | 0 | 1 | LOW |
| `AC-008` | FULL | 2 | 2 | 0 | 0 | LOW |

## Per-Requirement Detail

### AC-001 — GENERAL

> User can create a task with a title and a due date

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** MEDIUM  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Covered by:** SC-001

### AC-002 — GENERAL

> User can list all tasks ordered by due date, with overdue tasks pinned to the top

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** MEDIUM  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Covered by:** SC-002

### AC-003 — GENERAL

> User can mark a task as complete

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** MEDIUM  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Covered by:** SC-003

### AC-004 — GENERAL

> User can edit a task's title or due date

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** MEDIUM  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Covered by:** SC-004

### AC-005 — GENERAL

> User can delete a task

- **Coverage Status:** NONE  |  **Risk:** HIGH  |  **Criticality:** MEDIUM  |  **Kane:** skipped
- **Functional Coverage:** 0.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** none
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Execution:** 0 total | 0 passed | 0 failed | 0 flaky

### AC-006 — FILTER

> User can filter the task list by status (active / done / all)

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** LOW  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 0.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Missing Scenario Types:**
- `[NEGATIVE]` Apply filter that produces no results

**Covered by:** SC-006

### AC-007 — FILTER

> User can attach a colored label to a task and filter by label

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** LOW  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 0.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Missing Scenario Types:**
- `[NEGATIVE]` Apply filter that produces no results

**Covered by:** SC-007

### AC-008 — GENERAL

> User can view archived tasks on the Archive page and restore them to the active list

- **Coverage Status:** FULL  |  **Risk:** LOW  |  **Criticality:** MEDIUM  |  **Kane:** passed
- **Functional Coverage:** 100.0%  |  **Negative Coverage:** 100.0%
- **Browsers Tested:** chrome, firefox
- **Flaky:** no

**Coverage Categories:**
| Happy Path | Negative | Edge Case | Mobile | Android | HyperExecute | Regression |
|------------|----------|-----------|--------|---------|--------------|------------|
| ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

**Execution:** 2 total | 2 passed | 0 failed | 0 flaky

**Covered by:** SC-008

---
_Coverage analysis generated by Agentic STLC pipeline_

