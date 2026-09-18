"""Maquina de estados global (spec seccion 6).

Tabla de transiciones explicita; toda transicion no listada lanza
IllegalTransitionError y emite evento error. Todo cambio de estado
genera un evento persistente.

Diseno (spec seccion 6)
-----------------------
- La tabla base _TRANSICIONES_BASE transcribe LITERALMENTE la seccion 6.
- PAUSED, CANCELLED y FAILED son alcanzables desde CUALQUIER estado
  activo; en vez de repetirlos en cada fila de la tabla, se anaden por
  codigo a los estados de _ESTADOS_ACTIVOS. Asi la tabla base queda
  legible y fiel al documento.
- PAUSED guarda EXPLICITAMENTE el estado anterior (_pausado_desde) y al
  reanudar vuelve exactamente a el. Desde PAUSED la unica transicion
  legal es regresar a ese estado guardado.
- FAILED "siempre guarda checkpoint antes de detenerse": esta maquina
  NO persiste nada; solo emite el state_changed (y, si la transicion es
  ilegal, un evento error). El orquestador escucha ese cambio y crea el
  checkpoint (spec 25). Se documenta aqui para que la frontera quede clara.

Aprobaciones puntuales (spec seccion 6, IMPORTANTE)
---------------------------------------------------
Las aprobaciones de la seccion 4.5 solicitadas durante EXECUTING,
CROSS_REVIEW o CORRECTING NO cambian el estado global: son objetos
ApprovalRequest en cola y solo el agente afectado pasa a BLOCKED /
REQUESTING_APPROVAL. Por eso esta maquina NO ofrece ninguna transicion
hacia WAITING_PLAN_APPROVAL desde esos estados: WAITING_PLAN_APPROVAL se
reserva EXCLUSIVAMENTE para la aprobacion del plan consolidado
(PLANNING -> WAITING_PLAN_APPROVAL), y la espera de aprobacion del merge
es el propio estado READY_TO_MERGE. El diseno de la tabla hace esa
violacion inexpresable: no hay arista que la permita.
"""

from __future__ import annotations

from second_brain.core.event_bus import EventBus
from second_brain.exceptions import IllegalTransitionError
from second_brain.memory.models import (
    Actor,
    EventSeverity,
    EventType,
    GlobalState,
    Phase,
)

# ---------------------------------------------------------------------------
# Tabla de transiciones (transcripcion literal de la spec seccion 6)
# ---------------------------------------------------------------------------

# Conjuntos vacios (COMPLETED/CANCELLED/FAILED -> IDLE) se declaran abajo.
_TRANSICIONES_BASE: dict[GlobalState, frozenset[GlobalState]] = {
    GlobalState.IDLE: frozenset({GlobalState.INITIALIZING}),
    GlobalState.INITIALIZING: frozenset({GlobalState.INSPECTING, GlobalState.FAILED}),
    GlobalState.INSPECTING: frozenset({GlobalState.DISCUSSING, GlobalState.FAILED}),
    GlobalState.DISCUSSING: frozenset({GlobalState.PLANNING, GlobalState.FAILED}),
    GlobalState.PLANNING: frozenset(
        {GlobalState.WAITING_PLAN_APPROVAL, GlobalState.FAILED}
    ),
    # WAITING_PLAN_APPROVAL se reserva a la aprobacion del PLAN (spec 6).
    GlobalState.WAITING_PLAN_APPROVAL: frozenset(
        {
            GlobalState.EXECUTING,
            GlobalState.DISCUSSING,  # ronda extra
            GlobalState.PLANNING,  # el usuario edita el plan
            GlobalState.CANCELLED,
        }
    ),
    GlobalState.EXECUTING: frozenset(
        {
            GlobalState.CROSS_REVIEW,
            GlobalState.DISCUSSING,  # replanificar (spec 6)
            GlobalState.FAILED,
        }
    ),
    GlobalState.CROSS_REVIEW: frozenset(
        {GlobalState.CORRECTING, GlobalState.READY_TO_MERGE}
    ),
    GlobalState.CORRECTING: frozenset(
        {GlobalState.CROSS_REVIEW, GlobalState.READY_TO_MERGE, GlobalState.FAILED}
    ),
    # READY_TO_MERGE es en si el estado de espera de aprobacion del merge.
    GlobalState.READY_TO_MERGE: frozenset(
        {GlobalState.MERGING, GlobalState.CORRECTING, GlobalState.CANCELLED}
    ),
    GlobalState.MERGING: frozenset({GlobalState.SUMMARIZING, GlobalState.FAILED}),
    GlobalState.SUMMARIZING: frozenset({GlobalState.COMPLETED, GlobalState.FAILED}),
    # Estados terminales -> IDLE (nuevo objetivo sin reiniciar la app).
    GlobalState.COMPLETED: frozenset({GlobalState.IDLE}),
    GlobalState.CANCELLED: frozenset({GlobalState.IDLE}),
    GlobalState.FAILED: frozenset({GlobalState.IDLE}),
    # PAUSED es dinamico: su unica salida es el estado guardado. Se
    # resuelve en _es_legal, no en esta tabla.
    GlobalState.PAUSED: frozenset(),
}

