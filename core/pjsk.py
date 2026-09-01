"""Render PJSK stickers locally with Pillow.

The upstream web editor draws on a 296x256 HTML canvas. This module reproduces
that geometry so the numbers stored in the catalogue keep their meaning, while
adding the parts a chat bot needs: automatic font sizing, word wrapping, sane
line spacing and a proper arc layout.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import pjsk_catalog as catalog
from .imaging import (
    ImageRenderError,
    contain_size,
    fit_into,
    load_font,
    open_static,
    save_png,
)

#: Everything is composed at this multiple of the logical canvas, then reduced.
SUPERSAMPLE = 2
#: Upstream uses a centred 9px canvas stroke, which paints 4.5px outwards.
STROKE_WIDTH = 9 / 2
#: Upstream places curved glyphs this many font sizes away from the pivot.
ARC_RADIUS_RATIO = 3.5
#: Flatten the arc once the text would sweep further than this angle.
MAX_ARC_SWEEP = math.pi * 0.8
#: Latin advances average about this fraction of the font size.
ARC_REFERENCE_ADVANCE = 0.55

MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 100
DEFAULT_LINE_SPACING = 1.3
MIN_LINE_SPACING = 0.8
MAX_LINE_SPACING = 3.0
MAX_TEXT_LENGTH = 160
MAX_TEXT_LINES = 6
MAX_OUTPUT_SCALE = 4
#: Keep the text this far away from the canvas edge when auto-fitting.
EDGE_MARGIN = 5


@dataclass(frozen=True, slots=True)
class PjskTextLayout:
    """Resolved geometry for one render, after defaults and auto-fitting."""

    lines: tuple[str, ...]
    x: float
    y: float
    rotate: float
    font_size: int
    line_spacing: float
    curve: bool

    @property
    def radians(self) -> float:
        """Upstream stores rotation in tenths of a radian."""
        return self.rotate / 10


def normalise_text(raw: str) -> str:
    r"""Clean up chat input, treating a literal ``\n`` as a line break."""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\n", "\n").replace("\uff3cn", "\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    joined = "\n".join(lines[:MAX_TEXT_LINES])
    return joined[:MAX_TEXT_LENGTH]


@lru_cache(maxsize=64)
def _truetype(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def clear_font_cache() -> None:
    """Drop cached font handles, e.g. after the assets were reinstalled."""
    _truetype.cache_clear()


def sticker_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    """Load the PJSK handwriting font, or a CJK system font as a fallback."""
    if font_path is not None and font_path.is_file():
        try:
            return _truetype(str(font_path), size)
        except OSError:
            pass
    fallback = load_font(size)
    if not isinstance(fallback, ImageFont.FreeTypeFont):
        raise ImageRenderError("找不到可用的矩形字体，请先安装 PJSK 素材")
    return fallback


def _wrap_line(line: str, font: ImageFont.FreeTypeFont, limit: float) -> list[str]:
    """Wrap one logical line, breaking on spaces first and glyphs if needed."""
    if font.getlength(line) <= limit:
        return [line]
    out: list[str] = []
    current = ""
    for token in _tokenise(line):
        candidate = current + token
        if current and font.getlength(candidate.strip()) > limit:
            out.append(current.strip())
            current = token.lstrip()
        else:
            current = candidate
        while font.getlength(current) > limit and len(current) > 1:
            cut = len(current) - 1
            while cut > 1 and font.getlength(current[:cut]) > limit:
                cut -= 1
            out.append(current[:cut])
            current = current[cut:]
    if current.strip():
        out.append(current.strip())
    return out or [line]


def _tokenise(line: str) -> list[str]:
    """Split into wrap candidates: Latin words stay whole, CJK breaks anywhere."""
    tokens: list[str] = []
    buffer = ""
    for char in line:
        if char == " ":
            buffer += char
            tokens.append(buffer)
            buffer = ""
        elif ord(char) > 0x2E7F:
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
        else:
            buffer += char
    if buffer:
        tokens.append(buffer)
    return tokens


def _block_metrics(
    lines: tuple[str, ...], font: ImageFont.FreeTypeFont, step: float
) -> tuple[float, float, float, float]:
    """Return width, height and the baseline offsets of a text block."""
    ascent, descent = font.getmetrics()
    width = max((font.getlength(line) for line in lines), default=0.0)
    top = -float(ascent)
    bottom = step * (len(lines) - 1) + float(descent)
    return width, bottom - top, top, bottom


def _rotated_extent(width: float, height: float, radians: float) -> tuple[float, float]:
    cos, sin = abs(math.cos(radians)), abs(math.sin(radians))
    return width * cos + height * sin, width * sin + height * cos


def _fit_straight(
    text: str,
    font_path: Path | None,
    base_size: int,
    line_spacing: float,
    radians: float,
) -> tuple[tuple[str, ...], int]:
    """Shrink and wrap until the rotated text block fits the canvas."""
    limit_w = catalog.CANVAS_WIDTH - 2 * STROKE_WIDTH - 2 * EDGE_MARGIN
    limit_h = catalog.CANVAS_HEIGHT - 2 * STROKE_WIDTH - 2 * EDGE_MARGIN
    wrap_w = catalog.CANVAS_WIDTH - 2 * STROKE_WIDTH
    requested = tuple(text.split("\n"))
    best: tuple[tuple[str, ...], int] | None = None
    for size in range(base_size, MIN_FONT_SIZE - 1, -1):
        font = sticker_font(font_path, size)
        wrapped: list[str] = []
        for line in requested:
            wrapped.extend(_wrap_line(line, font, wrap_w))
        candidate = tuple(wrapped[:MAX_TEXT_LINES])
        step = size * line_spacing
        width, height, _, _ = _block_metrics(candidate, font, step)
        extent_w, extent_h = _rotated_extent(width, height, radians)
        best = (candidate, size)
        if extent_w <= limit_w and extent_h <= limit_h:
            return candidate, size
    return best if best is not None else (requested, MIN_FONT_SIZE)

def _clamp_offsets(
    x: float,
    y: float,
    box: tuple[float, float, float, float],
    radians: float,
) -> tuple[float, float]:
    """Nudge one pivot so a rotated text box stays inside the canvas."""
    left, right, top, bottom = box
    cos, sin = math.cos(radians), math.sin(radians)
    corners = ((left, top), (right, top), (left, bottom), (right, bottom))
    rotated = [(a * cos - b * sin, a * sin + b * cos) for a, b in corners]
    min_x = min(point[0] for point in rotated) - STROKE_WIDTH
    max_x = max(point[0] for point in rotated) + STROKE_WIDTH
    min_y = min(point[1] for point in rotated) - STROKE_WIDTH
    max_y = max(point[1] for point in rotated) + STROKE_WIDTH
    if x + min_x < EDGE_MARGIN:
        x = EDGE_MARGIN - min_x
    if x + max_x > catalog.CANVAS_WIDTH - EDGE_MARGIN:
        x = min(x, catalog.CANVAS_WIDTH - EDGE_MARGIN - max_x)
    if y + min_y < EDGE_MARGIN:
        y = EDGE_MARGIN - min_y
    if y + max_y > catalog.CANVAS_HEIGHT - EDGE_MARGIN:
        y = min(y, catalog.CANVAS_HEIGHT - EDGE_MARGIN - max_y)
    return x, y


def _clamp_pivot(
    layout: PjskTextLayout, font: ImageFont.FreeTypeFont
) -> tuple[float, float]:
    """Keep a straight text block inside the canvas."""
    step = layout.font_size * layout.line_spacing
    width, _, top, bottom = _block_metrics(layout.lines, font, step)
    box = (-width / 2, width / 2, top, bottom)
    return _clamp_offsets(layout.x, layout.y, box, layout.radians)


def _number(value: float | str | None, default: float) -> float:
    """Coerce one optional user argument into a float."""
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace("＋", "+").replace("－", "-"))
    except (TypeError, ValueError):
        return default


def _resolve_scale(value: float | str | None) -> int:
    """Clamp the requested output multiple of the 296x256 canvas."""
    return max(1, min(round(_number(value, 1)), MAX_OUTPUT_SCALE))


def _arc_geometry(
    line: str, font: ImageFont.FreeTypeFont, radius: float
) -> tuple[tuple[float, ...], float]:
    """Place characters on an arc using their real glyph advances."""
    advances = [font.getlength(char) for char in line]
    if not advances:
        return (), 0.0
    steps = [0.0]
    for previous, current in pairwise(advances):
        steps.append((previous + current) / 2 / max(radius, 1.0))
    sweep = sum(steps)
    angles: list[float] = []
    cursor = -sweep / 2
    for step in steps:
        cursor += step
        angles.append(cursor)
    return tuple(angles), sweep


def _arc_radius(line: str, font: ImageFont.FreeTypeFont, base: float) -> float:
    """Widen the arc for wide glyphs, then flatten it if it still wraps."""
    radius = max(base, 1.0)
    advances = [font.getlength(char) for char in line]
    if advances:
        mean = sum(advances) / len(advances)
        reference = max(font.size * ARC_REFERENCE_ADVANCE, 1.0)
        radius *= max(1.0, mean / reference)
    _, sweep = _arc_geometry(line, font, radius)
    if sweep > MAX_ARC_SWEEP:
        radius *= sweep / MAX_ARC_SWEEP
    return radius


def _arc_box(
    lines: tuple[str, ...],
    font: ImageFont.FreeTypeFont,
    font_size: int,
    line_spacing: float,
) -> tuple[float, float, float, float] | None:
    """Bounding box of an arc block, relative to the first arc apex."""
    if not any(lines):
        return None
    ascent, descent = font.getmetrics()
    step = font_size * line_spacing
    base_radius = font_size * ARC_RADIUS_RATIO
    left = right = top = bottom = 0.0
    for offset, line in enumerate(lines):
        if not line:
            continue
        radius = _arc_radius(line, font, base_radius)
        _, sweep = _arc_geometry(line, font, radius)
        advance = max(font.getlength(char) for char in line)
        half = sweep / 2
        width = 2 * ((radius + ascent) * math.sin(half) + advance / 2)
        apex = offset * step
        left = min(left, -width / 2)
        right = max(right, width / 2)
        top = min(top, apex - ascent)
        bottom = max(bottom, apex + radius * (1 - math.cos(half)) + descent)
    return left, right, top, bottom


def _fit_arc(
    text: str, font_path: Path | None, base_size: int, line_spacing: float
) -> tuple[tuple[str, ...], int]:
    """Shrink and wrap until every arc of text fits the canvas."""
    limit_w = catalog.CANVAS_WIDTH - 2 * STROKE_WIDTH - 2 * EDGE_MARGIN
    limit_h = catalog.CANVAS_HEIGHT - 2 * STROKE_WIDTH - 2 * EDGE_MARGIN
    wrap_w = catalog.CANVAS_WIDTH - 2 * STROKE_WIDTH
    requested = tuple(text.split("\n"))
    best: tuple[tuple[str, ...], int] = (requested, MIN_FONT_SIZE)
    for size in range(base_size, MIN_FONT_SIZE - 1, -1):
        font = sticker_font(font_path, size)
        wrapped: list[str] = []
        for line in requested:
            wrapped.extend(_wrap_line(line, font, wrap_w))
        candidate = tuple(wrapped[:MAX_TEXT_LINES])
        best = (candidate, size)
        box = _arc_box(candidate, font, size, line_spacing)
        if box is None:
            return candidate, size
        left, right, top, bottom = box
        if right - left <= limit_w and bottom - top <= limit_h:
            return candidate, size
    return best


def resolve_layout(
    sticker: catalog.PjskSticker,
    text: str,
    *,
    font_path: Path | None = None,
    x: float | str | None = None,
    y: float | str | None = None,
    rotate: float | str | None = None,
    font_size: float | str | None = None,
    line_spacing: float | str | None = None,
    curve: bool = False,
) -> PjskTextLayout:
    """Merge user overrides with the layout upstream stores for a sticker."""
    cleaned = normalise_text(text) or sticker.default_text
    size = round(_number(font_size, sticker.font_size))
    size = max(MIN_FONT_SIZE, min(size, MAX_FONT_SIZE))
    spacing = _number(line_spacing, DEFAULT_LINE_SPACING)
    spacing = max(MIN_LINE_SPACING, min(spacing, MAX_LINE_SPACING))
    turn = max(-10.0, min(_number(rotate, sticker.rotate), 10.0))
    pivot_x = _number(x, float(sticker.x))
    pivot_x = max(0.0, min(pivot_x, float(catalog.CANVAS_WIDTH)))
    pivot_y = _number(y, float(sticker.y))
    pivot_y = max(0.0, min(pivot_y, float(catalog.CANVAS_HEIGHT)))
    if curve:
        lines, size = _fit_arc(cleaned, font_path, size, spacing)
    else:
        lines, size = _fit_straight(cleaned, font_path, size, spacing, turn / 10)
    layout = PjskTextLayout(
        lines=lines,
        x=pivot_x,
        y=pivot_y,
        rotate=turn,
        font_size=size,
        line_spacing=spacing,
        curve=bool(curve),
    )
    font = sticker_font(font_path, size)
    if curve:
        box = _arc_box(lines, font, size, spacing)
        placed = (
            _clamp_offsets(pivot_x, pivot_y, box, layout.radians)
            if box is not None
            else (pivot_x, pivot_y)
        )
    else:
        placed = _clamp_pivot(layout, font)
    if placed == (layout.x, layout.y):
        return layout
    return PjskTextLayout(
        lines=lines,
        x=placed[0],
        y=placed[1],
        rotate=turn,
        font_size=size,
        line_spacing=spacing,
        curve=bool(curve),
    )


def _paste_tile(layer: Image.Image, tile: Image.Image, left: int, top: int) -> None:
    """Alpha-composite one tile, cropping whatever falls outside the layer."""
    crop_left = max(0, -left)
    crop_top = max(0, -top)
    crop_right = min(tile.width, layer.width - left)
    crop_bottom = min(tile.height, layer.height - top)
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return
    if (crop_left, crop_top, crop_right, crop_bottom) != (
        0,
        0,
        tile.width,
        tile.height,
    ):
        tile = tile.crop((crop_left, crop_top, crop_right, crop_bottom))
    layer.alpha_composite(tile, (left + crop_left, top + crop_top))


def _text_passes(colour: str, stroke: int) -> tuple[tuple[str, int], ...]:
    """Halo first, glyphs second, so neighbours never overpaint each other."""
    if stroke <= 0:
        return ((colour, 0),)
    return (("#ffffff", stroke), (colour, 0))


def _draw_straight(
    layer: Image.Image,
    layout: PjskTextLayout,
    font: ImageFont.FreeTypeFont,
    colour: str,
    pivot: tuple[float, float],
    supersample: int,
    stroke: int,
) -> None:
    """Stack the lines on the pivot the way the upstream canvas does."""
    step = layout.font_size * layout.line_spacing * supersample
    for fill, width in _text_passes(colour, stroke):
        pass_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(pass_layer)
        for offset, line in enumerate(layout.lines):
            if not line:
                continue
            draw.text(
                (pivot[0], pivot[1] + offset * step),
                line,
                font=font,
                fill=fill,
                anchor="ms",
                stroke_width=width,
                stroke_fill=fill,
            )
        layer.alpha_composite(pass_layer)


def _arc_pass(
    target: Image.Image,
    layout: PjskTextLayout,
    font: ImageFont.FreeTypeFont,
    pivot: tuple[float, float],
    supersample: int,
    fill: str,
    stroke: int,
) -> None:
    """Paint one arc pass; the halo and glyph passes share this geometry."""
    ascent, descent = font.getmetrics()
    advance = max(
        (font.getlength(char) for line in layout.lines for char in line),
        default=float(font.size),
    )
    reach = math.hypot(advance / 2, max(ascent, descent)) + stroke
    side = 2 * math.ceil(reach) + 4
    step = layout.font_size * layout.line_spacing * supersample
    base_radius = layout.font_size * ARC_RADIUS_RATIO * supersample
    for offset, line in enumerate(layout.lines):
        if not line:
            continue
        radius = _arc_radius(line, font, base_radius)
        angles, _ = _arc_geometry(line, font, radius)
        centre_y = pivot[1] + offset * step + radius
        for char, angle in zip(line, angles, strict=True):
            tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text(
                (side / 2, side / 2),
                char,
                font=font,
                fill=fill,
                anchor="ms",
                stroke_width=stroke,
                stroke_fill=fill,
            )
            tile = tile.rotate(
                -math.degrees(angle),
                resample=Image.Resampling.BICUBIC,
                center=(side / 2, side / 2),
            )
            spot_x = pivot[0] + radius * math.sin(angle)
            spot_y = centre_y - radius * math.cos(angle)
            _paste_tile(
                target,
                tile,
                round(spot_x - side / 2),
                round(spot_y - side / 2),
            )


def _draw_arc(
    layer: Image.Image,
    layout: PjskTextLayout,
    font: ImageFont.FreeTypeFont,
    colour: str,
    pivot: tuple[float, float],
    supersample: int,
    stroke: int,
) -> None:
    """Bend each line over its own arc, with the apex on the pivot."""
    for fill, width in _text_passes(colour, stroke):
        pass_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        _arc_pass(pass_layer, layout, font, pivot, supersample, fill, width)
        layer.alpha_composite(pass_layer)

def sticker_path(image_root: Path, sticker: catalog.PjskSticker) -> Path:
    """Resolve one catalogue-relative sticker path under an images root."""
    return Path(image_root).joinpath(*sticker.image.split("/"))


def render_sticker(
    sticker: catalog.PjskSticker,
    text: str,
    *,
    image_path: Path,
    font_path: Path | None = None,
    x: float | str | None = None,
    y: float | str | None = None,
    rotate: float | str | None = None,
    font_size: float | str | None = None,
    line_spacing: float | str | None = None,
    curve: bool = False,
    scale: float | str | None = None,
) -> bytes:
    """Draw one PJSK sticker and return PNG bytes."""
    layout = resolve_layout(
        sticker,
        text,
        font_path=font_path,
        x=x,
        y=y,
        rotate=rotate,
        font_size=font_size,
        line_spacing=line_spacing,
        curve=curve,
    )
    supersample = SUPERSAMPLE
    width = catalog.CANVAS_WIDTH * supersample
    height = catalog.CANVAS_HEIGHT * supersample
    stroke = max(1, round(STROKE_WIDTH * supersample))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    artwork = open_static(image_path)
    target = contain_size(artwork.size, (width, height))
    artwork = artwork.resize(target, Image.Resampling.LANCZOS)
    canvas.alpha_composite(
        artwork, ((width - target[0]) // 2, (height - target[1]) // 2)
    )
    font = sticker_font(font_path, layout.font_size * supersample)
    layer = Image.new("RGBA", (width * 3, height * 3), (0, 0, 0, 0))
    pivot = (width + layout.x * supersample, height + layout.y * supersample)
    colour = sticker.character.color
    if layout.curve:
        _draw_arc(layer, layout, font, colour, pivot, supersample, stroke)
    else:
        _draw_straight(layer, layout, font, colour, pivot, supersample, stroke)
    if abs(layout.rotate) > 1e-9:
        layer = layer.rotate(
            -math.degrees(layout.radians),
            resample=Image.Resampling.BICUBIC,
            center=pivot,
        )
    canvas.alpha_composite(layer.crop((width, height, width * 2, height * 2)))
    output_scale = _resolve_scale(scale)
    final = (
        catalog.CANVAS_WIDTH * output_scale,
        catalog.CANVAS_HEIGHT * output_scale,
    )
    if final != canvas.size:
        canvas = canvas.resize(final, Image.Resampling.LANCZOS)
    return save_png(canvas)

#: Dark palette shared by every PJSK contact sheet.
SHEET_BACKGROUND = "#0d1220"
SHEET_HEADER = "#151d2d"
SHEET_CARD = "#182131"
SHEET_CARD_ALT = "#1e283b"
SHEET_BORDER = "#2b364f"
SHEET_TEXT = "#eef2fb"
SHEET_MUTED = "#93a0ba"
SHEET_ACCENT = "#5eead4"
SHEET_HEADER_H = 96

SheetFont = ImageFont.FreeTypeFont | ImageFont.ImageFont


@dataclass(frozen=True, slots=True)
class PjskSheetCell:
    """One labelled thumbnail slot on a contact sheet."""

    path: Path
    title: str
    subtitle: str
    accent: str


def _ellipsise(text: str, font: SheetFont, limit: float) -> str:
    """Trim one line until it fits, appending a single ellipsis."""
    if font.getlength(text) <= limit:
        return text
    trimmed = text
    while trimmed and font.getlength(trimmed + "…") > limit:
        trimmed = trimmed[:-1]
    return trimmed + "…" if trimmed else ""


def _label(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: SheetFont,
    fill: str,
    limit: float,
    *,
    centre: bool = False,
) -> None:
    """Draw one clipped single-line label without relying on text anchors."""
    shown = _ellipsise(text, font, limit)
    if not shown:
        return
    left, top = position
    if centre:
        left = int(left + (limit - font.getlength(shown)) / 2)
    draw.text((left, top), shown, font=font, fill=fill)


def _thumbnail(path: Path, box: tuple[int, int]) -> Image.Image | None:
    """Letterbox one sticker into the requested slot, or report a gap."""
    try:
        return fit_into(open_static(path), box, "contain")
    except ImageRenderError:
        return None


def _sheet_header(image: Image.Image, title: str, subtitle: str) -> None:
    """Paint the banner strip at the top of a contact sheet."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, SHEET_HEADER_H), fill=SHEET_HEADER)
    draw.rectangle(
        (0, SHEET_HEADER_H - 3, image.width, SHEET_HEADER_H), fill=SHEET_ACCENT
    )
    limit = image.width - 56
    _label(draw, (28, 22), title, load_font(30, bold=True), SHEET_TEXT, limit)
    _label(draw, (28, 62), subtitle, load_font(17), SHEET_MUTED, limit)


