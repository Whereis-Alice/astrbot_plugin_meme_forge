from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

MAX_FRAME_PIXELS = 16_000_000
MAX_TOTAL_FRAME_PIXELS = 32_000_000
MAX_INPUT_FRAMES = 60
MAX_OUTPUT_GIF_BYTES = 20 * 1024 * 1024

FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)

BOLD_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


class ImageRenderError(RuntimeError):
    """Raised for readable local image-composition failures."""


@dataclass(frozen=True, slots=True)
class DecodedImage:
    """One decoded still image or animation with per-frame durations."""

    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]

    @property
    def is_animated(self) -> bool:
        return len(self.frames) > 1

    @property
    def total_duration_ms(self) -> int:
        return sum(self.durations_ms)


def decode_image(data: bytes) -> DecodedImage:
    """Decode untrusted image bytes into bounded RGBA frames."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            pixels = width * height
            if width < 1 or height < 1 or pixels > MAX_FRAME_PIXELS:
                raise ImageRenderError("输入图片尺寸超过安全限制")
            source_frames = max(1, int(getattr(image, "n_frames", 1)))
            maximum = max(1, MAX_TOTAL_FRAME_PIXELS // pixels)
            frame_count = min(source_frames, MAX_INPUT_FRAMES, maximum)
            frames: list[Image.Image] = []
            durations: list[int] = []
            for index in range(frame_count):
                image.seek(index)
                frame = ImageOps.exif_transpose(image.copy()).convert("RGBA")
                frames.append(frame)
                duration = int(image.info.get("duration", 80) or 80)
                durations.append(max(20, min(duration, 10_000)))
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageRenderError("无法解码输入图片") from exc
    if not frames:
        raise ImageRenderError("输入图片没有可用画面")
    return DecodedImage(tuple(frames), tuple(durations))


def placeholder_image(index: int) -> bytes:
    """Build a neutral stand-in photo used by Dashboard previews."""
    colors = ((56, 189, 248), (251, 191, 36), (167, 139, 250))
    foreground = colors[index % len(colors)]
    image = Image.new("RGBA", (640, 480), (24, 29, 39, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 60, 560, 420), radius=48, fill=foreground)
    draw.ellipse((210, 100, 430, 320), fill=(255, 255, 255, 220))
    draw.rectangle((250, 300, 390, 380), fill=(255, 255, 255, 220))
    return save_png(image)


def frame_for_time(image: DecodedImage, index: int, interval_ms: int) -> Image.Image:
    """Sample the animation frame shown at one output frame index."""
    if len(image.frames) == 1:
        return image.frames[0].copy()
    total = sum(image.durations_ms)
    moment = (index * interval_ms) % max(total, 1)
    elapsed = 0
    for frame, duration in zip(image.frames, image.durations_ms, strict=True):
        elapsed += duration
        if moment < elapsed:
            return frame.copy()
    return image.frames[-1].copy()


def save_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def encode_gif(frames: Sequence[Image.Image], durations_ms: Sequence[int]) -> bytes:
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=list(frames[1:]),
        duration=list(durations_ms),
        loop=0,
        disposal=2,
        optimize=False,
    )
    return output.getvalue()


def coalesce_gif(
    frames: Sequence[Image.Image], durations_ms: Sequence[int]
) -> tuple[list[Image.Image], list[int]]:
    """Halve the frame count while preserving total playback duration."""
    next_frames: list[Image.Image] = []
    next_durations: list[int] = []
    for index in range(0, len(frames), 2):
        next_frames.append(frames[index])
        next_durations.append(sum(durations_ms[index : index + 2]))
    return next_frames, next_durations


def save_gif(frames: Sequence[Image.Image], durations_ms: int | Sequence[int]) -> bytes:
    """Encode frames as GIF, shrinking until the size limit is met."""
    if not frames:
        raise ImageRenderError("没有可编码的 GIF 帧")
    working = [frame.convert("RGBA") for frame in frames]
    durations = (
        [int(durations_ms)] * len(working)
        if isinstance(durations_ms, int)
        else [int(value) for value in durations_ms]
    )
    for _ in range(8):
        data = encode_gif(working, durations)
        if len(data) <= MAX_OUTPUT_GIF_BYTES:
            return data
        if len(working) > 12:
            working, durations = coalesce_gif(working, durations)
            continue
        width, height = working[0].size
        if min(width, height) <= 128:
            break
        size = (max(1, int(width * 0.85)), max(1, int(height * 0.85)))
        working = [frame.resize(size, Image.Resampling.LANCZOS) for frame in working]
    raise ImageRenderError("生成的 GIF 超过 20 MB 安全限制")


def open_static(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            return image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageRenderError(f"缺少或无法读取素材 {path.name}") from exc


def open_animation(path: Path) -> DecodedImage:
    try:
        return decode_image(path.read_bytes())
    except OSError as exc:
        raise ImageRenderError(f"缺少或无法读取素材 {path.name}") from exc


def square(image: Image.Image) -> Image.Image:
    size = min(image.size)
    left = (image.width - size) // 2
    top = (image.height - size) // 2
    return image.crop((left, top, left + size, top + size))


def contain_size(source: tuple[int, int], maximum: tuple[int, int]) -> tuple[int, int]:
    scale = min(maximum[0] / source[0], maximum[1] / source[1])
    return max(1, round(source[0] * scale)), max(1, round(source[1] * scale))


def load_font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a CJK-capable font, falling back to the bundled default."""
    candidates = BOLD_FONT_CANDIDATES if bold else FONT_CANDIDATES
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_fitted_text(
    image: Image.Image,
    box: tuple[int, int, int, int],
    text: str,
) -> None:
    """Center one shrink-to-fit black line inside a box."""
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    for size in range(24, 11, -1):
        font = load_font(size)
        bounds = draw.textbbox((0, 0), text, font=font)
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        if width <= right - left and height <= bottom - top:
            draw.text(
                ((left + right - width) // 2, (top + bottom - height) // 2),
                text,
                fill="black",
                font=font,
            )
            return
    font = load_font(12)
    draw.text((left, top), text, fill="black", font=font)


def fit_into(
    image: Image.Image,
    size: tuple[int, int],
    mode: str = "cover",
) -> Image.Image:
    """Resize one frame into a target box using cover/contain/stretch."""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    if mode == "stretch":
        return image.resize((width, height), Image.Resampling.LANCZOS)
    if mode == "contain":
        target = contain_size(image.size, (width, height))
        scaled = image.resize(target, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(
            scaled,
            ((width - target[0]) // 2, (height - target[1]) // 2),
        )
        return canvas
    scale = max(width / image.width, height / image.height)
    scaled = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def rounded_mask(size: tuple[int, int], radius: int, *, circle: bool = False) -> Image.Image:
    """Build an anti-aliased alpha mask for rounded or elliptical slots."""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    scale = 4 if max(width, height) <= 900 else 2
    mask = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(mask)
    if circle:
        draw.ellipse((0, 0, width * scale - 1, height * scale - 1), fill=255)
    else:
        bounded = max(0, min(int(radius), min(width, height) // 2))
        draw.rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1),
            radius=bounded * scale,
            fill=255,
        )
    return mask.resize((width, height), Image.Resampling.LANCZOS)
