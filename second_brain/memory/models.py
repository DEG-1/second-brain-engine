"""TODOS los modelos Pydantic y enums del sistema (spec seccion 10).

Este modulo es la BASE de la piramide de dependencias: lo importan core,
agents, vcs, processes y security. El no importa a nadie del sistema.
agents/contracts.py se limita a re-exportar WorkerTaskContract y
WorkerResult desde aqui (regla anti-ciclo, spec seccion 21).

REGLAS QUE ESTE MODULO HACE CUMPLIR
-----------------------------------
1. Todo campo de estado es un Enum CERRADO, nunca cadena libre (spec 10).
2. Los timestamps se guardan en UTC ISO-8601 con sufijo Z. La conversion
   a la zona horaria configurada ocurre SOLO al mostrar (spec 10).
3. Los IDs son secuencia por proyecto: el alias humano (TASK-001) es
   unico dentro del proyecto; la clave real es project_id + alias.
4. extra="forbid" en todos los modelos. Es deliberado: cuando un
   coordinador devuelve un JSON con campos inventados, la validacion
   debe FALLAR y disparar el reintento unico de la seccion 23.1, en vez
   de aceptar datos silenciosamente.
5. Los estados de la seccion 6 se serializan en minusculas; la forma en
   mayusculas del documento es solo notacion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)

# ---------------------------------------------------------------------------
# Tiempo
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Instante actual en UTC, siempre consciente de zona horaria."""
    return datetime.now(UTC)


