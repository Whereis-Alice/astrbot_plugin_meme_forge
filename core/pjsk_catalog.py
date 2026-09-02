"""Static catalogue for the PJSK sticker workshop.

The sticker artwork itself is never redistributed with this plugin. Only the
metadata needed to describe, index and lay out the stickers lives here, so the
picker can be shown before any asset has been downloaded.

Metadata is derived from laffylaffyla/sekai-stickers (MIT) at commit
6668a26d37aec08a25674a4f3ad3f886ab9b2af2 - a maintained fork of the archived
TheOriginalAyaka/sekai-stickers that also carries the artwork added to the game
after the original repository stopped updating. Upstream numbers the files per
character (``airi/airi1.png``), so this module keeps that local number and adds
a contiguous 1-based global index that users type in chat commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final

#: Pinned upstream revision the metadata below was generated from.
SOURCE_REPOSITORY: Final = "https://github.com/laffylaffyla/sekai-stickers"
SOURCE_COMMIT: Final = "6668a26d37aec08a25674a4f3ad3f886ab9b2af2"
SOURCE_LICENSE: Final = "MIT"
#: Archived project the pinned fork, and every earlier release of ours, builds on.
ORIGIN_REPOSITORY: Final = "https://github.com/TheOriginalAyaka/sekai-stickers"

#: Canvas the upstream editor draws on; every geometry value is in this space.
CANVAS_WIDTH: Final = 296
CANVAS_HEIGHT: Final = 256

#: Layout shared by every sticker except the first three of each character,
#: expressed as x, y, rotate, font size.
DEFAULT_GEOMETRY: Final = (148, 58, -2.0, 47)
#: Bespoke layouts upstream ships, keyed by the per-character local number.
GEOMETRY_OVERRIDES: Final = {
    2: (148, 58, 0.0, 28),
    3: (140, 79, 2.0, 47),
}

#: Placeholder wording upstream ships, keyed by the per-character local number.
DEFAULT_TEXT: Final = "something"
TEXT_OVERRIDES: Final = {
    1: "keep up",
    2: "nice to meet ya",
    3: "keep at it!",
}

#: key, romanised name, Chinese name, colour, sticker count, aliases
_ROWS: Final = (
    ("airi", "Airi", "桃井爱莉", "#FB8AAC", 30, ("爱莉", "桃井", "桃井愛莉")),
    ("akito", "Akito", "东云彰人", "#FF7722", 28, ("彰人", "东云彰人", "東雲彰人")),
    ("an", "An", "白石杏", "#00BADC", 30, ("杏", "白石杏", "小杏")),
    ("emu", "Emu", "凤笑梦", "#FF66BB", 27, ("笑梦", "凤笑梦", "鳳えむ")),
    ("ena", "Ena", "东云绘名", "#B18F6C", 29, ("绘名", "东云绘名", "東雲絵名")),
    ("haruka", "Haruka", "桐谷遥", "#6495F0", 29, ("遥", "桐谷遥")),
    ("honami", "Honami", "望月穗波", "#F86666", 30, ("穗波", "望月穗波")),
    ("ichika", "Ichika", "星乃一歌", "#33AAEE", 33, ("一歌", "星乃一歌")),
    ("kaito", "KAITO", "KAITO", "#3366CC", 31, ("凯托",)),
    ("kanade", "Kanade", "宵崎奏", "#BB6688", 33, ("奏", "宵崎奏")),
    ("kohane", "Kohane", "小豆泽心羽", "#FF6699", 29, ("心羽", "小豆泽心羽", "小豆沢こはね")),
    ("len", "Len", "镜音连", "#D3BD00", 31, ("连", "镜音连", "镜音len")),
    ("luka", "Luka", "巡音流歌", "#F88CA7", 25, ("流歌", "巡音流歌")),
    ("mafuyu", "Mafuyu", "朝比奈真冬", "#7171AF", 28, ("真冬", "朝比奈真冬")),
    ("meiko", "Meiko", "MEIKO", "#E4485F", 33, ("咩子",)),
    ("miku", "Miku", "初音未来", "#33CCBB", 41, ("未来", "初音未来", "初音")),
    ("minori", "Minori", "花里实乃理", "#F39E7D", 32, ("实乃理", "花里实乃理", "花里美乃梨")),
    ("mizuki", "Mizuki", "晓山瑞希", "#CA8DB6", 29, ("瑞希", "晓山瑞希")),
    ("nene", "Nene", "草薙宁宁", "#19CD94", 27, ("宁宁", "草薙宁宁")),
    ("rin", "Rin", "镜音铃", "#E8A505", 33, ("铃", "镜音铃", "镜音rin")),
    ("rui", "Rui", "神代类", "#BB88EE", 29, ("类", "神代类")),
    ("saki", "Saki", "天马咲希", "#F5B303", 30, ("咲希", "天马咲希")),
    ("shiho", "Shiho", "日野森志步", "#A0C10B", 31, ("志步", "日野森志步")),
    ("shizuku", "Shizuku", "日野森雫", "#5CD0B9", 28, ("雫", "日野森雫")),
    ("touya", "Touya", "青柳冬弥", "#0077DD", 31, ("冬弥", "青柳冬弥")),
    ("tsukasa", "Tsukasa", "天马司", "#F09A04", 30, ("司", "天马司")),
)

#: Totals for the downloadable artwork, verified against SOURCE_COMMIT.
IMAGE_COUNT: Final = 787
IMAGE_BYTES: Final = 55_912_834
#: sha256 over "<relative path>\n<sha256 of the bytes>\n" for all images, sorted.
IMAGE_DIGEST: Final = (
    "5a627976030e3af44f964a65886b71056feae95d37eea70406370bf510c7502d"
)

#: How many stickers the pre-787 catalogue held.
LEGACY_INDEX_COUNT: Final = 359
#: Old global index -> today's global index, used to migrate saved
#: favourites. The previous pin shipped 359 stickers and upstream later
#: re-exported the artwork under fresh per-character numbers, so no metadata
#: links the two numberings. The table below was recovered by matching the
#: pictures themselves (crop to the alpha box, flatten on white, greyscale,
#: resize to 48x48, z-normalise, compare by RMS) within a single character.
#: ``0`` marks the 15 old entries upstream redrew too heavily to match.
_LEGACY_INDEX_TABLE: Final = (
    2, 3, 4, 5, 6, 7, 8, 9, 10, 11,  # 1-10
    1, 14, 15, 43, 42, 41, 40, 38, 37, 36,  # 11-20
    33, 32, 31, 35, 39, 34, 59, 60, 61, 62,  # 21-30
    0, 64, 65, 66, 67, 69, 70, 71, 75, 89,  # 31-40
    90, 91, 92, 93, 94, 95, 96, 97, 98, 99,  # 41-50
    100, 101, 116, 117, 118, 119, 120, 121, 122, 123,  # 51-60
    124, 125, 126, 127, 128, 145, 146, 147, 148, 149,  # 61-70
    150, 151, 152, 153, 154, 156, 157, 155, 174, 175,  # 71-80
    176, 177, 178, 179, 180, 181, 182, 183, 184, 186,  # 81-90
    187, 188, 189, 204, 205, 206, 207, 208, 210, 211,  # 91-100
    214, 215, 216, 217, 218, 219, 220, 209, 0, 238,  # 101-110
    0, 240, 241, 242, 243, 244, 245, 246, 247, 248,  # 111-120
    249, 268, 0, 270, 271, 272, 273, 274, 277, 278,  # 121-130
    279, 280, 281, 284, 282, 301, 302, 303, 305, 306,  # 131-140
    307, 308, 309, 310, 311, 312, 313, 314, 316, 0,  # 141-150
    331, 332, 333, 334, 335, 336, 337, 338, 339, 340,  # 151-160
    341, 342, 343, 361, 362, 363, 364, 365, 366, 368,  # 161-170
    369, 370, 371, 372, 373, 367, 397, 386, 388, 389,  # 171-180
    398, 387, 390, 391, 393, 395, 396, 399, 400, 401,  # 181-190
    414, 415, 416, 417, 418, 419, 420, 421, 422, 423,  # 191-200
    424, 425, 426, 0, 448, 449, 453, 450, 451, 452,  # 201-210
    454, 455, 456, 457, 459, 466, 488, 489, 490, 0,  # 211-220
    492, 0, 0, 496, 497, 498, 0, 500, 501, 502,  # 221-230
    520, 521, 522, 523, 524, 525, 526, 527, 528, 529,  # 231-240
    530, 531, 532, 533, 549, 550, 551, 552, 553, 554,  # 241-250
    0, 0, 557, 558, 559, 561, 562, 576, 577, 578,  # 251-260
    579, 580, 581, 582, 583, 584, 585, 586, 587, 588,  # 261-270
    612, 623, 624, 609, 610, 611, 613, 614, 615, 616,  # 271-280
    617, 618, 619, 622, 621, 620, 638, 639, 640, 641,  # 281-290
    642, 643, 644, 0, 646, 647, 648, 649, 650, 651,  # 291-300
    652, 668, 669, 670, 671, 672, 673, 674, 675, 676,  # 301-310
    677, 678, 679, 680, 681, 682, 699, 700, 701, 702,  # 311-320
    703, 704, 705, 706, 707, 708, 709, 710, 711, 736,  # 321-330
    729, 732, 727, 730, 728, 731, 733, 734, 735, 737,  # 331-340
    738, 739, 741, 740, 766, 768, 767, 758, 759, 760,  # 341-350
    761, 762, 0, 0, 771, 774, 765, 769, 770,  # 351-359
)


@dataclass(frozen=True, slots=True)
class PjskCharacter:
    """One PJSK character and the contiguous index range it owns."""

    key: str
    #: Romanised name as upstream spells it, used when no Chinese name fits.
    roman: str
    name_zh: str
    color: str
    #: How many stickers this character owns; upstream numbers them 1..count.
    count: int
    aliases: tuple[str, ...]
    #: 1-based position in the catalogue, typed as the 角色号 in /sk角色.
    number: int
    first_index: int

    @property
    def last_index(self) -> int:
        return self.first_index + self.count - 1

    @property
    def display_name(self) -> str:
        """Chinese name when it differs from the romanised key."""
        return self.roman if self.name_zh.lower() == self.key else self.name_zh

    @property
    def range_label(self) -> str:
        if self.count == 1:
            return str(self.first_index)
        return f"{self.first_index}-{self.last_index}"


@dataclass(frozen=True, slots=True)
class PjskSticker:
    """One selectable sticker plus the upstream text layout for it."""

    index: int
    #: 1-based position inside the owning character, typed as e.g. miku3.
    local_index: int
    character: PjskCharacter
    image: str
    default_text: str
    x: int
    y: int
    rotate: float
    font_size: int

    @property
    def token(self) -> str:
        """Selector that survives a catalogue renumbering, e.g. ``miku3``."""
        return f"{self.character.key}{self.local_index}"
    @property
    def name(self) -> str:
        return f"{self.character.roman} {self.local_index}"

    @property
    def label(self) -> str:
        return f"{self.index}. {self.character.display_name} {self.local_index}"


@dataclass(frozen=True, slots=True)
class PjskSelection:
    """Outcome of parsing one user selector token."""

    character: PjskCharacter
    sticker: PjskSticker | None

    @property
    def is_exact(self) -> bool:
        return self.sticker is not None


_FULLWIDTH_DIGITS: Final = str.maketrans("０１２３４５６７８９", "0123456789")


def normalise_token(token: str) -> str:
    """Fold one user token into the form alias lookups are keyed on."""
    return token.translate(_FULLWIDTH_DIGITS).strip().strip("#＃").lower()


@lru_cache(maxsize=1)
def characters() -> tuple[PjskCharacter, ...]:
    """Return all 26 characters in catalogue order."""
    built: list[PjskCharacter] = []
    cursor = 1
    for number, row in enumerate(_ROWS, start=1):
        key, roman, name_zh, color, count, aliases = row
        built.append(
            PjskCharacter(
                key=key,
                roman=roman,
                name_zh=name_zh,
                color=color,
                count=count,
                aliases=tuple(aliases),
                number=number,
                first_index=cursor,
            )
        )
        cursor += count
    return tuple(built)


@lru_cache(maxsize=1)
def stickers() -> tuple[PjskSticker, ...]:
    """Return every sticker with its global 1-based index assigned."""
    built: list[PjskSticker] = []
    for character in characters():
        for offset in range(character.count):
            local = offset + 1
            geometry = GEOMETRY_OVERRIDES.get(local, DEFAULT_GEOMETRY)
            x, y, rotate, font_size = geometry
            built.append(
                PjskSticker(
                    index=character.first_index + offset,
                    local_index=local,
                    character=character,
                    image=f"{character.key}/{character.key}{local}.png",
                    default_text=TEXT_OVERRIDES.get(local, DEFAULT_TEXT),
                    x=x,
                    y=y,
                    rotate=rotate,
                    font_size=font_size,
                )
            )
    return tuple(built)


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, PjskCharacter]:
    table: dict[str, PjskCharacter] = {}
    for character in characters():
        for alias in (
            character.key,
            character.roman,
            character.name_zh,
            *character.aliases,
        ):
            table.setdefault(normalise_token(alias), character)
    return table


@lru_cache(maxsize=1)
def expected_images() -> frozenset[str]:
    """Relative image paths the downloader is allowed to keep."""
    return frozenset(sticker.image for sticker in stickers())


def sticker_by_index(index: int) -> PjskSticker | None:
    """Look up one sticker by its global 1-based index."""
    if index < 1 or index > len(stickers()):
        return None
    return stickers()[index - 1]


def sticker_by_legacy_index(index: int) -> PjskSticker | None:
    """Map an index from the pre-787 catalogue onto the sticker it is now.

    Returns ``None`` when the old index never existed or when upstream redrew
    that picture past recognition, so callers can say so instead of silently
    handing back the wrong artwork.
    """
    if index < 1 or index > len(_LEGACY_INDEX_TABLE):
        return None
    return sticker_by_index(_LEGACY_INDEX_TABLE[index - 1])

def find_character(token: str) -> PjskCharacter | None:
    """Resolve one character by key, folder, Chinese name or alias."""
    return _alias_index().get(normalise_token(token))


def character_count() -> int:
    """How many characters the catalogue holds (the 角色号 upper bound)."""
    return len(characters())


def character_by_number(number: int) -> PjskCharacter | None:
    """Look up one character by the 1-based 角色号 shown on the overview."""
    rows = characters()
    if number < 1 or number > len(rows):
        return None
    return rows[number - 1]


def character_stickers(character: PjskCharacter) -> tuple[PjskSticker, ...]:
    """Return the stickers owned by one character, in catalogue order."""
    return stickers()[character.first_index - 1 : character.last_index]


def parse_selector(token: str) -> PjskSelection | None:
    """Parse 137, miku3, 未来3 or 未来 into one selection.

    A bare character name resolves to that character without a sticker, which
    lets callers pick a random sticker from the group.
    """
    cleaned = normalise_token(token)
    if not cleaned:
        return None
    if cleaned.isdigit():
        sticker = sticker_by_index(int(cleaned))
        return PjskSelection(sticker.character, sticker) if sticker else None

    head = cleaned.rstrip("0123456789")
    tail = cleaned[len(head) :]
    if head and tail:
        character = find_character(head)
        if character is None:
            return None
        local = int(tail)
        if local < 1 or local > character.count:
            return None
        target = sticker_by_index(character.first_index + local - 1)
        return PjskSelection(character, target)

    character = find_character(cleaned)
    return PjskSelection(character, None) if character else None


def parse_character_selector(token: str) -> PjskCharacter | None:
    """Parse one 角色 selector: 3, 未来, miku or 未来3 all reach 初音未来.

    Digits are read as the 角色号 printed on the overview sheet, which is a
    separate namespace from the sticker 序号 used by ``/sk``.
    """
    cleaned = normalise_token(token)
    if not cleaned:
        return None
    if cleaned.isdigit():
        return character_by_number(int(cleaned))
    selection = parse_selector(cleaned)
    return None if selection is None else selection.character
