"""Parse the chat arguments accepted by the PJSK sticker commands.

One selector token picks the artwork, the remaining words become the caption
and a few dash options tune the layout. The chat commands and the WebUI
workbench share this table so both validate input the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import pjsk_catalog as catalog
from .pjsk import (
    MAX_FONT_SIZE,
    MAX_LINE_SPACING,
    MAX_OUTPUT_SCALE,
    MAX_TEXT_LENGTH,
    MAX_TEXT_LINES,
    MIN_FONT_SIZE,
    MIN_LINE_SPACING,
)

#: Sub-commands accepted in place of a selector, so /sk 表情 works too.
SHEET_TOKENS = frozenset({"表情", "表情包", "列表", "菜单", "list", "menu"})
#: Sub-commands that open the character index, so /sk 角色 3 works too.
CHARACTER_TOKENS = frozenset({"角色", "角色表", "character", "char"})
#: Tokens that ask for one random sticker.
RANDOM_TOKENS = frozenset({"随机", "随机表情", "抽一张", "random"})
#: Tokens that ask for the usage guide.
HELP_TOKENS = frozenset({"帮助", "用法", "说明", "help", "?", "\uff1f"})

_FULLWIDTH_NUMBERS: dict[int, str] = {
    ord("\uff10") + offset: str(offset) for offset in range(10)
}
_FULLWIDTH_NUMBERS.update(
    {ord("\uff0d"): "-", ord("\u2212"): "-", ord("\uff0e"): ".", ord("\uff0b"): "+"}
)

#: Dash options that take a value, keyed by their lowercase body.
_VALUE_ALIASES: dict[str, str] = {
    "x": "x",
    "横": "x",
    "横向": "x",
    "y": "y",
    "纵": "y",
    "纵向": "y",
    "r": "rotate",
    "rotate": "rotate",
    "旋转": "rotate",
    "角度": "rotate",
    "s": "font_size",
    "size": "font_size",
    "字号": "font_size",
    "大小": "font_size",
    "l": "line_spacing",
    "spacing": "line_spacing",
    "行距": "line_spacing",
    "scale": "scale",
    "倍数": "scale",
    "清晰度": "scale",
}

#: Dash options that behave as switches.
_FLAG_ALIASES: dict[str, str] = {
    "c": "curve",
    "curve": "curve",
    "弧形": "curve",
    "弯曲": "curve",
    "曲线": "curve",
}

#: Accepted range and user-facing label for every value option.
_BOUNDS: dict[str, tuple[float, float, str]] = {
    "x": (0.0, float(catalog.CANVAS_WIDTH), "横向位置"),
    "y": (0.0, float(catalog.CANVAS_HEIGHT), "纵向位置"),
    "rotate": (-10.0, 10.0, "旋转"),
    "font_size": (float(MIN_FONT_SIZE), float(MAX_FONT_SIZE), "字号"),
    "line_spacing": (MIN_LINE_SPACING, MAX_LINE_SPACING, "行距"),
    "scale": (1.0, float(MAX_OUTPUT_SCALE), "输出倍数"),
}


class PjskCommandError(ValueError):
    """Raised when chat arguments cannot be turned into a render request."""


@dataclass(frozen=True, slots=True)
class PjskArguments:
    """Positional words plus the layout overrides parsed from chat input."""

    words: tuple[str, ...] = ()
    x: float | None = None
    y: float | None = None
    rotate: float | None = None
    font_size: float | None = None
    line_spacing: float | None = None
    curve: bool = False
    scale: int | None = None

    def render_options(self) -> dict[str, Any]:
        """Keyword arguments understood by ``core.pjsk.render_sticker``."""
        return {
            "x": self.x,
            "y": self.y,
            "rotate": self.rotate,
            "font_size": self.font_size,
            "line_spacing": self.line_spacing,
            "curve": self.curve,
            "scale": self.scale,
        }


@dataclass(frozen=True, slots=True)
class PjskTarget:
    """A resolved selector plus the caption text that followed it."""

    character: catalog.PjskCharacter | None
    sticker: catalog.PjskSticker | None
    text: str


def _format_bound(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _normalise_number(text: str) -> str:
    return str(text).translate(_FULLWIDTH_NUMBERS).strip()


def _coerce(field: str, text: str, token: str) -> float:
    low, high, label = _BOUNDS[field]
    try:
        number = float(_normalise_number(text))
    except ValueError:
        raise PjskCommandError(f"{token} 需要一个数字，收到：{text}") from None
    if not low - 1e-9 <= number <= high + 1e-9:
        raise PjskCommandError(
            f"{label}需要在 {_format_bound(low)} ~ {_format_bound(high)} 之间，"
            f"收到：{text}"
        )
    return number


def _split_option(token: str) -> tuple[str, str | None] | None:
    """Recognise -s, --size and --size=40 style tokens, ignoring plain text."""
    if len(token) < 2 or not token.startswith("-"):
        return None
    body = token.lstrip("-")
    if not body:
        return None
    head, separator, tail = body.partition("=")
    name = head.strip().lower()
    if name in _VALUE_ALIASES or name in _FLAG_ALIASES:
        return name, tail if separator else None
    return None


def parse_arguments(tokens: Sequence[str]) -> PjskArguments:
    """Split chat tokens into positional words and validated overrides."""
    words: list[str] = []
    values: dict[str, float] = {}
    curve = False
    pending: tuple[str, str] | None = None
    for raw in tokens:
        token = str(raw or "")
        if not token:
            continue
        if pending is not None:
            field, source = pending
            values[field] = _coerce(field, token, source)
            pending = None
            continue
        option = _split_option(token)
        if option is None:
            words.append(token)
            continue
        name, inline = option
        if name in _FLAG_ALIASES:
            if inline:
                raise PjskCommandError(f"{token} 是开关参数，不需要取值")
            curve = True
            continue
        field = _VALUE_ALIASES[name]
        if inline is None:
            pending = (field, token)
            continue
        values[field] = _coerce(field, inline, token)
    if pending is not None:
        raise PjskCommandError(f"{pending[1]} 后面缺少取值")
    scale = values.pop("scale", None)
    return PjskArguments(
        words=tuple(words),
        curve=curve,
        scale=None if scale is None else round(scale),
        **values,
    )


def _looks_like_index(token: str) -> bool:
    return _normalise_number(token).isdigit()


def resolve_target(words: Sequence[str]) -> PjskTarget:
    """Resolve selector words into a character, a sticker and the caption."""
    items = [str(word) for word in words if str(word or "").strip()]
    if not items:
        return PjskTarget(None, None, "")
    selection = catalog.parse_selector(items[0])
    if selection is None:
        raise PjskCommandError(
            f"认不出「{items[0]}」。发送 /sk角色 看角色号，"
            f"再用 /sk角色 <角色号> 查表情序号（1~{catalog.IMAGE_COUNT}），"
            "也可以用角色名加编号，例如 未来3 或 miku3。"
        )
    character = selection.character
    sticker = selection.sticker
    rest = list(items[1:])
    if sticker is None and rest and _looks_like_index(rest[0]):
        local = int(_normalise_number(rest[0]))
        if 1 <= local <= character.count:
            sticker = catalog.sticker_by_index(character.first_index + local - 1)
            rest.pop(0)
    return PjskTarget(character, sticker, " ".join(rest))


def coerce_options(payload: Any) -> PjskArguments:
    """Validate one WebUI payload of layout overrides."""
    source = dict(payload or {})
    values: dict[str, float] = {}
    for field, bounds in _BOUNDS.items():
        raw = source.get(field)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        values[field] = _coerce(field, str(raw), bounds[2])
    scale = values.pop("scale", None)
    return PjskArguments(
        curve=bool(source.get("curve")),
        scale=None if scale is None else round(scale),
        **values,
    )


def usage_lines() -> tuple[str, ...]:
    """Help block shown by /sk帮助 and by /sk without arguments."""
    spacing = f"{_format_bound(MIN_LINE_SPACING)}~{_format_bound(MAX_LINE_SPACING)}"
    return (
        "PJSK 表情工坊：先按角色号翻角色，再按表情序号配文字。",
        (
            f"1. /sk角色 → 角色总览图（{catalog.character_count()} 位角色，"
            "大号数字就是角色号）"
        ),
        (
            "2. /sk角色 16 → 翻开 16 号角色，看每张底图的表情序号"
            "（也可写 /sk角色 未来）"
        ),
        "3. /sk 206 Wonderhoy → 生成表情包",
        (
            f"两种数字别混：/sk角色 用角色号 1~{catalog.character_count()}，"
            f"/sk 与 /sk表情 用表情序号 1~{catalog.IMAGE_COUNT}。"
        ),
        "选择方式：序号 206、角色加编号 未来3 / miku3、只写角色名则随机一张。",
        "可选参数：",
        f"  -x 横向 0~{catalog.CANVAS_WIDTH}    -y 纵向 0~{catalog.CANVAS_HEIGHT}",
        f"  -r 旋转 -10~10    -s 字号 {MIN_FONT_SIZE}~{MAX_FONT_SIZE}",
        f"  -l 行距 {spacing}    -c 弧形排版    --scale 倍数 1~{MAX_OUTPUT_SCALE}",
        "示例：/sk 未来3 早上好 -s 34 -r 2 -c",
        r"文字中的 \n 会换行。",
        f"单次文字最多 {MAX_TEXT_LINES} 行、{MAX_TEXT_LENGTH} 字。",
        (
            "其他：/sk表情 全部 看整张底图墙，/sk随机 随机一张，"
            "/sk素材状态 查看素材。"
        ),
        "旧写法 /pjsk、/pjsk角色、/pjsk表情 等仍然可用。",
    )
