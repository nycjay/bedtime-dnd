"""Email sending via generic HTTP email API. Disabled unless EMAIL_ENABLED=true."""

import logging

import httpx

from app.config import APP_NAME, APP_URL, EMAIL_API_KEY, EMAIL_API_URL, EMAIL_ENABLED, EMAIL_FROM

logger = logging.getLogger(__name__)


def send_invite(to_email: str, inviter_name: str, campaign_name: str) -> bool:
    """Send a campaign sharing invite email. Returns True if sent, False if skipped/failed."""
    if not EMAIL_ENABLED:
        return False
    try:
        resp = httpx.post(
            EMAIL_API_URL,
            headers={"X-Api-Key": EMAIL_API_KEY, "Authorization": f"Bearer {EMAIL_API_KEY}"},
            json={
                "from": {"address": EMAIL_FROM, "display_name": APP_NAME},
                "to": [{"address": to_email}],
                "subject": f"\U0001f3f0 {inviter_name} invited you to {campaign_name}",
                "html": (
                    f"<h2>You've been invited to an adventure!</h2>"
                    f"<p><strong>{inviter_name}</strong> shared their campaign "
                    f"<strong>{campaign_name}</strong> with you.</p>"
                    f'<p><a href="{APP_URL}/campaigns"'
                    f' style="background:#d97706;color:white;padding:12px 24px;'
                    f'border-radius:8px;text-decoration:none;">Open {APP_NAME}</a></p>'
                    f'<p style="color:#666;font-size:12px;">Bedtime D&amp;D for the whole family</p>'
                ),
            },
        )
        resp.raise_for_status()
        logger.info("Invite email sent to %s for campaign %s", to_email, campaign_name)
        return True
    except Exception:
        logger.exception("Failed to send invite email to %s", to_email)
        return False
