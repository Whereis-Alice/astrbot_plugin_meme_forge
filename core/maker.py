from __future__ import annotations

import base64
import binascii
import json
import math
import re
import shutil
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageDraw, ImageOps

from .imaging import (
    MAX_INPUT_FRAMES,
    DecodedImage,
    ImageRenderError,
    decode_image,
    fit_into,
    frame_for_time,
    load_font,
    placeholder_image,
    rounded_mask,
    save_gif,
    save_png,
)

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
CJK_RANGES = (
    (0x2E80, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F),
    (0xFF00, 0xFF65),
    (0x3000, 0x303F),
)

TEMPLATE_FILE = "template.json"
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_TEMPLATES = 200
MAX_SLOTS = 16
MAX_IMAGE_SLOTS = 4
MAX_TEXT_SLOTS = 8
MAX_KEYWORDS = 8
MIN_CANVAS = 64
MAX_CANVAS = 2048
MAX_CANVAS_PIXELS = 4_000_000
GIF_INTERVAL_MS = 80
FIT_MODES = ("cover", "contain", "stretch")
ALIGNMENTS = ("left", "center", "right")
VERTICAL_ALIGNMENTS = ("top", "middle", "bottom")


class MakerError(ValueError):
    """Raised for a user-correctable Meme Maker template problem."""


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return max(minimum, min(number, maximum))


def _clamp_choice(value: Any, choices: Sequence[str], default: str) -> str:
    text = str(value or "").strip().casefold()
    return text if text in choices else default


def _clamp_color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if COLOR_PATTERN.match(text) else default


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in CJK_RANGES)


