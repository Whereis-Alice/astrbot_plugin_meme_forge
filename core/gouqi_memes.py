from __future__ import annotations

import hashlib
import io
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)


class GouqiRenderError(RuntimeError):
    """Raised for readable Gouqi template generation failures."""


@dataclass(frozen=True, slots=True)
class GouqiParams:
    min_images: int
    max_images: int
    min_texts: int
    max_texts: int
    default_texts: list[str]
    options: list[Any]


@dataclass(frozen=True, slots=True)
class GouqiInfo:
    key: str
    params: GouqiParams
    keywords: list[str]
    shortcuts: list[Any]
    tags: set[str]


@dataclass(frozen=True, slots=True)
class DecodedImage:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]


@dataclass(slots=True)
class GouqiRenderContext:
    images: list[DecodedImage]
    texts: list[str]
    random: random.Random


Renderer = Callable[[GouqiRenderContext, Path], bytes]

MAX_FRAME_PIXELS = 16_000_000
MAX_TOTAL_FRAME_PIXELS = 32_000_000
MAX_INPUT_FRAMES = 60
MAX_OUTPUT_GIF_BYTES = 20 * 1024 * 1024


class GouqiMeme:
    source = "gouqi"

    def __init__(
        self,
        *,
        key: str,
        keywords: Sequence[str],
        min_images: int,
        max_images: int,
        min_texts: int = 0,
        max_texts: int = 0,
        tags: Sequence[str] = (),
        assets_root: Path,
        renderer: Renderer,
    ) -> None:
        self.key = key
        self.assets_root = assets_root
        self.renderer = renderer
        self.info = GouqiInfo(
            key=key,
            params=GouqiParams(
                min_images=min_images,
                max_images=max_images,
                min_texts=min_texts,
                max_texts=max_texts,
                default_texts=[],
                options=[],
            ),
            keywords=[str(value) for value in keywords],
            shortcuts=[],
            tags={"gouqi", *tags},
        )

    @property
    def material_directory(self) -> Path:
        return self.assets_root / self.key / "images"

    def _generate(
        self,
        raw_images: Sequence[tuple[str, bytes]],
        texts: Sequence[str],
    ) -> bytes:
        params = self.info.params
        image_count = len(raw_images)
        text_count = len(texts)
        if not params.min_images <= image_count <= params.max_images:
            raise GouqiRenderError(
                f"需要 {params.min_images}~{params.max_images} 张图片，实际 {image_count} 张"
            )
        if not params.min_texts <= text_count <= params.max_texts:
            raise GouqiRenderError(
                f"需要 {params.min_texts}~{params.max_texts} 段文本，实际 {text_count} 段"
            )

        digest = hashlib.sha256()
        decoded: list[DecodedImage] = []
        for _, data in raw_images:
            digest.update(data)
            decoded.append(_decode_image(data))
        context = GouqiRenderContext(
            images=decoded,
            texts=[str(value) for value in texts],
            random=random.Random(int.from_bytes(digest.digest()[:8], "big")),
        )
        try:
            result = self.renderer(context, self.assets_root / self.key)
        except GouqiRenderError:
            raise
        except (OSError, ValueError, ZeroDivisionError) as exc:
            raise GouqiRenderError(str(exc) or type(exc).__name__) from exc
        if not isinstance(result, bytes) or not result:
            raise GouqiRenderError("渲染器没有返回有效图片")
        return result

    def generate_from_inputs(self, inputs: Any) -> bytes:
        return self._generate(inputs.images, inputs.texts)

    def generate_preview(self) -> bytes:
        params = self.info.params
        images = [
            (f"preview-{index}.png", _placeholder_image(index))
            for index in range(params.min_images)
        ]
        texts = ["Meme 工坊" for _ in range(params.min_texts)]
        return self._generate(images, texts)


def _decode_image(data: bytes) -> DecodedImage:
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            pixels = width * height
            if width < 1 or height < 1 or pixels > MAX_FRAME_PIXELS:
                raise GouqiRenderError("输入图片尺寸超过 Gouqi 扩展安全限制")
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
        raise GouqiRenderError("无法解码输入图片") from exc
    if not frames:
        raise GouqiRenderError("输入图片没有可用画面")
    return DecodedImage(tuple(frames), tuple(durations))


