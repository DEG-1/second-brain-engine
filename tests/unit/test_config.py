"""Carga y validacion de la configuracion (spec seccion 22).

Cada test aisla su propio SECOND_BRAIN_HOME con monkeypatch para no tocar
el HOME compartido de la suite ni el userdata real del usuario.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from second_brain.config import (
    AppConfig,
    default_config_text,
    ensure_user_config,
    load_config,
)
from second_brain.exceptions import ConfigurationError
from second_brain.utils import paths


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Un SECOND_BRAIN_HOME fresco y vacio para el test."""
    destino = tmp_path / "home"
    destino.mkdir()
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(destino))
    return destino


def _mutated_default(**overrides: object) -> dict:
    data = yaml.safe_load(default_config_text())
    data.update(overrides)
    return data


def test_carga_del_default_empaquetado() -> None:
    """El default empaquetado carga y valida los 14 bloques (spec 22)."""
    data = yaml.safe_load(default_config_text())
    from second_brain.memory.models import Coordinator

    config = AppConfig.model_validate(data)
    assert config.application.name == "Second Brain"
    assert config.application.timezone == "America/Bogota"
    assert set(config.coordinators) == {Coordinator.FABLE, Coordinator.SOL}


def test_crea_config_de_usuario_en_primer_arranque(home: Path) -> None:
    """Si no existe el config del usuario, se crea copiando el default (spec 22)."""
    target = paths.user_config_path()
    assert not target.exists()
    creado = ensure_user_config()
    assert creado == target
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == default_config_text()


def test_precedencia_explicito_sobre_second_brain_home(
    home: Path, tmp_path: Path
) -> None:
    """--config explicito gana sobre $SECOND_BRAIN_HOME/config.yaml (spec 22)."""
    # Config del HOME: nombre HOME.
    home_data = _mutated_default(application={"name": "HOME"})
    (home / "config.yaml").write_text(
        yaml.safe_dump(home_data), encoding="utf-8"
    )
    # Config explicito: nombre EXPLICITO.
    explicit = tmp_path / "explicito.yaml"
    explicit.write_text(
        yaml.safe_dump(_mutated_default(application={"name": "EXPLICITO"})),
        encoding="utf-8",
    )

    assert load_config().application.name == "HOME"
    assert load_config(explicit).application.name == "EXPLICITO"


def test_config_explicito_inexistente_es_error(tmp_path: Path) -> None:
    """Una ruta --config que no existe es un error explicito (spec 22)."""
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "no_existe.yaml")


def test_clave_desconocida_es_configuration_error(tmp_path: Path) -> None:
    """Una clave desconocida en el YAML es error con nombre, no ruido (spec 22)."""
    data = _mutated_default(bloque_inventado={"x": 1})
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(ruta)


def test_falta_un_coordinador_es_error(tmp_path: Path) -> None:
    """FABLE y SOL deben existir aunque esten deshabilitados (spec 16, 22)."""
    data = yaml.safe_load(default_config_text())
    del data["coordinators"]["sol"]
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(ruta)


def test_yaml_invalido_es_configuration_error(tmp_path: Path) -> None:
    """Un YAML sintacticamente roto falla ruidosamente (spec 22)."""
    ruta = tmp_path / "config.yaml"
    ruta.write_text("application: [sin cerrar", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(ruta)
