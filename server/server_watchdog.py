# server/server_watchdog.py
#
# Background thread that detects agents that have gone offline
# and requeues any jobs they were working on.

import threading
import time
from datetime import datetime, timedelta, timezone

from .server_settings import WATCHDOG_INTERVAL_SECONDS, AGENT_OFFLINE_AFTER_SECONDS
from .server_util import utcnow_iso

_watchdog_started = False


def watchdog_loop():
    while True:
        try:
            _run_watchdog_tick()
        except Exception as exc:
            print(f"[watchdog] error: {exc}")
        try:
            _reap_stuck_cancels()
        except Exception as exc:
            print(f"[watchdog] reap_stuck_cancels error: {exc}")
        time.sleep(WATCHDOG_INTERVAL_SECONDS)


def _run_watchdog_tick():
    from .server_supabase import get_supabase
    sb = get_supabase()

    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=AGENT_OFFLINE_AFTER_SECONDS)
    ).isoformat()

    # Find agents that haven't sent a heartbeat recently and aren't already offline
    stale = (
        sb.table("agents")
        .select("agent_id")
        .lt("last_seen", cutoff)
        .neq("status", "offline")
        .execute()
    )
    if not stale.data:
        return

    for row in stale.data:
        agent_id = row["agent_id"]

        # Mark agent offline
        sb.table("agents").update({"status": "offline"}).eq("agent_id", agent_id).execute()

        # Handle in-progress jobs assigned to this agent
        jobs = (
            sb.table("jobs")
            .select("job_id, cancel_requested")
            .eq("agent_id", agent_id)
            .eq("status", "in_progress")
            .execute()
        )
        now = utcnow_iso()
        for job_row in (jobs.data or []):
            if job_row.get("cancel_requested"):
                # Job was already cancel-requested — finalize it immediately
                sb.table("jobs").update({
                    "status": "canceled",
                    "agent_id": None,
                    "assigned_at": None,
                    "fail_reason": "canceled by user (agent offline)",
                }).eq("job_id", job_row["job_id"]).execute()
                print(f"[watchdog] Canceled job {job_row['job_id']} (cancel_requested + agent {agent_id} offline)")
            else:
                # Requeue so another agent can pick it up
                sb.table("jobs").update({
                    "status": "queued",
                    "agent_id": None,
                    "assigned_at": None,
                    "requeued_at": now,
                    "requeued_reason": "agent offline",
                    "requeued_from_agent": agent_id,
                }).eq("job_id", job_row["job_id"]).execute()
                print(f"[watchdog] Requeued job {job_row['job_id']} because agent {agent_id} is offline")


def _reap_stuck_cancels():
    """Force-cancel jobs stuck in cancel_requested for over 15 seconds.

    Safety net for edge cases where the agent didn't terminate cleanly,
    or a queued job has cancel_requested but was never picked up.
    """
    from .server_supabase import get_supabase
    sb = get_supabase()

    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=15)
    ).isoformat()

    # Catch both in_progress AND queued jobs with cancel_requested.
    # Use cancel_requested_at as the time reference — this is when the
    # user actually clicked cancel, not when the job was first assigned.
    # Fall back to created_at for legacy rows without cancel_requested_at.
    stuck = (
        sb.table("jobs")
        .select("job_id, agent_id, status, cancel_requested_at, created_at")
        .in_("status", ["in_progress", "queued"])
        .eq("cancel_requested", True)
        .execute()
    )
    # Filter in Python: only reap if cancel was requested > 15s ago
    stuck_rows = []
    for row in (stuck.data or []):
        cancel_at = row.get("cancel_requested_at") or row.get("created_at")
        if cancel_at and cancel_at < cutoff:
            stuck_rows.append(row)
    for row in stuck_rows:
        agent_id = row.get("agent_id")
        sb.table("jobs").update({
            "status": "canceled",
            "agent_id": None,
            "assigned_at": None,
            "target_agent_id": None,
            "cancel_requested_at": None,
            "failed_at": utcnow_iso(),
            "fail_reason": "canceled by user (forced — agent unresponsive)",
        }).eq("job_id", row["job_id"]).execute()
        # Reset the agent to idle so it can pick up new work
        if agent_id:
            sb.table("agents").update({
                "status": "idle",
                "last_seen": utcnow_iso(),
            }).eq("agent_id", agent_id).eq("status", "busy").execute()
        print(f"[watchdog] Force-canceled stuck job {row['job_id']} ({row['status']} + cancel_requested > 15s)")


def start_watchdog_thread():
    global _watchdog_started
    if _watchdog_started:
        return
    _watchdog_started = True
    t = threading.Thread(target=watchdog_loop, daemon=True)
    t.start()
    print("[watchdog] started")
