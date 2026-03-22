import { supabase } from "../supabaseClient";

// NEVER call getSession() or refreshSession() in the hot path — that races
// with Supabase's internal autoRefreshToken timer and causes SIGNED_OUT.
// Instead, we cache the token from onAuthStateChange and, on 401, wait
// briefly for Supabase's own refresh to deliver a new token, then retry.

let _cachedToken: string | undefined;

// Keep cache in sync — fires on login, logout, AND auto token refresh
supabase.auth.onAuthStateChange((_event, session) => {
  _cachedToken = session?.access_token;
});

// ── 401 retry strategy ───────────────────────────────────────────────────
// When the access token is expired but Supabase's auto-refresh hasn't
// delivered the new one yet, our request gets a 401.  Instead of calling
// refreshSession() (which would race), we wait up to 3 seconds for the
// onAuthStateChange listener to update _cachedToken with a fresh one,
// then retry once.

function _waitForNewToken(staleToken: string, timeoutMs = 3000): Promise<string | null> {
  return new Promise((resolve) => {
    // If token already changed (refresh happened between request and here)
    if (_cachedToken && _cachedToken !== staleToken) {
      resolve(_cachedToken);
      return;
    }

    const start = Date.now();
    const interval = setInterval(() => {
      if (_cachedToken && _cachedToken !== staleToken) {
        clearInterval(interval);
        resolve(_cachedToken);
      } else if (Date.now() - start >= timeoutMs) {
        clearInterval(interval);
        resolve(null); // timed out, token never refreshed
      }
    }, 100);
  });
}

// ── Public hook ──────────────────────────────────────────────────────────
export function useApi() {
  async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
    const token = _cachedToken;

    const headers: Record<string, string> = {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers as Record<string, string> | undefined),
    };

    if (opts.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    const res = await fetch(path, { ...opts, headers });

    // On 401, wait for Supabase's auto-refresh to deliver a new token
    if (res.status === 401 && token) {
      const freshToken = await _waitForNewToken(token);
      if (freshToken) {
        const retryHeaders: Record<string, string> = {
          ...headers,
          Authorization: `Bearer ${freshToken}`,
        };
        return fetch(path, { ...opts, headers: retryHeaders });
      }
    }

    return res;
  }

  async function apiJson<T>(path: string, opts: RequestInit = {}): Promise<T> {
    const res = await apiFetch(path, opts);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body.detail) {
          detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        }
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json() as Promise<T>;
  }

  return { apiFetch, apiJson };
}
