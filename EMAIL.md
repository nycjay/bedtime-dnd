# Email Setup (Optional)

Email is **disabled by default**. The app works fully without it — accounts are created instantly with no confirmation, and password resets are done manually via the Supabase dashboard.

When enabled, email powers:
- Signup confirmation (user must verify email before logging in)
- Password reset (self-service via email link)
- Campaign invite notifications

## Prerequisites

You need an email provider with:
1. **An HTTP API** for sending emails from the app (campaign invites)
2. **SMTP credentials** for Supabase Auth (signup confirmation, password reset)
3. **A verified sending domain** (most providers require this)

Recommended providers: [Resend](https://resend.com), [Maileroo](https://maileroo.com), [Brevo](https://brevo.com), [Postmark](https://postmarkapp.com)

## 1. Enable in Environment

Add to your `.env`:

```bash
EMAIL_ENABLED=true
EMAIL_FROM=noreply@yourdomain.com
EMAIL_API_URL=<provider's send endpoint>
EMAIL_API_KEY=<your API key>
```

**Provider-specific API URLs:**
| Provider | EMAIL_API_URL |
|----------|--------------|
| Maileroo | `https://smtp.maileroo.com/api/v2/emails` |
| Resend | `https://api.resend.com/emails` |

## 2. Configure Supabase Auth SMTP

In **Supabase Dashboard → Auth → SMTP Settings**, enable custom SMTP:

| Field | Value |
|-------|-------|
| Sender email | same as `EMAIL_FROM` |
| Sender name | Your `APP_NAME` value |
| Host | provider's SMTP host |
| Port | `587` (or `465`) |
| Username | provider-specific |
| Password | provider-specific |

Also enable **"Enable email confirmations"** in Auth → Settings.

## 3. Supabase Redirect URLs

In **Auth → URL Configuration**:
- Site URL: Your `APP_URL` value (or `http://localhost:8000` for local)
- Add `http://localhost:8000/reset-password` to additional redirect URLs for local testing

## 4. Deploy

Push secrets to Fly:

```bash
just deploy-secrets
```

## When Email is Disabled

- Signup creates accounts instantly (no confirmation email)
- "Forgot password?" link is hidden on the login page
- Campaign sharing still works, just without email notification
- Password resets must be done via Supabase dashboard (see README)
