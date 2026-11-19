from __future__ import annotations

import asyncio
import re
import socket
import ssl
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import dns.resolver
import psutil

from .models import Event

PING_TIME = re.compile(r"(?:time|tiempo)[=<]\s*(\d+)\s*ms", re.IGNORECASE)


def parse_ping_output(output: str, elapsed_ms: float) -> tuple[bool, float | None]:
    match = PING_TIME.search(output)
    if match:
        value = float(match.group(1))
        return True, min(value, elapsed_ms) if value else value
    if re.search(r"TTL[=:]\s*\d+", output, re.IGNORECASE):
        return True, elapsed_ms
    return False, None


async def icmp_probe(target: str, timeout: float = 1.5) -> Event:
    started = time.perf_counter()
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "1",
            "-w",
            str(int(timeout * 1000)),
            target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout + 1)
        elapsed = (time.perf_counter() - started) * 1000
        text = output.decode(errors="replace")
        ok, latency = parse_ping_output(text, elapsed)
        return Event("icmp", target, ok, latency, {"exit_code": process.returncode})
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    except (TimeoutError, OSError) as exc:
        return Event(
            "icmp",
            target,
            False,
            (time.perf_counter() - started) * 1000,
            {"error": type(exc).__name__},
        )


async def dns_probe(host: str, timeout: float = 2.0) -> Event:
    started = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        answers = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout)
        addresses = sorted({item[4][0] for item in answers})
        return Event(
            "dns", host, True, (time.perf_counter() - started) * 1000, {"addresses": addresses[:8]}
        )
    except (TimeoutError, OSError, socket.gaierror) as exc:
        return Event(
            "dns",
            host,
            False,
            (time.perf_counter() - started) * 1000,
            {"error": type(exc).__name__},
        )


async def direct_dns_probe(host: str, resolver: str, timeout: float = 2.0) -> Event:
    started = time.perf_counter()

    def resolve() -> list[str]:
        client = dns.resolver.Resolver(configure=False)
        client.nameservers = [resolver]
        client.timeout = timeout
        client.lifetime = timeout
        return [str(answer) for answer in client.resolve(host, "A")]

    try:
        answers = await asyncio.wait_for(asyncio.to_thread(resolve), timeout + 0.5)
        return Event(
            "dns_direct",
            f"{host}@{resolver}",
            True,
            (time.perf_counter() - started) * 1000,
            {"addresses": answers},
        )
    except Exception as exc:  # dnspython exposes several resolver/transport exceptions
        return Event(
            "dns_direct",
            f"{host}@{resolver}",
            False,
            (time.perf_counter() - started) * 1000,
            {"error": type(exc).__name__},
        )


async def tcp_probe(host: str, port: int, timeout: float = 2.0) -> Event:
    started = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        await writer.wait_closed()
        return Event("tcp", f"{host}:{port}", True, (time.perf_counter() - started) * 1000)
    except (TimeoutError, OSError) as exc:
        return Event(
            "tcp",
            f"{host}:{port}",
            False,
            (time.perf_counter() - started) * 1000,
            {"error": type(exc).__name__},
        )


async def tls_probe(host: str, port: int, timeout: float = 3.0) -> Event:
    started = time.perf_counter()
    context = ssl.create_default_context()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host), timeout
        )
        ssl_object = writer.get_extra_info("ssl_object")
        version = ssl_object.version() if ssl_object else None
        writer.close()
        await writer.wait_closed()
        return Event(
            "tls",
            f"{host}:{port}",
            True,
            (time.perf_counter() - started) * 1000,
            {"version": version},
        )
    except (TimeoutError, OSError, ssl.SSLError) as exc:
        return Event(
            "tls",
            f"{host}:{port}",
            False,
            (time.perf_counter() - started) * 1000,
            {"error": type(exc).__name__},
        )


def interface_snapshot() -> dict[str, dict]:
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    addresses = psutil.net_if_addrs()
    result: dict[str, dict] = {}
    for name in sorted(set(stats) | set(counters)):
        stat = stats.get(name)
        counter = counters.get(name)
        result[name] = {
            "up": stat.isup if stat else None,
            "speed_mbps": stat.speed if stat else None,
            "bytes_sent": counter.bytes_sent if counter else None,
            "bytes_recv": counter.bytes_recv if counter else None,
            "errors_in": counter.errin if counter else None,
            "errors_out": counter.errout if counter else None,
            "drops_in": counter.dropin if counter else None,
            "drops_out": counter.dropout if counter else None,
            "addresses": [
                a.address
                for a in addresses.get(name, [])
                if a.family in (socket.AF_INET, socket.AF_INET6)
            ],
        }
    return result


def discover_gateway() -> str | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | "
        "Select-Object -First 1 -ExpandProperty NextHop)",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        gateway = result.stdout.strip()
        return gateway if gateway and gateway != "0.0.0.0" else None
    except (OSError, subprocess.TimeoutExpired):
        return None


Probe = Callable[[], Awaitable[Event]]


@dataclass(slots=True)
class NamedProbe:
    name: str
    call: Probe
