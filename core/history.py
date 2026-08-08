from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class MemeUsageRecord:
    """One successfully delivered meme generation, without image content."""

    key: str
    trigger: str
    platform: str
    session: str
    sender_id: str
    sender_name: str
    created_at: str

    @classmethod
    def from_dict(cls, value: Any) -> MemeUsageRecord | None:
        if not isinstance(value, dict):
            return None
        key = str(value.get("key", "")).strip()
        session = str(value.get("session", "")).strip()
        platform = str(value.get("platform", "")).strip()
        sender_id = str(value.get("sender_id", "")).strip()
        created_at = str(value.get("created_at", "")).strip()
        if not all((key, session, platform, sender_id, created_at)):
            return None
        trigger = str(value.get("trigger", "")).strip() or key
        sender_name = str(value.get("sender_name", "")).strip() or sender_id
        return cls(
            key=key,
            trigger=trigger,
            platform=platform,
            session=session,
            sender_id=sender_id,
            sender_name=sender_name,
            created_at=created_at,
        )


class MemeUsageHistory:
    """Bounded, newest-first usage history suitable for AstrBot KV storage."""

    def __init__(self, records: Any = None, *, max_records: int = 500):
        self.max_records = max(20, int(max_records))
        self.records = self._normalize(records)[: self.max_records]

    @staticmethod
    def _normalize(value: Any) -> list[MemeUsageRecord]:
        if not isinstance(value, list):
            return []
        return [
            record
            for item in value
            if (record := MemeUsageRecord.from_dict(item)) is not None
        ]

    def dump(self) -> list[dict[str, str]]:
        return [asdict(record) for record in self.records]

    def remember(
        self,
        *,
        key: str,
        trigger: str,
        platform: str,
        session: str,
        sender_id: str,
        sender_name: str,
        created_at: str | None = None,
    ) -> MemeUsageRecord:
        record = MemeUsageRecord(
            key=str(key).strip(),
            trigger=str(trigger).strip() or str(key).strip(),
            platform=str(platform).strip(),
            session=str(session).strip(),
            sender_id=str(sender_id).strip(),
            sender_name=str(sender_name).strip() or str(sender_id).strip(),
            created_at=created_at
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        self.records.insert(0, record)
        del self.records[self.max_records :]
        return record

    def recent(
        self,
        *,
        limit: int = 10,
        session: str | None = None,
        platform: str | None = None,
        sender_id: str | None = None,
    ) -> list[MemeUsageRecord]:
        maximum = max(1, min(int(limit), self.max_records))
        return [
            record
            for record in self.records
            if (session is None or record.session == session)
            and (platform is None or record.platform == platform)
            and (sender_id is None or record.sender_id == sender_id)
        ][:maximum]

    def conversation_summaries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for record in self.records:
            summary = summaries.get(record.session)
            if summary is None:
                summaries[record.session] = {
                    "session": record.session,
                    "platform": record.platform,
                    "count": 1,
                    "last_used_at": record.created_at,
                    "last_trigger": record.trigger,
                    "last_key": record.key,
                    "last_sender_name": record.sender_name,
                }
            else:
                summary["count"] += 1
        return list(summaries.values())[: max(1, min(int(limit), 200))]
