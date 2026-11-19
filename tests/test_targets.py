import json

import pytest

from netdiag.targets import add_target, clear_targets, load_targets, validate_address


def test_adds_default_iterative_names_and_persists(tmp_path):
    first, _ = add_target(tmp_path, "1.2.3.4")
    second, _ = add_target(tmp_path, "example.com")
    assert first.title == "Destino 1"
    assert second.title == "Destino 2"
    assert load_targets(tmp_path) == [first, second]


def test_named_target_replaces_same_address(tmp_path):
    add_target(tmp_path, "1.2.3.4")
    updated, _ = add_target(tmp_path, "1.2.3.4", "League LAN")
    assert load_targets(tmp_path) == [updated]
    assert updated.title == "League LAN"


def test_clear_removes_saved_targets(tmp_path):
    add_target(tmp_path, "1.2.3.4")
    assert clear_targets(tmp_path) == 1
    assert load_targets(tmp_path) == []


@pytest.mark.parametrize("value", ["", "bad host", "-bad.example", "bad_.example"])
def test_rejects_invalid_target(value):
    with pytest.raises(ValueError):
        validate_address(value)


def test_saved_file_is_readable_json(tmp_path):
    _, path = add_target(tmp_path, "1.2.3.4", "Test")
    assert json.loads(path.read_text())[0]["title"] == "Test"
