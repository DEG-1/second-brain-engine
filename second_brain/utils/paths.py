"""Resolución de TODAS las rutas del sistema. Base de la pirámide.

Única frontera entre el código y el sistema de archivos. Contratos:

1. Acceso a recursos empaquetados SOLO por resource_text()/resource_bytes(),
   implementados con importlib.resources: funcionan igual en desarrollo,
   en wheel y dentro del bundle de PyInstaller. PROHIBIDO en el resto del
   código: Path(__file__) hacia resources/ y sys._MEIPASS (que solo puede
   aparecer en este archivo).

2. Datos de usuario en modo portátil: <raíz de la app>/userdata. La
   variable de entorno SECOND_BRAIN_HOME, si existe, los reubica todos
   (sirve para USB, para Program Files no escribible, y para que la suite
   de tests jamás toque los datos reales: conftest.py la fija a un
   temporal).

3. Windows es case-insensitive: la identidad de un proyecto es
   normalize_project_path(), nunca la ruta cruda. Sin esto se crean dos
   vaults sobre el mismo repo y la memoria se parte en dos.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from importlib import resources
from pathlib import Path

_RESOURCES_PACKAGE = "second_brain.resources"

# Nombres que Windows reserva a dispositivos: un archivo llamado CON.md
# ni siquiera puede crearse. Aplica a nombres derivados de texto del
# usuario (títulos de resúmenes, temas).
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


# ---------------------------------------------------------------------------
# Recursos empaquetados
# ---------------------------------------------------------------------------


def resource_text(relative: str) -> str:
    """Lee un recurso empaquetado como texto UTF-8.

    `relative` es la ruta dentro de second_brain/resources/, con barras
    normales: "prompts/discussion.md", "config.default.yaml".
    """
    return resources.files(_RESOURCES_PACKAGE).joinpath(relative).read_text(encoding="utf-8")


def resource_bytes(relative: str) -> bytes:
    """Lee un recurso empaquetado como bytes."""
    return resources.files(_RESOURCES_PACKAGE).joinpath(relative).read_bytes()


def resource_exists(relative: str) -> bool:
    """Comprueba si un recurso empaquetado existe."""
    return resources.files(_RESOURCES_PACKAGE).joinpath(relative).is_file()


# ---------------------------------------------------------------------------
# Raíz de la aplicación y datos de usuario (modo portátil)
# ---------------------------------------------------------------------------


def app_root() -> Path:
    """Raíz de la instalación.

    En desarrollo: el directorio del repo (el que contiene main.py).
    Congelado con PyInstaller (--onedir): el directorio del ejecutable.
    Este es el ÚNICO lugar del sistema donde se consulta sys.frozen.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def second_brain_home() -> Path | None:
    """Valor de SECOND_BRAIN_HOME, si está definida."""
    raw = os.environ.get("SECOND_BRAIN_HOME")
    return Path(raw).resolve() if raw else None


def user_data_dir() -> Path:
    """Datos que el usuario escribe: config, overrides de prompts y datos."""
    home = second_brain_home()
    return home if home is not None else app_root() / "userdata"


def user_state_dir() -> Path:
    """Estado de esta máquina: registro de proyectos, logs, caché.

    En modo portátil coincide con user_data_dir(); se mantienen como
    funciones separadas para poder dividirlos (p. ej. %APPDATA% vs
    %LOCALAPPDATA%) sin tocar a los llamadores.
    """
    return user_data_dir()


def user_config_path() -> Path:
    """El config.yaml real del usuario."""
    return user_data_dir() / "config.yaml"


def projects_registry_path() -> Path:
    """Índice derivable de proyectos conocidos (projects.json)."""
    return user_state_dir() / "projects.json"


def prompts_override_dir() -> Path:
    """Overrides de prompts del usuario; ganan sobre resources/prompts/."""
    return user_data_dir() / "prompts"


def user_data_files_dir() -> Path:
    """Glosario y bloqueos adicionales del usuario (fusión aditiva)."""
    return user_data_dir() / "data"


def global_logs_dir() -> Path:
    """Logs de la aplicación previos a abrir un proyecto."""
    return user_state_dir() / "logs"


def cache_dir() -> Path:
    """Caché local: versiones de CLIs, sonda del sandbox de Codex."""
    return user_state_dir() / "cache"


# ---------------------------------------------------------------------------
# Identidad y saneamiento de rutas (Windows)
# ---------------------------------------------------------------------------


def normalize_project_path(path: str | Path) -> str:
    """Clave de identidad de un proyecto: ruta resuelta y case-normalizada.

    "D:\\Proyectos\\APRIA" y "d:\\proyectos\\apria" deben producir la MISMA
    clave; es lo que deduplica el registro de proyectos (spec, registro).
    """
    return os.path.normcase(str(Path(path).resolve()))


def same_path(a: str | Path, b: str | Path) -> bool:
    """True si ambas rutas apuntan al mismo directorio (resueltas y sin caso).

    Comparacion por la misma clave que ``normalize_project_path``: en
    Windows "D:\\Repo" y "d:\\repo" son el mismo sitio.
    """
    return normalize_project_path(a) == normalize_project_path(b)


def slugify(text: str, max_length: int = 40) -> str:
    """Convierte texto libre del usuario en un nombre de archivo seguro.

    Quita tildes, pasa a minúsculas, colapsa lo no alfanumérico a guiones,
    recorta, y esquiva los nombres reservados de Windows (CON, NUL...).
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:max_length].rstrip("-")
    if not slug:
        return "sin-titulo"
    if slug in _WINDOWS_RESERVED:
        return f"{slug}-x"
    return slug
