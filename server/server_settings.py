# server/server_settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the server/ directory (works whether run from project root or server/)
load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

# ---------------------------------------------------------------------------
# Request / upload size limits
# ---------------------------------------------------------------------------
MAX_PREVIEW_BYTES = 100 * 1024 * 1024  # 100 MB — preview images + compiled videos
MAX_REQUEST_BYTES = 1 * 1024 * 1024   # 1 MB — all other requests

# ---------------------------------------------------------------------------
# Job limits
# ---------------------------------------------------------------------------
MIN_FRAME_NUMBER = 1
MAX_FRAME_NUMBER = 1_000_000
MAX_FRAMES_PER_JOB = 2000
MAX_QUEUED_JOBS_PER_USER = 5
FREE_HISTORY_LIMIT = 10  # Free-tier users keep only the 10 most recent completed jobs
JOB_HISTORY_TTL_DAYS = 90  # Auto-delete completed/failed/canceled jobs older than this
JOB_HISTORY_CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour — how often to check for expired jobs

# ---------------------------------------------------------------------------
# Auto-retry
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
AUTO_RETRY_ENABLED = True
AUTO_RETRY_BACKOFF_SECONDS = 15

# ---------------------------------------------------------------------------
# Watchdog (detects offline agents and requeues their jobs)
# ---------------------------------------------------------------------------
WATCHDOG_ENABLED = True
WATCHDOG_INTERVAL_SECONDS = 15
AGENT_OFFLINE_AFTER_SECONDS = 75

# ---------------------------------------------------------------------------
# Preview storage (local disk — replaces Supabase Storage for egress savings)
# ---------------------------------------------------------------------------
# All preview JPEGs and compiled MP4s are stored on VPS local disk and served
# directly through FastAPI.  This eliminates Supabase Storage egress costs.
# Structure: PREVIEW_STORAGE_DIR/{user_id}/{job_id}/frames/{frame}/{pass}.jpg
#            PREVIEW_STORAGE_DIR/{user_id}/{job_id}/latest.jpg
#            PREVIEW_STORAGE_DIR/{user_id}/{job_id}/passes/{pass}.jpg
#            PREVIEW_STORAGE_DIR/{user_id}/{job_id}/compile.mp4
PREVIEW_STORAGE_DIR = os.environ.get(
    "PREVIEW_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "preview_storage"),
)
PREVIEW_TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp_previews")  # legacy
PREVIEW_FRAME_TTL_FREE_SECONDS = 1800       # 30 min — free tier (no frame browser anyway)
PREVIEW_FRAME_TTL_PRO_SECONDS = 86400      # 24 hours — pro tier, instant browsing after long renders
PREVIEW_VIDEO_TTL_SECONDS = 86400          # 24 hours — compiled animations (match frame TTL)
PREVIEW_CLEANUP_INTERVAL_SECONDS = 300  # 5 min — cleanup check frequency
MAX_COMPILE_BYTES = 100 * 1024 * 1024  # 100 MB for compiled videos

# ---------------------------------------------------------------------------
# Frontend URL (used in notification emails and links)
# ---------------------------------------------------------------------------
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "https://rendermanager.com")

# ---------------------------------------------------------------------------
# Notifications (email via Resend, Discord webhooks)
# ---------------------------------------------------------------------------
NOTIFICATIONS_ENABLED = os.environ.get("NOTIFICATIONS_ENABLED", "true").lower() in ("true", "1", "yes")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFICATION_FROM_EMAIL = os.environ.get("NOTIFICATION_FROM_EMAIL", "Render Manager <no-reply@rendermanager.com>")

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
ADMIN_EMAILS = [e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]

# ---------------------------------------------------------------------------
# Stripe (subscription billing)
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")  # monthly Pro price

# ---------------------------------------------------------------------------
# Agent versioning
# ---------------------------------------------------------------------------
LATEST_AGENT_VERSION = "1.1.5"
MIN_AGENT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Tier limits
# ---------------------------------------------------------------------------
MAX_AGENTS_FREE = 1
MAX_AGENTS_PRO = 3

# ---------------------------------------------------------------------------
# Blend file scan limits (server-side enforcement)
# ---------------------------------------------------------------------------
MAX_BLEND_FILES = 500
MAX_BLEND_INFO_BYTES = 1 * 1024 * 1024  # 1 MB
