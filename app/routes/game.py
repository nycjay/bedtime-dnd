import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from google.genai import types

from app.config import SUPABASE_KEY, SUPABASE_URL, config
from app.deps import (
    SPRITE_KEYWORDS,
    gemini_client,
    get_user_client,
    require_auth,
    require_one,
    supabase_admin,
    templates,
)
from app.helpers import execute_tool_calls, extract_game_events, maybe_generate_scene_image, maybe_generate_summary

router = APIRouter()
logger = logging.getLogger(__name__)


def _persist_response(client, campaign_id: str, full_response: str, function_calls: list, members_data: list):
    """Persist the model response and apply game state changes. Returns (log_id, turn_number, notifications)."""
    log_entry = (
        client.table("game_logs")
        .insert({"campaign_id": campaign_id, "role": "model", "content": full_response})
        .execute()
    )
    log_id = log_entry.data[0]["id"] if log_entry.data else None
    turn_number = log_entry.data[0].get("turn_number") if log_entry.data else None
    # Apply game state changes
    if function_calls:
        notifications = execute_tool_calls(function_calls, campaign_id, members_data)
    else:
        extract_game_events(campaign_id, members_data, full_response)
        notifications = []
    # Update last played + flip turn
    supabase_admin.table("campaigns").update({"last_played_at": datetime.now(timezone.utc).isoformat()}).eq(
        "id", campaign_id
    ).execute()
    shares = client.table("campaign_shares").select("profile_id").eq("campaign_id", campaign_id).execute()
    if shares.data:
        campaign_data = (
            client.table("campaigns")
            .select("profile_id, current_turn_profile_id")
            .eq("id", campaign_id)
            .single()
            .execute()
        )
        all_profiles = [campaign_data.data["profile_id"]] + [s["profile_id"] for s in shares.data]
        current = campaign_data.data.get("current_turn_profile_id") or all_profiles[0]
        idx = all_profiles.index(current) if current in all_profiles else 0
        next_profile = all_profiles[(idx + 1) % len(all_profiles)]
        client.table("campaigns").update({"current_turn_profile_id": next_profile}).eq("id", campaign_id).execute()
    return log_id, turn_number, notifications


