from __future__ import annotations

import html
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import read_events, write_json


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def metric(events: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(events)
    successful = [event for event in events if event.get("ok")]
    latencies = [float(e["duration_ms"]) for e in successful if e.get("duration_ms") is not None]
    deltas = [abs(b - a) for a, b in zip(latencies, latencies[1:], strict=False)]
    return {
        "attempts": attempted,
        "successes": len(successful),
        "failure_rate": round((attempted - len(successful)) / attempted, 4) if attempted else None,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "jitter_mean_abs": round(statistics.mean(deltas), 2) if deltas else None,
        },
    }


def degraded(events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    stats = metric(events)
    return bool(stats["failure_rate"] >= 0.25 or (stats["latency_ms"]["max"] or 0) >= 500)


def classify_window(events: list[dict[str, Any]]) -> dict[str, str]:
    by_probe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        probe = event.get("detail", {}).get("probe")
        if probe:
            by_probe[probe].append(event)
    gateway_bad = degraded(by_probe.get("gateway", []))
    public = [items for name, items in by_probe.items() if name.startswith("public:")]
    public_bad = sum(degraded(items) for items in public)
    dns_bad = any(degraded(items) for name, items in by_probe.items() if name.startswith("dns:"))
    tcp_bad = degraded(by_probe.get("tcp", [])) or degraded(by_probe.get("tls", []))
    if gateway_bad:
        return {
            "classification": "local_network_or_router",
            "confidence": "high" if public_bad else "medium",
            "reason": (
                "The gateway degraded near the marker; the fault is compatible with "
                "LAN/Wi-Fi/NIC/router."
            ),
        }
    if len(public) >= 2 and public_bad >= 2:
        return {
            "classification": "common_upstream_or_access",
            "confidence": "medium",
            "reason": "Gateway stayed healthy while multiple independent public targets degraded.",
        }
    if public_bad == 1:
        return {
            "classification": "selective_route_or_target",
            "confidence": "medium",
            "reason": "Only one public path degraded; a general outage is not supported.",
        }
    if dns_bad and public_bad == 0:
        return {
            "classification": "dns_path_or_resolver",
            "confidence": "medium",
            "reason": "IP reachability was healthy while one or more DNS probes degraded.",
        }
    if tcp_bad and public_bad == 0 and not dns_bad:
        return {
            "classification": "transport_filtering_or_service",
            "confidence": "low",
            "reason": "ICMP/DNS were healthy but TCP or TLS degraded.",
        }
    return {
        "classification": "no_measured_network_fault",
        "confidence": "low",
        "reason": "Measured probes were healthy; a game/client issue is compatible but not proven.",
    }


def summarize(events: list[dict[str, Any]], window_seconds: float = 10.0) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["kind"] in {"icmp", "dns", "dns_direct", "tcp", "tls"}:
            key = event.get("detail", {}).get("probe", f"{event['kind']}:{event['target']}")
            grouped[key].append(event)
    markers = []
    for marker in (event for event in events if event["kind"] == "marker"):
        center = parse_utc(marker["timestamp_utc"])
        nearby = [
            e
            for e in events
            if e["kind"] != "marker"
            and abs((parse_utc(e["timestamp_utc"]) - center).total_seconds()) <= window_seconds
        ]
        markers.append(
            {**marker, "assessment": classify_window(nearby), "window_event_count": len(nearby)}
        )
    return {
        "schema_version": 1,
        "started_utc": events[0]["timestamp_utc"] if events else None,
        "ended_utc": events[-1]["timestamp_utc"] if events else None,
        "metrics": {name: metric(items) for name, items in sorted(grouped.items())},
        "markers": markers,
        "caveat": "Classifications are evidence-compatible hypotheses, not proof of causality.",
    }


def create_report(session_dir: Path, window_seconds: float = 10.0) -> tuple[Path, Path]:
    events = read_events(session_dir)
    summary = summarize(events, window_seconds)
    summary_path = session_dir / "summary.json"
    write_json(summary_path, summary)
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{m['attempts']}</td><td>{m['failure_rate']}</td>"
        f"<td>{m['latency_ms']['median']}</td><td>{m['latency_ms']['max']}</td>"
        f"<td>{m['latency_ms']['jitter_mean_abs']}</td></tr>"
        for name, m in summary["metrics"].items()
    )
    marker_html = (
        "".join(
            f"<article><h3>{html.escape(m['target'])} — {html.escape(m['timestamp_utc'])}</h3>"
            f"<p><b>{html.escape(m['assessment']['classification'])}</b> "
            f"({html.escape(m['assessment']['confidence'])} confidence)</p>"
            f"<p>{html.escape(m['assessment']['reason'])}</p>"
            f"<p>Note: {html.escape(m.get('detail', {}).get('note', ''))}</p></article>"
            for m in summary["markers"]
        )
        or "<p>No manual markers were recorded.</p>"
    )
    payload = html.escape(json.dumps(summary, ensure_ascii=False))
    document = f"""<!doctype html><html lang='en'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width'><title>Network diagnostic report</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:auto;padding:2rem;color:#17202a}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:.55rem;border:1px solid #ccd1d1;text-align:left}}
th{{background:#edf2f7}}article{{border-left:4px solid #5b8def;padding:.2rem 1rem;margin:1rem 0}}
.warn{{background:#fff3cd;padding:1rem}}code{{word-break:break-all}}</style>
<h1>Network Diagnostic Suite report</h1><p class='warn'>{html.escape(summary["caveat"])}</p>
<p>{summary["started_utc"]} → {summary["ended_utc"]}</p><h2>Probe metrics</h2>
<table><thead><tr><th>Probe</th><th>Attempts</th><th>Failure rate</th><th>Median ms</th>
<th>Max ms</th><th>Jitter ms</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Marked events</h2>{marker_html}<details><summary>Machine-readable summary</summary>
<code>{payload}</code></details></html>"""
    report_path = session_dir / "report.html"
    report_path.write_text(document, encoding="utf-8")
    return summary_path, report_path


def compare_summaries(paths: list[Path], tolerance_seconds: float = 5.0) -> dict[str, Any]:
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    matches = []
    if len(summaries) >= 2:
        for left in summaries[0].get("markers", []):
            for right in summaries[1].get("markers", []):
                delta = abs(
                    (
                        parse_utc(left["timestamp_utc"]) - parse_utc(right["timestamp_utc"])
                    ).total_seconds()
                )
                if delta <= tolerance_seconds:
                    matches.append(
                        {
                            "left": left["timestamp_utc"],
                            "right": right["timestamp_utc"],
                            "delta_seconds": delta,
                            "interpretation": (
                                "Concurrent symptoms support, but do not prove, a shared cause."
                            ),
                        }
                    )
    return {
        "schema_version": 1,
        "sources": [str(p) for p in paths],
        "coincident_markers": matches,
        "clock_tolerance_seconds": tolerance_seconds,
        "caveat": "Synchronize system clocks; coincidence does not establish causality.",
    }
