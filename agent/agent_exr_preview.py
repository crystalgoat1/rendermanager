import os
import subprocess
import json
import tempfile
import sys
from typing import List, Optional

# The Blender python script to extract passes via the compositor
_EXTRACT_SCRIPT_CONTENT = """
import bpy
import sys
import os
import json

try:
    idx_double_dash = sys.argv.index("--")
    exr_path = sys.argv[idx_double_dash + 1]
    out_dir = sys.argv[idx_double_dash + 2]
    out_json = sys.argv[idx_double_dash + 3]
except (ValueError, IndexError):
    print("Invalid arguments.")
    sys.exit(1)

os.makedirs(out_dir, exist_ok=True)

bpy.context.scene.use_nodes = True
tree = bpy.context.scene.node_tree
tree.nodes.clear()

img_node = tree.nodes.new(type="CompositorNodeImage")
try:
    img = bpy.data.images.load(exr_path)
    img_node.image = img
except Exception as e:
    print(f"Failed to load image: {e}")
    sys.exit(1)

# All outputs of the image node represent available passes/layers
available_passes = []
for output in img_node.outputs:
    # "Alpha" alone isn't highly useful, omit if desired, but we'll include it for completeness if needed
    if output.enabled:
        available_passes.append(output.name)

# Create a File Output node to save them out as JPEG
out_node = tree.nodes.new(type="CompositorNodeOutputFile")
out_node.base_path = out_dir
out_node.format.file_format = 'JPEG'
out_node.format.quality = 85

# Clear default inputs (usually 'Image')
for intput in list(out_node.inputs):
    out_node.inputs.remove(intput)

# Connect each pass to the output node
for pass_name in available_passes:
    # The File Output node saves files named after the socket, e.g. "Depth0001.jpg"
    out_node.file_slots.new(pass_name)
    in_socket = out_node.inputs[-1]
    
    # Optional: For data passes like Depth, Normal, we might need to normalize them 
    # to be visible as JPEGs. A "Viewer" node or simply saving it direct works for a basic preview.
    # To keep it simple, we pipe it direct. Values > 1 will clamp to white, < 0 to black.
    tree.links.new(img_node.outputs[pass_name], in_socket)

# Render resolution needs to match the image so the compositor output isn't cropped/scaled
bpy.context.scene.render.resolution_x = img.size[0]
bpy.context.scene.render.resolution_y = img.size[1]
bpy.context.scene.render.resolution_percentage = 100

# Execute the compositor
try:
    bpy.ops.render.render(write_still=False)
except Exception as e:
    print(f"Failed to render: {e}")
    sys.exit(1)

# Write the list of passes to a JSON file so the agent knows what was extracted
with open(out_json, "w", encoding="utf-8") as f:
    json.dump({"passes": available_passes}, f)

print(f"Successfully extracted {len(available_passes)} passes to {out_dir}")
"""

def extract_exr_passes_with_blender(blender_path: str, exr_path: str) -> Optional[dict]:
    """
    Spawns a headless Blender process to extract the layers from a Multilayer EXR
    into separate JPEG files in a temporary directory.

    Args:
        blender_path: Path to the Blender executable
        exr_path: Path to the EXR file

    Returns:
        A dict containing:
        {
            "passes": ["Combined", "Depth", "Normal", ...],
            "temp_dir": "/path/to/extracted/jpegs", 
            "extracted_files": {
                "Combined": "/path/to/extracted/jpegs/Combined0001.jpg",
                "Depth": "/path/to/extracted/jpegs/Depth0001.jpg",
                ...
            }
        }
        or None if extraction fails.
    """
    if not os.path.exists(exr_path):
        return None

    # We need a temp directory for the extracted JPEGs
    temp_out_dir = tempfile.mkdtemp(prefix="agent_exr_previews_")
    
    # We need a temp script file to run in Blender
    script_fd, script_path = tempfile.mkstemp(suffix=".py", prefix="extract_script_")
    with os.fdopen(script_fd, "w", encoding="utf-8") as f:
        f.write(_EXTRACT_SCRIPT_CONTENT)

    # We need a temp JSON file to read the result
    json_path = os.path.join(temp_out_dir, "passes.json")

    cmd = [
        blender_path,
        "-b",
        "--factory-startup",
        "-P", script_path,
        "--",
        exr_path,
        temp_out_dir,
        json_path
    ]

    try:
        import sys
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        
        if proc.returncode != 0:
            print(f"[exr_preview] Blender extraction failed (rc={proc.returncode}):\n{proc.stderr}")
            return None

        if not os.path.exists(json_path):
            print(f"[exr_preview] JSON result file not found.")
            return None

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        passes = data.get("passes", [])
        
        # The CompositorOutputFile node appends "0001" if frame range is set to 1, or just the frame number.
        # Since we ran `bpy.ops.render.render()` without a specific frame bound, 
        # Blender uses the current scene frame which is 1 by default.
        # So files look like "Combined0001.jpg".
        
        extracted_files = {}
        for p in passes:
            # We must find the correct jpg file. It usually appends frame number.
            # Easiest way is to check if exactly one file starts with this pass name.
            # File slots replace problematic chars internally sometimes, but simple names stay simple.
            possible_files = [f for f in os.listdir(temp_out_dir) if f.startswith(p) and f.endswith(".jpg")]
            if possible_files:
                extracted_files[p] = os.path.join(temp_out_dir, possible_files[0])

        return {
            "passes": list(extracted_files.keys()),
            "temp_dir": temp_out_dir,
            "extracted_files": extracted_files
        }

    except subprocess.TimeoutExpired:
        print(f"[exr_preview] Blender extraction timed out.")
        return None
    except Exception as e:
        print(f"[exr_preview] Error extracting EXR: {e}")
        return None
    finally:
        # Cleanup the python script
        try:
            os.remove(script_path)
        except OSError:
            pass


