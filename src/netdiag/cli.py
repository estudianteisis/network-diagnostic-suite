from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .advanced_capture import AdvancedCaptureError
from .analysis import compare_summaries, create_report
from .monitor import MonitorConfig, mark_event, run_monitor
from .settings import default_measurements_dir, save_measurements_dir, validate_storage_root
from .targets import add_target, clear_targets, load_targets


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=32, width=100)


def endpoint(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("Expected HOST:PORT")
    try:
        return host, int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer") from exc


def parser() -> argparse.ArgumentParser:
    measurements_dir = default_measurements_dir()
    root = argparse.ArgumentParser(
        prog="netdiag",
        description="Mide calidad, picos de latencia y cortes sin adivinar la causa.",
        formatter_class=HelpFormatter,
    )
    root.add_argument(
        "--version",
        action="version",
        version=f"netdiag {__version__}\nMediciones: {measurements_dir}",
    )
    commands = root.add_subparsers(dest="command", required=True)
    monitor = commands.add_parser(
        "start",
        help="Iniciar medicion en vivo",
        description=(
            "Inicia las sondas simultaneas y muestra una tabla en vivo. "
            "Finaliza limpiamente con Ctrl+C."
        ),
        epilog=(
            "Ejemplos:\n"
            '  netdiag start --name "Ranked noche"\n'
            "  netdiag start --interval 0.5 --target 104.160.136.3 "
            '--target-name "League LAN"\n'
            '  netdiag start --output-dir "D:\\Diagnosticos\\Red"'
            "\n  netdiag start --advanced --capture-size-mb 256"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    monitor.add_argument(
        "--name", default="medicion", metavar="NOMBRE", help="Nombre legible de la medicion"
    )
    monitor.add_argument("--label", dest="name", help=argparse.SUPPRESS)
    monitor.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SEGUNDOS",
        help="Tiempo objetivo entre ciclos de medicion (predeterminado: 1.0)",
    )
    monitor.add_argument(
        "--public",
        action="append",
        default=[],
        metavar="IP",
        help="Destino publico ICMP; repite la opcion para varios (pred.: 1.1.1.1 y 8.8.8.8)",
    )
    monitor.add_argument(
        "--dns-host",
        default="example.com",
        metavar="HOSTNAME",
        help="Hostname utilizado para comprobar resolucion DNS (predeterminado: example.com)",
    )
    monitor.add_argument(
        "--direct-dns",
        action="append",
        default=[],
        metavar="IP_DNS",
        help="Resolvedor DNS directo; repite para varios (pred.: 1.1.1.1 y 8.8.8.8)",
    )
    monitor.add_argument(
        "--tcp-host",
        type=endpoint,
        default=("1.1.1.1", 443),
        metavar="HOST:PUERTO",
        help="Endpoint para probar apertura TCP (predeterminado: 1.1.1.1:443)",
    )
    monitor.add_argument(
        "--tls-host",
        type=endpoint,
        default=("www.cloudflare.com", 443),
        metavar="HOST:PUERTO",
        help="Endpoint para probar handshake TLS (pred.: www.cloudflare.com:443)",
    )
    monitor.add_argument(
        "--gateway",
        metavar="IP",
        help="Gateway local; si se omite, NetDiag intenta detectarlo automaticamente",
    )
    monitor.add_argument(
        "--target", metavar="IP_O_HOSTNAME", help="Destino ICMP adicional para esta sesion"
    )
    monitor.add_argument(
        "--target-name", metavar="TITULO", help="Nombre mostrado en la tabla para --target"
    )
    monitor.add_argument(
        "--save-target", action="store_true", help="Guardar --target para futuras sesiones"
    )
    monitor.add_argument(
        "--clear-targets", action="store_true", help="Borrar destinos guardados antes de iniciar"
    )
    monitor.add_argument(
        "--advanced",
        action="store_true",
        help="Capturar trafico con pktmon; requiere PowerShell como administrador",
    )
    monitor.add_argument(
        "--capture-size-mb",
        type=int,
        default=256,
        metavar="MB",
        help="Tamano maximo del buffer circular de pktmon; solo con --advanced",
    )
    monitor.add_argument(
        "--output-dir",
        dest="sessions_dir",
        type=Path,
        default=measurements_dir,
        metavar="CARPETA",
        help=f"Carpeta de mediciones (predeterminada: {measurements_dir})",
    )
    monitor.add_argument(
        "--sessions-dir",
        dest="sessions_dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    mark = commands.add_parser(
        "note",
        help="Anotar algo que notaste",
        description="Agrega una nota UTC a la medicion activa.",
    )
    mark.add_argument("note", help='Descripcion, por ejemplo: "ping alto por unos segundos"')
    mark.add_argument(
        "--name", default="user-observation", metavar="TIPO", help="Tipo corto de anotacion"
    )
    mark.add_argument(
        "--output-dir",
        dest="sessions_dir",
        type=Path,
        default=measurements_dir,
        metavar="CARPETA",
        help="Carpeta de mediciones donde buscar la sesion activa",
    )
    mark.add_argument(
        "--sessions-dir",
        dest="sessions_dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    report = commands.add_parser(
        "report", help="Crear reporte legible", description="Genera report.html y summary.json."
    )
    report.add_argument(
        "session",
        type=Path,
        nargs="?",
        metavar="MEDICION",
        help="Carpeta de medicion; si se omite, usa la mas reciente",
    )
    report.add_argument(
        "--window",
        type=float,
        default=10.0,
        metavar="SEGUNDOS",
        help="Ventana alrededor de cada anotacion manual",
    )
    report.add_argument(
        "--output-dir",
        type=Path,
        default=measurements_dir,
        metavar="CARPETA",
        help="Carpeta donde buscar la medicion mas reciente",
    )
    compare = commands.add_parser("compare", help="Comparar reportes de dos personas")
    compare.add_argument("summaries", type=Path, nargs="+", metavar="SUMMARY_JSON")
    compare.add_argument(
        "--tolerance",
        type=float,
        default=5.0,
        metavar="SEGUNDOS",
        help="Diferencia maxima para considerar dos anotaciones simultaneas",
    )
    compare.add_argument("--output", type=Path, metavar="ARCHIVO", help="Guardar resultado JSON")
    targets = commands.add_parser("targets", help="Ver o administrar destinos guardados")
    targets.add_argument("--add", metavar="IP_O_HOSTNAME", help="Guardar o actualizar un destino")
    targets.add_argument("--name", help="Nombre del destino")
    targets.add_argument("--clear", action="store_true", help="Borrar todos los destinos")
    targets.add_argument(
        "--output-dir",
        dest="sessions_dir",
        type=Path,
        default=measurements_dir,
        metavar="CARPETA",
        help="Carpeta que contiene saved-targets.json",
    )
    targets.add_argument(
        "--sessions-dir",
        dest="sessions_dir",
        type=Path,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    config = commands.add_parser("config", help="Ver o cambiar la carpeta predeterminada")
    config.add_argument(
        "--reports-dir", type=Path, metavar="CARPETA", help="Nueva carpeta predeterminada"
    )
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
        if not 16 <= args.capture_size_mb <= 4096:
            raise SystemExit("--capture-size-mb debe estar entre 16 y 4096")
        if args.capture_size_mb != 256 and not args.advanced:
            raise SystemExit("--capture-size-mb requiere --advanced")
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
        try:
            args.sessions_dir = validate_storage_root(args.sessions_dir)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        console.print(f"Carpeta de mediciones: [bold]{args.sessions_dir}[/bold]")
        config = MonitorConfig(
            name=args.name,
            interval=args.interval,
            public=tuple(args.public or ("1.1.1.1", "8.8.8.8")),
            dns_host=args.dns_host,
            direct_dns=tuple(args.direct_dns or ("1.1.1.1", "8.8.8.8")),
            tcp_host=args.tcp_host,
            tls_host=args.tls_host,
            gateway=args.gateway,
            custom_targets=tuple(custom_targets),
            advanced=args.advanced,
            capture_size_mb=args.capture_size_mb,
            sessions_dir=args.sessions_dir,
        )
        session: Path | None = None
        try:
            session = asyncio.run(run_monitor(config, console))
        except AdvancedCaptureError as exc:
            console.print(f"[bold red]No se pudo iniciar el modo avanzado:[/bold red] {exc}")
            return 2
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
            session = newest_session(args.output_dir)
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
    elif args.command == "config":
        if args.reports_dir:
            try:
                path = save_measurements_dir(args.reports_dir)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            console.print(f"[green]Carpeta predeterminada actualizada:[/green] {path}")
        else:
            console.print(f"Carpeta predeterminada: [bold]{default_measurements_dir()}[/bold]")
            console.print("Cambiarla: netdiag config --reports-dir RUTA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
