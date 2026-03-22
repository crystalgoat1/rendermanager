import { useState, useRef, useCallback, useEffect } from "preact/hooks";
import { Icon } from "./Icon";
import { useApi } from "../hooks/useApi";
import { useProfile } from "../hooks/useProfile";

interface FrameBrowserProps {
    jobId: string;
    frameStart: number;
    frameEnd: number;
    progress?: number;
    currentFrame?: number | null;
    collapsible?: boolean;
    availablePasses?: string[];
    isRendering?: boolean;
    locked?: boolean;
    outputFormat?: string;
    agentOnline?: boolean;
    agentName?: string;
}

type RequestStatus = "idle" | "requesting" | "ready" | "error";

export function FrameBrowser({ jobId, frameStart, frameEnd, progress, currentFrame, collapsible, availablePasses = [], isRendering = false, locked = false, outputFormat, agentOnline = true, agentName }: FrameBrowserProps) {
    // Cap slider to the newest frame that has been rendered
    // Prefer exact currentFrame from agent when available
    const effectiveMax = (progress != null && progress >= 100)
        ? frameEnd
        : (currentFrame != null && currentFrame >= frameStart)
            ? Math.min(currentFrame, frameEnd)
            : (progress != null && progress < 100)
                ? Math.max(frameStart, frameStart + Math.ceil((progress / 100) * (frameEnd - frameStart)))
                : frameEnd;
    const { apiJson } = useApi();
    const { profile } = useProfile();
    const isPro = profile?.tier === "pro";

    const [expanded, setExpanded] = useState(!collapsible);
    const [frame, setFrame] = useState(frameStart);
    const [status, setStatus] = useState<RequestStatus>("idle");
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [selectedPass, setSelectedPass] = useState<string>("Combined");
    const showPassSelector = outputFormat === "OPEN_EXR_MULTILAYER" && availablePasses.length > 1;
    const [fullscreen, setFullscreen] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Cache signed URLs per pass for the currently loaded frame
    const passUrlCacheRef = useRef<Map<string, string>>(new Map());
    const cachedFrameRef = useRef<number | null>(null);

    // Pass switching state — separate from frame loading
    const [passLoading, setPassLoading] = useState(false);
    const passPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Compile state
    const [compileStatus, setCompileStatus] = useState<RequestStatus>("idle");
    const [compileError, setCompileError] = useState<string | null>(null);
    const [videoUrl, setVideoUrl] = useState<string | null>(null);
    const [compiledRange, setCompiledRange] = useState<{ start: number; end: number } | null>(null);
    const [cooldownRemaining, setCooldownRemaining] = useState(0);
    const cooldownRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const compilePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const clearPoll = useCallback(() => {
        if (pollRef.current) {
            clearTimeout(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const clearPassPoll = useCallback(() => {
        if (passPollRef.current) {
            clearTimeout(passPollRef.current);
            passPollRef.current = null;
        }
    }, []);

    const clearCompilePoll = useCallback(() => {
        if (compilePollRef.current) {
            clearTimeout(compilePollRef.current);
            compilePollRef.current = null;
        }
    }, []);

    function cancelRequest() {
        clearPoll();
        setStatus(previewUrl ? "ready" : "idle");
        setError(null);
    }

    function cancelCompile() {
        clearCompilePoll();
        setCompileStatus("idle");
        setCompileError(null);
    }

    // Try to load cached compilation automatically on mount so users don't have to click "Compile" if it's ready
    const initialCompileCheckDone = useRef(false);
    useEffect(() => {
        if (!initialCompileCheckDone.current && isPro && effectiveMax > frameStart) {
            initialCompileCheckDone.current = true;
            apiJson<{ url: string; frame_start?: number; frame_end?: number }>(`/jobs/${jobId}/compile-url`)
                .then(cached => {
                    if (cached.url && cached.url.length > 0) {
                        setVideoUrl(cached.url);
                        setCompileStatus("ready");
                        setCompiledRange({ start: cached.frame_start ?? frameStart, end: cached.frame_end ?? effectiveMax });
                    }
                })
                .catch(() => { /* do nothing */ });
        }
    }, [jobId, effectiveMax, frameStart, isPro, apiJson]);

    // Clean up all polls on unmount
    useEffect(() => {
        return () => {
            if (pollRef.current) clearTimeout(pollRef.current);
            if (passPollRef.current) clearTimeout(passPollRef.current);
            if (compilePollRef.current) clearTimeout(compilePollRef.current);
        };
    }, []);

    /** Try to get a signed URL for a frame/pass directly from Supabase Storage */
    async function getFrameSignedUrl(f: number, passName: string): Promise<string | null> {
        try {
            const params = new URLSearchParams({ frame: String(f), pass_name: passName });
            const data = await apiJson<{ url: string }>(
                `/jobs/${jobId}/frame-preview-url?${params}`,
            );
            return data.url;
        } catch {
            return null;
        }
    }

    // ── Frame loading (Load button) ─────────────────────────────────────────

    async function requestFrame(passNameOverride?: string) {
        clearPoll();
        setStatus("requesting");
        setError(null);

        const passToUse = passNameOverride ?? selectedPass;

        // If switching frames, clear the cache
        if (cachedFrameRef.current !== frame) {
            passUrlCacheRef.current.clear();
            cachedFrameRef.current = frame;
        }

        // 1) Try signed URL first (instant if agent already uploaded to Storage)
        const signedUrl = await getFrameSignedUrl(frame, passToUse);
        if (signedUrl) {
            if (previewUrl === signedUrl) setStatus("ready");
            setPreviewUrl(signedUrl);
            passUrlCacheRef.current.set(passToUse, signedUrl);
            prefetchOtherPasses(passToUse);
            return;
        }

        if (!agentOnline) {
            setStatus("error");
            setError(`${agentName || "Workstation"} is offline. Only recently cached frames are available.`);
            return;
        }

        // 2) Fall back to on-demand request → poll → signed URL
        try {
            const body: any = { type: "frame", frame };
            if (passToUse && passToUse !== "Combined") {
                body.pass_name = passToUse;
            }
            const data = await apiJson<{ request_id: string; status: string }>(
                `/api/jobs/${jobId}/preview-request`,
                { method: "POST", body: JSON.stringify(body) },
            );

            if (data.status === "ready") {
                const url = await getFrameSignedUrl(frame, passToUse);
                if (url) {
                    if (previewUrl === url) setStatus("ready");
                    setPreviewUrl(url);
                    passUrlCacheRef.current.set(passToUse, url);
                    prefetchOtherPasses(passToUse);
                    return;
                }
            }

            // Poll until ready (max ~30s) using recursive setTimeout
            let pollAttempts = 0;
            function schedulePoll() {
                pollRef.current = setTimeout(async () => {
                    pollAttempts++;
                    if (pollAttempts > 15) {
                        pollRef.current = null;
                        setStatus("error");
                        setError("Frame not available - the file may not exist on the workstation");
                        return;
                    }
                    try {
                        const poll = await apiJson<{ status: string; request_id: string }>(
                            `/api/preview-requests/${data.request_id}`,
                        );
                        if (poll.status === "ready") {
                            pollRef.current = null;
                            const url = await getFrameSignedUrl(frame, passToUse);
                            if (url) {
                                if (previewUrl === url) setStatus("ready");
                                setPreviewUrl(url);
                                passUrlCacheRef.current.set(passToUse, url);
                                prefetchOtherPasses(passToUse);
                            } else {
                                setStatus("error");
                                setError("Preview ready but URL not available");
                            }
                        } else if (poll.status === "failed" || poll.status === "expired") {
                            pollRef.current = null;
                            setStatus("error");
                            setError("Frame not available - the file may have been deleted or was never rendered");
                        } else {
                            schedulePoll();
                        }
                    } catch {
                        pollRef.current = null;
                        setStatus("error");
                        setError("Failed to poll status");
                    }
                }, 2000);
            }
            schedulePoll();
        } catch (e: any) {
            setStatus("error");
            setError(e.message ?? "Request failed");
        }
    }

    // ── Background pass prefetch ────────────────────────────────────────────

    async function prefetchOtherPasses(loadedPass: string) {
        if (availablePasses.length <= 1) return;
        const currentFrame = frame;
        for (const pass of availablePasses) {
            if (pass === loadedPass) continue;
            if (passUrlCacheRef.current.has(pass)) continue;
            (async () => {
                try {
                    const url = await getFrameSignedUrl(currentFrame, pass);
                    if (url && cachedFrameRef.current === currentFrame) {
                        passUrlCacheRef.current.set(pass, url);
                    } else if (!url && cachedFrameRef.current === currentFrame) {
                        if (!agentOnline) return;
                        // Pass not found in Supabase → Request on-demand extraction from agent
                        await apiJson(`/api/jobs/${jobId}/preview-request`, {
                            method: "POST",
                            body: JSON.stringify({ type: "frame", frame: currentFrame, pass_name: pass }),
                        });
                        // Don't poll here. When user actually clicks the pass later,
                        // requestFrame will poll for it if it's not ready yet.
                    }
                } catch { /* background prefetch — ignore errors */ }
            })();
        }
    }

    // ── Pass switching (dropdown) — SEPARATE from frame loading ─────────────

    function switchPass(newPass: string) {
        // Cancel any in-progress pass load
        clearPassPoll();

        setSelectedPass(newPass);
        const cached = passUrlCacheRef.current.get(newPass);
        if (cached) {
            // Instant swap from cache
            setPreviewUrl(cached);
            setPassLoading(false);
        } else {
            // Show loading screen while loading the new pass
            setPassLoading(true);
            loadPass(newPass);
        }
    }

    async function loadPass(passName: string) {
        clearPassPoll();
        setPassLoading(true);

        const frameToLoad = cachedFrameRef.current ?? frame;

        // 1) Try signed URL (instant if agent preloaded)
        try {
            const url = await getFrameSignedUrl(frameToLoad, passName);
            if (url) {
                if (previewUrl === url) setPassLoading(false);
                setPreviewUrl(url);
                passUrlCacheRef.current.set(passName, url);
                return;
            }
        } catch { /* fall through */ }

        if (!agentOnline) {
            setPassLoading(false);
            setError(`${agentName || "Workstation"} is offline. Only recently cached passes are available.`);
            return;
        }

        // 2) On-demand request + poll
        try {
            const body: any = { type: "frame", frame: frameToLoad };
            if (passName && passName !== "Combined") {
                body.pass_name = passName;
            }
            const data = await apiJson<{ request_id: string; status: string }>(
                `/api/jobs/${jobId}/preview-request`,
                { method: "POST", body: JSON.stringify(body) },
            );

            if (data.status === "ready") {
                const url = await getFrameSignedUrl(frameToLoad, passName);
                if (url) {
                    if (previewUrl === url) setPassLoading(false);
                    setPreviewUrl(url);
                    passUrlCacheRef.current.set(passName, url);
                    return;
                }
            }

            // Poll until ready
            let attempts = 0;
            function schedulePassPoll() {
                passPollRef.current = setTimeout(async () => {
                    attempts++;
                    if (attempts > 15) {
                        passPollRef.current = null;
                        setPassLoading(false);
                        setError(`Pass '${passName}' not available`);
                        return;
                    }
                    try {
                        const poll = await apiJson<{ status: string }>(
                            `/api/preview-requests/${data.request_id}`,
                        );
                        if (poll.status === "ready") {
                            passPollRef.current = null;
                            const url = await getFrameSignedUrl(frameToLoad, passName);
                            if (url) {
                                if (previewUrl === url) setPassLoading(false);
                                setPreviewUrl(url);
                                passUrlCacheRef.current.set(passName, url);
                            } else {
                                setPassLoading(false);
                            }
                        } else if (poll.status === "failed" || poll.status === "expired") {
                            passPollRef.current = null;
                            setPassLoading(false);
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
        }
    }

    // ── Compile ─────────────────────────────────────────────────────────────

    async function requestCompile() {
        clearCompilePoll();
        setCompileStatus("requesting");
        setCompileError(null);
        setVideoUrl(null);

        try {
            // If we already compiled this exact range, return the stored video
            if (compiledRange && effectiveMax <= compiledRange.end) {
                try {
                    const cached = await apiJson<{ url: string }>(`/jobs/${jobId}/compile-url`);
                    if (cached.url) {
                        setVideoUrl(cached.url);
                        setCompileStatus("ready");
                        return;
                    }
                } catch { /* not cached, continue to fresh compile */ }
            }

            // Next, see if it was recently cached in Supabase
            try {
                const cached = await apiJson<{ url: string; frame_start?: number; frame_end?: number }>(`/jobs/${jobId}/compile-url`);
                if (cached.url && cached.url.length > 0) {
                    setVideoUrl(cached.url);
                    setCompileStatus("ready");
                    setCompiledRange({ start: cached.frame_start ?? frameStart, end: cached.frame_end ?? effectiveMax });
                    return;
                }
            } catch { /* fall through to generate */ }

            if (!agentOnline) {
                setCompileStatus("error");
                setCompileError(`Compilation requires ${agentName || "the workstation"} to be online.`);
                return;
            }

            const data = await apiJson<{ request_id: string; status: string }>(
                `/api/jobs/${jobId}/preview-request`,
                { method: "POST", body: JSON.stringify({ type: "compile", pass_name: "Combined", frame_start: frameStart, frame_end: effectiveMax }) },
            );

            if (data.status === "ready") {
                const urlData = await apiJson<{ url: string }>(`/jobs/${jobId}/compile-url`);
                setVideoUrl(urlData.url);
                setCompileStatus("ready");
                setCompiledRange({ start: frameStart, end: effectiveMax });
                return;
            }

            // Poll until ready (max ~5 min for compilation)
            let compileAttempts = 0;
            function scheduleCompilePoll() {
                compilePollRef.current = setTimeout(async () => {
                    compileAttempts++;
                    if (compileAttempts > 100) {
                        compilePollRef.current = null;
                        setCompileStatus("error");
                        return;
                    }
                    try {
                        const poll = await apiJson<{ status: string }>(
                            `/api/preview-requests/${data.request_id}`,
                        );
                        if (poll.status === "ready") {
                            compilePollRef.current = null;
                            try {
                                const urlData = await apiJson<{ url: string }>(`/jobs/${jobId}/compile-url`);
                                setVideoUrl(urlData.url);
                                setCompileStatus("ready");
                                setCompiledRange({ start: frameStart, end: effectiveMax });
                            } catch {
                                setCompileStatus("error");
                                setCompileError("Failed to fetch the compiled video URL.");
                            }
                        } else if (poll.status === "failed" || poll.status === "expired") {
                            compilePollRef.current = null;
                            setCompileStatus("error");
                            setCompileError("Compile failed on the workstation. Ensure ffmpeg and OpenEXR are working.");
                        } else {
                            scheduleCompilePoll();
                        }
                    } catch {
                        compilePollRef.current = null;
                        setCompileStatus("error");
                        setCompileError("Connection failed while polling the compilation status.");
                    }
                }, 3000);
            }
            scheduleCompilePoll();
        } catch {
            setCompileStatus("error");
            setCompileError("Network error while trying to request compilation.");
        }
    }

    const [showCompileConfirm, setShowCompileConfirm] = useState(false);

    function handleCompile() {
        setShowCompileConfirm(true);
    }

    function confirmCompile() {
        setShowCompileConfirm(false);
        setVideoUrl(null);
        setCompileError(null);

        // Start 1 min cooldown
        setCooldownRemaining(1);
        if (cooldownRef.current) clearTimeout(cooldownRef.current);
        cooldownRef.current = setTimeout(() => setCooldownRemaining(0), 60_000) as unknown as ReturnType<typeof setInterval>;

        requestCompile();
    }

    // ── Render ──────────────────────────────────────────────────────────────

    if (collapsible && !expanded) {
        const hasAnimation = videoUrl != null || (compiledRange && effectiveMax <= compiledRange.end);
        return (
            <button
                onClick={() => setExpanded(true)}
                className="flex items-center gap-2 text-sm font-semibold text-primary hover:text-white transition-colors mt-2"
            >
                <Icon name={hasAnimation ? "movie" : "image_search"} className="text-base" />
                {hasAnimation ? "View Animation" : "Browse Frames"}
            </button>
        );
    }

    return (
        <div className="mt-3 bg-bg-base/60 rounded-lg border border-white/5 p-4 space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h4 className="text-xs font-bold uppercase tracking-widest text-slate-400">
                        Frame Browser
                    </h4>
                    {locked && (
                        <span className="text-[9px] font-bold uppercase tracking-widest text-primary border border-primary/30 bg-primary/10 px-1.5 py-0.5 rounded">
                            Pro
                        </span>
                    )}
                </div>
                {collapsible && (
                    <button
                        onClick={() => setExpanded(false)}
                        className="text-slate-500 hover:text-slate-200 transition-colors"
                    >
                        <Icon name="close" className="text-base" />
                    </button>
                )}
            </div>

            {/* Slider + input row */}
            <div className={`flex items-center gap-3 flex-wrap ${locked ? "opacity-40 pointer-events-none" : ""}`}>
                <input
                    type="range"
                    min={frameStart}
                    max={effectiveMax}
                    value={frame}
                    disabled={locked}
                    onInput={(e) => setFrame(Number((e.target as HTMLInputElement).value))}
                    className="w-full h-1.5 rounded-full appearance-none bg-slate-700 accent-[var(--color-primary,#6366f1)] cursor-pointer"
                />
                <input
                    type="number"
                    min={frameStart}
                    max={effectiveMax}
                    value={frame}
                    disabled={locked}
                    onInput={(e) => {
                        const v = Number((e.target as HTMLInputElement).value);
                        if (v >= frameStart && v <= effectiveMax) setFrame(v);
                    }}
                    className="w-20 bg-bg-surface border border-white/10 rounded-lg px-3 py-1.5 text-sm text-center text-slate-200 focus:ring-2 focus:ring-primary/50 outline-none"
                />
                <button
                    onClick={() => requestFrame()}
                    disabled={locked || status === "requesting"}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg gradient-primary text-white font-semibold text-sm shadow-lg shadow-black/20 hover:opacity-90 transition-all active:scale-95 disabled:opacity-40"
                >
                    {status === "requesting" ? (
                        <Icon name="progress_activity" className="text-sm animate-spin" />
                    ) : (
                        <Icon name="image" className="text-sm" />
                    )}
                    Load
                </button>
                {status === "requesting" && (
                    <button
                        onClick={cancelRequest}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 font-semibold text-sm hover:bg-red-500/20 transition-all active:scale-95"
                        title="Cancel loading"
                    >
                        <Icon name="close" className="text-sm" />
                        Cancel
                    </button>
                )}
            </div>

            {/* Frame label */}
            <p className="text-xs text-slate-500">
                Frame <span className="text-slate-200 font-medium">{frame}</span>{" "}
                of {frameStart}-{effectiveMax}
                {effectiveMax < frameEnd && (
                    <span className="text-slate-500 ml-1">(rendering up to {frameEnd})</span>
                )}
            </p>

            {/* Error */}
            {error && (
                <p className="text-xs text-red-400">{error}</p>
            )}

            {/* Preview image — placeholder for frame loading or pass switching */}
            {(previewUrl || status === "requesting" || passLoading) && (
                <div className="relative w-full aspect-video rounded-lg bg-black/40 border border-white/10 shadow-inner group">
                    {previewUrl && (
                        <img
                            src={previewUrl}
                            alt={`Frame ${frame}`}
                            className={`w-full h-full object-contain cursor-pointer md:cursor-default transition-opacity duration-200 ${(status === "requesting" || passLoading) ? "opacity-0" : "opacity-100"}`}
                            onLoad={() => {
                                setPassLoading(false);
                                if (status === "requesting") setStatus("ready");
                            }}
                            onError={() => {
                                setPassLoading(false);
                                if (status === "requesting") setStatus("ready");
                            }}
                            onClick={() => {
                                if (window.innerWidth < 768) setFullscreen(true);
                            }}
                        />
                    )}

                    {(!previewUrl || status === "requesting" || passLoading) && (
                        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/80 rounded-lg z-[2] pointer-events-none transition-opacity duration-200">
                            <Icon name="progress_activity" className="text-2xl text-slate-500 animate-spin" />
                            <span className="text-xs text-slate-500 font-medium">{passLoading ? "Loading pass..." : "Loading..."}</span>
                        </div>
                    )}

                    {/* Top-left Pass Selector (if multilayer EXR) */}
                    {showPassSelector && (
                        <div className="absolute top-2 left-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2">
                            <select
                                value={selectedPass}
                                onChange={(e) => {
                                    const val = (e.target as HTMLSelectElement).value;
                                    switchPass(val);
                                }}
                                className={`bg-black/80 backdrop-blur-md text-xs font-semibold text-slate-200 cursor-pointer border border-white/10 rounded px-2 py-1 outline-none focus:border-white/30 shadow-xl appearance-none pr-6`}
                                style={{
                                    backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23cbd5e1%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E")`,
                                    backgroundRepeat: "no-repeat",
                                    backgroundPosition: "right 0.5rem top 50%",
                                    backgroundSize: "0.65rem auto",
                                }}
                                title={!isPro ? "Multilayer EXR streaming is a Pro feature" : "Select Render Pass to Preview"}
                            >
                                {availablePasses.sort((a, b) => a === "Combined" ? -1 : b === "Combined" ? 1 : a.localeCompare(b)).map((p) => (
                                    <option key={p} value={p}>{p}</option>
                                ))}
                            </select>
                            {!isPro && (
                                <div className="bg-black/80 backdrop-blur-md px-2 py-1 rounded text-[10px] font-bold text-primary border border-primary/30 flex items-center gap-1 shadow-xl">
                                    <Icon name="bolt" className="text-[10px]" />
                                    PRO
                                </div>
                            )}
                        </div>
                    )}

                    <div className="absolute top-2 right-2 hidden md:flex gap-1">
                        <button
                            onClick={() => setFullscreen(true)}
                            className="bg-black/60 backdrop-blur-md p-1.5 rounded border border-white/10 text-white/70 hover:text-white transition-colors"
                            title="Fullscreen"
                        >
                            <Icon name="fullscreen" className="text-sm" />
                        </button>
                    </div>
                    <div className="absolute bottom-2 left-2 bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-bold border border-white/10">
                        Frame {frame}
                    </div>
                </div>
            )}

            {/* Fullscreen */}
            {fullscreen && previewUrl && (
                <div
                    className="fixed inset-0 z-50 bg-black/92 backdrop-blur-sm flex items-center justify-center"
                    onClick={() => setFullscreen(false)}
                >
                    <img
                        src={previewUrl}
                        alt={`Frame ${frame}`}
                        className="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
                        onClick={(e) => e.stopPropagation()}
                    />
                    <button
                        className="absolute top-4 right-4 bg-white/10 hover:bg-white/20 rounded-full p-2.5 text-white transition-colors"
                        onClick={() => setFullscreen(false)}
                    >
                        <Icon name="close" className="text-xl" />
                    </button>
                </div>
            )}

            {/* Compile animation section */}
            <div className="pt-3 border-t border-white/5 space-y-3">
                <div className="flex items-center gap-3 flex-wrap">
                    {(() => {
                        const hasNewFrames = !compiledRange || effectiveMax > compiledRange.end;
                        const inCooldown = cooldownRemaining > 0;
                        const canCompile = hasNewFrames && !inCooldown && compileStatus !== "requesting" && isPro;
                        return (
                            <>
                                <button
                                    onClick={() => { handleCompile(); }}
                                    disabled={!canCompile}
                                    title={!isPro ? "Animation compilation is a Pro feature" : ""}
                                    className={`flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-slate-200 font-semibold text-sm hover:bg-white/10 hover:text-white transition-all active:scale-95 disabled:opacity-40 flex-wrap relative ${!isPro ? 'cursor-not-allowed' : ''}`}
                                >
                                    {compileStatus === "requesting" ? (
                                        <>
                                            <Icon name="progress_activity" className="text-base animate-spin" />
                                            Compiling...
                                        </>
                                    ) : compiledRange ? (
                                        <>
                                            <Icon name="refresh" className="text-base" />
                                            Re-compile
                                        </>
                                    ) : (
                                        <>
                                            <Icon name="movie" className="text-base" />
                                            Compile Animation
                                        </>
                                    )}
                                    {!isPro && (
                                        <span className="text-[9px] font-bold uppercase tracking-widest text-primary border border-primary/30 bg-primary/10 px-1.5 py-0.5 rounded ml-1">
                                            Pro Feature
                                        </span>
                                    )}
                                </button>

                                {inCooldown && (
                                    <span className="text-xs text-slate-500">1 min cooldown</span>
                                )}

                                {!hasNewFrames && !inCooldown && compiledRange && !videoUrl && (
                                    <span className="text-xs text-slate-500">Up to date</span>
                                )}
                                {!hasNewFrames && !inCooldown && compiledRange && videoUrl && (
                                    <span className="text-xs text-emerald-500 font-medium">Ready to play</span>
                                )}
                            </>
                        );
                    })()}

                    {compileStatus === "requesting" && (
                        <button
                            onClick={cancelCompile}
                            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 font-semibold text-sm hover:bg-red-500/20 transition-all active:scale-95"
                            title="Cancel compilation"
                        >
                            <Icon name="close" className="text-sm" />
                            Cancel
                        </button>
                    )}

                    {compileStatus === "error" && (
                        <span className="text-xs text-red-400">{compileError || "Compile failed"}</span>
                    )}
                </div>

                {/* Compiled range info */}
                {compiledRange && effectiveMax > compiledRange.end && (
                    <p className="text-xs text-amber-400/80 flex items-center gap-1.5">
                        <Icon name="info" className="text-sm" />
                        More frames available - re-compile to include frames {compiledRange.end + 1}-{effectiveMax}
                    </p>
                )}
            </div>

            {/* Compile confirmation popup */}
            {showCompileConfirm && (
                <div className="p-3 rounded-lg bg-white/5 border border-white/10 space-y-3">
                    <p className="text-sm text-slate-200 font-medium">
                        Compile frames {frameStart}-{effectiveMax} into video?
                    </p>
                    {isRendering && (
                        <p className="text-xs text-amber-400 flex items-center gap-1.5">
                            <Icon name="warning" className="text-sm" />
                            Render is still in progress - more frames will be available later.
                        </p>
                    )}
                    <div className="flex gap-2">
                        <button
                            onClick={confirmCompile}
                            className="px-4 py-1.5 rounded-lg bg-primary/20 border border-primary/30 text-primary font-semibold text-sm hover:bg-primary/30 transition-all"
                        >
                            Compile
                        </button>
                        <button
                            onClick={() => setShowCompileConfirm(false)}
                            className="px-4 py-1.5 rounded-lg bg-white/5 border border-white/10 text-slate-400 text-sm hover:text-white transition-all"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            )}

            {/* Video player */}
            {videoUrl && (
                <div className="relative w-full rounded-lg overflow-hidden border border-white/10 bg-black">
                    <video
                        key={videoUrl}
                        controls
                        playsInline
                        preload="auto"
                        className="w-full"
                        style={{ maxHeight: "400px", minHeight: "200px" }}
                        onError={(e) => {
                            console.error("[video] Playback error:", (e.target as HTMLVideoElement).error);
                        }}
                    >
                        <source src={videoUrl} type="video/mp4" />
                    </video>
                    {compiledRange && (
                        <div className="absolute top-2 left-2 bg-black/70 backdrop-blur-md px-2.5 py-1 rounded text-[10px] font-bold border border-white/10 text-slate-200">
                            Frames {compiledRange.start}-{compiledRange.end}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
