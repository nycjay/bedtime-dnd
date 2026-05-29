# Bedtime D&D

A mobile-optimized D&D Dungeon Master web app for running quick 20-minute bedtime RPG sessions with kids. AI-powered storytelling with streaming narrative, dice rolling, character avatars, and multi-household play.

**Features:**
- 🏰 Campaign management with adventure themes and content ratings
- 🧙 Character creation with AI-generated 80s fantasy avatars
- ⬆️ Leveling system — earn stat points from heroic moments
- 🎲 D20 dice roller with sound effects
- 📖 Streaming AI narrative (Gemini) with scene illustrations
- 🌙 Bedtime mode — wraps up the story naturally
- 🤝 Multi-household sharing with turn-based play
- 🔊 Text-to-speech narration with voice selection
- 📱 Mobile-first PWA (installable on home screen)

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [just](https://github.com/casey/just) (task runner)
- [Supabase CLI](https://supabase.com/docs/guides/cli)

### 1. Clone and install

```bash
git clone <repo-url> && cd dnd
just install
```

### 2. Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. From Settings → API, grab:
   - **Project URL** → `SUPABASE_URL`
   - **Publishable (anon) key** → `SUPABASE_KEY`
   - **Secret (service_role) key** → `SUPABASE_SERVICE_KEY`

3. Link and push the schema:
```bash
just db-link <project-ref>
just db-push
```

### 3. Gemini API

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Click "Create API Key" (create or select a Google Cloud project)
3. Copy the key → `GEMINI_API_KEY`

### 4. Email (optional)

See [EMAIL.md](EMAIL.md) for setting up email (campaign invites, password reset).

### 5. Environment

```bash
cp .env.example .env
# Fill in your keys
```

### 6. Run

```bash
just serve
```

Open `http://localhost:8000` on your phone or browser.

## Commands

| Command | Description |
|---------|-------------|
| `just serve` | Start dev server |
| `just install` | Install deps + set up pre-commit hook |
| `just check` | Run lint + format check + tests |
| `just deploy` | Deploy to Fly.io |
| `just deploy-secrets` | Push `.env` to Fly.io secrets |
| `just db-push` | Apply pending migrations |
| `just db-status` | Check migration status |
| `just db-new <name>` | Create a new migration |
| `just db-link <ref>` | Link to Supabase project (one-time) |

## Password Reset

Since email is not configured, use one of these methods if someone forgets their password:

**Option 1: Supabase Dashboard**
1. Go to Authentication → find the user → click on them
2. Click "Update user" and set a new password

**Option 2: SQL Editor**
```sql
update auth.users
set encrypted_password = crypt('newpassword', gen_salt('bf'))
where email = 'user@example.com';
```

## Deployment (Fly.io)

### Prerequisites

```bash
# Install Fly CLI
brew install flyctl

# Sign up / log in (requires credit card for free tier)
fly auth login
```

### First-time deploy

```bash
# Copy the example config and edit the app name
cp fly.toml.example fly.toml

# Launch the app
fly launch --no-deploy

# Push secrets from your .env file
just deploy-secrets

# Deploy
just deploy
```

Your app will be live at your Fly.io URL (e.g., `https://your-app.fly.dev`).

### Subsequent deploys

```bash
just deploy
```

### Useful commands

| Command | Description |
|---------|-------------|
| `fly status` | Check app status |
| `fly logs` | View live logs |
| `fly ssh console` | SSH into the running container |
| `fly secrets list` | List configured secrets |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MIT — see [LICENSE](LICENSE).