def _sheet_footer(image: Image.Image, footer: str, height: int) -> None:
    """Print the follow-up hint under the grid."""
    if not footer:
        return
    draw = ImageDraw.Draw(image)
    top = image.height - height + 10
    _label(draw, (28, top), footer, load_font(16), SHEET_MUTED, image.width - 56)


def _render_sheet(
    title: str,
    subtitle: str,
    cells: Sequence[PjskSheetCell],
    *,
    columns: int,
    thumb: tuple[int, int],
    footer: str = "",
) -> bytes:
    """Lay labelled thumbnails out on a dark grid and return PNG bytes."""
    columns = max(1, columns)
    gap, pad = 14, 28
    compact = thumb[0] < 160
    inset = 6 if compact else 10
    index_line = 24 if compact else 32
    label_line = 18 if compact else 24
    index_font = load_font(19 if compact else 25, bold=True)
    label_font = load_font(14 if compact else 18)
    cell_w = thumb[0] + inset * 2
    cell_h = inset + thumb[1] + 4 + index_line + label_line + 10
    rows = max(1, -(-len(cells) // columns))
    width = pad * 2 + columns * cell_w + (columns - 1) * gap
    grid_top = SHEET_HEADER_H + pad
    footer_h = 46 if footer else 0
    height = grid_top + rows * cell_h + (rows - 1) * gap + pad + footer_h
    image = Image.new("RGB", (width, height), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(image)
    for position, cell in enumerate(cells):
        row, column = divmod(position, columns)
        left = pad + column * (cell_w + gap)
        top = grid_top + row * (cell_h + gap)
        draw.rounded_rectangle(
            (left, top, left + cell_w, top + cell_h),
            radius=14,
            fill=SHEET_CARD if (row + column) % 2 == 0 else SHEET_CARD_ALT,
            outline=SHEET_BORDER,
        )
        art = _thumbnail(cell.path, thumb)
        if art is not None:
            image.paste(art, (left + inset, top + inset), art)
        text_left = left + inset
        text_top = top + inset + thumb[1] + 4
        _label(
            draw,
            (text_left, text_top),
            cell.title,
            index_font,
            cell.accent,
            thumb[0],
            centre=True,
        )
        _label(
            draw,
            (text_left, text_top + index_line),
            cell.subtitle,
            label_font,
            SHEET_MUTED,
            thumb[0],
            centre=True,
        )
    _sheet_header(image, title, subtitle)
    _sheet_footer(image, footer, footer_h)
    return save_png(image)


def _render_grouped_sheet(
    title: str,
    subtitle: str,
    image_root: Path,
    *,
    thumb: tuple[int, int],
    footer: str = "",
) -> bytes:
    """Draw every sticker as one rounded panel per character."""
    groups = [
        (character, catalog.character_stickers(character))
        for character in catalog.characters()
    ]
    columns = max((len(items) for _, items in groups), default=1)
    gap, pad, panel_pad, panel_gap = 10, 28, 26, 14
    head_line, index_line = 32, 22
    index_font = load_font(15, bold=True)
    name_font = load_font(21, bold=True)
    meta_font = load_font(15)
    cell_w = thumb[0] + 6
    inner = columns * cell_w + (columns - 1) * gap
    width = pad * 2 + panel_pad * 2 + inner
    panel_h = head_line + thumb[1] + 2 + index_line + 14
    footer_h = 46 if footer else 0
    height = (
        SHEET_HEADER_H
        + pad
        + len(groups) * panel_h
        + (len(groups) - 1) * panel_gap
        + pad
        + footer_h
    )
    image = Image.new("RGB", (width, height), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(image)
    content_left = pad + panel_pad
    for row, (character, items) in enumerate(groups):
        top = SHEET_HEADER_H + pad + row * (panel_h + panel_gap)
        draw.rounded_rectangle(
            (pad, top, width - pad, top + panel_h),
            radius=16,
            fill=SHEET_CARD if row % 2 == 0 else SHEET_CARD_ALT,
            outline=SHEET_BORDER,
        )
        draw.rounded_rectangle(
            (pad + 9, top + 15, pad + 13, top + panel_h - 15),
            radius=2,
            fill=character.color,
        )
        _label(
            draw, (content_left, top + 6), character.display_name, name_font,
            SHEET_TEXT, 152,
        )
        _label(
            draw,
            (content_left + 162, top + 10),
            f"序号 {character.range_label} · {character.key}",
            meta_font,
            SHEET_MUTED,
            inner - 172,
        )
        for column, sticker in enumerate(items):
            left = content_left + column * (cell_w + gap)
            art = _thumbnail(sticker_path(image_root, sticker), thumb)
            if art is not None:
                image.paste(art, (left + 3, top + head_line), art)
            _label(
                draw,
                (left + 3, top + head_line + thumb[1] + 2),
                str(sticker.index),
                index_font,
                character.color,
                thumb[0],
                centre=True,
            )
    _sheet_header(image, title, subtitle)
    _sheet_footer(image, footer, footer_h)
    return save_png(image)



def render_character_sheet(image_root: Path) -> bytes:
    """Draw the character index shown by the first selection step."""
    cells = [
        PjskSheetCell(
            path=sticker_path(image_root, catalog.character_stickers(character)[0]),
            title=character.range_label,
            subtitle=character.display_name,
            accent=character.color,
        )
        for character in catalog.characters()
    ]
    return _render_sheet(
        "PJSK 表情工坊 · 角色总览",
        f"{len(cells)} 位角色 · {catalog.IMAGE_COUNT} 张底图，先认区间再挑单张",
        cells,
        columns=6,
        thumb=(176, 152),
        footer=(
            "下一步：/pjsk表情 未来 → 看单张序号 ｜ /pjsk 206 你好呀 → 直接出图"
        ),
    )


def render_character_stickers_sheet(
    image_root: Path,
    character: catalog.PjskCharacter,
) -> bytes:
    """Draw one character page where every thumbnail shows its 序号."""
    items = catalog.character_stickers(character)
    cells = [
        PjskSheetCell(
            path=sticker_path(image_root, sticker),
            title=str(sticker.index),
            subtitle=sticker.name,
            accent=character.color,
        )
        for sticker in items
    ]
    return _render_sheet(
        f"PJSK · {character.display_name}",
        f"{len(cells)} 张底图 · 序号 {character.range_label} · 别名 {character.key}",
        cells,
        columns=4 if len(cells) <= 12 else 5,
        thumb=(220, 190),
        footer=f"用法：/pjsk {items[0].index} 你想说的话 （可加 -c 弧形、-s 字号）",
    )


def render_all_stickers_sheet(image_root: Path) -> bytes:
    """Draw the full 359-sticker contact sheet, grouped by character."""
    return _render_grouped_sheet(
        "PJSK 表情工坊 · 全部底图",
        f"{catalog.IMAGE_COUNT} 张底图按角色分组，数字即 /pjsk 序号",
        image_root,
        thumb=(76, 66),
        footer="太长可改用 /pjsk表情 <角色> 只看一位角色",
    )
