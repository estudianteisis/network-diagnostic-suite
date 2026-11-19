from __future__ import annotations

import argparse
import asyncio
import json
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
    root = argparse.ArgumentParser(prog="netdiag", description="Evidence-first network diagnostics")
    commands = root.add_subparsers(dest="command", required=True)
    monitor = commands.add_parser("monitor", help="Start a monitoring session")
    monitor.add_argument("--label", default="player")
    monitor.add_argument("--interval", type=float, default=1.0)
    monitor.add_argument("--public", action="append", default=[])
    monitor.add_argument("--dns-host", default="example.com")
    monitor.add_argument("--direct-dns", action="append", default=[])
    monitor.add_argument("--tcp-host", type=endpoint, default=("1.1.1.1", 443))
    monitor.add_argument("--tls-host", type=endpoint, default=("www.cloudflare.com", 443))
    monitor.add_argument("--gateway")
    monitor.add_argument("--sessions-dir", type=Path, default=Path("sessions"))
    mark = commands.add_parser("mark", help="Mark a symptom in the active session")
    mark.add_argument("name")
    mark.add_argument("--note", default="")
    mark.add_argument("--sessions-dir", type=Path, default=Path("sessions"))
    report = commands.add_parser("report", help="Create summary.json and report.html")
    report.add_argument("session", type=Path)
    report.add_argument("--window", type=float, default=10.0)
    compare = commands.add_parser("compare", help="Compare two or more summary files")
    compare.add_argument("summaries", type=Path, nargs="+")
    compare.add_argument("--tolerance", type=float, default=5.0)
    compare.add_argument("--output", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    console = Console()
    if args.command == "monitor":
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
    elif args.command == "mark":
        session = mark_event(args.name, args.note, args.sessions_dir)
        console.print(f"[green]Marker saved:[/green] {session}")
    elif args.command == "report":
        summary, report = create_report(args.session, args.window)
        console.print(f"[green]Created:[/green] {summary} and {report}")
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
