# agent/agent_override.py
#
# Generates a secure Blender override script from validated settings.
# Only whitelisted keys with strict type/range validation are accepted.
# The generated script sets scene properties via bpy — the .blend file
# on disk is NEVER modified.

import os
import tempfile
from typing import Any, Optional

# ── Allowlist of override keys ───────────────────────────────────────────────
# Each entry: key → (type, *constraints)
#   int:   (int, min, max)
#   float: (float, min, max)
#   bool:  (bool,)
#   str:   (str, {allowed_values})  or  (str, None) for open set

ALLOWED_OVERRIDES: dict[str, tuple] = {
    # ── Common (all engines) ─────────────────────────────────────────────────
    "resolution_x":          (int, 1, 16384),
    "resolution_y":          (int, 1, 16384),
    "resolution_percentage": (int, 1, 100),
    "film_transparent":      (bool,),
    "color_depth":           (str, {"8", "16", "32"}),
    "compression":           (int, 0, 100),
    "active_camera":         (str, None),
    "passes":                (list, str),

    # ── Output ───────────────────────────────────────────────────────────────
    "exr_codec":             (str, {"NONE", "PXR24", "ZIP", "PIZ", "RLE",
                                    "ZIPS", "B44", "B44A", "DWAA", "DWAB"}),

    # ── Film & Motion Blur ───────────────────────────────────────────────────
    "pixel_filter_type":     (str, {"BOX", "TENT", "GAUSSIAN", "MITCHELL",
                                    "CATMULLROM", "CUBIC"}),
    "pixel_filter_width":    (float, 0.01, 10.0),
    "use_motion_blur":       (bool,),
    "motion_blur_shutter":   (float, 0.0, 100.0),

    # ── Render Safety ────────────────────────────────────────────────────────
    "use_compositing":       (bool,),
    "use_sequencer":         (bool,),
    "dither_intensity":      (float, 0.0, 2.0),
    "use_border":            (bool,),
    "use_crop_to_border":    (bool,),
    "use_lock_interface":    (bool,),
    "use_stamp":             (bool,),
    "use_overwrite":         (bool,),
    "use_placeholder":       (bool,),

    # ── Color Management ─────────────────────────────────────────────────────
    "view_transform":        (str, None),
    "look":                  (str, None),
    "exposure":              (float, -32.0, 32.0),
    "gamma":                 (float, 0.001, 5.0),

    # ── Simplify (common) ────────────────────────────────────────────────────
    "use_simplify":                    (bool,),
    "simplify_subdivision_render":     (int, 0, 6),
    "simplify_child_particles_render": (float, 0.0, 1.0),
    "texture_limit_render":            (str, {"OFF", "128", "256", "512",
                                              "1024", "2048", "4096", "8192"}),
    "simplify_volumes":                (float, 0.0, 1.0),
    "use_camera_cull":                 (bool,),
    "camera_cull_margin":              (float, 0.0, 5.0),

    # ── Performance (common) ─────────────────────────────────────────────────
    "compositor_device":     (str, {"CPU", "GPU"}),

    # ── Cycles ───────────────────────────────────────────────────────────────
    # Sampling
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

    # Light Paths
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

    # Film (Cycles-specific)
    "cycles_film_transparent_glass":     (bool,),
    "cycles_film_transparent_roughness": (float, 0.0, 1.0),
    "cycles_motion_blur_position":       (str, {"START", "CENTER", "END"}),

    # Performance (Cycles)
    "cycles_use_persistent_data": (bool,),
    "cycles_use_auto_tile":       (bool,),
    "cycles_tile_size":           (int, 8, 16384),

    # Simplify GI (Cycles)
    "cycles_use_light_tree":    (bool,),
    "cycles_ao_bounces_render": (int, 0, 1024),

    # ── EEVEE ────────────────────────────────────────────────────────────────
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

# Maps override key → bpy assignment (left side of `=`)
BPY_PATHS: dict[str, str] = {
    # ── Common ───────────────────────────────────────────────────────────────
    "resolution_x":          "bpy.context.scene.render.resolution_x",
    "resolution_y":          "bpy.context.scene.render.resolution_y",
    "resolution_percentage": "bpy.context.scene.render.resolution_percentage",
    "film_transparent":      "bpy.context.scene.render.film_transparent",
    "color_depth":           "bpy.context.scene.render.image_settings.color_depth",
    "compression":           "bpy.context.scene.render.image_settings.compression",
    "exr_codec":             "bpy.context.scene.render.image_settings.exr_codec",

    # Film & Motion Blur
    "pixel_filter_type":     "bpy.context.scene.render.filter_type",
    "pixel_filter_width":    "bpy.context.scene.render.filter_size",
    "use_motion_blur":       "bpy.context.scene.render.use_motion_blur",
    "motion_blur_shutter":   "bpy.context.scene.render.motion_blur_shutter",

    # Render Safety
    "use_compositing":       "bpy.context.scene.render.use_compositing",
    "use_sequencer":         "bpy.context.scene.render.use_sequencer",
    "dither_intensity":      "bpy.context.scene.render.dither_intensity",
    "use_border":            "bpy.context.scene.render.use_border",
    "use_crop_to_border":    "bpy.context.scene.render.use_crop_to_border",
    "use_lock_interface":    "bpy.context.scene.render.use_lock_interface",
    "use_stamp":             "bpy.context.scene.render.use_stamp",
    "use_overwrite":         "bpy.context.scene.render.use_overwrite",
    "use_placeholder":       "bpy.context.scene.render.use_placeholder",

    # Color Management
    "view_transform":        "bpy.context.scene.view_settings.view_transform",
    "look":                  "bpy.context.scene.view_settings.look",
    "exposure":              "bpy.context.scene.view_settings.exposure",
    "gamma":                 "bpy.context.scene.view_settings.gamma",

    # Simplify
    "use_simplify":                    "bpy.context.scene.render.use_simplify",
    "simplify_subdivision_render":     "bpy.context.scene.render.simplify_subdivision_render",
    "simplify_child_particles_render": "bpy.context.scene.render.simplify_child_particles_render",
    "simplify_volumes":                "bpy.context.scene.render.simplify_volumes",
    # NOTE: use_camera_cull / camera_cull_margin removed in Blender 4.5.
    # Kept for older Blender versions; the try/except in the generated script
    # handles the AttributeError gracefully if these don't exist.
    "use_camera_cull":                 "bpy.context.scene.render.use_camera_cull",
    "camera_cull_margin":              "bpy.context.scene.render.camera_cull_margin",

    # Performance
    "compositor_device":     "bpy.context.scene.render.compositor_device",

    # ── Cycles ───────────────────────────────────────────────────────────────
    "cycles_samples":               "bpy.context.scene.cycles.samples",
    "cycles_use_denoising":         "bpy.context.scene.cycles.use_denoising",
    "cycles_denoiser":              "bpy.context.scene.cycles.denoiser",
    "cycles_device":                "bpy.context.scene.cycles.device",
    "cycles_use_adaptive_sampling": "bpy.context.scene.cycles.use_adaptive_sampling",
    "cycles_adaptive_threshold":    "bpy.context.scene.cycles.adaptive_threshold",
    "cycles_adaptive_min_samples":  "bpy.context.scene.cycles.adaptive_min_samples",
    "cycles_denoising_prefilter":   "bpy.context.scene.cycles.denoising_prefilter",
    "cycles_denoising_input_passes": "bpy.context.scene.cycles.denoising_input_passes",
    "cycles_denoising_use_gpu":      "bpy.context.scene.cycles.denoising_use_gpu",

    # Light Paths
    "cycles_max_bounces":             "bpy.context.scene.cycles.max_bounces",
    "cycles_diffuse_bounces":         "bpy.context.scene.cycles.diffuse_bounces",
    "cycles_glossy_bounces":          "bpy.context.scene.cycles.glossy_bounces",
    "cycles_transmission_bounces":    "bpy.context.scene.cycles.transmission_bounces",
    "cycles_volume_bounces":          "bpy.context.scene.cycles.volume_bounces",
    "cycles_transparent_max_bounces": "bpy.context.scene.cycles.transparent_max_bounces",
    "cycles_sample_clamp_direct":     "bpy.context.scene.cycles.sample_clamp_direct",
    "cycles_sample_clamp_indirect":   "bpy.context.scene.cycles.sample_clamp_indirect",
    "cycles_caustic_reflective":      "bpy.context.scene.cycles.caustics_reflective",
    "cycles_caustic_refractive":      "bpy.context.scene.cycles.caustics_refractive",
    "cycles_blur_glossy":             "bpy.context.scene.cycles.blur_glossy",

    # Film (Cycles)
    "cycles_film_transparent_glass":     "bpy.context.scene.cycles.film_transparent_glass",
    "cycles_film_transparent_roughness": "bpy.context.scene.cycles.film_transparent_roughness",
    "cycles_motion_blur_position":       "bpy.context.scene.cycles.motion_blur_position",

    # Performance (Cycles)
    "cycles_use_persistent_data": "bpy.context.scene.render.use_persistent_data",
    "cycles_use_auto_tile":       "bpy.context.scene.cycles.use_auto_tile",
    "cycles_tile_size":           "bpy.context.scene.cycles.tile_size",

    # Simplify GI (Cycles)
    "cycles_use_light_tree":      "bpy.context.scene.cycles.use_light_tree",
    "cycles_ao_bounces_render":   "bpy.context.scene.cycles.ao_bounces_render",
    "texture_limit_render":       "bpy.context.scene.cycles.texture_limit_render",

    # ── EEVEE ────────────────────────────────────────────────────────────────
    "eevee_taa_render_samples":   "bpy.context.scene.eevee.taa_render_samples",
    "eevee_use_bloom":            "bpy.context.scene.eevee.use_bloom",
    "eevee_use_ssr":              "bpy.context.scene.eevee.use_ssr",
    "eevee_use_gtao":             "bpy.context.scene.eevee.use_gtao",
    "eevee_shadow_cube_size":     "bpy.context.scene.eevee.shadow_cube_size",
    "eevee_shadow_cascade_size":  "bpy.context.scene.eevee.shadow_cascade_size",
    "eevee_volumetric_start":     "bpy.context.scene.eevee.volumetric_start",
    "eevee_volumetric_end":       "bpy.context.scene.eevee.volumetric_end",
    "eevee_volumetric_tile_size": "bpy.context.scene.eevee.volumetric_tile_size",
    "eevee_volumetric_samples":   "bpy.context.scene.eevee.volumetric_samples",
}


def validate_override(key: str, value: Any) -> Optional[Any]:
    """Validate a single override value. Returns sanitized value or None."""
    spec = ALLOWED_OVERRIDES.get(key)
    if spec is None:
        return None  # Unknown key — reject silently

    expected_type = spec[0]

    if expected_type is int:
        if not isinstance(value, (int, float)):
            return None
        v = int(value)
        lo, hi = spec[1], spec[2]
        if not (lo <= v <= hi):
            return None
        return v

    elif expected_type is float:
        if not isinstance(value, (int, float)):
            return None
        v = float(value)
        lo, hi = spec[1], spec[2]
        if not (lo <= v <= hi):
            return None
        return v

    elif expected_type is bool:
        if not isinstance(value, bool):
            return None
        return value

    elif expected_type is str:
        if not isinstance(value, str):
            return None
        if len(spec) > 1 and spec[1] is not None:
            allowed = spec[1]
            if value not in allowed:
                return None
        return value

    elif expected_type is list:
        if not isinstance(value, list):
            return None
        elem_type = spec[1]
        if elem_type is str:
            if not all(isinstance(x, str) for x in value):
                return None
        # Could add other element types if needed in the future
        return value

    return None


def validate_overrides(raw: dict) -> dict:
    """Validate all overrides, returning only valid key-value pairs."""
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key, value in raw.items():
        validated = validate_override(key, value)
        if validated is not None:
            result[key] = validated
    return result


def _python_literal(value: Any) -> str:
    """Convert a validated value to a Python literal string."""
    if isinstance(value, bool):
        return "True" if value else "False"
    elif isinstance(value, float):
        return repr(value)
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, str):
        # We allow custom strings for camera names, so we must quote and escape safely
        safe_str = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{safe_str}"'
    elif isinstance(value, list):
        # Convert list of strings
        if all(isinstance(x, str) for x in value):
            items = [_python_literal(x) for x in value]
            return "[" + ", ".join(items) + "]"
    raise ValueError(f"Unexpected type: {type(value)}")


