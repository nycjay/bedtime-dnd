# Bedtime D&D — Agent Reference

## Project Overview

A mobile-optimized D&D Dungeon Master web app for running quick 20-minute bedtime RPG sessions with kids. All mechanics are digital — character stats, inventories, dice rolling — played entirely from the browser.

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | Python / FastAPI | Renders Jinja2 HTML templates |
| Frontend | HTML5 + Tailwind CSS | CDN-only, no build step |
| Database | Supabase (Postgres) | Row Level Security for multi-tenancy |
| Auth | Supabase Email/Password Auth | Cookie-based session tokens |
| AI | Gemini 2.5 Flash (narrative) + Gemini 2.5 Flash Image (avatars) | `google-genai` Python SDK |
| Storage | Supabase Storage | `avatars` bucket for generated character art |

## Data Model

```
profiles          → auth.users (1:1)
players           → profiles (many:1) — reusable character sheets
campaigns         → profiles (many:1) — game instances
campaign_members  → campaigns × players (join) — live state per session
game_logs         → campaigns (many:1) — sequential narrative history
game_events       → campaigns (many:1) — audit trail of HP/inventory changes
```

| Table | Key Columns | Purpose |
|-------|------------|---------|
| `profiles` | `id` (FK → auth.users), `display_name` | App user identity, multi-tenancy root |
| `players` | `name`, `class`, `description`, `might`, `agility`, `wits`, `max_hp`, `avatar_url` | Reusable character sheets |
| `campaigns` | `name`, `summary`, `difficulty`, `profile_id` | Active game instances |
| `campaign_members` | `campaign_id`, `player_id`, `current_hp`, `inventory` (jsonb) | Live mutable state per character per campaign |
| `game_logs` | `campaign_id`, `role` (user/model), `content` | LLM context history |
| `game_events` | `campaign_id`, `player_id`, `event_type`, `detail` (jsonb) | Audit trail for state changes |

## Project Structure

```
dnd/
├── main.py              # FastAPI app entry point, top-level routes
├── app/
│   ├── config.py        # Environment vars + app settings
│   ├── deps.py          # Shared dependencies (Supabase, Gemini, templates)
│   ├── email.py         # Email sending (optional)
│   ├── helpers.py       # Shared logic (avatar gen, game state extraction)
│   └── routes/          # Route modules (auth, campaigns, players, game, etc.)
├── templates/           # Jinja2 HTML templates
├── static/              # CSS, icons, sprites
├── scripts/             # Utility scripts (sprite generation, pre-commit hook)
├── tests/               # pytest test suite
├── supabase/
│   └── migrations/      # Idempotent SQL migrations
├── .github/
│   ├── workflows/       # CI + CodeQL
│   ├── ISSUE_TEMPLATE/  # Bug report + feature request forms
│   └── dependabot.yml   # Auto dependency updates
├── pyproject.toml       # uv-managed dependencies + tool config
├── justfile             # Task runner — db, serve, check, deploy recipes
└── .env.example         # Required env vars template
```

## Database Workflow

Migrations are managed via the Supabase CLI and applied with `just`:

```bash
just db-link <project-ref>   # One-time link to remote project
just db-push                 # Apply pending migrations (safe to re-run)
just db-status               # Check applied vs pending
just db-new <name>           # Create a new migration file
just db-nuke                 # DESTRUCTIVE: wipe and re-apply (requires confirmation)
```

All migrations use `IF NOT EXISTS`, `CREATE OR REPLACE`, and conditional `DO` blocks so they can be applied repeatedly without error.

**Never use `db-nuke` on hosted Supabase** — it can break auth internals. Prefer deleting and recreating the project if a full reset is needed.

## Development Workflow

```bash
# Local development
just serve              # Start dev server (auto-reloads on code changes)
just check              # Run lint + format check + tests

# Commit (pre-commit hook enforces just check)
git add <files>
git commit -m "message"
git push                # Push to GitHub

# Deploy to production
just deploy             # Build + push to Fly.io
just deploy-secrets     # Sync .env to Fly (only when env vars change)
```

Production URL: Configured via `APP_URL` environment variable

### Git Rules
- Keep commits focused — one logical change per commit
- Don't amend commits that have already been pushed without explicit agreement
- Run `just check` before committing (the pre-commit hook enforces this)

## Conventions

