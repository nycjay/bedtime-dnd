# Bedtime D&D — project commands
# Requires: just, supabase CLI, uv, .env
# Note: values with spaces in .env must be quoted (e.g. APP_NAME="Bedtime D&D")

set dotenv-load

# Show available recipes
default:
    @just --list

# Link local project to remote Supabase (run once)
db-link project_ref:
    supabase link --project-ref {{project_ref}}

# Push all pending migrations to the remote database
db-push:
    supabase db push

# Check migration status against remote
db-status:
    supabase migration list

# Generate a new timestamped migration file
db-new name:
    supabase migration new {{name}}

# Start local Supabase stack (docker required)
db-start:
    supabase start

# Stop local Supabase stack
db-stop:
    supabase stop

# ⚠️  DESTRUCTIVE: Wipe remote DB and re-apply all migrations. Can break Supabase Auth!
db-nuke:
    @echo "🚨 This DESTROYS all data and resets the remote database."
    @echo "   Supabase Auth internals may break — you may need to delete and recreate the project."
    @read -p "Type 'nuke' to confirm: " confirm && [ "$$confirm" = "nuke" ] || exit 1
    supabase db reset --linked

# Run the FastAPI dev server
serve:
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Deploy to Fly.io
deploy:
    #!/usr/bin/env bash
    set -euo pipefail
    # Validate config
    if [[ ! -f fly.toml ]]; then
        echo "❌ fly.toml not found. Copy fly.toml.example and edit the app name:"
        echo "   cp fly.toml.example fly.toml"
        exit 1
    fi
    if [[ ! -f .env ]]; then
        echo "❌ .env not found. Copy .env.example and fill in your keys:"
        echo "   cp .env.example .env"
        exit 1
    fi
    # Validate token by hitting the API, not just checking local state
    if ! fly apps list &>/dev/null 2>&1; then
        read -p "⚠️  Fly.io auth expired. Run 'fly auth login'? [Y/n] " answer
        if [[ "${answer:-Y}" =~ ^[Nn] ]]; then
            exit 1
        fi
        fly auth login
    fi
    fly deploy || {
        echo ""
        echo "⚠️  Deploy failed. If auth-related, re-authenticate and retry:"
        echo "   fly auth login && just deploy"
        exit 1
    }

# Push secrets from .env to Fly.io
deploy-secrets:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -f .env ]]; then
        echo "❌ .env not found. Copy .env.example and fill in your keys:"
        echo "   cp .env.example .env"
        exit 1
    fi
    fly secrets import < .env

# Install/sync Python dependencies and set up git hooks
install:
    #!/usr/bin/env bash
    echo "📦 Installing dependencies..."
    uv sync
    echo "🪝 Installing pre-commit hook..."
    cp scripts/pre-commit .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
    echo "✅ Done — run 'just serve' to start developing"

# Run code quality checks (lint, format, tests)
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run pytest -q
