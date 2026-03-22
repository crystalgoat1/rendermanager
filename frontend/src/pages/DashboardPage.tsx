import { useState, useEffect, useRef } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { useJobs } from "../hooks/useJobs";
import { useAgents } from "../hooks/useAgent";
import { useApi } from "../hooks/useApi";
import { useProfile } from "../hooks/useProfile";
import { Icon } from "../components/Icon";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FrameBrowser } from "../components/FrameBrowser";
import { JobSettingsModal } from "../components/JobSettingsModal";
import { Job, Agent } from "../types";

// ─── helpers ────────────────────────────────────────────────────────────────

const ENGINE_LABELS: Record<string, string> = {
  CYCLES: "Cycles",
  BLENDER_EEVEE: "EEVEE",
  BLENDER_EEVEE_NEXT: "EEVEE Next",
  BLENDER_WORKBENCH: "Workbench",
};

function engineLabel(raw?: string | null) {
  return raw ? (ENGINE_LABELS[raw] ?? raw) : "Blend default";
}

// ─── Active render card ──────────────────────────────────────────────────────

function ActiveRenderCard({ job, agents }: { job: Job; agents: Agent[] }) {
  const { apiJson } = useApi();
  const { profile } = useProfile();
  const isPro = profile?.tier === "pro";
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showHardware, setShowHardware] = useState(false);
  const [previewFrame, setPreviewFrame] = useState<number | null>(null);
  const [passLoading, setPassLoading] = useState(false);
  const passUrlCacheRef = useRef<Map<string, string>>(new Map());
  const passPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Optimistic UI — update immediately, reset when real data arrives
  const [localPaused, setLocalPaused] = useState<boolean | null>(null);
  const [localCanceled, setLocalCanceled] = useState(false);

  // Reset optimistic overrides when real job data catches up
  useEffect(() => {
    if (localPaused != null && job.paused === localPaused) setLocalPaused(null);
  }, [job.paused]);
  useEffect(() => {
    if (localCanceled && job.status !== "in_progress") setLocalCanceled(false);
  }, [job.status]);

  const isPaused = (localPaused ?? job.paused) || job.pause_requested;
  const isCanceling = localCanceled || job.cancel_requested;
  const isResuming = job.status === "queued" && !!job.requeued_from_agent;

  // ── ETA ────────────────────────────────────────────────────────────────────
  // Track per-frame completion timestamps for a rolling average.
  // Each entry is the wall-clock ms when that frame finished.
  const frameTimestampsRef = useRef<number[]>([]);
  const lastTrackedFrameRef = useRef<number | null>(null);

  // When current_frame advances, record the timestamp of that frame completion.
  useEffect(() => {
    if (isPaused || job.current_frame == null) return;
    if (lastTrackedFrameRef.current !== job.current_frame) {
      lastTrackedFrameRef.current = job.current_frame;
      frameTimestampsRef.current = [...frameTimestampsRef.current, Date.now()].slice(-6);
    }
  }, [job.current_frame, isPaused]);

  // Stable ETA string — recomputed only when a frame completes (not every second).
  const [etaRemaining, setEtaRemaining] = useState<string | null>(null);
  const [etaFinishAt, setEtaFinishAt] = useState<string | null>(null);

  useEffect(() => {
    if (isPaused || job.progress <= 0 || job.progress >= 100) {
      setEtaRemaining(null);
      setEtaFinishAt(null);
      return;
    }

    const timestamps = frameTimestampsRef.current;
    const totalFrames = job.frame_end - job.frame_start + 1;
    const framesRendered = Math.round((job.progress / 100) * totalFrames);
    const framesLeft = totalFrames - framesRendered;

    let msPerFrame: number | null = null;

    if (timestamps.length >= 2) {
      // Average interval between the last N frame-completion timestamps
      const intervals: number[] = [];
      for (let i = 1; i < timestamps.length; i++) {
        intervals.push(timestamps[i] - timestamps[i - 1]);
      }
      msPerFrame = intervals.reduce((a, b) => a + b, 0) / intervals.length;
    } else if (job.assigned_at && framesRendered > 0) {
      // Fallback: overall average from session start
      const startMs = new Date(job.assigned_at).getTime();
      const progressBase = job.progress_base ?? 0;
      const sessionFrames = Math.round(((job.progress - progressBase) / 100) * totalFrames);
      if (sessionFrames > 0) {
        msPerFrame = (Date.now() - startMs) / sessionFrames;
      }
    }

    if (msPerFrame == null || msPerFrame <= 0 || framesLeft <= 0) {
      setEtaRemaining(null);
      setEtaFinishAt(null);
      return;
    }

    const remainMs = msPerFrame * framesLeft;
    const nowMs = Date.now();
    const totalSecs = Math.round(remainMs / 1000);
    const mins = Math.floor(totalSecs / 60);
    const hours = Math.floor(mins / 60);

    let remaining: string;
    if (hours > 0) remaining = `~${hours}h ${mins % 60}m`;
    else if (mins > 0) remaining = `~${mins}m`;
    else remaining = `<1m`;

    const finishDate = new Date(nowMs + remainMs);
    const timeStr = finishDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const todayMidnight = new Date(nowMs);
    todayMidnight.setHours(23, 59, 59, 999);
    const finishAt = finishDate > todayMidnight
      ? finishDate.toLocaleDateString([], { month: "short", day: "numeric" }) + " · " + timeStr
      : timeStr;

    setEtaRemaining(remaining);
    setEtaFinishAt(finishAt);
  }, [job.current_frame, job.progress, isPaused]);

  function pauseJob() {
    setLocalPaused(true);
    cancelPreview();
    apiJson(`/api/jobs/${job.job_id}/pause`, { method: "POST" })
      .catch((e) => console.error("[pause] failed:", e));
  }

  function resumeJob() {
    setLocalPaused(false);
    cancelPreview();
    apiJson(`/api/jobs/${job.job_id}/resume`, { method: "POST" })
      .catch((e) => console.error("[resume] failed:", e));
  }

  function doCancel() {
    setCancelConfirm(false);
    setLocalCanceled(true);
    cancelPreview();
    apiJson(`/api/jobs/${job.job_id}/cancel`, { method: "POST" })
      .catch((e) => console.error("[cancel] failed:", e));
  }

  // Pass selection
  const [selectedPass, setSelectedPass] = useState<string>("Combined");
  const selectedPassRef = useRef("Combined");
  const passes = job.available_passes || [];
  const showPassSelector = job.output_format === "OPEN_EXR_MULTILAYER" && passes.length > 1;

  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewCancelledRef = useRef(false);

  function cancelPreview() {
    // Signal cancellation to the in-flight promise
    previewCancelledRef.current = true;
    if (previewPollRef.current) {
      clearInterval(previewPollRef.current);
      previewPollRef.current = null;
    }
    if (passPollRef.current) {
      clearTimeout(passPollRef.current);
      passPollRef.current = null;
    }
    setPreviewLoading(false);
    setPassLoading(false);
    setPreviewError(null);
  }

  // Clean up poll intervals on unmount
  useEffect(() => {
    return () => {
      previewCancelledRef.current = true;
      if (previewPollRef.current) clearInterval(previewPollRef.current);
      if (passPollRef.current) clearTimeout(passPollRef.current);
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, []);

  // ── Auto-refresh: poll for the latest preview every 10s while rendering ──
  // Use a ref-based approach to avoid stale closures in the interval

  // Track how long each non-Combined pass should keep refreshing (target frame = current + 5)
  const passLeasesRef = useRef<Record<string, number>>({});

  const autoRefreshFnRef = useRef<() => void>(() => { });
  autoRefreshFnRef.current = () => {
    const currentFrameIdx = job.latest_preview_frame || job.current_frame || job.frame_start;

    // Always fetch Combined and the explicitly selected pass
    const passesToFetch = new Set<string>(["Combined", selectedPassRef.current || "Combined"]);

    // Also fetch any pass that has an active lease
    for (const [p, targetFrame] of Object.entries(passLeasesRef.current)) {
      if (currentFrameIdx <= targetFrame) {
        passesToFetch.add(p);
      } else {
        // Lease gracefully expires
        delete passLeasesRef.current[p];
      }
    }

    passesToFetch.forEach(p => fetchPreview(p));
  };

  useEffect(() => {
    if (autoRefreshRef.current) {
      clearInterval(autoRefreshRef.current);
      autoRefreshRef.current = null;
    }

    // Initial fetch (always do this once on mount or when frame/status changes)
    autoRefreshFnRef.current();

    const isActive = job.status === "in_progress" && !isPaused;
    if (!isActive) return;

    autoRefreshRef.current = setInterval(() => {
      autoRefreshFnRef.current();
    }, 10_000);

    return () => {
      if (autoRefreshRef.current) {
        clearInterval(autoRefreshRef.current);
        autoRefreshRef.current = null;
      }
    };
  }, [job.status, isPaused, job.current_frame]); // re-trigger when frame advances

  async function fetchPreview(pass?: string) {
    const passToLoad = pass || selectedPassRef.current || "Combined";
    const isMain = passToLoad === (selectedPassRef.current || "Combined");

    if (isMain) {
      previewCancelledRef.current = false;
      setPreviewError(null);

      // If the frame has advanced since our last successful fetch, drop the old image
      // and show the loading spinner so the user never stares at a stale frame.
      // Exception: For the Combined pass, the new frame is already fully uploaded 
      // by the agent (which is why the frame bumped). We prefer a seamless, video-like 
      // transition without spinners or blurring while the browser downloads the new JPEG.
      const currentTargetFrame = job.latest_preview_frame ?? job.current_frame ?? job.frame_start;
      if (previewFrame !== null && currentTargetFrame > previewFrame) {
        if (passToLoad !== "Combined") {
          // Keep old image visible while loading new frame's pass
          setPreviewLoading(true);
        }
      }
    }

    try {
      const q = passToLoad && passToLoad !== "Combined" ? `?pass_name=${encodeURIComponent(passToLoad)}` : "";
      const data = await apiJson<{ url: string }>(`/jobs/${job.job_id}/preview-url${q}`);

      // Update cache in the background for all loaded passes
      passUrlCacheRef.current.set(passToLoad, data.url);

      // Only update UI state if we're fetching the currently visible pass
      if (isMain && !previewCancelledRef.current) {
        if (previewUrl === data.url) {
          setPreviewLoading(false);
          setPassLoading(false);
        }
        setPreviewUrl(data.url);
        setPreviewFrame(job.latest_preview_frame ?? null);
      }
    } catch {
      // Fallback to on-demand request
      try {
        const result = await fetchPreviewOnDemand(passToLoad);
        if (isMain && !previewCancelledRef.current) {
          if (previewUrl === result.url) {
            setPreviewLoading(false);
            setPassLoading(false);
          }
          setPreviewUrl(result.url);
          setPreviewFrame(result.frame);
        }
      } catch (e: any) {
        if (isMain && !previewCancelledRef.current) {
          const msg = e?.message || "No preview available yet";
          if (msg !== "Waiting for first frame...") {
            setPreviewError(msg);
          }
          setPreviewLoading(false);
          setPassLoading(false);
        }
      }
    }
  }

  /** Switch render pass — show dark placeholder while loading */
  // Free tier: user can browse pass names but only Combined actually loads
  const isFreeTierPassBlock = !isPro && selectedPass !== "Combined";

  function switchPass(newPass: string) {
    if (newPass === selectedPass) return;

    // Cancel any in-progress requests for the main view
    cancelPreview();

    setSelectedPass(newPass);
    selectedPassRef.current = newPass;
    setPreviewError(null);

    // Give this pass a 5-frame lease (for Pro users) so it stays fresh if user toggles back
    if (isPro) {
      const currentFrameIdx = job.latest_preview_frame || job.current_frame || job.frame_start;
      passLeasesRef.current[newPass] = currentFrameIdx + 5;
    }

    // Free tier: don't fetch non-Combined passes, just show placeholder
    if (!isPro && newPass !== "Combined") {
      setPassLoading(false);
      return;
    }

    // Check cache first — instant swap (e.g. switching back to Combined)
    const cached = passUrlCacheRef.current.get(newPass);
    if (cached) {
      setPreviewUrl(cached);
      setPreviewLoading(false);
      // Still trigger a background refresh to ensure we have the very latest frame
      if (job.status === "in_progress" && !isPaused) {
        fetchPreview(newPass);
      }
      return;
    }

    // Pass NOT cached! Show loading placeholder until fully loaded.
    setPassLoading(true);
    fetchPreview(newPass);
  }

  /** Load a specific pass — try signed URL first, fall back to on-demand + poll */
  async function loadPass(passName: string) {
    const frameToUse = previewFrame
      ?? (job.current_frame != null && job.current_frame >= job.frame_start
        ? Math.min(job.current_frame, job.frame_end)
        : null);

    if (frameToUse == null) {
      setPassLoading(false);
      setPreviewError(`Pass '${passName}' not available yet`);
      return;
    }

    // 1) Try signed URL (instant if agent preloaded)
    try {
      const params = new URLSearchParams({ frame: String(frameToUse), pass_name: passName });
      const data = await apiJson<{ url: string }>(`/jobs/${job.job_id}/frame-preview-url?${params}`);
      setPreviewUrl(data.url);
      passUrlCacheRef.current.set(passName, data.url);
      setPassLoading(false);
      return;
    } catch { /* fall through to on-demand */ }

    // 2) On-demand request + poll
    try {
      const body: any = { type: "frame", frame: frameToUse };
      if (passName && passName !== "Combined") body.pass_name = passName;

      const reqData = await apiJson<{ request_id: string; status: string }>(
        `/api/jobs/${job.job_id}/preview-request`,
        { method: "POST", body: JSON.stringify(body) },
      );

      if (reqData.status === "ready") {
        const params = new URLSearchParams({ frame: String(frameToUse), pass_name: passName });
        try {
          const data = await apiJson<{ url: string }>(`/jobs/${job.job_id}/frame-preview-url?${params}`);
          setPreviewUrl(data.url);
          passUrlCacheRef.current.set(passName, data.url);
        } catch { /* URL fetch failed */ }
        setPassLoading(false);
        return;
      }

      // Poll until ready
      let attempts = 0;
      function schedulePassPoll() {
        passPollRef.current = setTimeout(async () => {
          attempts++;
          if (attempts > 15) {
            passPollRef.current = null;
            setPassLoading(false);
            setPreviewError(`Pass '${passName}' timed out`);
            return;
          }
          try {
            const poll = await apiJson<{ status: string }>(`/api/preview-requests/${reqData.request_id}`);
            if (poll.status === "ready") {
              passPollRef.current = null;
              const params = new URLSearchParams({ frame: String(frameToUse), pass_name: passName });
              try {
                const data = await apiJson<{ url: string }>(`/jobs/${job.job_id}/frame-preview-url?${params}`);
                setPreviewUrl(data.url);
                passUrlCacheRef.current.set(passName, data.url);
              } catch { /* URL fetch failed */ }
              setPassLoading(false);
            } else if (poll.status === "failed" || poll.status === "expired") {
              passPollRef.current = null;
              setPassLoading(false);
              setPreviewError(`Pass '${passName}' not available`);
            } else {
              schedulePassPoll();
            }
          } catch {
            passPollRef.current = null;
            setPassLoading(false);
          }
        }, 2000);
      }
      schedulePassPoll();
    } catch {
      setPassLoading(false);
      setPreviewError(`Pass '${passName}' not available`);
    }
  }

  async function fetchPreviewOnDemand(pass?: string): Promise<{ url: string, frame: number }> {
    // Rely on the exact frame the agent just uploaded if available.
    // Otherwise fallback to estimating from current_frame or progress.
    let latestFrame: number;
    if (job.latest_preview_frame != null) {
      latestFrame = job.latest_preview_frame;
    } else if (job.current_frame != null && job.current_frame >= job.frame_start) {
      latestFrame = Math.min(job.current_frame, job.frame_end);
    } else {
      const totalFrames = (job.frame_end - job.frame_start) + 1;
      const completedFrames = Math.ceil((job.progress / 100) * totalFrames);
      latestFrame = job.progress >= 100
        ? job.frame_end
        : Math.max(job.frame_start, Math.min(job.frame_end,
          job.frame_start + completedFrames - 1));
    }

    // Check if we are at the very beginning of the job before the first frame is done
    if (job.status === "in_progress" && job.progress === 0 && job.latest_preview_frame == null) {
      throw new Error("Waiting for first frame...");
    }

    const passName = pass || "Combined";

    // Helper to get a signed URL for the frame
    async function getSignedUrl(): Promise<string | null> {
      try {
        const params = new URLSearchParams({ frame: String(latestFrame), pass_name: passName });
        const data = await apiJson<{ url: string }>(`/jobs/${job.job_id}/frame-preview-url?${params}`);
        return data.url;
      } catch { return null; }
    }

    // Check cancellation before each step
    if (previewCancelledRef.current) throw new Error("Cancelled");

    // Try signed URL first (instant if already in Storage)
    const directUrl = await getSignedUrl();
    if (previewCancelledRef.current) throw new Error("Cancelled");
    if (directUrl) {
      passUrlCacheRef.current.set(passName, directUrl);
      return { url: directUrl, frame: latestFrame };
    }

    // Fall back to on-demand request
    const body: any = { type: "frame", frame: latestFrame };
    if (pass && pass !== "Combined") body.pass_name = pass;

    const reqData = await apiJson<{ request_id: string; status: string }>(
      `/api/jobs/${job.job_id}/preview-request`,
      { method: "POST", body: JSON.stringify(body) },
    );
    if (previewCancelledRef.current) throw new Error("Cancelled");

    if (reqData.status === "ready") {
      const url = await getSignedUrl();
      if (previewCancelledRef.current) throw new Error("Cancelled");
      if (url) {
        passUrlCacheRef.current.set(passName, url);
        return { url, frame: latestFrame };
      }
      throw new Error("Preview ready but URL not available");
    }

    // Poll for result (max ~30s)
    return new Promise<{ url: string, frame: number }>((resolve, reject) => {
      if (previewPollRef.current) clearInterval(previewPollRef.current);
      let attempts = 0;
      previewPollRef.current = setInterval(async () => {
        // Check cancellation inside the interval
        if (previewCancelledRef.current) {
          if (previewPollRef.current) clearInterval(previewPollRef.current);
          previewPollRef.current = null;
          reject(new Error("Cancelled"));
          return;
        }
        attempts++;
        if (attempts > 15) {
          if (previewPollRef.current) clearInterval(previewPollRef.current);
          previewPollRef.current = null;
          reject(new Error("Preview timed out - try again or use Browse Frames"));
          return;
        }
        try {
          const poll = await apiJson<{ status: string }>(`/api/preview-requests/${reqData.request_id}`);
          if (previewCancelledRef.current) {
            if (previewPollRef.current) clearInterval(previewPollRef.current);
            previewPollRef.current = null;
            reject(new Error("Cancelled"));
            return;
          }
          if (poll.status === "ready") {
            if (previewPollRef.current) clearInterval(previewPollRef.current);
            previewPollRef.current = null;
            const url = await getSignedUrl();
            if (url) {
              passUrlCacheRef.current.set(passName, url);
              resolve({ url, frame: latestFrame });
            } else {
              reject(new Error("Preview ready but URL not available"));
            }
          } else if (poll.status === "failed" || poll.status === "expired") {
            if (previewPollRef.current) clearInterval(previewPollRef.current);
            previewPollRef.current = null;
            reject(new Error("Frame not available - the file may have been deleted or was never rendered"));
          }
        } catch {
          if (previewPollRef.current) clearInterval(previewPollRef.current);
          previewPollRef.current = null;
          reject(new Error("Poll error"));
        }
      }, 2000);
    });
  }

  useEffect(() => {
    // If we have passes but haven't fetched the current one yet, we should
    // when the component mounts or when passes change.
    // The main interval polling doesn't poll preview URL directly, 
    // it relies on the user clicking the refresh button.
    // However, if the user changes the pass dropdown, we should fetch it.
    // This is handled by the onChange handler.
  }, [passes.length]);

  const fileName = job.blend_relpath.split(/[\\/]/).pop() ?? job.blend_relpath;

  return (
    <div className="bg-bg-surface rounded-xl border border-white/5 overflow-hidden shadow-xl">
      {/* Label bar */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between border-b border-white/5">
        <div className="flex items-center gap-2">
          {isCanceling ? (
            <span className="text-[10px] font-bold text-red-400 uppercase tracking-widest flex items-center gap-1.5">
              <Icon name="cancel" fill className="text-sm" />
              Canceling...
            </span>
          ) : isResuming ? (
            <span className="text-[10px] font-bold text-blue-400 uppercase tracking-widest flex items-center gap-1.5">
              <Icon name="play_circle" fill className="text-sm" />
              Resuming...
            </span>
          ) : isPaused ? (
            <span className="text-[10px] font-bold text-amber-400 uppercase tracking-widest flex items-center gap-1.5">
              <Icon name="pause_circle" fill className="text-sm" />
              Paused
            </span>
          ) : (
            <>
              <span className="relative flex size-2">
                <span className="animate-ping absolute inline-flex size-full rounded-full bg-primary opacity-60" />
                <span className="relative inline-flex rounded-full size-2 bg-primary" />
              </span>
              <span className="text-[10px] font-bold text-primary uppercase tracking-widest">Rendering Now</span>
            </>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* File + frames */}
        <div className="flex items-start justify-between">
          <div>
            <p className="text-lg font-bold leading-tight">{fileName}</p>
            <p className="text-xs text-slate-400 mt-0.5">Frames {job.frame_start}-{job.frame_end}</p>
          </div>
          <div className="flex items-center gap-1">
            {(() => {
              const agent = agents.find(a => a.agent_id === job.agent_id);
              const sys = agent?.system_info;
              const gpu = sys?.gpus?.[0];
              const diskFreeGb = sys ? Math.round(sys.disk_free_mb / 1024) : null;
              const hasCritical = !!(
                (gpu && gpu.temperature_c > 90) ||
                (gpu && gpu.vram_percent > 98) ||
                (diskFreeGb !== null && diskFreeGb < 5) ||
                (sys && sys.ram_percent > 98)
              );
              const hasWarning = !hasCritical && !!(
                (gpu && gpu.temperature_c > 80) ||
                (gpu && gpu.vram_percent > 90) ||
                (diskFreeGb !== null && diskFreeGb < 20) ||
                (sys && sys.ram_percent > 90) ||
                (sys && sys.cpu_percent > 95)
              );
              return (
                <button
                  onClick={() => setShowHardware(!showHardware)}
                  className={`relative p-1.5 rounded-lg transition-colors ${showHardware ? "text-primary bg-primary/10" : "text-slate-500 hover:text-slate-200 hover:bg-white/5"}`}
                  title="Hardware status"
                >
                  <Icon name="memory" className="text-lg" />
                  {(hasCritical || hasWarning) && (
                    <span className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full ${hasCritical ? "bg-red-500" : "bg-amber-500"}`} />
                  )}
                </button>
              );
            })()}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={`p-1.5 rounded-lg transition-colors ${showSettings ? "text-primary bg-primary/10" : "text-slate-500 hover:text-slate-200 hover:bg-white/5"}`}
              title="Job settings"
            >
              <Icon name="info" className="text-lg" />
            </button>
          </div>
        </div>

        {/* Read-only settings Modal */}
        {showSettings && (
          <JobSettingsModal job={job} onClose={() => setShowSettings(false)} />
        )}

        {/* Hardware status popup */}
        {showHardware && (() => {
          const agent = agents.find(a => a.agent_id === job.agent_id);
          const sys = agent?.system_info;
          if (!sys) return (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setShowHardware(false)}>
              <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
              <div className="relative bg-bg-surface border border-white/10 rounded-xl p-5 w-full max-w-sm shadow-2xl animate-in fade-in duration-200" onClick={e => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold">Hardware Status</h3>
                  <button onClick={() => setShowHardware(false)} className="p-1 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-white/5"><Icon name="close" className="text-lg" /></button>
                </div>
                <p className="text-xs text-slate-500">No telemetry data available</p>
              </div>
            </div>
          );

          const gpu = sys.gpus?.[0];
          const diskFreeGb = Math.round(sys.disk_free_mb / 1024);
          const diskTotalGb = Math.round(sys.disk_total_mb / 1024);
          const ramUsedGb = (sys.ram_used_mb / 1024).toFixed(1);
          const ramTotalGb = (sys.ram_total_mb / 1024).toFixed(1);

          type Severity = "normal" | "warning" | "critical";
          const severity = (warning: boolean, critical: boolean): Severity =>
            critical ? "critical" : warning ? "warning" : "normal";
          const severityColor = (s: Severity) =>
            s === "critical" ? "text-red-400" : s === "warning" ? "text-amber-400" : "text-slate-300";
          const barColor = (s: Severity) =>
            s === "critical" ? "bg-red-500" : s === "warning" ? "bg-amber-500" : "bg-primary";

          const cpuSev = severity(sys.cpu_percent > 95, false);
          const ramSev = severity(sys.ram_percent > 90, sys.ram_percent > 98);
          const diskSev = severity(diskFreeGb < 20, diskFreeGb < 5);
          const gpuLoadSev = gpu ? severity(false, false) : "normal" as Severity;
          const gpuTempSev = gpu ? severity(gpu.temperature_c > 80, gpu.temperature_c > 90) : "normal" as Severity;
          const vramSev = gpu ? severity(gpu.vram_percent > 90, gpu.vram_percent > 98) : "normal" as Severity;

          const MetricBar = ({ label, value, percent, sev, icon }: { label: string; value: string; percent: number; sev: Severity; icon: string }) => (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Icon name={icon} className="text-sm" />
                  {label}
                </span>
                <span className={`text-xs font-medium ${severityColor(sev)}`}>{value}</span>
              </div>
              <div className="h-1.5 w-full bg-slate-800/60 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${barColor(sev)}`} style={{ width: `${Math.min(percent, 100)}%` }} />
              </div>
            </div>
          );

          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setShowHardware(false)}>
              <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
              <div className="relative bg-bg-surface border border-white/10 rounded-xl p-5 w-full max-w-sm shadow-2xl animate-in fade-in duration-200" onClick={e => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold flex items-center gap-2">
                    <Icon name="memory" className="text-base" />
                    Hardware Status
                  </h3>
                  <button onClick={() => setShowHardware(false)} className="p-1 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-white/5"><Icon name="close" className="text-lg" /></button>
                </div>

                <div className="space-y-3">
                  {gpu && (
                    <>
                      <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{gpu.name || "GPU"}</div>
                      <MetricBar icon="speed" label="GPU Load" value={`${gpu.load_percent}%`} percent={gpu.load_percent} sev={gpuLoadSev} />
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-xs text-slate-400">
                          <Icon name="thermostat" className="text-sm" />
                          Temperature
                        </span>
                        <span className={`text-xs font-medium ${severityColor(gpuTempSev)}`}>{gpu.temperature_c}°C</span>
                      </div>
                      <MetricBar icon="memory" label="VRAM" value={`${Math.round(gpu.vram_used_mb / 1024)}/${Math.round(gpu.vram_total_mb / 1024)} GB`} percent={gpu.vram_percent} sev={vramSev} />
                      <div className="border-t border-white/5 my-1" />
                    </>
                  )}
                  <MetricBar icon="monitor" label="CPU" value={`${sys.cpu_percent}%`} percent={sys.cpu_percent} sev={cpuSev} />
                  <MetricBar icon="stacks" label="RAM" value={`${ramUsedGb}/${ramTotalGb} GB`} percent={sys.ram_percent} sev={ramSev} />
                  <MetricBar icon="hard_drive" label="Disk" value={`${diskFreeGb}/${diskTotalGb} GB free`} percent={sys.disk_percent} sev={diskSev} />
                </div>
              </div>
            </div>
          );
        })()}

        {/* Preview area */}
        {(() => {
          const hasFrames = !!job.latest_preview_path || job.progress > 0
            || (job.current_frame != null && job.current_frame >= job.frame_start);

          return (
            <div className="relative w-full aspect-video rounded-lg bg-black/40 border border-white/10 shadow-inner group">

              {/* === Main Content Area === */}
              {previewUrl && (
                <>
                  <img
                    src={previewUrl}
                    alt="Render preview"
                    className={`w-full h-full object-contain cursor-pointer md:cursor-default rounded-lg transition-opacity duration-200 ${(passLoading || previewLoading) ? "opacity-0" : "opacity-100"}`}
                    onLoad={() => {
                      setPreviewLoading(false);
                      setPassLoading(false);
                    }}
                    onError={() => {
                      setPreviewLoading(false);
                      setPassLoading(false);
                    }}
                    onClick={() => {
                      if (window.innerWidth < 768) setFullscreen(true);
                    }}
                  />

                  {/* Free tier pass block overlay */}
                  {isFreeTierPassBlock && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 z-[5] rounded-lg">
                      <Icon name="bolt" className="text-3xl text-primary" />
                      <span className="text-sm font-bold text-slate-300">Pro Feature</span>
                      <span className="text-xs text-slate-500 text-center px-6">Multilayer EXR pass viewing requires Pro.<br />The Combined pass is shown by default.</span>
                    </div>
                  )}
                </>
              )}

              {/* Loading & Empty states overlay */}
              {(!previewUrl || passLoading || previewLoading) && !isFreeTierPassBlock && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/80 rounded-lg z-[2] pointer-events-none transition-opacity duration-200">
                  <Icon name="progress_activity" className="text-2xl text-slate-500 animate-spin" />
                  <span className="text-xs text-slate-500 font-medium text-center px-4">
                    {passLoading ? "Loading pass..." :
                     previewLoading ? "Loading preview..." :
                     isPaused && !previewUrl ? "Preview paused" : "Waiting for first frame..."}
                  </span>
                </div>
              )}

              {/* === Persistent Overlays (always visible) === */}

              {/* Top-left Pass Selector (if multilayer EXR) */}
              {showPassSelector && (
                <div className="absolute top-2 left-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                  <select
                    value={selectedPass}
                    onChange={(e) => switchPass((e.target as HTMLSelectElement).value)}
                    className="bg-black/80 backdrop-blur-md text-xs font-semibold text-slate-200 border border-white/10 rounded px-2 py-1 outline-none focus:border-white/30 cursor-pointer shadow-xl appearance-none pr-6"
                    style={{
                      backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23cbd5e1%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E")`,
                      backgroundRepeat: "no-repeat",
                      backgroundPosition: "right 0.5rem top 50%",
                      backgroundSize: "0.65rem auto",
                    }}
                    title="Select Render Pass to Preview"
                  >
                    {passes.sort((a, b) => a === "Combined" ? -1 : b === "Combined" ? 1 : a.localeCompare(b)).map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Pass error overlay */}
              {previewError && (
                <div className="absolute bottom-10 left-2 right-2 z-10">
                  <span className="bg-black/80 backdrop-blur-md text-xs text-red-400 font-medium px-2.5 py-1 rounded border border-red-500/20">
                    {previewError}
                  </span>
                </div>
              )}

              {/* Top-right controls */}
              <div className="absolute top-2 right-2 hidden md:flex gap-1 z-10">
                <button
                  onClick={() => setFullscreen(true)}
                  className="bg-black/60 backdrop-blur-md p-1.5 rounded border border-white/10 text-white/70 hover:text-white transition-colors"
                  title="Fullscreen"
                >
                  <Icon name="fullscreen" className="text-sm" />
                </button>
              </div>

              {/* Bottom label */}
              {previewUrl && (
                <div className="absolute bottom-2 left-2 bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1.5 border border-white/10 z-10">
                  {isPaused ? (
                    <>
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                      <span className="text-amber-400">
                        {previewFrame != null
                          ? `Last saved · Frame ${previewFrame}`
                          : (job.latest_preview_frame != null ? `Last saved · Frame ${job.latest_preview_frame}` : "Preview")}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0" />
                      <span>
                        {previewFrame != null
                          ? `Last saved · Frame ${previewFrame}`
                          : (job.latest_preview_frame != null ? `Last saved · Frame ${job.latest_preview_frame}` : "Preview")}
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })()}

        {/* Fullscreen overlay */}
        {fullscreen && previewUrl && (
          <div
            className="fixed inset-0 z-50 bg-black/92 backdrop-blur-sm flex items-center justify-center"
            onClick={() => setFullscreen(false)}
          >
            <img
              src={previewUrl}
              alt="Render preview"
              className="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
            <button
              className="absolute top-4 right-4 bg-white/10 hover:bg-white/20 rounded-full p-2.5 text-white transition-colors"
              onClick={() => setFullscreen(false)}
              title="Close"
            >
              <Icon name="close" className="text-xl" />
            </button>
          </div>
        )}

        {/* Frame browser */}
        {(() => {
          const targetAgent = job.agent_id ? agents.find((a) => a.agent_id === job.agent_id) : null;
          return (
            <FrameBrowser
              jobId={job.job_id}
              frameStart={job.frame_start}
              frameEnd={job.frame_end}
              progress={job.progress}
              currentFrame={job.current_frame}
              availablePasses={passes}
              outputFormat={job.output_format ?? undefined}
              collapsible
              isRendering={job.status === "in_progress" && !job.paused}
              locked={!isPro}
              agentOnline={targetAgent?.status !== "offline"}
              agentName={targetAgent?.name}
            />
          );
        })()}

        {/* Progress bar */}
        <div>
          <div className="flex justify-between items-end mb-2">
            <span className="text-2xl font-bold">{job.progress}%</span>
            {job.progress_message && !isPaused && !isResuming && (
              <span className="text-xs text-slate-400 font-mono">{job.progress_message}</span>
            )}
            {isResuming && (
              <span className="text-xs text-blue-400 font-medium">Resuming from {job.progress}%</span>
            )}
            {isPaused && !isResuming && (
              <span className="text-xs text-amber-400 font-medium">Paused at {job.progress}%</span>
            )}
          </div>
          <div className="h-2.5 w-full bg-slate-800/60 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 relative ${isPaused ? "bg-amber-500/60" : isResuming ? "bg-blue-500/60" : "gradient-primary"}`}
              style={{ width: `${job.progress}%` }}
            >
              {!isPaused && !isResuming && (
                <div className="absolute inset-y-0 right-0 w-6 bg-gradient-to-r from-transparent to-white/20 rounded-full" />
              )}
            </div>
          </div>

          {/* ETA row */}
          {etaRemaining && (
            <div className="flex items-center justify-between mt-2 text-xs text-slate-500">
              <span>{etaRemaining} remaining</span>
              <span>Done ~{etaFinishAt}</span>
            </div>
          )}

        </div>

        {/* Controls */}
        <div className="flex gap-3">
          {isCanceling ? (
            <div className="flex-1 text-center py-2.5 text-sm text-slate-500 font-medium">
              Canceling render...
            </div>
          ) : (
            <>
              {isResuming ? (
                <div className="flex-1 text-center py-2.5 text-sm text-blue-400 font-medium">
                  Waiting for agent to pick up...
                </div>
              ) : isPaused ? (
                <button
                  onClick={resumeJob}
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg gradient-primary text-white font-semibold text-sm shadow-lg shadow-black/20 hover:opacity-90 transition-all active:scale-95"
                >
                  <Icon name="play_arrow" fill className="text-lg" />
                  Resume
                </button>
              ) : (
                <button
                  onClick={pauseJob}
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg gradient-primary text-white font-semibold text-sm shadow-lg shadow-black/20 hover:opacity-90 transition-all active:scale-95"
                >
                  <Icon name="pause_circle" fill className="text-lg" />
                  Pause
                </button>
              )}
              <button
                onClick={() => setCancelConfirm(true)}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg bg-white/5 text-slate-400 font-semibold text-sm border border-white/10 hover:bg-white/10 hover:text-slate-200 transition-all active:scale-95"
              >
                <Icon name="stop_circle" className="text-lg" />
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      {cancelConfirm && (
        <ConfirmDialog
          title={isPaused ? "Cancel paused job?" : "Cancel render?"}
          message={
            isPaused
              ? "This job will be permanently removed."
              : "The current render will be stopped and the job removed."
          }
          confirmLabel="Yes, cancel"
          danger
          onConfirm={doCancel}
          onCancel={() => setCancelConfirm(false)}
        />
      )}
    </div>
  );
}

// ─── Queue row ───────────────────────────────────────────────────────────────

function QueueRow({ job }: { job: Job }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: job.job_id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    ...(isDragging ? { zIndex: 10 } : {}),
  };

  const { apiJson } = useApi();
  const [, navigate] = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState(false);

  function promptRemove() {
    setMenuOpen(false);
    setRemoveConfirm(true);
  }

  async function doRemove() {
    setRemoveConfirm(false);
    await apiJson(`/api/jobs/${job.job_id}`, { method: "DELETE" }).catch(() => { });
  }

  function editJob() {
    setMenuOpen(false);
    navigate(`/edit/${job.job_id}`);
  }

  const fileName = job.blend_relpath.split(/[\\/]/).pop() ?? job.blend_relpath;
  const totalFrames = job.frame_end - job.frame_start + 1;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors group border-b border-white/5 last:border-b-0 relative bg-bg-surface ${
        isDragging ? "opacity-30 border border-white/10 rounded-lg scale-[1.02] shadow-2xl" : ""
      }`}
    >
      {/* Drag handle */}
      <div
        {...(attributes as any)}
        {...listeners}
        className="p-1.5 -ml-1.5 cursor-grab active:cursor-grabbing text-slate-500 hover:text-slate-300 transition-colors touch-none"
      >
        <Icon name="drag_indicator" className="text-base shrink-0" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-200 truncate">{fileName}</p>
        <p className="text-xs text-slate-500 mt-0.5">
          {totalFrames} frame{totalFrames !== 1 ? "s" : ""}
          {" · "}frames {job.frame_start}-{job.frame_end}
        </p>
      </div>

      {/* Status — only show if paused */}
      {job.paused && (
        <span className="text-[10px] font-bold uppercase tracking-wider shrink-0 text-amber-400">
          Paused
        </span>
      )}

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
            {/* Click-away backdrop */}
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            {/* Dropdown */}
            <div className="absolute right-0 top-full mt-1 w-36 bg-bg-elevated border border-white/10 rounded-lg overflow-hidden shadow-xl z-20">
              <button
                onClick={editJob}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-200 hover:bg-white/5 transition-colors"
              >
                <Icon name="edit" className="text-base text-slate-400" />
                Edit Job
              </button>
              <button
                onClick={promptRemove}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
              >
                <Icon name="delete" className="text-base" />
                Remove
              </button>
            </div>
          </>
        )}
      </div>

      {removeConfirm && (
        <ConfirmDialog
          title="Remove from queue?"
          message={`"${job.blend_relpath.split(/[\\/]/).pop()}" will be removed from the queue.`}
          confirmLabel="Remove"
          danger
          onConfirm={doRemove}
          onCancel={() => setRemoveConfirm(false)}
        />
      )}
    </div>
  );
}

// ─── Dashboard page ──────────────────────────────────────────────────────────

export function DashboardPage() {
  const { jobs, loading: jobsLoading } = useJobs();
  const { agents } = useAgents();
  const { apiJson } = useApi();
  const { profile, setActiveAgent } = useProfile();

  const isPro = profile?.tier === "pro";
  const activeAgentId = profile?.active_agent_id;
  const selectedAgent = activeAgentId
    ? agents.find((a) => a.agent_id === activeAgentId)
    : null;

  const onlineAgents = agents.filter((a) => a.status !== "offline");
  const selectedIsOffline = selectedAgent ? selectedAgent.status === "offline" : true;
  const onlineAlternative = selectedIsOffline
    ? onlineAgents.find((a) => a.agent_id !== activeAgentId)
    : null;

  // Show workstation switcher only for Pro with multiple workstations
  const showSwitcher = isPro && agents.length > 1;
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);

  // Filter jobs to the selected workstation
  const myJobs = activeAgentId
    ? jobs.filter((j) => {
      // In-progress / completed jobs have agent_id set by the server
      if (j.agent_id === activeAgentId) return true;
      // Paused jobs belong to the agent they were paused from
      if (j.status === "paused" && j.requeued_from_agent === activeAgentId) return true;
      // Queued jobs have target_agent_id set by the frontend
      if (j.status === "queued" && j.target_agent_id === activeAgentId) return true;
      // Jobs with no target_agent_id (legacy) — show on whatever workstation is active
      if (j.status === "queued" && !j.agent_id && !j.target_agent_id) return true;
      // Paused jobs with no target — show on active workstation
      if (j.status === "paused" && !j.requeued_from_agent) return true;
      return false;
    })
    : jobs;

  const inProgress = myJobs.filter(
    (j) => j.status === "in_progress" || j.status === "paused"
      // Resumed-from-pause jobs stay in the active area instead of queue
      || (j.status === "queued" && !!j.requeued_from_agent)
  );
  const queued = myJobs
    .filter((j) => j.status === "queued" && !j.requeued_from_agent)
    .sort((a, b) => (a.available_at ?? "").localeCompare(b.available_at ?? ""));
  const isEmpty = !jobsLoading && inProgress.length === 0 && queued.length === 0;

  // Local state for optimistic drag-and-drop updates
  const [localQueued, setLocalQueued] = useState<Job[]>([]);
  const [isUpdatingOrder, setIsUpdatingOrder] = useState(false);

  useEffect(() => {
    if (!isUpdatingOrder) {
      setLocalQueued(queued);
    }
  }, [queued, isUpdatingOrder]);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5, // minimum drag distance so taps work natively
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Drag end logic for optimistic updates
  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = localQueued.findIndex((j) => j.job_id === active.id);
      const newIndex = localQueued.findIndex((j) => j.job_id === over.id);
      
      if (oldIndex !== -1 && newIndex !== -1) {
        const reordered = arrayMove(localQueued, oldIndex, newIndex);
        
        // 1. Immediately visually update the queue without side-effects in a callback
        setIsUpdatingOrder(true);
        setLocalQueued(reordered);
        
        // 2. Perform background backend sync
        const orderedIds = reordered.map((j) => j.job_id);
        
        apiJson("/api/jobs/reorder", {
          method: "POST",
          body: JSON.stringify({ job_ids: orderedIds }),
        }).finally(() => {
          // Keep the lock active slightly longer to let WebSockets catch up.
          // This prevents rapid snap-backs between the local state and DB state.
          setTimeout(() => setIsUpdatingOrder(false), 2000);
        });
      }
    }
  }

  return (
    <div className="flex flex-col min-h-screen bg-bg-base">
      {/* Ambient glow */}
      <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
        <div className="absolute -top-32 right-0 w-96 h-96 bg-primary/8 rounded-full blur-[120px]" />
        <div className="absolute bottom-0 left-0 w-80 h-80 bg-secondary/5 rounded-full blur-[120px]" />
      </div>

      {/* Page header */}
      <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 shrink-0">
            <h1 className="text-xl font-bold tracking-tight">Render Queue</h1>
            {/* Status dot for single-agent users */}
            {!showSwitcher && selectedAgent && (
              <span
                className={`size-2 rounded-full shrink-0 ${
                  selectedAgent.status === "busy" ? "bg-primary animate-pulse"
                    : selectedAgent.status === "offline" ? "bg-slate-500"
                      : "bg-emerald-400"
                }`}
                title={selectedAgent.status === "busy" ? "Rendering" : selectedAgent.status === "offline" ? "Offline" : "Online"}
              />
            )}
          </div>

          <div className="flex items-center gap-2 min-w-0">
            {/* Agent selector — compact dropdown (only when multiple agents + Pro) */}
            {showSwitcher && selectedAgent && (
              <div className="relative min-w-0">
                <button
                  onClick={() => setAgentMenuOpen(!agentMenuOpen)}
                  className="flex items-center gap-1.5 pl-2.5 pr-2 py-1.5 rounded-lg text-xs font-medium transition-all min-w-0 bg-bg-surface border border-white/10 hover:border-white/20 cursor-pointer"
                >
                  <span className={`size-1.5 rounded-full shrink-0 ${
                    selectedAgent.status === "busy" ? "bg-primary animate-pulse"
                      : selectedAgent.status === "offline" ? "bg-slate-500"
                        : "bg-emerald-400"
                  }`} />
                  <span className="text-slate-200 truncate max-w-[72px] sm:max-w-[160px]">
                    {selectedAgent.name}
                  </span>
                  <Icon name="expand_more" className={`text-sm text-slate-500 shrink-0 transition-transform ${agentMenuOpen ? "rotate-180" : ""}`} />
                  {selectedIsOffline && onlineAlternative && (
                    <span className="size-1.5 rounded-full bg-emerald-400 shrink-0 -ml-0.5" title="Another workstation is online" />
                  )}
                </button>

                {/* Dropdown menu */}
                {agentMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setAgentMenuOpen(false)} />
                    <div className="absolute right-0 top-full mt-1 w-56 bg-bg-elevated border border-white/10 rounded-lg overflow-hidden shadow-xl z-20">
                      {agents.map((agent) => {
                        const isActive = agent.agent_id === activeAgentId;
                        return (
                          <button
                            key={agent.agent_id}
                            onClick={() => {
                              if (!isActive) setActiveAgent(agent.agent_id);
                              setAgentMenuOpen(false);
                            }}
                            className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors ${
                              isActive
                                ? "bg-white/5 text-white font-semibold"
                                : "text-slate-300 hover:bg-white/5 hover:text-white"
                            }`}
                          >
                            <span className={`size-2 rounded-full shrink-0 ${
                              agent.status === "busy" ? "bg-primary animate-pulse"
                                : agent.status !== "offline" ? "bg-emerald-400"
                                  : "bg-slate-500"
                            }`} />
                            <span className="truncate">{agent.name || "Unnamed"}</span>
                            <span className="ml-auto text-[10px] text-slate-500 shrink-0">
                              {agent.status === "busy" ? "Rendering" : agent.status === "offline" ? "Offline" : "Online"}
                            </span>
                            {isActive && (
                              <Icon name="check" className="text-sm text-primary shrink-0" />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>
            )}

            <Link href="/new">
              <button className="flex items-center gap-2 gradient-primary text-white font-semibold text-sm px-4 py-2 rounded-lg shadow-lg shadow-black/20 hover:opacity-90 transition-all active:scale-95 shrink-0">
                <Icon name="add" className="text-lg" />
                <span className={showSwitcher ? "hidden sm:inline" : ""}>New Render</span>
              </button>
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1 p-6 pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-6 space-y-6">
        {jobsLoading ? (
          <div className="flex items-center justify-center h-40 text-slate-500 text-sm">Loading...</div>

        ) : isEmpty ? (
          /* ── Empty state ── */
          <div className="max-w-md mx-auto mt-8">
            <div className="bg-bg-surface border border-white/5 rounded-xl p-10 flex flex-col items-center text-center shadow-lg">
              <div className="relative mb-6">
                <div className="absolute -inset-4 bg-primary/8 rounded-full blur-2xl" />
                <div className="relative size-20 flex items-center justify-center bg-bg-base border border-white/10 rounded-2xl">
                  <Icon name="movie_filter" className="text-5xl text-slate-500" />
                </div>
              </div>
              <h3 className="text-lg font-bold mb-2">No jobs in queue</h3>
              <div className="text-left text-slate-300 text-sm leading-relaxed mb-8 max-w-sm space-y-3">
                <p className="flex gap-2.5">
                  <span className="flex items-center justify-center bg-primary/20 text-primary rounded-full size-5 text-xs font-black shrink-0">1</span>
                  <span>Make sure your app is running on your workstation.</span>
                </p>
                <p className="flex gap-2.5">
                  <span className="flex items-center justify-center bg-primary/20 text-primary rounded-full size-5 text-xs font-black shrink-0">2</span>
                  <span>Install the Blender Addon from the app setup wizard for 1-click rendering.</span>
                </p>
                <p className="flex gap-2.5">
                  <span className="flex items-center justify-center bg-primary/20 text-primary rounded-full size-5 text-xs font-black shrink-0">3</span>
                  <span><b>Alternative:</b> copy your <code>.blend</code> files into your <code>BlendFiles</code> workspace folder.</span>
                </p>
              </div>
              <Link href="/new" className="w-full">
                <button className="w-full gradient-primary text-white font-bold py-3 px-6 rounded-lg flex items-center justify-center gap-2 shadow-lg shadow-black/20 hover:opacity-90 transition-all active:scale-95">
                  <Icon name="add_circle" className="text-lg" />
                  New Render Job
                </button>
              </Link>
            </div>

            {/* No workstation tip */}
            {agents.length === 0 && (
              <div className="mt-5 bg-primary/5 border border-primary/20 rounded-xl p-4 flex items-start gap-3">
                <div className="bg-primary/10 p-2 rounded-lg shrink-0">
                  <Icon name="lightbulb" className="text-primary text-xl" />
                </div>
                <div>
                  <p className="text-sm font-bold mb-1">App not installed</p>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Install the Windows app on your render PC to start queuing jobs.
                  </p>
                  <Link href="/download" className="text-xs font-bold text-primary flex items-center gap-1 mt-2">
                    Download App <Icon name="arrow_forward" className="text-xs" />
                  </Link>
                </div>
              </div>
            )}
          </div>

        ) : (
          /* ── Active content ── */
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            {/* Left column: active render */}
            <div className="space-y-4">
              {inProgress.length > 0 ? (
                inProgress.map((job) => (
                  <ActiveRenderCard key={job.job_id} job={job} agents={agents} />
                ))
              ) : (
                <div className="bg-bg-surface rounded-xl border border-white/5 p-8 flex flex-col items-center gap-3 text-center">
                  <Icon name="hourglass_empty" className="text-slate-500 text-4xl" />
                  <p className="text-slate-500 text-sm font-medium">No active render</p>
                  <p className="text-slate-500 text-xs">Jobs in queue will start when the workstation is ready.</p>
                </div>
              )}
            </div>

            {/* Right column: queue list */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest">
                  Queue
                </h2>
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                  {localQueued.length} job{localQueued.length !== 1 ? "s" : ""}
                </span>
              </div>

              <div className="bg-bg-surface rounded-xl border border-white/5">
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext
                    items={localQueued.map((j) => j.job_id)}
                    strategy={verticalListSortingStrategy}
                  >
                    {localQueued.length > 0 ? (
                      localQueued.map((job) => (
                        <QueueRow key={job.job_id} job={job} />
                      ))
                    ) : (
                      <div className="px-4 py-3 border-b border-white/5 flex items-center gap-4">
                        <span className="text-[10px] font-bold text-slate-500 w-5 text-center">-</span>
                        <p className="text-sm text-slate-500 italic">Queue is empty</p>
                      </div>
                    )}
                  </SortableContext>
                </DndContext>

                {/* "Add to queue" */}
                <Link href="/new" className="block">
                  <div className="flex items-center gap-4 px-4 py-3 text-slate-500 hover:text-primary hover:bg-white/[0.02] transition-colors border-t border-dashed border-white/5">
                    <Icon name="add" className="text-base ml-5 shrink-0" />
                    <span className="text-sm font-semibold">Add to queue...</span>
                  </div>
                </Link>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
