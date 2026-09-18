"""Carga y validación de la configuración (spec sección 22).

Única puerta de entrada: ningún otro módulo lee YAML de configuración
directamente, y los subsistemas reciben VALORES por parámetro (nunca el
objeto de config entero salvo en el composition root).

Precedencia de fuentes:

    1. --config <ruta>                (explícita; error si no existe)
    2. $SECOND_BRAIN_HOME/config.yaml (implícita en user_config_path())
    3. userdata/config.yaml           (modo portátil)
    4. resources/config.default.yaml  (recurso empaquetado)

En el primer arranque, si no existe el config del usuario, se crea
copiando el default (escritura atómica), de modo que el usuario siempre
tiene un archivo real que editar.

La validación usa extra="forbid": una clave desconocida en el YAML es un
error con nombre, no una opción ignorada en silencio — el clásico "llevo
una hora cambiando un valor que la app no lee" queda imposible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from second_brain.exceptions import ConfigurationError
from second_brain.memory.models import Coordinator, Provider
from second_brain.utils import json_io, paths

_DEFAULT_RESOURCE = "config.default.yaml"


class _ConfigModel(BaseModel):
    """Base de los bloques: una clave desconocida es error, no ruido."""

    model_config = ConfigDict(extra="forbid")


class ApplicationConfig(_ConfigModel):
    name: str = "Second Brain"
    timezone: str = "America/Bogota"
    max_parallel_workers: int = Field(default=3, gt=0)
    discussion_messages_per_coordinator: int = Field(default=3, gt=0)
    # Turnos de proceso por coordinador en EXECUTING/CORRECTING (spec 7.5).
    # El bucle se corta antes si el coordinador se bloquea o un turno no
    # avanza nada (orquestador, Fase 5).
    execution_turns_per_coordinator: int = Field(default=3, gt=0)
    # Comando de pruebas que el orquestador re-ejecuta tras rebasar la
    # segunda rama en la integracion secuencial (spec 18, paso 4). Lista
    # vacia = sin comando configurado: el re-test se SALTA con un evento
    # warning explicito (nunca se adivina un comando).
    test_command: list[str] = Field(default_factory=list)
    # "fake" = adaptadores simulados (sin cuota, spec 30); "real" = las
    # CLIs de verdad (Fase 2+). El modo real consume cuota del usuario:
    # por eso el default es fake y el cambio es una decision explicita
    # (config o flag --real). La demo fuerza fake siempre.
    adapter_mode: Literal["fake", "real"] = "fake"


class CoordinatorConfig(_ConfigModel):
    provider: Provider
    command: str
    model: str | None = None
    minimum_version: str | None = None
    enabled: bool = True


class WorkersConfig(_ConfigModel):
    models: dict[Provider, str | None] = Field(default_factory=dict)
    per_type: dict[str, str] = Field(default_factory=dict)


class MemoryConfig(_ConfigModel):
    max_initial_summaries: int = Field(default=3, gt=0)
    max_initial_files: int = Field(default=8, gt=0)
    max_conversation_fragments: int = Field(default=3, gt=0)
    enable_embeddings: bool = False


class BudgetsConfig(_ConfigModel):
    planning_tokens: int = Field(default=120_000, gt=0)
    execution_tokens: int = Field(default=100_000, gt=0)
    review_tokens: int = Field(default=30_000, gt=0)
    closing_tokens: int = Field(default=8_000, gt=0)
    worker_default_tokens: int = Field(default=8_000, gt=0)
    compaction_reserve_tokens: int = Field(default=3_000, gt=0)


class RetentionConfig(_ConfigModel):
    checkpoints_keep: int = Field(default=50, gt=0)
    events_keep_days: int = Field(default=90, gt=0)
    logs_keep_days: int = Field(default=30, gt=0)
    outputs_keep_days: int = Field(default=90, gt=0)
    conversations: Literal["never_delete"] = "never_delete"


class GitConfig(_ConfigModel):
    use_worktrees: bool = True
    auto_commit: bool = False
    auto_merge: bool = False
    auto_push: bool = False


class SecurityConfig(_ConfigModel):
    allow_network: bool = False
    allow_dependency_install: bool = False
    allow_database_migrations: bool = False
    protected_paths: list[str] = Field(default_factory=list)
    extra_blocked_commands_file: str | None = None


class RetrievalConfig(_ConfigModel):
    extra_glossary_files: list[str] = Field(default_factory=list)


class PathsConfig(_ConfigModel):
    vault_dir: str = ".agent_vault"
    worktrees_dir: str = ".agent_worktrees"
    user_data_dir: str | None = None
    user_state_dir: str | None = None
    projects_registry: str | None = None
    prompts_override_dir: str | None = None


class ProjectsConfig(_ConfigModel):
    recent_limit: int = Field(default=20, gt=0)
    auto_register_on_open: bool = True
    prune_missing: bool = False


class CliCacheConfig(_ConfigModel):
    ttl_hours: int = Field(default=24, gt=0)
    revalidate_on_binary_change: bool = True


class LoggingConfig(_ConfigModel):
    level: Literal["debug", "info", "warning", "error"] = "info"
    file: str = ".agent_vault/archive/logs/app.log"
    global_file: str | None = None
    max_bytes: int = Field(default=5_242_880, gt=0)
    backup_count: int = Field(default=5, ge=0)


class UiConfig(_ConfigModel):
    refresh_rate_ms: int = Field(default=250, gt=0)
    show_raw_logs_by_default: bool = False
    theme: str = "dark"


class AppConfig(_ConfigModel):
    """Configuración completa y validada (los 14 bloques de la sección 22)."""

    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    coordinators: dict[Coordinator, CoordinatorConfig]
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    budgets: BudgetsConfig = Field(default_factory=BudgetsConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    cli_cache: CliCacheConfig = Field(default_factory=CliCacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ui: UiConfig = Field(default_factory=UiConfig)

    @model_validator(mode="after")
    def _both_coordinators_declared(self) -> AppConfig:
        """FABLE y SOL deben existir en la config aunque estén deshabilitados.

        El modo de un solo coordinador se expresa con enabled: false, no
        borrando el bloque (spec sección 16).
        """
        missing = [c.value for c in Coordinator if c not in self.coordinators]
        if missing:
            msg = f"faltan coordinadores en la configuración: {', '.join(missing)}"
            raise ValueError(msg)
        return self

    # -- Rutas resueltas (null en YAML = default de plataforma) ------------

    def resolved_user_data_dir(self) -> Path:
        if self.paths.user_data_dir:
            return Path(self.paths.user_data_dir)
        return paths.user_data_dir()

    def resolved_user_state_dir(self) -> Path:
        if self.paths.user_state_dir:
            return Path(self.paths.user_state_dir)
        return paths.user_state_dir()

    def resolved_projects_registry(self) -> Path:
        if self.paths.projects_registry:
            return Path(self.paths.projects_registry)
        return self.resolved_user_state_dir() / "projects.json"

    def resolved_prompts_override_dir(self) -> Path:
        if self.paths.prompts_override_dir:
            return Path(self.paths.prompts_override_dir)
        return self.resolved_user_data_dir() / "prompts"

    def resolved_global_log_file(self) -> Path:
        if self.logging.global_file:
            return Path(self.logging.global_file)
        return self.resolved_user_state_dir() / "logs" / "app.log"


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------


def default_config_text() -> str:
    """Texto del default empaquetado (resources/config.default.yaml)."""
    return paths.resource_text(_DEFAULT_RESOURCE)


def _parse_yaml(text: str, source: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"YAML inválido en {source}: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(data, dict):
        msg = f"la configuración de {source} debe ser un mapeo, no {type(data).__name__}"
        raise ConfigurationError(msg)
    return data


def _validate(data: dict[str, Any], source: str) -> AppConfig:
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        msg = f"configuración inválida en {source}:\n{exc}"
        raise ConfigurationError(msg) from exc


def ensure_user_config() -> Path:
    """Garantiza que exista el config.yaml del usuario; lo crea del default.

    La escritura es atómica: si el proceso muere a mitad del primer
    arranque, no queda un YAML truncado que rompa el segundo.
    """
    target = paths.user_config_path()
    if not target.exists():
        json_io.write_text_atomic(target, default_config_text())
    return target


def load_config(
    explicit_path: str | Path | None = None,
    *,
    create_user_config: bool = True,
) -> AppConfig:
    """Carga y valida la configuración según la cadena de precedencia."""
    if explicit_path is not None:
        source = Path(explicit_path)
        if not source.is_file():
            msg = f"no existe el archivo de configuración: {source}"
            raise ConfigurationError(msg)
        return _validate(_parse_yaml(json_io.read_text(source), str(source)), str(source))

    user_file = ensure_user_config() if create_user_config else paths.user_config_path()
    if user_file.is_file():
        return _validate(
            _parse_yaml(json_io.read_text(user_file), str(user_file)), str(user_file)
        )

    return _validate(
        _parse_yaml(default_config_text(), _DEFAULT_RESOURCE), _DEFAULT_RESOURCE
    )
