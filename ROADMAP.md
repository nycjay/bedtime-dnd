# Bedtime D&D — Roadmap

## Security Hardening

- Replace inline access_token in game.html with a short-lived Realtime-only token endpoint

## Social & Sharing

- Email invites via Supabase email (free tier: 4 emails/hour, or custom SMTP)
- New share notifications on login
- Unshare button (owner removes a shared user)
- Quick action buttons (Attack, Sneak, Talk — less typing for kids)

## Multi-Device

- Push notifications when it's your turn (Web Push API)

## Multi-Provider AI

Make the app AI-model agnostic for open-source flexibility.

- Abstract AI calls behind a thin `app/ai.py` interface
- Separate image provider config (Gemini Image, DALL-E, Stability AI)
- Config switch: `AI_PROVIDER` and `IMAGE_PROVIDER` in .env
- Users bring their own API key for their preferred provider

## Sound & Voice Enhancements

- Ambient background music loops (tavern, forest, dungeon)
- Critical hit/fail fanfare sounds
- Auto-read new DM responses (optional)

## Campaign History

- Session list with dates and summaries
- Export as a "storybook" PDF

## Tests

- Test party join/leave narrative log insertion
