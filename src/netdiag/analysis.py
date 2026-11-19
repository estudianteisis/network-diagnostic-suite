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
            "p95": (
                round(statistics.quantiles(latencies, n=20, method="inclusive")[18], 2)
                if len(latencies) >= 2
                else (round(latencies[0], 2) if latencies else None)
            ),
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
    incidents = []
    for incident in (event for event in events if event["kind"] == "quality_incident"):
        incidents.append(
            {
                "timestamp_utc": incident["timestamp_utc"],
                "probe": incident["target"],
                "state": incident.get("detail", {}).get("state"),
                "signal": incident.get("detail", {}).get("signal"),
                "latency_ms": incident.get("duration_ms"),
                "baseline_ms": incident.get("detail", {}).get("baseline_ms"),
            }
        )
    metrics = {name: metric(items) for name, items in sorted(grouped.items())}
    started_events = [item for item in incidents if item["state"] == "started"]
    failure_rates = [
        value["failure_rate"] for value in metrics.values() if value["failure_rate"] is not None
    ]
    if started_events:
        health = "Se detectaron degradaciones de calidad"
    elif failure_rates and max(failure_rates) > 0:
        health = "Hubo respuestas perdidas aisladas"
    else:
        health = "No se detectaron degradaciones en esta sesion"
    return {
        "schema_version": 2,
        "started_utc": events[0]["timestamp_utc"] if events else None,
        "ended_utc": events[-1]["timestamp_utc"] if events else None,
        "overview": {
            "health": health,
            "automatic_incidents": len(started_events),
            "manual_notes": len(markers),
        },
        "metrics": metrics,
        "incidents": incidents,
        "markers": markers,
        "caveat": "Classifications are evidence-compatible hypotheses, not proof of causality.",
    }


def create_report(session_dir: Path, window_seconds: float = 10.0) -> tuple[Path, Path]:
    events = read_events(session_dir)
    summary = summarize(events, window_seconds)
    summary_path = session_dir / "summary.json"
    write_json(summary_path, summary)
    from .detection import human_probe

    rows = "".join(
        f"<tr><td><b>{html.escape(human_probe(name))}</b><small>{html.escape(name)}</small></td>"
        f"<td>{m['attempts']}</td><td>{m['failure_rate'] * 100:.1f}%</td>"
        f"<td>{m['latency_ms']['median']}</td><td>{m['latency_ms']['p95']}</td>"
        f"<td>{m['latency_ms']['max']}</td><td>{m['latency_ms']['jitter_mean_abs']}</td></tr>"
        for name, m in summary["metrics"].items()
    )
    marker_html = (
        "".join(
            f"<article><h3>{html.escape(m['timestamp_utc'])}</h3>"
            f"<p><b>{html.escape(m.get('detail', {}).get('note', m['target']))}</b></p>"
            f"<p>{html.escape(m['assessment']['classification'])} "
            f"(confianza {html.escape(m['assessment']['confidence'])})</p>"
            f"<p>{html.escape(m['assessment']['reason'])}</p>"
            "</article>"
            for m in summary["markers"]
        )
        or "<p>No se agregaron anotaciones manuales.</p>"
    )
    incident_html = (
        "".join(
            f"<article class='incident'><h3>{html.escape(item['timestamp_utc'])}</h3>"
            f"<p><b>{html.escape(human_probe(item['probe']))}: "
            f"{html.escape(item['signal'] or 'degradacion')}</b></p>"
            f"<p>Latencia: {item['latency_ms']} ms; base: {item['baseline_ms']} ms.</p></article>"
            for item in summary["incidents"]
            if item["state"] == "started"
        )
        or "<p>No se detectaron bursts sostenidos ni cortes.</p>"
    )
    payload = html.escape(json.dumps(summary, ensure_ascii=False))
    overview = summary["overview"]
    document = f"""<!doctype html><html lang='es'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width'><title>Reporte de calidad de red</title>
<style>:root{{--ink:#152033;--muted:#667085;--line:#e4e7ec;--blue:#175cd3;--bg:#f8fafc}}
body{{font:16px system-ui;max-width:1180px;margin:auto;padding:2rem;color:var(--ink);
background:var(--bg)}}
h1{{margin-bottom:.25rem}}.subtitle,small{{display:block;color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin:2rem 0}}
.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:1.25rem}}
.value{{font-size:1.7rem;font-weight:750}}table{{border-collapse:collapse;width:100%;background:white}}
th,td{{padding:.7rem;border-bottom:1px solid var(--line);text-align:left}}th{{background:#eef4ff}}
article{{background:white;border-left:4px solid var(--blue);padding:.5rem 1rem;margin:1rem 0}}
.incident{{border-color:#f79009}}.warn{{background:#fffaeb;padding:1rem;border-radius:8px}}
code{{word-break:break-all}}@media(max-width:700px){{.cards{{grid-template-columns:1fr}}}}</style>
<h1>Calidad de red</h1><p class='subtitle'>{summary["started_utc"]} a {summary["ended_utc"]}</p>
<div class='cards'><div class='card'><span class='subtitle'>Resultado</span><span class='value'>
{html.escape(overview["health"])}</span></div><div class='card'>
<span class='subtitle'>Degradaciones</span>
<span class='value'>{overview["automatic_incidents"]}</span></div><div class='card'>
<span class='subtitle'>Anotaciones tuyas</span>
<span class='value'>{overview["manual_notes"]}</span></div></div>
<h2>Linea temporal de degradaciones</h2>{incident_html}<h2>Tus anotaciones</h2>{marker_html}
<h2>Metricas por destino</h2><table><thead><tr><th>Medicion</th><th>Muestras</th>
<th>Perdida</th><th>Mediana</th><th>P95</th><th>Maximo</th><th>Jitter</th></tr></thead>
<tbody>{rows}</tbody></table><p class='warn'>{html.escape(summary["caveat"])}</p>
<details><summary>Datos tecnicos completos</summary>
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
