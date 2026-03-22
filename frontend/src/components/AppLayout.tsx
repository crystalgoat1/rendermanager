import type { ComponentChildren } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import { BottomNav } from "./BottomNav";
import { useAgents } from "../hooks/useAgent";
import { usePresence } from "../hooks/usePresence";
import { useProfile } from "../hooks/useProfile";
import type { SystemAnnouncement } from "../types";

function AnnouncementBanner() {
  const [announcement, setAnnouncement] = useState<SystemAnnouncement | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    function fetchAnnouncement() {
      fetch("/api/system/announcement")
        .then((r) => r.json())
        .then((data) => setAnnouncement(data.announcement || null))
        .catch(() => {});
    }
    fetchAnnouncement();
    intervalRef.current = setInterval(fetchAnnouncement, 60_000);
    return () => clearInterval(intervalRef.current);
  }, []);

  // Reset dismissed state when announcement text changes
  const prevText = useRef(announcement?.text);
  useEffect(() => {
    if (announcement?.text !== prevText.current) {
      setDismissed(false);
      prevText.current = announcement?.text;
    }
  }, [announcement?.text]);

  if (!announcement?.text || dismissed) return null;

  const colors = {
    info: "bg-blue-500/10 border-blue-500/20 text-blue-300",
    warning: "bg-amber-500/10 border-amber-500/20 text-amber-300",
    critical: "bg-red-500/10 border-red-500/20 text-red-300",
  };
  const icons = { info: "info", warning: "warning", critical: "error" };

  return (
    <div className={`px-4 py-2.5 border-b flex items-center gap-3 ${colors[announcement.type]}`}>
      <Icon name={icons[announcement.type]} className="text-lg shrink-0" />
      <p className="text-sm flex-1">{announcement.text}</p>
      <button
        onClick={() => setDismissed(true)}
        className="shrink-0 p-1 rounded hover:bg-white/10 transition-colors"
      >
        <Icon name="close" className="text-sm" />
      </button>
    </div>
  );
}

const NAV_MAIN = [
  { href: "/dashboard", icon: "dashboard", label: "Dashboard" },
  { href: "/new", icon: "add_circle", label: "New Render" },
  { href: "/history", icon: "history", label: "History" },
  { href: "/download", icon: "download", label: "Download App" },
] as const;

