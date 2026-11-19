from __future__ import annotations

import getpass
import os
import platform
import socket
from datetime import UTC, datetime
from typing import Any

import psutil

from .probes import interface_snapshot

VPN_HINTS = ("vpn", "wireguard", "wintun", "tap", "tun", "tailscale", "zerotier", "hamachi")
NOTABLE_HINTS = (
    "league",
    "riot",
    "vanguard",
    "discord",
    "steam",
    "onedrive",
    "dropbox",
    "torrent",
    "vpn",
    "zerotier",
    "tailscale",
    "obs",
)


def _network_totals() -> dict[str, int]:
    counters = psutil.net_io_counters()
    return {
        "bytes_sent": counters.bytes_sent,
        "bytes_received": counters.bytes_recv,
        "packets_sent": counters.packets_sent,
        "packets_received": counters.packets_recv,
        "errors_in": counters.errin,
        "errors_out": counters.errout,
        "drops_in": counters.dropin,
        "drops_out": counters.dropout,
    }


def _processes() -> dict[str, Any]:
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            memory = process.info["memory_info"]
            rows.append(
                {
                    "pid": process.info["pid"],
                    "name": process.info["name"] or "unknown",
                    "memory_mb": round((memory.rss if memory else 0) / 1024 / 1024, 1),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    rows.sort(key=lambda item: item["memory_mb"], reverse=True)
    notable = [item for item in rows if any(hint in item["name"].lower() for hint in NOTABLE_HINTS)]
    return {
        "running_count": len(rows),
        "top_by_memory": rows[:20],
        "notable_network_or_game_processes": notable[:30],
        "bandwidth_attribution_available": False,
        "bandwidth_note": (
            "Windows/psutil no atribuye bytes por proceso de forma fiable sin ETW o captura "
            "privilegiada; se reporta trafico total del equipo, no un culpable por proceso."
        ),
    }


def collect_start_context() -> dict[str, Any]:
    interfaces = interface_snapshot()
    vpn_candidates = [
        name
        for name, values in interfaces.items()
        if values.get("up") and any(hint in name.lower() for hint in VPN_HINTS)
    ]
    memory = psutil.virtual_memory()
    return {
        "identity": {
            "user": getpass.getuser(),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "system": {
            "cpu_logical_count": psutil.cpu_count(),
            "memory_total_gb": round(memory.total / 1024**3, 2),
            "memory_used_percent_at_start": memory.percent,
            "boot_time_utc": datetime.fromtimestamp(psutil.boot_time(), UTC).isoformat(),
        },
        "interfaces_at_start": interfaces,
        "possible_vpn_interfaces": vpn_candidates,
        "vpn_note": (
            "Lista heuristica por nombre de interfaz; vacia no prueba que no exista VPN y una "
            "coincidencia no prueba que el trafico pase por ella."
        ),
        "processes_at_start": _processes(),
        "network_totals_at_start": _network_totals(),
        "collector_pid": os.getpid(),
    }


def finish_context(context: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    end = _network_totals()
    start = context.get("network_totals_at_start", {})
    sent = max(0, end["bytes_sent"] - int(start.get("bytes_sent", 0)))
    received = max(0, end["bytes_received"] - int(start.get("bytes_received", 0)))
    duration = max(elapsed_seconds, 0.001)
    context["network_totals_at_end"] = end
    context["session_traffic"] = {
        "bytes_sent": sent,
        "bytes_received": received,
        "average_upload_mbps": round(sent * 8 / duration / 1_000_000, 3),
        "average_download_mbps": round(received * 8 / duration / 1_000_000, 3),
        "note": "Promedio total del equipo durante la medicion; no identifica procesos.",
    }
    context["memory_used_percent_at_end"] = psutil.virtual_memory().percent
    return context
