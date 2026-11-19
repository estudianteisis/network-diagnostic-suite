from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .analysis import compare_summaries, create_report
from .monitor import MonitorConfig, mark_event, run_monitor
from .targets import add_target, clear_targets, load_targets


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
    root.add_argument("--version", action="version", version=f"netdiag {__version__}")
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
    monitor.add_argument("--target", help="IP o hostname adicional para esta sesion")
    monitor.add_argument("--target-name", help="Nombre mostrado para --target")
    monitor.add_argument(
        "--save-target", action="store_true", help="Guardar --target para futuras sesiones"
    )
    monitor.add_argument(
        "--clear-targets", action="store_true", help="Borrar destinos guardados antes de iniciar"
    )
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
    targets = commands.add_parser("targets", help="Ver o administrar destinos guardados")
    targets.add_argument("--add", metavar="IP_O_HOSTNAME")
    targets.add_argument("--name", help="Nombre del destino")
    targets.add_argument("--clear", action="store_true", help="Borrar todos los destinos")
    targets.add_argument("--sessions-dir", type=Path, default=Path("sessions"))
    return root


def newest_session(sessions_dir: Path) -> Path | None:
    candidates = sorted(
        (path for path in sessions_dir.glob("*") if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def finish_session(session: Path, console: Console) -> None:
    console.print("\n[bold green]Medicion terminada limpiamente.[/bold green]")
    console.print(f"Datos crudos guardados en: [bold]{session}[/bold]")
    try:
        answer = console.input("¿Generar el reporte HTML ahora? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in {"y", "yes", "s", "si", "sí"}:
        summary, report = create_report(session)
        console.print(f"[green]Reporte guardado:[/green] {report}")
        console.print(f"Resumen JSON: {summary}")
    else:
        console.print("Reporte omitido. Puedes crearlo luego con: [bold]netdiag report[/bold]")


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
        if args.clear_targets:
            removed = clear_targets(args.sessions_dir)
            console.print(f"Destinos guardados eliminados: {removed}")
        custom_targets = load_targets(args.sessions_dir)
        if args.target:
            if args.save_target:
                target, _path = add_target(args.sessions_dir, args.target, args.target_name)
            else:
                from .targets import CustomTarget, validate_address

                target = CustomTarget(
                    validate_address(args.target),
                    args.target_name or f"Destino {len(custom_targets) + 1}",
                )
            custom_targets = [item for item in custom_targets if item.address != target.address]
            custom_targets.append(target)
        elif args.save_target:
            raise SystemExit("--save-target requiere --target IP_O_HOSTNAME")
        config = MonitorConfig(
            label=args.label,
            interval=args.interval,
            public=tuple(args.public or ("1.1.1.1", "8.8.8.8")),
            dns_host=args.dns_host,
            direct_dns=tuple(args.direct_dns or ("1.1.1.1", "8.8.8.8")),
            tcp_host=args.tcp_host,
            tls_host=args.tls_host,
            gateway=args.gateway,
            custom_targets=tuple(custom_targets),
            sessions_dir=args.sessions_dir,
        )
        session: Path | None = None
        try:
            session = asyncio.run(run_monitor(config, console))
        except KeyboardInterrupt:
            session = newest_session(args.sessions_dir)
        if session is not None:
            finish_session(session, console)
    elif args.command == "note":
        session = mark_event(args.name, args.note, args.sessions_dir)
        console.print(f"[green]Anotacion guardada[/green] en {session.name}")
    elif args.command == "report":
        session = args.session
        if session is None:
            session = newest_session(Path("sessions"))
            if session is None:
                raise SystemExit("No hay sesiones. Ejecuta `netdiag start` primero.")
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
    elif args.command == "targets":
        if args.clear:
            removed = clear_targets(args.sessions_dir)
            console.print(f"Destinos eliminados: {removed}")
        if args.add:
            target, path = add_target(args.sessions_dir, args.add, args.name)
            console.print(f"[green]Guardado:[/green] {target.title} -> {target.address}")
            console.print(f"Configuracion: {path}")
        if not args.add and not args.clear:
            targets = load_targets(args.sessions_dir)
            if not targets:
                console.print("No hay destinos guardados.")
            for target in targets:
                console.print(f"- [bold]{target.title}[/bold]: {target.address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
