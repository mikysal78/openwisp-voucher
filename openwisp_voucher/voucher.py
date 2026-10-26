"""Dati di un accesso e funzioni senza interfaccia (testabili)."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# niente caratteri che si confondono sulla carta (0/O, 1/l/I)
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
USERNAME_RE = re.compile(r"^[\w.@+-]+$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9@.+_-]{1,20}$")


@dataclass
class Voucher:
    username: str
    password: str
    expiration: date  # ultimo giorno valido
    guest: str = ""
    notes: str = ""


def generate_password(length: int = 8) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def expiration_for_days(days: int, today: date | None = None) -> date:
    """N giorni a partire da oggi compreso.

    OpenWISP disattiva alle 00:01 gli utenti con scadenza < oggi, quindi la
    data di scadenza è l'ultimo giorno in cui l'accesso funziona.
    """
    if days < 1:
        raise ValueError("almeno un giorno")
    return (today or date.today()) + timedelta(days=days - 1)


def days_for_expiration(expiration: date, today: date | None = None) -> int:
    return (expiration - (today or date.today())).days + 1


def batch_name(kind: str, now: datetime | None = None) -> str:
    """Nome unico per l'organizzazione (vincolo di openwisp-radius)."""
    now = now or datetime.now()
    return f"voucher-{kind}-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def valid_username(username: str) -> bool:
    return bool(username) and len(username) <= 150 and bool(USERNAME_RE.match(username))


def valid_prefix(prefix: str) -> bool:
    return bool(PREFIX_RE.match(prefix))


def _wifi_escape(value: str) -> str:
    return re.sub(r'([\\;,:"])', r"\\\1", value)


def wifi_qr_payload(ssid: str, password: str = "") -> str:
    """Formato riconosciuto dalle fotocamere di Android e iOS."""
    if password:
        return f"WIFI:T:WPA;S:{_wifi_escape(ssid)};P:{_wifi_escape(password)};;"
    return f"WIFI:T:nopass;S:{_wifi_escape(ssid)};;"


def share_text(voucher: Voucher, ssid: str, website: str = "", lang=None) -> str:
    from .i18n import tr

    t = lang or tr
    lines = []
    if ssid:
        lines.append(t("Rete Wi-Fi: {ssid}").format(ssid=ssid))
    lines += [
        t("Utente: {username}").format(username=voucher.username),
        t("Password: {password}").format(password=voucher.password),
        t("Valido fino al {date} compreso").format(
            date=voucher.expiration.strftime("%d/%m/%Y")
        ),
    ]
    if website:
        lines.append(website)
    return "\n".join(lines)
