from datetime import datetime

import pytest

from netdiag.settings import (
    MAX_SAFE_PATH,
    default_measurements_dir,
    measurement_dir,
    safe_name,
    save_measurements_dir,
)


def test_default_is_in_documents(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert default_measurements_dir() == tmp_path / "Documents" / "NetDiag" / "Mediciones"


def test_configured_directory_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    selected = tmp_path / "Mis reportes"
    assert save_measurements_dir(selected) == selected.resolve()
    assert default_measurements_dir() == selected.resolve()


def test_readable_folder_name_and_collision(tmp_path):
    now = datetime(2026, 11, 19, 15, 42, 8)
    first = measurement_dir(tmp_path, "Test League LAN", now)
    first.mkdir()
    second = measurement_dir(tmp_path, "Test League LAN", now)
    assert first.name == "2026-11-19_15-42-08_Test-League-LAN"
    assert second.name.endswith("_2")


def test_long_measurement_name_is_shortened_safely(tmp_path):
    result = measurement_dir(tmp_path, "x" * 500)
    assert len(str(result / "active-session.txt")) <= MAX_SAFE_PATH
    assert len(result.name) < 500


def test_overlong_root_fails_before_writing(tmp_path):
    root = tmp_path / ("x" * 210)
    with pytest.raises(ValueError, match="demasiado larga"):
        measurement_dir(root, "test")


def test_safe_name_removes_windows_hostile_characters():
    assert safe_name('  test: League / "LAN"  ') == "test-League-LAN"
