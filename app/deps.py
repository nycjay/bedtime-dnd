from fastapi import Request
from fastapi.templating import Jinja2Templates
from google import genai
from supabase.lib.client_options import SyncClientOptions

from app.config import APP_NAME, APP_URL, GEMINI_API_KEY, SUPABASE_KEY, SUPABASE_SERVICE_KEY, SUPABASE_URL
from supabase import Client, create_client

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
templates = Jinja2Templates(directory="templates")


def _relative_time(value: str) -> str:
    """Convert an ISO timestamp to a relative time string."""
    if not value:
        return ""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        return value[:10]
    except Exception:
        return value[:10] if value else ""


templates.env.filters["relative_time"] = _relative_time

# Keyword → sprite filename mapping (checked in order, first match wins)
SPRITE_KEYWORDS: list[tuple[list[str], str]] = [
    (["sword", "blade", "dagger", "knife"], "sword"),
    (["shield", "buckler"], "shield"),
    (["potion", "elixir", "vial", "flask", "brew"], "potion"),
    (["scroll", "parchment", "map", "letter", "note"], "scroll"),
    (["gem", "jewel", "diamond", "ruby", "emerald", "sapphire", "crystal"], "gem"),
    (["key", "lockpick"], "key"),
    (["bow", "arrow", "quiver"], "bow"),
    (["staff", "wand", "rod", "scepter"], "staff"),
    (["helmet", "helm", "crown", "hat", "hood", "cap"], "helmet"),
    (["ring", "amulet", "necklace", "pendant", "bracelet"], "ring"),
    (["torch", "lantern", "lamp", "candle", "light"], "torch"),
    (["coin", "gold", "silver", "copper", "money", "treasure"], "coin"),
    (["meat", "steak", "drumstick", "jerky", "ham", "chicken", "fish"], "meat"),
    (["fruit", "apple", "pear", "banana", "orange", "peach"], "fruit"),
    (["berry", "berries"], "berries"),
    (["medicine", "herb", "salve", "bandage", "remedy", "antidote"], "medicine"),
    (["armor", "chainmail", "plate", "breastplate", "tunic", "cloak", "robe"], "armor"),
]


def item_sprite(item_name: str) -> str:
    """Return the sprite path for an item name, or empty string if no match."""
    lower = item_name.lower()
    for keywords, sprite in SPRITE_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return f"/static/sprites/{sprite}.png"
    return ""


templates.env.globals["item_sprite"] = item_sprite
templates.env.globals["app_name"] = APP_NAME
templates.env.globals["app_url"] = APP_URL


def get_user_client(request: Request) -> tuple[Client | None, object | None]:
    """Get an authenticated Supabase client. Returns (None, None) if not authenticated."""
    token = request.cookies.get("access_token")
    if not token:
        return None, None
    try:
        user = supabase.auth.get_user(token)
    except Exception:
        return None, None
    client = _get_client_for_token(token)
    return client, user.user


class AuthRequired(Exception):
    """Raised when authentication is required. Caught by exception handler to redirect."""

    pass


def require_auth(request: Request) -> tuple[Client, object]:
    """FastAPI dependency that returns (client, user) or raises AuthRequired."""
    client, user = get_user_client(request)
    if not client:
        raise AuthRequired()
    return client, user


def _get_client_for_token(token: str) -> Client:
    """Get or create a Supabase client for a given token. Cached to avoid re-creation."""
    cached = _client_cache.get(token)
    if cached:
        return cached
    opts = SyncClientOptions(headers={"Authorization": f"Bearer {token}"})
    client = create_client(SUPABASE_URL, SUPABASE_KEY, options=opts)
    # Keep cache bounded (JWTs rotate, so old entries become stale)
    if len(_client_cache) > 20:
        _client_cache.pop(next(iter(_client_cache)))
    _client_cache[token] = client
    return client


_client_cache: dict[str, Client] = {}


def require_one(query):
    """Execute a .single() query, raising HTTPException(404) if not found."""
    from fastapi import HTTPException
    from postgrest.exceptions import APIError

    try:
        result = query.execute()
    except APIError:
        raise HTTPException(status_code=404)
    if not result.data:
        raise HTTPException(status_code=404)
    return result


def get_user_by_email(email: str):
    """Look up a user by email via the admin API. Returns an object with .id or None."""
    from types import SimpleNamespace

    import httpx

    resp = httpx.get(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        params={"filter": email, "page": 1, "per_page": 1},
        headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
    )
    if resp.status_code != 200:
        return None
    users = resp.json().get("users", [])
    match = next((u for u in users if (u.get("email") or "").lower() == email.lower()), None)
    return SimpleNamespace(id=match["id"], email=match["email"]) if match else None
