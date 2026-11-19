from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(slots=True)
class Event:
    kind: str
    target: str
    ok: bool
    duration_ms: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(default_factory=utc_now)
    monotonic_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
