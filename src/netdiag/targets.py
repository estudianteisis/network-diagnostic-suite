from __future__ import annotations

import ipaddress
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CustomTarget:
    address: str
    title: str


def validate_address(value: str) -> str:
    value = value.strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError("El destino debe ser una IP o hostname sin espacios.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        labels = value.rstrip(".").split(".")
        if any(not label or len(label) > 63 for label in labels):
            raise ValueError("El hostname no es valido.") from None
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
        invalid = any(
            set(label) - allowed or label.startswith("-") or label.endswith("-") for label in labels
        )
        if invalid:
            raise ValueError("El hostname no es valido.") from None
    return value


def targets_path(sessions_dir: Path) -> Path:
    return sessions_dir / "saved-targets.json"


def load_targets(sessions_dir: Path) -> list[CustomTarget]:
    path = targets_path(sessions_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [CustomTarget(validate_address(item["address"]), str(item["title"])) for item in data]


def save_targets(sessions_dir: Path, targets: list[CustomTarget]) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = targets_path(sessions_dir)
    path.write_text(
        json.dumps([asdict(target) for target in targets], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def add_target(
    sessions_dir: Path, address: str, title: str | None = None
) -> tuple[CustomTarget, Path]:
    address = validate_address(address)
    targets = load_targets(sessions_dir)
    existing = next((item for item in targets if item.address == address), None)
    if existing:
        targets.remove(existing)
        default_title = existing.title
    else:
        default_title = f"Destino {len(targets) + 1}"
    target = CustomTarget(address, title.strip() if title and title.strip() else default_title)
    targets.append(target)
    return target, save_targets(sessions_dir, targets)


def clear_targets(sessions_dir: Path) -> int:
    targets = load_targets(sessions_dir)
    path = targets_path(sessions_dir)
    if path.exists():
        path.unlink()
    return len(targets)