# ── Lightweight OpenEXR extraction (no Blender needed) ──────────────────

_DEPTH_PASS_NAMES = frozenset({"Depth", "Z", "Mist"})
_NORMAL_PASS_NAMES = frozenset({"Normal"})
_VECTOR_PASS_NAMES = frozenset({"Vector", "Speed"})


def _group_exr_channels(channel_names):
    """Group EXR channel names into render passes.

    Blender multilayer:  "ViewLayer.Combined.R", "ViewLayer.Depth.Z"
    Single-layer:        "R", "G", "B", "A"
    """
    groups = {}
    for ch in channel_names:
        parts = ch.split(".")
        if len(parts) == 1:
            display, letter = "Image", parts[0]
        elif len(parts) == 2:
            display, letter = parts[0], parts[1]
        else:
            display, letter = parts[-2], parts[-1]
        groups.setdefault(display, {})[letter] = ch
    return groups


def _tonemap_color(rgb):
    """Reinhard tone-map + sRGB gamma for HDR color data."""
    import numpy as np
    from PIL import Image as _PILImage

    rgb = np.maximum(rgb, 0.0)
    rgb = rgb / (1.0 + rgb)
    rgb = np.power(rgb, 1.0 / 2.2)
    return _PILImage.fromarray((rgb * 255).clip(0, 255).astype(np.uint8), "RGB")


def _tonemap_depth(arr):
    """Normalize depth to grayscale (near=bright, far=dark)."""
    import numpy as np
    from PIL import Image as _PILImage

    finite = np.isfinite(arr)
    if not finite.any():
        return _PILImage.fromarray(
            np.full(arr.shape, 128, dtype=np.uint8), "L"
        ).convert("RGB")

    vals = arr[finite]
    vmin, vmax = float(vals.min()), float(vals.max())
    if vmax <= vmin:
        out = np.zeros_like(arr, dtype=np.uint8)
    else:
        norm = np.where(finite, (arr - vmin) / (vmax - vmin), 1.0)
        out = ((1.0 - norm) * 255).clip(0, 255).astype(np.uint8)
    return _PILImage.fromarray(out, "L").convert("RGB")


def _extract_single_pass(exr_file, pass_name, channels, pt, h, w):
    """Extract one render pass to a PIL Image."""
    import numpy as np
    from PIL import Image as _PILImage

    def rd(name):
        return np.frombuffer(exr_file.channel(name, pt), dtype=np.float32).reshape(h, w)

    ch_keys = set(channels.keys())

    # Depth
    if pass_name in _DEPTH_PASS_NAMES or ch_keys == {"Z"}:
        ch = channels.get("Z") or next(iter(channels.values()))
        return _tonemap_depth(rd(ch))

    # Normal
    if pass_name in _NORMAL_PASS_NAMES and ch_keys >= {"X", "Y", "Z"}:
        rgb = np.stack([rd(channels[c]) for c in "XYZ"], axis=-1)
        return _PILImage.fromarray(
            ((rgb + 1.0) * 127.5).clip(0, 255).astype(np.uint8), "RGB"
        )

    # Vector / data
    if pass_name in _VECTOR_PASS_NAMES:
        arrs = [rd(channels[k]) for k in sorted(channels)]
        if len(arrs) >= 3:
            rgb = np.stack(arrs[:3], axis=-1)
        elif len(arrs) == 2:
            rgb = np.stack([arrs[0], arrs[1], np.zeros((h, w), np.float32)], axis=-1)
        else:
            rgb = np.stack([arrs[0]] * 3, axis=-1)
        lo, hi = float(rgb.min()), float(rgb.max())
        if hi > lo:
            rgb = (rgb - lo) / (hi - lo)
        return _PILImage.fromarray((rgb * 255).clip(0, 255).astype(np.uint8), "RGB")

    # Color pass (default) — R/G/B channels
    r = rd(channels["R"]) if "R" in channels else np.zeros((h, w), np.float32)
    g = rd(channels["G"]) if "G" in channels else np.zeros((h, w), np.float32)
    b = rd(channels["B"]) if "B" in channels else np.zeros((h, w), np.float32)
    return _tonemap_color(np.stack([r, g, b], axis=-1))