def _to_utc_z(value: datetime) -> str:
    """Serializa a ISO-8601 con sufijo Z (spec seccion 10)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    PlainSerializer(_to_utc_z, return_type=str, when_used="json"),
]

# ---------------------------------------------------------------------------
# Identificadores
# ---------------------------------------------------------------------------

# Alias humano: PREFIJO-NNN (TASK-001, DEC-014, PLAN-002...). La unicidad
# real es project_id + alias; la garantiza SQLite, no el modelo.
Alias = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3,4}-\d{3,}$")]

# Actor de un evento (spec seccion 24).
Actor = Annotated[
    str,
    StringConstraints(pattern=r"^(fable|sol|orchestrator|user|worker:[A-Za-z0-9\-]+)$"),
]

# Identificador de trabajador: F-H01, S-W01. Se mantiene CORTO a proposito:
# forma parte de la ruta del worktree y Windows tiene el limite MAX_PATH de
# 260 caracteres, que Git alcanza antes que Python (spec 16.1, utils/paths).
WorkerId = Annotated[str, StringConstraints(pattern=r"^[FS]-[A-Z]\d{2,}$")]

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Progress = Annotated[float, Field(ge=0.0, le=1.0)]

# ---------------------------------------------------------------------------
# Enums de estado
# ---------------------------------------------------------------------------


class GlobalState(StrEnum):
    """Estados globales de la maquina (spec seccion 6)."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    INSPECTING = "inspecting"
    DISCUSSING = "discussing"
    PLANNING = "planning"
    WAITING_PLAN_APPROVAL = "waiting_plan_approval"
    EXECUTING = "executing"
    CROSS_REVIEW = "cross_review"
    CORRECTING = "correcting"
    READY_TO_MERGE = "ready_to_merge"
    MERGING = "merging"
    SUMMARIZING = "summarizing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentState(StrEnum):
    """Estados de un coordinador o trabajador (spec seccion 6).

    BLOCKED significa "turno cerrado, sesion guardada, esperando
    resolucion": NO hay proceso vivo esperando (spec seccion 10).
    """

    OFFLINE = "offline"
    READY = "ready"
    THINKING = "thinking"
    READING = "reading"
    WAITING = "waiting"
    RUNNING_TOOL = "running_tool"
    WRITING = "writing"
    TESTING = "testing"
    BLOCKED = "blocked"
    REQUESTING_CONTEXT = "requesting_context"
    REQUESTING_APPROVAL = "requesting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    """Fases de trabajo; gobiernan el archivado de conversaciones (spec 13)."""

    INSPECTION = "inspection"
    DISCUSSION = "discussion"
    PLANNING = "planning"
    EXECUTION = "execution"
    CROSS_REVIEW = "cross_review"
    CORRECTION = "correction"
    INTEGRATION = "integration"
    CLOSING = "closing"


class ObjectiveStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ContextRequestStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"


class WorkerStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Enums de dominio
# ---------------------------------------------------------------------------


class Coordinator(StrEnum):
    """Alias configurables; no dependen de un modelo concreto (spec 1)."""

    FABLE = "fable"
    SOL = "sol"


class Provider(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class PermissionMode(StrEnum):
    """Modos de permiso (spec seccion 19).

    El adaptador los traduce a flags de cada CLI. approved_commands NO es
    expresable en `codex exec`: ese adaptador debe declararlo en supports()
    y fallar, nunca degradar en silencio.
    """

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    APPROVED_COMMANDS = "approved_commands"
    UNRESTRICTED = "unrestricted"


class WorkerType(StrEnum):
    """Tipos iniciales de trabajador (spec seccion 15)."""

    REPOSITORY_EXPLORER = "repository_explorer"
    CODE_IMPLEMENTER = "code_implementer"
    TEST_RUNNER = "test_runner"
    SECURITY_REVIEWER = "security_reviewer"
    FRONTEND_REVIEWER = "frontend_reviewer"
    BACKEND_REVIEWER = "backend_reviewer"
    LOG_ANALYZER = "log_analyzer"
    DOCUMENTATION_WRITER = "documentation_writer"
    MEMORY_SUMMARIZER = "memory_summarizer"
    GIT_DIFF_REVIEWER = "git_diff_reviewer"


class ContextRequestType(StrEnum):
    CONVERSATION_FRAGMENT = "conversation_fragment"
    FILE = "file"
    SUMMARY = "summary"
    REPO_MAP_SECTION = "repo_map_section"


class ReviewVerdict(StrEnum):
    APPROVE = "approve"
    NEEDS_FIXES = "needs_fixes"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(StrEnum):
    """Tipos de evento (spec seccion 24)."""

    STATE_CHANGED = "state_changed"
    MESSAGE_STARTED = "message_started"
    MESSAGE_COMPLETED = "message_completed"
    FILE_READ = "file_read"
    FILE_CHANGED = "file_changed"
    COMMAND_STARTED = "command_started"
    COMMAND_COMPLETED = "command_completed"
    TEST_STARTED = "test_started"
    TEST_COMPLETED = "test_completed"
    CONTEXT_REQUESTED = "context_requested"
    CONTEXT_GRANTED = "context_granted"
    CONTEXT_DENIED = "context_denied"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    WORKER_SPAWNED = "worker_spawned"
    WORKER_COMPLETED = "worker_completed"
    WORKER_FAILED = "worker_failed"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    USER_INSTRUCTION = "user_instruction"
    TOKEN_UPDATED = "token_updated"
    CHECKPOINT_CREATED = "checkpoint_created"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Base comun
# ---------------------------------------------------------------------------


class SBModel(BaseModel):
    """Base de todos los modelos.

    extra="forbid" es deliberado: un JSON de agente con campos inventados
    debe fallar la validacion y disparar el reintento de la seccion 23.1.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _reject_naive_datetime(cls, value: Any) -> Any:
        """Rechaza timestamps sin zona horaria.

        Un datetime naive serializado como UTC produce desfases silenciosos
        que solo se descubren al comparar eventos de sesiones distintas.
        """
        if isinstance(value, datetime) and value.tzinfo is None:
            msg = "los timestamps deben ser conscientes de zona horaria (UTC)"
            raise ValueError(msg)
        return value


# ---------------------------------------------------------------------------
# Nucleo del dominio
# ---------------------------------------------------------------------------


class Project(SBModel):
    """Un repositorio bajo gestion. Una fila por base (spec seccion 20)."""

    id: str
    name: str
    path: str
    path_key: str = Field(
        description="os.path.normcase de la ruta resuelta; deduplica en Windows"
    )
    created_at: UtcDatetime = Field(default_factory=utc_now)


