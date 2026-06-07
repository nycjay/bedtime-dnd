from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_user_by_email, require_auth, require_one, supabase_admin, templates
from app.email import send_invite

router = APIRouter()


@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(request: Request, auth=Depends(require_auth)):
    client, user = auth
    # Own campaigns
    owned = client.table("campaigns").select("*").eq("profile_id", user.id).order("last_played_at", desc=True).execute()
    # Shared campaigns
    shares = client.table("campaign_shares").select("campaign_id, created_at").eq("profile_id", user.id).execute()
    shared_ids = [s["campaign_id"] for s in shares.data]
    shared = []
    if shared_ids:
        shared = client.table("campaigns").select("*").in_("id", shared_ids).execute().data
        share_dates = {s["campaign_id"]: s["created_at"] for s in shares.data}
        for c in shared:
            c["shared_at"] = share_dates.get(c["id"])
    # Member counts
    all_ids = [c["id"] for c in owned.data] + shared_ids
    member_counts = {}
    if all_ids:
        members = supabase_admin.table("campaign_members").select("campaign_id").in_("campaign_id", all_ids).execute()
        for m in members.data:
            member_counts[m["campaign_id"]] = member_counts.get(m["campaign_id"], 0) + 1
    return templates.TemplateResponse(
        request, "campaigns.html", {"campaigns": owned.data, "shared_campaigns": shared, "member_counts": member_counts}
    )


@router.post("/campaigns")
async def create_campaign(request: Request, auth=Depends(require_auth), name: str = Form(...)):
    client, user = auth
    client.table("campaigns").insert({"profile_id": user.id, "name": name}).execute()
    return RedirectResponse(url="/campaigns", status_code=303)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("*").eq("id", campaign_id).single())

    members = (
        supabase_admin.table("campaign_members")
        .select("player_id, sort_order")
        .eq("campaign_id", campaign_id)
        .order("sort_order")
        .execute()
    )
    member_ids = [m["player_id"] for m in members.data]
    shares = (
        supabase_admin.table("campaign_shares")
        .select("profile_id, profiles(display_name)")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    is_owner = campaign.data["profile_id"] == user.id

    # Load players: own + other households for shared campaigns
    players = client.table("players").select("*").execute()
    all_players = players.data
    my_player_ids = [p["id"] for p in players.data]
    if is_owner and shares.data:
        shared_profile_ids = [s["profile_id"] for s in shares.data]
        other = (
            supabase_admin.table("players")
            .select("*, profiles(display_name)")
            .in_("profile_id", shared_profile_ids)
            .execute()
        )
        all_players.extend(other.data)
    elif not is_owner:
        owner_players = (
            supabase_admin.table("players")
            .select("*, profiles(display_name)")
            .eq("profile_id", campaign.data["profile_id"])
            .execute()
        )
        all_players.extend(owner_players.data)

    # Load friends for quick-pick sharing
    shared_profile_ids = [s["profile_id"] for s in shares.data]
    friends = []
    if is_owner:
        friendships = (
            supabase_admin.table("friendships")
            .select("friend_id, profiles!friendships_friend_id_fkey(id, display_name)")
            .eq("profile_id", user.id)
            .execute()
        )
        friends = [{"id": f["friend_id"], "display_name": f["profiles"]["display_name"]} for f in friendships.data]

    return templates.TemplateResponse(
        request,
        "campaign_detail.html",
        {
            "campaign": campaign.data,
            "players": all_players,
            "member_ids": member_ids,
            "my_player_ids": my_player_ids,
            "shares": shares.data,
            "friends": friends,
            "shared_profile_ids": shared_profile_ids,
            "is_owner": is_owner,
        },
    )


@router.post("/campaigns/{campaign_id}/edit")
async def edit_campaign(
    request: Request,
    campaign_id: str,
    auth=Depends(require_auth),
    name: str = Form(...),
    summary: str = Form(""),
    difficulty: str = Form("normal"),
    rating: str = Form("campfire"),
):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("profile_id").eq("id", campaign_id).single())
    if campaign.data["profile_id"] != user.id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    client.table("campaigns").update({"name": name, "summary": summary, "difficulty": difficulty, "rating": rating}).eq(
        "id", campaign_id
    ).execute()
    return RedirectResponse(url=f"/campaigns/{campaign_id}?saved=1", status_code=303)


