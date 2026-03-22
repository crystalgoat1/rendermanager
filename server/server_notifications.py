# server/server_notifications.py
#
# Notification dispatcher — sends email and Discord notifications
# when renders complete or fail. All sends are fire-and-forget in a
# background thread so they never block the API response.

import json
import threading
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from .server_settings import (
    NOTIFICATIONS_ENABLED,
    RESEND_API_KEY,
    NOTIFICATION_FROM_EMAIL,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_notification(user_id: str, event_type: str, job: dict) -> None:
    """Fire-and-forget notification dispatch.

    Args:
        user_id:   The user who owns the job.
        event_type: "completed" or "failed".
        job:       The job row dict (must include job_id, blend_relpath, etc.).
    """
    if not NOTIFICATIONS_ENABLED:
        return

    # Run in background thread so the API response is never delayed
    t = threading.Thread(
        target=_dispatch,
        args=(user_id, event_type, job),
        daemon=True,
        name=f"notify-{event_type}-{job.get('job_id', '')[:8]}",
    )
    t.start()


# ---------------------------------------------------------------------------
# Internal dispatch
# ---------------------------------------------------------------------------

def _dispatch(user_id: str, event_type: str, job: dict) -> None:
    """Fetch user prefs, then fan out to enabled channels."""
    try:
        from .server_supabase import get_supabase

        sb = get_supabase()

        # Fetch user profile with notification preferences and email
        profile = (
            sb.table("profiles")
            .select("notification_preferences")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        prefs = (profile.data or {}).get("notification_preferences") or {}

        # Check if user wants this event type
        if event_type == "completed" and not prefs.get("notify_on_complete", True):
            return
        if event_type == "failed" and not prefs.get("notify_on_failure", True):
            return

        # Get user email from Supabase auth
        user_email = _get_user_email(sb, user_id)

        animation_url = None
        if event_type == "completed":
            job_id = job.get("job_id")
            if job_id:
                preview = sb.table("preview_requests").select("status").eq("job_id", job_id).eq("type", "compile").eq("status", "ready").limit(1).execute()
                if preview.data and len(preview.data) > 0:
                    from .server_settings import FRONTEND_BASE_URL
                    animation_url = f"{FRONTEND_BASE_URL}/history"

        # Fan out to enabled channels
        if prefs.get("email_enabled", True) and user_email:
            _send_email_notification(user_email, event_type, job, animation_url)

        if prefs.get("discord_enabled", False):
            webhook_url = prefs.get("discord_webhook_url")
            if webhook_url:
                _send_discord_notification(webhook_url, event_type, job, animation_url)

    except Exception as exc:
        print(f"[notify] dispatch error for user {user_id}: {exc}")


def _get_user_email(sb, user_id: str) -> Optional[str]:
    """Retrieve user email from Supabase auth.users via service role."""
    try:
        user = sb.auth.admin.get_user_by_id(user_id)
        return user.user.email if user and user.user else None
    except Exception as exc:
        print(f"[notify] failed to fetch email for {user_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Email via Resend
# ---------------------------------------------------------------------------

def _send_email_notification(to: str, event_type: str, job: dict, animation_url: Optional[str] = None) -> None:
    """Send a notification email via the Resend API."""
    if not RESEND_API_KEY or RESEND_API_KEY.startswith("re_xxxx"):
        print(f"[notify] email skipped — no valid RESEND_API_KEY configured")
        return

    blend_file = _short_blend_name(job.get("blend_relpath", "Unknown"))
    frames = f"{job.get('frame_start', '?')}-{job.get('frame_end', '?')}"
    vram_recovery = job.get("vram_recovery")

    if event_type == "completed":
        subject = f"✅ Render Complete - {blend_file}"
        status_line = "Your render has finished successfully."
        status_color = "#22c55e"
        status_emoji = "✅"
    else:
        subject = f"❌ Render Failed - {blend_file}"
        reason = job.get("fail_reason", "Unknown error")
        status_line = f"Your render has failed: {reason}"
        status_color = "#ef4444"
        status_emoji = "❌"

    # Build VRAM recovery row for the info table
    vram_recovery_html = ""
    if vram_recovery and isinstance(vram_recovery, dict) and vram_recovery.get("recovered_frames", 0) > 0:
        recovered = vram_recovery["recovered_frames"]
        tier_name = vram_recovery.get("max_tier_name", "unknown")
        vram_recovery_html = f"""
          <tr>
            <td style="padding: 4px 0;">VRAM Recovery</td>
            <td style="padding: 4px 0; text-align: right; color: #f59e0b;">{recovered} frame{"s" if recovered != 1 else ""} recovered (max: {tier_name})</td>
          </tr>"""

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
      <div style="background: #0f1117; border-radius: 12px; padding: 24px; border: 1px solid #1e293b;">
        <h2 style="color: #f1f5f9; margin: 0 0 16px; font-size: 18px;">
          {status_emoji} {blend_file}
        </h2>
        <div style="background: {status_color}15; border: 1px solid {status_color}30; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;">
          <p style="color: {status_color}; margin: 0; font-size: 14px; font-weight: 600;">
            {status_line}
          </p>
        </div>
        <table style="width: 100%; font-size: 13px; color: #94a3b8;">
          <tr>
            <td style="padding: 4px 0;">File</td>
            <td style="padding: 4px 0; text-align: right; color: #e2e8f0;">{blend_file}</td>
          </tr>
          <tr>
            <td style="padding: 4px 0;">Frames</td>
            <td style="padding: 4px 0; text-align: right; color: #e2e8f0;">{frames}</td>
          </tr>{vram_recovery_html}
        </table>
        """
    if animation_url:
        html += f"""
        <div style="margin-top: 24px; text-align: center;">
          <a href="{animation_url}" style="background-color: #3b82f6; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
            View Animation
          </a>
        </div>
        """
    html += """
        <hr style="border: none; border-top: 1px solid #1e293b; margin: 16px 0;" />
        <p style="color: #64748b; font-size: 11px; margin: 0; text-align: center;">
          Render Manager - <a href="https://rendermanager.com" style="color: #64748b;">rendermanager.com</a>
        </p>
      </div>
    </div>
    """

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": NOTIFICATION_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            print(f"[notify] Resend API error {resp.status_code}: {resp.text[:200]}")
        else:
            print(f"[notify] email sent to {to} ({event_type})")
    except Exception as exc:
        print(f"[notify] email send error: {exc}")


# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------

def _send_discord_notification(webhook_url: str, event_type: str, job: dict, animation_url: Optional[str] = None) -> None:
    """Send a rich embed notification to a Discord webhook."""
    if not _is_valid_discord_webhook(webhook_url):
        print(f"[notify] invalid Discord webhook URL, skipping")
        return

    blend_file = _short_blend_name(job.get("blend_relpath", "Unknown"))
    frames = f"{job.get('frame_start', '?')}-{job.get('frame_end', '?')}"
    vram_recovery = job.get("vram_recovery")

    if event_type == "completed":
        color = 0x22C55E  # green
        title = "✅ Render Complete"
        description = f"**{blend_file}** has finished rendering."
        if animation_url:
            description += f"\n\n[▶️ **View Animation**]({animation_url})"
    else:
        color = 0xEF4444  # red
        reason = job.get("fail_reason", "Unknown error")
        title = "❌ Render Failed"
        description = f"**{blend_file}** failed: {reason}"

    fields = [
        {"name": "File", "value": blend_file, "inline": True},
        {"name": "Frames", "value": frames, "inline": True},
    ]

    # Add VRAM recovery info if it was used
    if vram_recovery and isinstance(vram_recovery, dict) and vram_recovery.get("recovered_frames", 0) > 0:
        recovered = vram_recovery["recovered_frames"]
        tier_name = vram_recovery.get("max_tier_name", "unknown")
        fields.append({
            "name": "⚡ VRAM Recovery",
            "value": f"{recovered} frame{'s' if recovered != 1 else ''} recovered (max: {tier_name})",
            "inline": False,
        })

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "Render Manager"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        resp = httpx.post(
            webhook_url,
            json={"embeds": [embed]},
            timeout=10,
        )
        if resp.status_code >= 400:
            print(f"[notify] Discord webhook error {resp.status_code}: {resp.text[:200]}")
        else:
            print(f"[notify] Discord notification sent ({event_type})")
    except Exception as exc:
        print(f"[notify] Discord send error: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_blend_name(blend_relpath: str) -> str:
    """Extract just the filename from a blend file path."""
    return blend_relpath.replace("\\", "/").rsplit("/", 1)[-1] if blend_relpath else "Unknown"


def _is_valid_discord_webhook(url: str) -> bool:
    """Basic validation that a URL looks like a Discord webhook."""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and (parsed.netloc == "discord.com" or parsed.netloc.endswith(".discord.com"))
            and "/api/webhooks/" in parsed.path
        )
    except Exception:
        return False
