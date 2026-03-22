import { useEffect, useState } from "preact/hooks";
import { useApi } from "./useApi";
import type { Profile } from "../types";
import { useSession } from "./useSession";

// ---------------------------------------------------------------------------
// Shared fetch deduplication
// ---------------------------------------------------------------------------
// Multiple components call useProfile(), each with its own useEffect.
// When Supabase fires auth events (token refresh), all of them trigger
// simultaneously, flooding the server with duplicate /api/profile requests.
//
// Fix: share a single in-flight promise and throttle to max 1 request per
// second.  All callers that trigger within the same window get the same result.
// ---------------------------------------------------------------------------

let _inflight: Promise<any> | null = null;
let _lastFetchTime = 0;
const MIN_INTERVAL_MS = 1000; // max 1 profile fetch per second

let _listeners: Array<(p: any, e: string | null) => void> = [];
let _cachedProfile: any = null;
let _cachedError: string | null = null;

function _notifyListeners(profile: any, error: string | null) {
    _cachedProfile = profile;
    _cachedError = error;
    for (const fn of _listeners) fn(profile, error);
}

async function _sharedFetch(apiFetch: (path: string) => Promise<Response>) {
    // If there's already a request in flight, return that promise
    if (_inflight) return _inflight;

    // Throttle: skip if we fetched less than MIN_INTERVAL_MS ago
    const now = Date.now();
    if (now - _lastFetchTime < MIN_INTERVAL_MS && _cachedProfile) {
        return;
    }

    _lastFetchTime = now;
    _inflight = (async () => {
        try {
            const res = await apiFetch("/api/profile");
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const data = await res.json();
            _notifyListeners(data, null);
        } catch (err: any) {
            console.error("Failed to fetch profile:", err);
            _notifyListeners(null, err.message);
        } finally {
            _inflight = null;
        }
    })();

    return _inflight;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useProfile() {
    const { session } = useSession();
    const { apiFetch } = useApi();
    const [profile, setProfile] = useState<Profile | null>(_cachedProfile);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(_cachedError);

    useEffect(() => {
        // Register this component as a listener for shared fetches
        const listener = (p: any, e: string | null) => {
            setProfile(p);
            setError(e);
            setLoading(false);
        };
        _listeners.push(listener);

        if (!session) {
            setProfile(null);
            setLoading(false);
            _cachedProfile = null;
            return () => {
                _listeners = _listeners.filter(l => l !== listener);
            };
        }

        // Trigger shared fetch (deduplicates automatically)
        // Only show loading spinner on initial fetch when no data exists yet
        if (!_cachedProfile) setLoading(true);
        _sharedFetch(apiFetch);

        return () => {
            _listeners = _listeners.filter(l => l !== listener);
        };
    }, [!!session]);

    const fetchProfile = async () => {
        // Manual refresh: bypass throttle by resetting timer
        _lastFetchTime = 0;
        if (!profile && !_cachedProfile) setLoading(true);
        await _sharedFetch(apiFetch);
    };

    const createCheckoutSession = async () => {
        try {
            const res = await apiFetch("/api/billing/create-checkout-session", { method: "POST" });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.url) {
                window.location.href = data.url;
            }
        } catch (err) {
            console.error("Create checkout session failed", err);
            throw err;
        }
    };

    const openCustomerPortal = async () => {
        try {
            const res = await apiFetch("/api/billing/create-portal-session", { method: "POST" });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.url) {
                window.location.href = data.url;
            }
        } catch (err) {
            console.error("Open customer portal failed", err);
            throw err;
        }
    };

    const setActiveAgent = async (agentId: string | null) => {
        try {
            const res = await apiFetch("/api/profile/active-agent", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ agent_id: agentId }),
            });
            if (!res.ok) throw new Error(await res.text());
            // Refresh profile so all components see the new active_agent_id
            _lastFetchTime = 0;
            await _sharedFetch(apiFetch);
        } catch (err) {
            console.error("Set active agent failed", err);
            throw err;
        }
    };

    return { profile, loading, error, refreshProfile: fetchProfile, createCheckoutSession, openCustomerPortal, setActiveAgent };
}
