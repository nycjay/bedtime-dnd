from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import require_auth, supabase_admin, templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, auth=Depends(require_auth)):
    client, user = auth
    profile = client.table("profiles").select("display_name").eq("id", user.id).single().execute()
    friendships = (
        supabase_admin.table("friendships")
        .select("friend_id, profiles!friendships_friend_id_fkey(display_name)")
        .eq("profile_id", user.id)
        .execute()
    )
    friends = [{"id": f["friend_id"], "display_name": f["profiles"]["display_name"]} for f in friendships.data]
    return templates.TemplateResponse(
        request, "settings.html", {"user": user, "profile": profile.data, "friends": friends}
    )


@router.post("/settings/display-name")
async def update_display_name(request: Request, auth=Depends(require_auth), display_name: str = Form(...)):
    client, user = auth
    client.table("profiles").update({"display_name": display_name}).eq("id", user.id).execute()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/delete-account")
async def delete_account(request: Request, auth=Depends(require_auth)):
    client, user = auth
    # Log departure from other people's campaigns
    my_players = supabase_admin.table("players").select("id, name").eq("profile_id", user.id).execute()
    if my_players.data:
        player_ids = [p["id"] for p in my_players.data]
        player_names = {p["id"]: p["name"] for p in my_players.data}
        # Find campaign_members in campaigns owned by others
        members = (
            supabase_admin.table("campaign_members")
            .select("campaign_id, player_id, campaigns!inner(profile_id)")
            .in_("player_id", player_ids)
            .neq("campaigns.profile_id", user.id)
            .execute()
        )
        # Group by campaign
        by_campaign: dict[str, list[str]] = {}
        for m in members.data:
            by_campaign.setdefault(m["campaign_id"], []).append(player_names[m["player_id"]])
        for campaign_id, names in by_campaign.items():
            msg = f"[PARTY] {', '.join(names)} left the party — their adventurer has moved on."
            supabase_admin.table("game_logs").insert(
                {"campaign_id": campaign_id, "role": "user", "content": msg}
            ).execute()
    supabase_admin.auth.admin.delete_user(user.id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@router.get("/guide", response_class=HTMLResponse)
async def guide_page(request: Request, auth=Depends(require_auth)):
    return templates.TemplateResponse(request, "guide.html")