def extract_single_exr_pass(exr_path: str, pass_name: str, output_path: str) -> bool:
    """Extract a single pass from an EXR to a JPEG file.

    Much faster than extract_exr_passes_openexr() when you only need one pass
    (e.g. during animation compilation).

    Returns True on success, False on failure.
    """
    try:
        import OpenEXR
        import Imath
    except ImportError:
        return False

    if not os.path.exists(exr_path):
        return False

    try:
        exr = OpenEXR.InputFile(exr_path)
        header = exr.header()
        dw = header["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1

        passes = _group_exr_channels(header["channels"].keys())
        pt = Imath.PixelType(Imath.PixelType.FLOAT)

        # Find the requested pass
        ch_map = passes.get(pass_name)
        actual_name = pass_name
        
        # Fallback 1: Case-insensitive / fuzzy match (e.g. Emission vs emission, Diffuse vs Diff)
        if not ch_map:
            search_name = pass_name.lower().replace("_", "")
            for p_name, p_chans in passes.items():
                if search_name in p_name.lower().replace("_", ""):
                    ch_map = p_chans
                    actual_name = p_name
                    break
                    
        # Fallback 2: Combined pass
        if not ch_map:
            ch_map = passes.get("Combined")
            actual_name = "Combined" if "Combined" in passes else None
            
        # Fallback 3: First available pass if nothing else matches
        if not ch_map and passes:
            actual_name = next(iter(passes))
            ch_map = passes[actual_name]

        if not ch_map or not actual_name:
            exr.close()
            return False

        img = _extract_single_pass(exr, actual_name, ch_map, pt, h, w)
        exr.close()
        if not img:
            return False

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"[exr_preview] Single-pass extraction failed: {e}")
        return False


def extract_exr_passes_openexr(exr_path: str, output_dir: str = None) -> Optional[dict]:
    """Extract all passes from an EXR using the OpenEXR Python library.

    ~10-60x faster than Blender-based extraction, no GPU needed.
    Returns the same dict format as extract_exr_passes_with_blender(),
    or None if OpenEXR is not installed or extraction fails.
    """
    try:
        import OpenEXR
        import Imath
    except ImportError:
        print("[exr_preview] OpenEXR/Imath not installed — cannot use fast extraction")
        return None

    if not os.path.exists(exr_path):
        return None

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="agent_exr_openexr_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    try:
        exr = OpenEXR.InputFile(exr_path)
        header = exr.header()
        dw = header["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1

        passes = _group_exr_channels(header["channels"].keys())
        pt = Imath.PixelType(Imath.PixelType.FLOAT)

        extracted = {}
        for pname, ch_map in passes.items():
            try:
                img = _extract_single_pass(exr, pname, ch_map, pt, h, w)
                if img:
                    out = os.path.join(output_dir, f"{pname}.jpg")
                    img.save(out, "JPEG", quality=85)
                    extracted[pname] = out
            except Exception as e:
                print(f"[exr_preview] Failed to extract pass '{pname}': {e}")

        exr.close()

        if not extracted:
            return None

        return {
            "passes": list(extracted.keys()),
            "temp_dir": output_dir,
            "extracted_files": extracted,
        }
    except Exception as e:
        print(f"[exr_preview] OpenEXR extraction failed: {e}")
        return None


def get_exr_pass_names(exr_path: str) -> list[str]:
    """Read pass names from an EXR header without extracting any pixel data.

    Very fast — only reads file metadata, no decompression or image processing.
    Returns a list of pass names (e.g. ["Combined", "DiffCol", "GlossCol", ...])
    or an empty list on failure.
    """
    try:
        import OpenEXR
    except ImportError:
        return []

    if not os.path.exists(exr_path):
        return []

    try:
        exr = OpenEXR.InputFile(exr_path)
        header = exr.header()
        passes = _group_exr_channels(header["channels"].keys())
        exr.close()
        return list(passes.keys())
    except Exception:
        return []
