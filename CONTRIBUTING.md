# Contributing to Anjor

Thank you for your interest in contributing. Contributions that improve observability, reliability, or developer experience for AI agent builders are very welcome.

---

## Before You Start

- Check [open issues](https://github.com/anjor-labs/anjor/issues) to avoid duplicating work.
- For anything beyond a typo fix, open an issue first to discuss the approach.

---

## Development Setup

Requires Python 3.11+.

```bash
git clone https://github.com/anjor-labs/anjor.git
cd anjor
pip install -e ".[dev]"
```

Verify the setup:

```bash
pytest --cov=anjor --cov-fail-under=95 -q   # must pass
ruff check anjor/ tests/                     # zero lint errors
mypy anjor/                                  # zero type errors
```

---

## Running Tests

```bash
pytest                                   # full suite
pytest tests/unit/                       # unit tests only
pytest tests/integration/               # integration tests
pytest -k test_fingerprint              # single test by name
```

Coverage is enforced at 95%. New code must ship with tests.

---

## Code Style

```bash
ruff check anjor/ tests/    # lint
ruff format anjor/ tests/   # format
mypy anjor/                 # type check (strict)
```

Rules:
- **No f-strings in SQL** — parameterised queries only.
- **No `eval`, `exec`, `pickle`, or `shell=True`** — ever.
- **Payloads sanitised before storage or logging** — sensitive keys are redacted.
- Domain core (`core/`) has zero framework dependencies — keep it that way.

---

## Pull Request Guidelines

1. Branch off `main`. Name branches `feat/short-description` or `fix/short-description`.
2. Keep PRs focused — one logical change per PR.
3. Update `CHANGELOG.md` under `[Unreleased]` with a user-facing bullet for your change.
4. All CI checks must pass before review.
5. No backwards-compatibility shims — if something is unused, delete it.

---

## Architecture

Read these before touching the code:

- [`docs/architecture.md`](docs/architecture.md) — layer diagram and design decisions

---

## Reporting Security Issues

Do **not** open a public GitHub issue for security vulnerabilities. See [`SECURITY.md`](SECURITY.md).
