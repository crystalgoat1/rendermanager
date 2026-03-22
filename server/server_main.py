# server/server_main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

from .server_settings import (
    MAX_REQUEST_BYTES,
    MAX_PREVIEW_BYTES,
    WATCHDOG_ENABLED,
    PREVIEW_STORAGE_DIR,
    PREVIEW_FRAME_TTL_FREE_SECONDS,
    PREVIEW_FRAME_TTL_PRO_SECONDS,
    PREVIEW_VIDEO_TTL_SECONDS,
    PREVIEW_CLEANUP_INTERVAL_SECONDS,
    JOB_HISTORY_TTL_DAYS,
    JOB_HISTORY_CLEANUP_INTERVAL_SECONDS,
)
from .server_watchdog import start_watchdog_thread
from .server_routes_agent import router as agent_router
from .server_routes_jobs import router as jobs_router
from .server_routes_auth import router as auth_router
from .server_routes_api import router as api_router
from .server_routes_billing import router as billing_router
from .server_routes_admin import router as admin_router, public_router as system_router


# ---------------------------------------------------------------------------
# Body size limiting middleware (unchanged from v1)
# ---------------------------------------------------------------------------

class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject requests with bodies larger than the configured limit.

    - Uses Content-Length when provided (fast path)
    - Counts bytes as they stream in for chunked uploads
    - Preview endpoint is allowed up to MAX_PREVIEW_BYTES; everything else is 1 MB
    """

    def __init__(self, app, max_bytes: int, preview_max_bytes: int):
        self.app = app
        self.max_bytes = int(max_bytes)
        self.preview_max_bytes = int(preview_max_bytes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        limit = self.preview_max_bytes if path.endswith("/preview/latest") or "/preview-upload" in path else self.max_bytes

        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
        }
        cl = headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            resp = PlainTextResponse("Request too large", status_code=413)
            await resp(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"") or b""
                received += len(body)
                if received > limit:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            resp = PlainTextResponse("Request too large", status_code=413)
            await resp(scope, receive, send)


# ---------------------------------------------------------------------------
# Temp preview cleanup
# ---------------------------------------------------------------------------

import os
import time
import threading
from pathlib import Path


def _cleanup_preview_storage():
    """Background thread: deletes expired preview files from local disk.

    Queries preview_requests where status='ready' and completed_at is older than
    the configured TTL. Deletes the corresponding local file and marks the row
    as 'expired'.
    """
    from datetime import datetime, timezone, timedelta
    from .server_supabase import get_supabase
    from .server_util import get_user_tier

    storage = Path(PREVIEW_STORAGE_DIR)
    storage.mkdir(parents=True, exist_ok=True)

    while True:
        time.sleep(PREVIEW_CLEANUP_INTERVAL_SECONDS)
        try:
            sb = get_supabase()
            now = datetime.now(timezone.utc)

            # Use free-tier TTL for the DB query (shortest) — we'll check
            # per-user tier before actually deleting pro users' files.
            frame_cutoff_free = (now - timedelta(seconds=PREVIEW_FRAME_TTL_FREE_SECONDS)).isoformat()
            video_cutoff = (now - timedelta(seconds=PREVIEW_VIDEO_TTL_SECONDS)).isoformat()

            # Find potentially expired frame previews (using free-tier cutoff)
            expired_frames = (
                sb.table("preview_requests")
                .select("request_id, job_id, user_id, type, frame, pass_name, completed_at")
                .eq("status", "ready")
                .eq("type", "frame")
                .lt("completed_at", frame_cutoff_free)
                .limit(50)
                .execute()
            )

            # Find expired compiled videos
            expired_videos = (
                sb.table("preview_requests")
                .select("request_id, job_id, user_id, type")
                .eq("status", "ready")
                .eq("type", "compile")
                .lt("completed_at", video_cutoff)
                .limit(10)
                .execute()
            )

            expired = (expired_frames.data or []) + (expired_videos.data or [])
            if not expired:
                continue

            # Cache tier lookups to avoid repeated DB queries within one cycle
            tier_cache: dict[str, str] = {}
            frame_cutoff_pro = (now - timedelta(seconds=PREVIEW_FRAME_TTL_PRO_SECONDS)).isoformat()

            expired_ids = []
            for row in expired:
                uid = row["user_id"]
                jid = row["job_id"]

                # Pro users get longer frame TTL — skip if not yet expired for them
                if row["type"] == "frame":
                    if uid not in tier_cache:
                        tier_cache[uid] = get_user_tier(sb, uid)
                    if tier_cache[uid] == "pro":
                        completed = row.get("completed_at", "")
                        if completed > frame_cutoff_pro:
                            continue  # Not expired yet for pro

                try:
                    if row["type"] == "compile":
                        fp = storage / uid / jid / "compile.mp4"
                    else:
                        frame = row.get("frame") or 0
                        pname = row.get("pass_name") or "Combined"
                        fp = storage / uid / jid / "frames" / str(frame) / f"{pname}.jpg"
                    if fp.is_file():
                        fp.unlink()
                except Exception:
                    pass  # File may already be gone
                expired_ids.append(row["request_id"])

            # Mark all as expired in the DB
            if expired_ids:
                for rid in expired_ids:
                    sb.table("preview_requests").update(
                        {"status": "expired"}
                    ).eq("request_id", rid).execute()
                print(f"[cleanup] Expired {len(expired_ids)} preview files from disk")

            # Clean up empty directories
            for d in sorted(storage.rglob("*"), reverse=True):
                try:
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass

        except Exception as e:
            print(f"[cleanup] Error cleaning preview storage: {e}")


# ---------------------------------------------------------------------------
# Job history cleanup (auto-delete old completed/failed/canceled jobs)
# ---------------------------------------------------------------------------

def _cleanup_old_jobs():
    """Background thread: deletes job records older than JOB_HISTORY_TTL_DAYS.

    Also cleans up any associated preview files and preview_requests rows.
    Runs every JOB_HISTORY_CLEANUP_INTERVAL_SECONDS (default: 1 hour).
    """
    from datetime import datetime, timezone, timedelta
    from .server_supabase import get_supabase

    storage = Path(PREVIEW_STORAGE_DIR)

    while True:
        time.sleep(JOB_HISTORY_CLEANUP_INTERVAL_SECONDS)
        try:
            sb = get_supabase()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=JOB_HISTORY_TTL_DAYS)).isoformat()

            # Find old completed/failed/canceled jobs
            old_jobs = (
                sb.table("jobs")
                .select("job_id, user_id, status, completed_at, failed_at")
                .in_("status", ["completed", "failed", "canceled"])
                .lt("created_at", cutoff)
                .limit(50)
                .execute()
            )

            if not old_jobs.data:
                continue

            deleted_count = 0
            for job in old_jobs.data:
                jid = job["job_id"]
                uid = job["user_id"]

                try:
                    # Delete associated preview_requests
                    sb.table("preview_requests").delete().eq("job_id", jid).execute()

                    # Delete preview files from disk
                    job_dir = storage / uid / jid
                    if job_dir.is_dir():
                        import shutil
                        shutil.rmtree(job_dir, ignore_errors=True)

                    # Delete the job record
                    sb.table("jobs").delete().eq("job_id", jid).execute()
                    deleted_count += 1
                except Exception as e:
                    print(f"[job-cleanup] Failed to delete job {jid}: {e}")

            if deleted_count:
                print(f"[job-cleanup] Deleted {deleted_count} jobs older than {JOB_HISTORY_TTL_DAYS} days")

        except Exception as e:
            print(f"[job-cleanup] Error during cleanup: {e}")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Render Manager API")

app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_REQUEST_BYTES,
    preview_max_bytes=MAX_PREVIEW_BYTES,
)

# CORS — the SPA origin must be in ALLOWED_ORIGINS env var in production
_origins_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Agent-Token"],
)

app.include_router(agent_router)
app.include_router(jobs_router)
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(billing_router)
app.include_router(admin_router)
app.include_router(system_router)


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS only when behind HTTPS (nginx sets X-Forwarded-Proto)
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)


@app.on_event("startup")
def startup():
    if WATCHDOG_ENABLED:
        start_watchdog_thread()
    # Start local preview storage cleanup thread
    t = threading.Thread(target=_cleanup_preview_storage, daemon=True, name="preview-cleanup")
    t.start()
    # Start job history cleanup thread (auto-delete jobs older than 90 days)
    t2 = threading.Thread(target=_cleanup_old_jobs, daemon=True, name="job-cleanup")
    t2.start()


@app.get("/health", include_in_schema=False)
def health() -> PlainTextResponse:
    return PlainTextResponse("ok", status_code=200)
