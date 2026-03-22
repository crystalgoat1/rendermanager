import { useState } from "preact/hooks";
import { Icon } from "./Icon";
import type { Job } from "../types";
import {
    FORMATS, COLOR_DEPTHS, DENOISER_OPTIONS, DEVICE_OPTIONS,
    EXR_CODEC_OPTIONS, PIXEL_FILTER_OPTIONS, DENOISING_PREFILTER_OPTIONS,
    DENOISING_INPUT_OPTIONS, TEXTURE_LIMIT_OPTIONS, SHADOW_SIZE_OPTIONS,
    VOLUMETRIC_TILE_OPTIONS, MOTION_BLUR_POSITION_OPTIONS,
    withDefaultMark, FieldLabel, SelectField, NumberField, ToggleField,
    EngineToggle, CollapsibleGroup, getViewTransformOptions, getLookOptions
} from "./RenderSettings";
import { useAgents } from "../hooks/useAgent";

// ── helpers ──────────────────────────────────────────────────────────────────

function formatDuration(ms: number): string {
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    const pad = (n: number) => String(n).padStart(2, "0");
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// ── component ────────────────────────────────────────────────────────────────

interface JobSettingsModalProps {
    job: Job;
    onClose: () => void;
    /** When true, shows a job info header (status, duration, frames, workstation, errors) above the settings. */
    showJobInfo?: boolean;
}

export function JobSettingsModal({ job, onClose, showJobInfo = false }: JobSettingsModalProps) {
    const { agents } = useAgents();
    const [showAdvanced, setShowAdvanced] = useState(false);

    // Active agent for blend info
    const activeAgent = agents.find((a) => a.status !== "offline" && (a.blend_files?.length ?? 0) > 0)
        ?? agents.find((a) => (a.blend_files?.length ?? 0) > 0);
    const blendInfo = activeAgent?.blend_files_info ?? {};
    const currentInfo = job.blend_relpath ? blendInfo[job.blend_relpath] : null;

    // Basic settings
    let engine = "CYCLES";
    const eng = job.render_engine ?? currentInfo?.engine ?? "CYCLES";
    if (eng === "CYCLES") engine = "CYCLES";
    else if (eng === "BLENDER_EEVEE" || eng === "BLENDER_EEVEE_NEXT") engine = "BLENDER_EEVEE";

    const outputFormat = job.output_format ?? currentInfo?.output_format ?? "PNG";
    const frameStep = job.frame_step ?? null;
    const threads = job.threads ?? null;

    // Render Overrides
    const ov = job.render_overrides || {};
    const isCycles = engine === "CYCLES";

    // Output
    const resX = ov.resolution_x ?? null;
    const resY = ov.resolution_y ?? null;
    const resPct = ov.resolution_percentage ?? null;
    const colorDepth = ov.color_depth ?? currentInfo?.color_depth ?? "8";
    const compression = ov.compression ?? null;

    // Film
    const filmTransparent = ov.film_transparent ?? currentInfo?.film_transparent ?? false;
    const filmTransparentGlass = ov.cycles_film_transparent_glass ?? currentInfo?.cycles?.film_transparent_glass ?? false;
    const filmTransparentRoughness = ov.cycles_film_transparent_roughness ?? null;

    // Pixel Filter
    const pixelFilterType = ov.pixel_filter_type ?? currentInfo?.pixel_filter_type ?? null;
    const pixelFilterWidth = ov.pixel_filter_width ?? null;

    // Motion Blur
    const useMotionBlur = ov.use_motion_blur ?? currentInfo?.use_motion_blur ?? false;
    const motionBlurShutter = ov.motion_blur_shutter ?? null;
    const motionBlurPosition = ov.cycles_motion_blur_position ?? currentInfo?.cycles?.motion_blur_position ?? null;

    // Dithering
    const ditherIntensity = ov.dither_intensity ?? null;

    // Cycles Sampling
    const samples = ov.cycles_samples ?? null;
    const useDenoising = ov.cycles_use_denoising ?? currentInfo?.cycles?.use_denoising ?? true;
    const denoiser = ov.cycles_denoiser ?? currentInfo?.cycles?.denoiser ?? "OPENIMAGEDENOISE";
    const device = ov.cycles_device ?? currentInfo?.cycles?.device ?? "CPU";
    const useAdaptiveSampling = ov.cycles_use_adaptive_sampling ?? currentInfo?.cycles?.use_adaptive_sampling ?? true;
    const adaptiveThreshold = ov.cycles_adaptive_threshold ?? null;
    const adaptiveMinSamples = ov.cycles_adaptive_min_samples ?? null;
    const denoisingPrefilter = ov.cycles_denoising_prefilter ?? currentInfo?.cycles?.denoising_prefilter ?? "ACCURATE";
    const denoisingInputPasses = ov.cycles_denoising_input_passes ?? currentInfo?.cycles?.denoising_input_passes ?? "RGB_ALBEDO_NORMAL";
    const denoisingUseGpu = ov.cycles_denoising_use_gpu ?? currentInfo?.cycles?.denoising_use_gpu ?? false;

    // EEVEE
    const eeveeSamples = ov.eevee_taa_render_samples ?? null;
    const eeveeBloom = ov.eevee_use_bloom ?? currentInfo?.eevee?.use_bloom ?? false;
    const eeveeSsr = ov.eevee_use_ssr ?? currentInfo?.eevee?.use_ssr ?? false;
    const eeveeGtao = ov.eevee_use_gtao ?? currentInfo?.eevee?.use_gtao ?? false;
    const eeveeShadowCube = ov.eevee_shadow_cube_size ?? currentInfo?.eevee?.shadow_cube_size ?? "512";
    const eeveeShadowCascade = ov.eevee_shadow_cascade_size ?? currentInfo?.eevee?.shadow_cascade_size ?? "1024";
    const eeveeVolStart = ov.eevee_volumetric_start ?? null;
    const eeveeVolEnd = ov.eevee_volumetric_end ?? null;
    const eeveeVolTile = ov.eevee_volumetric_tile_size ?? currentInfo?.eevee?.volumetric_tile_size ?? "8";
    const eeveeVolSamples = ov.eevee_volumetric_samples ?? null;

    // Light Paths (Cycles)
    const maxBounces = ov.cycles_max_bounces ?? null;
    const diffuseBounces = ov.cycles_diffuse_bounces ?? null;
    const glossyBounces = ov.cycles_glossy_bounces ?? null;
    const transmissionBounces = ov.cycles_transmission_bounces ?? null;
    const volumeBounces = ov.cycles_volume_bounces ?? null;
    const transparentBounces = ov.cycles_transparent_max_bounces ?? null;
    const clampDirect = ov.cycles_sample_clamp_direct ?? null;
    const clampIndirect = ov.cycles_sample_clamp_indirect ?? null;
    const causticReflective = ov.cycles_caustic_reflective ?? currentInfo?.cycles?.caustics_reflective ?? true;
    const causticRefractive = ov.cycles_caustic_refractive ?? currentInfo?.cycles?.caustics_refractive ?? true;
    const blurGlossy = ov.cycles_blur_glossy ?? null;

    // Color Management
    const viewTransform = ov.view_transform ?? null;
    const look = ov.look ?? null;
    const cmExposure = ov.exposure ?? null;
    const cmGamma = ov.gamma ?? null;

    // Simplify
    const useSimplify = ov.use_simplify ?? currentInfo?.simplify?.use_simplify ?? false;
    const simplifySubdivision = ov.simplify_subdivision_render ?? null;
    const simplifyChildParticles = ov.simplify_child_particles_render ?? null;
    const simplifyVolumes = ov.simplify_volumes ?? null;
    const textureLimitRender = ov.texture_limit_render ?? currentInfo?.cycles?.texture_limit_render ?? "OFF";
    const useCameraCull = ov.use_camera_cull ?? currentInfo?.simplify?.use_camera_cull ?? false;
    const cameraCullMargin = ov.camera_cull_margin ?? null;
    const useLightTree = ov.cycles_use_light_tree ?? currentInfo?.cycles?.use_light_tree ?? true;
    const aoBounces = ov.cycles_ao_bounces_render ?? null;

    // Performance
    const compositorDevice = ov.compositor_device ?? currentInfo?.compositor_device ?? null;
    const usePersistentData = ov.cycles_use_persistent_data ?? currentInfo?.cycles?.use_persistent_data ?? false;
    const useAutoTile = ov.cycles_use_auto_tile ?? currentInfo?.cycles?.use_auto_tile ?? true;
    const tileSize = ov.cycles_tile_size ?? null;

    // Render Checks
    const useCompositing = ov.use_compositing;
    const useSequencer = ov.use_sequencer;
    const useBorder = ov.use_border;
    const useStamp = ov.use_stamp;

    // ── Job info header data ──
    const isCompleted = job.status === "completed";
    const isFailed = job.status === "failed" || job.status === "canceled";
    const statusLabel = isCompleted ? "Completed" : job.status === "canceled" ? "Canceled" : job.status === "failed" ? "Failed" : job.status === "in_progress" ? "In Progress" : "Queued";
    const statusClass = isCompleted
        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
        : isFailed
            ? "bg-red-500/10 text-red-400 border-red-500/20"
            : "bg-primary/10 text-primary border-primary/20";

    const endDate = isCompleted && job.completed_at
        ? new Date(job.completed_at)
        : isFailed && job.failed_at
            ? new Date(job.failed_at)
            : null;

    const durationMs = endDate && job.assigned_at
        ? endDate.getTime() - new Date(job.assigned_at).getTime()
        : null;

    const totalFrames = job.frame_end - job.frame_start + 1;
    const renderedFrames = isCompleted
        ? totalFrames
        : job.current_frame != null
            ? Math.min(job.current_frame - job.frame_start + 1, totalFrames)
            : Math.round((job.progress / 100) * totalFrames);

    // Resolve workstation name from agent_id
    const renderAgent = job.agent_id ? agents.find((a) => a.agent_id === job.agent_id) : null;
    const workstationName = renderAgent?.name ?? (job.agent_id ? "Unknown" : "-");

    // no-op for disabled fields
    const noop = () => {};

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-6 pb-[max(1rem,env(safe-area-inset-bottom))] bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
            <div
                className="absolute inset-0"
                onClick={onClose}
            />
            <div className="relative w-full max-w-xl bg-bg-base border border-white/10 rounded-2xl shadow-2xl flex flex-col max-h-[85vh] max-h-[calc(100dvh-4rem)] md:max-h-[90vh]">

                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-bg-surface rounded-t-2xl shrink-0">
                    <div>
                        <h2 className="text-lg font-bold">{showJobInfo ? "Job Details" : "Job Settings"}</h2>
                        <p className="text-xs text-slate-500 mt-0.5 truncate max-w-xs">{job.blend_relpath}</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors"
                    >
                        <Icon name="close" className="text-xl" />
                    </button>
                </div>

                {/* Scrollable Content */}
                <div className="overflow-y-auto p-6 pb-8 sm:pb-6 space-y-5 custom-scrollbar">

                    {/* Job Info Header (only for history / completed/failed jobs) */}
                    {showJobInfo && (
                        <div className="bg-bg-surface rounded-xl p-5 border border-white/5 space-y-4">
                            {/* Status badge */}
                            <div className="flex items-center justify-between">
                                <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold border ${statusClass}`}>
                                    {statusLabel}
                                </span>
                                {endDate && (
                                    <span className="text-xs text-slate-500">
                                        {endDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                                        {" · "}
                                        {endDate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
                                    </span>
                                )}
                            </div>

                            {/* Info grid */}
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Duration</p>
                                    <p className="text-sm font-medium mt-0.5">{durationMs != null ? formatDuration(durationMs) : "-"}</p>
                                </div>
                                <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Frames Rendered</p>
                                    <p className="text-sm font-medium mt-0.5">{renderedFrames} / {totalFrames}</p>
                                </div>
                                <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Workstation</p>
                                    <p className="text-sm font-medium mt-0.5">{workstationName}</p>
                                </div>
                                <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Progress</p>
                                    <p className="text-sm font-medium mt-0.5">{job.progress}%</p>
                                </div>
                            </div>

                            {/* Error details */}
                            {isFailed && job.fail_reason && (
                                <div className="bg-red-500/5 border border-red-500/10 rounded-lg p-3">
                                    <p className="text-[10px] uppercase tracking-wider text-red-400 font-bold mb-1">Error Details</p>
                                    <p className="text-sm text-red-400 break-words whitespace-pre-wrap">{job.fail_reason}</p>
                                </div>
                            )}

                            {/* VRAM Recovery info */}
                            {job.vram_recovery && job.vram_recovery.recovered_frames > 0 && (
                                <div className="bg-amber-500/5 border border-amber-500/10 rounded-lg p-3">
                                    <p className="text-[10px] uppercase tracking-wider text-amber-400 font-bold mb-1">VRAM Recovery</p>
                                    <p className="text-sm text-amber-300">
                                        {job.vram_recovery.recovered_frames} frame{job.vram_recovery.recovered_frames !== 1 ? "s" : ""} recovered
                                        {job.vram_recovery.max_tier_name && (
                                            <span className="text-amber-400/70"> · max recovery: {job.vram_recovery.max_tier_name}</span>
                                        )}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Engine + Frame range */}
                    <div className="bg-bg-surface rounded-xl p-5 border border-white/5 space-y-4">
                        <EngineToggle value={engine} onChange={noop} disabled={true} />
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <FieldLabel label="Start Frame" />
                                <NumberField value={job.frame_start} onChange={noop} disabled={true} />
                            </div>
                            <div>
                                <FieldLabel label="End Frame" />
                                <NumberField value={job.frame_end} onChange={noop} disabled={true} />
                            </div>
                        </div>
                    </div>

                    {/* Output format */}
                    <div className="bg-bg-surface rounded-xl p-5 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Output</h2>
                        <div>
                            <FieldLabel label="Output Format" />
                            <SelectField value={outputFormat} onChange={noop} options={withDefaultMark(FORMATS, currentInfo?.output_format)} disabled={true} />
                        </div>
                    </div>

                    {/* Advanced settings */}
                    <div className="bg-bg-surface rounded-xl border border-white/5 overflow-hidden">
                        <button
                            type="button"
                            onClick={() => setShowAdvanced(!showAdvanced)}
                            className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-white/[0.02] transition-colors"
                        >
                            <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Advanced Settings</span>
                            <Icon
                                name={showAdvanced ? "expand_less" : "expand_more"}
                                className="text-lg text-slate-500 shrink-0"
                            />
                        </button>

                        {showAdvanced && (
                            <div className="px-5 pb-5 space-y-3 border-t border-white/5 pt-4">
                                {Object.keys(ov).length === 0 && !frameStep && !threads ? (
                                    <p className="text-sm text-slate-500 py-4 text-center">No overrides - using blend file defaults</p>
                                ) : (
                                    <>
                                        {/* ── Output ── */}
                                        <CollapsibleGroup title="Output" defaultOpen>
                                            <div className="grid grid-cols-3 gap-3">
                                                <div><FieldLabel label="Width" /><NumberField value={resX} onChange={noop} placeholder={currentInfo ? `${currentInfo.resolution_x}` : "1920"} disabled /></div>
                                                <div><FieldLabel label="Height" /><NumberField value={resY} onChange={noop} placeholder={currentInfo ? `${currentInfo.resolution_y}` : "1080"} disabled /></div>
                                                <div><FieldLabel label="Scale %" /><NumberField value={resPct} onChange={noop} placeholder={currentInfo ? `${currentInfo.resolution_percentage}` : "100"} disabled /></div>
                                            </div>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div><FieldLabel label="Color Depth" /><SelectField value={colorDepth} onChange={noop} options={withDefaultMark(COLOR_DEPTHS, currentInfo?.color_depth)} disabled /></div>
                                                <div><FieldLabel label="Compression" /><NumberField value={compression} onChange={noop} placeholder={currentInfo ? `${currentInfo.compression}` : "15"} disabled /></div>
                                            </div>
                                            {ov.exr_codec && (
                                                <div><FieldLabel label="EXR Codec" /><SelectField value={ov.exr_codec} onChange={noop} options={EXR_CODEC_OPTIONS as any} disabled /></div>
                                            )}
                                            {ditherIntensity !== null && (
                                                <div><FieldLabel label="Dithering" /><NumberField value={ditherIntensity} onChange={noop} disabled /></div>
                                            )}
                                        </CollapsibleGroup>

                                        {/* ── Sampling (Cycles) ── */}
                                        {isCycles && (
                                            <CollapsibleGroup title="Sampling" defaultOpen>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Samples" /><NumberField value={samples} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.samples}` : "128"} disabled /></div>
                                                    <div><FieldLabel label="Device" /><SelectField value={device} onChange={noop} options={withDefaultMark(DEVICE_OPTIONS, currentInfo?.cycles?.device)} disabled /></div>
                                                </div>
                                                <ToggleField label="Adaptive Sampling" value={useAdaptiveSampling} onChange={noop} blendDefault={currentInfo?.cycles?.use_adaptive_sampling} disabled />
                                                {useAdaptiveSampling && (
                                                    <div className="grid grid-cols-2 gap-3">
                                                        <div><FieldLabel label="Noise Threshold" /><NumberField value={adaptiveThreshold} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.adaptive_threshold}` : "0.01"} disabled /></div>
                                                        <div><FieldLabel label="Min Samples" /><NumberField value={adaptiveMinSamples} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.adaptive_min_samples}` : "0"} disabled /></div>
                                                    </div>
                                                )}
                                                <ToggleField label="Denoising" value={useDenoising} onChange={noop} blendDefault={currentInfo?.cycles?.use_denoising} disabled />
                                                {useDenoising && (
                                                    <>
                                                        <div className="grid grid-cols-2 gap-3">
                                                            <div><FieldLabel label="Denoiser" /><SelectField value={denoiser} onChange={noop} options={withDefaultMark(DENOISER_OPTIONS, currentInfo?.cycles?.denoiser)} disabled /></div>
                                                            <div><FieldLabel label="Prefilter" /><SelectField value={denoisingPrefilter} onChange={noop} options={withDefaultMark(DENOISING_PREFILTER_OPTIONS, currentInfo?.cycles?.denoising_prefilter)} disabled /></div>
                                                        </div>
                                                        <div><FieldLabel label="Input Passes" /><SelectField value={denoisingInputPasses} onChange={noop} options={withDefaultMark(DENOISING_INPUT_OPTIONS, currentInfo?.cycles?.denoising_input_passes)} disabled /></div>
                                                        {denoiser === "OPENIMAGEDENOISE" && (
                                                            <ToggleField label="Denoise on GPU" value={denoisingUseGpu} onChange={noop} blendDefault={currentInfo?.cycles?.denoising_use_gpu} disabled />
                                                        )}
                                                    </>
                                                )}
                                            </CollapsibleGroup>
                                        )}

                                        {/* ── EEVEE ── */}
                                        {!isCycles && (
                                            <CollapsibleGroup title="EEVEE" defaultOpen>
                                                <div><FieldLabel label="Render Samples" /><NumberField value={eeveeSamples} onChange={noop} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.taa_render_samples}` : "64"} disabled /></div>
                                                <div className="grid grid-cols-3 gap-3">
                                                    <ToggleField label="Bloom" value={eeveeBloom} onChange={noop} blendDefault={currentInfo?.eevee?.use_bloom} disabled />
                                                    <ToggleField label="SSR" value={eeveeSsr} onChange={noop} blendDefault={currentInfo?.eevee?.use_ssr} disabled />
                                                    <ToggleField label="AO" value={eeveeGtao} onChange={noop} blendDefault={currentInfo?.eevee?.use_gtao} disabled />
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Shadow Cube Size" /><SelectField value={eeveeShadowCube} onChange={noop} options={withDefaultMark(SHADOW_SIZE_OPTIONS, currentInfo?.eevee?.shadow_cube_size)} disabled /></div>
                                                    <div><FieldLabel label="Shadow Cascade Size" /><SelectField value={eeveeShadowCascade} onChange={noop} options={withDefaultMark(SHADOW_SIZE_OPTIONS, currentInfo?.eevee?.shadow_cascade_size)} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Volumetric Start" /><NumberField value={eeveeVolStart} onChange={noop} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_start}` : "0.1"} disabled /></div>
                                                    <div><FieldLabel label="Volumetric End" /><NumberField value={eeveeVolEnd} onChange={noop} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_end}` : "100"} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Volumetric Tile Size" /><SelectField value={eeveeVolTile} onChange={noop} options={withDefaultMark(VOLUMETRIC_TILE_OPTIONS, currentInfo?.eevee?.volumetric_tile_size)} disabled /></div>
                                                    <div><FieldLabel label="Volumetric Samples" /><NumberField value={eeveeVolSamples} onChange={noop} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_samples}` : "64"} disabled /></div>
                                                </div>
                                            </CollapsibleGroup>
                                        )}

                                        {/* ── Light Paths (Cycles) ── */}
                                        {isCycles && (
                                            <CollapsibleGroup title="Light Paths">
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Max Bounces" /><NumberField value={maxBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.max_bounces}` : "12"} disabled /></div>
                                                    <div><FieldLabel label="Diffuse" /><NumberField value={diffuseBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.diffuse_bounces}` : "4"} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Glossy" /><NumberField value={glossyBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.glossy_bounces}` : "4"} disabled /></div>
                                                    <div><FieldLabel label="Transmission" /><NumberField value={transmissionBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.transmission_bounces}` : "12"} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Volume" /><NumberField value={volumeBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.volume_bounces}` : "0"} disabled /></div>
                                                    <div><FieldLabel label="Transparent" /><NumberField value={transparentBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.transparent_max_bounces}` : "8"} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Clamp Direct" /><NumberField value={clampDirect} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.sample_clamp_direct}` : "0"} disabled /></div>
                                                    <div><FieldLabel label="Clamp Indirect" /><NumberField value={clampIndirect} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.sample_clamp_indirect}` : "10"} disabled /></div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <ToggleField label="Caustics Reflective" value={causticReflective} onChange={noop} blendDefault={currentInfo?.cycles?.caustics_reflective} disabled />
                                                    <ToggleField label="Caustics Refractive" value={causticRefractive} onChange={noop} blendDefault={currentInfo?.cycles?.caustics_refractive} disabled />
                                                </div>
                                                <div><FieldLabel label="Filter Glossy" /><NumberField value={blurGlossy} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.blur_glossy}` : "1.0"} disabled /></div>
                                            </CollapsibleGroup>
                                        )}

                                        {/* ── Film & Motion Blur ── */}
                                        <CollapsibleGroup title="Film & Motion Blur">
                                            <ToggleField label="Film Transparent" value={filmTransparent} onChange={noop} blendDefault={currentInfo?.film_transparent} disabled />
                                            {filmTransparent && isCycles && (
                                                <>
                                                    <ToggleField label="Transparent Glass" value={filmTransparentGlass} onChange={noop} blendDefault={currentInfo?.cycles?.film_transparent_glass} disabled />
                                                    {filmTransparentGlass && filmTransparentRoughness !== null && (
                                                        <div><FieldLabel label="Roughness Threshold" /><NumberField value={filmTransparentRoughness} onChange={noop} disabled /></div>
                                                    )}
                                                </>
                                            )}
                                            {pixelFilterType && (
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Pixel Filter" /><SelectField value={pixelFilterType} onChange={noop} options={withDefaultMark(PIXEL_FILTER_OPTIONS, currentInfo?.pixel_filter_type)} disabled /></div>
                                                    <div><FieldLabel label="Filter Width" /><NumberField value={pixelFilterWidth} onChange={noop} placeholder={currentInfo ? `${currentInfo.pixel_filter_width}` : "1.5"} disabled /></div>
                                                </div>
                                            )}
                                            <ToggleField label="Motion Blur" value={useMotionBlur} onChange={noop} blendDefault={currentInfo?.use_motion_blur} disabled />
                                            {useMotionBlur && (
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div><FieldLabel label="Shutter" /><NumberField value={motionBlurShutter} onChange={noop} placeholder={currentInfo ? `${currentInfo.motion_blur_shutter}` : "0.5"} disabled /></div>
                                                    {isCycles && motionBlurPosition && (
                                                        <div><FieldLabel label="Position" /><SelectField value={motionBlurPosition} onChange={noop} options={withDefaultMark(MOTION_BLUR_POSITION_OPTIONS, currentInfo?.cycles?.motion_blur_position)} disabled /></div>
                                                    )}
                                                </div>
                                            )}
                                        </CollapsibleGroup>

                                        {/* ── Performance ── */}
                                        <CollapsibleGroup title="Performance">
                                            {isCycles && (
                                                <>
                                                    <ToggleField label="Persistent Data" value={usePersistentData} onChange={noop} blendDefault={currentInfo?.cycles?.use_persistent_data} disabled />
                                                    <ToggleField label="Use Tiling" value={useAutoTile} onChange={noop} blendDefault={currentInfo?.cycles?.use_auto_tile} disabled />
                                                    {useAutoTile && tileSize !== null && (
                                                        <div><FieldLabel label="Tile Size" /><NumberField value={tileSize} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.tile_size}` : "2048"} disabled /></div>
                                                    )}
                                                </>
                                            )}
                                            <div><FieldLabel label="Compositor Device" /><SelectField value={compositorDevice ?? "CPU"} onChange={noop} options={withDefaultMark(DEVICE_OPTIONS, currentInfo?.compositor_device)} disabled /></div>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div><FieldLabel label="Frame Step" /><NumberField value={frameStep} onChange={noop} placeholder={currentInfo?.frame_step ? `${currentInfo.frame_step}` : "1"} disabled /></div>
                                                <div><FieldLabel label="CPU Threads" /><NumberField value={threads} onChange={noop} placeholder="0 (auto)" disabled /></div>
                                            </div>
                                        </CollapsibleGroup>

                                        {/* ── Color Management ── */}
                                        <CollapsibleGroup title="Color Management">
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <FieldLabel label="View Transform" />
                                                    <SelectField
                                                        value={viewTransform ?? currentInfo?.color_management?.view_transform ?? "Filmic"}
                                                        onChange={noop}
                                                        options={getViewTransformOptions(currentInfo?.color_management?.available_view_transforms, currentInfo?.color_management?.view_transform)}
                                                        disabled
                                                    />
                                                </div>
                                                <div>
                                                    <FieldLabel label="Look" />
                                                    <SelectField
                                                        value={look ?? currentInfo?.color_management?.look ?? "None"}
                                                        onChange={noop}
                                                        options={getLookOptions(currentInfo?.color_management?.available_looks, currentInfo?.color_management?.look)}
                                                        disabled
                                                    />
                                                </div>
                                            </div>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div><FieldLabel label="Exposure" /><NumberField value={cmExposure} onChange={noop} placeholder={currentInfo?.color_management ? `${currentInfo.color_management.exposure}` : "0"} disabled /></div>
                                                <div><FieldLabel label="Gamma" /><NumberField value={cmGamma} onChange={noop} placeholder={currentInfo?.color_management ? `${currentInfo.color_management.gamma}` : "1.0"} disabled /></div>
                                            </div>
                                        </CollapsibleGroup>

                                        {/* ── Simplify ── */}
                                        <CollapsibleGroup title="Simplify">
                                            <ToggleField label="Enable Simplify" value={useSimplify} onChange={noop} blendDefault={currentInfo?.simplify?.use_simplify} disabled />
                                            {useSimplify && (
                                                <>
                                                    <div className="grid grid-cols-2 gap-3">
                                                        <div><FieldLabel label="Max Subdivision" /><NumberField value={simplifySubdivision} onChange={noop} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_subdivision_render}` : "6"} disabled /></div>
                                                        <div><FieldLabel label="Child Particles" /><NumberField value={simplifyChildParticles} onChange={noop} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_child_particles_render}` : "1.0"} disabled /></div>
                                                    </div>
                                                    <div><FieldLabel label="Volume Resolution" /><NumberField value={simplifyVolumes} onChange={noop} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_volumes}` : "1.0"} disabled /></div>
                                                    {isCycles && (
                                                        <div><FieldLabel label="Texture Limit" /><SelectField value={textureLimitRender} onChange={noop} options={withDefaultMark(TEXTURE_LIMIT_OPTIONS, currentInfo?.cycles?.texture_limit_render)} disabled /></div>
                                                    )}
                                                    <ToggleField label="Camera Culling" value={useCameraCull} onChange={noop} blendDefault={currentInfo?.simplify?.use_camera_cull} disabled />
                                                    {useCameraCull && cameraCullMargin !== null && (
                                                        <div><FieldLabel label="Cull Margin" /><NumberField value={cameraCullMargin} onChange={noop} disabled /></div>
                                                    )}
                                                    {isCycles && (
                                                        <>
                                                            <ToggleField label="Light Tree" value={useLightTree} onChange={noop} blendDefault={currentInfo?.cycles?.use_light_tree} disabled />
                                                            <div><FieldLabel label="AO Bounces (Approx)" /><NumberField value={aoBounces} onChange={noop} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.ao_bounces_render}` : "0"} disabled /></div>
                                                        </>
                                                    )}
                                                </>
                                            )}
                                        </CollapsibleGroup>

                                        {/* ── Render Checks ── */}
                                        {(useCompositing !== undefined || useBorder !== undefined || useStamp !== undefined || useSequencer !== undefined) && (
                                            <CollapsibleGroup title="Render Checks" variant="warning">
                                                <div className="grid grid-cols-2 gap-3">
                                                    {useCompositing !== undefined && <ToggleField label="Compositing" value={useCompositing} onChange={noop} disabled />}
                                                    {useSequencer !== undefined && <ToggleField label="Sequencer" value={useSequencer} onChange={noop} disabled />}
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    {useBorder !== undefined && <ToggleField label="Border Render" value={useBorder} onChange={noop} disabled />}
                                                    {useStamp !== undefined && <ToggleField label="Stamp" value={useStamp} onChange={noop} disabled />}
                                                </div>
                                            </CollapsibleGroup>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
