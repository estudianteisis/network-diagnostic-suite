import pytest

from netdiag.cli import main, parser


def test_help_lists_simple_commands_only(capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(["--help"])
    output = capsys.readouterr().out
    assert "{start,note,report,compare,targets}" in output
    assert "monitor" not in output


def test_legacy_monitor_command_is_still_accepted():
    with pytest.raises(SystemExit, match="greater than zero"):
        main(["monitor", "--interval", "0"])


def test_version_is_available(capsys):
    with pytest.raises(SystemExit, match="0"):
        parser().parse_args(["--version"])
    assert capsys.readouterr().out.strip() == "netdiag 0.2.0"
