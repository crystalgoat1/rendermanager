# agent/agent_blend_info.py
#
# Reads render settings from a .blend file by running Blender headless.
# The BPY_READER_SCRIPT is executed inside Blender; its stdout is parsed.

import json
import os
import subprocess
import textwrap
from typing import Optional

# ── Script that runs INSIDE Blender ──────────────────────────────────────────
# Prints a JSON blob to stdout, prefixed with a sentinel so we can parse it
# reliably even if Blender prints other messages.

BPY_READER_SCRIPT = textwrap.dedent(r"""
import bpy, json, sys

try:
    scene = bpy.context.scene
    rd = scene.render

    info = {
        "engine": rd.engine,
        "resolution_x": rd.resolution_x,
        "resolution_y": rd.resolution_y,
        "resolution_percentage": rd.resolution_percentage,
        "output_format": rd.image_settings.file_format,
        "color_depth": getattr(rd.image_settings, "color_depth", "8"),
        "compression": getattr(rd.image_settings, "compression", 15),
        "exr_codec": getattr(rd.image_settings, "exr_codec", "ZIP"),
        "film_transparent": rd.film_transparent,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "active_camera": scene.camera.name if scene.camera else None,
        "cameras": [o.name for o in bpy.data.objects if o.type == "CAMERA"],

        # Film & Motion Blur
        "pixel_filter_type": getattr(rd, "filter_type", "GAUSSIAN"),
        "pixel_filter_width": getattr(rd, "filter_size", 1.5),
        "use_motion_blur": getattr(rd, "use_motion_blur", False),
        "motion_blur_shutter": getattr(rd, "motion_blur_shutter", 0.5),

        # Render Safety
        "use_compositing": getattr(rd, "use_compositing", True),
        "use_sequencer": getattr(rd, "use_sequencer", True),
        "dither_intensity": getattr(rd, "dither_intensity", 1.0),
        "use_border": getattr(rd, "use_border", False),
        "use_crop_to_border": getattr(rd, "use_crop_to_border", False),
        "use_lock_interface": getattr(rd, "use_lock_interface", False),
        "use_stamp": getattr(rd, "use_stamp", False),
        "use_overwrite": getattr(rd, "use_overwrite", True),
        "use_placeholder": getattr(rd, "use_placeholder", False),

        # Performance
        "compositor_device": getattr(rd, "compositor_device", "CPU"),

        # Simplify
        "simplify": {
            "use_simplify": getattr(rd, "use_simplify", False),
            "simplify_subdivision_render": getattr(rd, "simplify_subdivision_render", 6),
            "simplify_child_particles_render": getattr(rd, "simplify_child_particles_render", 1.0),
            "simplify_volumes": getattr(rd, "simplify_volumes", 1.0),
            "use_camera_cull": getattr(rd, "use_camera_cull", False),
            "camera_cull_margin": getattr(rd, "camera_cull_margin", 0.1),
        },

        # Color Management
        "color_management": {
            "view_transform": getattr(scene.view_settings, "view_transform", "Filmic"),
            "look": getattr(scene.view_settings, "look", "None"),
            "exposure": getattr(scene.view_settings, "exposure", 0.0),
            "gamma": getattr(scene.view_settings, "gamma", 1.0),
        },
    }

    # Read available view transforms and looks from OCIO config.
    # Try multiple approaches — bl_rna enum_items can fail in some Blender builds.
    # In --background mode, OCIO may not be fully initialized and enum_items
    # can return just ["NONE"] as a placeholder — filter those out.
    try:
        vt_prop = scene.view_settings.bl_rna.properties.get("view_transform")
        if vt_prop and hasattr(vt_prop, "enum_items"):
            items = [item.identifier for item in vt_prop.enum_items if item.identifier != "NONE"]
            if items:
                info["color_management"]["available_view_transforms"] = items
    except Exception:
        pass

    try:
        look_prop = scene.view_settings.bl_rna.properties.get("look")
        if look_prop and hasattr(look_prop, "enum_items"):
            items = [item.identifier for item in look_prop.enum_items]
            # Filter out the bare "NONE" placeholder but keep "None" (valid look name)
            items = [i for i in items if i != "NONE"]
            if items:
                info["color_management"]["available_looks"] = items
    except Exception:
        pass

    # Fallback: read OCIO config directly if enum_items failed
    if "available_view_transforms" not in info["color_management"]:
        try:
            import PyOpenColorIO as OCIO
            config = OCIO.GetCurrentConfig()
            vts = []
            for i in range(config.getNumViews(config.getDefaultDisplay())):
                vts.append(config.getView(config.getDefaultDisplay(), i))
            if vts:
                info["color_management"]["available_view_transforms"] = vts
        except Exception:
            pass

    if "available_looks" not in info["color_management"]:
        try:
            import PyOpenColorIO as OCIO
            config = OCIO.GetCurrentConfig()
            looks = ["None"] + [config.getLook(i).getName() for i in range(config.getNumLooks())]
            if looks:
                info["color_management"]["available_looks"] = looks
        except Exception:
            pass
    
    vl = scene.view_layers[0] if scene.view_layers else None
    if vl:
        all_passes = []
        active_passes = []
        for prop in dir(vl):
            if prop.startswith("use_pass_"):
                try:
                    # Accessing some properties can raise errors if they are unsupported by the engine, so we test readability
                    val = getattr(vl, prop)
                    all_passes.append(prop)
                    if val is True:
                        active_passes.append(prop)
                except Exception:
                    pass
        info["all_passes"] = all_passes
        info["active_passes"] = active_passes

    # Engine-specific settings
    if rd.engine == "CYCLES":
        c = scene.cycles
        info["cycles"] = {
            # Sampling
            "samples": c.samples,
            "use_denoising": getattr(c, "use_denoising", False),
            "denoiser": getattr(c, "denoiser", "OPENIMAGEDENOISE"),
            "device": c.device,
            "use_adaptive_sampling": getattr(c, "use_adaptive_sampling", True),
            "adaptive_threshold": getattr(c, "adaptive_threshold", 0.01),
            "adaptive_min_samples": getattr(c, "adaptive_min_samples", 0),
            "denoising_prefilter": getattr(c, "denoising_prefilter", "ACCURATE"),
            "denoising_input_passes": getattr(c, "denoising_input_passes", "RGB_ALBEDO_NORMAL"),
            "denoising_use_gpu": getattr(c, "denoising_use_gpu", False),

            # Light Paths
            "max_bounces": getattr(c, "max_bounces", 12),
            "diffuse_bounces": getattr(c, "diffuse_bounces", 4),
            "glossy_bounces": getattr(c, "glossy_bounces", 4),
            "transmission_bounces": getattr(c, "transmission_bounces", 12),
            "volume_bounces": getattr(c, "volume_bounces", 0),
            "transparent_max_bounces": getattr(c, "transparent_max_bounces", 8),
            "sample_clamp_direct": getattr(c, "sample_clamp_direct", 0.0),
            "sample_clamp_indirect": getattr(c, "sample_clamp_indirect", 10.0),
            "caustics_reflective": getattr(c, "caustics_reflective", True),
            "caustics_refractive": getattr(c, "caustics_refractive", True),
            "blur_glossy": getattr(c, "blur_glossy", 1.0),

            # Film (Cycles-specific)
            "film_transparent_glass": getattr(c, "film_transparent_glass", False),
            "film_transparent_roughness": getattr(c, "film_transparent_roughness", 0.1),
            "motion_blur_position": getattr(c, "motion_blur_position", "CENTER"),

            # Performance
            "use_persistent_data": getattr(rd, "use_persistent_data", False),
            "use_auto_tile": getattr(c, "use_auto_tile", True),
            "tile_size": getattr(c, "tile_size", 2048),

            # Simplify GI
            "use_light_tree": getattr(c, "use_light_tree", True),
            "ao_bounces_render": getattr(c, "ao_bounces_render", 0),
            "texture_limit_render": getattr(c, "texture_limit_render", "OFF"),
        }
    elif rd.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        e = scene.eevee
        info["eevee"] = {
            "taa_render_samples": getattr(e, "taa_render_samples", getattr(e, "samples", 64)),
            "use_bloom": getattr(e, "use_bloom", False),
            "use_ssr": getattr(e, "use_ssr", False),
            "use_gtao": getattr(e, "use_gtao", False),
            "shadow_cube_size": getattr(e, "shadow_cube_size", "512"),
            "shadow_cascade_size": getattr(e, "shadow_cascade_size", "1024"),
            "volumetric_start": getattr(e, "volumetric_start", 0.1),
            "volumetric_end": getattr(e, "volumetric_end", 100.0),
            "volumetric_tile_size": getattr(e, "volumetric_tile_size", "8"),
            "volumetric_samples": getattr(e, "volumetric_samples", 64),
        }

    print("BLEND_INFO_JSON:" + json.dumps(info))
except Exception as exc:
    print("BLEND_INFO_ERROR:" + str(exc), file=sys.stderr)
    print("BLEND_INFO_JSON:" + json.dumps({"error": str(exc)}))

sys.exit(0)
""").strip()


