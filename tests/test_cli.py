import pytest

from netdiag.cli import main, parser


def test_help_lists_simple_commands_only(capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(["--help"])
    output = capsys.readouterr().out
    assert "{start,note,report,compare,targets,config}" in output
    assert "monitor" not in output


def test_legacy_monitor_command_is_still_accepted():
    with pytest.raises(SystemExit, match="greater than zero"):
        main(["monitor", "--interval", "0"])


def test_version_is_available(capsys):
    with pytest.raises(SystemExit, match="0"):
        parser().parse_args(["--version"])
    output = capsys.readouterr().out
    assert output.startswith("netdiag 0.4.0")
    assert "Mediciones:" in output


def test_start_help_describes_every_visible_option(capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(["start", "--help"])
    output = capsys.readouterr().out
    for text in (
        "Tiempo objetivo entre ciclos",
        "Destino publico ICMP",
        "Hostname utilizado",
        "Resolvedor DNS directo",
        "Endpoint para probar apertura TCP",
        "Endpoint para probar handshake TLS",
        "Gateway local",
        "buffer circular de pktmon",
        "Carpeta de mediciones",
        "Ejemplos:",
    ):
        assert text in output


def test_capture_size_requires_advanced():
    with pytest.raises(SystemExit, match="requiere --advanced"):
        main(["start", "--capture-size-mb", "128"])


def test_capture_size_has_safe_limits():
    with pytest.raises(SystemExit, match="entre 16 y 4096"):
        main(["start", "--advanced", "--capture-size-mb", "8"])
