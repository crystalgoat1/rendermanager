export type JobStatus =
  | "queued"
  | "in_progress"
  | "completed"
  | "failed"
  | "canceled"
  | "paused";

export interface Job {
  job_id: string;
  job_group_id: string;
  user_id: string;
  agent_id: string | null;
  target_agent_id: string | null;
  task: string;
  blend_relpath: string;
  frame_start: number;
  frame_end: number;
  status: JobStatus;
  attempt: number;
  retry_of: string | null;
  pause_requested: boolean;
  cancel_requested: boolean;
  paused: boolean;
  progress: number;
  current_frame: number | null;
  progress_message: string;
  last_progress_at: string | null;
  latest_preview_path: string | null;
  latest_preview_at: string | null;
  latest_preview_frame: number | null;
  fail_reason: string | null;
  render_engine: string | null;
  output_format: string | null;
  frame_step: number | null;
  threads: number | null;
  render_overrides: RenderOverrides | null;
  available_at: string;
  created_at: string;
  assigned_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  paused_at: string | null;
  available_passes: string[] | null;
  progress_base: number;
  requeued_from_agent: string | null;
  viewed_at: string | null;
  vram_recovery?: {
    recovered_frames: number;
    max_tier: number;
    max_tier_name: string | null;
  } | null;
}

export type AgentStatus = "idle" | "busy" | "offline";

export interface SystemInfo {
  cpu_percent: number;
  ram_total_mb: number;
  ram_used_mb: number;
  ram_percent: number;
  disk_total_mb: number;
  disk_free_mb: number;
  disk_percent: number;
  gpus: {
    id: number;
    name: string;
    load_percent: number;
    vram_total_mb: number;
    vram_used_mb: number;
    vram_percent: number;
    temperature_c: number;
  }[];
}

export interface Agent {
  agent_id: string;
  user_id: string;
  name: string;
  status: AgentStatus;
  last_seen: string | null;
  blend_files: string[];
  blend_files_updated_at: string | null;
  blend_files_info: Record<string, BlendFileInfo> | null;
  system_info: SystemInfo | null;
  created_at: string;
}

export interface BlendFileInfo {
  engine: string;
  resolution_x: number;
  resolution_y: number;
  resolution_percentage: number;
  output_format: string;
  color_depth: string;
  compression: number;
  exr_codec: string;
  film_transparent: boolean;
  frame_start: number;
  frame_end: number;
  frame_step: number;
  active_camera: string | null;
  cameras: string[];
  all_passes?: string[];
  active_passes?: string[];

  // Film & Motion Blur
  pixel_filter_type: string;
  pixel_filter_width: number;
  use_motion_blur: boolean;
  motion_blur_shutter: number;

  // Render Safety
  use_compositing: boolean;
  use_sequencer: boolean;
  dither_intensity: number;
  use_border: boolean;
  use_crop_to_border: boolean;
  use_lock_interface: boolean;
  use_stamp: boolean;
  use_overwrite: boolean;
  use_placeholder: boolean;

  // Performance
  compositor_device: string;

  // Simplify
  simplify?: {
    use_simplify: boolean;
    simplify_subdivision_render: number;
    simplify_child_particles_render: number;
    simplify_volumes: number;
    use_camera_cull: boolean;
    camera_cull_margin: number;
  };

  // Color Management
  color_management?: {
    view_transform: string;
    look: string;
    exposure: number;
    gamma: number;
    available_view_transforms?: string[];
    available_looks?: string[];
  };

  cycles?: {
    // Sampling
    samples: number;
    use_denoising: boolean;
    denoiser: string;
    device: string;
    use_adaptive_sampling: boolean;
    adaptive_threshold: number;
    adaptive_min_samples: number;
    denoising_prefilter: string;
    denoising_input_passes: string;
    denoising_use_gpu: boolean;

    // Light Paths
    max_bounces: number;
    diffuse_bounces: number;
    glossy_bounces: number;
    transmission_bounces: number;
    volume_bounces: number;
    transparent_max_bounces: number;
    sample_clamp_direct: number;
    sample_clamp_indirect: number;
    caustics_reflective: boolean;
    caustics_refractive: boolean;
    blur_glossy: number;

    // Film (Cycles-specific)
    film_transparent_glass: boolean;
    film_transparent_roughness: number;
    motion_blur_position: string;

    // Performance
    use_persistent_data: boolean;
    use_auto_tile: boolean;
    tile_size: number;

    // Simplify GI
    use_light_tree: boolean;
    ao_bounces_render: number;
    texture_limit_render: string;
  };

  eevee?: {
    taa_render_samples: number;
    use_bloom: boolean;
    use_ssr: boolean;
    use_gtao: boolean;
    shadow_cube_size: string;
    shadow_cascade_size: string;
    volumetric_start: number;
    volumetric_end: number;
    volumetric_tile_size: string;
    volumetric_samples: number;
  };
}

export interface RenderOverrides {
  // Common
  resolution_x?: number;
  resolution_y?: number;
  resolution_percentage?: number;
  film_transparent?: boolean;
  color_depth?: string;
  compression?: number;
  active_camera?: string;
  passes?: string[];

  // Output
  exr_codec?: string;

  // Film & Motion Blur
  pixel_filter_type?: string;
  pixel_filter_width?: number;
  use_motion_blur?: boolean;
  motion_blur_shutter?: number;

