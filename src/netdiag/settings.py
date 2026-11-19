from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_SAFE_PATH = 240
LONGEST_OUTPUT_NAME = "active-session.txt"


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
    return base / "NetDiag"


def settings_path() -> Path:
    return app_data_dir() / "config.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def documents_dir() -> Path:
    profile = Path(os.environ.get("USERPROFILE", Path.home()))
    return profile / "Documents"


def default_measurements_dir() -> Path:
    configured = load_settings().get("measurements_dir")
    return (
        Path(configured).expanduser() if configured else documents_dir() / "NetDiag" / "Mediciones"
    )


def validate_storage_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    reserved = 1 + len("2026-11-19_15-30-45_medicion") + 1 + len(LONGEST_OUTPUT_NAME)
    if len(str(resolved)) + reserved > MAX_SAFE_PATH:
        raise ValueError(
            f"La ruta base es demasiado larga ({len(str(resolved))} caracteres). "
            f"Elige una ruta mas corta; NetDiag limita sus rutas a {MAX_SAFE_PATH} caracteres."
        )
    return resolved


def save_measurements_dir(path: Path) -> Path:
    resolved = validate_storage_root(path)
    resolved.mkdir(parents=True, exist_ok=True)
    config = load_settings()
    config["measurements_dir"] = str(resolved)
    destination = settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return resolved


def safe_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized).strip("-_.")
    return normalized or "medicion"


def measurement_dir(root: Path, name: str, now: datetime | None = None) -> Path:
    root = validate_storage_root(root)
    stamp = (now or datetime.now().astimezone()).strftime("%Y-%m-%d_%H-%M-%S")
    slug = safe_name(name)
    max_folder = MAX_SAFE_PATH - len(str(root)) - 1 - len(LONGEST_OUTPUT_NAME) - 1
    prefix = f"{stamp}_"
    max_slug = max(8, max_folder - len(prefix))
    if len(slug) > max_slug:
        digest = hashlib.sha1(slug.encode(), usedforsecurity=False).hexdigest()[:8]
        slug = f"{slug[: max_slug - 9]}-{digest}"
    base = root / f"{prefix}{slug}"
    candidate = base
    counter = 2
    while candidate.exists():
        suffix = f"_{counter}"
        candidate = root / f"{base.name[: max_folder - len(suffix)]}{suffix}"
        counter += 1
    if len(str(candidate / LONGEST_OUTPUT_NAME)) > MAX_SAFE_PATH:
        raise ValueError("No se pudo producir una ruta segura. Usa una carpeta base mas corta.")
    return candidate
