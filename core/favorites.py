from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image, ImageOps

_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_hex_digest(value: str, length: int) -> bool:
    return len(value) == length and set(value) <= _HEX_DIGITS


@dataclass(frozen=True, slots=True)
class ImageFingerprint:
    sha256: str
    dhash: str | None
    aspect_ratio: float | None


@dataclass(frozen=True, slots=True)
class GeneratedMemeRecord:
    session: str
    key: str
    trigger: str
    sha256: str
    dhash: str | None
    aspect_ratio: float | None

    @classmethod
    def from_dict(cls, value: Any) -> GeneratedMemeRecord | None:
        if not isinstance(value, dict):
            return None
        session = str(value.get("session", "")).strip()
        key = str(value.get("key", "")).strip()
        trigger = str(value.get("trigger", "")).strip() or key
        sha256 = str(value.get("sha256", "")).strip().casefold()
        dhash_value = value.get("dhash")
        dhash = str(dhash_value).strip().casefold() if dhash_value else None
        aspect_value = value.get("aspect_ratio")
        try:
            aspect_ratio = float(aspect_value) if aspect_value is not None else None
        except (TypeError, ValueError):
            aspect_ratio = None
        if not session or not key or not _is_hex_digest(sha256, 64):
            return None
        if dhash is not None and not _is_hex_digest(dhash, 64):
            dhash = None
        return cls(
            session=session,
            key=key,
            trigger=trigger,
            sha256=sha256,
            dhash=dhash,
            aspect_ratio=aspect_ratio,
        )


@dataclass(frozen=True, slots=True)
class FavoriteEntry:
    key: str
    trigger: str

    @classmethod
    def from_dict(cls, value: Any) -> FavoriteEntry | None:
        if not isinstance(value, dict):
            return None
        key = str(value.get("key", "")).strip()
        trigger = str(value.get("trigger", "")).strip() or key
        return cls(key=key, trigger=trigger) if key else None


def fingerprint_image(image: bytes) -> ImageFingerprint:
    sha256 = hashlib.sha256(image).hexdigest()
    try:
        with Image.open(io.BytesIO(image)) as source:
            source.seek(0)
            foreground = ImageOps.exif_transpose(source.convert("RGBA"))
            background = Image.new("RGBA", foreground.size, "white")
            background.alpha_composite(foreground)
            frame = background.convert("RGB")
            aspect_ratio = round(frame.width / max(1, frame.height), 4)
            grayscale = frame.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
            flattened = getattr(grayscale, "get_flattened_data", None)
            pixels = list(flattened() if callable(flattened) else grayscale.getdata())
    except (OSError, SyntaxError, ValueError):
        return ImageFingerprint(sha256=sha256, dhash=None, aspect_ratio=None)

    bits = 0
    bit_count = 0
    for row in range(16):
        offset = row * 17
        for column in range(16):
            bits = (bits << 1) | int(
                pixels[offset + column] > pixels[offset + column + 1]
            )
            bit_count += 1
    return ImageFingerprint(
        sha256=sha256,
        dhash=f"{bits:0{bit_count // 4}x}",
        aspect_ratio=aspect_ratio,
    )


def hash_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return max(len(left), len(right)) * 4


class MemeOutputIndex:
    def __init__(self, records: Any = None, *, max_records: int = 500):
        self.max_records = max(10, int(max_records))
        self.records = self._normalize_records(records)[: self.max_records]

    @staticmethod
    def _normalize_records(records: Any) -> list[GeneratedMemeRecord]:
        if not isinstance(records, list):
            return []
        normalized: list[GeneratedMemeRecord] = []
        for value in records:
            if record := GeneratedMemeRecord.from_dict(value):
                normalized.append(record)
        return normalized

    def dump(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self.records]

    def remember(
        self,
        image: bytes,
        *,
        session: str,
        key: str,
        trigger: str,
    ) -> GeneratedMemeRecord:
        fingerprint = fingerprint_image(image)
        record = GeneratedMemeRecord(
            session=session,
            key=key,
            trigger=trigger or key,
            sha256=fingerprint.sha256,
            dhash=fingerprint.dhash,
            aspect_ratio=fingerprint.aspect_ratio,
        )
        self.records = [
            existing
            for existing in self.records
            if not (
                existing.session == session
                and existing.sha256 == fingerprint.sha256
            )
        ]
        self.records.insert(0, record)
        del self.records[self.max_records :]
        return record

    def match(self, image: bytes, *, session: str) -> GeneratedMemeRecord | None:
        fingerprint = fingerprint_image(image)
        candidates = [record for record in self.records if record.session == session]
        for record in candidates:
            if record.sha256 == fingerprint.sha256:
                return record

        if fingerprint.dhash is None or fingerprint.aspect_ratio is None:
            return None

        matches: list[tuple[int, int, GeneratedMemeRecord]] = []
        for position, record in enumerate(candidates):
            if record.dhash is None or record.aspect_ratio is None:
                continue
            if abs(record.aspect_ratio - fingerprint.aspect_ratio) > 0.03:
                continue
            distance = hash_distance(record.dhash, fingerprint.dhash)
            if distance <= 8:
                matches.append((distance, position, record))
        if not matches:
            return None
        return min(matches)[2]


def normalize_favorites(value: Any) -> list[FavoriteEntry]:
    if not isinstance(value, list):
        return []
    favorites: list[FavoriteEntry] = []
    seen: set[str] = set()
    for item in value:
        entry = FavoriteEntry.from_dict(item)
        if entry is None or entry.key in seen:
            continue
        seen.add(entry.key)
        favorites.append(entry)
    return favorites


def add_favorite(
    favorites: list[FavoriteEntry],
    entry: FavoriteEntry,
    *,
    max_favorites: int,
) -> tuple[list[FavoriteEntry], bool]:
    is_new = all(existing.key != entry.key for existing in favorites)
    updated = [existing for existing in favorites if existing.key != entry.key]
    updated.insert(0, entry)
    return updated[: max(1, max_favorites)], is_new


def remove_favorite(
    favorites: list[FavoriteEntry],
    key: str,
) -> tuple[list[FavoriteEntry], bool]:
    updated = [entry for entry in favorites if entry.key != key]
    return updated, len(updated) != len(favorites)


def dump_favorites(favorites: list[FavoriteEntry]) -> list[dict[str, str]]:
    return [asdict(entry) for entry in favorites]
