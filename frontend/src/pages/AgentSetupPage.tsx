// AgentSetupPage — shown when the agent setup wizard opens the browser.
// URL pattern: /agent-setup?port=<port>&challenge=<pkce_challenge>&name=<agent_name>
//
// This page:
//   1. Ensures the user is logged in (redirects to login if not)
//   2. Asks the user to confirm they want to authorize the agent
//   3. Calls POST /api/agent-tokens/provision
//   4. Redirects the browser to http://127.0.0.1:<port>/callback?code=<auth_code>

import { useState } from "preact/hooks";
import { useSession } from "../hooks/useSession";
import { useApi } from "../hooks/useApi";
import { Icon } from "../components/Icon";

function parseParams() {
  const p = new URLSearchParams(window.location.search);
  return {
    port: p.get("port") || "",
    challenge: p.get("challenge") || "",
    agentName: p.get("name") || "My Agent",
  };
}

export function AgentSetupPage() {
  const { session, loading } = useSession();
  const { apiJson } = useApi();
  const [authorizing, setAuthorizing] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { port, challenge, agentName } = parseParams();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen p-6">
        <span className="text-sm text-slate-500">Loading...</span>
      </div>
    );
  }

  if (!session) {
    const returnUrl = encodeURIComponent(window.location.href);
    window.location.href = `/login?next=${returnUrl}`;
    return null;
  }

  if (!port || !challenge) {
    window.location.href = "/download";
    return null;
  }

  async function handleAuthorize() {
    setAuthorizing(true);
    setError(null);
    try {
      const data = await apiJson<{ auth_code: string }>("/api/agent-tokens/provision", {
        method: "POST",
        body: JSON.stringify({ agent_name: agentName, code_challenge: challenge }),
      });
      setDone(true);
      setTimeout(() => {
        window.location.href = `http://127.0.0.1:${port}/callback?code=${encodeURIComponent(data.auth_code)}`;
      }, 800);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authorization failed");
    } finally {
      setAuthorizing(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen p-6">
      <div className="bg-bg-elevated border border-white/10 rounded-xl p-10 max-w-[440px] w-full text-center">
        <Icon name="desktop_windows" className="text-[48px] text-slate-400 mb-4" />
        <h1 className="text-xl font-bold tracking-tight mb-2">Connect Computer</h1>
        <p className="text-sm text-slate-400 mb-7">
          The setup wizard on your PC wants to connect as:
          <br />
          <strong className="text-white">"{agentName}"</strong>
        </p>
        <p className="text-xs text-slate-500 mb-7">
          Logged in as <strong className="text-slate-400">{session.user.email}</strong>
        </p>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-sm text-red-400 text-left mb-5">
            {error}
          </div>
        )}

        {(() => {
          if (done) {
            return (
              <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 text-sm text-emerald-400 mb-5">
                Authorized! Sending credentials to the setup wizard...<br />
                You can close this tab once the wizard confirms success.
              </div>
            );
          }

          return (
            <div className="space-y-3">
              <button
                onClick={handleAuthorize}
                disabled={authorizing}
                className="w-full py-3 gradient-primary text-white font-semibold rounded-xl shadow-lg shadow-black/20 hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-60"
              >
                {authorizing ? "Connecting..." : "Connect this computer"}
              </button>
              <button
                onClick={() => window.close()}
                className="w-full py-3 bg-white/5 text-slate-400 border border-white/10 rounded-xl font-medium hover:bg-white/10 hover:text-slate-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
