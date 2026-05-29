from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import config
from app.deps import gemini_client, require_auth, require_one, templates
from app.helpers import analyze_avatar, generate_avatar, generate_avatar_from_text, upload_avatar

router = APIRouter()


async def _process_avatar(
    photo, user_id: str, name: str, char_class: str, description: str
) -> tuple[str | None, str | None]:
    """Process photo upload into avatar URL. Returns (avatar_url, visual_description)."""
    image_data = None
    if photo and photo.size and photo.size > 0 and photo.size <= config.MAX_UPLOAD_SIZE:
        photo_bytes = await photo.read()
        image_data = generate_avatar(photo_bytes, photo.content_type, name, char_class, description)
    elif gemini_client:
        image_data = generate_avatar_from_text(name, char_class, description)
    if image_data:
        avatar_url = upload_avatar(user_id, image_data)
        visual_desc = analyze_avatar(image_data)
        return avatar_url, visual_desc
    return None, None


def _parse_stat(form, key: str, default: int = 3) -> int:
    """Parse a stat value from form, clamped to 1-5."""
    try:
        val = int(form.get(key, default))
    except (ValueError, TypeError):
        val = default
    return max(1, min(5, val))


@router.get("/players", response_class=HTMLResponse)
async def players_page(request: Request, auth=Depends(require_auth)):
    client, user = auth
    data = client.table("players").select("*").execute()
    return templates.TemplateResponse(request, "players.html", {"players": data.data})


@router.get("/players/new", response_class=HTMLResponse)
async def new_player_page(request: Request, auth=Depends(require_auth)):
    return templates.TemplateResponse(request, "player_new.html")


@router.post("/players/new")
async def create_player(request: Request, auth=Depends(require_auth)):
    client, user = auth
    form = await request.form()
    photo: UploadFile = form.get("photo")

    avatar_url, visual_desc = await _process_avatar(
        photo, user.id, form.get("name", ""), form.get("class", "Warrior"), form.get("description", "")
    )

    client.table("players").insert(
        {
            "profile_id": user.id,
            "name": form.get("name"),
            "class": form.get("class", "Warrior"),
            "description": form.get("description", ""),
            "might": _parse_stat(form, "might"),
            "agility": _parse_stat(form, "agility"),
            "wits": _parse_stat(form, "wits"),
            "max_hp": 8 + _parse_stat(form, "might"),
            "avatar_url": avatar_url,
            "visual_description": visual_desc,
        }
    ).execute()
    has_photo = photo and photo.size and photo.size > 0
    redirect_url = "/players?avatar_failed=1" if (has_photo and not avatar_url) else "/players"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/players/{player_id}", response_class=HTMLResponse)
async def player_detail(request: Request, player_id: str, auth=Depends(require_auth)):
    client, user = auth
    player = require_one(client.table("players").select("*").eq("id", player_id).single())
    memberships = (
        client.table("campaign_members").select("campaign_id, campaigns(name)").eq("player_id", player_id).execute()
    )
    return templates.TemplateResponse(
        request, "player_detail.html", {"player": player.data, "memberships": memberships.data}
    )


@router.post("/players/{player_id}/edit")
async def edit_player(request: Request, player_id: str, auth=Depends(require_auth)):
    client, user = auth
    form = await request.form()
    photo: UploadFile = form.get("photo")

    update_data = {
        "name": form.get("name"),
        "class": form.get("class"),
        "description": form.get("description", ""),
        "might": _parse_stat(form, "might"),
        "agility": _parse_stat(form, "agility"),
        "wits": _parse_stat(form, "wits"),
        "max_hp": 8 + _parse_stat(form, "might"),
    }

    if photo and photo.size and photo.size > 0 and photo.size <= config.MAX_UPLOAD_SIZE:
        new_avatar, visual_desc = await _process_avatar(
            photo, user.id, form.get("name", ""), form.get("class", "Warrior"), form.get("description", "")
        )
        if new_avatar:
            update_data["avatar_url"] = new_avatar
            update_data["visual_description"] = visual_desc

    client.table("players").update(update_data).eq("id", player_id).execute()
    return RedirectResponse(url=f"/players/{player_id}?saved=1", status_code=303)


@router.post("/players/{player_id}/level-up")
async def level_up_player(request: Request, player_id: str, auth=Depends(require_auth)):
    client, user = auth
    form = await request.form()
    stat = form.get("stat")
    if stat not in ("might", "agility", "wits"):
        return RedirectResponse(url=f"/players/{player_id}", status_code=303)
    player = require_one(
        client.table("players").select("might, agility, wits, unspent_points").eq("id", player_id).single()
    )
    if not player.data.get("unspent_points") or player.data["unspent_points"] < 1:
        return RedirectResponse(url=f"/players/{player_id}", status_code=303)
    update = {
        stat: player.data[stat] + 1,
        "unspent_points": player.data["unspent_points"] - 1,
        "max_hp": 8 + (player.data["might"] + (1 if stat == "might" else 0)),
    }
    client.table("players").update(update).eq("id", player_id).execute()
    return RedirectResponse(url=f"/players/{player_id}?saved=1", status_code=303)


@router.post("/players/{player_id}/delete")
async def delete_player(request: Request, player_id: str, auth=Depends(require_auth)):
    client, user = auth
    player = require_one(client.table("players").select("name").eq("id", player_id).single())
    memberships = client.table("campaign_members").select("campaign_id").eq("player_id", player_id).execute()
    for m in memberships.data:
        client.table("game_logs").insert(
            {
                "campaign_id": m["campaign_id"],
                "role": "model",
                "content": f"{player.data['name']} has departed from the adventure, "
                "vanishing into the mists of legend...",
            }
        ).execute()
    client.table("players").delete().eq("id", player_id).execute()
    return RedirectResponse(url="/players", status_code=303)
