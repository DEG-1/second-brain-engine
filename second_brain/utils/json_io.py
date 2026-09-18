"""Escritura atómica y lectura tolerante de archivos del vault (spec sección 20).

Toda escritura de JSON/Markdown del vault pasa por aquí: se escribe a
<nombre>.tmp en el MISMO directorio, se hace flush + os.fsync y se
renombra con os.replace(), que es atómico en NTFS local. Si el proceso
muere a mitad de una regeneración, el archivo destino nunca queda
truncado: el reemplazo ocurre completo o no ocurre.

La lectura usa utf-8-sig: si el usuario edita un archivo con Notepad,
Windows escribe BOM y un json.loads ingenuo falla con un error críptico
en el primer carácter.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str) -> None:
    """Escribe texto de forma atómica (tmp + fsync + os.replace).

    El nombre temporal incluye el PID (auditoría A3): dos procesos
    escribiendo el mismo destino no deben compartir el mismo .tmp — en
    Windows, os.replace falla con PermissionError si otro proceso tiene
    el temporal abierto.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json_atomic(path: Path, data: Any, *, indent: int = 2) -> None:
    """Serializa a JSON legible (UTF-8 real, sin escapes ASCII) y escribe atómico."""
    text = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)
    write_text_atomic(path, text + "\n")


def read_text(path: Path) -> str:
    """Lee texto tolerando el BOM que deja Notepad en Windows."""
    return path.read_text(encoding="utf-8-sig")


def read_json(path: Path) -> Any:
    """Lee y parsea un JSON del vault (tolerante a BOM)."""
    return json.loads(read_text(path))
