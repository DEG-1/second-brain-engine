"""Bus de eventos en memoria (spec secciones 5 y 24).

Publicar es sincrono y no bloqueante; la entrega ocurre en un consumidor
de fondo que aisla cada sink. Un sink que falla no puede tumbar a los
demas ni al bus.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from second_brain.core.event_bus import EventBus
from second_brain.memory.models import Event, EventType


def _emit(bus: EventBus, message: str = "") -> Event:
    return bus.emit(type=EventType.WARNING, actor="orchestrator", message=message)


async def test_emit_no_bloqueante_devuelve_event_con_id_correlativo() -> None:
    """emit() asigna un event_id correlativo y devuelve el Event (spec 24)."""
    bus = EventBus()
    await bus.start()
    ev1 = _emit(bus, "uno")
    ev2 = _emit(bus, "dos")
    assert ev1.event_id == "EVT-001"
    assert ev2.event_id == "EVT-002"
    assert isinstance(ev1, Event)
    await bus.aclose()


async def test_varios_sinks_reciben_todo() -> None:
    """Cada evento se entrega a todos los sinks registrados."""
    bus = EventBus()
    a: list[Event] = []
    b: list[Event] = []
    bus.register_sink(a.append)
    bus.register_sink(b.append)
    await bus.start()
    _emit(bus, "x")
    _emit(bus, "y")
    await bus.drain()
    await bus.aclose()
    assert [e.message for e in a] == ["x", "y"]
    assert [e.message for e in b] == ["x", "y"]


async def test_sink_que_lanza_no_tumba_a_los_demas(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un sink que lanza se registra y se ignora; los demas siguen (spec 5)."""

    def sink_malo(_event: Event) -> None:
        raise RuntimeError("sink roto a proposito")

    buenos: list[Event] = []
    bus = EventBus()
    bus.register_sink(sink_malo)
    bus.register_sink(buenos.append)
    await bus.start()
    with caplog.at_level(logging.ERROR):
        _emit(bus, "sobrevive")
        await bus.drain()
    await bus.aclose()

    assert [e.message for e in buenos] == ["sobrevive"]
    assert any("sink" in rec.message.lower() for rec in caplog.records)


async def test_sinks_sincronos_y_asincronos() -> None:
    """El bus admite sinks sincronos y asincronos por igual (spec 5)."""
    sincrono: list[Event] = []
    asincrono: list[Event] = []

    async def sink_async(event: Event) -> None:
        await asyncio.sleep(0)
        asincrono.append(event)

    bus = EventBus()
    bus.register_sink(sincrono.append)
    bus.register_sink(sink_async)
    await bus.start()
    _emit(bus, "z")
    await bus.drain()
    await bus.aclose()
    assert len(sincrono) == 1
    assert len(asincrono) == 1


async def test_aclose_drena_lo_pendiente() -> None:
    """aclose() entrega todo lo encolado antes de cerrar (spec 24)."""
    recibidos: list[Event] = []

    async def sink_lento(event: Event) -> None:
        await asyncio.sleep(0.01)
        recibidos.append(event)

    bus = EventBus()
    bus.register_sink(sink_lento)
    await bus.start()
    for i in range(5):
        _emit(bus, str(i))
    await bus.aclose()  # debe drenar los 5 aunque el sink sea lento
    assert [e.message for e in recibidos] == ["0", "1", "2", "3", "4"]


async def test_publish_tras_aclose_lanza() -> None:
    """Tras aclose() el bus rechaza nuevos eventos (spec 24)."""
    bus = EventBus()
    await bus.start()
    await bus.aclose()
    with pytest.raises(RuntimeError):
        _emit(bus, "tarde")


async def test_unregister_quita_el_sink() -> None:
    """register_sink devuelve como quitar el sink; deja de recibir."""
    recibidos: list[Event] = []
    bus = EventBus()
    quitar = bus.register_sink(recibidos.append)
    await bus.start()
    _emit(bus, "antes")
    await bus.drain()
    quitar()
    _emit(bus, "despues")
    await bus.drain()
    await bus.aclose()
    assert [e.message for e in recibidos] == ["antes"]