@router.get("/campaigns/{campaign_id}/play", response_class=HTMLResponse)
async def game_play(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("*").eq("id", campaign_id).single())
    members = (
        supabase_admin.table("campaign_members")
        .select("*, players(*)")
        .eq("campaign_id", campaign_id)
        .order("sort_order")
        .execute()
    )
    logs = (
        client.table("game_logs")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("created_at")
        .limit(config.MAX_GAME_LOGS)
        .execute()
    )
    # Long rest: restore HP if last activity was 4+ hours ago (new session)
    if logs.data:
        last_log_time = datetime.fromisoformat(logs.data[-1]["created_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last_log_time > timedelta(hours=4):
            for m in members.data:
                if m["current_hp"] < m["players"]["max_hp"]:
                    supabase_admin.table("campaign_members").update({"current_hp": m["players"]["max_hp"]}).eq(
                        "campaign_id", campaign_id
                    ).eq("player_id", m["player_id"]).execute()
                    m["current_hp"] = m["players"]["max_hp"]

    # Determine if it's this user's turn (only matters for shared campaigns)
    shares = client.table("campaign_shares").select("profile_id").eq("campaign_id", campaign_id).execute()
    is_shared = len(shares.data) > 0
    current_turn = campaign.data.get("current_turn_profile_id") or campaign.data["profile_id"]
    is_my_turn = not is_shared or current_turn == user.id
    turn_holder_name = ""
    if is_shared and not is_my_turn:
        holder = supabase_admin.table("profiles").select("display_name").eq("id", current_turn).single().execute()
        turn_holder_name = holder.data["display_name"] if holder.data else "the other household"
    return templates.TemplateResponse(
        request,
        "game.html",
        {
            "campaign": campaign.data,
            "members": members.data,
            "logs": logs.data,
            "has_logs": len(logs.data) > 0,
            "last_log_role": logs.data[-1]["role"] if logs.data else "",
            "is_my_turn": is_my_turn,
            "is_shared": is_shared,
            "turn_holder_name": turn_holder_name,
            "poll_interval": config.SPECTATOR_POLL_INTERVAL,
            "supabase_url": SUPABASE_URL,
            "supabase_key": SUPABASE_KEY,
            "access_token": request.cookies.get("access_token", ""),
        },
    )


@router.post("/campaigns/{campaign_id}/action")
async def game_action(
    request: Request, campaign_id: str, auth=Depends(require_auth), action: str = Form(..., max_length=5000)
):
    client, user = auth
    client.table("game_logs").insert({"campaign_id": campaign_id, "role": "user", "content": action}).execute()
    return RedirectResponse(url=f"/campaigns/{campaign_id}/play#bottom", status_code=303)


@router.get("/campaigns/{campaign_id}/last-response")
async def last_response(request: Request, campaign_id: str):
    """Return the most recent model response for this campaign."""
    client, user = get_user_client(request)
    if not client:
        return {"content": ""}
    log = (
        client.table("game_logs")
        .select("content")
        .eq("campaign_id", campaign_id)
        .eq("role", "model")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return {"content": log.data[0]["content"] if log.data else ""}


@router.get("/campaigns/{campaign_id}/recap/full")
async def quest_summary(request: Request, campaign_id: str):
    """Full quest summary — what's happened across the entire campaign."""
    client, user = get_user_client(request)
    if not client:
        raise HTTPException(status_code=401)
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini not configured")

    summaries = (
        client.table("game_summaries").select("summary").eq("campaign_id", campaign_id).order("from_turn").execute()
    )
    recent_logs = (
        client.table("game_logs")
        .select("role, content")
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=True)
        .limit(config.MAX_GAME_LOGS)
        .execute()
    )

    context_parts = [s["summary"] for s in summaries.data]
    recent_text = "\n".join(
        f"{'Player' if log['role'] == 'user' else 'DM'}: {log['content']}" for log in reversed(recent_logs.data)
    )
    if recent_text:
        context_parts.append(recent_text)

    prompt = (
        "Summarize this entire D&D quest so far in a fun, narrative style suitable for kids. "
        "Cover the major events, discoveries, battles, and character moments. "
        "Write 3-4 paragraphs as an exciting story recap.\n\n" + "\n\n".join(context_parts)
    )

    def generate():
        try:
            response = gemini_client.models.generate_content_stream(
                model=config.NARRATIVE_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(temperature=0.7),
            )
            for chunk in response:
                if chunk.text:
                    yield f"data: {chunk.text}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Recap error: {e}")
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/campaigns/{campaign_id}/recap/last-session")
async def last_session_recap(request: Request, campaign_id: str):
    """'Previously on...' — recap the last session (most recent day of play)."""
    client, user = get_user_client(request)
    if not client:
        raise HTTPException(status_code=401)
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini not configured")

    latest = (
        client.table("game_logs")
        .select("created_at")
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return StreamingResponse(
            iter(["data: No adventure history yet!\n\n", "data: [DONE]\n\n"]), media_type="text/event-stream"
        )

    last_date = latest.data[0]["created_at"][:10]
    session_logs = (
        client.table("game_logs")
        .select("role, content")
        .eq("campaign_id", campaign_id)
        .gte("created_at", last_date)
        .order("created_at")
        .execute()
    )

    session_text = "\n".join(
        f"{'Player' if log['role'] == 'user' else 'DM'}: {log['content']}" for log in session_logs.data
    )
    prompt = (
        "Write a short 'Previously on...' recap of this D&D session in a dramatic narrator voice, "
        "suitable for kids ages 5-9. Keep it to 2 short paragraphs. "
        "End with where the heroes are now and what they're facing.\n\n" + session_text
    )

    def generate():
        try:
            response = gemini_client.models.generate_content_stream(
                model=config.NARRATIVE_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(temperature=0.7),
            )
            for chunk in response:
                if chunk.text:
                    yield f"data: {chunk.text}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Recap error: {e}")
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/campaigns/{campaign_id}/stream")
async def game_stream(request: Request, campaign_id: str):
    client, user = get_user_client(request)
    if not client:
        raise HTTPException(status_code=401)
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini not configured")

    campaign = require_one(client.table("campaigns").select("*").eq("id", campaign_id).single())
    members = (
        supabase_admin.table("campaign_members")
        .select("*, players(*)")
        .eq("campaign_id", campaign_id)
        .order("sort_order")
        .execute()
    )
    logs = (
        client.table("game_logs")
        .select("role, content")
        .eq("campaign_id", campaign_id)
        .order("created_at")
        .limit(config.MAX_GAME_LOGS)
        .execute()
    )

    # Load recent summaries for long-term memory
    summaries = (
        client.table("game_summaries")
        .select("summary, from_turn, to_turn")
        .eq("campaign_id", campaign_id)
        .order("to_turn", desc=True)
        .limit(2)
        .execute()
    )

    party_desc = "\n".join(
        f"- {m['players']['name']} is a {m['players']['class']}. HP {m['current_hp']}/{m['players']['max_hp']}."
        + (f" Traits: {m['players']['description']}" if m["players"].get("description") else "")
        + (f" Items: {', '.join(m['inventory'])}." if m.get("inventory") else "")
        for m in members.data
    )
    rating = campaign.data.get("rating", "campfire")
    rating_rules = {
        "campfire": (
            "TONE: CAMPFIRE. Cozy storytelling, no real threat. "
            "Characters never get hurt. Problems solved with creativity, kindness, and humor."
        ),
        "quest": (
            "TONE: QUEST. Danger exists but heroes are never killed. "
            "At 0 HP a character is 'knocked out' — narrate a dramatic rescue opportunity. "
            "Party can revive with a good dice roll or quest item. "
            "If all are down, pause with 'to be continued...'"
        ),
        "dragons_lair": (
            "TONE: DRAGON'S LAIR. High stakes — real consequences. "
            "At 0 HP a character is gravely wounded and needs immediate help. "
            "Combat is dramatic and tense. Still no gore or graphic violence."
        ),
    }
    system_prompt = (
        f"You are a Dungeon Master for a bedtime D&D game with young children (ages 5-9). "
        f"Sessions are short (20 minutes). Use vivid descriptions. "
        f"Campaign: {campaign.data['name']}. "
        f"{'Theme: ' + campaign.data['summary'] + '. ' if campaign.data.get('summary') else ''}"
        f"Difficulty: {campaign.data.get('difficulty', 'normal')}.\n\n"
        f"{rating_rules.get(rating, rating_rules['campfire'])}\n\n"
        f"Party:\n{party_desc}\n\n"
        f"Characters can only use abilities that match their class and description. "
        f"If a player tries something their character clearly cannot do (e.g., a Warrior breathing fire), "
        f"gently remind them in-character. If it's plausible for their class (e.g., a Dragon breathing fire), "
        f"allow it. "
        f"IMPORTANT: Each character is a separate individual. Never mix traits between characters. "
        f"Describe each character's actions separately using only THEIR abilities and appearance. "
        f"Only call game tools (deal_damage, heal, award_item, remove_item) when the action SUCCEEDS. "
        f"Do NOT award items or deal damage on failed rolls or failed attempts. "
        f"When awarding items, prefer these types (but you may use others): "
        f"{', '.join(kws[0] for kws, _ in SPRITE_KEYWORDS)}. "
        f"Keep responses to 2-3 short paragraphs. End with a clear choice or question for the players. "
        f"At dramatic moments (combat, tricky actions, risky choices), ask the players to roll the dice. "
        f"Say something like 'Roll to see if...' — they have a D20. "
        f"Ask only ONE player to roll per response — address them by name. "
        f"When they report a roll, interpret it: "
        f"1-5 is a fail, 6-10 partial success, 11-17 success, 18-20 amazing success. "
        f"If this is the start of the adventure, set the scene. "
        f"If the player message starts with [BEDTIME], bring the current scene to a natural stopping point. "
        f"Match the tone of the adventure — a cliffhanger, a moment of rest, or a dramatic pause. "
        f"End with something that makes them excited to come back."
    )

    # Prepend summaries as "Previously..." context
    summary_context = ""
    if summaries.data:
        recaps = sorted(summaries.data, key=lambda s: s["from_turn"])
        summary_context = "PREVIOUSLY IN THIS ADVENTURE:\n" + "\n\n".join(s["summary"] for s in recaps) + "\n\n"

    contents = []
    if summary_context:
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=summary_context)]))
        contents.append(
            types.Content(role="model", parts=[types.Part.from_text(text="I remember. Let's continue the adventure.")])
        )
    for log in logs.data:
        role = "user" if log["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=log["content"])]))
    if not contents:
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text="Begin the adventure!")]))

    def generate():
        full_response = ""
        function_calls_made = []
        persisted = False
        try:
            tools = types.Tool(function_declarations=config.GAME_STATE_TOOLS)
            response = gemini_client.models.generate_content_stream(
                model=config.NARRATIVE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=config.NARRATIVE_TEMPERATURE,
                    tools=[tools],
                ),
            )
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {chunk.text}\n\n"
                # Collect function calls from streaming chunks
                if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                    for part in chunk.candidates[0].content.parts:
                        if part.function_call:
                            function_calls_made.append(part.function_call)

            if not full_response.strip():
                yield "data: [DONE]\n\n"
                return

            # Persist immediately after streaming completes
            log_id, turn_number, notifications = _persist_response(
                client, campaign_id, full_response, function_calls_made, members.data
            )
            persisted = True

            # Send inventory notifications to client
            for notif in notifications:
                yield f"event: inventory\ndata: {json.dumps(notif)}\n\n"

            yield "data: [DONE]\n\n"

            # Non-critical: summary and scene image (ok to lose on disconnect)
            maybe_generate_summary(campaign_id, turn_number or 0)
            if log_id:
                visual_desc = ", ".join(
                    f"{m['players']['name']}: " + (m["players"].get("visual_description") or f"{m['players']['class']}")
                    for m in members.data
                )
                img_url = maybe_generate_scene_image(campaign_id, log_id, full_response, visual_desc)
                if img_url:
                    yield f"event: image\ndata: {img_url}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: [ERROR] {e}\n\n"
        finally:
            # If client disconnected before we persisted, save now
            if full_response.strip() and not persisted:
                try:
                    _persist_response(client, campaign_id, full_response, function_calls_made, members.data)
                except Exception as e:
                    logger.error(f"Failed to persist on disconnect: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")
