import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import EMAIL_ENABLED
from app.deps import supabase, supabase_admin, templates

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        logger.error(f"Login failed for {email}: {e}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    response = RedirectResponse(url="/campaigns", status_code=303)
    response.set_cookie("access_token", res.session.access_token, httponly=True, secure=True, samesite="lax")
    return response


@router.post("/signup")
async def signup(email: str = Form(...), password: str = Form(...)):
    if EMAIL_ENABLED:
        # Email confirmation flow — user must verify before logging in
        try:
            supabase.auth.sign_up({"email": email, "password": password})
        except Exception as e:
            logger.error(f"Signup failed for {email}: {e}")
            raise HTTPException(status_code=400, detail="Could not create account. Email may already be in use.")
        return RedirectResponse(url="/login?confirm_sent=1", status_code=303)
    else:
        # No email — admin creates pre-confirmed user, auto-login
        if not supabase_admin:
            raise HTTPException(status_code=500, detail="Service unavailable")
        try:
            supabase_admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
        except Exception as e:
            logger.error(f"Signup failed for {email}: {e}")
            raise HTTPException(status_code=400, detail="Could not create account. Email may already be in use.")
        try:
            login_res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        except Exception as e:
            logger.error(f"Post-signup login failed for {email}: {e}")
            raise HTTPException(status_code=400, detail="Account created but login failed. Try logging in.")
        response = RedirectResponse(url="/campaigns", status_code=303)
        response.set_cookie("access_token", login_res.session.access_token, httponly=True, secure=True, samesite="lax")
        return response


@router.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    """Send a password reset email via Supabase Auth."""
    base_url = str(request.base_url).rstrip("/")
    try:
        supabase.auth.reset_password_email(email, options={"redirect_to": f"{base_url}/reset-password"})
    except Exception as e:
        logger.error(f"Password reset request failed for {email}: {e}")
    # Always redirect with success — don't reveal whether the email exists
    return RedirectResponse(url="/login?reset_sent=1", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    """Show the new password form. Tokens arrive in the URL fragment (client-side)."""
    return templates.TemplateResponse(request, "reset_password.html")


@router.post("/reset-password")
async def reset_password(access_token: str = Form(...), refresh_token: str = Form(...), password: str = Form(...)):
    """Set a new password using the recovery tokens from the email link."""
    try:
        supabase.auth.set_session(access_token, refresh_token)
        supabase.auth.update_user({"password": password})
    except Exception as e:
        logger.error(f"Password reset failed: {e}")
        msg = str(e)
        if "different from the old password" in msg:
            raise HTTPException(status_code=400, detail="New password must be different from your current password.")
        raise HTTPException(status_code=400, detail="Reset link expired or invalid. Please try again.")
    response = RedirectResponse(url="/login?reset_done=1", status_code=303)
    response.delete_cookie("access_token")
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response
