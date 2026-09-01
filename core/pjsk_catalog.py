"""Static catalogue for the PJSK sticker workshop.

The sticker artwork itself is never redistributed with this plugin. Only the
metadata needed to describe, index and lay out the stickers lives here, so the
picker can be shown before any asset has been downloaded.

Metadata is derived from TheOriginalAyaka/sekai-stickers (MIT) at commit
49189d2e63ed715df5de053261f3bc09d9e817f2. Upstream ships an "id" field with
gaps and one duplicate, so this module assigns its own contiguous 1-based index
that users type in chat commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final

#: Pinned upstream revision the metadata below was generated from.
SOURCE_REPOSITORY: Final = "https://github.com/TheOriginalAyaka/sekai-stickers"
SOURCE_COMMIT: Final = "49189d2e63ed715df5de053261f3bc09d9e817f2"
SOURCE_LICENSE: Final = "MIT"

#: Canvas the upstream editor draws on; every geometry value is in this space.
CANVAS_WIDTH: Final = 296
CANVAS_HEIGHT: Final = 256

#: Sticker numbers shared by every character, in upstream order.
BASE_NUMBERS: Final = (
    "01",
    "02",
    "03",
    "04",
    "06",
    "07",
    "08",
    "09",
    "11",
    "12",
    "13",
    "14",
    "16",
)
#: Optional extra numbers appended for characters with more than 13 stickers.
EXTRA_NUMBERS: Final = ("17", "18", "19")

#: Layout used by 356 of the 359 stickers: x, y, rotate, font size.
DEFAULT_GEOMETRY: Final = (148, 58, -2.0, 47)
#: The three stickers upstream gives a bespoke layout, keyed by global index.
GEOMETRY_OVERRIDES: Final = {
    2: (148, 58, 0.0, 28),
    3: (140, 79, 2.0, 47),
    50: (148, 70, -2.0, 38),
}

#: Placeholder wording upstream ships; only four stickers differ from the rest.
DEFAULT_TEXT: Final = "something"
TEXT_OVERRIDES: Final = {
    1: "keep up",
    2: "nice to meet ya",
    3: "keep at it!",
    50: "Wonderhoy!",
}

#: key, folder, file stem, Chinese name, colour, extra sticker count, aliases
_ROWS: Final = (
    ("airi", "airi", "Airi", "桃井爱莉", "#FB8AAC", 0, ("爱莉", "桃井", "桃井愛莉")),
    ("akito", "akito", "Akito", "东云彰人", "#FF7722", 0, ("彰人", "东云彰人", "東雲彰人")),
    ("an", "an", "An", "白石杏", "#00BADC", 0, ("杏", "白石杏", "小杏")),
    ("emu", "emu", "Emu", "凤笑梦", "#FF66BB", 0, ("笑梦", "凤笑梦", "鳳えむ")),
    ("ena", "ena", "Ena", "东云绘名", "#B18F6C", 0, ("绘名", "东云绘名", "東雲絵名")),
    ("haruka", "Haruka", "Haruka", "桐谷遥", "#6495F0", 0, ("遥", "桐谷遥")),
    ("honami", "Honami", "Honami", "望月穗波", "#F86666", 2, ("穗波", "望月穗波")),
    ("ichika", "Ichika", "Ichika", "星乃一歌", "#33AAEE", 2, ("一歌", "星乃一歌")),
    ("kaito", "KAITO", "KAITO", "KAITO", "#3366CC", 0, ("凯托",)),
    ("kanade", "Kanade", "Kanade", "宵崎奏", "#BB6688", 1, ("奏", "宵崎奏")),
    ("kohane", "Kohane", "Kohane", "小豆泽心羽", "#FF6699", 1, ("心羽", "小豆泽心羽", "小豆沢こはね")),
    ("len", "Len", "Len", "镜音连", "#D3BD00", 1, ("连", "镜音连", "镜音len")),
    ("luka", "Luka", "Luka", "巡音流歌", "#F88CA7", 0, ("流歌", "巡音流歌")),
    ("mafuyu", "Mafuyu", "Mafuyu", "朝比奈真冬", "#7171AF", 1, ("真冬", "朝比奈真冬")),
    ("meiko", "Meiko", "Meiko", "MEIKO", "#E4485F", 0, ("咩子",)),
    ("miku", "Miku", "Miku", "初音未来", "#33CCBB", 0, ("未来", "初音未来", "初音")),
    ("minori", "Minori", "Minori", "花里实乃理", "#F39E7D", 1, ("实乃理", "花里实乃理", "花里美乃梨")),
    ("mizuki", "Mizuki", "Mizuki", "晓山瑞希", "#CA8DB6", 1, ("瑞希", "晓山瑞希")),
    ("nene", "Nene", "Nene", "草薙宁宁", "#19CD94", 0, ("宁宁", "草薙宁宁")),
    ("rin", "Rin", "Rin", "镜音铃", "#E8A505", 0, ("铃", "镜音铃", "镜音rin")),
    ("rui", "Rui", "Rui", "神代类", "#BB88EE", 3, ("类", "神代类")),
    ("saki", "Saki", "Saki", "天马咲希", "#F5B303", 2, ("咲希", "天马咲希")),
    ("shiho", "Shiho", "Shiho", "日野森志步", "#A0C10B", 2, ("志步", "日野森志步")),
    ("shizuku", "Shizuku", "Shizuku", "日野森雫", "#5CD0B9", 0, ("雫", "日野森雫")),
    ("touya", "Touya", "Touya", "青柳冬弥", "#0077DD", 2, ("冬弥", "青柳冬弥")),
    ("tsukasa", "Tsukasa", "Tsukasa", "天马司", "#F09A04", 2, ("司", "天马司")),
)

#: Totals for the downloadable artwork, verified against SOURCE_COMMIT.
IMAGE_COUNT: Final = 359
IMAGE_BYTES: Final = 22_374_334
#: sha256 over "<relative path>\n<sha256 of the bytes>\n" for all images, sorted.
IMAGE_DIGEST: Final = "f9329a3a5c013846c569b1072138a88fbc76ce64be55ed366522aa86cd2ffa74"


@dataclass(frozen=True, slots=True)
class PjskCharacter:
    """One PJSK character and the contiguous index range it owns."""

    key: str
    folder: str
    stem: str
    name_zh: str
    color: str
    numbers: tuple[str, ...]
    aliases: tuple[str, ...]
    first_index: int

    @property
    def count(self) -> int:
        return len(self.numbers)

    @property
    def last_index(self) -> int:
        return self.first_index + self.count - 1

    @property
    def display_name(self) -> str:
        """Chinese name when it differs from the romanised key."""
        return self.stem if self.name_zh.lower() == self.key else self.name_zh

    @property
    def range_label(self) -> str:
        if self.count == 1:
            return str(self.first_index)
        return f"{self.first_index}-{self.last_index}"


@dataclass(frozen=True, slots=True)
class PjskSticker:
    """One selectable sticker plus the upstream text layout for it."""

    index: int
    local_index: int
    character: PjskCharacter
    number: str
    image: str
    default_text: str
    x: int
    y: int
    rotate: float
    font_size: int

    @property
    def name(self) -> str:
        return f"{self.character.stem} {self.number}"

    @property
    def label(self) -> str:
        return f"{self.index}. {self.character.display_name} {self.number}"


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
    for key, folder, stem, name_zh, color, extra, aliases in _ROWS:
        numbers = BASE_NUMBERS + EXTRA_NUMBERS[:extra]
        built.append(
            PjskCharacter(
                key=key,
                folder=folder,
                stem=stem,
                name_zh=name_zh,
                color=color,
                numbers=numbers,
                aliases=tuple(aliases),
                first_index=cursor,
            )
        )
        cursor += len(numbers)
    return tuple(built)


@lru_cache(maxsize=1)
def stickers() -> tuple[PjskSticker, ...]:
    """Return every sticker with its global 1-based index assigned."""
    built: list[PjskSticker] = []
    for character in characters():
        for offset, number in enumerate(character.numbers):
            index = character.first_index + offset
            x, y, rotate, font_size = GEOMETRY_OVERRIDES.get(index, DEFAULT_GEOMETRY)
            built.append(
                PjskSticker(
                    index=index,
                    local_index=offset + 1,
                    character=character,
                    number=number,
                    image=f"{character.folder}/{character.stem}_{number}.png",
                    default_text=TEXT_OVERRIDES.get(index, DEFAULT_TEXT),
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
            character.folder,
            character.stem,
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


def find_character(token: str) -> PjskCharacter | None:
    """Resolve one character by key, folder, Chinese name or alias."""
    return _alias_index().get(normalise_token(token))


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
