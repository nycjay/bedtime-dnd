import json
import logging
import uuid

from google.genai import types

from app.config import SUPABASE_URL, config
from app.deps import gemini_client, supabase_admin

logger = logging.getLogger(__name__)


def analyze_avatar(image_data: bytes) -> str | None:
    """Analyze a generated avatar and return a detailed visual description for consistency."""
    if not gemini_client:
        return None
    try:
        response = gemini_client.models.generate_content(
            model=config.EXTRACTION_MODEL,
            contents=[
                "Describe this fantasy character's visual appearance in one detailed paragraph. "
                "Include: hair color and style, eye color, skin tone, facial features, "
                "clothing/armor details, accessories, and any distinguishing features. "
                "Be specific enough that another artist could recreate this character consistently.",
                types.Part.from_bytes(data=image_data, mime_type="image/png"),
            ],
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return response.text
    except Exception as e:
        logger.error(f"Avatar analysis failed: {e}")
    return None


def generate_avatar_from_text(name: str, char_class: str, description: str) -> bytes | None:
    """Generate an avatar from class/description alone (no photo)."""
    if not gemini_client:
        return None
    prompt = (
        f"Create a 1980s fantasy animation character portrait of a {char_class} named {name}. "
        f"{'Character details: ' + description + '. ' if description else ''}"
        f"{config.AVATAR_STYLE} "
        f"Square portrait, head and shoulders only. No border, no frame, no text, edge-to-edge art."
    )
    try:
        response = gemini_client.models.generate_content(
            model=config.IMAGE_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        logger.error(f"Avatar from text failed: {e}")
    return None


def generate_avatar(photo_bytes: bytes, mime_type: str, name: str, char_class: str, description: str) -> bytes | None:
    """Generate an 80s fantasy avatar from a photo. Returns PNG bytes or None."""
    if not gemini_client:
        return None
    prompt = (
        f"Transform this photo of a child into a 1980s fantasy animation character portrait. "
        f"They are a {char_class} named {name} in a D&D adventure. "
        f"{'Character details: ' + description + '. ' if description else ''}"
        f"{config.AVATAR_STYLE} "
        f"Keep the child's facial features recognizable but stylized. "
        f"Square portrait, head and shoulders only. No border, no frame, no text, edge-to-edge art."
    )
    try:
        response = gemini_client.models.generate_content(
            model=config.IMAGE_MODEL,
            contents=[prompt, types.Part.from_bytes(data=photo_bytes, mime_type=mime_type)],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        logger.error(f"Avatar generation failed: {e}")
    return None


def upload_avatar(user_id: str, image_data: bytes) -> str:
    """Upload avatar to Supabase Storage, return public URL."""
    filename = f"{user_id}/{uuid.uuid4()}.png"
    supabase_admin.storage.from_("avatars").upload(filename, image_data, {"content-type": "image/png"})
    return f"{SUPABASE_URL}/storage/v1/object/public/avatars/{filename}"


def _apply_event(campaign_id: str, member: dict, event_type: str, value, player_id: str) -> dict | None:
    """Apply a single game state event to a member. Returns event info for client notification."""
    notification = None
    if event_type == "deal_damage" and isinstance(value, (int, float)):
        new_hp = max(0, member["current_hp"] - int(value))
        supabase_admin.table("campaign_members").update({"current_hp": new_hp}).eq("campaign_id", campaign_id).eq(
            "player_id", player_id
        ).execute()
        member["current_hp"] = new_hp
    elif event_type == "heal" and isinstance(value, (int, float)):
        max_hp = member["players"]["max_hp"]
        new_hp = min(max_hp, member["current_hp"] + int(value))
        supabase_admin.table("campaign_members").update({"current_hp": new_hp}).eq("campaign_id", campaign_id).eq(
            "player_id", player_id
        ).execute()
        member["current_hp"] = new_hp
    elif event_type == "award_item":
        inv = member.get("inventory") or []
        if value:
            inv.append(value)
        supabase_admin.table("campaign_members").update({"inventory": inv}).eq("campaign_id", campaign_id).eq(
            "player_id", player_id
        ).execute()
        notification = {
            "player_id": player_id,
            "player_name": member["players"]["name"],
            "type": "gained",
            "item": value,
        }
    elif event_type == "remove_item":
        inv = member.get("inventory") or []
        if value and value in inv:
            inv.remove(value)
        supabase_admin.table("campaign_members").update({"inventory": inv}).eq("campaign_id", campaign_id).eq(
            "player_id", player_id
        ).execute()
        notification = {"player_id": player_id, "player_name": member["players"]["name"], "type": "lost", "item": value}
    elif event_type in ("level_up", "award_xp"):
        player_data = (
            supabase_admin.table("players").select("level, unspent_points, xp").eq("id", player_id).single().execute()
        )
        current_xp = (player_data.data.get("xp") or 0) + 1
        current_level = player_data.data["level"] or 1
        unspent = player_data.data["unspent_points"] or 0
        if current_xp >= 3:
            # Level up!
            supabase_admin.table("players").update(
                {"level": current_level + 1, "unspent_points": unspent + 1, "xp": 0}
            ).eq("id", player_id).execute()
            notification = {
                "player_id": player_id,
                "player_name": member["players"]["name"],
                "type": "level_up",
                "item": f"Level {current_level + 1}",
            }
        else:
            supabase_admin.table("players").update({"xp": current_xp}).eq("id", player_id).execute()
            notification = {
                "player_id": player_id,
                "player_name": member["players"]["name"],
                "type": "xp",
                "item": f"{current_xp}/3 XP",
            }
    # Audit log
    supabase_admin.table("game_events").insert(
        {
            "campaign_id": campaign_id,
            "player_id": player_id,
            "event_type": event_type,
            "detail": {"value": value},
        }
    ).execute()
    return notification


def execute_tool_calls(function_calls: list, campaign_id: str, members: list) -> list:
    """Execute game state tool calls from Gemini function calling. Returns notifications."""
    notifications = []
    for fc in function_calls:
        player_name = fc.args.get("player_name")
        member = next((m for m in members if m["players"]["name"] == player_name), None)
        if not member:
            continue
        value = fc.args.get("amount") or fc.args.get("item_name") or 1
        notif = _apply_event(campaign_id, member, fc.name, value, member["player_id"])
        if notif:
            notifications.append(notif)
    return notifications


def extract_game_events(campaign_id: str, members: list, narrative: str):
    """Use Gemini to extract HP/inventory changes from narrative, apply to DB."""
    if not gemini_client:
        return
    party_names = [m["players"]["name"] for m in members]
    extraction_prompt = (
        f"Analyze this D&D narrative and extract any game state changes as JSON.\n"
        f"Party members: {party_names}\n"
        f"Return a JSON array of events. Each event has:\n"
        f'- "player_name": string (must match a party member)\n'
        f'- "event_type": "deal_damage" | "heal" | "award_item" | "remove_item" | "award_xp"\n'
        f'- "value": number (for damage/heal) or string (for items/status) or 1 (for award_xp)\n'
        f"If no state changes occurred, return an empty array: []\n"
        f"Award XP (award_xp) when a character does something heroic, clever, or completes a challenge.\n"
        f"ONLY return valid JSON, nothing else.\n\n"
        f"Narrative:\n{narrative}"
    )
    try:
        result = gemini_client.models.generate_content(
            model=config.EXTRACTION_MODEL,
            contents=[extraction_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=config.EXTRACTION_TEMPERATURE,
            ),
        )
        events = json.loads(result.text)
        if not isinstance(events, list):
            return
        for event in events:
            player_name = event.get("player_name")
            event_type = event.get("event_type")
            value = event.get("value")
            # Skip HP changes in fallback extraction — these should only happen via
            # explicit function calls from the DM. The extraction model tends to
            # hallucinate damage/healing that wasn't actually in the narrative.
            if event_type in ("deal_damage", "heal"):
                continue
            member = next((m for m in members if m["players"]["name"] == player_name), None)
            if not member:
                continue
            _apply_event(campaign_id, member, event_type, value, member["player_id"])
    except Exception as e:
        logger.error(f"Event extraction failed: {e}")


def maybe_generate_scene_image(campaign_id: str, log_id: str, narrative: str, party_desc: str = "") -> str | None:
    """Check if narrative warrants a scene illustration, generate and store it. Returns URL or None."""
    if not gemini_client:
        return None
    check_prompt = (
        "Does this D&D narrative describe a NEW major scene worth illustrating? "
        "Answer ONLY 'yes' or 'no'. Say 'yes' ONLY for: arriving at a completely new location for the first time, "
        "a boss or major monster appearing for the first time, or a truly dramatic visual moment. "
        "Say 'no' for: combat actions, dialogue, failed attempts, minor events, travel, "
        "or anything that continues an existing scene.\n\n"
        f"Narrative:\n{narrative}"
    )
    try:
        check = gemini_client.models.generate_content(
            model=config.EXTRACTION_MODEL,
            contents=[check_prompt],
            config=types.GenerateContentConfig(temperature=0.1),
        )
        if "yes" not in (check.text or "").lower():
            return None
        image_prompt = (
            f"Illustrate this D&D scene:\n{narrative}\n\n"
            f"{'Characters in scene: ' + party_desc + '. ' if party_desc else ''}"
            f"{config.AVATAR_STYLE} "
            f"Wide landscape composition, dramatic lighting. "
            f"IMPORTANT: Do NOT include any text, numbers, HP bars, stats, labels, or UI elements in the image. "
            f"Only include text if the scene explicitly describes readable writing (ancient runes, a sign, a letter). "
            f"Keep character appearances consistent with their descriptions above — "
            f"same clothing, hair, and features each time."
        )
        response = gemini_client.models.generate_content(
            model=config.IMAGE_MODEL,
            contents=[image_prompt],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                filename = f"scenes/{campaign_id}/{uuid.uuid4()}.png"
                supabase_admin.storage.from_("avatars").upload(
                    filename, part.inline_data.data, {"content-type": "image/png"}
                )
                image_url = f"{SUPABASE_URL}/storage/v1/object/public/avatars/{filename}"
                supabase_admin.table("game_logs").update({"image_url": image_url}).eq("id", log_id).execute()
                return image_url
    except Exception as e:
        logger.error(f"Scene image generation failed: {e}")
    return None


def maybe_generate_summary(campaign_id: str, current_turn: int):
    """Generate a summary if we've crossed a batch boundary."""
    if not gemini_client or current_turn < config.SUMMARY_BATCH_SIZE:
        return
    # Check if a summary already exists for this batch
    batch_end = (current_turn // config.SUMMARY_BATCH_SIZE) * config.SUMMARY_BATCH_SIZE
    batch_start = batch_end - config.SUMMARY_BATCH_SIZE + 1
    existing = (
        supabase_admin.table("game_summaries")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("from_turn", batch_start)
        .eq("to_turn", batch_end)
        .execute()
    )
    if existing.data:
        return
    # Fetch the logs for this batch
    logs = (
        supabase_admin.table("game_logs")
        .select("role, content, turn_number")
        .eq("campaign_id", campaign_id)
        .gte("turn_number", batch_start)
        .lte("turn_number", batch_end)
        .order("turn_number")
        .execute()
    )
    if not logs.data:
        return
    conversation = "\n".join(f"{'Player' if log['role'] == 'user' else 'DM'}: {log['content']}" for log in logs.data)
    prompt = (
        f"Summarize this D&D adventure segment (turns {batch_start}-{batch_end}) in 2-3 paragraphs. "
        f"Include key events, decisions, items found, damage taken, and where the story left off. "
        f"Write as a narrative recap.\n\n{conversation}"
    )
    try:
        result = gemini_client.models.generate_content(
            model=config.EXTRACTION_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.3),
        )
        supabase_admin.table("game_summaries").insert(
            {
                "campaign_id": campaign_id,
                "from_turn": batch_start,
                "to_turn": batch_end,
                "summary": result.text,
            }
        ).execute()
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