export function AppLayout({ children }: { children: ComponentChildren }) {
  const [location] = useLocation();
  const { agents } = useAgents();
  const { profile, setActiveAgent } = useProfile();
  usePresence();

  // Find the *selected* workstation from profile, not just any online one
  const activeAgentId = profile?.active_agent_id;
  const selectedAgent = activeAgentId
    ? agents.find((a) => a.agent_id === activeAgentId)
    : null;

  const onlineAgents = agents.filter((a) => a.status !== "offline");
  const selectedIsOffline = selectedAgent ? selectedAgent.status === "offline" : true;

  // If selected is offline, find the best online alternative to suggest
  const onlineAlternative = selectedIsOffline
    ? onlineAgents.find((a) => a.agent_id !== activeAgentId)
    : null;

  return (
    <div className="flex min-h-screen bg-bg-base">
      {/* ── Desktop sidebar ── */}
      <aside className="hidden md:flex flex-col w-56 shrink-0 border-r border-white/5 bg-bg-base fixed left-0 top-0 bottom-0 z-30">
        {/* Logo */}
        <div className="px-5 py-4">
          <Logo size="lg" />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 space-y-0.5">
          {NAV_MAIN.map(({ href, icon, label }) => {
            const active = location === href || location.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${active
                  ? "bg-primary/10 text-primary"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                  }`}
              >
                <Icon name={icon} fill={active} className="text-[20px] shrink-0" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Workstation status chip */}
        <div className="mx-3 mb-3 space-y-2">
          <div className="group relative">
            <div className="px-3 py-2.5 bg-bg-base/60 rounded-lg border border-white/5 cursor-pointer hover:bg-white/5 transition-colors">
              {selectedAgent ? (
                <div className="flex items-center gap-2.5 min-w-0">
                  {/* Status Dot */}
                  <div className="relative flex size-2 shrink-0">
                    {(() => {
                      const sys = selectedAgent.system_info;
                      const isDanger = sys && (
                         sys.disk_free_mb < 5000 || // Less than 5GB disk
                         (sys.gpus && sys.gpus.some(g => g.vram_percent > 95)) // >95% VRAM
                      );
                      
                      if (selectedAgent.status === "busy") {
                        if (isDanger) return (
                          <>
                            <span className="animate-ping absolute inline-flex size-full rounded-full bg-amber-500 opacity-60" />
                            <span className="relative inline-flex rounded-full size-2 bg-amber-500" />
                          </>
                        );
                        return (
                          <>
                            <span className="animate-ping absolute inline-flex size-full rounded-full bg-primary opacity-60" />
                            <span className="relative inline-flex rounded-full size-2 bg-primary" />
                          </>
                        );
                      }
                      if (selectedAgent.status === "offline") return <span className="relative inline-flex rounded-full size-2 bg-slate-600" />;
                      if (isDanger) return <span className="relative inline-flex rounded-full size-2 bg-amber-500" />;
                      return <span className="relative inline-flex rounded-full size-2 bg-emerald-400" />;
                    })()}
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold truncate text-slate-200 leading-tight">
                      {selectedAgent.name}
                    </p>
                    <p className={`text-[10px] leading-tight flex items-center gap-1 ${selectedAgent.status === "offline" ? "text-amber-400" : "text-slate-500"}`}>
                      {selectedAgent.status === "busy"
                        ? "Rendering..."
                        : selectedAgent.status === "offline"
                          ? "Offline"
                          : "Online"}
                    </p>
                  </div>
                  {/* Chevron to indicate it's clickable */}
                  <Icon name="expand_more" className="text-slate-500 text-sm opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
              ) : agents.length > 0 ? (
                <div className="flex items-center gap-2.5">
                  <span className="size-2 rounded-full bg-slate-600 shrink-0" />
                  <p className="text-xs text-slate-500">No workstation selected</p>
                </div>
              ) : (
                <div className="flex items-center gap-2.5">
                  <span className="size-2 rounded-full bg-slate-600 shrink-0" />
                  <p className="text-xs text-slate-500">No workstation connected</p>
                </div>
              )}
            </div>

            {/* Telemetry Popover (Hover/Click) */}
            {selectedAgent && selectedAgent.status !== "offline" && selectedAgent.system_info && (
              <div className="absolute left-full bottom-0 ml-2 w-64 bg-bg-surface border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50 overflow-hidden pointer-events-none group-hover:pointer-events-auto">
                <div className="px-4 py-3 border-b border-white/5 bg-white/[0.02]">
                  <p className="text-xs font-bold text-slate-200">System Health</p>
                  <p className="text-[10px] text-slate-500">Live hardware telemetry</p>
                </div>
                <div className="p-4 space-y-4">
                  {/* CPU */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px] font-semibold">
                      <span className="text-slate-400">CPU</span>
                      <span className={selectedAgent.system_info.cpu_percent > 90 ? "text-amber-400" : "text-slate-300"}>{selectedAgent.system_info.cpu_percent}%</span>
                    </div>
                    <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${selectedAgent.system_info.cpu_percent > 90 ? "bg-amber-500" : "bg-primary"}`} style={{ width: `${selectedAgent.system_info.cpu_percent}%` }} />
                    </div>
                  </div>

                  {/* RAM */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px] font-semibold">
                      <span className="text-slate-400">RAM</span>
                      <span className={selectedAgent.system_info.ram_percent > 90 ? "text-amber-400" : "text-slate-300"}>{selectedAgent.system_info.ram_used_mb}MB / {selectedAgent.system_info.ram_total_mb}MB</span>
                    </div>
                    <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${selectedAgent.system_info.ram_percent > 90 ? "bg-amber-500" : "bg-emerald-400"}`} style={{ width: `${selectedAgent.system_info.ram_percent}%` }} />
                    </div>
                  </div>

                  {/* GPUs */}
                  {selectedAgent.system_info.gpus && selectedAgent.system_info.gpus.length > 0 && selectedAgent.system_info.gpus.map((gpu) => (
                    <div key={gpu.id} className="space-y-2 pt-2 border-t border-white/5">
                      <div className="flex justify-between items-center text-[10px] font-semibold">
                        <span className="text-slate-300 truncate pr-2" title={gpu.name}>{gpu.name}</span>
                        <span className={gpu.temperature_c > 82 ? "text-red-400" : "text-slate-400"}>{gpu.temperature_c}°C</span>
                      </div>
                      
                      <div className="space-y-1">
                        <div className="flex justify-between text-[9px] text-slate-500">
                          <span>3D Load</span>
                          <span className={gpu.load_percent > 95 ? "text-primary" : ""}>{gpu.load_percent}%</span>
                        </div>
                        <div className="h-1 w-full bg-black/40 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full bg-primary`} style={{ width: `${gpu.load_percent}%` }} />
                        </div>
                      </div>

                      <div className="space-y-1">
                        <div className="flex justify-between text-[9px] text-slate-500">
                          <span>VRAM</span>
                          <span className={gpu.vram_percent > 95 ? "text-amber-400 font-semibold" : ""}>{Math.round(gpu.vram_used_mb/1024)}GB / {Math.round(gpu.vram_total_mb/1024)}GB</span>
                        </div>
                        <div className="h-1 w-full bg-black/40 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${gpu.vram_percent > 95 ? "bg-amber-500" : "bg-indigo-400"}`} style={{ width: `${gpu.vram_percent}%` }} />
                        </div>
                      </div>
                    </div>
                  ))}

                  {/* Disk Space */}
                  <div className="space-y-1.5 pt-2 border-t border-white/5">
                    <div className="flex justify-between text-[10px] font-semibold">
                      <span className="text-slate-400 flex items-center gap-1"><Icon name="hard_drive" className="text-[10px]" /> Output Disk</span>
                      <span className={selectedAgent.system_info.disk_free_mb < 10000 ? "text-red-400" : "text-slate-300"}>
                        {selectedAgent.system_info.disk_free_mb > 1024 ? `${Math.round(selectedAgent.system_info.disk_free_mb/1024)}GB free` : `${selectedAgent.system_info.disk_free_mb}MB free`}
                      </span>
                    </div>
                    <div className="h-1 w-full bg-black/40 rounded-full overflow-hidden flex justify-end">
                      <div className={`h-full rounded-full ${selectedAgent.system_info.disk_free_mb < 5000 ? "bg-red-500" : "bg-slate-500"}`} style={{ width: `${100 - selectedAgent.system_info.disk_percent}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Offline warning with switch link */}
          {selectedAgent && selectedIsOffline && onlineAlternative && (
            <button
              onClick={() => setActiveAgent(onlineAlternative.agent_id)}
              className="w-full px-3 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg text-left hover:bg-amber-500/15 transition-colors group"
            >
              <p className="text-[10px] text-amber-400 font-semibold leading-tight">
                Switch to {onlineAlternative.name}
              </p>
              <p className="text-[10px] text-amber-400/60 leading-tight">
                This workstation is online
              </p>
            </button>
          )}
        </div>

        {/* Settings + Help at bottom */}
        <div className="px-3 pb-5 border-t border-white/5 pt-3 space-y-0.5">
          <Link
            href="/help"
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${location === "/help"
              ? "bg-primary/10 text-primary"
              : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              }`}
          >
            <Icon name="help_outline" fill={location === "/help"} className="text-[20px] shrink-0" />
            Help
          </Link>
          <Link
            href="/settings"
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${location === "/settings"
              ? "bg-primary/10 text-primary"
              : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              }`}
          >
            <Icon name="settings" fill={location === "/settings"} className="text-[20px] shrink-0" />
            Settings
          </Link>
        </div>
      </aside>

      {/* ── Main content ── */}
      <div className="flex-1 md:ml-56 min-w-0 flex flex-col">
        <AnnouncementBanner />
        {children}
      </div>

      {/* ── Mobile bottom nav (hidden on /download — desktop-only page) ── */}
      {location !== "/download" && (
        <div className="md:hidden">
          <BottomNav />
        </div>
      )}
    </div>
  );
}
