"""Logging de la aplicación (bloque logging de la config).

Se llama `logs` y no `logging` para no sombrear el módulo estándar.

Dos destinos (plan de layout, dominio B):

- Log GLOBAL: activo desde la primera línea de main.py, ANTES de leer la
  config y de abrir cualquier proyecto. Vive en userdata/logs/app.log y
  es rotativo. Cubre el hueco temporal en el que el vault del proyecto
  aún no existe.
- Log DEL PROYECTO: un segundo handler que se añade al abrir el vault
  (archive/logs/app.log). El global NUNCA se quita.

Todo el sistema loguea bajo el logger raíz "second_brain".
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_LOGGER_NAME = "second_brain"

# Marcas para no duplicar handlers si el arranque se re-ejecuta (p. ej.
# la CLI reabre un proyecto sin reiniciar el proceso).
_ROLE_ATTR = "_second_brain_role"
_ROLE_GLOBAL = "global"
_ROLE_PROJECT = "project"

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def get_logger(name: str | None = None) -> logging.Logger:
    """Logger del espacio de nombres de la aplicación."""
    if name is None:
        return logging.getLogger(APP_LOGGER_NAME)
    return logging.getLogger(f"{APP_LOGGER_NAME}.{name}")


def _remove_role(logger: logging.Logger, role: str) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _ROLE_ATTR, None) == role:
            logger.removeHandler(handler)
            handler.close()


def _make_file_handler(
    file: Path,
    level: int,
    max_bytes: int,
    backup_count: int,
    role: str,
) -> RotatingFileHandler:
    file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    setattr(handler, _ROLE_ATTR, role)
    return handler


def setup_global_logging(
    *,
    level: str = "info",
    file: Path,
    max_bytes: int = 5_242_880,
    backup_count: int = 5,
) -> logging.Logger:
    """Configura el log global rotativo. Idempotente.

    Debe llamarse al principio de main.py, antes de cargar la config
    (por eso acepta valores por defecto y no un objeto de configuración).
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _remove_role(logger, _ROLE_GLOBAL)
    logger.addHandler(
        _make_file_handler(file, logger.level, max_bytes, backup_count, _ROLE_GLOBAL)
    )
    logger.propagate = False
    return logger


def add_project_log_handler(
    *,
    file: Path,
    max_bytes: int = 5_242_880,
    backup_count: int = 5,
) -> logging.Handler:
    """Añade el handler del proyecto al abrir su vault. El global se queda."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    _remove_role(logger, _ROLE_PROJECT)
    handler = _make_file_handler(
        file, logger.level, max_bytes, backup_count, _ROLE_PROJECT
    )
    logger.addHandler(handler)
    return handler


def remove_project_log_handler() -> None:
    """Retira el handler del proyecto al cerrarlo."""
    _remove_role(logging.getLogger(APP_LOGGER_NAME), _ROLE_PROJECT)
