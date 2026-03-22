# server/server_validation.py
#
# Server-side validation for render override values.
# Mirrors the type/range checks from agent_override.py as defense-in-depth.
# The agent also validates, but with open-source agents we can't trust the client.

from typing import Any, Optional


# Each entry: key -> (type, *constraints)
#   int:   (int, min, max)
#   float: (float, min, max)
#   bool:  (bool,)
#   str:   (str, {allowed_values})  or  (str, None) for open set
#   list:  (list, element_type)

OVERRIDE_TYPES: dict[str, tuple] = {
    # Common (all engines)
    "resolution_x":          (int, 1, 16384),
    "resolution_y":          (int, 1, 16384),
    "resolution_percentage": (int, 1, 100),
    "film_transparent":      (bool,),
    "color_depth":           (str, {"8", "16", "32"}),
    "compression":           (int, 0, 100),
    "active_camera":         (str, None),
    "passes":                (list, str),

    # Output
    "exr_codec":             (str, {"NONE", "PXR24", "ZIP", "PIZ", "RLE",
                                    "ZIPS", "B44", "B44A", "DWAA", "DWAB"}),

    # Film & Motion Blur
    "pixel_filter_type":     (str, {"BOX", "TENT", "GAUSSIAN", "MITCHELL",
                                    "CATMULLROM", "CUBIC"}),
    "pixel_filter_width":    (float, 0.01, 10.0),
    "use_motion_blur":       (bool,),
    "motion_blur_shutter":   (float, 0.0, 100.0),

    # Render Safety
    "use_compositing":       (bool,),
    "use_sequencer":         (bool,),
    "dither_intensity":      (float, 0.0, 2.0),
    "use_border":            (bool,),
    "use_crop_to_border":    (bool,),
    "use_lock_interface":    (bool,),
    "use_stamp":             (bool,),
    "use_overwrite":         (bool,),
    "use_placeholder":       (bool,),

    # Color Management
    "view_transform":        (str, None),
    "look":                  (str, None),
    "exposure":              (float, -32.0, 32.0),
    "gamma":                 (float, 0.001, 5.0),

    # Simplify
    "use_simplify":                    (bool,),
    "simplify_subdivision_render":     (int, 0, 6),
    "simplify_child_particles_render": (float, 0.0, 1.0),
    "texture_limit_render":            (str, {"OFF", "128", "256", "512",
                                              "1024", "2048", "4096", "8192"}),
    "simplify_volumes":                (float, 0.0, 1.0),
    "use_camera_cull":                 (bool,),
    "camera_cull_margin":              (float, 0.0, 5.0),

    # Performance
    "compositor_device":     (str, {"CPU", "GPU"}),

    # Cycles — Sampling
    "cycles_samples":               (int, 1, 100000),
    "cycles_use_denoising":         (bool,),
    "cycles_denoiser":              (str, {"OPENIMAGEDENOISE", "OPTIX"}),
    "cycles_device":                (str, {"CPU", "GPU"}),
    "cycles_use_adaptive_sampling": (bool,),
    "cycles_adaptive_threshold":    (float, 0.0, 1.0),
    "cycles_adaptive_min_samples":  (int, 0, 65536),
    "cycles_denoising_prefilter":   (str, {"NONE", "FAST", "ACCURATE"}),
    "cycles_denoising_input_passes": (str, {"RGB", "RGB_ALBEDO",
                                            "RGB_ALBEDO_NORMAL"}),
    "cycles_denoising_use_gpu":     (bool,),

    # Cycles — Light Paths
    "cycles_max_bounces":             (int, 0, 1024),
    "cycles_diffuse_bounces":         (int, 0, 1024),
    "cycles_glossy_bounces":          (int, 0, 1024),
    "cycles_transmission_bounces":    (int, 0, 1024),
    "cycles_volume_bounces":          (int, 0, 1024),
    "cycles_transparent_max_bounces": (int, 0, 1024),
    "cycles_sample_clamp_direct":     (float, 0.0, 1e10),
    "cycles_sample_clamp_indirect":   (float, 0.0, 1e10),
    "cycles_caustic_reflective":      (bool,),
    "cycles_caustic_refractive":      (bool,),
    "cycles_blur_glossy":             (float, 0.0, 10.0),

    # Cycles — Film
    "cycles_film_transparent_glass":     (bool,),
    "cycles_film_transparent_roughness": (float, 0.0, 1.0),
    "cycles_motion_blur_position":       (str, {"START", "CENTER", "END"}),

    # Cycles — Performance
    "cycles_use_persistent_data": (bool,),
    "cycles_use_auto_tile":       (bool,),
    "cycles_tile_size":           (int, 8, 16384),

    # Cycles — Simplify GI
    "cycles_use_light_tree":    (bool,),
    "cycles_ao_bounces_render": (int, 0, 1024),

    # EEVEE
    "eevee_taa_render_samples":   (int, 1, 65536),
    "eevee_use_bloom":            (bool,),
    "eevee_use_ssr":              (bool,),
    "eevee_use_gtao":             (bool,),
    "eevee_shadow_cube_size":     (str, {"64", "128", "256", "512",
                                         "1024", "2048", "4096"}),
    "eevee_shadow_cascade_size":  (str, {"64", "128", "256", "512",
                                         "1024", "2048", "4096"}),
    "eevee_volumetric_start":     (float, 0.0, 10000.0),
    "eevee_volumetric_end":       (float, 0.0, 10000.0),
    "eevee_volumetric_tile_size": (str, {"2", "4", "8", "16"}),
    "eevee_volumetric_samples":   (int, 1, 256),
}


def validate_override_value(key: str, value: Any) -> Optional[Any]:
    """Validate a single override value against the type spec.

    Returns the sanitized value, or None if invalid.
    """
    spec = OVERRIDE_TYPES.get(key)
    if spec is None:
        return None

    expected_type = spec[0]

    if expected_type is int:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        v = int(value)
        lo, hi = spec[1], spec[2]
        return v if lo <= v <= hi else None

    elif expected_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        v = float(value)
        lo, hi = spec[1], spec[2]
        return v if lo <= v <= hi else None

    elif expected_type is bool:
        return value if isinstance(value, bool) else None

    elif expected_type is str:
        if not isinstance(value, str):
            return None
        # Cap string length to prevent abuse
        if len(value) > 200:
            return None
        if len(spec) > 1 and spec[1] is not None:
            return value if value in spec[1] else None
        return value

    elif expected_type is list:
        if not isinstance(value, list):
            return None
        elem_type = spec[1]
        if elem_type is str:
            if not all(isinstance(x, str) and len(x) <= 200 for x in value):
                return None
        return value

    return None
