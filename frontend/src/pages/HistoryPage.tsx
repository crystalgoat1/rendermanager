import { useState } from "preact/hooks";
import { useLocation } from "wouter";
import { useJobs } from "../hooks/useJobs";
import { useAgents } from "../hooks/useAgent";
import { useProfile } from "../hooks/useProfile";
import { useApi } from "../hooks/useApi";
import { Icon } from "../components/Icon";
import { FrameBrowser } from "../components/FrameBrowser";
import { JobSettingsModal } from "../components/JobSettingsModal";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { Job } from "../types";

type Filter = "all" | "completed" | "failed";

const FILTERS: Array<{ key: Filter; label: string; icon?: string; iconColor?: string }> = [
  { key: "all", label: "All Jobs" },
  { key: "completed", label: "Completed", icon: "check_circle", iconColor: "text-emerald-500" },
  { key: "failed", label: "Failed", icon: "error", iconColor: "text-red-500" },
];

const NEW_RENDER_WINDOW_MS = 12 * 60 * 60 * 1000; // 12 hours

function HistoryCard({ job, onShowDetails, onDelete, isPro, renderAgentName, isAgentOnline }: { job: Job; onShowDetails: () => void; onDelete: () => void; isPro: boolean; renderAgentName: string | null; isAgentOnline: boolean }) {
  const { apiJson } = useApi();
  const [, navigate] = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const isCompleted = job.status === "completed";
  const isFailed = job.status === "failed" || job.status === "canceled";

  const isNew = isCompleted && !job.viewed_at && !!job.completed_at
    && Date.now() - new Date(job.completed_at).getTime() < NEW_RENDER_WINDOW_MS;

  function markViewed() {
    if (!isNew) return;
    apiJson(`/api/jobs/${job.job_id}/mark-viewed`, { method: "POST" }).catch(() => {});
  }

  const fileName = job.blend_relpath.split(/[\\/]/).pop() ?? job.blend_relpath;

  const endDate = isCompleted && job.completed_at
    ? new Date(job.completed_at)
    : isFailed && job.failed_at
      ? new Date(job.failed_at)
      : null;

  const statusLabel = isCompleted ? "Completed" : job.status === "canceled" ? "Canceled" : "Failed";
  const statusClass = isCompleted
    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
    : "bg-red-500/10 text-red-400 border border-red-500/20";

  const workstationName = renderAgentName;

  return (
    <div
      className={`bg-bg-surface rounded-xl p-4 border transition-colors ${isNew ? 'border-blue-500/30 shadow-[0_0_15px_rgba(59,130,246,0.1)] hover:border-blue-500/50' : 'border-white/5 shadow-sm hover:border-white/10'}`}
      onClick={markViewed}
    >
      {/* Top row: name, date, status, menu */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-200 truncate">{fileName}</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {endDate
              ? endDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) +
              " · " + endDate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
              : "-"}
            {workstationName && (
              <> · <span className="text-slate-400">{workstationName}</span></>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isNew && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-widest bg-blue-500/20 text-blue-400 border border-blue-500/30 animate-pulse">
              New
            </span>
          )}
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${statusClass}`}>
            {statusLabel}
          </span>
        </div>

        {/* 3-dot menu */}
        <div className="relative shrink-0">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-white/5 transition-colors"
            title="Options"
          >
            <Icon name="more_vert" className="text-base" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full mt-1 w-40 bg-bg-elevated border border-white/10 rounded-lg overflow-hidden shadow-xl z-20">
                <button
                  onClick={() => { setMenuOpen(false); onShowDetails(); }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-200 hover:bg-white/5 transition-colors"
                >
                  <Icon name="info" className="text-base text-slate-400" />
                  Details
                </button>
                <button
                  onClick={() => { setMenuOpen(false); navigate(`/new?from=${job.job_id}`); }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-200 hover:bg-white/5 transition-colors"
                >
                  <Icon name="replay" className="text-base text-slate-400" />
                  Render Again
                </button>
                <button
                  onClick={() => { setMenuOpen(false); onDelete(); }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <Icon name="delete" className="text-base" />
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Frame browser */}
      <FrameBrowser
        jobId={job.job_id}
        frameStart={job.frame_start}
        frameEnd={job.frame_end}
        progress={job.progress}
        currentFrame={job.current_frame}
        availablePasses={job.available_passes ?? []}
        outputFormat={job.output_format ?? undefined}
        agentOnline={isAgentOnline}
        agentName={renderAgentName ?? undefined}
        collapsible
        locked={!isPro}
      />
    </div>
  );
}

export function HistoryPage() {
  const { jobs, loading } = useJobs();
  const { agents } = useAgents();
  const { profile } = useProfile();
  const { apiJson } = useApi();
  const isPro = profile?.tier === "pro";

  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Job | null>(null);

  const historicJobs = jobs.filter((j) =>
    ["completed", "failed", "canceled"].includes(j.status)
  );

  const filtered = historicJobs
    .filter((j) => {
      if (filter === "completed") return j.status === "completed";
      if (filter === "failed") return j.status === "failed" || j.status === "canceled";
      return true;
    })
    .filter((j) =>
      search === "" || j.blend_relpath.toLowerCase().includes(search.toLowerCase())
    );

  async function doDelete() {
    if (!deleteTarget) return;
    try {
      await apiJson(`/api/jobs/${deleteTarget.job_id}`, { method: "DELETE" });
    } catch (err: any) {
      alert(`Failed to delete job: ${err.message}`);
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <div className="flex flex-col min-h-screen bg-bg-base">
      {/* Sticky header */}
      <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 pt-4 pb-3">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold tracking-tight">Render History</h1>
          <span className="text-xs text-slate-500 font-medium">
            {historicJobs.length} job{historicJobs.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Search */}
        <div className="relative flex items-center mb-3">
          <Icon name="search" className="absolute left-3 text-slate-500 pointer-events-none text-[18px]" />
          <input
            className="w-full max-w-md bg-bg-surface border border-white/5 rounded-lg py-2 pl-9 pr-4 text-sm text-slate-200 focus:ring-2 focus:ring-primary/50 outline-none placeholder:text-slate-500"
            placeholder="Search by file name..."
            type="text"
            value={search}
            onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          />
        </div>

        {/* Filter pills */}
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
          {FILTERS.map(({ key, label, icon, iconColor }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold whitespace-nowrap transition-all ${filter === key
                ? "gradient-primary text-white shadow-sm"
                : "bg-bg-surface border border-white/5 text-slate-200 hover:text-white"
                }`}
            >
              {icon && (
                <Icon
                  name={icon}
                  className={`text-[18px] ${filter === key ? "text-white" : iconColor}`}
                />
              )}
              {label}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 px-6 py-5 pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-8">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-slate-500 text-sm">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-20 text-center">
            <Icon name="history" className="text-slate-500 text-5xl" />
            <p className="text-slate-500 font-medium">
              {search ? "No matching jobs found" : "No render history yet"}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((job) => {
              const renderAgent = job.agent_id ? agents.find((a) => a.agent_id === job.agent_id) : null;
              return (
                <HistoryCard
                  key={job.job_id}
                  job={job}
                  onShowDetails={() => setDetailJob(job)}
                  onDelete={() => setDeleteTarget(job)}
                  isPro={isPro}
                  renderAgentName={renderAgent?.name ?? null}
                  isAgentOnline={renderAgent?.status !== "offline"}
                />
              );
            })}
          </div>
        )}
      </main>

      {/* Job details modal */}
      {detailJob && (
        <JobSettingsModal
          job={detailJob}
          onClose={() => setDetailJob(null)}
          showJobInfo
        />
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <ConfirmDialog
          title="Delete this job?"
          message={`"${deleteTarget.blend_relpath.split(/[\\/]/).pop()}" will be permanently deleted from your history.`}
          confirmLabel="Delete"
          danger
          onConfirm={doDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
