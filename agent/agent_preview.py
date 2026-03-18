import os
from PIL import Image

def make_jpeg_preview(png_path: str, jpg_out_path: str, quality: int = 85) -> str:
    os.makedirs(os.path.dirname(jpg_out_path), exist_ok=True)

    img = Image.open(png_path)
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")

    img.save(jpg_out_path, "JPEG", quality=quality, optimize=True)
    return jpg_out_path