def _placeholder_image(index: int) -> bytes:
    colors = ((56, 189, 248), (251, 191, 36), (167, 139, 250))
    foreground = colors[index % len(colors)]
    image = Image.new("RGBA", (640, 480), (24, 29, 39, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 60, 560, 420), radius=48, fill=foreground)
    draw.ellipse((210, 100, 430, 320), fill=(255, 255, 255, 220))
    draw.rectangle((250, 300, 390, 380), fill=(255, 255, 255, 220))
    return _save_png(image)


def _frame_for_time(image: DecodedImage, index: int, interval_ms: int) -> Image.Image:
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


def _save_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _encode_gif(frames: Sequence[Image.Image], durations_ms: Sequence[int]) -> bytes:
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


def _coalesce_gif(
    frames: Sequence[Image.Image], durations_ms: Sequence[int]
) -> tuple[list[Image.Image], list[int]]:
    next_frames: list[Image.Image] = []
    next_durations: list[int] = []
    for index in range(0, len(frames), 2):
        next_frames.append(frames[index])
        next_durations.append(sum(durations_ms[index : index + 2]))
    return next_frames, next_durations


def _save_gif(frames: Sequence[Image.Image], durations_ms: int | Sequence[int]) -> bytes:
    if not frames:
        raise GouqiRenderError("没有可编码的 GIF 帧")
    working = [frame.convert("RGBA") for frame in frames]
    durations = (
        [int(durations_ms)] * len(working)
        if isinstance(durations_ms, int)
        else [int(value) for value in durations_ms]
    )
    for _ in range(8):
        data = _encode_gif(working, durations)
        if len(data) <= MAX_OUTPUT_GIF_BYTES:
            return data
        if len(working) > 12:
            working, durations = _coalesce_gif(working, durations)
            continue
        width, height = working[0].size
        if min(width, height) <= 128:
            break
        size = (max(1, int(width * 0.85)), max(1, int(height * 0.85)))
        working = [frame.resize(size, Image.Resampling.LANCZOS) for frame in working]
    raise GouqiRenderError("生成的 GIF 超过 20 MB 安全限制")


def _open_static(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            return image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise GouqiRenderError(f"缺少或无法读取素材 {path.name}") from exc


def _open_animation(path: Path) -> DecodedImage:
    try:
        return _decode_image(path.read_bytes())
    except OSError as exc:
        raise GouqiRenderError(f"缺少或无法读取素材 {path.name}") from exc


def _square(image: Image.Image) -> Image.Image:
    size = min(image.size)
    left = (image.width - size) // 2
    top = (image.height - size) // 2
    return image.crop((left, top, left + size, top + size))


def _contain_size(
    source: tuple[int, int], maximum: tuple[int, int]
) -> tuple[int, int]:
    scale = min(maximum[0] / source[0], maximum[1] / source[1])
    return max(1, round(source[0] * scale)), max(1, round(source[1] * scale))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    )
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_fitted_text(
    image: Image.Image,
    box: tuple[int, int, int, int],
    text: str,
) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    for size in range(24, 11, -1):
        font = _load_font(size)
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
    font = _load_font(12)
    draw.text((left, top), text, fill="black", font=font)


def _render_ceshi(context: GouqiRenderContext, root: Path) -> bytes:
    user = _square(context.images[0].frames[0].convert("RGBA")).resize(
        (200, 200), Image.Resampling.LANCZOS
    )
    background = _open_static(root / "images" / "background.png")
    # Upstream draws at y=270..320 even though its current background is only
    # 260 px tall. Preserve the intended text area by adding a white footer.
    canvas = Image.new(
        "RGBA",
        (max(background.width, 300), max(background.height, 330)),
        (255, 255, 255, 255),
    )
    canvas.alpha_composite(background, (0, 0))
    canvas.alpha_composite(user, (50, 50))
    _draw_fitted_text(canvas, (30, 270, canvas.width - 30, 320), context.texts[0])
    return _save_png(canvas)


def _prepare_food(image: Image.Image) -> Image.Image:
    food = ImageOps.flip(ImageOps.exif_transpose(image).convert("RGBA"))
    food = _square(food)
    mask = Image.new("L", food.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, food.width - 1, food.height - 1), fill=255)
    food.putalpha(mask)
    return food.resize(_contain_size(food.size, (100, 100)), Image.Resampling.LANCZOS)