- **Templates**: Server-rendered Jinja2 with form POSTs and redirects
- **Styling**: Tailwind utility classes, dark theme (`bg-gray-900` base)
- **Auth pattern**: httpOnly cookie (`access_token`), redirect to `/login` if missing/expired
- **API style**: Form POSTs with 303 redirects (traditional web, not JSON API)
- **RLS**: All table access scoped to `auth.uid()` — no server-side filtering needed beyond token forwarding
- **Python tooling**: `uv` for package management, `ruff` for linting/formatting, `ty` for type checking, `pytest` for tests
- **Code quality**: `just check` runs lint + format check + tests; pre-commit hook enforces this before every commit
- **Line length**: 120 characters max
- **Imports**: sorted by `ruff` (isort-compatible)

## UI/UX Guidelines

### Visual Identity
- **Medieval fantasy feel** — warm amber accents, MedievalSharp font for headings, subtle card borders
- **Theming via CSS custom properties** — `--bg`, `--text`, `--card`, `--input`, `--muted`, `--accent`, `--accent-hover`
- **Never hardcode colors** — use `.card`, `.input`, `.muted`, `.btn-primary`, `.btn-danger` classes
- **Themes**: Dark (default), Light, Parchment, System — stored in `localStorage('theme')`
- **Accent color**: Amber/gold (`#d97706`) — used for headings, active nav, primary buttons
- **Font**: MedievalSharp (Google Fonts) for h1/h2, system font for body text

### Components
- **Buttons (primary)**: `.btn-primary` — amber/gold, white text, rounded
- **Buttons (danger)**: `.btn-danger` — dark red, light red text
- **Buttons (secondary)**: `.input` class with border — for toggles, options
- **Cards**: `.card p-4 rounded-lg` — subtle border, theme-aware background
- **Inputs**: `.input` class + `rounded p-3` — theme-aware with subtle border
- **Flash messages**: `data-flash` attribute for auto-dismiss (3s fade)

### Layout
- **Mobile-first** — max-w-md centered, thumb-friendly tap targets
- **Bottom nav** — sticky, 3 tabs (Campaigns, Characters, Settings)
- **Game screen** — full-height, no nav bar, sticky HP top + action bar bottom

### Icons (consistent emoji usage)
- ⚔️ — app logo (login only)
- 🏰 — campaigns
- 🧙 — characters / default avatar
- ⚙️ — settings
- 🎲 — dice roller

### Interactions
- **Confirm before delete** — browser `confirm()` dialog with context
- **Disable on submit** — buttons show "Creating..." / "..." while processing
- **Auto-dismiss notifications** — green success, yellow warning, 3 second fade

## Best Practices

### Code Organization
- Extract shared logic into helper functions (e.g., `_generate_avatar`, `_upload_avatar`, `_extract_game_events`)
- Group routes by domain (auth, campaigns, players, game)
- Keep route handlers thin — delegate complex logic to helpers

### Security
- `get_user_client()` catches expired/invalid JWTs and returns None (triggers login redirect)
- Admin operations (user creation) use `supabase_admin` with service key — never exposed to client
- RLS policies enforce data isolation at the database level
- Cookies are `httponly`, `secure`, `samesite=lax` to prevent XSS/CSRF
- **Auth error messages must be generic** — log details server-side, show "Invalid email or password" to users
- **File uploads must be size-limited** — check `photo.size` against `config.MAX_UPLOAD_SIZE` before reading
- **`supabase_admin` is required** — app fails fast at startup if `SUPABASE_SERVICE_KEY` is missing

