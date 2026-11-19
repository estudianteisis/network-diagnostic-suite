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
    assert output.startswith("netdiag 0.3.1")
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
        "Carpeta de mediciones",
        "Ejemplos:",
    ):
        assert text in output
