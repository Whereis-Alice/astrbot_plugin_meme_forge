from __future__ import annotations

import io

from PIL import Image, ImageOps


def compress_static_image(image: bytes, max_size: int = 512) -> bytes:
    """Resize oversized static images while leaving animated images untouched."""
    with Image.open(io.BytesIO(image)) as source:
        if getattr(source, "is_animated", False):
            return image
        if source.width <= max_size and source.height <= max_size:
            return image

        resized = ImageOps.exif_transpose(source.copy())
        resized.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image_format = source.format or "PNG"
        save_options: dict[str, int | bool] = {"optimize": True}
        if image_format.upper() in {"JPEG", "JPG"}:
            save_options["quality"] = 90
        resized.save(output, format=image_format, **save_options)
        return output.getvalue()
