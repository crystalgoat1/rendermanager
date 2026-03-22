import { useState, useEffect, useRef } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { useApi } from "../hooks/useApi";
import { useAgents } from "../hooks/useAgent";
import { useJobs } from "../hooks/useJobs";
import { APP_DISPLAY_NAME } from "../brand";
import { useProfile } from "../hooks/useProfile";
import { Icon } from "../components/Icon";
import type { BlendFileInfo, RenderOverrides } from "../types";
import {
  FORMATS, COLOR_DEPTHS, DENOISER_OPTIONS, DEVICE_OPTIONS,
  EXR_CODEC_OPTIONS, PIXEL_FILTER_OPTIONS, DENOISING_PREFILTER_OPTIONS,
  DENOISING_INPUT_OPTIONS, TEXTURE_LIMIT_OPTIONS, SHADOW_SIZE_OPTIONS,
  VOLUMETRIC_TILE_OPTIONS, MOTION_BLUR_POSITION_OPTIONS,
  withDefaultMark, FieldLabel, SelectField, NumberField, ToggleField,
  EngineToggle, PassSelectionList, CollapsibleGroup, validateNumericFields,
  getViewTransformOptions, getLookOptions
} from "../components/RenderSettings";

// ─── New job page ────────────────────────────────────────────────────────────

