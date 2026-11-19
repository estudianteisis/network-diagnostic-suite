from __future__ import annotations

import subprocess

import pytest

from netdiag.advanced_capture import AdvancedCaptureError, PktmonCapture


def completed(command: list[str], returncode: int = 0, output: str = ""):
    return subprocess.CompletedProcess(command, returncode, stdout=output, stderr="")


def test_pktmon_uses_bounded_circular_capture_and_only_stops_its_session(tmp_path):
    calls: list[list[str]] = []

    def runner(command: list[str]):
        calls.append(command)
        if command[-1] == "status":
            return completed(command, 1, "No active session")
        return completed(command)

    capture = PktmonCapture(
        tmp_path / "advanced" / "pktmon.etl",
        size_mb=128,
        runner=runner,
        admin_check=lambda: True,
        executable="pktmon.exe",
    )

    metadata = capture.start()
    stopped = capture.stop()
    capture.stop()

    start = calls[1]
    assert start[:3] == ["pktmon.exe", "start", "--capture"]
    assert start[start.index("--comp") + 1] == "nics"
    assert start[start.index("--pkt-size") + 1] == "128"
    assert start[start.index("--file-size") + 1] == "128"
    assert start[start.index("--log-mode") + 1] == "circular"
    assert calls.count(["pktmon.exe", "stop"]) == 1
    assert metadata["state"] == "running"
    assert stopped["state"] == "stopped"


def test_pktmon_refuses_to_replace_an_existing_capture(tmp_path):
    def runner(command: list[str]):
        return completed(command, 0, "Logger Parameters")

    capture = PktmonCapture(
        tmp_path / "pktmon.etl",
        runner=runner,
        admin_check=lambda: True,
        executable="pktmon.exe",
    )

    with pytest.raises(AdvancedCaptureError, match="captura de pktmon activa"):
        capture.preflight()


def test_pktmon_requires_administrator(tmp_path):
    capture = PktmonCapture(
        tmp_path / "pktmon.etl",
        admin_check=lambda: False,
        executable="pktmon.exe",
    )

    with pytest.raises(AdvancedCaptureError, match="administrador"):
        capture.preflight()


def test_pktmon_fails_closed_when_status_is_unknown(tmp_path):
    def runner(command: list[str]):
        return completed(command, 124, "timeout")

    capture = PktmonCapture(
        tmp_path / "pktmon.etl",
        runner=runner,
        admin_check=lambda: True,
        executable="pktmon.exe",
    )

    with pytest.raises(AdvancedCaptureError, match="no pudo confirmar"):
        capture.preflight()
