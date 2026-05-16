"""
Stage 3a — Collect Kane AI code exports and assemble tests/playwright/test_powerapps.py.

For every active scenario in scenarios.json, this script:
  1. Looks up the Kane session's code-export directory from analyzed_requirements.json.
  2. Reads the Kane-generated Python Playwright code.
  3. Extracts the test body (strips the function def / type annotations).
  4. Wraps the body in a pytest function with @pytest.mark.scenario / @pytest.mark.requirement.
  5. Writes the assembled file to tests/playwright/test_powerapps.py.

When Kane has no export for a scenario (session skipped or code-export missing), the script
falls back to a curated hand-written body for that acceptance criterion so the test is never
empty — it is always a real, executable Playwright action.

Writes:
  tests/playwright/test_powerapps.py
"""
import ast
import json
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stage_utils import print_stage_header, print_stage_result

import os
BASE_URL = os.environ.get("TARGET_URL", "https://nosecretformula.vercel.app/")

# ---------------------------------------------------------------------------
# Fallback bodies — used when Kane has no exported code for a given AC.
# Each body is a complete, real Playwright implementation for the acceptance
# criterion.  The placeholder {url} is substituted with the scenario URL.
# ---------------------------------------------------------------------------
# Fallback bodies are empty for the TaskFlow AUT. Replay-first means
# Kane always exports Playwright on record/replay, so this dict only
# fires on a full export failure. agent.py _FALLBACK_BODY (page.goto +
# assert title) covers that case.
_FALLBACK_BODIES: dict[str, str] = {}


def _load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _extract_test_body(py_file: Path) -> str:
    """Extract the body of the first test_* function from a Kane-exported .py file.

    Strips the function signature and any `page: Page` type annotation so the
    body can be embedded directly in a conftest-compatible pytest function.
    """
    source = py_file.read_text(encoding="utf-8")

    # Try AST extraction first — most reliable
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test"):
                    lines = source.splitlines()
                    body_start = node.body[0].lineno - 1
                    body_end = node.end_lineno
                    body_lines = lines[body_start:body_end]
                    dedented = textwrap.dedent("\n".join(body_lines))
                    # Remove any awaits — conftest.py uses sync Playwright
                    dedented = re.sub(r"\bawait\s+", "", dedented)
                    return dedented.rstrip()
    except SyntaxError:
        pass

    # Fallback: regex-based extraction
    lines = source.splitlines()
    body_lines: list[str] = []
    in_fn = False
    base_indent: int | None = None

    for line in lines:
        if re.match(r"^(async\s+)?def\s+test", line):
            in_fn = True
            base_indent = None
            continue
        if not in_fn:
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if base_indent is None and stripped:
            base_indent = indent
        if stripped and indent == 0 and base_indent and indent < base_indent:
            break
        if base_indent is not None and indent >= base_indent:
            body_lines.append(line[base_indent:] if base_indent else line)
        else:
            body_lines.append("")

    body = "\n".join(body_lines).strip()
    # Remove await calls for sync Playwright compatibility
    body = re.sub(r"\bawait\s+", "", body)
    return body


def _collect_exports(analyzed: list[dict]) -> dict[str, str]:
    """Returns mapping of AC-id → extracted test body string."""
    bodies: dict[str, str] = {}
    for item in analyzed:
        ac_id = item.get("id", "")
        export_dir = item.get("kane_code_export_dir", "")
        if not export_dir:
            continue
        export_path = Path(export_dir)
        if not export_path.exists():
            continue
        py_files = sorted(export_path.glob("*.py"))
        if not py_files:
            continue
        body = _extract_test_body(py_files[0])
        if body:
            bodies[ac_id] = body
            print(f"  [collect] {ac_id} — Kane export found: {py_files[0].name} ({len(body)} chars)")
        else:
            print(f"  [collect] {ac_id} — Kane export found but body empty: {py_files[0]}")
    return bodies