export function NewJobPage() {
  const { apiJson } = useApi();
  const { agents } = useAgents();
  const { jobs } = useJobs();
  const { profile, setActiveAgent } = useProfile();
  const [, navigate] = useLocation();

  const isPro = profile?.tier === "pro";

  const [blendRelpath, setBlendRelpath] = useState("");
  const [frameStart, setFrameStart] = useState(1);
  const [frameEnd, setFrameEnd] = useState(250);

  // Engine (basic setting — always visible)
  const [engine, setEngine] = useState("CYCLES");
  // Output format (basic)
  const [outputFormat, setOutputFormat] = useState("PNG");
  // Frame step and threads (basic)
  const [frameStep, setFrameStep] = useState<number | null>(null);
  const [threads, setThreads] = useState<number | null>(null);

  // Advanced override settings — null/empty = use blend default (shown as placeholder)
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [resX, setResX] = useState<number | null>(null);
  const [resY, setResY] = useState<number | null>(null);
  const [resPct, setResPct] = useState<number | null>(null);
  const [colorDepth, setColorDepth] = useState("8");
  const [compression, setCompression] = useState<number | null>(null);
  const [filmTransparent, setFilmTransparent] = useState(false);
  const [activeCamera, setActiveCamera] = useState<string | null>(null);
  const [selectedPasses, setSelectedPasses] = useState<string[] | null>(null);

  // Output
  const [exrCodec, setExrCodec] = useState("ZIP");

  // Film & Motion Blur
  const [pixelFilterType, setPixelFilterType] = useState<string | null>(null);
  const [pixelFilterWidth, setPixelFilterWidth] = useState<number | null>(null);
  const [useMotionBlur, setUseMotionBlur] = useState(false);
  const [motionBlurShutter, setMotionBlurShutter] = useState<number | null>(null);

  // Render Safety
  const [useCompositing, setUseCompositing] = useState(true);
  const [useSequencer, setUseSequencer] = useState(true);
  const [ditherIntensity, setDitherIntensity] = useState<number | null>(null);
  const [useBorder, setUseBorder] = useState(false);
  const [useCropToBorder, setUseCropToBorder] = useState(false);
  const [useLockInterface, setUseLockInterface] = useState(false);
  const [useStamp, setUseStamp] = useState(false);
  const [useOverwrite, setUseOverwrite] = useState(true);
  const [usePlaceholder, setUsePlaceholder] = useState(false);

  // Color Management
  const [viewTransform, setViewTransform] = useState<string | null>(null);
  const [look, setLook] = useState<string | null>(null);
  const [cmExposure, setCmExposure] = useState<number | null>(null);
  const [cmGamma, setCmGamma] = useState<number | null>(null);

  // Simplify
  const [useSimplify, setUseSimplify] = useState(false);
  const [simplifySubdivision, setSimplifySubdivision] = useState<number | null>(null);
  const [simplifyChildParticles, setSimplifyChildParticles] = useState<number | null>(null);
  const [simplifyVolumes, setSimplifyVolumes] = useState<number | null>(null);
  const [useCameraCull, setUseCameraCull] = useState(false);
  const [cameraCullMargin, setCameraCullMargin] = useState<number | null>(null);

  // Performance
  const [compositorDevice, setCompositorDevice] = useState("CPU");

  // Cycles-specific
  const [samples, setSamples] = useState<number | null>(null);
  const [useDenoising, setUseDenoising] = useState(true);
  const [denoiser, setDenoiser] = useState("OPENIMAGEDENOISE");
  const [device, setDevice] = useState("CPU");
  const [maxBounces, setMaxBounces] = useState<number | null>(null);
  const [useAdaptiveSampling, setUseAdaptiveSampling] = useState(true);
  const [adaptiveThreshold, setAdaptiveThreshold] = useState<number | null>(null);
  const [adaptiveMinSamples, setAdaptiveMinSamples] = useState<number | null>(null);
  const [denoisingPrefilter, setDenoisingPrefilter] = useState("ACCURATE");
  const [denoisingInputPasses, setDenoisingInputPasses] = useState("RGB_ALBEDO_NORMAL");
  const [denoisingUseGpu, setDenoisingUseGpu] = useState(false);

  // Cycles Light Paths
  const [diffuseBounces, setDiffuseBounces] = useState<number | null>(null);
  const [glossyBounces, setGlossyBounces] = useState<number | null>(null);
  const [transmissionBounces, setTransmissionBounces] = useState<number | null>(null);
  const [volumeBounces, setVolumeBounces] = useState<number | null>(null);
  const [transparentBounces, setTransparentBounces] = useState<number | null>(null);
  const [clampDirect, setClampDirect] = useState<number | null>(null);
  const [clampIndirect, setClampIndirect] = useState<number | null>(null);
  const [causticReflective, setCausticReflective] = useState(true);
  const [causticRefractive, setCausticRefractive] = useState(true);
  const [blurGlossy, setBlurGlossy] = useState<number | null>(null);

  // Cycles Film
  const [filmTransparentGlass, setFilmTransparentGlass] = useState(false);
  const [filmTransparentRoughness, setFilmTransparentRoughness] = useState<number | null>(null);
  const [motionBlurPosition, setMotionBlurPosition] = useState("CENTER");

  // Cycles Performance
  const [usePersistentData, setUsePersistentData] = useState(false);
  const [useAutoTile, setUseAutoTile] = useState(true);
  const [tileSize, setTileSize] = useState<number | null>(null);

  // Cycles Simplify GI
  const [useLightTree, setUseLightTree] = useState(true);
  const [aoBounces, setAoBounces] = useState<number | null>(null);
  const [textureLimitRender, setTextureLimitRender] = useState("OFF");

  // EEVEE-specific
  const [eeveeSamples, setEeveeSamples] = useState<number | null>(null);
  const [eeveeBloom, setEeveeBloom] = useState(false);
  const [eeveeSsr, setEeveeSsr] = useState(false);
  const [eeveeGtao, setEeveeGtao] = useState(false);
  const [eeveeShadowCube, setEeveeShadowCube] = useState("512");
  const [eeveeShadowCascade, setEeveeShadowCascade] = useState("1024");
  const [eeveeVolStart, setEeveeVolStart] = useState<number | null>(null);
  const [eeveeVolEnd, setEeveeVolEnd] = useState<number | null>(null);
  const [eeveeVolTile, setEeveeVolTile] = useState("8");
  const [eeveeVolSamples, setEeveeVolSamples] = useState<number | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prefillMissingFile, setPrefillMissingFile] = useState<string | null>(null);

  // ── "Render Again" pre-fill from history ──────────────────────────────────
  const prefillApplied = useRef(false);
  const fromJobId = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("from")
    : null;

  // Use the active agent from profile, or fall back to first agent with blend files
  const activeAgentId = profile?.active_agent_id;
  const activeAgent = activeAgentId
    ? agents.find((a) => a.agent_id === activeAgentId)
    : agents.find((a) => a.status !== "offline" && (a.blend_files?.length ?? 0) > 0)
    ?? agents.find((a) => (a.blend_files?.length ?? 0) > 0);

  const blendFiles = activeAgent?.blend_files ?? [];

  // Blend file info — comes directly with agent data via Supabase
  const blendInfo: Record<string, BlendFileInfo> = activeAgent?.blend_files_info ?? {};

  // Track which agent we last auto-selected a blend file for, so polling/realtime
  // updates don't keep re-triggering the auto-select and resetting all settings.
  const lastAutoSelectedAgentRef = useRef<string | null>(null);

  useEffect(() => {
    const agentId = activeAgent?.agent_id ?? null;
    // Only auto-select when:
    // 1. There are blend files available
    // 2. No file is currently selected OR we switched to a different agent
    const switchedAgent = agentId !== lastAutoSelectedAgentRef.current;
    if (blendFiles.length > 0 && (!blendRelpath || switchedAgent)) {
      setBlendRelpath(blendFiles[0]);
      lastAutoSelectedAgentRef.current = agentId;
    }
  }, [activeAgent?.agent_id, blendFiles.length]); // stable deps — not the array ref

  // Look up info for the currently selected file.
  // Stabilize: keep the last valid info so realtime heartbeat updates
  // (which may arrive with blend_files_info = null) don't flash placeholders
  // back to hardcoded defaults.
  const liveInfo = blendRelpath ? blendInfo[blendRelpath] : null;
  const stableInfoRef = useRef<BlendFileInfo | null>(null);
  const stableInfoFileRef = useRef("");
  if (!blendRelpath) {
    stableInfoRef.current = null;
    stableInfoFileRef.current = "";
  } else if (blendRelpath !== stableInfoFileRef.current && liveInfo) {
    // File selection changed and info is available — snapshot it
    stableInfoRef.current = liveInfo;
    stableInfoFileRef.current = blendRelpath;
  } else if (blendRelpath === stableInfoFileRef.current && liveInfo) {
    // Same file, fresh data arrived — update snapshot
    stableInfoRef.current = liveInfo;
  }
  // else: same file but liveInfo is null (stale heartbeat) — keep previous snapshot
  const currentInfo = stableInfoRef.current;

  // Reset all overrides to empty (= use blend defaults)
  function resetOverrides() {
    setResX(null); setResY(null); setResPct(null);
    setCompression(null); setFilmTransparent(false);
    setFrameStep(null); setThreads(null);
    setActiveCamera(null); setSelectedPasses(null);

    // Output
    setExrCodec(currentInfo?.exr_codec || "ZIP");

    // Film & Motion Blur
    setPixelFilterType(null); setPixelFilterWidth(null);
    setUseMotionBlur(currentInfo?.use_motion_blur ?? false);
    setMotionBlurShutter(null);

    // Render Safety
    setUseCompositing(currentInfo?.use_compositing ?? true);
    setUseSequencer(currentInfo?.use_sequencer ?? true);
    setDitherIntensity(null);
    setUseBorder(currentInfo?.use_border ?? false);
    setUseCropToBorder(currentInfo?.use_crop_to_border ?? false);
    setUseLockInterface(currentInfo?.use_lock_interface ?? false);
    setUseStamp(currentInfo?.use_stamp ?? false);
    setUseOverwrite(currentInfo?.use_overwrite ?? true);
    setUsePlaceholder(currentInfo?.use_placeholder ?? false);

    // Color Management
    setViewTransform(null); setLook(null);
    setCmExposure(null); setCmGamma(null);

    // Simplify
    setUseSimplify(currentInfo?.simplify?.use_simplify ?? false);
    setSimplifySubdivision(null); setSimplifyChildParticles(null);
    setSimplifyVolumes(null); setUseCameraCull(false); setCameraCullMargin(null);

    // Performance
    setCompositorDevice(currentInfo?.compositor_device || "CPU");

    // Cycles
    setSamples(null); setUseDenoising(true); setMaxBounces(null);
    setUseAdaptiveSampling(true); setAdaptiveThreshold(null); setAdaptiveMinSamples(null);
    setDenoisingPrefilter("ACCURATE"); setDenoisingInputPasses("RGB_ALBEDO_NORMAL"); setDenoisingUseGpu(false);
    setDiffuseBounces(null); setGlossyBounces(null); setTransmissionBounces(null);
    setVolumeBounces(null); setTransparentBounces(null);
    setClampDirect(null); setClampIndirect(null);
    setCausticReflective(true); setCausticRefractive(true); setBlurGlossy(null);
    setFilmTransparentGlass(false); setFilmTransparentRoughness(null);
    setMotionBlurPosition("CENTER");
    setUsePersistentData(false); setUseAutoTile(true); setTileSize(null);
    setUseLightTree(true); setAoBounces(null); setTextureLimitRender("OFF");
    setEeveeSamples(null); setEeveeBloom(false); setEeveeSsr(false); setEeveeGtao(false);
    setEeveeShadowCube("512"); setEeveeShadowCascade("1024");
    setEeveeVolStart(null); setEeveeVolEnd(null); setEeveeVolTile("8"); setEeveeVolSamples(null);

    // Restore dropdowns + engine from blend file
    if (currentInfo) {
      setOutputFormat(currentInfo.output_format || "PNG");
      setColorDepth(currentInfo.color_depth || "8");
      setDenoiser(currentInfo.cycles?.denoiser || "OPENIMAGEDENOISE");
      setDevice(currentInfo.cycles?.device || "CPU");
      if (currentInfo.engine === "CYCLES") setEngine("CYCLES");
      else if (currentInfo.engine === "BLENDER_EEVEE" || currentInfo.engine === "BLENDER_EEVEE_NEXT") setEngine("BLENDER_EEVEE");
    } else {
      setOutputFormat("PNG"); setColorDepth("8");
      setDenoiser("OPENIMAGEDENOISE"); setDevice("CPU");
    }
  }

  // Run on file selection change AND when blend info first becomes available
  // (e.g. newly added files whose metadata arrives after the scan completes)
  const hasInfoForSelected = blendRelpath ? !!blendInfo[blendRelpath] : false;
  useEffect(() => {
    const info = blendRelpath ? blendInfo[blendRelpath] : null;
    if (!info) return;

    // Set frame range and engine from blend file
    setFrameStart(info.frame_start);
    setFrameEnd(info.frame_end);

    if (info.engine === "CYCLES") setEngine("CYCLES");
    else if (info.engine === "BLENDER_EEVEE" || info.engine === "BLENDER_EEVEE_NEXT") setEngine("BLENDER_EEVEE");
    else setEngine("CYCLES");

    // Pre-fill settings from blend file (dropdowns get actual values, overrides stay null)
    setOutputFormat(info.output_format || "PNG");
    setColorDepth(info.color_depth || "8");
    setExrCodec(info.exr_codec || "ZIP");
    setResX(null); setResY(null); setResPct(null);
    setCompression(null);
    setFilmTransparent(info.film_transparent ?? false);
    setFrameStep(null); setThreads(null);
    setActiveCamera(null);
    setSelectedPasses(info.active_passes || null);

    // Film & Motion Blur
    setPixelFilterType(null); setPixelFilterWidth(null);
    setUseMotionBlur(info.use_motion_blur ?? false);
    setMotionBlurShutter(null);

    // Render Safety
    setUseCompositing(info.use_compositing ?? true);
    setUseSequencer(info.use_sequencer ?? true);
    setDitherIntensity(null);
    setUseBorder(info.use_border ?? false);
    setUseCropToBorder(info.use_crop_to_border ?? false);
    setUseLockInterface(info.use_lock_interface ?? false);
    setUseStamp(info.use_stamp ?? false);
    setUseOverwrite(info.use_overwrite ?? true);
    setUsePlaceholder(info.use_placeholder ?? false);

    // Color Management
    setViewTransform(null); setLook(null); setCmExposure(null); setCmGamma(null);

    // Simplify
    setUseSimplify(info.simplify?.use_simplify ?? false);
    setSimplifySubdivision(null); setSimplifyChildParticles(null);
    setSimplifyVolumes(null);
    setUseCameraCull(info.simplify?.use_camera_cull ?? false);
    setCameraCullMargin(null);

    // Performance
    setCompositorDevice(info.compositor_device || "CPU");

    // Engine-specific pre-fill
    if (info.cycles) {
      setSamples(null); setMaxBounces(null);
      setDenoiser(info.cycles.denoiser || "OPENIMAGEDENOISE");
      setDevice(info.cycles.device || "CPU");
      setUseDenoising(info.cycles.use_denoising ?? true);
      setUseAdaptiveSampling(info.cycles.use_adaptive_sampling ?? true);
      setAdaptiveThreshold(null); setAdaptiveMinSamples(null);
      setDenoisingPrefilter(info.cycles.denoising_prefilter || "ACCURATE");
      setDenoisingInputPasses(info.cycles.denoising_input_passes || "RGB_ALBEDO_NORMAL");
      setDenoisingUseGpu(info.cycles.denoising_use_gpu ?? false);

      // Light Paths
      setDiffuseBounces(null); setGlossyBounces(null); setTransmissionBounces(null);
      setVolumeBounces(null); setTransparentBounces(null);
      setClampDirect(null); setClampIndirect(null);
      setCausticReflective(info.cycles.caustics_reflective ?? true);
      setCausticRefractive(info.cycles.caustics_refractive ?? true);
      setBlurGlossy(null);

      // Film
      setFilmTransparentGlass(info.cycles.film_transparent_glass ?? false);
      setFilmTransparentRoughness(null);
      setMotionBlurPosition(info.cycles.motion_blur_position || "CENTER");

      // Performance
      setUsePersistentData(info.cycles.use_persistent_data ?? false);
      setUseAutoTile(info.cycles.use_auto_tile ?? true);
      setTileSize(null);

      // Simplify GI
      setUseLightTree(info.cycles.use_light_tree ?? true);
      setAoBounces(null);
      setTextureLimitRender(info.cycles.texture_limit_render || "OFF");
    } else {
      setSamples(null); setUseDenoising(true);
      setDenoiser("OPENIMAGEDENOISE"); setDevice("CPU"); setMaxBounces(null);
    }

    if (info.eevee) {
      setEeveeSamples(null);
      setEeveeBloom(info.eevee.use_bloom ?? false);
      setEeveeSsr(info.eevee.use_ssr ?? false);
      setEeveeGtao(info.eevee.use_gtao ?? false);
      setEeveeShadowCube(info.eevee.shadow_cube_size || "512");
      setEeveeShadowCascade(info.eevee.shadow_cascade_size || "1024");
      setEeveeVolStart(null); setEeveeVolEnd(null);
      setEeveeVolTile(info.eevee.volumetric_tile_size || "8");
      setEeveeVolSamples(null);
    } else {
      setEeveeSamples(null);
    }
  }, [blendRelpath, hasInfoForSelected]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Pre-fill from source job ("Render Again" from history) ────────────────
  useEffect(() => {
    if (!fromJobId || prefillApplied.current) return;
    const sourceJob = jobs.find((j) => j.job_id === fromJobId);
    if (!sourceJob) return;

    prefillApplied.current = true;
    if (blendFiles.length > 0 && !blendFiles.includes(sourceJob.blend_relpath)) {
      setPrefillMissingFile(sourceJob.blend_relpath);
    }
    setBlendRelpath(blendFiles.includes(sourceJob.blend_relpath) ? sourceJob.blend_relpath : "");
    setFrameStart(sourceJob.frame_start);
    setFrameEnd(sourceJob.frame_end);

    const eng = sourceJob.render_engine ?? "CYCLES";
    if (eng === "CYCLES") setEngine("CYCLES");
    else if (eng === "BLENDER_EEVEE" || eng === "BLENDER_EEVEE_NEXT") setEngine("BLENDER_EEVEE");

    setOutputFormat(sourceJob.output_format ?? "PNG");
    if (sourceJob.frame_step != null) setFrameStep(sourceJob.frame_step);
    if (sourceJob.threads != null) setThreads(sourceJob.threads);

    const ov = sourceJob.render_overrides;
    if (ov) {
      if (ov.resolution_x !== undefined) setResX(ov.resolution_x);
      if (ov.resolution_y !== undefined) setResY(ov.resolution_y);
      if (ov.resolution_percentage !== undefined) setResPct(ov.resolution_percentage);
      if (ov.film_transparent !== undefined) setFilmTransparent(ov.film_transparent);
      if (ov.color_depth !== undefined) setColorDepth(ov.color_depth);
      if (ov.compression !== undefined) setCompression(ov.compression);
      if (ov.active_camera !== undefined) setActiveCamera(ov.active_camera ?? null);
      if (ov.passes !== undefined) setSelectedPasses(ov.passes ?? null);
      if (ov.exr_codec !== undefined) setExrCodec(ov.exr_codec);
      if (ov.pixel_filter_type !== undefined) setPixelFilterType(ov.pixel_filter_type ?? null);
      if (ov.pixel_filter_width !== undefined) setPixelFilterWidth(ov.pixel_filter_width ?? null);
      if (ov.use_motion_blur !== undefined) setUseMotionBlur(ov.use_motion_blur);
      if (ov.motion_blur_shutter !== undefined) setMotionBlurShutter(ov.motion_blur_shutter ?? null);
      if (ov.use_compositing !== undefined) setUseCompositing(ov.use_compositing);
      if (ov.use_sequencer !== undefined) setUseSequencer(ov.use_sequencer);
      if (ov.dither_intensity !== undefined) setDitherIntensity(ov.dither_intensity ?? null);
      if (ov.use_border !== undefined) setUseBorder(ov.use_border);
      if (ov.use_crop_to_border !== undefined) setUseCropToBorder(ov.use_crop_to_border);
      if (ov.use_lock_interface !== undefined) setUseLockInterface(ov.use_lock_interface);
      if (ov.use_stamp !== undefined) setUseStamp(ov.use_stamp);
      if (ov.use_overwrite !== undefined) setUseOverwrite(ov.use_overwrite);
      if (ov.use_placeholder !== undefined) setUsePlaceholder(ov.use_placeholder);
      if (ov.view_transform !== undefined) setViewTransform(ov.view_transform ?? null);
      if (ov.look !== undefined) setLook(ov.look ?? null);
      if (ov.exposure !== undefined) setCmExposure(ov.exposure ?? null);
      if (ov.gamma !== undefined) setCmGamma(ov.gamma ?? null);
      if (ov.use_simplify !== undefined) setUseSimplify(ov.use_simplify);
      if (ov.simplify_subdivision_render !== undefined) setSimplifySubdivision(ov.simplify_subdivision_render ?? null);
      if (ov.simplify_child_particles_render !== undefined) setSimplifyChildParticles(ov.simplify_child_particles_render ?? null);
      if (ov.simplify_volumes !== undefined) setSimplifyVolumes(ov.simplify_volumes ?? null);
      if (ov.use_camera_cull !== undefined) setUseCameraCull(ov.use_camera_cull);
      if (ov.camera_cull_margin !== undefined) setCameraCullMargin(ov.camera_cull_margin ?? null);
      if (ov.compositor_device !== undefined) setCompositorDevice(ov.compositor_device);
      if (ov.cycles_samples !== undefined) setSamples(ov.cycles_samples ?? null);
      if (ov.cycles_use_denoising !== undefined) setUseDenoising(ov.cycles_use_denoising);
      if (ov.cycles_denoiser !== undefined) setDenoiser(ov.cycles_denoiser);
      if (ov.cycles_device !== undefined) setDevice(ov.cycles_device);
      if (ov.cycles_use_adaptive_sampling !== undefined) setUseAdaptiveSampling(ov.cycles_use_adaptive_sampling);
      if (ov.cycles_adaptive_threshold !== undefined) setAdaptiveThreshold(ov.cycles_adaptive_threshold ?? null);
      if (ov.cycles_adaptive_min_samples !== undefined) setAdaptiveMinSamples(ov.cycles_adaptive_min_samples ?? null);
      if (ov.cycles_denoising_prefilter !== undefined) setDenoisingPrefilter(ov.cycles_denoising_prefilter);
      if (ov.cycles_denoising_input_passes !== undefined) setDenoisingInputPasses(ov.cycles_denoising_input_passes);
      if (ov.cycles_denoising_use_gpu !== undefined) setDenoisingUseGpu(ov.cycles_denoising_use_gpu);
      if (ov.cycles_max_bounces !== undefined) setMaxBounces(ov.cycles_max_bounces ?? null);
      if (ov.cycles_diffuse_bounces !== undefined) setDiffuseBounces(ov.cycles_diffuse_bounces ?? null);
      if (ov.cycles_glossy_bounces !== undefined) setGlossyBounces(ov.cycles_glossy_bounces ?? null);
      if (ov.cycles_transmission_bounces !== undefined) setTransmissionBounces(ov.cycles_transmission_bounces ?? null);
      if (ov.cycles_volume_bounces !== undefined) setVolumeBounces(ov.cycles_volume_bounces ?? null);
      if (ov.cycles_transparent_max_bounces !== undefined) setTransparentBounces(ov.cycles_transparent_max_bounces ?? null);
      if (ov.cycles_sample_clamp_direct !== undefined) setClampDirect(ov.cycles_sample_clamp_direct ?? null);
      if (ov.cycles_sample_clamp_indirect !== undefined) setClampIndirect(ov.cycles_sample_clamp_indirect ?? null);
      if (ov.cycles_caustic_reflective !== undefined) setCausticReflective(ov.cycles_caustic_reflective);
      if (ov.cycles_caustic_refractive !== undefined) setCausticRefractive(ov.cycles_caustic_refractive);
      if (ov.cycles_blur_glossy !== undefined) setBlurGlossy(ov.cycles_blur_glossy ?? null);
      if (ov.cycles_film_transparent_glass !== undefined) setFilmTransparentGlass(ov.cycles_film_transparent_glass);
      if (ov.cycles_film_transparent_roughness !== undefined) setFilmTransparentRoughness(ov.cycles_film_transparent_roughness ?? null);
      if (ov.cycles_motion_blur_position !== undefined) setMotionBlurPosition(ov.cycles_motion_blur_position);
      if (ov.cycles_use_persistent_data !== undefined) setUsePersistentData(ov.cycles_use_persistent_data);
      if (ov.cycles_use_auto_tile !== undefined) setUseAutoTile(ov.cycles_use_auto_tile);
      if (ov.cycles_tile_size !== undefined) setTileSize(ov.cycles_tile_size ?? null);
      if (ov.cycles_use_light_tree !== undefined) setUseLightTree(ov.cycles_use_light_tree);
      if (ov.cycles_ao_bounces_render !== undefined) setAoBounces(ov.cycles_ao_bounces_render ?? null);
      if (ov.eevee_taa_render_samples !== undefined) setEeveeSamples(ov.eevee_taa_render_samples ?? null);
      if (ov.eevee_use_bloom !== undefined) setEeveeBloom(ov.eevee_use_bloom);
      if (ov.eevee_use_ssr !== undefined) setEeveeSsr(ov.eevee_use_ssr);
      if (ov.eevee_use_gtao !== undefined) setEeveeGtao(ov.eevee_use_gtao);
      if (ov.eevee_shadow_cube_size !== undefined) setEeveeShadowCube(ov.eevee_shadow_cube_size);
      if (ov.eevee_shadow_cascade_size !== undefined) setEeveeShadowCascade(ov.eevee_shadow_cascade_size);
      if (ov.eevee_volumetric_start !== undefined) setEeveeVolStart(ov.eevee_volumetric_start ?? null);
      if (ov.eevee_volumetric_end !== undefined) setEeveeVolEnd(ov.eevee_volumetric_end ?? null);
      if (ov.eevee_volumetric_tile_size !== undefined) setEeveeVolTile(ov.eevee_volumetric_tile_size);
      if (ov.eevee_volumetric_samples !== undefined) setEeveeVolSamples(ov.eevee_volumetric_samples ?? null);

      setShowAdvanced(true);
    }
  }, [fromJobId, jobs]); // eslint-disable-line react-hooks/exhaustive-deps

  // Button label logic — use the selected workstation's status
  const hasActiveRender = jobs.some((j) => j.status === "in_progress");
  const selectedAgentOnline = activeAgent ? activeAgent.status !== "offline" : false;
  const queueMode = hasActiveRender || !selectedAgentOnline;

  // Find an online alternative if selected is offline
  const onlineAlternative = activeAgent?.status === "offline"
    ? agents.find((a) => a.status !== "offline" && a.agent_id !== activeAgent?.agent_id)
    : null;

  const effectiveStep = frameStep ?? currentInfo?.frame_step ?? 1;
  const totalFrames = Math.max(0, Math.ceil((frameEnd - frameStart + 1) / Math.max(1, effectiveStep)));

  const isCycles = engine === "CYCLES";

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!blendRelpath) { setError("Select a blend file."); return; }
    if (frameEnd < frameStart) { setError("End frame must be ≥ start frame."); return; }

    // Validate all numeric fields against their constraints
    const numErr = validateNumericFields({
      frameStep, threads, resX, resY, resPct, compression, ditherIntensity,
      pixelFilterWidth, motionBlurShutter, cmExposure, cmGamma,
      simplifySubdivision, simplifyChildParticles, simplifyVolumes, cameraCullMargin,
      samples, adaptiveThreshold, adaptiveMinSamples,
      maxBounces, diffuseBounces, glossyBounces, transmissionBounces,
      volumeBounces, transparentBounces, clampDirect, clampIndirect, blurGlossy,
      filmTransparentRoughness, tileSize, aoBounces,
      eeveeSamples, eeveeVolStart, eeveeVolEnd, eeveeVolSamples,
    });
    if (numErr) { setError(numErr); return; }

    // Build render overrides
    const overrides: RenderOverrides = {};
    if (resX !== null) overrides.resolution_x = resX;
    if (resY !== null) overrides.resolution_y = resY;
    if (resPct !== null) overrides.resolution_percentage = resPct;
    overrides.film_transparent = filmTransparent;
    if (colorDepth) overrides.color_depth = colorDepth;
    if (compression !== null) overrides.compression = compression;
    if (activeCamera) overrides.active_camera = activeCamera;

    // Output
    if (outputFormat === "OPEN_EXR_MULTILAYER" && selectedPasses !== null) {
      overrides.passes = selectedPasses;
    }
    if ((outputFormat === "OPEN_EXR" || outputFormat === "OPEN_EXR_MULTILAYER") && exrCodec) {
      overrides.exr_codec = exrCodec;
    }

    // Film & Motion Blur
    if (pixelFilterType) overrides.pixel_filter_type = pixelFilterType;
    if (pixelFilterWidth !== null) overrides.pixel_filter_width = pixelFilterWidth;
    overrides.use_motion_blur = useMotionBlur;
    if (useMotionBlur && motionBlurShutter !== null) overrides.motion_blur_shutter = motionBlurShutter;

    // Render Safety
    overrides.use_compositing = useCompositing;
    overrides.use_sequencer = useSequencer;
    if (ditherIntensity !== null) overrides.dither_intensity = ditherIntensity;
    overrides.use_border = useBorder;
    if (useBorder) overrides.use_crop_to_border = useCropToBorder;
    overrides.use_lock_interface = useLockInterface;
    overrides.use_stamp = useStamp;
    overrides.use_overwrite = useOverwrite;
    overrides.use_placeholder = usePlaceholder;

    // Color Management
    if (viewTransform) overrides.view_transform = viewTransform;
    if (look) overrides.look = look;
    if (cmExposure !== null) overrides.exposure = cmExposure;
    if (cmGamma !== null) overrides.gamma = cmGamma;

    // Simplify
    overrides.use_simplify = useSimplify;
    if (useSimplify) {
      if (simplifySubdivision !== null) overrides.simplify_subdivision_render = simplifySubdivision;
      if (simplifyChildParticles !== null) overrides.simplify_child_particles_render = simplifyChildParticles;
      if (simplifyVolumes !== null) overrides.simplify_volumes = simplifyVolumes;
      overrides.use_camera_cull = useCameraCull;
      if (useCameraCull && cameraCullMargin !== null) overrides.camera_cull_margin = cameraCullMargin;
    }

    // Performance
    if (compositorDevice) overrides.compositor_device = compositorDevice;

    if (isCycles) {
      if (samples !== null) overrides.cycles_samples = samples;
      overrides.cycles_use_denoising = useDenoising;
      if (denoiser) overrides.cycles_denoiser = denoiser;
      if (device) overrides.cycles_device = device;
      overrides.cycles_use_adaptive_sampling = useAdaptiveSampling;
      if (useAdaptiveSampling) {
        if (adaptiveThreshold !== null) overrides.cycles_adaptive_threshold = adaptiveThreshold;
        if (adaptiveMinSamples !== null) overrides.cycles_adaptive_min_samples = adaptiveMinSamples;
      }
      if (useDenoising) {
        overrides.cycles_denoising_prefilter = denoisingPrefilter;
        overrides.cycles_denoising_input_passes = denoisingInputPasses;
        if (denoiser === "OPENIMAGEDENOISE") overrides.cycles_denoising_use_gpu = denoisingUseGpu;
      }

      // Light Paths
      if (maxBounces !== null) overrides.cycles_max_bounces = maxBounces;
      if (diffuseBounces !== null) overrides.cycles_diffuse_bounces = diffuseBounces;
      if (glossyBounces !== null) overrides.cycles_glossy_bounces = glossyBounces;
      if (transmissionBounces !== null) overrides.cycles_transmission_bounces = transmissionBounces;
      if (volumeBounces !== null) overrides.cycles_volume_bounces = volumeBounces;
      if (transparentBounces !== null) overrides.cycles_transparent_max_bounces = transparentBounces;
      if (clampDirect !== null) overrides.cycles_sample_clamp_direct = clampDirect;
      if (clampIndirect !== null) overrides.cycles_sample_clamp_indirect = clampIndirect;
      overrides.cycles_caustic_reflective = causticReflective;
      overrides.cycles_caustic_refractive = causticRefractive;
      if (blurGlossy !== null) overrides.cycles_blur_glossy = blurGlossy;

      // Film (Cycles)
      if (filmTransparent) {
        overrides.cycles_film_transparent_glass = filmTransparentGlass;
        if (filmTransparentGlass && filmTransparentRoughness !== null) {
          overrides.cycles_film_transparent_roughness = filmTransparentRoughness;
        }
      }
      if (useMotionBlur) overrides.cycles_motion_blur_position = motionBlurPosition;

      // Performance (Cycles)
      overrides.cycles_use_persistent_data = usePersistentData;
      overrides.cycles_use_auto_tile = useAutoTile;
      if (useAutoTile && tileSize !== null) overrides.cycles_tile_size = tileSize;

      // Simplify GI (Cycles)
      if (useSimplify) {
        overrides.cycles_use_light_tree = useLightTree;
        if (aoBounces !== null) overrides.cycles_ao_bounces_render = aoBounces;
        overrides.texture_limit_render = textureLimitRender;
      }
    } else {
      if (eeveeSamples !== null) overrides.eevee_taa_render_samples = eeveeSamples;
      overrides.eevee_use_bloom = eeveeBloom;
      overrides.eevee_use_ssr = eeveeSsr;
      overrides.eevee_use_gtao = eeveeGtao;
      if (eeveeShadowCube) overrides.eevee_shadow_cube_size = eeveeShadowCube;
      if (eeveeShadowCascade) overrides.eevee_shadow_cascade_size = eeveeShadowCascade;
      if (eeveeVolStart !== null) overrides.eevee_volumetric_start = eeveeVolStart;
      if (eeveeVolEnd !== null) overrides.eevee_volumetric_end = eeveeVolEnd;
      if (eeveeVolTile) overrides.eevee_volumetric_tile_size = eeveeVolTile;
      if (eeveeVolSamples !== null) overrides.eevee_volumetric_samples = eeveeVolSamples;
    }

    const hasOverrides = Object.keys(overrides).length > 0;

    setSubmitting(true);
    setError(null);
    try {
      await apiJson("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          blend_relpath: blendRelpath,
          frame_start: frameStart,
          frame_end: frameEnd,
          render_engine: engine || undefined,
          ...(outputFormat ? { output_format: outputFormat } : {}),
          ...(frameStep !== null ? { frame_step: frameStep } : {}),
          ...(threads !== null ? { threads } : {}),
          ...(hasOverrides ? { render_overrides: overrides } : {}),
          ...(activeAgent ? { target_agent_id: activeAgent.agent_id } : {}),
        }),
      });
      navigate("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create job");
    } finally {
      setSubmitting(false);
    }
  }

  const noAgentConnected = agents.length === 0;
  const noAgentOnline = agents.length > 0 && agents.every((a) => a.status === "offline");

  return (
    <div className="flex flex-col min-h-screen bg-bg-base">
      {/* Page header */}
      <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 py-4 flex items-center gap-4">
        <Link href="/dashboard">
          <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors">
            <Icon name="arrow_back" className="text-xl" />
          </button>
        </Link>
        <h1 className="text-xl font-bold tracking-tight">New Render Job</h1>
      </header>

      <main className="flex-1 p-6 pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-8">
        <form onSubmit={handleSubmit} className="max-w-xl mx-auto space-y-5">
          {/* ── Warnings ── */}
          {noAgentConnected && (
            <div className="bg-secondary/10 border border-secondary/20 rounded-xl p-4 flex gap-3 items-start">
              <Icon name="info" className="text-secondary shrink-0 mt-0.5" />
              <p className="text-sm text-slate-200">
                No computer connected.{" "}
                <Link href="/download" className="text-secondary font-semibold underline">Download the app</Link>
                {" "}to enable rendering. Job will be queued.
              </p>
            </div>
          )}
          {noAgentOnline && (
            <div className="bg-secondary/10 border border-secondary/20 rounded-xl p-4 flex gap-3 items-start">
              <Icon name="warning" className="text-secondary shrink-0 mt-0.5" />
              <div className="text-sm text-slate-200">
                <p>
                  {activeAgent
                    ? <>Your workstation <b>{activeAgent.name}</b> is currently offline. Job will be queued and start when it comes online.</>
                    : "Your workstation is currently offline. Job will be queued and start when it comes online."}
                </p>
                {onlineAlternative && (
                  <button
                    type="button"
                    onClick={() => setActiveAgent(onlineAlternative.agent_id)}
                    className="mt-2 text-xs font-bold text-secondary flex items-center gap-1 hover:opacity-80 transition-opacity"
                  >
                    Switch to {onlineAlternative.name} <Icon name="arrow_forward" className="text-xs" />
                  </button>
                )}
              </div>
            </div>
          )}
          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
              {error}
            </div>
          )}

          {/* ── Target workstation (multi-agent Pro only) ── */}
          {isPro && agents.length > 1 && (
            <div className="bg-bg-surface rounded-xl p-5 border border-white/5">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Target Workstation</h2>
              <SelectField
                value={activeAgent?.agent_id ?? ""}
                onChange={(id) => setActiveAgent(id)}
                options={agents.map((a) => ({
                  value: a.agent_id,
                  label: `${a.name || "Unnamed"} - ${a.status === "busy" ? "Rendering" : a.status === "offline" ? "Offline" : "Online"}`,
                }))}
              />
            </div>
          )}

          {/* ── Source file ── */}
          <div className="bg-bg-surface rounded-xl p-5 border border-white/5">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Source File</h2>
            <FieldLabel label="Blend File" note={activeAgent ? `from ${activeAgent.name || "workstation"}` : "Scanned from connected workstation"} />
            {blendFiles.length > 0 ? (
              <SelectField
                value={blendRelpath}
                onChange={setBlendRelpath}
                options={blendFiles.map((f) => ({ value: f, label: f }))}
              />
            ) : (
              <div className="w-full bg-bg-base border border-white/10 rounded-lg p-4 text-sm text-slate-400 text-left">
                <div className="flex items-center gap-2 text-amber-400 font-semibold mb-2">
                  <Icon name="warning" className="text-base" />
                  No .blend files found
                </div>
                {noAgentConnected ? (
                  <p>Connect a computer to see available files.</p>
                ) : (
                  <div className="space-y-2">
                    <p>To render, you must first copy your project into the <code>BlendFiles</code> folder within your agent's Workspace on your PC.</p>
                    <p>Alternatively, install the <b>{APP_DISPLAY_NAME} Blender Addon</b> to submit directly from Blender with one click.</p>
                  </div>
                )}
              </div>
            )}
            {prefillMissingFile && (
              <div className="mt-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-sm text-amber-400">
                <span className="font-semibold">File not found:</span> <code>{prefillMissingFile}</code> is no longer available on the workstation. Select a different file or re-add it to your BlendFiles folder.
              </div>
            )}
            {currentInfo && (
              <p className="text-[10px] text-slate-500 mt-2 flex items-center gap-1.5">
                <Icon name="info" className="text-xs" />
                {currentInfo.resolution_x}×{currentInfo.resolution_y} · {currentInfo.engine} · Frames {currentInfo.frame_start}-{currentInfo.frame_end}
              </p>
            )}
          </div>

          {/* ── Render Engine (always visible) ── */}
          <div className="bg-bg-surface rounded-xl p-5 border border-white/5">
            <EngineToggle value={engine} onChange={setEngine} />
          </div>

          {/* ── Frame range ── */}
          <div className="bg-bg-surface rounded-xl p-5 border border-white/5">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Frame Range</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel label="Start Frame" info="First frame number to render" />
                <NumberField value={frameStart} onChange={(v) => { if (v !== null) setFrameStart(v); }} min={0} placeholder="" />
              </div>
              <div>
                <FieldLabel label="End Frame" info="Last frame number to render" />
                <NumberField value={frameEnd} onChange={(v) => { if (v !== null) setFrameEnd(v); }} min={0} placeholder="" />
              </div>
            </div>
            {totalFrames > 0 && (
              <p className="text-xs text-slate-500 mt-3">
                {totalFrames} frame{totalFrames !== 1 ? "s" : ""} will be rendered
                {(effectiveStep > 1) ? ` (every ${effectiveStep} frames)` : ""}
              </p>
            )}
          </div>

          {/* ── Basic settings ── */}
          <div className="bg-bg-surface rounded-xl p-5 border border-white/5 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Output</h2>
            <div>
              <FieldLabel label="Output Format" info="Image file format for rendered frames" />
              <SelectField value={outputFormat} onChange={setOutputFormat} options={withDefaultMark(FORMATS, currentInfo?.output_format)} />
            </div>
          </div>

          {/* ── Advanced settings (engine-specific overrides) ── */}
          <div className="bg-bg-surface rounded-xl border border-white/5 overflow-hidden">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-white/[0.02] transition-colors gap-3"
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Advanced Settings</span>
                {!isPro && (
                  <span className="text-[9px] font-bold uppercase tracking-widest text-primary border border-primary/30 bg-primary/10 px-1.5 py-0.5 rounded shrink-0">
                    Pro
                  </span>
                )}
              </span>
              <div className="flex items-center gap-2 shrink-0 ml-auto">
                {showAdvanced && (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); resetOverrides(); }}
                    className="text-[10px] text-slate-500 hover:text-primary transition-colors px-2 py-1 rounded border border-white/5 hover:border-primary/30"
                  >
                    Reset defaults
                  </button>
                )}
                <Icon
                  name={showAdvanced ? "expand_less" : "expand_more"}
                  className="text-lg text-slate-500 shrink-0"
                />
              </div>
            </button>

            {showAdvanced && (
              <div className="px-5 pb-5 space-y-3 border-t border-white/5 pt-4">
                {!isPro && (
                  <div className="text-xs text-primary/80 bg-primary/5 border border-primary/20 rounded-lg px-3 py-2 text-center">
                    Upgrade to Pro to customize render settings
                  </div>
                )}

                {/* ── Render Safety / Gotchas — warning card at top ── */}
                <CollapsibleGroup title="Render Checks" variant="warning">
                  <div className="grid grid-cols-2 gap-3">
                    <ToggleField label="Compositing" value={useCompositing} onChange={setUseCompositing} blendDefault={currentInfo?.use_compositing} disabled={!isPro} info="Run the compositor after rendering. Disable if your scene has no compositing nodes" />
                    <ToggleField label="Sequencer" value={useSequencer} onChange={setUseSequencer} blendDefault={currentInfo?.use_sequencer} disabled={!isPro} info="Process the video sequence editor. Disable if not using the VSE" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <ToggleField label="Border Render" value={useBorder} onChange={setUseBorder} blendDefault={currentInfo?.use_border} disabled={!isPro} info="Only render a sub-region of the full frame" />
                    {useBorder && (
                      <ToggleField label="Crop to Border" value={useCropToBorder} onChange={setUseCropToBorder} blendDefault={currentInfo?.use_crop_to_border} disabled={!isPro} info="Crop the output image to the border region" />
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <ToggleField label="Stamp Metadata" value={useStamp} onChange={setUseStamp} blendDefault={currentInfo?.use_stamp} disabled={!isPro} info="Burn render info (frame, time, camera) into the output image" />
                    <ToggleField label="Lock Interface" value={useLockInterface} onChange={setUseLockInterface} blendDefault={currentInfo?.use_lock_interface} disabled={!isPro} info="Lock Blender's UI while rendering to prevent accidental changes" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <ToggleField label="Overwrite" value={useOverwrite} onChange={setUseOverwrite} blendDefault={currentInfo?.use_overwrite} disabled={!isPro} info="Overwrite existing rendered frames on disk" />
                    <ToggleField label="Placeholders" value={usePlaceholder} onChange={setUsePlaceholder} blendDefault={currentInfo?.use_placeholder} disabled={!isPro} info="Create empty placeholder files for frames before rendering them" />
                  </div>
                  <div>
                    <FieldLabel label="Dithering" info="Adds subtle noise to reduce color banding in gradients" />
                    <NumberField value={ditherIntensity} onChange={setDitherIntensity} min={0} max={2} step={0.05} placeholder={currentInfo ? `${currentInfo.dither_intensity}` : "1.0"} disabled={!isPro} />
                  </div>
                </CollapsibleGroup>

                {/* ── Output ── */}
                <CollapsibleGroup title="Output" defaultOpen>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <FieldLabel label="Width" info="Horizontal resolution in pixels" />
                      <NumberField value={resX} onChange={setResX} min={1} max={16384} placeholder={currentInfo ? `${currentInfo.resolution_x}` : "1920"} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="Height" info="Vertical resolution in pixels" />
                      <NumberField value={resY} onChange={setResY} min={1} max={16384} placeholder={currentInfo ? `${currentInfo.resolution_y}` : "1080"} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="Scale %" info="Scales the resolution without changing the aspect ratio" />
                      <NumberField value={resPct} onChange={setResPct} min={1} max={100} placeholder={currentInfo ? `${currentInfo.resolution_percentage}` : "100"} disabled={!isPro} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <FieldLabel label="Color Depth" info="Bits per channel. Higher = more color precision, larger files" />
                      <SelectField value={colorDepth} onChange={setColorDepth} options={withDefaultMark(COLOR_DEPTHS, currentInfo?.color_depth)} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="Compression" info="PNG/TIFF compression level. Higher = smaller files, slower save" />
                      <NumberField value={compression} onChange={setCompression} min={0} max={100} placeholder={currentInfo ? `${currentInfo.compression}` : "15"} disabled={!isPro} />
                    </div>
                  </div>
                  {(outputFormat === "OPEN_EXR" || outputFormat === "OPEN_EXR_MULTILAYER") && (
                    <div>
                      <FieldLabel label="EXR Codec" info="Compression method for EXR files. Lossy codecs are smaller but lose precision" />
                      <SelectField value={exrCodec} onChange={setExrCodec} options={withDefaultMark(EXR_CODEC_OPTIONS, currentInfo?.exr_codec)} disabled={!isPro} />
                    </div>
                  )}
                  {currentInfo?.cameras && currentInfo.cameras.length > 0 && (
                    <div>
                      <FieldLabel label={activeCamera ? "Camera (Override)" : "Camera"} info="Which camera to render from. Default uses the scene's active or animated camera" />
                      <SelectField
                        value={activeCamera ?? ""}
                        onChange={v => setActiveCamera(v || null)}
                        disabled={!isPro}
                        options={[
                          { value: "", label: `Default · ${currentInfo.active_camera || "Scene Camera"}` },
                          ...currentInfo.cameras.filter(c => c !== currentInfo.active_camera).map(c => ({
                            value: c,
                            label: c
                          }))
                        ]}
                      />
                    </div>
                  )}
                  {outputFormat === "OPEN_EXR_MULTILAYER" && currentInfo?.all_passes && (
                    <PassSelectionList
                      allPasses={currentInfo.all_passes}
                      defaultActivePasses={currentInfo.active_passes || []}
                      selectedPasses={selectedPasses}
                      onChange={setSelectedPasses}
                      disabled={!isPro}
                    />
                  )}
                </CollapsibleGroup>

                {/* ── Sampling (Cycles) ── */}
                {isCycles && (
                  <CollapsibleGroup title="Sampling" defaultOpen>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Render Samples" info="Number of light samples per pixel. More = less noise, longer render" />
                        <NumberField value={samples} onChange={setSamples} min={1} max={100000} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.samples}` : "128"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Compute Device" info="CPU is slower but uses less VRAM. GPU is faster for most scenes" />
                        <SelectField value={device} onChange={setDevice} options={withDefaultMark(DEVICE_OPTIONS, currentInfo?.cycles?.device)} disabled={!isPro} />
                      </div>
                    </div>
                    <ToggleField label="Adaptive Sampling" value={useAdaptiveSampling} onChange={setUseAdaptiveSampling} blendDefault={currentInfo?.cycles?.use_adaptive_sampling} disabled={!isPro} info="Stop sampling pixels early once they converge. Faster renders with little quality loss" />
                    {useAdaptiveSampling && (
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <FieldLabel label="Noise Threshold" info="Lower values produce less noise but take longer. 0 uses automatic threshold" />
                          <NumberField value={adaptiveThreshold} onChange={setAdaptiveThreshold} min={0} max={1} step={0.001} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.adaptive_threshold}` : "0.01"} disabled={!isPro} />
                        </div>
                        <div>
                          <FieldLabel label="Min Samples" info="Minimum samples before adaptive sampling can stop a pixel" />
                          <NumberField value={adaptiveMinSamples} onChange={setAdaptiveMinSamples} min={0} max={65536} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.adaptive_min_samples}` : "0"} disabled={!isPro} />
                        </div>
                      </div>
                    )}
                    <ToggleField label="Denoising" value={useDenoising} onChange={setUseDenoising} blendDefault={currentInfo?.cycles?.use_denoising} disabled={!isPro} info="Remove noise from the final render. Recommended for most scenes" />
                    {useDenoising && (
                      <>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <FieldLabel label="Denoiser" info="Denoising algorithm. OptiX requires an NVIDIA GPU" />
                            <SelectField value={denoiser} onChange={setDenoiser} options={withDefaultMark(DENOISER_OPTIONS, currentInfo?.cycles?.denoiser)} disabled={!isPro} />
                          </div>
                          <div>
                            <FieldLabel label="Prefilter" info="Cleans up auxiliary passes before denoising. Accurate is slower but better for complex scenes" />
                            <SelectField value={denoisingPrefilter} onChange={setDenoisingPrefilter} options={withDefaultMark(DENOISING_PREFILTER_OPTIONS, currentInfo?.cycles?.denoising_prefilter)} disabled={!isPro} />
                          </div>
                        </div>
                        <div>
                          <FieldLabel label="Input Passes" info="Which data passes to use for denoising. More passes = better quality but slower" />
                          <SelectField value={denoisingInputPasses} onChange={setDenoisingInputPasses} options={withDefaultMark(DENOISING_INPUT_OPTIONS, currentInfo?.cycles?.denoising_input_passes)} disabled={!isPro} />
                        </div>
                        {denoiser === "OPENIMAGEDENOISE" && (
                          <ToggleField label="Denoise on GPU" value={denoisingUseGpu} onChange={setDenoisingUseGpu} blendDefault={currentInfo?.cycles?.denoising_use_gpu} disabled={!isPro} info="Run OpenImageDenoise on the GPU for faster denoising" />
                        )}
                      </>
                    )}
                  </CollapsibleGroup>
                )}

                {/* ── Sampling (EEVEE) ── */}
                {!isCycles && (
                  <CollapsibleGroup title="EEVEE" defaultOpen>
                    <div>
                      <FieldLabel label="Render Samples" info="Temporal anti-aliasing samples. More = smoother image, slower render" />
                      <NumberField value={eeveeSamples} onChange={setEeveeSamples} min={1} max={65536} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.taa_render_samples}` : "64"} disabled={!isPro} />
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <ToggleField label="Bloom" value={eeveeBloom} onChange={setEeveeBloom} blendDefault={currentInfo?.eevee?.use_bloom} disabled={!isPro} info="Adds glow around bright areas" />
                      <ToggleField label="SSR" value={eeveeSsr} onChange={setEeveeSsr} blendDefault={currentInfo?.eevee?.use_ssr} disabled={!isPro} info="Screen Space Reflections for glossy surfaces" />
                      <ToggleField label="AO (GTAO)" value={eeveeGtao} onChange={setEeveeGtao} blendDefault={currentInfo?.eevee?.use_gtao} disabled={!isPro} info="Ground Truth Ambient Occlusion for contact shadows" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Shadow Cube Size" info="Resolution of point light shadow maps. Higher = sharper shadows, more VRAM" />
                        <SelectField value={eeveeShadowCube} onChange={setEeveeShadowCube} options={withDefaultMark(SHADOW_SIZE_OPTIONS, currentInfo?.eevee?.shadow_cube_size)} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Shadow Cascade Size" info="Resolution of sun light shadow maps" />
                        <SelectField value={eeveeShadowCascade} onChange={setEeveeShadowCascade} options={withDefaultMark(SHADOW_SIZE_OPTIONS, currentInfo?.eevee?.shadow_cascade_size)} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Volumetric Start" info="Near clip distance for volumetric effects" />
                        <NumberField value={eeveeVolStart} onChange={setEeveeVolStart} min={0} max={10000} step={0.1} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_start}` : "0.1"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Volumetric End" info="Far clip distance for volumetric effects" />
                        <NumberField value={eeveeVolEnd} onChange={setEeveeVolEnd} min={0} max={10000} step={0.1} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_end}` : "100"} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Volumetric Tile Size" info="Smaller tiles = more detail but slower. Larger = faster but blockier" />
                        <SelectField value={eeveeVolTile} onChange={setEeveeVolTile} options={withDefaultMark(VOLUMETRIC_TILE_OPTIONS, currentInfo?.eevee?.volumetric_tile_size)} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Volumetric Samples" info="Number of samples along each ray for volumetric effects" />
                        <NumberField value={eeveeVolSamples} onChange={setEeveeVolSamples} min={1} max={256} placeholder={currentInfo?.eevee ? `${currentInfo.eevee.volumetric_samples}` : "64"} disabled={!isPro} />
                      </div>
                    </div>
                  </CollapsibleGroup>
                )}

                {/* ── Light Paths (Cycles) ── */}
                {isCycles && (
                  <CollapsibleGroup title="Light Paths">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Total Max Bounces" info="Maximum total light bounces. Higher = more realistic but slower" />
                        <NumberField value={maxBounces} onChange={setMaxBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.max_bounces}` : "12"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Diffuse" info="Max bounces for diffuse/matte surfaces" />
                        <NumberField value={diffuseBounces} onChange={setDiffuseBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.diffuse_bounces}` : "4"} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Glossy" info="Max bounces for glossy/reflective surfaces" />
                        <NumberField value={glossyBounces} onChange={setGlossyBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.glossy_bounces}` : "4"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Transmission" info="Max bounces for transparent/refractive materials like glass" />
                        <NumberField value={transmissionBounces} onChange={setTransmissionBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.transmission_bounces}` : "12"} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Volume" info="Max bounces for volumetric effects like fog and smoke" />
                        <NumberField value={volumeBounces} onChange={setVolumeBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.volume_bounces}` : "0"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Transparent" info="Max bounces for transparent surfaces (alpha transparency)" />
                        <NumberField value={transparentBounces} onChange={setTransparentBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.transparent_max_bounces}` : "8"} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Clamp Direct" info="Limits maximum light intensity to reduce fireflies. 0 disables clamping" />
                        <NumberField value={clampDirect} onChange={setClampDirect} min={0} max={1e10} step={0.1} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.sample_clamp_direct}` : "0"} disabled={!isPro} />
                      </div>
                      <div>
                        <FieldLabel label="Clamp Indirect" info="Limits maximum indirect light intensity. 0 disables clamping" />
                        <NumberField value={clampIndirect} onChange={setClampIndirect} min={0} max={1e10} step={0.1} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.sample_clamp_indirect}` : "10"} disabled={!isPro} />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <ToggleField label="Caustics Reflective" value={causticReflective} onChange={setCausticReflective} blendDefault={currentInfo?.cycles?.caustics_reflective} disabled={!isPro} info="Light patterns from reflective surfaces. Disable to reduce noise" />
                      <ToggleField label="Caustics Refractive" value={causticRefractive} onChange={setCausticRefractive} blendDefault={currentInfo?.cycles?.caustics_refractive} disabled={!isPro} info="Light patterns from refractive surfaces like glass. Disable to reduce noise" />
                    </div>
                    <div>
                      <FieldLabel label="Filter Glossy" info="Blurs sharp glossy reflections to reduce fireflies. Higher = more blur" />
                      <NumberField value={blurGlossy} onChange={setBlurGlossy} min={0} max={10} step={0.01} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.blur_glossy}` : "1.0"} disabled={!isPro} />
                    </div>
                  </CollapsibleGroup>
                )}

                {/* ── Film & Motion Blur ── */}
                <CollapsibleGroup title="Film & Motion Blur">
                  <ToggleField label="Film Transparent" value={filmTransparent} onChange={setFilmTransparent} blendDefault={currentInfo?.film_transparent} disabled={!isPro} info="Render with a transparent background instead of the world color" />
                  {filmTransparent && isCycles && (
                    <>
                      <ToggleField label="Transparent Glass" value={filmTransparentGlass} onChange={setFilmTransparentGlass} blendDefault={currentInfo?.cycles?.film_transparent_glass} disabled={!isPro} info="Render glass as transparent when film transparency is on" />
                      {filmTransparentGlass && (
                        <div>
                          <FieldLabel label="Roughness Threshold" info="Glass below this roughness is rendered transparent when film is transparent" />
                          <NumberField value={filmTransparentRoughness} onChange={setFilmTransparentRoughness} min={0} max={1} step={0.01} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.film_transparent_roughness}` : "0.1"} disabled={!isPro} />
                        </div>
                      )}
                    </>
                  )}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <FieldLabel label="Pixel Filter" info="Anti-aliasing filter shape. Affects edge smoothing" />
                      <SelectField value={pixelFilterType ?? currentInfo?.pixel_filter_type ?? "GAUSSIAN"} onChange={setPixelFilterType} options={withDefaultMark(PIXEL_FILTER_OPTIONS, currentInfo?.pixel_filter_type)} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="Filter Width" info="Size of the pixel filter. Larger = smoother but blurrier" />
                      <NumberField value={pixelFilterWidth} onChange={setPixelFilterWidth} min={0.01} max={10} step={0.01} placeholder={currentInfo ? `${currentInfo.pixel_filter_width}` : "1.5"} disabled={!isPro} />
                    </div>
                  </div>
                  <ToggleField label="Motion Blur" value={useMotionBlur} onChange={setUseMotionBlur} blendDefault={currentInfo?.use_motion_blur} disabled={!isPro} info="Simulate camera motion blur for moving objects" />
                  {useMotionBlur && (
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <FieldLabel label="Shutter" info="Shutter time in frames. Higher = more blur" />
                        <NumberField value={motionBlurShutter} onChange={setMotionBlurShutter} min={0} max={100} step={0.01} placeholder={currentInfo ? `${currentInfo.motion_blur_shutter}` : "0.5"} disabled={!isPro} />
                      </div>
                      {isCycles && (
                        <div>
                          <FieldLabel label="Position" info="When the shutter opens relative to each frame" />
                          <SelectField value={motionBlurPosition} onChange={setMotionBlurPosition} options={withDefaultMark(MOTION_BLUR_POSITION_OPTIONS, currentInfo?.cycles?.motion_blur_position)} disabled={!isPro} />
                        </div>
                      )}
                    </div>
                  )}
                </CollapsibleGroup>

                {/* ── Performance ── */}
                <CollapsibleGroup title="Performance">
                  {isCycles && (
                    <>
                      <ToggleField label="Persistent Data" value={usePersistentData} onChange={setUsePersistentData} blendDefault={currentInfo?.cycles?.use_persistent_data} disabled={!isPro} info="Keep render data in memory between frames for faster animation renders" />
                      <ToggleField label="Use Tiling" value={useAutoTile} onChange={setUseAutoTile} blendDefault={currentInfo?.cycles?.use_auto_tile} disabled={!isPro} info="Split the image into tiles to reduce peak memory usage" />
                      {useAutoTile && (
                        <div>
                          <FieldLabel label="Tile Size" info="Larger tiles use more VRAM but can be faster on GPU" />
                          <NumberField value={tileSize} onChange={setTileSize} min={8} max={16384} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.tile_size}` : "2048"} disabled={!isPro} />
                        </div>
                      )}
                    </>
                  )}
                  <div>
                    <FieldLabel label="Compositor Device" info="Run compositing nodes on CPU or GPU" />
                    <SelectField value={compositorDevice} onChange={setCompositorDevice} options={withDefaultMark(DEVICE_OPTIONS, currentInfo?.compositor_device)} disabled={!isPro} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <FieldLabel label="Frame Step" info="Render every Nth frame. 2 = render every other frame" />
                      <NumberField value={frameStep} onChange={setFrameStep} min={1} max={100} placeholder={currentInfo?.frame_step ? `${currentInfo.frame_step}` : "1"} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="CPU Threads" info="0 = use all available threads" />
                      <NumberField value={threads} onChange={setThreads} min={0} max={64} placeholder="0 (auto)" disabled={!isPro} />
                    </div>
                  </div>
                </CollapsibleGroup>

                {/* ── Color Management ── */}
                <CollapsibleGroup title="Color Management">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <FieldLabel label="View Transform" info="Color mapping from scene-linear to display. Filmic/AgX handle highlights better than Standard" />
                      <SelectField
                        value={viewTransform ?? currentInfo?.color_management?.view_transform ?? "Filmic"}
                        onChange={setViewTransform}
                        disabled={!isPro}
                        options={getViewTransformOptions(currentInfo?.color_management?.available_view_transforms, currentInfo?.color_management?.view_transform)}
                      />
                    </div>
                    <div>
                      <FieldLabel label="Look" info="Artistic look modifier applied on top of the view transform" />
                      <SelectField
                        value={look ?? currentInfo?.color_management?.look ?? "None"}
                        onChange={setLook}
                        disabled={!isPro}
                        options={getLookOptions(currentInfo?.color_management?.available_looks, currentInfo?.color_management?.look)}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <FieldLabel label="Exposure" info="Scene exposure adjustment in stops. 0 = no change" />
                      <NumberField value={cmExposure} onChange={setCmExposure} min={-32} max={32} step={0.1} placeholder={currentInfo?.color_management ? `${currentInfo.color_management.exposure}` : "0"} disabled={!isPro} />
                    </div>
                    <div>
                      <FieldLabel label="Gamma" info="Display gamma correction. 1.0 = no correction" />
                      <NumberField value={cmGamma} onChange={setCmGamma} min={0.001} max={5} step={0.01} placeholder={currentInfo?.color_management ? `${currentInfo.color_management.gamma}` : "1.0"} disabled={!isPro} />
                    </div>
                  </div>
                </CollapsibleGroup>

                {/* ── Simplify ── */}
                <CollapsibleGroup title="Simplify">
                  <ToggleField label="Enable Simplify" value={useSimplify} onChange={setUseSimplify} blendDefault={currentInfo?.simplify?.use_simplify} disabled={!isPro} info="Reduce scene complexity for faster renders at the cost of detail" />
                  {useSimplify && (
                    <>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <FieldLabel label="Max Subdivision" info="Cap subdivision surface levels to speed up renders" />
                          <NumberField value={simplifySubdivision} onChange={setSimplifySubdivision} min={0} max={6} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_subdivision_render}` : "6"} disabled={!isPro} />
                        </div>
                        <div>
                          <FieldLabel label="Child Particles" info="Scale of child particles. 1.0 = full amount, lower = fewer particles" />
                          <NumberField value={simplifyChildParticles} onChange={setSimplifyChildParticles} min={0} max={1} step={0.01} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_child_particles_render}` : "1.0"} disabled={!isPro} />
                        </div>
                      </div>
                      <div>
                        <FieldLabel label="Volume Resolution" info="Scale of volume resolution. Lower = faster but less detailed smoke/fire" />
                        <NumberField value={simplifyVolumes} onChange={setSimplifyVolumes} min={0} max={1} step={0.01} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.simplify_volumes}` : "1.0"} disabled={!isPro} />
                      </div>
                      {isCycles && (
                        <div>
                          <FieldLabel label="Texture Limit" info="Cap texture resolution to save VRAM. Off = no limit" />
                          <SelectField value={textureLimitRender} onChange={setTextureLimitRender} options={withDefaultMark(TEXTURE_LIMIT_OPTIONS, currentInfo?.cycles?.texture_limit_render)} disabled={!isPro} />
                        </div>
                      )}
                      <ToggleField label="Camera Culling" value={useCameraCull} onChange={setUseCameraCull} blendDefault={currentInfo?.simplify?.use_camera_cull} disabled={!isPro} info="Skip rendering objects outside the camera view" />
                      {useCameraCull && (
                        <div>
                          <FieldLabel label="Cull Margin" info="Extra margin around camera frustum before culling objects" />
                          <NumberField value={cameraCullMargin} onChange={setCameraCullMargin} min={0} max={5} step={0.01} placeholder={currentInfo?.simplify ? `${currentInfo.simplify.camera_cull_margin}` : "0.1"} disabled={!isPro} />
                        </div>
                      )}
                      {isCycles && (
                        <>
                          <ToggleField label="Light Tree" value={useLightTree} onChange={setUseLightTree} blendDefault={currentInfo?.cycles?.use_light_tree} disabled={!isPro} info="Optimizes light sampling for scenes with many lights" />
                          <div>
                            <FieldLabel label="AO Bounces (Approx)" info="Approximate global illumination after this many bounces. 0 disables" />
                            <NumberField value={aoBounces} onChange={setAoBounces} min={0} max={1024} placeholder={currentInfo?.cycles ? `${currentInfo.cycles.ao_bounces_render}` : "0"} disabled={!isPro} />
                          </div>
                        </>
                      )}
                    </>
                  )}
                </CollapsibleGroup>

              </div>
            )}
          </div>

          {/* Submit */}
          <div className="flex justify-end pt-2">
            <button
              type="submit"
              disabled={submitting || blendFiles.length === 0}
              className="flex items-center gap-2 gradient-primary hover:opacity-90 text-white font-bold py-3 px-8 rounded-xl shadow-xl shadow-black/20 transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Icon name={queueMode ? "queue" : "rocket_launch"} className="text-lg" />
              {submitting ? "Submitting..." : queueMode ? "Add to Queue" : "Start Render Job"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
