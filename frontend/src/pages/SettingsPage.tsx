import type { ComponentChildren } from "preact";
import { useState, useEffect, useCallback } from "preact/hooks";
import { Link } from "wouter";
import { useApi } from "../hooks/useApi";
import { useAgents } from "../hooks/useAgent";
import { useSession } from "../hooks/useSession";
import { useProfile } from "../hooks/useProfile";
import { supabase } from "../supabaseClient";
import { Icon } from "../components/Icon";
import type {
  Agent, NotificationPreferences,
  AdminStats, AdminSystemStatus, AdminUserDetails, AuditLogEntry,
} from "../types";

function AgentRow({ agent, onDelete, isActive, onSetActive, showSelector }: { agent: Agent; onDelete: (id: string) => void; isActive: boolean; onSetActive: (id: string) => void; showSelector: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { apiJson } = useApi();

  const isOnline = agent.status !== "offline";
  const isRendering = agent.status === "busy";

  const statusLabel = isRendering ? "Rendering" : isOnline ? "Online" : "Offline";
  const statusColor = isRendering
    ? "bg-primary/10 text-primary border-primary/20"
    : isOnline
      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
      : "bg-slate-800 text-slate-500 border-white/10";

  async function handleDelete() {
    if (!confirming) { setConfirming(true); return; }
    setDeleting(true);
    try {
      await apiJson(`/api/agents/${agent.agent_id}`, { method: "DELETE" });
      onDelete(agent.agent_id);
    } catch (err: unknown) {
      console.error("Failed to remove computer:", err);
      alert("Failed to remove computer. Please try again.");
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  const lastSeen = agent.last_seen
    ? new Date(agent.last_seen).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    })
    : "Never";

  return (
    <div className="flex items-center gap-4 p-4 hover:bg-white/[0.02] transition-colors border-b border-white/5 last:border-b-0">
      {/* Active indicator / set active button — only shown when multiple workstations */}
      {showSelector && (
        <div className="shrink-0">
          <button
            onClick={() => onSetActive(agent.agent_id)}
            title={isActive ? "Currently active workstation" : "Set as active workstation"}
            className={`size-8 rounded-full border-2 flex items-center justify-center transition-all ${isActive
              ? "border-primary bg-primary/20 text-primary cursor-default"
              : "border-white/10 text-slate-600 hover:border-primary/40 hover:text-primary/60 cursor-pointer"
              }`}
          >
            {isActive && <span className="size-3 rounded-full bg-primary" />}
          </button>
        </div>
      )}

      {/* Status dot */}
      <div className="shrink-0">
        {isRendering ? (
          <span className="relative flex size-3">
            <span className="animate-ping absolute inline-flex size-full rounded-full bg-primary opacity-60" />
            <span className="relative inline-flex rounded-full size-3 bg-primary" />
          </span>
        ) : (
          <span className={`size-3 rounded-full inline-block ${isOnline ? "bg-emerald-400" : "bg-slate-600"}`} />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold truncate">{agent.name || "Unnamed"}</p>
          {isActive && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border bg-primary/10 text-primary border-primary/20">
              Active
            </span>
          )}
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border ${statusColor}`}>
            {statusLabel}
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-0.5">Last seen: {lastSeen}</p>
        {agent.blend_files && agent.blend_files.length > 0 && (
          <p className="text-[10px] text-slate-500 mt-0.5">
            {agent.blend_files.length} .blend file{agent.blend_files.length !== 1 ? "s" : ""} available
          </p>
        )}
      </div>

      {/* Delete / confirm */}
      {confirming ? (
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-red-400 font-medium hidden sm:inline">Remove this computer?</span>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="px-3 py-1.5 rounded-lg bg-red-500 hover:bg-red-600 text-white text-xs font-bold transition-colors disabled:opacity-60"
          >
            {deleting ? "Removing..." : "Confirm"}
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="px-3 py-1.5 rounded-lg bg-white/5 text-slate-400 text-xs font-bold hover:bg-white/10 transition-colors"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={handleDelete}
          title="Remove this computer and revoke its access"
          className="shrink-0 p-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
        >
          <Icon name="logout" className="text-base" />
        </button>
      )}
    </div>
  );
}



function NotificationsSection({ email, profile }: { email: string; profile: any }) {
  const { apiJson } = useApi();
  const defaultPrefs: NotificationPreferences = {
    email_enabled: true,
    discord_enabled: false,
    discord_webhook_url: null,
    notify_on_complete: true,
    notify_on_failure: true,
    notify_on_agent_offline: false,
  };
  const prefs: NotificationPreferences = profile?.notification_preferences || defaultPrefs;

  const [emailEnabled, setEmailEnabled] = useState(prefs.email_enabled);
  const [discordEnabled, setDiscordEnabled] = useState(prefs.discord_enabled);
  const [discordUrl, setDiscordUrl] = useState(prefs.discord_webhook_url || "");
  const [notifyComplete, setNotifyComplete] = useState(prefs.notify_on_complete);
  const [notifyFailure, setNotifyFailure] = useState(prefs.notify_on_failure);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const saveTimeoutRef = useState<ReturnType<typeof setTimeout> | null>(null);

  // Sync state when profile loads/changes
  const prefsJson = JSON.stringify(profile?.notification_preferences);
  useState(() => {
    // Initial sync only
  });

  async function save(updates: Partial<NotificationPreferences>) {
    setSaveStatus("saving");
    try {
      await apiJson("/api/notification-preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      setSaveStatus("saved");
      setUrlError(null);
      if (saveTimeoutRef[0]) clearTimeout(saveTimeoutRef[0]);
      saveTimeoutRef[0] = setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (err: any) {
      setSaveStatus("error");
      if (err?.message?.includes("Discord webhook")) {
        setUrlError(err.message);
      }
    }
  }

  function handleToggle(field: string, value: boolean, setter: (v: boolean) => void) {
    setter(value);
    save({ [field]: value });
  }

  // Debounced Discord URL save
  const urlSaveRef = useState<ReturnType<typeof setTimeout> | null>(null);
  function handleDiscordUrlChange(val: string) {
    setDiscordUrl(val);
    setUrlError(null);
    if (urlSaveRef[0]) clearTimeout(urlSaveRef[0]);
    urlSaveRef[0] = setTimeout(() => {
      save({ discord_webhook_url: val || "" });
    }, 800);
  }

  const [expanded, setExpanded] = useState(false);

  return (
    <section className="bg-bg-surface rounded-xl overflow-hidden border border-white/5">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between cursor-pointer hover:bg-white/[0.02] transition-colors"
      >
        <div className="text-left">
          <h2 className="text-base font-bold">Notifications</h2>
          <p className="text-xs text-slate-500 mt-0.5">Get notified when renders finish or fail.</p>
        </div>
        <div className="flex items-center gap-2">
          {saveStatus === "saving" && (
            <span className="text-[10px] text-slate-500 animate-pulse">Saving...</span>
          )}
          {saveStatus === "saved" && (
            <span className="text-[10px] text-emerald-400 flex items-center gap-1">
              <Icon name="check" className="text-xs" /> Saved
            </span>
          )}
          <Icon name={expanded ? "expand_less" : "expand_more"} className="text-slate-500 text-xl" />
        </div>
      </button>

      {expanded && <div className="p-5 space-y-4 border-t border-white/5">
        {/* ── Channels ── */}
        <div className="space-y-3">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Channels</p>

          {/* Email toggle */}
          <div className="flex items-center justify-between gap-4 p-3 bg-bg-base/50 rounded-lg border border-white/5">
            <div className="flex items-center gap-3 min-w-0">
              <div className="size-8 rounded-lg bg-bg-base flex items-center justify-center shrink-0">
                <Icon name="mail" className="text-slate-400 text-lg" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold">Email</p>
                <p className="text-[10px] text-slate-500 truncate">{email || "Your account email"}</p>
              </div>
            </div>
            <button
              onClick={() => handleToggle("email_enabled", !emailEnabled, setEmailEnabled)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${emailEnabled ? "bg-primary" : "bg-slate-700"}`}
            >
              <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${emailEnabled ? "translate-x-5" : "translate-x-0"}`} />
            </button>
          </div>

          {/* Discord toggle + URL */}
          <div className="p-3 bg-bg-base/50 rounded-lg border border-white/5 space-y-3">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <div className="size-8 rounded-lg bg-bg-base flex items-center justify-center shrink-0">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="size-4 text-[#5865F2]">
                    <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold">Discord Webhook</p>
                  <p className="text-[10px] text-slate-500">Get notifications in a Discord channel</p>
                </div>
              </div>
              <button
                onClick={() => handleToggle("discord_enabled", !discordEnabled, setDiscordEnabled)}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${discordEnabled ? "bg-primary" : "bg-slate-700"}`}
              >
                <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${discordEnabled ? "translate-x-5" : "translate-x-0"}`} />
              </button>
            </div>

            {discordEnabled && (
              <div className="space-y-1.5">
                <input
                  type="url"
                  value={discordUrl}
                  onChange={(e) => handleDiscordUrlChange((e.target as HTMLInputElement).value)}
                  placeholder="https://discord.com/api/webhooks/..."
                  className={`w-full px-3 py-2 bg-bg-base text-sm rounded-lg border ${urlError ? "border-red-500/50 focus:ring-red-500/50" : "border-white/10 focus:ring-primary/50"} focus:ring-1 focus:outline-none placeholder-slate-600 transition-colors`}
                />
                {urlError && (
                  <p className="text-[11px] text-red-400 flex items-center gap-1">
                    <Icon name="error" className="text-xs" /> {urlError}
                  </p>
                )}
                <p className="text-[10px] text-slate-600">
                  Server Settings → Integrations → Webhooks → New Webhook → Copy URL
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Events ── */}
        <div className="space-y-3">
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Notify me on</p>

          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={notifyComplete}
              onChange={() => handleToggle("notify_on_complete", !notifyComplete, setNotifyComplete)}
              className="size-4 rounded border-white/20 bg-bg-base text-primary accent-primary cursor-pointer"
            />
            <div>
              <p className="text-sm font-medium group-hover:text-white transition-colors">Render completed</p>
              <p className="text-[10px] text-slate-500">When a render finishes successfully</p>
            </div>
          </label>

          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={notifyFailure}
              onChange={() => handleToggle("notify_on_failure", !notifyFailure, setNotifyFailure)}
              className="size-4 rounded border-white/20 bg-bg-base text-primary accent-primary cursor-pointer"
            />
            <div>
              <p className="text-sm font-medium group-hover:text-white transition-colors">Render failed</p>
              <p className="text-[10px] text-slate-500">When a render fails without auto-retry</p>
            </div>
          </label>

        </div>
      </div>}
    </section>
  );
}

// ---------------------------------------------------------------------------
// VRAM Recovery (Pro feature)
// ---------------------------------------------------------------------------

function VRAMRecoverySection({ profile }: { profile: any }) {
  const { apiJson } = useApi();
  const isPro = profile?.tier === "pro";
  const [enabled, setEnabled] = useState(!!profile?.vram_recovery_enabled);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const saveTimeoutRef = useState<ReturnType<typeof setTimeout> | null>(null);
  const [expanded, setExpanded] = useState(false);

  // Sync when profile loads
  useEffect(() => {
    if (profile) setEnabled(!!profile.vram_recovery_enabled);
  }, [profile?.vram_recovery_enabled]);

  async function toggleEnabled(value: boolean) {
    setEnabled(value);
    setSaveStatus("saving");
    try {
      await apiJson("/api/vram-recovery", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: value }),
      });
      setSaveStatus("saved");
      if (saveTimeoutRef[0]) clearTimeout(saveTimeoutRef[0]);
      saveTimeoutRef[0] = setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
      setEnabled(!value); // revert
    }
  }

  return (
    <section className="bg-bg-surface rounded-xl overflow-hidden border border-white/5">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between cursor-pointer hover:bg-white/[0.02] transition-colors"
      >
        <div className="text-left">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold">VRAM Recovery</h2>
            {!isPro && (
              <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-primary/15 text-primary rounded">
                Pro
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Automatically recover frames that fail due to GPU memory limits.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {saveStatus === "saving" && (
            <span className="text-[10px] text-slate-500 animate-pulse">Saving...</span>
          )}
          {saveStatus === "saved" && (
            <span className="text-[10px] text-emerald-400 flex items-center gap-1">
              <Icon name="check" className="text-xs" /> Saved
            </span>
          )}
          <Icon name={expanded ? "expand_less" : "expand_more"} className="text-slate-500 text-xl" />
        </div>
      </button>

      {expanded && (
        <div className="p-5 space-y-4 border-t border-white/5">
          {/* Toggle */}
          <div className="flex items-center justify-between gap-4 p-3 bg-bg-base/50 rounded-lg border border-white/5">
            <div className="flex items-center gap-3 min-w-0">
              <div className="size-8 rounded-lg bg-bg-base flex items-center justify-center shrink-0">
                <Icon name="memory" className="text-slate-400 text-lg" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold">Enable VRAM Recovery</p>
                <p className="text-[10px] text-slate-500">Cycles GPU renders only</p>
              </div>
            </div>
            <button
              onClick={() => isPro && toggleEnabled(!enabled)}
              disabled={!isPro}
              className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                !isPro ? "opacity-40 cursor-not-allowed bg-slate-700" :
                enabled ? "bg-primary cursor-pointer" : "bg-slate-700 cursor-pointer"
              }`}
            >
              <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${enabled ? "translate-x-5" : "translate-x-0"}`} />
            </button>
          </div>

          {/* Info */}
          <div className="space-y-2 text-[11px] text-slate-400 leading-relaxed">
            <p>
              When a frame runs out of GPU memory, the agent automatically retries with
              progressively less VRAM-intensive settings. All adjustments are non-destructive
              - output is pixel-identical. Normal renders are completely unaffected.
            </p>
            <p className="text-slate-500">
              For best results, try to optimize your scene to fit in VRAM first. VRAM Recovery
              is a safety net, not a substitute for scene optimization.
            </p>
          </div>

          {/* Recovery stages */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Recovery stages</p>
            <div className="space-y-1.5">
              {[
                { icon: "database", label: "Disable persistent data", desc: "Frees cached scene data between frames" },
                { icon: "grid_view", label: "Reduce tile size", desc: "Smaller GPU memory allocation per tile" },
                { icon: "memory_alt", label: "CPU fallback", desc: "Bypasses GPU VRAM entirely (slower)" },
              ].map((stage, i) => (
                <div key={i} className="flex items-start gap-2.5 p-2 bg-bg-base/30 rounded-md">
                  <div className="size-5 rounded flex items-center justify-center shrink-0 mt-0.5 bg-bg-base">
                    <span className="text-[10px] font-bold text-slate-500">{i + 1}</span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-slate-300">{stage.label}</p>
                    <p className="text-[10px] text-slate-500">{stage.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}


// ---------------------------------------------------------------------------
// Admin Dashboard (expanded)
// ---------------------------------------------------------------------------

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-bg-base/50 rounded-lg border border-white/5 p-3 text-center">
      <p className={`text-xl font-bold ${color || "text-slate-200"}`}>{value}</p>
      <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mt-0.5">{label}</p>
    </div>
  );
}

// ── Confirm Modal ──
function ConfirmModal({
  open, title, description, confirmLabel, danger, onConfirm, onCancel,
}: {
  open: boolean; title: string; description: string; confirmLabel: string;
  danger?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onCancel}>
      <div className="bg-bg-surface border border-white/10 rounded-xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-white/5">
          <h3 className="text-sm font-bold">{title}</h3>
          <p className="text-xs text-slate-400 mt-1">{description}</p>
        </div>
        <div className="px-5 py-3 flex justify-end gap-2 bg-white/[0.01]">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200 rounded-lg hover:bg-white/5 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-bold rounded-lg border transition-all ${
              danger
                ? "bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20"
                : "bg-primary/10 hover:bg-primary/20 text-primary border-primary/20"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Collapsible Section ──
function AdminSection({
  title, icon, children, defaultOpen = false, badge,
}: {
  title: string; icon: string; children: ComponentChildren;
  defaultOpen?: boolean; badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-white/5 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-white/[0.02] hover:bg-white/[0.04] transition-colors text-left"
      >
        <Icon name={icon} className="text-slate-400 text-lg shrink-0" />
        <span className="text-sm font-bold flex-1">{title}</span>
        {badge && (
          <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">
            {badge}
          </span>
        )}
        <Icon name={open ? "expand_less" : "expand_more"} className="text-slate-500 text-sm shrink-0" />
      </button>
      {open && <div className="px-4 pt-5 pb-4 border-t border-white/5 space-y-3">{children}</div>}
    </div>
  );
}

function UserDetailPanel({ userId, email, tier, tierSource, onGrantPro, onRevoke, updatingId }: {
  userId: string; email: string; tier: string; tierSource: string;
  onGrantPro: (userId: string, email: string) => void;
  onRevoke: (userId: string, email: string, tierSource: string) => void;
  updatingId: string | null;
}) {
  const { apiJson } = useApi();
  const [details, setDetails] = useState<AdminUserDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ jobId: string; action: "cancel" | "requeue"; filename: string } | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<{ agentId: string; name: string } | null>(null);

  useEffect(() => {
    setLoading(true);
    apiJson(`/api/admin/user/${userId}/details`)
      .then((data: any) => setDetails(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  async function executeJobAction(jobId: string, action: "cancel" | "requeue") {
    setConfirmAction(null);
    setActionLoading(jobId);
    try {
      await apiJson(`/api/admin/jobs/${jobId}/${action}`, { method: "POST" });
      const data = await apiJson(`/api/admin/user/${userId}/details`) as any;
      setDetails(data);
    } catch (err: any) {
      alert(`Failed to ${action} job: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function executeDisconnectAgent(agentId: string) {
    setConfirmDisconnect(null);
    setActionLoading(agentId);
    try {
      await apiJson(`/api/admin/agents/${agentId}`, { method: "DELETE" });
      const data = await apiJson(`/api/admin/user/${userId}/details`) as any;
      setDetails(data);
    } catch (err: any) {
      alert(`Failed to disconnect agent: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  }

  if (loading) return <div className="px-4 py-3 text-xs text-slate-500">Loading details...</div>;
  if (!details) return <div className="px-4 py-3 text-xs text-red-400">Failed to load details</div>;

  return (
    <div className="px-4 py-3 space-y-3 bg-white/[0.01] border-t border-white/5">
      <ConfirmModal
        open={!!confirmAction}
        title={confirmAction?.action === "cancel" ? "Cancel this job?" : "Requeue this job?"}
        description={confirmAction?.action === "cancel"
          ? `This will cancel "${confirmAction?.filename}" and stop any in-progress rendering.`
          : `This will requeue "${confirmAction?.filename}" and it will be picked up by the next available agent.`}
        confirmLabel={confirmAction?.action === "cancel" ? "Yes, Cancel Job" : "Yes, Requeue Job"}
        danger={confirmAction?.action === "cancel"}
        onConfirm={() => confirmAction && executeJobAction(confirmAction.jobId, confirmAction.action)}
        onCancel={() => setConfirmAction(null)}
      />
      <ConfirmModal
        open={!!confirmDisconnect}
        title="Disconnect this agent?"
        description={`This will remove "${confirmDisconnect?.name}" and revoke its tokens. The agent will stop polling automatically.`}
        confirmLabel="Yes, Disconnect"
        danger
        onConfirm={() => confirmDisconnect && executeDisconnectAgent(confirmDisconnect.agentId)}
        onCancel={() => setConfirmDisconnect(null)}
      />

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onGrantPro(userId, email)}
          disabled={updatingId === userId}
          className="px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[11px] font-bold rounded-md border border-emerald-500/20 transition-all"
        >
          Grant Pro
        </button>
        {tierSource === "admin_grant" && (
          <button
            onClick={() => onRevoke(userId, email, tierSource)}
            disabled={updatingId === userId}
            className="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-[11px] font-bold rounded-md border border-red-500/20 transition-all"
          >
            Revoke Grant
          </button>
        )}
      </div>

      {/* Agents */}
      <div>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5">
          Agents ({details.agents.length})
        </p>
        {details.agents.length === 0 ? (
          <p className="text-xs text-slate-600 italic">No agents registered</p>
        ) : (
          <div className="space-y-1">
            {details.agents.map((a) => (
              <div key={a.agent_id} className="flex items-center gap-2 text-xs">
                <span className={`size-2 rounded-full shrink-0 ${
                  a.status === "busy" ? "bg-primary" : a.status === "idle" ? "bg-emerald-400" : "bg-slate-600"
                }`} />
                <span className="font-medium truncate">{a.name}</span>
                <span className="text-slate-500">{a.status}</span>
                <span className="ml-auto flex items-center gap-2">
                  {a.last_seen && (
                    <span className="text-slate-600 text-[10px]">
                      {new Date(a.last_seen).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  )}
                  <button
                    onClick={() => setConfirmDisconnect({ agentId: a.agent_id, name: a.name })}
                    disabled={actionLoading === a.agent_id}
                    className="px-2 py-0.5 bg-red-500/10 text-red-400 text-[10px] font-bold rounded border border-red-500/20 hover:bg-red-500/20 transition-all disabled:opacity-40"
                  >
                    Disconnect
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent Jobs */}
      <div>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5">
          Recent Jobs ({details.jobs.length})
        </p>
        {details.jobs.length === 0 ? (
          <p className="text-xs text-slate-600 italic">No jobs</p>
        ) : (
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {details.jobs.map((j) => {
              const statusColors: Record<string, string> = {
                completed: "text-emerald-400",
                failed: "text-red-400",
                canceled: "text-slate-500",
                in_progress: "text-primary",
                queued: "text-amber-400",
                paused: "text-amber-400",
              };
              const canCancel = j.status === "in_progress" || j.status === "queued" || j.status === "paused";
              const canRequeue = j.status === "failed" || j.status === "canceled";
              const filename = j.blend_relpath.split(/[/\\]/).pop() || j.blend_relpath;

              return (
                <div key={j.job_id} className="flex items-center gap-2 text-xs py-1">
                  <span className={`font-bold text-[10px] uppercase w-16 shrink-0 ${statusColors[j.status] || "text-slate-400"}`}>
                    {j.status}
                  </span>
                  <span className="truncate flex-1" title={j.blend_relpath}>
                    {filename}
                  </span>
                  <span className="text-slate-600 text-[10px] shrink-0">
                    {j.frame_start}-{j.frame_end}
                  </span>
                  {canCancel && (
                    <button
                      onClick={() => setConfirmAction({ jobId: j.job_id, action: "cancel", filename })}
                      disabled={actionLoading === j.job_id}
                      className="px-2 py-0.5 bg-red-500/10 text-red-400 text-[10px] font-bold rounded border border-red-500/20 hover:bg-red-500/20 transition-all disabled:opacity-40 shrink-0"
                    >
                      Cancel
                    </button>
                  )}
                  {canRequeue && (
                    <button
                      onClick={() => setConfirmAction({ jobId: j.job_id, action: "requeue", filename })}
                      disabled={actionLoading === j.job_id}
                      className="px-2 py-0.5 bg-primary/10 text-primary text-[10px] font-bold rounded border border-primary/20 hover:bg-primary/20 transition-all disabled:opacity-40 shrink-0"
                    >
                      Requeue
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function AuditLogSection({
  loadAuditLog, auditLog, auditFilter, setAuditFilter,
}: {
  loadAuditLog: () => void;
  auditLog: AuditLogEntry[] | null;
  auditFilter: string;
  setAuditFilter: (v: string) => void;
}) {
  // Load on mount (i.e. when section is expanded)
  useEffect(() => { loadAuditLog(); }, []);

  return (
    <AdminSection title="Audit Log" icon="history">
      <input
        type="text"
        value={auditFilter}
        onInput={(e) => setAuditFilter((e.target as HTMLInputElement).value)}
        placeholder="Filter by event name (e.g. admin_set_tier)..."
        className="w-full px-3 py-2 bg-bg-base text-xs rounded-lg border border-white/10 focus:border-primary/50 focus:ring-1 focus:ring-primary/50 focus:outline-none placeholder-slate-600 transition-colors"
      />
      {auditLog === null ? (
        <p className="text-xs text-slate-500">Loading...</p>
      ) : auditLog.length === 0 ? (
        <p className="text-xs text-slate-600 italic">No entries found.</p>
      ) : (
        <div className="max-h-64 overflow-y-auto space-y-1">
          {auditLog.map((entry, i) => (
            <details key={i} className="group">
              <summary className="flex items-center gap-2 text-xs cursor-pointer py-1 hover:bg-white/[0.02] rounded px-2 list-none">
                <span className="text-[10px] text-slate-600 shrink-0 w-28">
                  {new Date(entry.created_at).toLocaleString("en-US", {
                    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                  })}
                </span>
                <span className="font-mono text-primary font-medium">{entry.event}</span>
                <Icon name="expand_more" className="text-slate-600 text-xs ml-auto group-open:rotate-180 transition-transform" />
              </summary>
              <pre className="text-[10px] text-slate-500 bg-bg-base/50 rounded p-2 mx-2 mb-1 overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(entry.details, null, 2)}
                {entry.user_id && `\nuser_id: ${entry.user_id}`}
                {entry.job_id && `\njob_id: ${entry.job_id}`}
              </pre>
            </details>
          ))}
        </div>
      )}
    </AdminSection>
  );
}

function AdminDashboard() {
  const { apiJson } = useApi();

  // ── Stats ──
  const [stats, setStats] = useState<AdminStats | null>(null);
  const loadStats = useCallback(() => {
    apiJson("/api/admin/stats").then((d: any) => setStats(d)).catch(() => {});
  }, []);
  useEffect(() => { loadStats(); }, []);

  // ── Emergency Pause ──
  const [systemStatus, setSystemStatus] = useState<AdminSystemStatus | null>(null);
  const [pauseReason, setPauseReason] = useState("");
  const [cancelActive, setCancelActive] = useState(false);
  const [pauseLoading, setPauseLoading] = useState(false);
  const [confirmPause, setConfirmPause] = useState(false);
  const [confirmResume, setConfirmResume] = useState(false);

  const loadSystemStatus = useCallback(() => {
    apiJson("/api/admin/system-status").then((d: any) => {
      setSystemStatus(d);
      setPauseReason(d.emergency_pause?.reason || "");
    }).catch(() => {});
  }, []);
  useEffect(() => { loadSystemStatus(); }, []);

  async function executePauseToggle() {
    if (!systemStatus) return;
    const enabling = !systemStatus.emergency_pause.enabled;
    setConfirmPause(false);
    setConfirmResume(false);
    setPauseLoading(true);
    try {
      await apiJson("/api/admin/emergency-pause", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: enabling,
          reason: enabling ? pauseReason : null,
          cancel_active: enabling && cancelActive,
        }),
      });
      loadSystemStatus();
      loadStats();
      if (!enabling) { setPauseReason(""); setCancelActive(false); }
    } catch (err: any) {
      alert("Failed: " + err.message);
    } finally {
      setPauseLoading(false);
    }
  }

  // ── Announcement ──
  const [annText, setAnnText] = useState("");
  const [annType, setAnnType] = useState<"info" | "warning" | "critical">("info");
  const [annLoading, setAnnLoading] = useState(false);
  const [currentAnn, setCurrentAnn] = useState<{ text: string | null; type: string } | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [confirmClearAnn, setConfirmClearAnn] = useState(false);

  useEffect(() => {
    fetch("/api/system/announcement")
      .then((r) => r.json())
      .then((d) => {
        setCurrentAnn(d.announcement);
        if (d.announcement?.text) {
          setAnnText(d.announcement.text);
          setAnnType(d.announcement.type);
        }
      })
      .catch(() => {});
  }, []);

  async function executeSetAnnouncement() {
    setConfirmPublish(false);
    setAnnLoading(true);
    try {
      await apiJson("/api/admin/announcement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: annText || null, type: annType }),
      });
      setCurrentAnn(annText ? { text: annText, type: annType } : null);
    } catch (err: any) {
      alert("Failed: " + err.message);
    } finally {
      setAnnLoading(false);
    }
  }

  async function executeClearAnnouncement() {
    setConfirmClearAnn(false);
    setAnnLoading(true);
    try {
      await apiJson("/api/admin/announcement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: null, type: "info" }),
      });
      setCurrentAnn(null);
      setAnnText("");
      setAnnType("info");
    } catch (err: any) {
      alert("Failed: " + err.message);
    } finally {
      setAnnLoading(false);
    }
  }

  // ── User Search ──
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [grantModal, setGrantModal] = useState<{ userId: string; email: string } | null>(null);
  const [grantDays, setGrantDays] = useState("30");
  const [grantReason, setGrantReason] = useState("");
  const [confirmRevoke, setConfirmRevoke] = useState<{ userId: string; email: string; tierSource: string } | null>(null);

  async function handleSearch() {
    if (search.length < 3) return;
    setSearching(true);
    try {
      const data = await apiJson(`/api/admin/search-user?email=${encodeURIComponent(search)}`) as any;
      setResults(data.users || []);
      setExpandedUserId(null);
    } catch (err: any) {
      alert("Search failed: " + err.message);
    } finally {
      setSearching(false);
    }
  }

  async function executeGrantPro(userId: string) {
    setGrantModal(null);
    setUpdatingId(userId);
    try {
      await apiJson("/api/admin/grant-pro", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          duration_days: parseInt(grantDays) || 30,
          reason: grantReason || undefined,
        }),
      });
      setResults((prev) =>
        prev.map((u) => (u.user_id === userId ? { ...u, tier: "pro", tier_source: "admin_grant" } : u))
      );
      setGrantDays("30");
      setGrantReason("");
    } catch (err: any) {
      alert("Failed to grant pro: " + err.message);
    } finally {
      setUpdatingId(null);
    }
  }

  async function executeRevoke(userId: string) {
    setConfirmRevoke(null);
    setUpdatingId(userId);
    try {
      const result = await apiJson("/api/admin/revoke-grant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, force: true }),
      }) as any;
      setResults((prev) =>
        prev.map((u) => (u.user_id === userId ? { ...u, tier: result.effective_tier || "free", tier_source: result.has_stripe_subscription ? "stripe" : "none" } : u))
      );
    } catch (err: any) {
      alert("Failed to revoke: " + err.message);
    } finally {
      setUpdatingId(null);
    }
  }

  // ── Audit Log ──
  const [auditLog, setAuditLog] = useState<AuditLogEntry[] | null>(null);
  const [auditFilter, setAuditFilter] = useState("");

  const loadAuditLog = useCallback(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (auditFilter) params.set("event", auditFilter);
    apiJson(`/api/admin/audit-log?${params}`).then((d: any) => setAuditLog(d.entries || [])).catch(() => {});
  }, [auditFilter]);

  const isPaused = systemStatus?.emergency_pause?.enabled;

  return (
    <section className="bg-bg-surface rounded-xl overflow-hidden border border-white/5">
      <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between bg-primary/5">
        <div>
          <h2 className="text-base font-bold text-primary">Admin Dashboard</h2>
          <p className="text-xs text-slate-500 mt-0.5">System controls, user management, and monitoring.</p>
        </div>
        <Icon name="admin_panel_settings" className="text-primary text-xl" />
      </div>

      {/* All confirm modals */}
      <ConfirmModal
        open={!!confirmRevoke}
        title="Revoke admin grant?"
        description={
          confirmRevoke?.tierSource === "stripe"
            ? `${confirmRevoke?.email} also has an active Stripe subscription. Revoking the admin grant won't affect their paid subscription.`
            : `This will revoke the admin grant for ${confirmRevoke?.email}. They will be downgraded to the Free plan.`
        }
        confirmLabel="Yes, Revoke Grant"
        danger
        onConfirm={() => confirmRevoke && executeRevoke(confirmRevoke.userId)}
        onCancel={() => setConfirmRevoke(null)}
      />

      {/* Grant Pro modal */}
      {grantModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-bg-elevated border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4">
            <h2 className="text-lg font-bold mb-1">Grant Pro Access</h2>
            <p className="text-sm text-slate-400 mb-4">{grantModal.email}</p>
            <label className="block text-xs text-slate-500 font-bold mb-1">Duration (days)</label>
            <input
              type="number"
              min="1"
              value={grantDays}
              onInput={(e) => setGrantDays((e.target as HTMLInputElement).value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:border-primary/50"
            />
            <label className="block text-xs text-slate-500 font-bold mb-1">Reason (optional)</label>
            <input
              type="text"
              value={grantReason}
              onInput={(e) => setGrantReason((e.target as HTMLInputElement).value)}
              placeholder="e.g. Beta tester, contest winner"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:border-primary/50"
            />
            <div className="flex gap-3">
              <button
                onClick={() => { setGrantModal(null); setGrantDays("30"); setGrantReason(""); }}
                className="flex-1 py-2.5 bg-white/5 text-slate-400 border border-white/10 rounded-xl font-medium hover:bg-white/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => executeGrantPro(grantModal.userId)}
                className="flex-1 py-2.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 text-emerald-400 font-bold rounded-xl transition-all"
              >
                Grant Pro
              </button>
            </div>
          </div>
        </div>
      )}
      <ConfirmModal
        open={confirmPublish}
        title="Publish announcement?"
        description={`This will show "${annText}" as a ${annType} banner to all users immediately.`}
        confirmLabel="Yes, Publish"
        onConfirm={executeSetAnnouncement}
        onCancel={() => setConfirmPublish(false)}
      />
      <ConfirmModal
        open={confirmClearAnn}
        title="Clear announcement?"
        description="This will remove the current announcement banner for all users."
        confirmLabel="Yes, Clear"
        onConfirm={executeClearAnnouncement}
        onCancel={() => setConfirmClearAnn(false)}
      />
      <ConfirmModal
        open={confirmPause}
        title="Pause the entire service?"
        description={`All agents will stop receiving new jobs immediately.${cancelActive ? " All in-progress jobs will also be canceled." : ""} Users will not be able to start new renders until you resume.${pauseReason ? ` Reason: "${pauseReason}"` : ""}`}
        confirmLabel="Yes, Pause Everything"
        danger
        onConfirm={executePauseToggle}
        onCancel={() => setConfirmPause(false)}
      />
      <ConfirmModal
        open={confirmResume}
        title="Resume service?"
        description="Agents will start picking up jobs again. Any queued jobs will begin processing."
        confirmLabel="Yes, Resume Service"
        onConfirm={executePauseToggle}
        onCancel={() => setConfirmResume(false)}
      />

      <div className="p-5 space-y-3">

        {/* ── 1. User Management (most common daily task) ── */}
        <AdminSection title="User Management" icon="group">
          <div className="flex gap-2">
            <input
              type="email"
              value={search}
              onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search user by email..."
              className="flex-1 px-3 py-2 bg-bg-base text-sm rounded-lg border border-white/10 focus:border-primary/50 focus:ring-1 focus:ring-primary/50 focus:outline-none placeholder-slate-600 transition-colors"
            />
            <button
              onClick={handleSearch}
              disabled={searching || search.length < 3}
              className="px-4 py-2 bg-primary/10 hover:bg-primary/20 text-primary text-sm font-bold rounded-lg border border-primary/20 transition-all disabled:opacity-40"
            >
              {searching ? "..." : "Search"}
            </button>
          </div>

          {results.length > 0 && (
            <div className="space-y-1">
              {results.map((user) => (
                <div key={user.user_id} className="rounded-lg border border-white/5 overflow-hidden">
                  <div
                    className="flex items-center justify-between p-3 bg-white/[0.02] cursor-pointer hover:bg-white/[0.04] transition-colors"
                    onClick={() => setExpandedUserId(expandedUserId === user.user_id ? null : user.user_id)}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon
                        name={expandedUserId === user.user_id ? "expand_less" : "expand_more"}
                        className="text-slate-500 text-sm shrink-0"
                      />
                      <div className="min-w-0">
                        <p className="text-sm font-semibold truncate">{user.email}</p>
                        <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold flex items-center gap-1.5 flex-wrap">
                          <span className={user.tier === "pro" ? "text-emerald-400" : "text-slate-400"}>{user.tier}</span>
                          {user.tier_source === "stripe" && (
                            <span className="text-[9px] font-bold text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded-full normal-case">Stripe</span>
                          )}
                          {user.tier_source === "admin_grant" && (
                            <span className="text-[9px] font-bold text-amber-400 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded-full normal-case">Granted</span>
                          )}
                          {user.created_at && (
                            <span className="ml-1 normal-case text-slate-600">
                              joined {new Date(user.created_at).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                    <Icon
                      name="chevron_right"
                      className={`text-slate-500 text-sm shrink-0 transition-transform ${expandedUserId === user.user_id ? "rotate-90" : ""}`}
                    />
                  </div>
                  {expandedUserId === user.user_id && (
                    <UserDetailPanel
                      userId={user.user_id}
                      email={user.email}
                      tier={user.tier}
                      tierSource={user.tier_source}
                      onGrantPro={(uid, em) => setGrantModal({ userId: uid, email: em })}
                      onRevoke={(uid, em, ts) => setConfirmRevoke({ userId: uid, email: em, tierSource: ts })}
                      updatingId={updatingId}
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          {results.length === 0 && search.length >= 3 && !searching && (
            <p className="text-center py-4 text-xs text-slate-500 italic">No users found matching your search.</p>
          )}
        </AdminSection>

        {/* ── 2. Service Health (read-only overview) ── */}
        <AdminSection title="Service Health" icon="monitoring">
          {stats ? (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              <StatCard label="Users" value={stats.total_users} />
              <StatCard label="Online" value={stats.online_agents} color="text-emerald-400" />
              <StatCard label="Offline" value={stats.offline_agents} color={stats.offline_agents > 0 ? "text-slate-400" : undefined} />
              <StatCard label="Active Jobs" value={stats.active_jobs} color="text-primary" />
              <StatCard label="Queued" value={stats.queued_jobs} />
              <StatCard label="Done (24h)" value={stats.completed_24h} color="text-emerald-400" />
              <StatCard label="Failed (24h)" value={stats.failed_24h} color={stats.failed_24h > 0 ? "text-red-400" : undefined} />
            </div>
          ) : (
            <p className="text-xs text-slate-500">Loading stats...</p>
          )}
          <button
            onClick={loadStats}
            className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1"
          >
            <Icon name="refresh" className="text-xs" /> Refresh
          </button>
        </AdminSection>

        {/* ── 3. Announcement ── */}
        <AdminSection title="System Announcement" icon="campaign">
          {currentAnn?.text && (
            <div className={`px-3 py-2 rounded-lg border text-xs ${
              currentAnn.type === "critical" ? "bg-red-500/10 border-red-500/20 text-red-300"
                : currentAnn.type === "warning" ? "bg-amber-500/10 border-amber-500/20 text-amber-300"
                  : "bg-blue-500/10 border-blue-500/20 text-blue-300"
            }`}>
              Currently live: {currentAnn.text}
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={annText}
              onInput={(e) => setAnnText((e.target as HTMLInputElement).value)}
              placeholder="Announcement message..."
              className="flex-1 px-3 py-2 bg-bg-base text-sm rounded-lg border border-white/10 focus:border-primary/50 focus:ring-1 focus:ring-primary/50 focus:outline-none placeholder-slate-600 transition-colors"
            />
            <select
              value={annType}
              onChange={(e) => setAnnType((e.target as HTMLSelectElement).value as any)}
              className="px-2 py-2 bg-bg-base text-sm rounded-lg border border-white/10 text-slate-300"
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setConfirmPublish(true)}
              disabled={annLoading || !annText}
              className="px-4 py-2 bg-primary/10 hover:bg-primary/20 text-primary text-sm font-bold rounded-lg border border-primary/20 transition-all disabled:opacity-40"
            >
              {annLoading ? "..." : "Publish"}
            </button>
            {currentAnn?.text && (
              <button
                onClick={() => setConfirmClearAnn(true)}
                disabled={annLoading}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-slate-400 text-sm font-bold rounded-lg border border-white/10 transition-all disabled:opacity-40"
              >
                Clear
              </button>
            )}
          </div>
        </AdminSection>

        {/* ── 4. Audit Log ── */}
        <AuditLogSection loadAuditLog={loadAuditLog} auditLog={auditLog} auditFilter={auditFilter} setAuditFilter={setAuditFilter} />

        {/* ── 5. Emergency Pause (most dangerous, at the bottom) ── */}
        <AdminSection
          title="Emergency Pause"
          icon="emergency"
          badge={isPaused ? "ACTIVE" : undefined}
        >
          <div className={`rounded-lg p-3 space-y-3 ${isPaused ? "bg-red-500/5 border border-red-500/20" : ""}`}>
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-400">
                {isPaused
                  ? "Service is paused. No agents are receiving jobs."
                  : "Stop all job dispatch globally. Use during critical incidents."}
              </p>
              <button
                onClick={() => isPaused ? setConfirmResume(true) : setConfirmPause(true)}
                disabled={pauseLoading}
                className={`px-4 py-2 text-sm font-bold rounded-lg border transition-all disabled:opacity-40 shrink-0 ml-4 ${
                  isPaused
                    ? "bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border-emerald-500/20"
                    : "bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20"
                }`}
              >
                {pauseLoading ? "..." : isPaused ? "Resume Service" : "Pause Service"}
              </button>
            </div>
            {!isPaused && (
              <>
                <input
                  type="text"
                  value={pauseReason}
                  onInput={(e) => setPauseReason((e.target as HTMLInputElement).value)}
                  placeholder="Reason (optional)..."
                  className="w-full px-3 py-2 bg-bg-base text-sm rounded-lg border border-white/10 focus:border-red-500/50 focus:ring-1 focus:ring-red-500/50 focus:outline-none placeholder-slate-600 transition-colors"
                />
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={cancelActive}
                    onChange={() => setCancelActive(!cancelActive)}
                    className="size-4 rounded border-white/20 bg-bg-base accent-red-500 cursor-pointer"
                  />
                  <span className="text-xs text-slate-400">Also cancel all in-progress jobs</span>
                </label>
              </>
            )}
            {isPaused && systemStatus?.emergency_pause?.reason && (
              <p className="text-xs text-red-300/70">
                Reason: {systemStatus.emergency_pause.reason}
              </p>
            )}
          </div>
        </AdminSection>

      </div>
    </section>
  );
}

export function SettingsPage() {
  const { agents, loading: agentsLoading } = useAgents();
  const { session } = useSession();
  const { profile, loading: profileLoading, refreshProfile, createCheckoutSession, openCustomerPortal, setActiveAgent } = useProfile();

  const { apiJson } = useApi();

  // Allow local removal of agents after delete without waiting for Realtime to update
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [upgrading, setUpgrading] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [isGrantModal, setIsGrantModal] = useState(false);
  const [showPlanPopup, setShowPlanPopup] = useState(false);

  // Handle return from Stripe Checkout
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") {
      setShowSuccessModal(true);
      setUpgrading(false);
      // Clean URL
      window.history.replaceState({}, "", window.location.pathname);
      // Refresh once — the /api/profile safety net syncs from Stripe if the webhook hasn't arrived yet
      refreshProfile();
    }
  }, []);

  // Handle ?upgrade=true from landing page — auto-trigger Stripe checkout
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("upgrade") === "true" && profile && profile.tier !== "pro" && !upgrading) {
      window.history.replaceState({}, "", window.location.pathname);
      handleUpgrade();
    }
  }, [profile]);

  // Show success modal once per admin grant (keyed on grant_until timestamp)
  useEffect(() => {
    if (
      profile?.tier === "pro" &&
      profile?.tier_source === "admin_grant" &&
      profile?.grant_until
    ) {
      const key = `grant_popup_shown_${profile.grant_until}`;
      if (!localStorage.getItem(key)) {
        localStorage.setItem(key, "1");
        setIsGrantModal(true);
        setShowSuccessModal(true);
      }
    }
  }, [profile?.tier_source, profile?.grant_until]);

  // Refresh profile when returning from Stripe Portal (or any tab switch)
  useEffect(() => {
    const onFocus = () => refreshProfile();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const displayAgents = agents.filter((a) => !deletedIds.has(a.agent_id));

  // Auto-select the first agent whenever agents exist but none is active
  const activeAgentId = profile?.active_agent_id ?? null;
  if (displayAgents.length > 0 && !activeAgentId && profile) {
    setActiveAgent(displayAgents[0].agent_id).catch(() => { });
  }

  function handleAgentDeleted(id: string) {
    setDeletedIds((prev) => {
      const next = new Set([...prev, id]);
      // If the deleted agent was the active one, pick another
      if (id === activeAgentId) {
        const remaining = agents.filter((a) => !next.has(a.agent_id));
        if (remaining.length > 0) {
          setActiveAgent(remaining[0].agent_id).catch(() => { });
        }
      }
      return next;
    });
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
  }

  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);

  async function handleDeleteAccount() {
    if (deleteConfirmText !== "DELETE") return;
    setDeletingAccount(true);
    try {
      await apiJson("/api/account", { method: "DELETE" });
      await supabase.auth.signOut();
    } catch (err: any) {
      alert(`Failed to delete account: ${err.message}`);
      setDeletingAccount(false);
    }
  }

  async function handleUpgrade() {
    setUpgrading(true);
    try {
      await createCheckoutSession();
    } catch (err) {
      console.error("Failed to start checkout:", err);
      alert("Failed to start checkout. Please try again.");
      setUpgrading(false);
    }
  }

  const email = session?.user?.email ?? "";

  return (
    <div className="flex flex-col min-h-screen bg-bg-base">
      {/* Gradient top */}
      <div className="fixed top-0 left-0 w-full h-48 bg-gradient-to-b from-primary/8 to-transparent pointer-events-none -z-10" />

      {/* Page header */}
      <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 py-4">
        <h1 className="text-xl font-bold tracking-tight">Settings</h1>
      </header>

      <main className="flex-1 px-6 py-6 pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-8 max-w-3xl mx-auto w-full space-y-5">

        {/* ── Upgrade Success Modal ── */}
        {showSuccessModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="bg-bg-surface border border-white/10 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
              <div className="px-6 pt-8 pb-5 text-center">
                <div className="size-16 rounded-full bg-emerald-500/10 border-2 border-emerald-500/20 flex items-center justify-center mx-auto mb-4">
                  <Icon name="check" className="text-emerald-400 text-3xl" />
                </div>
                <h2 className="text-xl font-bold">Welcome to Pro!</h2>
                <p className="text-sm text-slate-400 mt-1">
                  {isGrantModal
                    ? "You've been granted Pro access. Here's what you've unlocked:"
                    : "Your subscription is active. Here's what you've unlocked:"}
                </p>
              </div>
              <div className="px-6 pb-4 space-y-2.5">
                {[
                  { icon: "devices", label: "Up to 3 computers", desc: "Render on multiple workstations" },
                  { icon: "queue", label: "Job queue", desc: "Queue up to 8 jobs per computer" },
                  { icon: "browse_gallery", label: "Frame browser & EXR passes", desc: "Browse frames and select render passes" },
                  { icon: "movie", label: "Animation preview", desc: "Compile MP4 previews from rendered frames" },
                ].map((f) => (
                  <div key={f.icon} className="flex items-center gap-3 p-3 bg-emerald-500/5 rounded-xl border border-emerald-500/10">
                    <Icon name={f.icon} className="text-emerald-400 text-lg shrink-0" />
                    <div>
                      <p className="text-sm font-semibold text-slate-200">{f.label}</p>
                      <p className="text-[11px] text-slate-500">{f.desc}</p>
                    </div>
                    <Icon name="check_circle" className="text-emerald-500 text-sm ml-auto shrink-0" />
                  </div>
                ))}
              </div>
              <div className="px-6 pb-6 pt-2">
                <button
                  onClick={() => { setShowSuccessModal(false); setIsGrantModal(false); }}
                  className="w-full py-3 gradient-primary hover:opacity-90 text-white font-bold rounded-xl shadow-lg shadow-black/20 transition-all active:scale-[0.98]"
                >
                  Get Started
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Subscription ── */}
        <section className="bg-bg-surface rounded-xl p-6 border border-white/5">
          <div className="flex items-center justify-between mb-5">
            <div>
              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Subscription</p>
              <p className="text-2xl font-bold mt-1">
                {profileLoading ? "Loading..." : profile?.tier === "pro" ? "Pro Plan" : "Free Plan"}
                {profile?.tier === "pro" && profile?.tier_source === "admin_grant" && (
                  <span className="ml-2 text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full align-middle">
                    Granted
                  </span>
                )}
              </p>
            </div>
          </div>
          <div className="space-y-4">
            {/* ── Active Stripe subscriber ── */}
            {profile?.tier === "pro" && profile?.tier_source === "stripe" ? (
              <>
                <div className="flex items-center gap-3 px-4 py-3 bg-emerald-500/5 rounded-xl border border-emerald-500/10">
                  <Icon name="check_circle" className="text-emerald-400 text-xl shrink-0" />
                  <span className="text-sm font-medium text-emerald-400">Your Pro plan is active</span>
                </div>

                {/* Subscription status */}
                {profile.cancel_at_period_end ? (
                  <>
                    <div className="flex items-start gap-3 p-4 bg-amber-500/5 rounded-xl border border-amber-500/20">
                      <Icon name="event_busy" className="text-amber-400 text-xl shrink-0 mt-0.5" />
                      <div className="text-sm text-slate-400 leading-relaxed">
                        <p className="font-semibold text-amber-400">Subscription canceled</p>
                        <p className="mt-1">
                          You'll keep Pro access until{" "}
                          <span className="font-bold text-slate-300">
                            {profile.current_period_end
                              ? new Date(profile.current_period_end).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
                              : "-"}
                          </span>
                          . After that, you'll be on the Free plan.
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={openCustomerPortal}
                      className="w-full py-3 gradient-primary hover:opacity-90 text-white font-bold rounded-xl shadow-lg shadow-black/20 transition-all flex items-center justify-center gap-2 active:scale-[0.98]"
                    >
                      <Icon name="refresh" className="text-xl" />
                      Resubscribe
                    </button>
                  </>
                ) : (
                  <>
                    <div className="flex items-center justify-between px-4 py-3 bg-white/[0.02] rounded-xl border border-white/5">
                      <div className="flex items-center gap-2">
                        <Icon name="event_repeat" className="text-slate-500 text-base" />
                        <span className="text-xs text-slate-500">Next renewal</span>
                      </div>
                      <span className="text-xs font-semibold text-slate-300">
                        {profile.current_period_end
                          ? new Date(profile.current_period_end).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
                          : "-"}
                      </span>
                    </div>
                    <button
                      onClick={openCustomerPortal}
                      className="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 font-medium rounded-xl transition-all flex items-center justify-center gap-2 active:scale-[0.98] text-sm"
                    >
                      <Icon name="settings" className="text-base" />
                      Manage Subscription
                    </button>
                  </>
                )}
              </>

            /* ── Admin-granted Pro ── */
            ) : profile?.tier === "pro" && profile?.tier_source === "admin_grant" ? (
              <>
                <div className="flex items-start gap-3 p-4 bg-emerald-500/5 rounded-xl border border-emerald-500/10">
                  <Icon name="card_giftcard" className="text-emerald-400 text-xl shrink-0 mt-0.5" />
                  <div className="text-sm text-slate-400 leading-relaxed">
                    <p>
                      You have been granted <span className="font-bold text-emerald-400">Pro</span> access. All Pro features are available.
                    </p>
                    {profile.grant_until && (() => {
                      const remaining = Math.max(0, Math.ceil((new Date(profile.grant_until).getTime() - Date.now()) / (1000 * 60 * 60 * 24)));
                      return (
                        <p className="mt-2 text-slate-500">
                          <span className={`font-semibold ${remaining <= 3 ? "text-amber-400" : "text-slate-400"}`}>
                            {remaining} {remaining === 1 ? "day" : "days"}
                          </span>
                          {" "}remaining - expires{" "}
                          <span className="text-slate-400">
                            {new Date(profile.grant_until).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
                          </span>
                        </p>
                      );
                    })()}
                  </div>
                </div>
                <button
                  onClick={handleUpgrade}
                  disabled={upgrading}
                  className="w-full py-3 gradient-primary hover:opacity-90 text-white font-bold rounded-xl shadow-lg shadow-black/20 transition-all flex items-center justify-center gap-2 active:scale-[0.98] disabled:opacity-60 text-sm"
                >
                  <Icon name="lock_open" className="text-lg" />
                  {upgrading ? "Redirecting to checkout..." : "Subscribe to keep Pro"}
                </button>
              </>

            /* ── Free plan with comparison ── */
            ) : (
              <>
                {/* Plan comparison */}
                <div
                  className="grid grid-cols-2 gap-3 md:cursor-default cursor-pointer"
                  onClick={() => { if (window.innerWidth < 768) setShowPlanPopup(true); }}
                >
                  {/* Free column */}
                  <div className="rounded-xl border border-white/10 p-4 md:pb-4 pb-0 bg-white/[0.02] relative md:max-h-none max-h-[225px] overflow-hidden">
                    <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Free</p>
                    <p className="text-lg font-bold mt-1 text-slate-300">€0<span className="text-xs font-normal text-slate-500">/mo</span></p>
                    <div className="mt-3 space-y-2">
                      {[
                        { label: "1 computer", included: true },
                        { label: "1 job at a time", included: true },
                        { label: "Live preview", included: true },
                        { label: "Basic render settings", included: true },
                        { label: "Last 10 jobs in history", included: true },
                        { label: "Animation preview", included: false },
                        { label: "Frame browser & EXR passes", included: false },
                        { label: "Advanced render settings", included: false },
                        { label: "VRAM recovery", included: false },
                      ].map((f) => (
                        <div key={f.label} className="flex items-center gap-2">
                          <Icon
                            name={f.included ? "check" : "close"}
                            className={`text-xs ${f.included ? "text-slate-400" : "text-slate-600"}`}
                          />
                          <span className={`text-[11px] ${f.included ? "text-slate-400" : "text-slate-600"}`}>{f.label}</span>
                        </div>
                      ))}
                    </div>
                    <div className="md:hidden absolute bottom-0 left-0 right-0 h-20 rounded-b-xl bg-gradient-to-t from-[#141324] from-10% via-[#141324]/90 via-40% to-transparent pointer-events-none" />
                  </div>

                  {/* Pro column */}
                  <div className="relative">
                    <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2.5 py-0.5 bg-primary text-white text-[9px] font-bold rounded-full uppercase tracking-wider z-[1]">
                      Recommended
                    </div>
                    <div className="rounded-xl border border-primary/30 p-4 md:pb-4 pb-0 bg-primary/5 relative md:max-h-none max-h-[225px] overflow-hidden">
                      <p className="text-xs font-bold text-primary uppercase tracking-widest">Pro</p>
                      <p className="text-lg font-bold mt-1 text-slate-200">€9<span className="text-xs font-normal text-slate-500">/mo</span></p>
                      <div className="mt-3 space-y-2">
                        {[
                          { label: "Up to 3 computers" },
                          { label: "8 jobs queued per computer" },
                          { label: "Live preview" },
                          { label: "Basic render settings" },
                          { label: "Unlimited job history" },
                          { label: "Animation preview" },
                          { label: "Frame browser & EXR passes" },
                          { label: "Advanced render settings" },
                          { label: "VRAM recovery" },
                        ].map((f) => (
                          <div key={f.label} className="flex items-center gap-2">
                            <Icon name="check" className="text-xs text-primary" />
                            <span className="text-[11px] text-slate-300">{f.label}</span>
                          </div>
                        ))}
                      </div>
                      <div className="md:hidden absolute bottom-0 left-0 right-0 h-20 rounded-b-xl bg-gradient-to-t from-[#161428] from-10% via-[#161428]/90 via-40% to-transparent pointer-events-none" />
                    </div>
                  </div>
                </div>

                {/* Mobile expand hint */}
                <div
                  className="md:hidden flex items-center justify-center gap-1.5 -mt-1 py-1 text-slate-500 cursor-pointer"
                  onClick={() => setShowPlanPopup(true)}
                >
                  <span className="text-[10px]">See all features</span>
                  <Icon name="expand_more" className="text-sm" />
                </div>

                <button
                  onClick={handleUpgrade}
                  disabled={upgrading}
                  className="w-full py-3.5 gradient-primary hover:opacity-90 text-white font-bold rounded-xl shadow-lg shadow-black/20 transition-all flex items-center justify-center gap-2 active:scale-[0.98] disabled:opacity-60"
                >
                  <Icon name="lock_open" className="text-xl" />
                  {upgrading ? "Redirecting to checkout..." : "Unlock Pro"}
                </button>

                {/* Mobile plan comparison popup */}
                {showPlanPopup && (
                  <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={() => setShowPlanPopup(false)}>
                    <div className="bg-bg-surface border border-white/10 rounded-2xl shadow-2xl w-full max-w-lg overflow-y-auto max-h-[85vh]" onClick={(e) => e.stopPropagation()}>
                      {/* Header with close button */}
                      <div className="sticky top-0 bg-bg-surface/95 backdrop-blur-sm px-5 pt-4 pb-3 flex items-center justify-between border-b border-white/5 z-10 rounded-t-2xl">
                        <h3 className="text-base font-bold">Compare Plans</h3>
                        <button onClick={() => setShowPlanPopup(false)} className="size-8 flex items-center justify-center rounded-full bg-white/5 hover:bg-white/10 transition-colors">
                          <Icon name="close" className="text-lg text-slate-400" />
                        </button>
                      </div>

                      <div className="p-4 space-y-4">
                        {/* Full comparison grid */}
                        <div className="grid grid-cols-2 gap-3">
                          {/* Free column */}
                          <div className="rounded-xl border border-white/10 p-4 bg-white/[0.02]">
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Free</p>
                            <p className="text-lg font-bold mt-1 text-slate-300">€0<span className="text-xs font-normal text-slate-500">/mo</span></p>
                            <div className="mt-3 space-y-2">
                              {[
                                { label: "1 computer", included: true },
                                { label: "1 job at a time", included: true },
                                { label: "Live preview", included: true },
                                { label: "Basic render settings", included: true },
                                { label: "Last 10 jobs in history", included: true },
                                { label: "Animation preview", included: false },
                                { label: "Frame browser & EXR passes", included: false },
                                { label: "Advanced render settings", included: false },
                                { label: "VRAM recovery", included: false },
                              ].map((f) => (
                                <div key={f.label} className="flex items-center gap-2">
                                  <Icon
                                    name={f.included ? "check" : "close"}
                                    className={`text-xs ${f.included ? "text-slate-400" : "text-slate-600"}`}
                                  />
                                  <span className={`text-[11px] ${f.included ? "text-slate-400" : "text-slate-600"}`}>{f.label}</span>
                                </div>
                              ))}
                            </div>
                          </div>

                          {/* Pro column */}
                          <div className="rounded-xl border border-primary/30 p-4 bg-primary/5 relative">
                            <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2.5 py-0.5 bg-primary text-white text-[9px] font-bold rounded-full uppercase tracking-wider">
                              Recommended
                            </div>
                            <p className="text-xs font-bold text-primary uppercase tracking-widest">Pro</p>
                            <p className="text-lg font-bold mt-1 text-slate-200">€9<span className="text-xs font-normal text-slate-500">/mo</span></p>
                            <div className="mt-3 space-y-2">
                              {[
                                { label: "Up to 3 computers" },
                                { label: "8 jobs queued per computer" },
                                { label: "Live preview" },
                                { label: "Basic render settings" },
                                { label: "Unlimited job history" },
                                { label: "Animation preview" },
                                { label: "Frame browser & EXR passes" },
                                { label: "Advanced render settings" },
                                { label: "VRAM recovery" },
                              ].map((f) => (
                                <div key={f.label} className="flex items-center gap-2">
                                  <Icon name="check" className="text-xs text-primary" />
                                  <span className="text-[11px] text-slate-300">{f.label}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>

                        <button
                          onClick={handleUpgrade}
                          disabled={upgrading}
                          className="w-full py-3.5 gradient-primary hover:opacity-90 text-white font-bold rounded-xl shadow-lg shadow-black/20 transition-all flex items-center justify-center gap-2 active:scale-[0.98] disabled:opacity-60"
                        >
                          <Icon name="lock_open" className="text-xl" />
                          {upgrading ? "Redirecting to checkout..." : "Unlock Pro"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* ── Connected Agents ── */}
        <section className="bg-bg-surface rounded-xl overflow-hidden border border-white/5">
          <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold">Your Computers</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {displayAgents.length > 1
                  ? "Workstations registered to your account. Click the circle to set the active workstation."
                  : "Workstations registered to your account."}
              </p>
            </div>
            <Icon name="devices" className="text-slate-500 text-xl" />
          </div>

          {agentsLoading && displayAgents.length === 0 ? (
            <div className="text-center py-12 text-slate-400">Loading computers...</div>
          ) : displayAgents.length === 0 ? (
            <div className="text-center py-12 text-slate-500 bg-bg-base/50 rounded-lg border border-white/5 border-dashed">
              No computers connected. Install the app on your workstation to get started.
            </div>
          ) : (
            <div>
              {displayAgents.map((agent) => (
                <AgentRow
                  key={agent.agent_id}
                  agent={agent}
                  onDelete={handleAgentDeleted}
                  isActive={agent.agent_id === activeAgentId}
                  onSetActive={(id) => setActiveAgent(id)}
                  showSelector={displayAgents.length > 1}
                />
              ))}
            </div>
          )}

          <div className="px-5 py-3 bg-bg-base/40 border-t border-white/5">
            <Link
              href="/download"
              className="text-xs font-bold text-primary flex items-center gap-1 w-fit hover:opacity-80 transition-opacity"
            >
              <Icon name="add" className="text-sm" />
              Add another computer
            </Link>
          </div>
        </section>

        {/* ── Notifications ── */}
        <NotificationsSection email={email} profile={profile} />

        {/* ── VRAM Recovery ── */}
        <VRAMRecoverySection profile={profile} />

        {/* ── Account ── */}
        <section className="bg-bg-surface rounded-xl p-5 border border-white/5">
          <h2 className="text-base font-bold mb-4">Account</h2>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 min-w-0">
              <div className="size-10 rounded-lg bg-bg-base flex items-center justify-center shrink-0">
                <Icon name="alternate_email" className="text-slate-500" />
              </div>
              <p className="text-sm font-medium truncate">{email || "-"}</p>
            </div>
            <button
              onClick={handleSignOut}
              className="shrink-0 px-4 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-bold transition-colors"
            >
              Sign Out
            </button>
          </div>
        </section>

        {/* ── Delete Account ── */}
        <section className="bg-bg-surface rounded-xl p-5 border border-red-500/20">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-red-400">Delete Account</h2>
              <p className="text-xs text-slate-500 mt-1">Permanently delete your account and all associated data.</p>
            </div>
            {!showDeleteAccount && (
              <button
                onClick={() => setShowDeleteAccount(true)}
                className="shrink-0 text-xs text-red-400/60 hover:text-red-400 transition-colors underline underline-offset-2"
              >
                Delete Account
              </button>
            )}
          </div>
          {showDeleteAccount && (
            <div className="mt-4 p-4 bg-red-500/5 rounded-lg border border-red-500/20 space-y-3">
              <p className="text-sm text-slate-300">
                This will permanently delete your account, all job history, agent connections, and render data. This action cannot be undone.
              </p>
              <div>
                <label className="text-xs text-slate-400 block mb-1">Type <span className="font-mono font-bold text-red-400">DELETE</span> to confirm</label>
                <input
                  type="text"
                  value={deleteConfirmText}
                  onInput={(e) => setDeleteConfirmText((e.target as HTMLInputElement).value)}
                  className="w-full bg-bg-base border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-red-500/50"
                  placeholder="DELETE"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={handleDeleteAccount}
                  disabled={deleteConfirmText !== "DELETE" || deletingAccount}
                  className="px-4 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {deletingAccount ? "Deleting..." : "Permanently Delete Account"}
                </button>
                <button
                  onClick={() => { setShowDeleteAccount(false); setDeleteConfirmText(""); }}
                  className="px-4 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm font-bold transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>

        {/* ── Need Help? ── */}
        <div className="flex items-center justify-center gap-2 py-2 text-xs text-slate-500">
          <Icon name="mail" className="text-sm" />
          <span>Need help?</span>
          <a href="mailto:support@rendermanager.com" className="text-primary hover:text-primary/80 font-medium transition-colors">
            support@rendermanager.com
          </a>
        </div>

        {/* ── Admin Dashboard ── */}
        {profile?.is_admin && <AdminDashboard />}
      </main>

    </div>
  );
}
