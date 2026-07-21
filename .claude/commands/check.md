Run the full quality suite for this project and report results.

Execute each check as a **separate** Bash call (so output doesn't interleave), capturing both stdout and stderr. Run them in this order even if an earlier one fails — we want the full picture:

1. `uv run tox -e format 2>&1` — Ruff format check
2. `uv run tox -e lint 2>&1` — Ruff lint
3. `uv run tox -e test 2>&1` — pytest + coverage
4. `uv run pyright 2>&1` — type checking

After all four complete, produce a concise summary in this format:

```
FORMAT   ✓ / ✗  (if fail: list file:line violations)
LINT     ✓ / ✗  (if fail: list file:line:rule violations)
TESTS    ✓ / ✗  (if fail: test names + one-line failure reason each; coverage % if available)
TYPES    ✓ / ✗  (if fail: error count + first 5 errors)

Verdict: All checks passed  OR  Fix: FORMAT LINT TESTS TYPES (whichever failed)
```

Keep the failure details tight — skip tox boilerplate, virtualenv setup lines, and full tracebacks unless the traceback IS the error. Surface only what needs action.