class Objective(SBModel):
    """Raiz del trabajo: tareas, plan, sesiones y presupuestos cuelgan de el."""

    id: Alias
    project_id: str
    text: str
    status: ObjectiveStatus = ObjectiveStatus.ACTIVE
    created_at: UtcDatetime = Field(default_factory=utc_now)
    closed_at: UtcDatetime | None = None


class Task(SBModel):
    """Unidad de trabajo asignable.

    coordinator es el responsable; worker el ejecutor delegado, opcional.
    No existe un tercer campo de asignacion (spec seccion 10).
    """

    id: Alias
    objective_id: Alias
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.NORMAL
    coordinator: Coordinator | None = None
    worker: WorkerId | None = None
    dependencies: list[Alias] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    error: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)


class Decision(SBModel):
    """Decision tecnica con linaje.

    superseded_by conserva la cadena de razones cuando una decision
    reemplaza a otra: es justo lo que un segundo cerebro debe recordar.
    """

    id: Alias
    project_id: str
    objective_id: Alias | None = None
    topic: str
    decision: str
    reason: str = ""
    status: DecisionStatus = DecisionStatus.PROPOSED
    superseded_by: Alias | None = None
    proposed_by: Actor
    accepted_by: list[Coordinator] = Field(default_factory=list)
    source_summary: str | None = None
    source_conversation: str | None = None
    source_messages: list[str] = Field(default_factory=list)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)


class Plan(SBModel):
    """Consolidacion determinista de los dos cierres (spec seccion 7.4).

    Lo construye el ORQUESTADOR sin llamar a ningun modelo. Un plan no
    puede aprobarse con tareas sin asignar: la vista de aprobacion obliga
    a resolver cada huerfana antes de habilitar /approve.
    """

    id: Alias
    objective_id: Alias
    summary: str = ""
    tasks: list[Alias] = Field(default_factory=list)
    assignments: dict[str, Coordinator] = Field(default_factory=dict)
    contracts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unresolved_disagreements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    approved_by: str | None = None
    superseded_by: Alias | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    def unassigned_tasks(self) -> list[Alias]:
        """Tareas del plan sin coordinador. Bloquean la aprobacion."""
        return [t for t in self.tasks if t not in self.assignments]


# ---------------------------------------------------------------------------
# Trabajadores
# ---------------------------------------------------------------------------


class WorkerTaskContract(SBModel):
    """Contrato entregado a un trabajador (spec secciones 10 y 15).

    maximum_files y maximum_tool_calls NO son imponibles como flags de las
    CLIs: se aplican por capas (instruccion en el prompt, aproximacion con
    --max-turns, vigilancia del stream con tolerancia +20 %, y validacion
    a posteriori del resultado).
    """

    task_id: Alias
    worker_id: WorkerId
    worker_type: WorkerType
    provider: Provider
    model: str | None = None
    objective: str
    context_files: list[str] = Field(default_factory=list)
    context_summaries: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    permission_mode: PermissionMode = PermissionMode.READ_ONLY
    token_budget: int = Field(default=8000, gt=0)
    time_limit_seconds: int = Field(default=300, gt=0)
    maximum_files: int = Field(default=8, gt=0)
    maximum_tool_calls: int = Field(default=20, gt=0)
    can_spawn_agents: bool = False
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("can_spawn_agents")
    @classmethod
    def _depth_one_only(cls, value: bool) -> bool:
        """Profundidad maxima de agentes: 1 (spec seccion 2)."""
        if value:
            msg = "los trabajadores no pueden crear otros trabajadores"
            raise ValueError(msg)
        return value


class WorkerResult(SBModel):
    """Resultado estructurado de un trabajador (spec seccion 10)."""

    task_id: Alias
    worker_id: WorkerId
    status: WorkerStatus
    error: str | None = None
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requests: list[str] = Field(default_factory=list)
    confidence: Confidence = 0.0
    tokens_estimated: int = Field(default=0, ge=0)
    started_at: UtcDatetime = Field(default_factory=utc_now)
    finished_at: UtcDatetime | None = None


