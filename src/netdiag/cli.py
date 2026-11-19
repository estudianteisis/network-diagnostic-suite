from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from .analysis import compare_summaries, create_report
from .monitor import MonitorConfig, mark_event, run_monitor


def endpoint(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("Expected HOST:PORT")
    try:
        return host, int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer") from exc


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="netdiag",
        description="Mide calidad, picos de latencia y cortes sin adivinar la causa.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    monitor = commands.add_parser("start", help="Iniciar medicion en vivo")
    monitor.add_argument("--label", default="player")
    monitor.add_argument("--interval", type=float, default=1.0)
    monitor.add_argument("--public", action="append", default=[])
    monitor.add_argument("--dns-host", default="example.com")
    monitor.add_argument("--direct-dns", action="append", default=[])
    monitor.add_argument("--tcp-host", type=endpoint, default=("1.1.1.1", 443))
    monitor.add_argument("--tls-host", type=endpoint, default=("www.cloudflare.com", 443))
    monitor.add_argument("--gateway")
    monitor.add_argument("--sessions-dir", type=Path, default=Path("sessions"))
    mark = commands.add_parser("note", help="Anotar algo que notaste")
    mark.add_argument("note", help="Ej: ping alto por unos segundos")
    mark.add_argument("--name", default="user-observation")
    mark.add_argument("--sessions-dir", type=Path, default=Path("sessions"))
    report = commands.add_parser("report", help="Crear reporte legible")
    report.add_argument("session", type=Path, nargs="?")
    report.add_argument("--window", type=float, default=10.0)
    compare = commands.add_parser("compare", help="Comparar reportes de dos personas")
    compare.add_argument("summaries", type=Path, nargs="+")
    compare.add_argument("--tolerance", type=float, default=5.0)
    compare.add_argument("--output", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Backwards compatibility without cluttering the user-facing help.
    if argv and argv[0] in {"monitor", "mark"}:
        argv[0] = {"monitor": "start", "mark": "note"}[argv[0]]
    args = parser().parse_args(argv)
    console = Console()
    if args.command == "start":
        if args.interval <= 0:
            raise SystemExit("--interval must be greater than zero")
        config = MonitorConfig(
            label=args.label,
            interval=args.interval,
            public=tuple(args.public or ("1.1.1.1", "8.8.8.8")),
            dns_host=args.dns_host,
            direct_dns=tuple(args.direct_dns or ("1.1.1.1", "8.8.8.8")),
            tcp_host=args.tcp_host,
            tls_host=args.tls_host,
            gateway=args.gateway,
            sessions_dir=args.sessions_dir,
        )
        asyncio.run(run_monitor(config, console))
    elif args.command == "note":
        session = mark_event(args.name, args.note, args.sessions_dir)
        console.print(f"[green]Anotacion guardada[/green] en {session.name}")
    elif args.command == "report":
        session = args.session
        if session is None:
            candidates = sorted(
                (path for path in Path("sessions").glob("*") if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            if not candidates:
                raise SystemExit("No hay sesiones. Ejecuta `netdiag start` primero.")
            session = candidates[0]
        summary, report = create_report(session, args.window)
        console.print(f"[green]Reporte creado:[/green] {report}")
        console.print(f"Datos detallados: {summary}")
    elif args.command == "compare":
        result = compare_summaries(args.summaries, args.tolerance)
        rendered = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
            console.print(f"[green]Created:[/green] {args.output}")
        else:
            console.print_json(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
