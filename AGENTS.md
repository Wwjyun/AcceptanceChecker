# AGENTS.md

Guidance for AI agents working on this repository.

## Project Context

AcceptanceChecker is a Python 3.9+ AOI raw-image acceptance checker. It includes:

- `acceptance_checker/core`: image loading, normalization, metrics, defect detection, threshold config, judging, and pipeline orchestration.
- `acceptance_checker/reporting`: text, CSV, drift, ranked recommendations, and cross-batch history-log reporting.
- `acceptance_checker/gui`: PySide6 GUI, preview widgets, workers, ROI selection, and threshold dialogs.
- `acceptance_checker/cli`: batch CLI entry points.
- `tests`: pytest coverage.
- `smoketest.py`: end-to-end offscreen GUI and CLI smoke test.

Prefer existing project patterns over new abstractions. Keep core logic independent from Qt so CLI, tests, and GUI can share the same pipeline.

## Dependency Rules

Use the repository virtual environment as the source of truth:

```powershell
.\env\Scripts\python.exe -m pip install -e ".[dev]"
```

Run project commands through `.\env\Scripts\python.exe`. Fall back to system Python only if `env` is missing and the user explicitly accepts that fallback.

Runtime dependencies belong in `requirements.txt` and `[project].dependencies` in `pyproject.toml`.

Development dependencies belong in `[project.optional-dependencies].dev`.

Do not commit generated caches or local environments:

- `env/`
- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `*.pyc`
- `acceptance_checker.egg-info/`
- `build/`
- `dist/`

## Validation

After meaningful changes, run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\王\.codex\skills\acceptance-checker\scripts\validate_project.ps1
```

The validation script installs editable dev dependencies, runs compile checks, Ruff, Mypy, pytest, and `smoketest.py` with Qt offscreen mode.

If iterating quickly, at minimum run:

```powershell
.\env\Scripts\python.exe -m compileall -q acceptance_checker tests main.py smoketest.py
.\env\Scripts\python.exe -m pytest -q
```

Treat Mypy as advisory while CI has `continue-on-error: true`; still report its failure reason.

## Git Workflow

Before editing, inspect:

```powershell
git status --short --branch
```

The worktree may contain user changes. Do not revert or stage unrelated files.

After validation passes:

1. Review `git diff --stat`.
2. Stage only intended files.
3. Commit with a concise message.
4. Push the current branch.

If the branch lacks an upstream:

```powershell
git push -u origin HEAD
```

## Packaging And Release

When the user asks to package, 打包, release, or git release:

1. Run full validation first.
2. Confirm `acceptance_checker.__version__` matches `pyproject.toml`.
3. Clean only project-local `build/` and `dist/` outputs.
4. Build:

```powershell
.\env\Scripts\python.exe -m pip install build
.\env\Scripts\python.exe -m build
```

5. Create an annotated tag `v<version>` if missing.
6. Push the branch and tag.
7. Create a GitHub release and attach `dist/*` artifacts, using `gh release create` when available.

Do not create a release from failing validation.