# ---------------------------------------------------------------------------
# Peticiones al orquestador
# ---------------------------------------------------------------------------


class ContextRequest(SBModel):
    """Peticion de contexto adicional (spec seccion 12)."""

    id: Alias
    project_id: str
    session_id: str | None = None
    status: ContextRequestStatus = ContextRequestStatus.PENDING
    requested_by: Actor
    type: ContextRequestType
    topic: str
    reason: str = ""
    maximum_items: int = Field(default=3, gt=0)
    priority: Priority = Priority.NORMAL
    created_at: UtcDatetime = Field(default_factory=utc_now)


class ApprovalRequest(SBModel):
    """Solicitud de aprobacion humana (spec secciones 4.5 y 10).

    Ocurre SIEMPRE en frontera de turno: el proceso del agente ya termino.
    No hay timeout que pausar, porque no hay proceso vivo esperando.
    """

    id: Alias
    project_id: str
    session_id: str | None = None
    requested_by: Actor
    action: str
    description: str = ""
    risk: RiskLevel = RiskLevel.MEDIUM
    command: str | None = None
    affected_paths: list[str] = Field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    resolved_by: str | None = None
    resolved_at: UtcDatetime | None = None
    response_note: str | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Eventos y conversaciones
# ---------------------------------------------------------------------------


class Event(SBModel):
    """Esquema CANONICO de evento (spec seccion 24).

    Identico en el bus en memoria y en la tabla events. No existen dos
    formatos de evento: las instrucciones remotas tambien usan este.
    """

    event_id: str
    timestamp: UtcDatetime = Field(default_factory=utc_now)
    project_id: str | None = None
    session_id: str | None = None
    actor: Actor
    type: EventType
    severity: EventSeverity = EventSeverity.INFO
    message: str = ""
    progress: Progress | None = None
    tokens_estimated: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class Session(SBModel):
    """Sesion de una fase. Guarda el id de sesion de la CLI para --resume."""

    id: str
    project_id: str
    objective_id: Alias | None = None
    coordinator: Coordinator | None = None
    phase: Phase
    provider_session_id: str | None = None
    started_at: UtcDatetime = Field(default_factory=utc_now)
    ended_at: UtcDatetime | None = None


class Message(SBModel):
    """Mensaje archivado (spec seccion 13).

    Los resumenes deben referenciar estos ids para poder volver del
    resumen a la fuente exacta.
    """

    id: Alias
    session_id: str
    agent: Actor
    round: int = Field(default=1, ge=1)
    phase: Phase
    timestamp: UtcDatetime = Field(default_factory=utc_now)
    message: str
    tokens_estimated: int = Field(default=0, ge=0)


class Handoff(SBModel):
    """Relevo que un coordinador deja al cerrar su turno o fase (spec 10.1)."""

    written_by: Coordinator
    phase: Phase
    session_id: str | None = None
    done: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    blocked_on: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions_for_other: list[str] = Field(default_factory=list)
    created_at: UtcDatetime = Field(default_factory=utc_now)


class Checkpoint(SBModel):
    """Todo lo necesario para reanudar (spec secciones 10.1 y 25).

    La reanudacion lee EXCLUSIVAMENTE la tabla checkpoints;
    CHECKPOINT.json es un espejo humano regenerable.
    """

    created_at: UtcDatetime = Field(default_factory=utc_now)
    schema_version: int = 1
    global_state: GlobalState
    phase: Phase
    objective_id: Alias | None = None
    plan_id: Alias | None = None
    coordinator_sessions: dict[Coordinator, str] = Field(default_factory=dict)
    active_workers: list[WorkerId] = Field(default_factory=list)
    open_worktrees: list[str] = Field(default_factory=list)
    pending_approvals: list[Alias] = Field(default_factory=list)
    last_event_id: str | None = None
    # Estado del que se entro en PAUSED (auditoria F5, critico F1): sin
    # persistirlo, una maquina restaurada en PAUSED no tenia NINGUNA
    # transicion legal (resume() exige el estado guardado) y el proyecto
    # quedaba atascado para siempre.
    paused_from: GlobalState | None = None


