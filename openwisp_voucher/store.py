"""Impostazioni, storico degli accessi creati e token.

Tutto sta nella cartella di configurazione dell'utente:
- Linux: $XDG_CONFIG_HOME/openwisp-voucher (di solito ~/.config/openwisp-voucher)
- Windows: %APPDATA%\\openwisp-voucher

Il token va nel portachiavi del sistema (keyring); solo se manca finisce in un
file leggibile dal solo utente.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP = "openwisp-voucher"

# formati di stampa
FORMAT_A4 = "a4"
FORMAT_58 = "thermal58"
FORMAT_80 = "thermal80"
FORMAT_LABEL = "label"
FORMATS = (FORMAT_A4, FORMAT_58, FORMAT_80, FORMAT_LABEL)

# contenuto del QR code
QR_WIFI = "wifi"
QR_URL = "url"
QR_NONE = "none"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_private(path: Path, text: str) -> None:
    """Scrive il file con permessi 600 (su Windows vale la cartella utente)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass
class Settings:
    # server
    server: str = ""
    username: str = ""
    organization_id: str = ""
    organization_slug: str = ""
    organization_name: str = ""
    radius_group: str = ""
    # struttura (stampati sul biglietto)
    venue_name: str = ""
    logo_file: str = ""  # nome del file nella cartella di configurazione
    website: str = ""
    email: str = ""
    phone: str = ""
    ssid: str = ""
    wifi_password: str = ""  # solo per il QR, se la rete è protetta
    footer_note: str = ""
    # stampa
    print_format: str = FORMAT_A4
    label_width_mm: float = 62.0
    label_height_mm: float = 100.0
    qr: str = QR_WIFI
    qr_url: str = ""
    printer_name: str = ""  # ultima stampante usata
    # valori predefiniti
    default_days: int = 1
    series_prefix: str = "ospite"
    password_length: int = 8
    language: str = ""  # "" = lingua del sistema

    @property
    def logo_path(self) -> Path | None:
        if not self.logo_file:
            return None
        path = config_dir() / self.logo_file
        return path if path.exists() else None


SETTINGS_FILE = "settings.json"


def load_settings() -> Settings:
    path = config_dir() / SETTINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def save_settings(settings: Settings) -> None:
    _write_private(
        config_dir() / SETTINGS_FILE,
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
    )


def import_logo(source: str | Path) -> str:
    """Copia il logo nella configurazione: il file originale può sparire."""
    source = Path(source)
    suffix = source.suffix.lower() or ".png"
    name = "logo" + suffix
    for old in config_dir().glob("logo.*"):
        old.unlink()
    shutil.copyfile(source, config_dir() / name)
    return name


def remove_logo() -> None:
    for old in config_dir().glob("logo.*"):
        old.unlink()


# --- storico ---

HISTORY_FILE = "accessi.json"


@dataclass
class HistoryEntry:
    username: str
    password: str
    expiration: str  # ISO, ultimo giorno valido
    created: str  # ISO datetime
    organization_slug: str
    user_id: str | None = None
    guest: str = ""  # nome dell'ospite
    notes: str = ""  # es. camera
    batch: str = ""
    active: bool | None = None  # ultimo stato letto dal server
    extra: dict = field(default_factory=dict)


def load_history() -> list[HistoryEntry]:
    path = config_dir() / HISTORY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    known = {f.name for f in fields(HistoryEntry)}
    return [HistoryEntry(**{k: v for k, v in e.items() if k in known}) for e in data]


def save_history(entries: list[HistoryEntry]) -> None:
    _write_private(
        config_dir() / HISTORY_FILE,
        json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False),
    )


# --- token ---

TOKEN_FILE = "token"


def _key(server: str, username: str) -> str:
    return f"{server}|{username}"


def save_token(server: str, username: str, token: str) -> bool:
    """True se è finito nel portachiavi, False se nel file di riserva."""
    try:
        import keyring

        keyring.set_password(APP, _key(server, username), token)
        (config_dir() / TOKEN_FILE).unlink(missing_ok=True)
        return True
    except Exception:
        _write_private(config_dir() / TOKEN_FILE, token)
        return False


def load_token(server: str, username: str) -> str | None:
    try:
        import keyring

        token = keyring.get_password(APP, _key(server, username))
        if token:
            return token
    except Exception:
        pass
    try:
        return (config_dir() / TOKEN_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def delete_token(server: str, username: str) -> None:
    try:
        import keyring

        keyring.delete_password(APP, _key(server, username))
    except Exception:
        pass
    (config_dir() / TOKEN_FILE).unlink(missing_ok=True)
