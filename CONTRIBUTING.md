# Contributing to Anjor

Thank you for your interest in contributing. Anjor is in active early development — contributions that align with the [product vision](vision.txt) are very welcome.

---

## Before You Start

- Check [open issues](https://github.com/anjor-labs/anjor/issues) to avoid duplicating work.
- For anything beyond a typo fix, open an issue first to discuss the approach.
- Phase 1 (tool call observability) is the current focus. See `CLAUDE.md` for what's in scope.

---

## Development Setup

Requires Python 3.11+.

```bash
git clone https://github.com/anjor-labs/anjor.git
cd anjor
bash scripts/dev_setup.sh   # creates .venv, installs deps, copies .env
source .venv/bin/activate
```

Verify the setup:

```bash
.venv/bin/pytest            # must pass with ≥95% coverage
ruff check .                # zero lint errors
```

---

## Running Tests

Always use the venv Python to avoid picking up system packages:

```bash
.venv/bin/pytest                         # full suite
.venv/bin/pytest tests/unit/             # unit tests only
.venv/bin/pytest tests/integration/     # integration tests
.venv/bin/pytest -k test_fingerprint    # single test
```

Coverage is enforced at 95%. New code must ship with tests.

---

## Code Style

This project uses `ruff` for formatting and linting, and `mypy` (strict) for type checking.

```bash
ruff check .          # lint
ruff format .         # format
mypy anjor/      # type check
```

Rules:
- **No f-strings in SQL** — parameterised queries only.
- **No `eval`, `exec`, `pickle`, or `shell=True`** — ever.
- **Payloads sanitised before storage or logging** — sensitive keys are redacted.
- Follow the layer rules in `CLAUDE.md` — domain core has zero framework dependencies.

---

## Pre-commit Hooks

Install once after cloning:

```bash
pip install pre-commit
pre-commit install
```

Hooks run `ruff` and `mypy` on every commit. CI enforces the same checks.

---

## Pull Request Guidelines

1. Branch off `main`. Name branches `feat/short-description` or `fix/short-description`.
2. Keep PRs focused — one logical change per PR.
3. Update `CHANGELOG.md` under `[Unreleased]` with a bullet for your change.
4. All CI checks must pass before review.
5. No backwards-compatibility shims. If something is unused, delete it.

---

## Architecture

Read these before touching the code:

- [`CLAUDE.md`](CLAUDE.md) — hard constraints, build order, non-negotiables
- [`docs/architecture.md`](docs/architecture.md) — layer diagram and design decisions
- [`docs/code_flow.md`](docs/code_flow.md) — detailed execution traces

---

## Reporting Security Issues

Do **not** open a public GitHub issue for security vulnerabilities. See [`SECURITY.md`](SECURITY.md).