def generate_override_script(overrides: dict, job_id: str, temp_dir: str) -> Optional[str]:
    """Generate a temp Python file with bpy assignments.

    Returns the file path, or None if no valid overrides.
    The caller MUST delete this file after the render completes.
    """
    validated = validate_overrides(overrides)
    if not validated:
        return None

    lines = ["import bpy", ""]
    lines.append("print('[RM Override] Script running...')")

    for key, value in validated.items():
        if key == "active_camera":
            lines.append("try:")
            lines.append(f"    cam = bpy.data.objects.get({_python_literal(value)})")
            lines.append("    if cam and cam.type == 'CAMERA':")
            lines.append("        bpy.context.scene.camera = cam")
            lines.append("except Exception as e:")
            lines.append("    print('Failed to set camera overrides:', e)")
            continue
            
        if key == "passes":
            lines.append("try:")
            lines.append("    vl = bpy.context.scene.view_layers[0]")
            lines.append("    passes_to_enable = set(" + _python_literal(value) + ")")
            # First map over all pass properties
            lines.append("    for prop in dir(vl):")
            lines.append("        if prop.startswith('use_pass_'):")
            lines.append("            try:")
            lines.append("                should_enable = prop in passes_to_enable")
            lines.append("                setattr(vl, prop, should_enable)")
            lines.append("            except Exception:")
            lines.append("                pass")
            lines.append("except Exception as e:")
            lines.append("    print('Failed to set passes overrides:', e)")
            continue
    
        bpy_path = BPY_PATHS.get(key)
        if bpy_path is None:
            continue

        # Wrap every assignment in try/except so one missing/renamed
        # property (e.g. use_camera_cull removed in Blender 4.5) can't
        # kill the entire override script.
        lines.append(f"try:")
        lines.append(f"    {bpy_path} = {_python_literal(value)}")
        lines.append(f"    print(f'[RM Override] {key} = {_python_literal(value)}')")
        lines.append(f"except Exception as _e:")
        lines.append(f"    print(f'[RM Override] SKIP {key}: {{_e}}')")

    lines.append("print('[RM Override] Script complete.')")
    lines.append("")  # trailing newline

    # Write to temp dir with a safe filename
    safe_id = "".join(c for c in job_id if c.isalnum() or c in "-_")[:64]
    script_path = os.path.join(temp_dir, f"override_{safe_id}.py")
    os.makedirs(temp_dir, exist_ok=True)

    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return script_path

