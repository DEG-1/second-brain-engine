"""Manejo de tiempo del sistema (spec sección 10).

Regla única: se GUARDA en UTC ISO-8601 con sufijo Z; se convierte a la
zona horaria configurada (application.timezone) SOLO al mostrar. Ningún
otro módulo hace aritmética de zonas horarias por su cuenta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    """Instante actual, siempre consciente de zona horaria (UTC)."""
    return datetime.now(UTC)


def to_iso_z(moment: datetime) -> str:
    """Serializa a ISO-8601 con sufijo Z, el formato de todo el vault.

    Rechaza datetimes naive: aceptar uno produciría desfases silenciosos
    que solo se descubren al comparar eventos de sesiones distintas.
    """
    if moment.tzinfo is None:
        msg = "se requiere un datetime consciente de zona horaria"
        raise ValueError(msg)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso_z(text: str) -> datetime:
    """Parsea ISO-8601 (acepta sufijo Z) y devuelve un datetime en UTC."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        msg = f"timestamp sin zona horaria: {text!r}"
        raise ValueError(msg)
    return moment.astimezone(UTC)


def to_local(moment: datetime, timezone_name: str) -> datetime:
    """Convierte a la zona configurada. SOLO para mostrar, nunca para guardar."""
    if moment.tzinfo is None:
        msg = "se requiere un datetime consciente de zona horaria"
        raise ValueError(msg)
    return moment.astimezone(ZoneInfo(timezone_name))


def format_local(
    moment: datetime,
    timezone_name: str,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """Representación local legible para la interfaz."""
    return to_local(moment, timezone_name).strftime(fmt)