# Estados de trabajo en curso. Desde cualquiera de ellos se puede pausar,
# cancelar o fallar (spec seccion 6). No incluye IDLE (no hay trabajo),
# PAUSED (no es trabajo activo) ni los terminales.
_ESTADOS_ACTIVOS: frozenset[GlobalState] = frozenset(
    {
        GlobalState.INITIALIZING,
        GlobalState.INSPECTING,
        GlobalState.DISCUSSING,
        GlobalState.PLANNING,
        GlobalState.WAITING_PLAN_APPROVAL,
        GlobalState.EXECUTING,
        GlobalState.CROSS_REVIEW,
        GlobalState.CORRECTING,
        GlobalState.READY_TO_MERGE,
        GlobalState.MERGING,
        GlobalState.SUMMARIZING,
    }
)

# Alcanzables desde cualquier estado activo (spec seccion 6).
_INTERRUPCIONES: frozenset[GlobalState] = frozenset(
    {GlobalState.PAUSED, GlobalState.CANCELLED, GlobalState.FAILED}
)


def _construir_transiciones() -> dict[GlobalState, frozenset[GlobalState]]:
    """Tabla completa = base + interrupciones desde cada estado activo."""
    tabla: dict[GlobalState, frozenset[GlobalState]] = {}
    for estado in GlobalState:
        permitidas = _TRANSICIONES_BASE.get(estado, frozenset())
        if estado in _ESTADOS_ACTIVOS:
            permitidas = permitidas | _INTERRUPCIONES
        tabla[estado] = permitidas
    return tabla


TRANSICIONES: dict[GlobalState, frozenset[GlobalState]] = _construir_transiciones()

# ---------------------------------------------------------------------------
# Mapeo estado global -> Phase (spec secciones 7 y 13)
# ---------------------------------------------------------------------------

# La seccion 13 archiva la conversacion al cambiar de FASE. No todo estado
# global tiene fase de conversacion: IDLE, INITIALIZING, PAUSED y los
# terminales devuelven None (no hay sesion de modelo que archivar).
# INITIALIZING es trabajo del orquestador sin turnos de modelo (spec 7.2).
_FASE_POR_ESTADO: dict[GlobalState, Phase] = {
    GlobalState.INSPECTING: Phase.INSPECTION,
    GlobalState.DISCUSSING: Phase.DISCUSSION,
    GlobalState.PLANNING: Phase.PLANNING,
    # La aprobacion del plan sigue perteneciendo a la fase de planificacion.
    GlobalState.WAITING_PLAN_APPROVAL: Phase.PLANNING,
    GlobalState.EXECUTING: Phase.EXECUTION,
    GlobalState.CROSS_REVIEW: Phase.CROSS_REVIEW,
    GlobalState.CORRECTING: Phase.CORRECTION,
    # READY_TO_MERGE y MERGING son la fase de integracion (spec 7.8).
    GlobalState.READY_TO_MERGE: Phase.INTEGRATION,
    GlobalState.MERGING: Phase.INTEGRATION,
    GlobalState.SUMMARIZING: Phase.CLOSING,
}


def phase_for(estado: GlobalState) -> Phase | None:
    """Fase de conversacion de un estado, o None si no archiva (spec 13)."""
    return _FASE_POR_ESTADO.get(estado)


# ---------------------------------------------------------------------------
# Maquina de estados
# ---------------------------------------------------------------------------


