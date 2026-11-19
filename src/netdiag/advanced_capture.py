from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class AdvancedCaptureError(RuntimeError):
    """Raised when an explicitly requested advanced capture cannot run safely."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr="timeout")


@dataclass(slots=True)
class PktmonCapture:
    output_path: Path
    size_mb: int = 256
    runner: Runner = _run
    admin_check: Callable[[], bool] = is_windows_admin
    executable: str | None = None
    owns_session: bool = False

    def preflight(self) -> None:
        if os.name != "nt":
            raise AdvancedCaptureError(
                "El modo avanzado con pktmon solo esta disponible en Windows."
            )
        if not self.admin_check():
            raise AdvancedCaptureError(
                "El modo avanzado requiere una terminal abierta como administrador. "
                "Cierra esta terminal, abre PowerShell como administrador y repite el comando."
            )
        self.executable = self.executable or shutil.which("pktmon")
        if not self.executable:
            raise AdvancedCaptureError("Windows no encontro pktmon.exe en este equipo.")
        status = self.runner([self.executable, "status"])
        if status.returncode == 0:
            raise AdvancedCaptureError(
                "Ya hay una captura de pktmon activa. NetDiag no la detendra ni la reemplazara."
            )
        combined = f"{status.stdout}\n{status.stderr}".lower()
        if "access is denied" in combined or "acceso denegado" in combined:
            raise AdvancedCaptureError(
                "Windows denego el acceso a pktmon. Ejecuta PowerShell como administrador."
            )
        inactive_messages = (
            "not running",
            "no active session",
            "no running session",
            "is not started",
            "no se esta ejecutando",
        )
        if not any(message in combined for message in inactive_messages):
            detail = (status.stderr or status.stdout).strip() or f"codigo {status.returncode}"
            raise AdvancedCaptureError(
                f"NetDiag no pudo confirmar el estado de pktmon y no iniciara una captura: {detail}"
            )

    def start(self) -> dict[str, object]:
        self.preflight()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.executable or "pktmon",
            "start",
            "--capture",
            "--comp",
            "nics",
            "--pkt-size",
            "128",
            "--file-name",
            str(self.output_path),
            "--file-size",
            str(self.size_mb),
            "--log-mode",
            "circular",
        ]
        result = self.runner(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "error desconocido"
            raise AdvancedCaptureError(f"pktmon no pudo iniciar la captura: {detail}")
        self.owns_session = True
        return {
            "enabled": True,
            "tool": "pktmon",
            "state": "running",
            "file": str(self.output_path),
            "size_limit_mb": self.size_mb,
            "log_mode": "circular",
            "packet_bytes": 128,
            "components": "nics",
        }

    def stop(self) -> dict[str, object]:
        if not self.owns_session:
            return {"state": "not-started"}
        result = self.runner([self.executable or "pktmon", "stop"])
        if result.returncode == 0:
            self.owns_session = False
        detail = (result.stderr or result.stdout).strip()
        return {
            "state": "stopped" if result.returncode == 0 else "stop-failed",
            "stop_exit_code": result.returncode,
            "stop_detail": detail,
            "file_exists": self.output_path.exists(),
            "file_size_bytes": self.output_path.stat().st_size if self.output_path.exists() else 0,
        }
