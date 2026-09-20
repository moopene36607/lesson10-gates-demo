# lesson10-gates-demo

Demo repository for a recorded lesson on CI quality gates (FastAPI issue tracker).

- `.github/workflows/gates.yml` — three jobs: `tasks-lint`, `pytest`, `severity-gate`
- `tasks_lint.py` — parallel-safety linter for `tasks.md` (exit 1 on conflicts)
- `gate_from_severity.py` — turns an AI review severity summary into a blocking gate
- `app/`, `tests/` — the FastAPI sample under test
