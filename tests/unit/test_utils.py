"""Utilidades base: json_io, timestamps y paths (spec secciones 10, 20).

json_io (escritura atomica y lectura tolerante a BOM), timestamps (UTC Z,
zona local) y paths (slugify y normalize_project_path para Windows).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from second_brain.utils import json_io, paths, timestamps

# ---------------------------------------------------------------------------
# json_io (spec seccion 20)
# ---------------------------------------------------------------------------


def test_json_io_escritura_atomica_no_deja_tmp(tmp_path: Path) -> None:
    """write_json_atomic escribe el destino completo y no deja el .tmp."""
    destino = tmp_path / "sub" / "datos.json"
    json_io.write_json_atomic(destino, {"clave": "valor con tilde: acción"})
    assert destino.is_file()
    assert not destino.with_name(destino.name + ".tmp").exists()
    assert json_io.read_json(destino) == {"clave": "valor con tilde: acción"}


def test_json_io_lectura_con_bom(tmp_path: Path) -> None:
    """read_text/read_json toleran el BOM que deja Notepad en Windows (spec 20)."""
    destino = tmp_path / "con_bom.json"
    # Escribir con BOM explicito (utf-8-sig), como Notepad.
    destino.write_text('{"x": 1}', encoding="utf-8-sig")
    assert destino.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json_io.read_json(destino) == {"x": 1}
    assert not json_io.read_text(destino).startswith("﻿")


def test_json_io_texto_atomico_roundtrip(tmp_path: Path) -> None:
    """write_text_atomic + read_text conserva el contenido UTF-8 real."""
    destino = tmp_path / "nota.md"
    json_io.write_text_atomic(destino, "# Café\nSesión válida\n")
    assert json_io.read_text(destino) == "# Café\nSesión válida\n"


# ---------------------------------------------------------------------------
# timestamps (spec seccion 10)
# ---------------------------------------------------------------------------


def test_to_iso_z_rechaza_naive() -> None:
    """to_iso_z exige un datetime consciente de zona horaria (spec 10)."""
    with pytest.raises(ValueError):
        timestamps.to_iso_z(datetime(2026, 7, 18, 12, 0, 0))


def test_roundtrip_iso_z() -> None:
    """to_iso_z produce sufijo Z y parse_iso_z lo recupera en UTC (spec 10)."""
    momento = datetime(2026, 7, 18, 15, 30, 45, tzinfo=UTC)
    texto = timestamps.to_iso_z(momento)
    assert texto == "2026-07-18T15:30:45Z"
    vuelta = timestamps.parse_iso_z(texto)
    assert vuelta == momento
    assert vuelta.tzinfo is not None


def test_parse_iso_z_rechaza_sin_zona() -> None:
    """parse_iso_z rechaza un timestamp sin zona horaria (spec 10)."""
    with pytest.raises(ValueError):
        timestamps.parse_iso_z("2026-07-18T15:30:45")


def test_format_local_con_america_bogota() -> None:
    """format_local convierte a la zona configurada solo al mostrar (spec 10)."""
    # 2026-07-18 00:00:00Z equivale a 2026-07-17 19:00:00 en Bogota (UTC-5).
    momento = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)
    local = timestamps.format_local(momento, "America/Bogota")
    assert local == "2026-07-17 19:00:00"


# ---------------------------------------------------------------------------
# paths.slugify (spec seccion 21, utils)
# ---------------------------------------------------------------------------


def test_slugify_quita_tildes_y_normaliza() -> None:
    """slugify quita tildes, pasa a minusculas y colapsa a guiones."""
    assert paths.slugify("Implementación Rápida del Núcleo") == "implementacion-rapida-del-nucleo"


def test_slugify_esquiva_reservados_de_windows() -> None:
    """Los nombres reservados (CON, NUL...) se esquivan con sufijo -x."""
    assert paths.slugify("CON") == "con-x"
    assert paths.slugify("NUL") == "nul-x"
    assert paths.slugify("com1") == "com1-x"


def test_slugify_vacio_devuelve_sin_titulo() -> None:
    """Un texto vacio o sin caracteres validos produce 'sin-titulo'."""
    assert paths.slugify("") == "sin-titulo"
    assert paths.slugify("   ") == "sin-titulo"
    assert paths.slugify("---!!!___") == "sin-titulo"


def test_slugify_recorta_a_max_length() -> None:
    """slugify respeta max_length sin dejar un guion colgante al final."""
    resultado = paths.slugify("palabra " * 20, max_length=10)
    assert len(resultado) <= 10
    assert not resultado.endswith("-")


# ---------------------------------------------------------------------------
# paths.normalize_project_path (Windows case-insensitive)
# ---------------------------------------------------------------------------


def test_normalize_project_path_case_insensitive(tmp_path: Path) -> None:
    """Dos grafias de la misma ruta producen la MISMA clave (spec, registro)."""
    base = tmp_path / "Proyecto"
    base.mkdir()
    clave_alta = paths.normalize_project_path(str(base).upper())
    clave_baja = paths.normalize_project_path(str(base).lower())
    assert clave_alta == clave_baja


def test_normalize_project_path_resuelve_ruta(tmp_path: Path) -> None:
    """La clave es la ruta resuelta y case-normalizada, no la cruda."""
    base = tmp_path / "Repo"
    base.mkdir()
    con_dot = base / "." / "sub" / ".."
    (base / "sub").mkdir()
    assert paths.normalize_project_path(con_dot) == paths.normalize_project_path(base)
