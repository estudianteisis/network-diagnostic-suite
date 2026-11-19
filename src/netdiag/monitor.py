from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from rich.console import Console

from .models import Event, utc_now
from .probes import (
    NamedProbe,
    direct_dns_probe,
    discover_gateway,
    dns_probe,
    icmp_probe,
    interface_snapshot,
    tcp_probe,
    tls_probe,
)
from .storage import EventStore, write_json


@dataclass(slots=True)
class MonitorConfig:
    label: str = "player"
    interval: float = 1.0
    public: tuple[str, ...] = ("1.1.1.1", "8.8.8.8")
    dns_host: str = "example.com"
    direct_dns: tuple[str, ...] = ("1.1.1.1", "8.8.8.8")
    tcp_host: tuple[str, int] = ("1.1.1.1", 443)
    tls_host: tuple[str, int] = ("www.cloudflare.com", 443)
    gateway: str | None = None
    sessions_dir: Path = Path("sessions")


def make_session_dir(config: MonitorConfig) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in config.label).strip("-")
    return config.sessions_dir / f"{stamp}-{safe_label or 'player'}"


def build_probes(config: MonitorConfig) -> list[NamedProbe]:
    gateway = config.gateway or discover_gateway()
    probes: list[NamedProbe] = []
    if gateway:
        probes.append(NamedProbe("gateway", partial(icmp_probe, gateway)))
    probes.extend(
        NamedProbe(f"public:{target}", partial(icmp_probe, target)) for target in config.public
    )
    probes.append(NamedProbe("dns:system", partial(dns_probe, config.dns_host)))
    probes.extend(
        NamedProbe(f"dns:{resolver}", partial(direct_dns_probe, config.dns_host, resolver))
        for resolver in config.direct_dns
    )
    probes.append(NamedProbe("tcp", partial(tcp_probe, *config.tcp_host)))
    probes.append(NamedProbe("tls", partial(tls_probe, *config.tls_host)))
    return probes


async def run_monitor(config: MonitorConfig, console: Console | None = None) -> Path:
    console = console or Console()
    session_dir = make_session_dir(config)
    store = EventStore(session_dir)
    gateway = config.gateway or discover_gateway()
    metadata = asdict(config)
    metadata["sessions_dir"] = str(config.sessions_dir)
    metadata["gateway"] = gateway
    metadata["started_utc"] = utc_now()
    write_json(session_dir / "session.json", metadata)
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    (config.sessions_dir / "active-session.txt").write_text(
        str(session_dir.resolve()), encoding="utf-8"
    )
    probes = build_probes(MonitorConfig(**{**asdict(config), "gateway": gateway}))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    previous_interfaces = None
    console.print(f"[green]Monitoring[/green] {len(probes)} probes -> {session_dir}")
    console.print("Use [bold]netdiag mark reconnecting[/bold] in another terminal; Ctrl+C stops.")
    started = time.monotonic()
    try:
        while not stop.is_set():
            cycle_started = time.monotonic()
            results = await asyncio.gather(*(probe.call() for probe in probes))
            for probe, event in zip(probes, results, strict=True):
                event.detail["probe"] = probe.name
                event.monotonic_s = time.monotonic() - started
                store.append(event)
            interfaces = interface_snapshot()
            if interfaces != previous_interfaces:
                store.append(
                    Event(
                        "interfaces",
                        "local",
                        True,
                        detail={"snapshot": interfaces},
                        monotonic_s=time.monotonic() - started,
                    )
                )
                previous_interfaces = interfaces
            failed = [
                probe.name for probe, event in zip(probes, results, strict=True) if not event.ok
            ]
            if failed:
                console.print(f"[yellow]{utc_now()} failures:[/yellow] {', '.join(failed)}")
            remaining = max(0.0, config.interval - (time.monotonic() - cycle_started))
            try:
                await asyncio.wait_for(stop.wait(), timeout=remaining)
            except TimeoutError:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        store.append(
            Event(
                "session_end",
                "monitor",
                True,
                detail={"reason": "stopped"},
                monotonic_s=time.monotonic() - started,
            )
        )
        active = config.sessions_dir / "active-session.txt"
        if active.exists() and active.read_text(encoding="utf-8").strip() == str(
            session_dir.resolve()
        ):
            active.unlink()
    console.print(f"[green]Session saved:[/green] {session_dir}")
    return session_dir


def mark_event(name: str, note: str, sessions_dir: Path) -> Path:
    active = sessions_dir / "active-session.txt"
    if not active.exists():
        raise FileNotFoundError("No active session. Start `netdiag monitor` first.")
    session = Path(active.read_text(encoding="utf-8").strip())
    EventStore(session).append(Event("marker", name, True, detail={"note": note}))
    return session
