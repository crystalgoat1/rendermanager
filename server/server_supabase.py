# server/server_supabase.py
#
# Supabase service-role client singleton.
# The service-role key bypasses Row-Level Security — use it only on the server,
# never expose it to the browser or the agent.

import httpx
from supabase import create_client, Client
from .server_settings import SUPABASE_URL, SUPABASE_SERVICE_KEY

_client: Client | None = None

# httpx connection pool limits: expire idle connections quickly so we never try
# to reuse a connection that Supabase's server has already closed server-side.
# Without this, Supabase closing an idle pooled connection causes
# httpx.RemoteProtocolError: Server disconnected on the next request that tries
# to reuse it.
_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=5,
    keepalive_expiry=10,  # drop idle connections after 10 s (server closes at ~60 s)
)


def _patch_postgrest_session(client: Client) -> None:
    """Replace the PostgREST httpx.Client with one that expires idle connections quickly."""
    try:
        old = client.postgrest.session  # type: ignore[attr-defined]
        new = httpx.Client(
            base_url=str(old.base_url),
            headers=dict(old.headers),
            timeout=old.timeout,
            limits=_LIMITS,
        )
        client.postgrest.session = new  # type: ignore[attr-defined]
        old.close()
    except AttributeError:
        pass  # postgrest internals changed — fall back to default client behaviour


def get_supabase() -> Client:
    """Return the shared Supabase service-role client (created on first call)."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY env vars must be set"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        _patch_postgrest_session(_client)
    return _client
