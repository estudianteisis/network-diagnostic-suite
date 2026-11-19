from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from functools import partial
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .detection import QualityDetector, human_probe, quality_label
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
from .settings import default_measurements_dir, measurement_dir
from .storage import EventStore, write_json
from .system_context import collect_start_context, finish_context
from .targets import CustomTarget


@dataclass(slots=True)
class MonitorConfig:
    name: str = "medicion"
    label: str | None = None  # Legacy API alias; prefer name.
    interval: float = 1.0
    public: tuple[str, ...] = ("1.1.1.1", "8.8.8.8")
    dns_host: str = "example.com"
    direct_dns: tuple[str, ...] = ("1.1.1.1", "8.8.8.8")
    tcp_host: tuple[str, int] = ("1.1.1.1", 443)
    tls_host: tuple[str, int] = ("www.cloudflare.com", 443)
    gateway: str | None = None
    custom_targets: tuple[CustomTarget, ...] = ()
    sessions_dir: Path = field(default_factory=default_measurements_dir)


def make_session_dir(config: MonitorConfig) -> Path:
    return measurement_dir(config.sessions_dir, config.label or config.name)


def build_probes(config: MonitorConfig) -> list[NamedProbe]:
    gateway = config.gateway or discover_gateway()
    probes: list[NamedProbe] = []
    if gateway:
        probes.append(NamedProbe("gateway", partial(icmp_probe, gateway)))
    probes.extend(
        NamedProbe(f"public:{target}", partial(icmp_probe, target)) for target in config.public
    )
    probes.extend(
        NamedProbe(f"custom:{target.title}", partial(icmp_probe, target.address))
        for target in config.custom_targets
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
    metadata["started_local"] = datetime.now().astimezone().isoformat(timespec="seconds")
    metadata["environment"] = collect_start_context()
    write_json(session_dir / "session.json", metadata)
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    (config.sessions_dir / "active-session.txt").write_text(
        str(session_dir.resolve()), encoding="utf-8"
    )
    probes = build_probes(replace(config, gateway=gateway))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    previous_interfaces = None
    console.print("[bold green]NETDIAG - Calidad de red en vivo[/bold green]")
    console.print(f"Sesion: {session_dir}")
    console.print('Marca cualquier sintoma con: [bold]netdiag note "descripcion"[/bold]')
    console.print("Detener y crear reporte: [bold]Ctrl+C[/bold]\n")
    started = time.monotonic()
    detector = QualityDetector()
    incident_count = 0
    latest: dict[str, Event] = {}

    def dashboard() -> Table:
        table = Table(title=f"Estado actual | incidentes automaticos: {incident_count}")
        table.add_column("Medicion", style="bold")
        table.add_column("Resultado", justify="right")
        table.add_column("Estado")
        for probe in probes:
            event = latest.get(probe.name)
            if event is None:
                table.add_row(human_probe(probe.name), "esperando", "...")
            else:
                state = "[green]OK[/green]" if event.ok else "[red]FALLO[/red]"
                table.add_row(human_probe(probe.name), quality_label(event.to_dict()), state)
        return table

    try:
        with Live(dashboard(), console=console, refresh_per_second=4) as live:
            while not stop.is_set():
                cycle_started = time.monotonic()
                results = await asyncio.gather(*(probe.call() for probe in probes))
                for probe, event in zip(probes, results, strict=True):
                    event.detail["probe"] = probe.name
                    event.monotonic_s = time.monotonic() - started
                    store.append(event)
                    latest[probe.name] = event
                    for incident in detector.observe(probe.name, event):
                        incident.monotonic_s = event.monotonic_s
                        store.append(incident)
                        if incident.detail["state"] == "started":
                            incident_count += 1
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
                live.update(dashboard())
                remaining = max(0.0, config.interval - (time.monotonic() - cycle_started))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=remaining)
                except TimeoutError:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.monotonic() - started
        store.append(
            Event(
                "session_end",
                "monitor",
                True,
                detail={"reason": "stopped"},
                monotonic_s=elapsed,
            )
        )
        metadata["ended_utc"] = utc_now()
        metadata["ended_local"] = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata["duration_seconds"] = round(elapsed, 3)
        metadata["environment"] = finish_context(metadata["environment"], elapsed)
        write_json(session_dir / "session.json", metadata)
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
