import bpy
import sys
import os

try:
    exr_path = sys.argv[sys.argv.index("--") + 1]
    out_dir = sys.argv[sys.argv.index("--") + 2]
except ValueError:
    print("Usage: blender -b -P script.py -- <exr_path> <out_dir>")
    sys.exit(1)

# Ensure output directory exists
os.makedirs(out_dir, exist_ok=True)

# Clean up existing nodes
bpy.context.scene.use_nodes = True
tree = bpy.context.scene.node_tree
tree.nodes.clear()

# Create image node and load EXR
img_node = tree.nodes.new(type="CompositorNodeImage")
img = bpy.data.images.load(exr_path)
img_node.image = img

# Get available layers/passes from the EXR
# In Blender CompositorNodeImage, the outputs correspond to the layers
passes = [output.name for output in img_node.outputs if output.name != "Alpha" and output.enabled]
print(f"FOUND_PASSES: {passes}")

# Optional: We could set up a File Output node to save all passes
out_node = tree.nodes.new(type="CompositorNodeOutputFile")
out_node.base_path = out_dir
out_node.format.file_format = 'JPEG'
out_node.format.quality = 90

# Connect outputs to File Output node
for i, pass_name in enumerate(passes):
    # Add input socket to File Output node
    if i == 0:
        in_socket = out_node.inputs[0]
        in_socket.name = pass_name
    else:
        out_node.file_slots.new(pass_name)
        in_socket = out_node.inputs[-1]
        
    # Connect
    tree.links.new(img_node.outputs[pass_name], in_socket)

# Render to execute the compositor (requires a dummy render, but we can set resolution to match image)
bpy.context.scene.render.resolution_x = img.size[0]
bpy.context.scene.render.resolution_y = img.size[1]
bpy.context.scene.render.resolution_percentage = 100

# Just running the compositor is enough for the File Output node
bpy.ops.render.render(write_still=False)

print("SUCCESS")