@router.post("/campaigns/{campaign_id}/members")
async def update_campaign_members(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    form = await request.form()
    selected_ids = form.getlist("player_ids")

    # Only manage this user's characters — don't touch other households' members
    my_players = supabase_admin.table("players").select("id, name").eq("profile_id", user.id).execute()
    my_player_ids = {p["id"] for p in my_players.data}
    my_player_names = {p["id"]: p["name"] for p in my_players.data}

    # Current members that belong to this user
    current_members = (
        supabase_admin.table("campaign_members").select("player_id").eq("campaign_id", campaign_id).execute()
    )
    current_mine = {m["player_id"] for m in current_members.data if m["player_id"] in my_player_ids}
    selected_mine = {pid for pid in selected_ids if pid in my_player_ids}

    removed = current_mine - selected_mine
    added = selected_mine - current_mine

    # Remove characters
    for pid in removed:
        supabase_admin.table("campaign_members").delete().eq("campaign_id", campaign_id).eq("player_id", pid).execute()

    # Add characters
    if added:
        players = supabase_admin.table("players").select("id, max_hp").in_("id", list(added)).execute()
        hp_map = {p["id"]: p["max_hp"] for p in players.data}
        for pid in added:
            supabase_admin.table("campaign_members").upsert(
                {"campaign_id": campaign_id, "player_id": pid, "current_hp": hp_map.get(pid, 10)},
                on_conflict="campaign_id,player_id",
            ).execute()

    # If the adventure has started, log narrative entries for party changes
    if removed or added:
        has_logs = supabase_admin.table("game_logs").select("id").eq("campaign_id", campaign_id).limit(1).execute()
        if has_logs.data:
            parts = []
            if removed:
                names = [my_player_names[pid] for pid in removed if pid in my_player_names]
                if names:
                    parts.append(f"{', '.join(names)} left the party — called away on other business.")
            if added:
                names = [my_player_names[pid] for pid in added if pid in my_player_names]
                if names:
                    parts.append(f"{', '.join(names)} joined the party!")
            if parts:
                supabase_admin.table("game_logs").insert(
                    {"campaign_id": campaign_id, "role": "user", "content": "[PARTY] " + " ".join(parts)}
                ).execute()

    return RedirectResponse(url=f"/campaigns/{campaign_id}?saved=1", status_code=303)


@router.post("/campaigns/{campaign_id}/reorder")
async def reorder_members(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("profile_id").eq("id", campaign_id).single())
    if campaign.data["profile_id"] != user.id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    form = await request.form()
    order = form.getlist("order")
    if order:
        for i, pid in enumerate(order):
            supabase_admin.table("campaign_members").update({"sort_order": i}).eq(
                "campaign_id", campaign_id
            ).eq("player_id", pid).execute()
    return RedirectResponse(url=f"/campaigns/{campaign_id}?saved=1", status_code=303)


@router.post("/campaigns/{campaign_id}/delete")
async def delete_campaign(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("profile_id").eq("id", campaign_id).single())
    if campaign.data["profile_id"] != user.id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    client.table("campaigns").delete().eq("id", campaign_id).execute()
    return RedirectResponse(url="/campaigns", status_code=303)


@router.post("/campaigns/{campaign_id}/share")
async def share_campaign(request: Request, campaign_id: str, auth=Depends(require_auth), email: str = Form(...)):
    client, user = auth
    if not supabase_admin:
        return RedirectResponse(url=f"/campaigns/{campaign_id}?error=admin_required", status_code=303)
    target = get_user_by_email(email)
    if not target:
        return RedirectResponse(url=f"/campaigns/{campaign_id}?error=user_not_found", status_code=303)
    supabase_admin.table("campaign_shares").upsert(
        {"campaign_id": campaign_id, "profile_id": target.id}, on_conflict="campaign_id,profile_id"
    ).execute()
    # Send invite email
    campaign = supabase_admin.table("campaigns").select("name").eq("id", campaign_id).single().execute()
    profile = supabase_admin.table("profiles").select("display_name").eq("id", user.id).single().execute()
    send_invite(email, profile.data["display_name"], campaign.data["name"])
    return RedirectResponse(url=f"/campaigns/{campaign_id}?saved=1", status_code=303)


@router.post("/campaigns/{campaign_id}/share-friend")
async def share_campaign_friend(
    request: Request, campaign_id: str, auth=Depends(require_auth), friend_id: str = Form(...)
):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("profile_id").eq("id", campaign_id).single())
    if campaign.data["profile_id"] != user.id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    supabase_admin.table("campaign_shares").upsert(
        {"campaign_id": campaign_id, "profile_id": friend_id}, on_conflict="campaign_id,profile_id"
    ).execute()
    return RedirectResponse(url=f"/campaigns/{campaign_id}?saved=1", status_code=303)


@router.get("/campaigns/{campaign_id}/history", response_class=HTMLResponse)
async def campaign_history(request: Request, campaign_id: str, auth=Depends(require_auth)):
    client, user = auth
    campaign = require_one(client.table("campaigns").select("id, name").eq("id", campaign_id).single())

    # Get all game logs grouped by session (4+ hour gap = new session)
    logs = (
        client.table("game_logs")
        .select("created_at, role, content, image_url")
        .eq("campaign_id", campaign_id)
        .order("created_at")
        .execute()
    )

    # Group into sessions (4+ hour gap between logs = new session)
    sessions = []
    current_session = []
    for log in logs.data:
        if current_session:
            prev_time = datetime.fromisoformat(current_session[-1]["created_at"].replace("Z", "+00:00"))
            curr_time = datetime.fromisoformat(log["created_at"].replace("Z", "+00:00"))
            if (curr_time - prev_time) > timedelta(hours=4):
                sessions.append(current_session)
                current_session = []
        current_session.append(log)
    if current_session:
        sessions.append(current_session)

    # Build session summaries
    session_data = []
    for session_logs in sessions:
        first_time = datetime.fromisoformat(session_logs[0]["created_at"].replace("Z", "+00:00"))
        dm_messages = [
            {"content": log["content"], "image_url": log.get("image_url")}
            for log in session_logs
            if log["role"] == "model"
        ]
        preview = dm_messages[0]["content"][:150] + "..." if dm_messages else ""
        turns = len([log for log in session_logs if log["role"] == "user"])
        session_data.append({"date": first_time, "preview": preview, "turns": turns, "story": dm_messages})

    return templates.TemplateResponse(
        request, "campaign_history.html", {"campaign": campaign.data, "sessions": session_data}
    )