def read_blend_info(blender_path: str, blend_file: str, timeout: int = 30) -> Optional[dict]:
    """Run Blender headless to extract render settings from a .blend file.

    Returns a dict of settings, or None if extraction failed.
    """
    if not os.path.isfile(blend_file):
        return None

    # Write the reader script to a secure temp file (not predictable name)
    import tempfile as _tempfile
    fd, script_path = _tempfile.mkstemp(suffix=".py", prefix="blend_info_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(BPY_READER_SCRIPT)

        result = subprocess.run(
            [blender_path, "-b", blend_file, "--python", script_path, "--quit"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        # Parse sentinel line from stdout
        for line in result.stdout.splitlines():
            if line.startswith("BLEND_INFO_JSON:"):
                json_str = line[len("BLEND_INFO_JSON:"):]
                data = json.loads(json_str)
                if "error" in data:
                    print(f"[blend_info] Script error for {blend_file}: {data['error']}")
                    return None
                return data

        # No sentinel found — log last few lines of stderr for debugging
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr else "(empty)"
        print(f"[blend_info] No output for {blend_file} | exit={result.returncode} | stderr: {stderr_tail}")
        return None

    except subprocess.TimeoutExpired:
        print(f"[blend_info] Timeout reading {blend_file}")
        return None
    except Exception as e:
        print(f"[blend_info] Error reading {blend_file}: {e}")
        return None
    finally:
        if script_path:
            try:
                os.remove(script_path)
            except OSError:
                pass