@dataclass(frozen=True, slots=True)
class ImageSlot:
    """One user-supplied picture placed on the template canvas."""

    x: int = 0
    y: int = 0
    width: int = 100
    height: int = 100
    fit: str = "cover"
    radius: int = 0
    circle: bool = False
    rotate: float = 0.0
    opacity: float = 1.0
    flip: bool = False
    grayscale: bool = False
    behind_base: bool = False
    kind: ClassVar[str] = "image"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ImageSlot:
        return cls(
            x=_clamp_int(payload.get("x"), -MAX_CANVAS, MAX_CANVAS, 0),
            y=_clamp_int(payload.get("y"), -MAX_CANVAS, MAX_CANVAS, 0),
            width=_clamp_int(payload.get("width"), 8, MAX_CANVAS, 100),
            height=_clamp_int(payload.get("height"), 8, MAX_CANVAS, 100),
            fit=_clamp_choice(payload.get("fit"), FIT_MODES, "cover"),
            radius=_clamp_int(payload.get("radius"), 0, MAX_CANVAS, 0),
            circle=bool(payload.get("circle", False)),
            rotate=_clamp_float(payload.get("rotate"), -180.0, 180.0, 0.0),
            opacity=_clamp_float(payload.get("opacity"), 0.05, 1.0, 1.0),
            flip=bool(payload.get("flip", False)),
            grayscale=bool(payload.get("grayscale", False)),
            behind_base=bool(payload.get("behind_base", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "image",
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "fit": self.fit,
            "radius": self.radius,
            "circle": self.circle,
            "rotate": self.rotate,
            "opacity": self.opacity,
            "flip": self.flip,
            "grayscale": self.grayscale,
            "behind_base": self.behind_base,
        }


@dataclass(frozen=True, slots=True)
class TextSlot:
    """One caption box with shrink-to-fit layout and optional outline."""

    x: int = 0
    y: int = 0
    width: int = 200
    height: int = 60
    default: str = ""
    color: str = "#111111"
    stroke_color: str = "#ffffff"
    stroke_width: int = 0
    font_size: int = 0
    min_font_size: int = 12
    bold: bool = False
    align: str = "center"
    valign: str = "middle"
    rotate: float = 0.0
    line_spacing: float = 1.18
    max_lines: int = 4
    uppercase: bool = False
    kind: ClassVar[str] = "text"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TextSlot:
        return cls(
            x=_clamp_int(payload.get("x"), -MAX_CANVAS, MAX_CANVAS, 0),
            y=_clamp_int(payload.get("y"), -MAX_CANVAS, MAX_CANVAS, 0),
            width=_clamp_int(payload.get("width"), 16, MAX_CANVAS, 200),
            height=_clamp_int(payload.get("height"), 16, MAX_CANVAS, 60),
            default=str(payload.get("default", ""))[:120],
            color=_clamp_color(payload.get("color"), "#111111"),
            stroke_color=_clamp_color(payload.get("stroke_color"), "#ffffff"),
            stroke_width=_clamp_int(payload.get("stroke_width"), 0, 16, 0),
            font_size=_clamp_int(payload.get("font_size"), 0, 400, 0),
            min_font_size=_clamp_int(payload.get("min_font_size"), 8, 200, 12),
            bold=bool(payload.get("bold", False)),
            align=_clamp_choice(payload.get("align"), ALIGNMENTS, "center"),
            valign=_clamp_choice(payload.get("valign"), VERTICAL_ALIGNMENTS, "middle"),
            rotate=_clamp_float(payload.get("rotate"), -180.0, 180.0, 0.0),
            line_spacing=_clamp_float(payload.get("line_spacing"), 0.8, 2.5, 1.18),
            max_lines=_clamp_int(payload.get("max_lines"), 1, 12, 4),
            uppercase=bool(payload.get("uppercase", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "text",
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "default": self.default,
            "color": self.color,
            "stroke_color": self.stroke_color,
            "stroke_width": self.stroke_width,
            "font_size": self.font_size,
            "min_font_size": self.min_font_size,
            "bold": self.bold,
            "align": self.align,
            "valign": self.valign,
            "rotate": self.rotate,
            "line_spacing": self.line_spacing,
            "max_lines": self.max_lines,
            "uppercase": self.uppercase,
        }


Slot = ImageSlot | TextSlot


@dataclass(frozen=True, slots=True)
class MakerTemplate:
    """One user-authored meme template stored in the plugin data directory."""

    key: str
    title: str
    keywords: tuple[str, ...]
    width: int
    height: int
    background: str = "#ffffff"
    base: str | None = None
    overlay: str | None = None
    slots: tuple[Slot, ...] = ()
    tags: tuple[str, ...] = ()
    author: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def image_slots(self) -> tuple[ImageSlot, ...]:
        return tuple(slot for slot in self.slots if isinstance(slot, ImageSlot))

    @property
    def text_slots(self) -> tuple[TextSlot, ...]:
        return tuple(slot for slot in self.slots if isinstance(slot, TextSlot))

    @property
    def min_texts(self) -> int:
        return sum(1 for slot in self.text_slots if not slot.default)

    @property
    def default_texts(self) -> list[str]:
        return [slot.default for slot in self.text_slots if slot.default]

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "keywords": list(self.keywords),
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "base": self.base,
            "overlay": self.overlay,
            "slots": [slot.to_payload() for slot in self.slots],
            "tags": list(self.tags),
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def summary(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload["image_slots"] = len(self.image_slots)
        payload["text_slots"] = len(self.text_slots)
        payload["min_texts"] = self.min_texts
        return payload


def normalize_key(value: Any) -> str:
    raw = str(value or "").strip()
    if any(token in raw for token in ("/", "\\", "..", ":")):
        raise MakerError("模板 ID 不能包含路径分隔符。")
    text = raw.casefold().replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]", "", text)
    if not KEY_PATTERN.match(text):
        raise MakerError(
            "模板 ID 需为 2~32 位小写字母、数字或下划线，且以字母开头。"
        )
    return text


def normalize_keywords(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        candidates: Iterable[Any] = re.split(r"[\s,，、]+", values)
    elif isinstance(values, Iterable):
        candidates = values
    else:
        raise MakerError("触发词格式无效。")

    keywords: list[str] = []
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        if any(char.isspace() for char in text):
            raise MakerError(f"触发词「{text}」不能包含空格。")
        if len(text) > 16:
            raise MakerError(f"触发词「{text}」超过 16 个字符。")
        if text not in keywords:
            keywords.append(text)
    if not keywords:
        raise MakerError("至少需要一个触发词。")
    if len(keywords) > MAX_KEYWORDS:
        raise MakerError(f"触发词最多 {MAX_KEYWORDS} 个。")
    return tuple(keywords)


def _normalize_slots(values: Any, width: int, height: int) -> tuple[Slot, ...]:
    if not isinstance(values, list):
        raise MakerError("图层列表格式无效。")
    if len(values) > MAX_SLOTS:
        raise MakerError(f"图层最多 {MAX_SLOTS} 个。")

    slots: list[Slot] = []
    images = 0
    texts = 0
    for entry in values:
        if not isinstance(entry, dict):
            raise MakerError("图层格式无效。")
        kind = str(entry.get("type", "image")).strip().casefold()
        if kind == "text":
            texts += 1
            slots.append(TextSlot.from_payload(entry))
        elif kind == "image":
            images += 1
            slots.append(ImageSlot.from_payload(entry))
        else:
            raise MakerError(f"未知图层类型：{kind}")
    if images > MAX_IMAGE_SLOTS:
        raise MakerError(f"图片图层最多 {MAX_IMAGE_SLOTS} 个。")
    if texts > MAX_TEXT_SLOTS:
        raise MakerError(f"文字图层最多 {MAX_TEXT_SLOTS} 个。")
    if not slots:
        raise MakerError("至少需要一个图片或文字图层。")

    bounded: list[Slot] = []
    for slot in slots:
        x = max(-width, min(slot.x, width))
        y = max(-height, min(slot.y, height))
        slot_width = max(8, min(slot.width, MAX_CANVAS))
        slot_height = max(8, min(slot.height, MAX_CANVAS))
        bounded.append(
            replace(slot, x=x, y=y, width=slot_width, height=slot_height)
        )
    return tuple(bounded)


def template_from_payload(
    payload: dict[str, Any],
    *,
    existing: MakerTemplate | None = None,
) -> MakerTemplate:
    """Validate an untrusted template payload from chat or the Dashboard."""
    if not isinstance(payload, dict):
        raise MakerError("模板数据格式无效。")

    key = normalize_key(payload.get("key", existing.key if existing else ""))
    width = _clamp_int(
        payload.get("width", existing.width if existing else 640),
        MIN_CANVAS,
        MAX_CANVAS,
        640,
    )
    height = _clamp_int(
        payload.get("height", existing.height if existing else 640),
        MIN_CANVAS,
        MAX_CANVAS,
        640,
    )
    if width * height > MAX_CANVAS_PIXELS:
        raise MakerError("画布面积超过 400 万像素限制。")

    title = str(payload.get("title", existing.title if existing else "")).strip()[:48]
    keywords = normalize_keywords(
        payload.get("keywords", list(existing.keywords) if existing else [])
    )
    raw_slots = payload.get("slots")
    if raw_slots is None and existing is not None:
        slots = existing.slots
    else:
        slots = _normalize_slots(raw_slots, width, height)

    tags: list[str] = []
    for tag in payload.get("tags", list(existing.tags) if existing else []) or []:
        text = str(tag).strip()[:16]
        if text and text not in tags:
            tags.append(text)

    now = time.time()
    return MakerTemplate(
        key=key,
        title=title or key,
        keywords=keywords,
        width=width,
        height=height,
        background=_clamp_color(
            payload.get("background", existing.background if existing else "#ffffff"),
            "#ffffff",
        ),
        base=existing.base if existing else None,
        overlay=existing.overlay if existing else None,
        slots=slots,
        tags=tuple(tags[:6]),
        author=str(
            payload.get("author", existing.author if existing else "")
        ).strip()[:48],
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )


def template_from_stored(payload: dict[str, Any]) -> MakerTemplate:
    """Rebuild a template from its on-disk JSON, tolerating older files."""
    template = template_from_payload(payload)
    base = payload.get("base")
    overlay = payload.get("overlay")
    return replace(
        template,
        base=str(base) if base else None,
        overlay=str(overlay) if overlay else None,
        created_at=_clamp_float(payload.get("created_at"), 0.0, 4e9, template.created_at),
        updated_at=_clamp_float(payload.get("updated_at"), 0.0, 4e9, template.updated_at),
    )


def decode_data_url(value: Any, *, limit: int = MAX_ASSET_BYTES) -> bytes:
    """Decode a bounded base64 data URL uploaded from the Dashboard."""
    text = str(value or "").strip()
    if not text:
        raise MakerError("缺少图片数据。")
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    text = re.sub(r"\s+", "", text)
    if len(text) > limit * 4 // 3 + 128:
        raise MakerError(
            f"图片数据超过 {limit // 1024 // 1024} MB 限制。"
        )
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MakerError("图片数据不是合法的 base64。") from exc
    if not data:
        raise MakerError("图片数据为空。")
    if len(data) > limit:
        raise MakerError(f"图片超过 {limit // 1024 // 1024} MB 限制。")
    return data


def _asset_suffix(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise MakerError("仅支持 PNG、JPEG、WebP 或 GIF 图片。")


class MakerStore:
    """Persist user-authored templates as JSON plus validated image assets."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def ensure_root(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def template_directory(self, key: str) -> Path:
        safe = normalize_key(key)
        directory = (self.root / safe).resolve(strict=False)
        root = self.root.resolve(strict=False)
        if directory != root and root not in directory.parents:
            raise MakerError("模板路径无效。")
        return directory

    def keys(self) -> list[str]:
        try:
            entries = sorted(entry.name for entry in self.root.iterdir() if entry.is_dir())
        except OSError:
            return []
        return [name for name in entries if KEY_PATTERN.match(name)]

    def load(self, key: str) -> MakerTemplate:
        directory = self.template_directory(key)
        path = directory / TEMPLATE_FILE
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MakerError(f"没有找到模板 {key}。") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise MakerError(f"模板 {key} 数据损坏：{exc}") from exc
        if not isinstance(payload, dict):
            raise MakerError(f"模板 {key} 数据损坏。")
        payload.setdefault("key", directory.name)
        return template_from_stored(payload)

    def templates(self) -> list[MakerTemplate]:
        """Load every readable template, skipping unusable directories."""
        results: list[MakerTemplate] = []
        for key in self.keys():
            try:
                results.append(self.load(key))
            except MakerError:
                continue
        results.sort(key=lambda item: item.key)
        return results

    def save(
        self,
        payload: dict[str, Any],
        *,
        base_data: bytes | None = None,
        overlay_data: bytes | None = None,
        remove_base: bool = False,
        remove_overlay: bool = False,
        reserved_keys: Iterable[str] = (),
    ) -> MakerTemplate:
        """Create or update one template and its optional image assets."""
        key = normalize_key(payload.get("key", ""))
        existing: MakerTemplate | None = None
        directory = self.template_directory(key)
        if (directory / TEMPLATE_FILE).is_file():
            existing = self.load(key)
        elif len(self.keys()) >= MAX_TEMPLATES:
            raise MakerError(f"自制模板最多 {MAX_TEMPLATES} 个。")
        else:
            reserved = {str(value) for value in reserved_keys}
            if key in reserved:
                raise MakerError(f"模板 ID {key} 与已加载的表情包冲突，请换一个。")

        template = template_from_payload(payload, existing=existing)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            return self._write_template(
                template,
                directory,
                base_data=base_data,
                overlay_data=overlay_data,
                remove_base=remove_base,
                remove_overlay=remove_overlay,
            )
        except MakerError:
            if existing is None and not (directory / TEMPLATE_FILE).is_file():
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def _write_template(
        self,
        template: MakerTemplate,
        directory: Path,
        *,
        base_data: bytes | None,
        overlay_data: bytes | None,
        remove_base: bool,
        remove_overlay: bool,
    ) -> MakerTemplate:
        if remove_base:
            self._drop_asset(directory, template.base)
            template = replace(template, base=None)
        if base_data is not None:
            template = replace(
                template, base=self._write_asset(directory, "base", base_data)
            )
        if remove_overlay:
            self._drop_asset(directory, template.overlay)
            template = replace(template, overlay=None)
        if overlay_data is not None:
            template = replace(
                template,
                overlay=self._write_asset(directory, "overlay", overlay_data),
            )

        if template.base is None and not template.image_slots:
            raise MakerError("模板需要底图或至少一个图片图层。")

        path = directory / TEMPLATE_FILE
        tmp_path = directory / f"{TEMPLATE_FILE}.tmp"
        tmp_path.write_text(
            json.dumps(template.to_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return template

    @staticmethod
    def _write_asset(directory: Path, stem: str, data: bytes) -> str:
        suffix = _asset_suffix(data)
        decode_image(data)
        for candidate in ASSET_SUFFIXES:
            stale = directory / f"{stem}{candidate}"
            if stale.is_file() and candidate != suffix:
                stale.unlink(missing_ok=True)
        name = f"{stem}{suffix}"
        (directory / name).write_bytes(data)
        return name

    @staticmethod
    def _drop_asset(directory: Path, name: str | None) -> None:
        if not name:
            return
        candidate = directory / Path(name).name
        if candidate.is_file() and candidate.suffix.casefold() in ASSET_SUFFIXES:
            candidate.unlink(missing_ok=True)

    def delete(self, key: str) -> str:
        directory = self.template_directory(key)
        if not (directory / TEMPLATE_FILE).is_file():
            raise MakerError(f"没有找到模板 {key}。")
        shutil.rmtree(directory, ignore_errors=True)
        return directory.name

    def asset_path(self, template: MakerTemplate, name: str | None) -> Path | None:
        if not name:
            return None
        directory = self.template_directory(template.key)
        candidate = directory / Path(str(name)).name
        if candidate.suffix.casefold() not in ASSET_SUFFIXES or not candidate.is_file():
            return None
        return candidate

    def build_memes(self) -> list[MakerMeme]:
        return [MakerMeme(template, self) for template in self.templates()]


@dataclass(slots=True)
class MakerParams:
    min_images: int
    max_images: int
    min_texts: int
    max_texts: int
    default_texts: list[str]
    options: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class MakerInfo:
    key: str
    params: MakerParams
    keywords: list[str]
    shortcuts: list[Any]
    tags: set[str]


class MakerMeme:
    """Adapter exposing one user template through the shared meme engine."""

    source = "maker"

    def __init__(self, template: MakerTemplate, store: MakerStore):
        self.template = template
        self.store = store
        self.key = template.key
        image_slots = len(template.image_slots)
        self.info = MakerInfo(
            key=template.key,
            params=MakerParams(
                min_images=image_slots,
                max_images=image_slots,
                min_texts=template.min_texts,
                max_texts=len(template.text_slots),
                default_texts=template.default_texts,
                options=[],
            ),
            keywords=list(template.keywords),
            shortcuts=[],
            tags={"maker", "自制", *template.tags},
        )

    @property
    def material_directory(self) -> Path:
        return self.store.template_directory(self.template.key)

    def generate_from_inputs(self, inputs: Any) -> bytes:
        return self._generate(
            [data for _, data in getattr(inputs, "images", [])],
            list(getattr(inputs, "texts", [])),
        )

    def generate_preview(self) -> bytes:
        images = [
            placeholder_image(index)
            for index in range(len(self.template.image_slots))
        ]
        texts = [
            slot.default or f"文字{index + 1}"
            for index, slot in enumerate(self.template.text_slots)
        ]
        return self._generate(images, texts)

    def _generate(self, raw_images: Sequence[bytes], texts: Sequence[str]) -> bytes:
        params = self.info.params
        if len(raw_images) != params.max_images:
            raise ImageRenderError(
                f"需要 {params.max_images} 张图片，实际 {len(raw_images)} 张"
            )
        if len(texts) > params.max_texts:
            raise ImageRenderError(
                f"最多 {params.max_texts} 段文本，实际 {len(texts)} 段"
            )
        decoded = [decode_image(data) for data in raw_images]
        return render_template(self.template, decoded, list(texts), store=self.store)


def _resolve_texts(template: MakerTemplate, texts: Sequence[str]) -> list[str]:
    """Fill required slots first, then optional ones, keeping slot defaults."""
    slots = template.text_slots
    supplied = [str(value) for value in texts]
    if len(supplied) == len(slots):
        return [
            (value if value.strip() else slot.default)
            for value, slot in zip(supplied, slots, strict=True)
        ]

    required = [index for index, slot in enumerate(slots) if not slot.default]
    optional = [index for index, slot in enumerate(slots) if slot.default]
    resolved = [slot.default for slot in slots]
    for position, value in zip(required + optional, supplied, strict=False):
        resolved[position] = value
    return resolved


def _tokenize(paragraph: str) -> list[str]:
    """Split a paragraph into atomic units: CJK chars, spaces and Latin words."""
    tokens: list[str] = []
    buffer = ""
    for char in paragraph:
        if char.isspace() or _is_cjk(char):
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(" " if char.isspace() else char)
        else:
            buffer += char
    if buffer:
        tokens.append(buffer)
    return tokens


def _split_wide_token(
    token: str,
    font: Any,
    draw: ImageDraw.ImageDraw,
    max_width: int,
) -> list[str]:
    """Hard-break a single token that cannot fit the box on its own."""
    parts: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _wrap_text(
    text: str,
    font: Any,
    draw: ImageDraw.ImageDraw,
    max_width: int,
    max_lines: int,
) -> list[str] | None:
    """Wrap on CJK characters and Latin word boundaries, or report overflow."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        tokens: list[str] = []
        for token in _tokenize(paragraph):
            if token != " " and draw.textlength(token, font=font) > max_width:
                tokens.extend(_split_wide_token(token, font, draw, max_width))
            else:
                tokens.append(token)

        current = ""
        for token in tokens:
            if token == " " and not current:
                continue
            candidate = current + token
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current.rstrip())
                current = "" if token == " " else token
        lines.append(current.rstrip())
        if len(lines) > max_lines:
            return None

    if len(lines) > max_lines:
        return None
    for line in lines:
        if len(line) > 1 and draw.textlength(line, font=font) > max_width:
            return None
    return lines


def _render_text_layer(slot: TextSlot, text: str) -> Image.Image | None:
    """Render one caption box as a transparent layer sized to the slot."""
    content = text.strip()
    if not content:
        return None
    if slot.uppercase:
        content = content.upper()

    layer = Image.new("RGBA", (slot.width, slot.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    padding = max(2, slot.stroke_width)
    box_width = max(8, slot.width - padding * 2)
    box_height = max(8, slot.height - padding * 2)

    start = slot.font_size or min(box_height, max(16, int(box_height * 0.9)))
    start = max(slot.min_font_size, min(start, 400))
    chosen_font = None
    chosen_lines: list[str] = []
    for size in range(start, slot.min_font_size - 1, -1):
        font = load_font(size, bold=slot.bold)
        lines = _wrap_text(content, font, draw, box_width, slot.max_lines)
        if lines is None:
            continue
        line_height = size * slot.line_spacing
        if line_height * len(lines) <= box_height:
            chosen_font = font
            chosen_lines = lines
            break
    if chosen_font is None:
        chosen_font = load_font(slot.min_font_size, bold=slot.bold)
        chosen_lines = (
            _wrap_text(content, chosen_font, draw, box_width, slot.max_lines * 3)
            or [content]
        )[: slot.max_lines]

    size = getattr(chosen_font, "size", slot.min_font_size)
    line_height = size * slot.line_spacing
    block_height = line_height * len(chosen_lines)
    if slot.valign == "top":
        top = float(padding)
    elif slot.valign == "bottom":
        top = slot.height - padding - block_height
    else:
        top = (slot.height - block_height) / 2

    for index, line in enumerate(chosen_lines):
        width = draw.textlength(line, font=chosen_font)
        if slot.align == "left":
            left = float(padding)
        elif slot.align == "right":
            left = slot.width - padding - width
        else:
            left = (slot.width - width) / 2
        draw.text(
            (left, top + index * line_height),
            line,
            font=chosen_font,
            fill=slot.color,
            stroke_width=slot.stroke_width or 0,
            stroke_fill=slot.stroke_color if slot.stroke_width else None,
        )
    return layer


def _paste_rotated(canvas: Image.Image, layer: Image.Image, slot: Slot) -> None:
    """Paste a slot layer, rotating around the slot center when requested."""
    center_x = slot.x + slot.width / 2
    center_y = slot.y + slot.height / 2
    working = layer
    if abs(slot.rotate) > 0.01:
        working = layer.rotate(
            slot.rotate, resample=Image.Resampling.BICUBIC, expand=True
        )
    left = round(center_x - working.width / 2)
    top = round(center_y - working.height / 2)
    canvas.alpha_composite(working, (left, top))


def _render_image_slot(slot: ImageSlot, frame: Image.Image) -> Image.Image:
    fitted = fit_into(frame, (slot.width, slot.height), slot.fit)
    if slot.flip:
        fitted = ImageOps.mirror(fitted)
    if slot.grayscale:
        alpha = fitted.getchannel("A")
        fitted = ImageOps.grayscale(fitted).convert("RGBA")
        fitted.putalpha(alpha)
    if slot.circle or slot.radius > 0:
        mask = rounded_mask(fitted.size, slot.radius, circle=slot.circle)
        alpha = fitted.getchannel("A")
        alpha = Image.composite(alpha, Image.new("L", fitted.size, 0), mask)
        fitted.putalpha(alpha)
    if slot.opacity < 0.999:
        alpha = fitted.getchannel("A").point(
            lambda value: int(value * slot.opacity)
        )
        fitted.putalpha(alpha)
    return fitted


def _compose_frame(
    template: MakerTemplate,
    frame_index: int,
    images: Sequence[DecodedImage],
    base: DecodedImage | None,
    overlay: DecodedImage | None,
    text_layers: Sequence[Image.Image | None],
) -> Image.Image:
    size = (template.width, template.height)
    canvas = Image.new("RGBA", size, template.background)
    behind: list[tuple[ImageSlot, int]] = []
    above: list[tuple[ImageSlot, int]] = []
    image_index = 0
    for slot in template.slots:
        if isinstance(slot, ImageSlot):
            (behind if slot.behind_base else above).append((slot, image_index))
            image_index += 1

    for slot, index in behind:
        if index < len(images):
            frame = frame_for_time(images[index], frame_index, GIF_INTERVAL_MS)
            _paste_rotated(canvas, _render_image_slot(slot, frame), slot)

    if base is not None:
        base_frame = frame_for_time(base, frame_index, GIF_INTERVAL_MS)
        canvas.alpha_composite(fit_into(base_frame, size, "cover"), (0, 0))

    for slot, index in above:
        if index < len(images):
            frame = frame_for_time(images[index], frame_index, GIF_INTERVAL_MS)
            _paste_rotated(canvas, _render_image_slot(slot, frame), slot)

    text_index = 0
    for slot in template.slots:
        if isinstance(slot, TextSlot):
            layer = (
                text_layers[text_index] if text_index < len(text_layers) else None
            )
            if layer is not None:
                _paste_rotated(canvas, layer, slot)
            text_index += 1

    if overlay is not None:
        overlay_frame = frame_for_time(overlay, frame_index, GIF_INTERVAL_MS)
        canvas.alpha_composite(fit_into(overlay_frame, size, "cover"), (0, 0))
    return canvas


def _output_frame_count(sources: Sequence[DecodedImage]) -> int:
    animated = [item for item in sources if item.is_animated]
    if not animated:
        return 1
    longest = max(item.total_duration_ms for item in animated)
    frames = max(2, round(longest / GIF_INTERVAL_MS))
    return min(frames, MAX_INPUT_FRAMES)


def render_template(
    template: MakerTemplate,
    images: Sequence[DecodedImage],
    texts: Sequence[str],
    *,
    store: MakerStore,
) -> bytes:
    """Compose one template into a PNG, or a GIF when any input animates."""
    base = None
    overlay = None
    base_path = store.asset_path(template, template.base)
    if base_path is not None:
        base = decode_image(base_path.read_bytes())
    overlay_path = store.asset_path(template, template.overlay)
    if overlay_path is not None:
        overlay = decode_image(overlay_path.read_bytes())
    if base is None and not template.image_slots:
        raise ImageRenderError(f"模板 {template.key} 缺少底图")

    resolved_texts = _resolve_texts(template, texts)
    text_layers = [
        _render_text_layer(slot, value)
        for slot, value in zip(template.text_slots, resolved_texts, strict=True)
    ]

    sources = [*images]
    if base is not None:
        sources.append(base)
    if overlay is not None:
        sources.append(overlay)
    frame_count = _output_frame_count(sources)

    if frame_count <= 1:
        frame = _compose_frame(
            template, 0, images, base, overlay, text_layers
        )
        return save_png(frame.convert("RGBA"))

    frames = [
        _compose_frame(
            template, index, images, base, overlay, text_layers
        )
        for index in range(frame_count)
    ]
    return save_gif(frames, GIF_INTERVAL_MS)


def image_canvas_size(data: bytes) -> tuple[int, int]:
    """Return a bounded canvas size that matches an uploaded base image."""
    decoded = decode_image(data)
    frame = decoded.frames[0]
    width, height = frame.width, frame.height
    if width < 1 or height < 1:
        raise MakerError("底图尺寸无效。")
    scale = min(1.0, MAX_CANVAS / max(width, height))
    pixels = (width * scale) * (height * scale)
    if pixels > MAX_CANVAS_PIXELS:
        scale *= math.sqrt(MAX_CANVAS_PIXELS / pixels)
    return (
        max(MIN_CANVAS, min(round(width * scale), MAX_CANVAS)),
        max(MIN_CANVAS, min(round(height * scale), MAX_CANVAS)),
    )


def caption_template_payload(
    key: str,
    keywords: Any,
    *,
    width: int,
    height: int,
    title: str = "",
    with_image_slot: bool = False,
) -> dict[str, Any]:
    """Build the classic bottom-caption template used by quick chat authoring."""
    band = max(48, int(height * 0.24))
    slots: list[dict[str, Any]] = []
    if with_image_slot:
        slots.append(
            {
                "type": "image",
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
                "fit": "cover",
            }
        )
    return {
        "key": key,
        "title": title or key,
        "keywords": list(normalize_keywords(keywords)),
        "width": width,
        "height": height,
        "background": "#000000",
        "slots": [
            *slots,
            {
                "type": "text",
                "x": int(width * 0.04),
                "y": height - band + int(band * 0.08),
                "width": int(width * 0.92),
                "height": int(band * 0.84),
                "color": "#ffffff",
                "stroke_color": "#000000",
                "stroke_width": max(2, width // 220),
                "bold": True,
                "align": "center",
                "valign": "middle",
                "max_lines": 3,
            },
        ],
    }
