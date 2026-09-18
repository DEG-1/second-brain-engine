"""Maquina de estados global (spec seccion 6).

La tabla de transiciones legales se transcribe AQUI a partir del documento
(no se importa TRANSICIONES, que seria una tautologia): asi el test vigila
que el codigo siga fiel a la spec seccion 6.
"""

from __future__ import annotations

import pytest

from second_brain.core.event_bus import EventBus
from second_brain.core.state_machine import StateMachine, phase_for
from second_brain.exceptions import IllegalTransitionError
from second_brain.memory.models import EventSeverity, EventType, GlobalState, Phase

S = GlobalState

# Transiciones base, transcritas literalmente de la spec seccion 6.
_BASE_LEGAL: dict[GlobalState, set[GlobalState]] = {
    S.IDLE: {S.INITIALIZING},
    S.INITIALIZING: {S.INSPECTING, S.FAILED},
    S.INSPECTING: {S.DISCUSSING, S.FAILED},
    S.DISCUSSING: {S.PLANNING, S.FAILED},
    S.PLANNING: {S.WAITING_PLAN_APPROVAL, S.FAILED},
    S.WAITING_PLAN_APPROVAL: {S.EXECUTING, S.DISCUSSING, S.PLANNING, S.CANCELLED},
    S.EXECUTING: {S.CROSS_REVIEW, S.DISCUSSING, S.FAILED},
    S.CROSS_REVIEW: {S.CORRECTING, S.READY_TO_MERGE},
    S.CORRECTING: {S.CROSS_REVIEW, S.READY_TO_MERGE, S.FAILED},
    S.READY_TO_MERGE: {S.MERGING, S.CORRECTING, S.CANCELLED},
    S.MERGING: {S.SUMMARIZING, S.FAILED},
    S.SUMMARIZING: {S.COMPLETED, S.FAILED},
    S.COMPLETED: {S.IDLE},
    S.CANCELLED: {S.IDLE},
    S.FAILED: {S.IDLE},
}

# Alcanzables desde cualquier estado activo (spec 6).
_ACTIVOS = {
    S.INITIALIZING,
    S.INSPECTING,
    S.DISCUSSING,
    S.PLANNING,
    S.WAITING_PLAN_APPROVAL,
    S.EXECUTING,
    S.CROSS_REVIEW,
    S.CORRECTING,
    S.READY_TO_MERGE,
    S.MERGING,
    S.SUMMARIZING,
}
_INTERRUPCIONES = {S.PAUSED, S.CANCELLED, S.FAILED}


def _legal_pairs() -> list[tuple[GlobalState, GlobalState]]:
    pares: set[tuple[GlobalState, GlobalState]] = set()
    for origen, destinos in _BASE_LEGAL.items():
        for destino in destinos:
            pares.add((origen, destino))
    for origen in _ACTIVOS:
        for destino in _INTERRUPCIONES:
            pares.add((origen, destino))
    return sorted(pares, key=lambda p: (p[0].value, p[1].value))


@pytest.mark.parametrize(("origen", "destino"), _legal_pairs())
def test_transiciones_legales_de_la_seccion_6(
    origen: GlobalState, destino: GlobalState
) -> None:
    """Cada transicion listada en la tabla de la seccion 6 es aceptada."""
    machine = StateMachine(EventBus(), estado_inicial=origen)
    assert machine.can_transition(destino)
    assert machine.transition(destino) is destino
    assert machine.state is destino


# Muestra representativa de transiciones ILEGALES (spec 6: no listadas).
_ILEGALES = [
    (S.IDLE, S.EXECUTING),
    (S.IDLE, S.IDLE),
    (S.DISCUSSING, S.IDLE),
    (S.INSPECTING, S.EXECUTING),
    (S.SUMMARIZING, S.EXECUTING),
    (S.COMPLETED, S.DISCUSSING),
    (S.WAITING_PLAN_APPROVAL, S.MERGING),
    (S.CROSS_REVIEW, S.WAITING_PLAN_APPROVAL),
]


