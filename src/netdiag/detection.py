from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .models import Event


@dataclass(slots=True)
class QualityDetector:
    """Detect sustained latency bursts, timeouts and recovery without claiming causality."""

    baseline_size: int = 60
    min_baseline: int = 10
    absolute_latency_ms: float = 150.0
    burst_factor: float = 2.5
    consecutive_samples: int = 2
    history: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    streaks: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    active: set[str] = field(default_factory=set)

    def observe(self, probe: str, sample: Event) -> list[Event]:
        if not (probe == "gateway" or probe.startswith("public:") or probe.startswith("custom:")):
            return []
        values = self.history[probe]
        baseline = statistics.median(values) if len(values) >= self.min_baseline else None
        duration = sample.duration_ms
        timeout = not sample.ok
        dynamic_limit = baseline * self.burst_factor if baseline is not None else 0
        high_latency = bool(
            sample.ok
            and duration is not None
            and duration >= max(self.absolute_latency_ms, dynamic_limit)
        )
        bad = timeout or high_latency
        self.streaks[probe] = self.streaks[probe] + 1 if bad else 0
        emitted: list[Event] = []
        if self.streaks[probe] >= self.consecutive_samples and probe not in self.active:
            self.active.add(probe)
            emitted.append(
                Event(
                    "quality_incident",
                    probe,
                    False,
                    duration,
                    {
                        "state": "started",
                        "signal": "timeout" if timeout else "latency_burst",
                        "baseline_ms": round(baseline, 2) if baseline is not None else None,
                        "threshold_ms": round(max(self.absolute_latency_ms, dynamic_limit), 2),
                    },
                )
            )
        elif not bad and probe in self.active:
            self.active.remove(probe)
            emitted.append(
                Event(
                    "quality_incident",
                    probe,
                    True,
                    duration,
                    {"state": "recovered", "signal": "healthy_sample"},
                )
            )
        if sample.ok and duration is not None and not high_latency:
            values.append(float(duration))
            while len(values) > self.baseline_size:
                values.popleft()
        return emitted


def human_probe(name: str) -> str:
    if name == "gateway":
        return "Red local / router"
    if name.startswith("public:"):
        return f"Internet ({name.removeprefix('public:')})"
    if name.startswith("custom:"):
        return name.removeprefix("custom:")
    if name == "dns:system":
        return "DNS del sistema"
    if name.startswith("dns:"):
        return f"DNS ({name.removeprefix('dns:')})"
    return {"tcp": "Conexion TCP", "tls": "Conexion TLS"}.get(name, name)


def quality_label(event: dict[str, Any]) -> str:
    if not event.get("ok"):
        return "Sin respuesta"
    latency = event.get("duration_ms")
    return "--" if latency is None else f"{latency:.0f} ms"