  // Render Safety
  use_compositing?: boolean;
  use_sequencer?: boolean;
  dither_intensity?: number;
  use_border?: boolean;
  use_crop_to_border?: boolean;
  use_lock_interface?: boolean;
  use_stamp?: boolean;
  use_overwrite?: boolean;
  use_placeholder?: boolean;

  // Color Management
  view_transform?: string;
  look?: string;
  exposure?: number;
  gamma?: number;

  // Simplify
  use_simplify?: boolean;
  simplify_subdivision_render?: number;
  simplify_child_particles_render?: number;
  texture_limit_render?: string;
  simplify_volumes?: number;
  use_camera_cull?: boolean;
  camera_cull_margin?: number;

  // Performance
  compositor_device?: string;

  // Cycles — Sampling
  cycles_samples?: number;
  cycles_use_denoising?: boolean;
  cycles_denoiser?: string;
  cycles_device?: string;
  cycles_use_adaptive_sampling?: boolean;
  cycles_adaptive_threshold?: number;
  cycles_adaptive_min_samples?: number;
  cycles_denoising_prefilter?: string;
  cycles_denoising_input_passes?: string;
  cycles_denoising_use_gpu?: boolean;

  // Cycles — Light Paths
  cycles_max_bounces?: number;
  cycles_diffuse_bounces?: number;
  cycles_glossy_bounces?: number;
  cycles_transmission_bounces?: number;
  cycles_volume_bounces?: number;
  cycles_transparent_max_bounces?: number;
  cycles_sample_clamp_direct?: number;
  cycles_sample_clamp_indirect?: number;
  cycles_caustic_reflective?: boolean;
  cycles_caustic_refractive?: boolean;
  cycles_blur_glossy?: number;

  // Cycles — Film
  cycles_film_transparent_glass?: boolean;
  cycles_film_transparent_roughness?: number;
  cycles_motion_blur_position?: string;

  // Cycles — Performance
  cycles_use_persistent_data?: boolean;
  cycles_use_auto_tile?: boolean;
  cycles_tile_size?: number;

  // Cycles — Simplify GI
  cycles_use_light_tree?: boolean;
  cycles_ao_bounces_render?: number;

  // EEVEE
  eevee_taa_render_samples?: number;
  eevee_use_bloom?: boolean;
  eevee_use_ssr?: boolean;
  eevee_use_gtao?: boolean;
  eevee_shadow_cube_size?: string;
  eevee_shadow_cascade_size?: string;
  eevee_volumetric_start?: number;
  eevee_volumetric_end?: number;
  eevee_volumetric_tile_size?: string;
  eevee_volumetric_samples?: number;
}

export interface AgentToken {
  token_id: string;
  agent_name: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface NotificationPreferences {
  email_enabled: boolean;
  discord_enabled: boolean;
  discord_webhook_url: string | null;
  notify_on_complete: boolean;
  notify_on_failure: boolean;
  notify_on_agent_offline: boolean;
}

export type TierSource = "stripe" | "admin_grant" | "none";

export interface Profile {
  user_id: string;
  name: string;
  created_at: string;
  tier: "free" | "pro";
  tier_source: TierSource;
  active_agent_id: string | null;
  notification_preferences: NotificationPreferences;
  vram_recovery_enabled?: boolean;
  is_admin?: boolean;
  // Stripe subscription info
  subscription_status?: string | null;
  current_period_end?: string | null;
  cancel_at_period_end?: boolean | null;
  // Admin grant info
  has_active_grant?: boolean;
  grant_until?: string | null;
}

// ---------------------------------------------------------------------------
// Admin types
// ---------------------------------------------------------------------------

export interface SystemAnnouncement {
  text: string | null;
  type: "info" | "warning" | "critical";
}

export interface EmergencyPauseState {
  enabled: boolean;
  reason: string | null;
}

export interface AdminSystemStatus {
  emergency_pause: EmergencyPauseState;
  total_users: number;
  online_agents: number;
  offline_agents: number;
  active_jobs: number;
  queued_jobs: number;
}

export interface AdminStats {
  total_users: number;
  online_agents: number;
  offline_agents: number;
  active_jobs: number;
  queued_jobs: number;
  completed_24h: number;
  failed_24h: number;
}

export interface AdminGrant {
  id: string;
  granted_by: string;
  granted_until: string;
  reason: string | null;
  revoked: boolean;
  revoked_at: string | null;
  created_at: string;
}

export interface SubscriptionInfo {
  tier_source: TierSource;
  subscription_status: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean | null;
  has_active_grant: boolean;
  grant_until: string | null;
}

export interface AdminUserDetails {
  profile: {
    user_id: string;
    name: string;
    tier: "free" | "pro";
    created_at: string;
    active_agent_id: string | null;
  } | null;
  subscription: SubscriptionInfo;
  grants: AdminGrant[];
  agents: {
    agent_id: string;
    name: string;
    status: AgentStatus;
    last_seen: string | null;
    created_at: string;
  }[];
  jobs: {
    job_id: string;
    status: JobStatus;
    blend_relpath: string;
    frame_start: number;
    frame_end: number;
    progress: number;
    fail_reason: string | null;
    created_at: string;
    completed_at: string | null;
    failed_at: string | null;
    agent_id: string | null;
  }[];
}

export interface AuditLogEntry {
  event: string;
  user_id: string | null;
  agent_id: string | null;
  job_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}
