import { useEffect, useState } from "preact/hooks";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../supabaseClient";

// ---------------------------------------------------------------------------
// Global Session State
// ---------------------------------------------------------------------------
// DO NOT attach a new onAuthStateChange listener or call getSession() for
// every component. If a list of 50 items mounts, 50 concurrent getSession()
// calls will cause the Supabase client to fire 50 concurrent /token refresh
// API requests, immediately ratelimiting the IP and forcing a SIGNED_OUT event.
// ---------------------------------------------------------------------------

let _globalSession: Session | null = null;
let _globalLoading = true;
let _listeners: Array<() => void> = [];
let _signedOutTimer: ReturnType<typeof setTimeout> | null = null;

function _notifyListeners() {
  for (const fn of _listeners) fn();
}

// If Supabase hasn't responded within 3s (e.g. Safari ITP throttling),
// assume no session and stop blocking the UI.
setTimeout(() => {
  if (_globalLoading) {
    _globalLoading = false;
    _notifyListeners();
  }
}, 3000);

// Single global listener — onAuthStateChange fires INITIAL_SESSION on startup
// which already calls getSession() internally. An explicit getSession() call
// would duplicate the network request and double the wait on slow connections.
supabase.auth.onAuthStateChange((event, newSession) => {
  if (event === "SIGNED_OUT") {
    // Supabase can emit transient SIGNED_OUT events if a token refresh
    // races or gets a network error. Wait 2s before dropping the session.
    if (_signedOutTimer) clearTimeout(_signedOutTimer);
    _signedOutTimer = setTimeout(() => {
      _globalSession = null;
      _globalLoading = false;
      _signedOutTimer = null;
      _notifyListeners();
    }, 2000);
    return;
  }

  // Any other event (TOKEN_REFRESHED, SIGNED_IN, INITIAL_SESSION)
  if (_signedOutTimer && newSession) {
    clearTimeout(_signedOutTimer);
    _signedOutTimer = null;
  }

  _globalSession = newSession;
  _globalLoading = false;
  _notifyListeners();
});

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSession() {
  const [session, setSession] = useState<Session | null>(_globalSession);
  const [loading, setLoading] = useState(_globalLoading);

  useEffect(() => {
    // Sync React state with global state on mount and updates
    const updateState = () => {
      setSession(_globalSession);
      setLoading(_globalLoading);
    };

    // Catch any changes that happened between render and mount
    updateState();

    _listeners.push(updateState);
    return () => {
      _listeners = _listeners.filter((l) => l !== updateState);
    };
  }, []);

  return { session, loading };
}