### When to use `supabase_admin` vs user `client`
- **User `client`** (default): For operations where RLS should apply — reading own campaigns, own players, own game logs
- **`supabase_admin`**: For cross-household reads or writes that RLS would block:
  - Creating users (signup)
  - Sharing campaigns (inserting into `campaign_shares`)
  - Managing campaign members (insert/delete `campaign_members` — shared users need access)
  - Reading campaign members with joined player data (players from other households aren't visible via RLS)
  - Looking up other users' profiles (display names for turn tracking)
- **Rule of thumb**: If the operation involves data owned by another user, use admin. Always verify access in the route first (via `get_user_client`).

### Error Handling
- External API calls (Gemini, Supabase Storage) are wrapped in try/except
- Failures degrade gracefully (e.g., avatar generation fails → character still created, user sees warning)
- Errors are logged with `logger.error()` for debugging
- User-facing errors show friendly messages, not stack traces
- **Use `require_one()` for all user-facing `.single()` queries** — returns 404 instead of crashing with 500 on bad IDs
- **Never use bare `.single().execute()` in route handlers** — always wrap with `require_one()` or try/except
- **Internal/helper lookups can use `.single().execute()` directly** if they handle None gracefully

### Authorization
- **Verify ownership before mutations** — when using `supabase_admin` (which bypasses RLS), always check that the current user has permission before writing
- **RLS is not a substitute for route-level checks** when using admin client — admin bypasses all policies
- **Pattern**: Load the resource with the user's `client` first (RLS enforces access), then use `supabase_admin` only for the cross-household operation

### Performance
- Batch DB queries where possible (e.g., `.in_()` for multi-record fetches)
- Game logs capped at 50 entries per load (`MAX_GAME_LOGS`)
- Gemini streaming via SSE — user sees text immediately, not after full generation
- Avoid N+1 query patterns in loops

### Testing
- Write tests for new features — at minimum: route accessibility, input validation, core logic
- Tests live in `tests/` and run via `just check` (pytest)
- Use `conftest.py` for path setup; tests import from `app.*` directly
- **Focus on signal**: test behavior and edge cases, not trivial getters/setters
- **Don't test the framework** — no need to verify FastAPI routing or Jinja2 rendering works
- **Test the interesting logic**: state machines (XP → level up), extraction parsing, authorization gates, error paths
- Mock external services (Supabase, Gemini) — don't hit real APIs in tests
- **Use `patch()` at the module level** where the symbol is used, not where it's defined (e.g., `patch("app.helpers.gemini_client")` not `patch("app.deps.gemini_client")`)
- **Prefer verifying behavior over implementation** — assert on return values, side effects, or DB calls rather than internal state
- **Keep mocks shallow** — if a test needs 5+ levels of `.return_value.return_value...`, consider testing the helper directly instead of through the full call chain
- **Group tests by domain** in classes: `TestExtractGameEvents`, `TestCampaignSharingFlow`, etc.
- Long mock chains in tests can use `# noqa: E501` — readability of the assertion matters more than line length

### Notifications
- Flash messages use `data-flash` attribute and auto-dismiss after 3 seconds
- Green for success, yellow for warnings
- **Every save/edit action must show a confirmation** — redirect with `?saved=1` and display the flash

### Game State
- Narrative streamed via Server-Sent Events (SSE) from `/campaigns/{id}/stream`
- **Primary**: Gemini function calling — DM calls `deal_damage()`, `heal()`, `award_item()`, `remove_item()` during generation
- **Fallback**: If no function calls made, post-hoc extraction analyzes narrative for state changes
- All state changes audited in `game_events` table
- HP changes applied to `campaign_members.current_hp`
- Inventory changes applied to `campaign_members.inventory` (jsonb array)
- **Realtime**: Supabase Realtime (WebSocket) pushes new `game_logs` to spectators instantly — no polling

### Inventory Sprites
Item sprites are pre-generated 80s fantasy icons displayed next to item names in the inventory panel.

**How it works:**
- Sprites live in `static/sprites/` as transparent PNGs
- `SPRITE_KEYWORDS` in `app/deps.py` maps keyword lists → sprite filenames
- `item_sprite(name)` is a Jinja2 global that returns the sprite path (or `""` for no match)
- The DM system prompt lists preferred item types so Gemini tends to award items that match sprites
- Unmatched items fall back to a 🎒 emoji — the system is permissive, not restrictive

**To add a new sprite:**
1. Add the item name to `ITEMS` in `scripts/generate_sprites.py`
2. Run `uv run python scripts/generate_sprites.py` (only generates missing sprites)
3. Add keyword mappings to `SPRITE_KEYWORDS` in `app/deps.py`
4. The DM prompt auto-updates (it reads from `SPRITE_KEYWORDS`)
  - Enabled via migration (`alter publication supabase_realtime add table game_logs`)
  - Uses the publishable anon key in the browser (safe — RLS protects data)

## Roadmap

### Phase 1: Foundation & Multi-Tenancy ✅
- Supabase schema with RLS policies
- Email/password auth with cookie sessions
- Campaign CRUD and selector dashboard

### Phase 2: Structured Mobile Onboarding ✅
- Character creation wizard (name, class, stats, description)
- Avatar photo upload → AI-generated 80s fantasy art via Gemini
- Campaign member assignment (party picker)

### Phase 3: Digital Dice & Streaming Loop ✅
- Mobile storybook game interface
- Sticky HP monitors per character
- Client-side D20 dice roller with animation
- FastAPI `StreamingResponse` piping Gemini text chunks via SSE
- Automated game state extraction (HP, inventory) from narrative

### Phase 4: Polish & Social (planned)
- Email invites via Supabase email (free tier: 4 emails/hour via built-in SMTP, or configure custom SMTP)
- New share notifications on login