@pytest.mark.parametrize(("origen", "destino"), _ILEGALES)
async def test_transicion_ilegal_lanza_y_emite_error(
    origen: GlobalState, destino: GlobalState
) -> None:
    """Una transicion no listada lanza IllegalTransitionError y emite error."""
    bus = EventBus()
    capturados: list = []
    bus.register_sink(capturados.append)
    await bus.start()
    machine = StateMachine(bus, estado_inicial=origen)

    with pytest.raises(IllegalTransitionError):
        machine.transition(destino)
    await bus.drain()
    await bus.aclose()

    assert machine.state is origen  # no cambio
    errores = [e for e in capturados if e.type is EventType.ERROR]
    assert errores, "toda transicion ilegal emite un evento error (spec 6)"
    assert errores[-1].severity is EventSeverity.ERROR
    assert errores[-1].payload["reason"] == "illegal_transition"


async def test_transicion_legal_emite_state_changed() -> None:
    """Una transicion legal emite un state_changed persistente (spec 6, 24)."""
    bus = EventBus()
    capturados: list = []
    bus.register_sink(capturados.append)
    await bus.start()
    machine = StateMachine(bus, estado_inicial=S.IDLE)
    machine.transition(S.INITIALIZING)
    await bus.drain()
    await bus.aclose()

    cambios = [e for e in capturados if e.type is EventType.STATE_CHANGED]
    assert len(cambios) == 1
    assert cambios[0].payload == {"from": "idle", "to": "initializing", "phase": None}


def test_paused_guarda_y_restaura_el_estado_exacto() -> None:
    """PAUSED guarda el estado anterior y resume() vuelve exacto (spec 6)."""
    machine = StateMachine(EventBus(), estado_inicial=S.EXECUTING)
    machine.pause()
    assert machine.state is S.PAUSED
    assert machine.paused_from is S.EXECUTING
    # Desde PAUSED la unica salida legal es el estado guardado.
    assert machine.allowed_targets() == frozenset({S.EXECUTING})
    assert machine.resume() is S.EXECUTING
    assert machine.state is S.EXECUTING
    assert machine.paused_from is None


def test_paused_desde_otro_estado_restaura_ese_estado() -> None:
    """El estado guardado depende de donde se pauso (spec 6)."""
    machine = StateMachine(EventBus(), estado_inicial=S.CROSS_REVIEW)
    machine.pause()
    machine.resume()
    assert machine.state is S.CROSS_REVIEW


def test_resume_fuera_de_paused_falla() -> None:
    """resume() solo es legal estando en PAUSED (spec 6)."""
    machine = StateMachine(EventBus(), estado_inicial=S.EXECUTING)
    with pytest.raises(IllegalTransitionError):
        machine.resume()


@pytest.mark.parametrize("terminal", [S.COMPLETED, S.CANCELLED, S.FAILED])
def test_terminales_vuelven_a_idle(terminal: GlobalState) -> None:
    """COMPLETED/CANCELLED/FAILED -> IDLE: nuevo objetivo sin reiniciar (spec 6)."""
    machine = StateMachine(EventBus(), estado_inicial=terminal)
    assert machine.transition(S.IDLE) is S.IDLE


def test_phase_for_mapea_segun_lo_documentado() -> None:
    """phase_for() mapea estado global -> Phase segun la spec (secciones 7, 13)."""
    assert phase_for(S.INSPECTING) is Phase.INSPECTION
    assert phase_for(S.DISCUSSING) is Phase.DISCUSSION
    assert phase_for(S.PLANNING) is Phase.PLANNING
    assert phase_for(S.WAITING_PLAN_APPROVAL) is Phase.PLANNING
    assert phase_for(S.EXECUTING) is Phase.EXECUTION
    assert phase_for(S.CROSS_REVIEW) is Phase.CROSS_REVIEW
    assert phase_for(S.CORRECTING) is Phase.CORRECTION
    assert phase_for(S.READY_TO_MERGE) is Phase.INTEGRATION
    assert phase_for(S.MERGING) is Phase.INTEGRATION
    assert phase_for(S.SUMMARIZING) is Phase.CLOSING


@pytest.mark.parametrize("estado", [S.IDLE, S.INITIALIZING, S.PAUSED, S.COMPLETED, S.FAILED])
def test_phase_for_none_sin_sesion_de_modelo(estado: GlobalState) -> None:
    """IDLE, INITIALIZING, PAUSED y terminales no tienen fase de conversacion."""
    assert phase_for(estado) is None
