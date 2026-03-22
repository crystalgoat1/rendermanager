from server.server_supabase import get_supabase


def check_schema():
    sb = get_supabase()
    errors = []

    # Check profiles table
    try:
        res = sb.table("profiles").select("user_id, tier").limit(1).execute()
        print("[ok] profiles table exists (user_id, tier)")
    except Exception as e:
        errors.append(f"profiles: {e}")

    # Check subscriptions table
    try:
        res = sb.table("subscriptions").select(
            "id, user_id, stripe_customer_id, stripe_subscription_id, "
            "stripe_status, current_period_end, cancel_at_period_end"
        ).limit(1).execute()
        print("[ok] subscriptions table exists")
    except Exception as e:
        errors.append(f"subscriptions: {e}")

    # Check admin_grants table
    try:
        res = sb.table("admin_grants").select(
            "id, user_id, granted_by, granted_until, reason, revoked, revoked_at, revoked_by"
        ).limit(1).execute()
        print("[ok] admin_grants table exists")
        # Show active grants count
        from .server_util import utcnow_iso
        now_iso = utcnow_iso()
        active = sb.table("admin_grants").select("id", count="exact").eq(
            "revoked", False
        ).gt("granted_until", now_iso).execute()
        print(f"     active grants: {active.count or 0}")
        # Show all grants for debugging
        all_grants = sb.table("admin_grants").select(
            "user_id, granted_until, revoked, revoked_at"
        ).order("created_at", desc=True).limit(5).execute()
        for g in (all_grants.data or []):
            print(f"     grant: user={g['user_id'][:8]}... until={g.get('granted_until')} revoked={g.get('revoked')}")
    except Exception as e:
        errors.append(f"admin_grants: {e}")

    # Check other core tables
    for table in ["agents", "agent_tokens", "jobs", "preview_requests", "audit_log", "system_settings"]:
        try:
            sb.table(table).select("*", count="exact").limit(0).execute()
            print(f"[ok] {table} table exists")
        except Exception as e:
            errors.append(f"{table}: {e}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for err in errors:
            print(f"  [FAIL] {err}")
    else:
        print("\nAll tables OK.")

    # Show user count
    try:
        res = sb.auth.admin.list_users()
        users = res if isinstance(res, list) else getattr(res, 'users', [])
        print(f"\nAuth users: {len(users)}")
    except Exception as e:
        print(f"\nCould not list auth users: {e}")


if __name__ == "__main__":
    check_schema()
