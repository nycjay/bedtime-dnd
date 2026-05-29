from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_user_by_email, require_auth, supabase_admin, templates

router = APIRouter()


@router.get("/friends", response_class=HTMLResponse)
async def friends_page(request: Request, auth=Depends(require_auth)):
    client, user = auth
    # Load friendships with profiles in one query
    friendships = (
        supabase_admin.table("friendships")
        .select("friend_id, profiles!friendships_friend_id_fkey(id, display_name)")
        .eq("profile_id", user.id)
        .execute()
    )
    friend_ids = [f["friend_id"] for f in friendships.data]
    if not friend_ids:
        return templates.TemplateResponse(request, "friends.html", {"friends": []})

    # Batch: all characters for all friends
    all_chars = (
        supabase_admin.table("players").select("profile_id, name, class").in_("profile_id", friend_ids).execute()
    )
    chars_by_profile: dict[str, list] = {}
    for c in all_chars.data:
        chars_by_profile.setdefault(c["profile_id"], []).append(c)

    # Batch: all campaign shares for friends
    all_shares = (
        supabase_admin.table("campaign_shares")
        .select("profile_id, campaign_id, campaigns(id, name)")
        .in_("profile_id", friend_ids)
        .execute()
    )
    campaigns_by_profile: dict[str, list] = {}
    for s in all_shares.data:
        campaigns_by_profile.setdefault(s["profile_id"], []).append(s["campaigns"])

    friends = []
    for f in friendships.data:
        fid = f["friend_id"]
        if not f.get("profiles"):
            continue
        friends.append(
            {
                "id": fid,
                "display_name": f["profiles"]["display_name"],
                "characters": chars_by_profile.get(fid, []),
                "shared_campaigns": campaigns_by_profile.get(fid, []),
            }
        )
    return templates.TemplateResponse(request, "friends.html", {"friends": friends})


@router.post("/friends/add")
async def add_friend(request: Request, auth=Depends(require_auth), email: str = Form(...)):
    client, user = auth
    target = get_user_by_email(email)
    if not target or target.id == user.id:
        return RedirectResponse(url="/friends?error=user_not_found", status_code=303)
    # Bidirectional friendship
    supabase_admin.table("friendships").upsert(
        {"profile_id": user.id, "friend_id": target.id}, on_conflict="profile_id,friend_id"
    ).execute()
    supabase_admin.table("friendships").upsert(
        {"profile_id": target.id, "friend_id": user.id}, on_conflict="profile_id,friend_id"
    ).execute()
    return RedirectResponse(url="/friends?saved=1", status_code=303)


@router.post("/friends/remove")
async def remove_friend(request: Request, auth=Depends(require_auth), friend_id: str = Form(...)):
    client, user = auth
    supabase_admin.table("friendships").delete().eq("profile_id", user.id).eq("friend_id", friend_id).execute()
    supabase_admin.table("friendships").delete().eq("profile_id", friend_id).eq("friend_id", user.id).execute()
    return RedirectResponse(url="/friends", status_code=303)