def _render_eav_grill(context: GouqiRenderContext, root: Path) -> bytes:
    background = _open_static(root / "images" / "background.png")
    frames: list[Image.Image] = []
    for index in range(24):
        frame = background.copy()
        food = _prepare_food(_frame_for_time(context.images[0], index, 50))
        phase = index / 24 * 2 * math.pi
        angle = math.radians(8 + 45 * math.sin(phase))
        rope_end = (55 + 60 * math.sin(angle), -60 + 60 * math.cos(angle))
        position = (
            round(rope_end[0] - food.width * 0.5),
            round(rope_end[1] - food.height * 0.08),
        )
        frame.alpha_composite(food, position)
        frames.append(frame)
    return _save_gif(frames, 50)


def _render_greeting_cat(context: GouqiRenderContext, root: Path) -> bytes:
    template = _open_animation(root / "images" / "greeting_cat.gif")
    frames: list[Image.Image] = []
    for index, overlay in enumerate(template.frames):
        user = _frame_for_time(context.images[0], index, template.durations_ms[index])
        user = user.resize((250, 250), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
        canvas.alpha_composite(user, (0, 300 - user.height))
        canvas.alpha_composite(overlay.convert("RGBA"), (0, 0))
        frames.append(canvas)
    return _save_gif(frames, template.durations_ms)


def _render_haine_shoot(context: GouqiRenderContext, root: Path) -> bytes:
    image_root = root / "images"
    frames = [_open_static(image_root / f"haine{index}.png") for index in range(10)]
    for index in range(7):
        user = _frame_for_time(context.images[0], index, 100)
        user = ImageEnhance.Brightness(user).enhance(0.8)
        user = user.resize((410, 410), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (410, 600))
        frame.alpha_composite(user, (0, 95))
        stain = _open_static(image_root / f"stain{index}.png")
        frame.alpha_composite(stain, (0, 95))
        frames.append(frame)
    return _save_gif(frames, 100)


@dataclass(slots=True)
class _Dust:
    x: float
    y: float
    dx: float
    dy: float
    radius: int
    vx: float = 0
    vy: float = 0

    def move(self, step: float) -> None:
        acceleration = 0.02 * step / self.radius
        self.vx += acceleration * self.dx
        self.vy += acceleration * self.dy
        self.x += round(self.vx)
        self.y += round(self.vy)


def _dust_layer(
    dusts: list[_Dust],
    step: float,
    size: tuple[int, int],
    generator: random.Random,
) -> Image.Image:
    layer = Image.new("RGBA", size)
    draw = ImageDraw.Draw(layer)
    remaining: list[_Dust] = []
    for dust in dusts:
        dust.move(step)
        if generator.random() < 0.25:
            dust.radius -= 1
        if (
            dust.radius <= 0
            or dust.x + dust.radius < 0
            or dust.x - dust.radius > size[0]
            or dust.y + dust.radius < 0
            or dust.y - dust.radius > size[1]
        ):
            continue
        draw.ellipse(
            (
                dust.x - dust.radius,
                dust.y - dust.radius,
                dust.x + dust.radius,
                dust.y + dust.radius,
            ),
            fill=(0, 0, 0, 255),
        )
        remaining.append(dust)
    dusts[:] = remaining
    return layer


def _masked_target(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target = image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    target.putalpha(mask)
    return target


def _disintegrate(
    image: Image.Image,
    *,
    frame_index: int,
    origin: tuple[float, float],
    step: float,
    dusts: list[_Dust],
    generator: random.Random,
) -> Image.Image:
    output = image.copy()
    source_pixels = image.load()
    output_pixels = output.load()
    origin_x, origin_y = origin
    start_y = max(0, min(image.height, image.height - round(step * (frame_index + 11))))
    for x in range(image.width):
        for y in range(start_y, image.height):
            value = source_pixels[x, y]
            if value[3] == 0:
                continue
            distance = math.hypot(x - origin_x, y - origin_y)
            if distance <= step * (frame_index - 5):
                output_pixels[x, y] = (0, 0, 0, 0)
            elif distance <= step * (frame_index - 4):
                output_pixels[x, y] = (0, 0, 0, 255)
                if distance > 0 and generator.random() <= 0.06:
                    dusts.append(
                        _Dust(
                            x=x,
                            y=y,
                            dx=(x - origin_x) / distance,
                            dy=(y - origin_y * 1.5) / distance,
                            radius=generator.randint(1, 3),
                        )
                    )
            elif distance <= step * (frame_index + 2):
                factor = (distance - step * (frame_index - 11)) / (step * 12)
                factor = max(0.0, min(1.0, factor))
                factor *= 0.9 + 0.2 * generator.random()
                gray = round(sum(value[:3]) / 3 * factor)
                output_pixels[x, y] = (gray, gray, gray, value[3])
    dust = _dust_layer(dusts, step, image.size, generator)
    output.alpha_composite(dust)
    return output


def _render_squeeze(
    context: GouqiRenderContext,
    *,
    background: Image.Image | None,
    overlay: Image.Image | None,
    background_input: DecodedImage | None,
    target_input: DecodedImage,
) -> bytes:
    first_target = target_input.frames[0]
    target_size = _contain_size(first_target.size, (300, 200))
    canvas_size = (
        background.size
        if background is not None
        else overlay.size
        if overlay is not None
        else (640, 480)
    )
    paste_x = min(max(460 - target_size[0] // 2, 0), canvas_size[0] - target_size[0])
    paste_y = min(max(360 - target_size[1] // 2, 0), canvas_size[1] - target_size[1])
    origin = (target_size[0] * 2 / 3, target_size[1] * 3 / 2)
    step = math.hypot(*origin) / 24
    dusts: list[_Dust] = []
    frames: list[Image.Image] = []

    for index in range(35):
        if background_input is not None:
            source = _frame_for_time(background_input, index, 80)
            contained = source.resize(
                _contain_size(source.size, (640, 480)), Image.Resampling.LANCZOS
            )
            canvas = Image.new("RGBA", (640, 480))
            canvas.alpha_composite(
                contained,
                ((640 - contained.width) // 2, (480 - contained.height) // 2),
            )
        else:
            assert background is not None
            canvas = background.copy()
        if overlay is not None:
            canvas.alpha_composite(overlay, (0, 0))

        target = _masked_target(
            _frame_for_time(target_input, index, 80), target_size
        )
        if index <= 9:
            foreground = target
        elif index < 28:
            foreground = _disintegrate(
                target,
                frame_index=index,
                origin=origin,
                step=step,
                dusts=dusts,
                generator=context.random,
            )
        else:
            foreground = _dust_layer(dusts, step, target.size, context.random)
        canvas.alpha_composite(foreground, (paste_x, paste_y))
        frames.append(canvas)
    return _save_gif(frames, 80)


def _render_i_squeeze(context: GouqiRenderContext, root: Path) -> bytes:
    overlay = _open_static(root / "images" / "ct_rucyfina_hand.png")
    return _render_squeeze(
        context,
        background=None,
        overlay=overlay,
        background_input=context.images[0],
        target_input=context.images[1],
    )


def _render_lucifina_chan_squeeze(
    context: GouqiRenderContext, root: Path
) -> bytes:
    background = _open_static(root / "images" / "ct_rucyfinac1.png")
    return _render_squeeze(
        context,
        background=background,
        overlay=None,
        background_input=None,
        target_input=context.images[0],
    )


def _render_lucifina_squeeze(context: GouqiRenderContext, root: Path) -> bytes:
    background = _open_static(root / "images" / "ct_rucyfina1.png")
    return _render_squeeze(
        context,
        background=background,
        overlay=None,
        background_input=None,
        target_input=context.images[0],
    )


def _render_line_art(context: GouqiRenderContext, root: Path) -> bytes:
    del root
    output: list[Image.Image] = []
    source = context.images[0]
    for frame in source.frames:
        canvas = Image.new("RGBA", frame.size, (255, 255, 255, 255))
        canvas.alpha_composite(ImageOps.exif_transpose(frame).convert("RGBA"))
        grayscale = canvas.convert("L")
        softened = grayscale.filter(ImageFilter.GaussianBlur(radius=1.2))
        edges = ImageOps.autocontrast(softened.filter(ImageFilter.FIND_EDGES), cutoff=2)
        mask = edges.point(lambda value: 255 if value >= 40 else 0, mode="L")
        output.append(ImageOps.invert(mask).convert("RGBA"))
    if len(output) == 1:
        return _save_png(output[0])
    return _save_gif(output, source.durations_ms)


def _render_twist(
    context: GouqiRenderContext,
    root: Path,
    *,
    names: Sequence[str],
    input_size: tuple[int, int],
    center: tuple[int, int],
) -> bytes:
    source = _square(context.images[0].frames[0]).resize(
        input_size, Image.Resampling.LANCZOS
    )
    frames: list[Image.Image] = []
    step = 360 / len(names)
    for index, name in enumerate(names):
        template = _open_static(root / "images" / name)
        angle = 30 - index * step
        rotated = source.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
        position = (
            round(center[0] - rotated.width / 2),
            round(center[1] - rotated.height / 2),
        )
        frame = Image.new("RGBA", template.size)
        frame.alpha_composite(rotated, position)
        frame.alpha_composite(template)
        frames.append(frame)
    return _save_gif(frames, 100)


def _render_lucifinac_twist(context: GouqiRenderContext, root: Path) -> bytes:
    return _render_twist(
        context,
        root,
        names=(
            "lucifinac_action1.png",
            "lucifinac_action2.png",
            "lucifinac_action3.png",
            "lucifinac_action4.png",
        ),
        input_size=(150, 150),
        center=(150, 187),
    )


def _render_luluka_twist(context: GouqiRenderContext, root: Path) -> bytes:
    return _render_twist(
        context,
        root,
        names=(
            "luluka_action1.png",
            "luluka_action2.png",
            "luluka_action3.png",
            "luluka_action4.png",
        ),
        input_size=(126, 126),
        center=(166, 203),
    )


def build_gouqi_memes(assets_root: Path) -> list[GouqiMeme]:
    definitions: tuple[dict[str, Any], ...] = (
        {
            "key": "ceshi",
            "keywords": ["测试"],
            "min_images": 1,
            "max_images": 1,
            "min_texts": 1,
            "max_texts": 1,
            "tags": ["静态"],
            "renderer": _render_ceshi,
        },
        {
            "key": "eav_grill",
            "keywords": ["伊娃烧"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_eav_grill,
        },
        {
            "key": "greeting_cat",
            "keywords": ["挥手猫"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_greeting_cat,
        },
        {
            "key": "haine_shoot",
            "keywords": ["海涅喷射"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_haine_shoot,
        },
        {
            "key": "i_squeeze",
            "keywords": ["我捏"],
            "min_images": 2,
            "max_images": 2,
            "tags": ["动画"],
            "renderer": _render_i_squeeze,
        },
        {
            "key": "line_art",
            "keywords": ["线稿化", "线稿", "素描线稿"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["滤镜"],
            "renderer": _render_line_art,
        },
        {
            "key": "lucifina_chan_squeeze",
            "keywords": ["小露西菲娜捏"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_lucifina_chan_squeeze,
        },
        {
            "key": "lucifina_squeeze",
            "keywords": ["露西菲娜捏"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_lucifina_squeeze,
        },
        {
            "key": "lucifinac_twist",
            "keywords": ["小露西菲娜旋转", "小露西旋转", "小菲娜旋转"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_lucifinac_twist,
        },
        {
            "key": "luluka_twist",
            "keywords": ["露露卡旋转"],
            "min_images": 1,
            "max_images": 1,
            "tags": ["动画"],
            "renderer": _render_luluka_twist,
        },
    )
    return [GouqiMeme(assets_root=assets_root, **definition) for definition in definitions]


def render_gouqi_list_panel(memes: Sequence[GouqiMeme]) -> bytes:
    line_height = 38
    width = 980
    height = 72 + line_height * len(memes)
    image = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(28)
    body_font = _load_font(22)
    draw.text((28, 20), "Gouqi 扩展", fill="#172033", font=title_font)
    for index, meme in enumerate(memes, start=1):
        y = 66 + (index - 1) * line_height
        background = "#ffffff" if index % 2 else "#edf2f7"
        draw.rectangle((20, y, width - 20, y + line_height), fill=background)
        keywords = " / ".join(meme.info.keywords)
        draw.text(
            (34, y + 6),
            f"{index}. {keywords} ({meme.key})",
            fill="#263247",
            font=body_font,
        )
    return _save_png(image)
