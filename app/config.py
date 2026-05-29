import os

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass  # truststore not needed in production (no VPN)


class Config:
    # AI Models
    NARRATIVE_MODEL = "gemini-2.5-flash"
    IMAGE_MODEL = "gemini-2.5-flash-image"
    EXTRACTION_MODEL = "gemini-2.5-flash"

    # Generation settings
    NARRATIVE_TEMPERATURE = 0.9
    EXTRACTION_TEMPERATURE = 0.1

    # Game limits
    MAX_GAME_LOGS = 50
    SUMMARY_BATCH_SIZE = 50  # Generate a summary every N turns
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB max photo upload
    SPECTATOR_POLL_INTERVAL = 5  # Seconds between spectator polls for new content

    # Avatar style
    AVATAR_STYLE = (
        "Style: classic 80s fantasy cartoon like the Dungeons & Dragons TV show, He-Man, or Ralph Bakshi. "
        "Bold outlines, saturated colors, painterly background."
    )

    # Game state tools for function calling
    GAME_STATE_TOOLS = [
        {
            "name": "deal_damage",
            "description": "Deal damage to a character. Call when a character takes damage in combat or from a hazard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Name of the character taking damage"},
                    "amount": {"type": "integer", "description": "Amount of damage dealt"},
                },
                "required": ["player_name", "amount"],
            },
        },
        {
            "name": "heal",
            "description": "Heal a character. Call when a character is healed by magic, potions, or rest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Name of the character being healed"},
                    "amount": {"type": "integer", "description": "Amount of HP restored"},
                },
                "required": ["player_name", "amount"],
            },
        },
        {
            "name": "award_item",
            "description": "Give an item to a character. Call when a character finds, receives, or picks up an item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Name of the character receiving the item"},
                    "item_name": {"type": "string", "description": "Name of the item"},
                },
                "required": ["player_name", "item_name"],
            },
        },
        {
            "name": "remove_item",
            "description": "Remove an item from a character. Call when an item is used up, lost, or given away.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Name of the character losing the item"},
                    "item_name": {"type": "string", "description": "Name of the item"},
                },
                "required": ["player_name", "item_name"],
            },
        },
        {
            "name": "award_xp",
            "description": (
                "Award 1 XP to a character for a heroic moment, clever idea, great roll, "
                "or completing a challenge. At 3 XP they level up automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Name of the character earning XP"},
                },
                "required": ["player_name"],
            },
        },
    ]


config = Config()

# Environment
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# App identity (used in templates, emails, manifest)
APP_NAME = os.environ.get("APP_NAME", "Bedtime D&D")
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")

# Email (disabled by default — see EMAIL.md to enable)
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "").lower() in ("1", "true", "yes")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_API_URL = os.environ.get("EMAIL_API_URL", "")
EMAIL_API_KEY = os.environ.get("EMAIL_API_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_SERVICE_KEY environment variable is required")
