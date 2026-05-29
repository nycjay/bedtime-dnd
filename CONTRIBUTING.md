# Contributing

Thanks for your interest in contributing to Bedtime D&D!

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
2. Clone the repo and install dependencies:
   ```bash
   git clone <repo-url> && cd dnd
   just install
   ```
3. Copy `.env.example` to `.env` and fill in your Supabase + Gemini keys (see README for details)
4. Run the dev server:
   ```bash
   just serve
   ```

## Development workflow

```bash
just check    # lint + format check + tests
just serve    # start dev server with auto-reload
```

A pre-commit hook is installed by `just install` — it runs `just check` before every commit so you catch issues early. CI also runs the same checks on every PR.

## Code style

- Python formatting and linting enforced by [ruff](https://docs.astral.sh/ruff/)
- 120 character line length
- Imports sorted automatically
- No need to configure anything — `just check` handles it

## Pull requests

- Keep PRs focused — one logical change per PR
- All checks must pass (lint, format, tests)
- Add tests for new features or bug fixes
- Update documentation if behavior changes

## Project structure

- `app/` — Python backend (FastAPI routes, helpers, config)
- `templates/` — Jinja2 HTML templates
- `static/` — CSS, icons, sprites
- `supabase/migrations/` — Database schema (idempotent SQL)
- `tests/` — pytest test suite

## Running tests

```bash
uv run pytest -q              # quick run
uv run pytest -v              # verbose
uv run pytest -k "test_name"  # run specific test
```

Tests mock external services (Supabase, Gemini) — no real API keys needed to run them.
