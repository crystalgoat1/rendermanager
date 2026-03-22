# server/server_routes_billing.py
#
# Stripe subscription billing endpoints:
#   - Create Checkout Session (subscribe)
#   - Create Customer Portal session (manage / cancel)
#   - Webhook handler (lifecycle events)

import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request

from .server_auth import get_user_id_from_request, verify_supabase_jwt
from .server_settings import (
    STRIPE_SECRET_KEY,
    STRIPE_PUBLISHABLE_KEY,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_ID,
    FREE_HISTORY_LIMIT,
    MAX_AGENTS_FREE,
)
from .server_supabase import get_supabase
from .server_util import audit_log_event, get_user_tier, utcnow_iso

router = APIRouter(prefix="/api/billing")

stripe.api_key = STRIPE_SECRET_KEY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_email(request: Request) -> str:
    """Extract user email from the Supabase JWT."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    token = auth[len("Bearer "):]
    payload = verify_supabase_jwt(token)
    return payload.get("email", "")


def _get_or_create_stripe_customer(sb, user_id: str, email: str) -> str:
    """Look up existing Stripe customer or create one. Returns stripe_customer_id."""
    # Check if we already have a subscription row with a customer
    row = sb.table("subscriptions").select(
        "stripe_customer_id"
    ).eq("user_id", user_id).maybe_single().execute()

    if row and row.data and row.data.get("stripe_customer_id"):
        return row.data["stripe_customer_id"]

    # Create Stripe customer
    customer = stripe.Customer.create(
        email=email,
        metadata={"supabase_user_id": user_id},
    )

    # Upsert subscription row (may not exist yet)
    sb.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_customer_id": customer["id"],
        "updated_at": utcnow_iso(),
    }, on_conflict="user_id").execute()

    return customer["id"]


def _sync_subscription_to_db(sb, subscription, user_id: str = None, force: bool = False):
    """Sync a Stripe Subscription object to our subscriptions table and update cached tier."""
    # Resolve user_id from subscription metadata or customer metadata
    if not user_id:
        user_id = subscription.get("metadata", {}).get("supabase_user_id")
    if not user_id:
        # Look up from customer
        customer = stripe.Customer.retrieve(subscription["customer"])
        user_id = customer.get("metadata", {}).get("supabase_user_id")
    if not user_id:
        # Last resort: look up by stripe_customer_id in our DB
        row = sb.table("subscriptions").select("user_id").eq(
            "stripe_customer_id", subscription["customer"]
        ).maybe_single().execute()
        if row and row.data:
            user_id = row.data["user_id"]
    if not user_id:
        print(f"[stripe] cannot resolve user_id for subscription {subscription['id']}")
        return

    # Guard: don't let a stale webhook for an OLD subscription overwrite the
    # user's current active subscription (e.g. Stripe retrying a failed
    # customer.subscription.deleted for a previous sub).
    if not force:
        existing = sb.table("subscriptions").select(
            "stripe_subscription_id, stripe_status"
        ).eq("user_id", user_id).maybe_single().execute()
        if existing and existing.data:
            db_sub_id = existing.data.get("stripe_subscription_id")
            db_status = existing.data.get("stripe_status")
            if (db_sub_id and db_sub_id != subscription["id"]
                    and db_status in ("active", "trialing", "past_due")):
                print(f"[stripe] skipping sync for old sub {subscription['id']} "
                      f"— user {user_id} has active sub {db_sub_id}")
                return

    # Stripe API 2025-03-31+ moved current_period_end from Subscription to
    # Subscription Item level. Try subscription-level first (older API / webhook
    # payloads), then fall back to the first item's period.
    raw_period_end = subscription.get("current_period_end")
    if not raw_period_end:
        items = subscription.get("items", {})
        item_data = items.get("data", []) if isinstance(items, dict) else []
        if item_data:
            raw_period_end = item_data[0].get("current_period_end")

    period_end = None
    if raw_period_end:
        period_end = datetime.fromtimestamp(raw_period_end, tz=timezone.utc).isoformat()

    sb.table("subscriptions").upsert({
        "user_id": user_id,
        "stripe_customer_id": subscription["customer"],
        "stripe_subscription_id": subscription["id"],
        "stripe_status": subscription["status"],
        "current_period_end": period_end,
        "cancel_at_period_end": subscription.get("cancel_at_period_end") or subscription.get("cancel_at") is not None,
        "updated_at": utcnow_iso(),
    }, on_conflict="user_id").execute()

    # Update cached tier in profiles
    effective_tier = get_user_tier(sb, user_id)
    try:
        sb.table("profiles").update({"tier": effective_tier}).eq("user_id", user_id).execute()
    except Exception as exc:
        print(f"[stripe] failed to update cached tier for {user_id}: {exc}")

    # If user just dropped to free tier, enforce limits immediately
    if effective_tier == "free":
        _enforce_free_tier_limits(sb, user_id)


def _enforce_free_tier_limits(sb, user_id: str):
    """Enforce free-tier limits when a user downgrades from Pro.

    1. Trim job history to FREE_HISTORY_LIMIT (keep most recent).
    2. Disable VRAM recovery (Pro-only feature).
    3. Deactivate excess agents beyond MAX_AGENTS_FREE (keep most recently seen).
    """
    # 1) Trim job history ------------------------------------------------
    try:
        old_jobs = (
            sb.table("jobs")
            .select("job_id")
            .eq("user_id", user_id)
            .in_("status", ["completed", "failed", "canceled"])
            .order("created_at", desc=True)
            .range(FREE_HISTORY_LIMIT, FREE_HISTORY_LIMIT + 200)
            .execute()
        )
        deleted = 0
        for j in old_jobs.data or []:
            sb.table("jobs").delete().eq("job_id", j["job_id"]).execute()
            deleted += 1
        if deleted:
            print(f"[downgrade] trimmed {deleted} history jobs for user {user_id}")
    except Exception as exc:
        print(f"[downgrade] failed to trim job history for {user_id}: {exc}")

    # 2) Disable VRAM recovery -------------------------------------------
    try:
        sb.table("profiles").update(
            {"vram_recovery_enabled": False}
        ).eq("user_id", user_id).execute()
    except Exception as exc:
        print(f"[downgrade] failed to disable VRAM recovery for {user_id}: {exc}")

    # 3) Deactivate excess agents ----------------------------------------
    try:
        agents = (
            sb.table("agents")
            .select("agent_id, name, last_seen")
            .eq("user_id", user_id)
            .order("last_seen", desc=True)
            .execute()
        )
        agent_list = agents.data or []
        if len(agent_list) > MAX_AGENTS_FREE:
            # Keep the most recently seen agent(s), remove the rest
            to_remove = agent_list[MAX_AGENTS_FREE:]
            for agent in to_remove:
                aid = agent["agent_id"]
                aname = agent.get("name", "")
                # Revoke tokens
                if aname:
                    sb.table("agent_tokens").update(
                        {"revoked": True}
                    ).eq("user_id", user_id).eq("agent_name", aname).execute()
                # Delete agent record
                sb.table("agents").delete().eq("agent_id", aid).execute()
                audit_log_event("agent_deactivated_downgrade",
                                user_id=user_id, agent_id=aid)
            print(f"[downgrade] removed {len(to_remove)} excess agents for user {user_id}")
    except Exception as exc:
        print(f"[downgrade] failed to deactivate excess agents for {user_id}: {exc}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/create-checkout-session")
def create_checkout_session(request: Request):
    """Create a Stripe Checkout Session for the Pro monthly subscription."""
    uid = get_user_id_from_request(request)

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Billing is not configured")

    sb = get_supabase()

    # Don't allow if already subscribed via Stripe
    existing = sb.table("subscriptions").select(
        "stripe_status"
    ).eq("user_id", uid).maybe_single().execute()
    if existing and existing.data and existing.data.get("stripe_status") in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="Already subscribed")

    email = _get_user_email(request)
    customer_id = _get_or_create_stripe_customer(sb, uid, email)

    # Determine redirect URLs from the Origin header
    origin = request.headers.get("origin", "")
    success_url = f"{origin}/settings?checkout=success"
    cancel_url = f"{origin}/settings?checkout=canceled"

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"supabase_user_id": uid},
        allow_promotion_codes=True,
    )

    audit_log_event("stripe_checkout_created", user_id=uid)
    return {"url": session["url"]}


@router.post("/create-portal-session")
def create_portal_session(request: Request):
    """Create a Stripe Customer Portal session for subscription management."""
    uid = get_user_id_from_request(request)

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing is not configured")

    sb = get_supabase()
    row = sb.table("subscriptions").select(
        "stripe_customer_id"
    ).eq("user_id", uid).maybe_single().execute()

    if not row or not row.data or not row.data.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No billing account found")

    origin = request.headers.get("origin", "")
    return_url = f"{origin}/settings"

    session = stripe.billing_portal.Session.create(
        customer=row.data["stripe_customer_id"],
        return_url=return_url,
    )

    return {"url": session["url"]}


@router.get("/config")
def billing_config():
    """Return the Stripe publishable key for frontend use."""
    return {"publishable_key": STRIPE_PUBLISHABLE_KEY}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events. Unauthenticated — verified by signature."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        print(f"[stripe] webhook parse error: {exc}")
        raise HTTPException(status_code=400, detail="Bad payload")

    sb = get_supabase()
    event_type = event["type"]
    data_obj = event["data"]["object"]

    print(f"[stripe] webhook received: {event_type}")

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(sb, data_obj)

    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(sb, data_obj)

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(sb, data_obj)

    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(sb, data_obj)

    elif event_type == "invoice.paid":
        _handle_invoice_paid(sb, data_obj)

    return {"received": True}


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------

def _handle_checkout_completed(sb, session):
    """checkout.session.completed — new subscription created."""
    user_id = session.get("metadata", {}).get("supabase_user_id")
    subscription_id = session.get("subscription")

    if not subscription_id:
        return  # Not a subscription checkout

    # Fetch the full subscription object for details
    subscription = stripe.Subscription.retrieve(subscription_id)

    # Cancel any pre-existing different subscription in Stripe to prevent
    # stale webhooks from interfering with the new one.
    if user_id:
        old_row = sb.table("subscriptions").select(
            "stripe_subscription_id, stripe_status"
        ).eq("user_id", user_id).maybe_single().execute()
        if (old_row and old_row.data
                and old_row.data.get("stripe_subscription_id")
                and old_row.data["stripe_subscription_id"] != subscription_id
                and old_row.data.get("stripe_status") in ("active", "trialing", "past_due")):
            old_sub_id = old_row.data["stripe_subscription_id"]
            try:
                stripe.Subscription.cancel(old_sub_id)
                print(f"[stripe] canceled old sub {old_sub_id} for user {user_id}")
            except Exception as exc:
                print(f"[stripe] failed to cancel old sub {old_sub_id}: {exc}")

    # force=True bypasses the guard in _sync_subscription_to_db since this
    # is a new checkout and should always overwrite the existing row.
    _sync_subscription_to_db(sb, subscription, user_id=user_id, force=True)

    audit_log_event("stripe_subscribed", user_id=user_id,
                    subscription_id=subscription_id)
    print(f"[stripe] checkout completed for user {user_id}, sub {subscription_id}")


def _handle_subscription_updated(sb, subscription_data):
    """customer.subscription.updated — status change, renewal, cancel_at_period_end toggle."""
    sub_id = subscription_data.get("id")
    if not sub_id:
        return

    # Always fetch latest state from Stripe to avoid out-of-order webhook
    # issues (e.g. a stale event overwriting cancel_at_period_end).
    subscription = stripe.Subscription.retrieve(sub_id)

    # Guard: don't let an older "active" event overwrite a "canceled" status.
    incoming_status = subscription.get("status")
    if incoming_status == "active":
        existing = sb.table("subscriptions").select("stripe_status").eq(
            "stripe_subscription_id", sub_id
        ).maybe_single().execute()
        if existing and existing.data and existing.data.get("stripe_status") == "canceled":
            print(f"[stripe] ignoring stale 'active' update for already-canceled sub {sub_id}")
            return

    _sync_subscription_to_db(sb, subscription)

    print(f"[stripe] subscription updated: {subscription['id']} → {subscription['status']}"
          f" cancel_at_period_end={subscription.get('cancel_at_period_end')}")


def _handle_subscription_deleted(sb, subscription_data):
    """customer.subscription.deleted — subscription fully ended."""
    sub_id = subscription_data.get("id")
    if not sub_id:
        return

    # Try to get the latest state from Stripe for accuracy; fall back to
    # the raw webhook payload if the subscription is already fully gone.
    try:
        subscription = stripe.Subscription.retrieve(sub_id)
    except Exception:
        subscription = subscription_data

    _sync_subscription_to_db(sb, subscription)

    # Resolve user for audit log
    user_id = None
    row = sb.table("subscriptions").select("user_id").eq(
        "stripe_subscription_id", sub_id
    ).maybe_single().execute()
    if row and row.data:
        user_id = row.data["user_id"]

    audit_log_event("stripe_subscription_ended", user_id=user_id,
                    subscription_id=sub_id)
    print(f"[stripe] subscription deleted: {sub_id}")


def _handle_payment_failed(sb, invoice):
    """invoice.payment_failed — payment retry in progress."""
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return

    subscription = stripe.Subscription.retrieve(subscription_id)
    _sync_subscription_to_db(sb, subscription)
    print(f"[stripe] payment failed for subscription {subscription_id}")


def _handle_invoice_paid(sb, invoice):
    """invoice.paid — successful payment (renewal or recovery from past_due)."""
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return

    subscription = stripe.Subscription.retrieve(subscription_id)
    _sync_subscription_to_db(sb, subscription)
    print(f"[stripe] invoice paid for subscription {subscription_id}")