class StateMachine:
    """Maquina de estados global del objetivo en curso (spec seccion 6).

    Arranca en IDLE. Cada transicion legal emite un evento state_changed
    persistente; cada intento ilegal emite un evento error y lanza
    IllegalTransitionError. La persistencia del evento la realiza el sink
    de la base de datos conectado al bus (spec 21), no esta clase.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        actor: Actor = "orchestrator",
        project_id: str | None = None,
        session_id: str | None = None,
        estado_inicial: GlobalState = GlobalState.IDLE,
        paused_from: GlobalState | None = None,
    ) -> None:
        """Crea la maquina enlazada al bus de eventos.

        actor por defecto "orchestrator": los cambios de estado global los
        decide el orquestador (spec seccion 6 y 24).

        ``paused_from`` siembra el estado guardado de PAUSED al RESTAURAR
        desde un checkpoint (auditoria F5, critico F1): una maquina
        restaurada en PAUSED sin este dato no tiene ninguna transicion
        legal. Solo tiene sentido con ``estado_inicial=PAUSED``; en
        cualquier otro estado se ignora.
        """
        self._bus = bus
        self._actor = actor
        self._project_id = project_id
        self._session_id = session_id
        self._estado = estado_inicial
        # Estado desde el que se entro en PAUSED; None si no esta en pausa
        # (spec seccion 6: al reanudar vuelve al estado anterior guardado).
        self._pausado_desde: GlobalState | None = (
            paused_from if estado_inicial is GlobalState.PAUSED else None
        )

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    @property
    def state(self) -> GlobalState:
        """Estado global actual."""
        return self._estado

    @property
    def phase(self) -> Phase | None:
        """Fase de conversacion del estado actual (spec 13), o None."""
        return phase_for(self._estado)

    @property
    def paused_from(self) -> GlobalState | None:
        """Estado guardado del que se entro en PAUSED, o None."""
        return self._pausado_desde

    def allowed_targets(self) -> frozenset[GlobalState]:
        """Estados alcanzables ahora mismo desde el estado actual."""
        if self._estado is GlobalState.PAUSED:
            # Desde PAUSED solo se puede reanudar al estado guardado.
            return frozenset() if self._pausado_desde is None else frozenset(
                {self._pausado_desde}
            )
        return TRANSICIONES[self._estado]

    def can_transition(self, destino: GlobalState) -> bool:
        """True si transicionar al destino seria legal ahora (spec 6)."""
        return destino in self.allowed_targets()

    # ------------------------------------------------------------------
    # Transiciones
    # ------------------------------------------------------------------
    def transition(
        self,
        destino: GlobalState,
        *,
        message: str = "",
    ) -> GlobalState:
        """Transiciona al destino si es legal; en otro caso falla ruidoso.

        Emite state_changed al exito. Ante una transicion ilegal emite un
        evento error y lanza IllegalTransitionError (spec seccion 6).
        Devuelve el nuevo estado.
        """
        if not self.can_transition(destino):
            self._emitir_error(destino)
            msg = (
                f"transicion ilegal {self._estado.value} -> {destino.value} "
                "(spec seccion 6)"
            )
            raise IllegalTransitionError(msg)

        anterior = self._estado

        # Gestion explicita del estado guardado de PAUSED (spec seccion 6).
        if destino is GlobalState.PAUSED:
            self._pausado_desde = anterior
        elif anterior is GlobalState.PAUSED:
            # Reanudacion: ya volvemos al estado guardado, limpiar marca.
            self._pausado_desde = None

        self._estado = destino
        self._emitir_cambio(anterior, destino, message)
        return destino

    def pause(self, *, message: str = "") -> GlobalState:
        """Pausa desde el estado activo actual, guardandolo (spec 6).

        Atajo de transition(PAUSED) que documenta la intencion. El estado
        anterior queda en paused_from para que resume() vuelva exacto.
        """
        return self.transition(GlobalState.PAUSED, message=message)

    def resume(self, *, message: str = "") -> GlobalState:
        """Reanuda al estado exacto anterior a la pausa (spec seccion 6)."""
        if self._estado is not GlobalState.PAUSED or self._pausado_desde is None:
            self._emitir_error(self._estado)
            msg = "resume() solo es legal estando en PAUSED con estado guardado"
            raise IllegalTransitionError(msg)
        return self.transition(self._pausado_desde, message=message)

    # ------------------------------------------------------------------
    # Emision de eventos (spec seccion 24)
    # ------------------------------------------------------------------
    def _emitir_cambio(
        self,
        anterior: GlobalState,
        destino: GlobalState,
        message: str,
    ) -> None:
        """Emite el state_changed persistente del cambio (spec 6 y 24)."""
        texto = message or f"{anterior.value} -> {destino.value}"
        fase = phase_for(destino)
        self._bus.emit(
            type=EventType.STATE_CHANGED,
            actor=self._actor,
            severity=EventSeverity.INFO,
            message=texto,
            project_id=self._project_id,
            session_id=self._session_id,
            payload={
                "from": anterior.value,
                "to": destino.value,
                "phase": fase.value if fase is not None else None,
            },
        )

    def _emitir_error(self, destino: GlobalState) -> None:
        """Emite el evento error de una transicion rechazada (spec 6)."""
        self._bus.emit(
            type=EventType.ERROR,
            actor=self._actor,
            severity=EventSeverity.ERROR,
            message=(
                f"transicion ilegal {self._estado.value} -> {destino.value}"
            ),
            project_id=self._project_id,
            session_id=self._session_id,
            payload={
                "from": self._estado.value,
                "to": destino.value,
                "reason": "illegal_transition",
            },
        )