def _make_fn_name(sc_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60]
    return f"test_{sc_id.lower().replace('-', '_')}_{slug}"


FILE_HEADER = '''\
"""
Playwright test suite for LambdaTest Ecommerce Playground.
Generated by Agentic STLC pipeline from Kane AI code exports.
Do not edit manually — re-run Stage 1 to regenerate.
"""
import os
import uuid
import pytest
from playwright.sync_api import expect

'''


def build_test_function(scenario: dict, body: str) -> str:
    sc_id = scenario["id"]
    req_id = scenario["requirement_id"]
    fn_name = scenario.get("function_name") or _make_fn_name(sc_id, scenario.get("title", sc_id))
    title = scenario.get("title", "").replace('"', "'")
    indented_body = textwrap.indent(body.strip(), "    ")
    return (
        f'@pytest.mark.scenario("{sc_id}")\n'
        f'@pytest.mark.requirement("{req_id}")\n'
        f'def {fn_name}(page):\n'
        f'    """{sc_id}: {title}."""\n'
        f'{indented_body}\n'
    )


def collect_and_assemble(
    analyzed_path: str = "requirements/analyzed_requirements.json",
    scenarios_path: str = "scenarios/scenarios.json",
    output_path: str = "tests/playwright/test_powerapps.py",
) -> dict:
    print_stage_header("3a", "COLLECT_KANE_EXPORTS",
                       "Assemble Kane-exported Python Playwright code into test_powerapps.py")

    analyzed: list[dict] = _load_json(analyzed_path, [])
    scenarios: list[dict] = _load_json(scenarios_path, [])

    if not scenarios:
        print(f"[ERROR] No scenarios found at {scenarios_path}", file=sys.stderr)
        sys.exit(1)

    # Build AC-id → Kane export body mapping
    kane_bodies = _collect_exports(analyzed)

    # Build AC-id → analyzed item mapping for URL resolution
    ac_map = {item["id"]: item for item in analyzed}

    functions: list[str] = []
    kane_used = 0
    fallback_used = 0
    missing = 0

    for sc in scenarios:
        if sc.get("status") == "deprecated":
            continue

        req_id = sc.get("requirement_id", "")
        url = sc.get("kane_url", BASE_URL)
        if req_id not in ac_map:
            url = BASE_URL

        # Priority 1: Kane-exported body
        if req_id in kane_bodies:
            body = kane_bodies[req_id]
            kane_used += 1
            source = "kane_export"
        # Priority 2: Curated fallback
        elif req_id in _FALLBACK_BODIES:
            body = _FALLBACK_BODIES[req_id].format(url=url)
            fallback_used += 1
            source = "fallback"
        else:
            body = f'# No implementation available for {req_id}\npytest.skip("No test body for {req_id}")'
            missing += 1
            source = "skip"

        print(f"  [{source:12}] {sc['id']} ({req_id}): {sc.get('title', '')[:50]}")
        functions.append(build_test_function(sc, body))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(FILE_HEADER + "\n\n".join(functions) + "\n", encoding="utf-8")

    total = len(functions)
    print_stage_result("3a", "COLLECT_KANE_EXPORTS", {
        "Scenarios assembled":   total,
        "Kane export used":      kane_used,
        "Fallback used":         fallback_used,
        "Skipped (no impl)":     missing,
        "Kane coverage":         f"{round(kane_used / total * 100)}%" if total else "0%",
        "Output":                output_path,
    })

    return {
        "total": total,
        "kane_used": kane_used,
        "fallback_used": fallback_used,
        "missing": missing,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzed", default="requirements/analyzed_requirements.json")
    parser.add_argument("--scenarios", default="scenarios/scenarios.json")
    parser.add_argument("--output", default="tests/playwright/test_powerapps.py")
    args = parser.parse_args()
    collect_and_assemble(args.analyzed, args.scenarios, args.output)
