# server/set_tier_cli.py
#
# Usage:
#   python -m server.set_tier_cli <user_id_or_email> grant <days>    Grant Pro for N days
#   python -m server.set_tier_cli <user_id_or_email> revoke          Revoke admin grants
#   python -m server.set_tier_cli <user_id_or_email> status          Show tier & subscription info
#   python -m server.set_tier_cli <user_id_or_email> pro             Legacy: grant 9999 days
#   python -m server.set_tier_cli <user_id_or_email> free            Legacy: revoke grants

import re
import sys
from datetime import datetime, timedelta, timezone

from .server_supabase import get_supabase
from .server_util import get_user_tier, get_subscription_info, utcnow_iso


def _resolve_user(sb, target: str) -> str:
    """Resolve a user_id or email to a user_id."""
    is_uuid = re.match(r"^[0-9a-f-]{36}$", target.lower())

    if is_uuid:
        profile = sb.table("profiles").select("user_id").eq("user_id", target).maybe_single().execute()
        if profile.data:
            return profile.data["user_id"]

    # Search by email
    print(f"Searching for user by email: {target}...")
    try:
        res = sb.auth.admin.list_users()
        users = res if isinstance(res, list) else getattr(res, 'users', [])
        for u in users:
            if u.email.lower() == target.lower():
                print(f"Found user with ID: {u.id}")
                return u.id
    except Exception as e:
        print(f"Error searching for user: {e}")
        sys.exit(1)

    print(f"Error: Could not find user with ID or email '{target}'")
    sys.exit(1)


def _cmd_grant(sb, user_id: str, days: int):
    """Grant Pro for N days."""
    granted_until = datetime.now(timezone.utc) + timedelta(days=days)
    sb.table("admin_grants").insert({
        "user_id": user_id,
        "granted_by": "00000000-0000-0000-0000-000000000000",  # CLI sentinel
        "granted_until": granted_until.isoformat(),
        "reason": f"CLI grant ({days} days)",
        "revoked": False,
    }).execute()
    sb.table("profiles").update({"tier": "pro"}).eq("user_id", user_id).execute()
    print(f"Granted Pro to {user_id} until {granted_until.isoformat()}")


def _cmd_revoke(sb, user_id: str):
    """Revoke all active admin grants."""
    now_iso = utcnow_iso()
    sb.table("admin_grants").update({
        "revoked": True,
        "revoked_at": now_iso,
        "revoked_by": "00000000-0000-0000-0000-000000000000",
    }).eq("user_id", user_id).eq("revoked", False).execute()

    effective_tier = get_user_tier(sb, user_id)
    sb.table("profiles").update({"tier": effective_tier}).eq("user_id", user_id).execute()
    print(f"Revoked admin grants for {user_id}. Effective tier: {effective_tier}")


def _cmd_status(sb, user_id: str):
    """Show current tier, source, subscription, and grant info."""
    tier = get_user_tier(sb, user_id)
    info = get_subscription_info(sb, user_id)
    print(f"User:           {user_id}")
    print(f"Effective tier: {tier}")
    print(f"Tier source:    {info['tier_source']}")
    if info["subscription_status"]:
        print(f"Stripe status:  {info['subscription_status']}")
        print(f"Period end:     {info['current_period_end']}")
        print(f"Cancel at end:  {info['cancel_at_period_end']}")
    if info["has_active_grant"]:
        print(f"Grant until:    {info['grant_until']}")
    if not info["subscription_status"] and not info["has_active_grant"]:
        print("No active subscription or grant.")


def run():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python -m server.set_tier_cli <user> grant <days>")
        print("  python -m server.set_tier_cli <user> revoke")
        print("  python -m server.set_tier_cli <user> status")
        print("  python -m server.set_tier_cli <user> pro       (legacy: grant 9999 days)")
        print("  python -m server.set_tier_cli <user> free      (legacy: revoke grants)")
        sys.exit(1)

    target = sys.argv[1]
    action = sys.argv[2].lower()

    sb = get_supabase()
    user_id = _resolve_user(sb, target)

    if action == "grant":
        if len(sys.argv) < 4:
            print("Error: grant requires a number of days. E.g.: grant 30")
            sys.exit(1)
        try:
            days = int(sys.argv[3])
        except ValueError:
            print(f"Error: '{sys.argv[3]}' is not a valid number of days.")
            sys.exit(1)
        if days < 1:
            print("Error: days must be >= 1")
            sys.exit(1)
        _cmd_grant(sb, user_id, days)

    elif action == "revoke":
        _cmd_revoke(sb, user_id)

    elif action == "status":
        _cmd_status(sb, user_id)

    elif action == "pro":
        # Legacy compat
        _cmd_grant(sb, user_id, 9999)

    elif action == "free":
        # Legacy compat
        _cmd_revoke(sb, user_id)

    else:
        print(f"Unknown action: {action}")
        print("Valid actions: grant, revoke, status, pro, free")
        sys.exit(1)


if __name__ == "__main__":
    run()