class UserRule(SBModel):
    """Regla del usuario. Comparte la prioridad 1 con la instruccion actual."""

    id: int
    project_id: str
    text: str
    active: bool = True
    created_at: UtcDatetime = Field(default_factory=utc_now)


class SummaryEntry(SBModel):
    """Entrada de SUMMARY_INDEX.json: buscar resumenes sin abrirlos."""

    file: str
    topic: str
    keywords: list[str] = Field(default_factory=list)
    decisions: list[Alias] = Field(default_factory=list)
    tasks: list[Alias] = Field(default_factory=list)
    created_at: UtcDatetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Esquemas de salida de los agentes (spec seccion 23)
# ---------------------------------------------------------------------------


class TaskProposal(SBModel):
    """Tarea candidata dentro de un cierre.

    El orquestador le asigna el alias TASK-nnn al consolidar (spec 7.4);
    por eso aqui todavia no hay id. El titulo no puede ser vacio: es la
    clave de comparacion de la consolidacion (auditoria funcional #7).
    """

    title: Annotated[str, StringConstraints(min_length=1)]
    description: str = ""
    allowed_paths: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class DiscussionOutput(SBModel):
    """Rondas 1 y 2 de cada coordinador (spec seccion 23)."""

    opinion: str = ""
    proposal: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    candidate_tasks: list[TaskProposal] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    suggested_workers: list[WorkerType] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    estimated_budget: int = Field(default=0, ge=0)
    confidence: Confidence = 0.0


class ClosingOutput(SBModel):
    """Ronda 3 y mini-rondas de replanificacion (spec secciones 23 y 6)."""

    role_proposal: str = ""
    tasks_i_accept: list[TaskProposal] = Field(default_factory=list)
    tasks_for_other: list[TaskProposal] = Field(default_factory=list)
    shared_contracts: list[str] = Field(default_factory=list)
    allowed_paths_requested: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unresolved_disagreements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    workers_requested: list[WorkerType] = Field(default_factory=list)


class WorkerRequest(SBModel):
    """Peticion de trabajador desde un turno de ejecucion.

    El coordinador propone lo que conoce; el orquestador valida contra los
    filtros de la seccion 15 y completa el resto del contrato.
    """

    worker_type: WorkerType
    objective: str
    allowed_paths: list[str] = Field(default_factory=list)
    token_budget: int | None = Field(default=None, gt=0)


class ExecutionTurnOutput(SBModel):
    """Turnos de EXECUTING y CORRECTING (spec seccion 23).

    Es la frontera de turno por la que se piden trabajadores, aprobaciones
    y contexto: no existe otro canal, porque el proceso no tiene stdin.
    """

    progress_summary: str = ""
    tasks_advanced: list[Alias] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    worker_requests: list[WorkerRequest] = Field(default_factory=list)
    approval_requests: list[str] = Field(default_factory=list)
    context_requests: list[str] = Field(default_factory=list)
    blocked_on: list[str] = Field(default_factory=list)
    next_step: str = ""


class ReviewFinding(SBModel):
    """Hallazgo de la revision cruzada."""

    file: str = ""
    severity: RiskLevel = RiskLevel.MEDIUM
    description: str
    suggested_fix: str = ""


class CrossReviewOutput(SBModel):
    """Revision cruzada (spec secciones 23 y 7.6).

    Ramificacion: ambos approve -> READY_TO_MERGE; algun needs_fixes ->
    CORRECTING. Maximo dos ciclos; al tercero decide el humano.
    """

    reviewed_coordinator: Coordinator
    verdict: ReviewVerdict
    findings: list[ReviewFinding] = Field(default_factory=list)
    tests_verified: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: Confidence = 0.0


class HandoffOutput(SBModel):
    """Ultimo turno antes de archivar la sesion de una fase (spec seccion 23)."""

    done: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    blocked_on: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions_for_other: list[str] = Field(default_factory=list)
