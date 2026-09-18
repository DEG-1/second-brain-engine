"""Bus de eventos en memoria con esquema canonico (spec seccion 24).

NO importa memory: expone register_sink(); memory/database.py
implementa el sink de persistencia y main.py los conecta (regla
anti-ciclo, spec 21).

Por que asincrono (spec seccion 5)
----------------------------------
La UI se refresca desde este bus y NO debe bloquearse durante procesos
largos. Por eso publicar un evento es una operacion sincrona y NO
bloqueante (solo encola), mientras que un consumidor de fondo entrega
cada evento a los sinks. Un sink lento o que falla NO puede tumbar el
bus ni bloquear a los demas sinks: cada entrega se aisla en su propio
try/except y las entregas de un mismo evento corren en paralelo.

Por que el bus genera el event_id (spec seccion 24)
---------------------------------------------------
El esquema canonico exige un event_id correlativo (EVT-001, EVT-002,
...). Centralizarlo aqui garantiza una unica secuencia monotona para
todos los productores (orquestador, coordinadores, trabajadores) y
evita colisiones que romperian last_event_id del checkpoint (spec 25).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

from second_brain.memory.models import (
    Actor,
    Event,
    EventSeverity,
    EventType,
    Progress,
)

logger = logging.getLogger(__name__)

# Un sink puede ser sincrono (devuelve None) o asincrono (devuelve un
# awaitable). El bus admite ambos: si el resultado es awaitable, lo espera.
# Se admite lo sincrono a proposito para sinks triviales (por ejemplo, un
# log en memoria de la UI) que no necesitan E/S.
Sink = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """Bus de eventos asincrono en memoria (spec secciones 5, 24 y 21).

    Ciclo de vida::

        bus = EventBus()
        bus.register_sink(mi_sink)
        await bus.start()
        bus.emit(type=EventType.STATE_CHANGED, actor="orchestrator")
        await bus.aclose()   # drena lo pendiente antes de cerrar

    Tambien es utilizable como gestor de contexto asincrono::

        async with EventBus() as bus:
            ...
    """

    def __init__(self, *, sink_timeout: float | None = None) -> None:
        """Crea el bus.

        sink_timeout: segundos maximos que se espera a un sink asincrono
        antes de abandonar esa entrega (protege contra un sink colgado,
        spec seccion 5). None desactiva el limite. No protege contra un
        sink SINCRONO que bloquee el bucle de eventos: por eso los sinks
        con E/S deben ser asincronos.
        """
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._sinks: list[Sink] = []
        self._sink_timeout = sink_timeout
        self._sequence = 0
        self._last_event_id: str | None = None
        self._consumer: asyncio.Task[None] | None = None
        self._closed = False

    def seed_sequence(self, highest_persisted: int) -> None:
        """Siembra la secuencia con el maximo event_id ya persistido.

        CRITICO (auditoria F1): cada proceso nuevo arranca la secuencia en
        cero; sin sembrarla, los event_id de una reapertura chocan con los
        historicos y el sink los descarta EN SILENCIO — toda sesion
        posterior a la primera perderia su auditoria completa. El
        composition root (cli) la siembra tras abrir la base del proyecto.
        """
        self._sequence = max(self._sequence, highest_persisted)

    @property
    def last_event_id(self) -> str | None:
        """Id del ultimo evento emitido; alimenta el checkpoint (spec 25)."""
        return self._last_event_id

    # ------------------------------------------------------------------
    # Registro de sinks (composition root; spec seccion 21)
    # ------------------------------------------------------------------
    def register_sink(self, sink: Sink) -> Callable[[], None]:
        """Registra un consumidor de eventos y devuelve como quitarlo.

        main.py conecta aqui el sink de persistencia de memory/database.py,
        el de la UI y el de logs. El bus NO conoce ninguno de esos modulos:
        asi se rompe el ciclo event_bus -> database -> event_bus (spec 21).
        """
        self._sinks.append(sink)

        def _unregister() -> None:
            try:
                self._sinks.remove(sink)
            except ValueError:
                pass

        return _unregister

    @property
    def sink_count(self) -> int:
        """Numero de sinks registrados (util para pruebas y diagnostico)."""
        return len(self._sinks)

    # ------------------------------------------------------------------
    # Publicacion (no bloqueante; spec seccion 5)
    # ------------------------------------------------------------------
    def next_event_id(self) -> str:
        """Devuelve el siguiente event_id correlativo (spec seccion 24)."""
        self._sequence += 1
        return f"EVT-{self._sequence:03d}"

    def emit(
        self,
        *,
        type: EventType,
        actor: Actor,
        severity: EventSeverity = EventSeverity.INFO,
        message: str = "",
        project_id: str | None = None,
        session_id: str | None = None,
        progress: Progress | None = None,
        tokens_estimated: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """Construye un Event canonico, lo encola y lo devuelve.

        Es SINCRONO y no bloqueante (spec seccion 5): asigna el event_id,
        valida contra el modelo canonico (spec 24) y encola. La entrega a
        los sinks ocurre despues, en el consumidor de fondo. El Event se
        devuelve para que el productor pueda, por ejemplo, guardar su
        event_id como last_event_id del checkpoint (spec 25).
        """
        if self._closed:
            msg = "el bus esta cerrado; no admite nuevos eventos"
            raise RuntimeError(msg)
        event = Event(
            event_id=self.next_event_id(),
            actor=actor,
            type=type,
            severity=severity,
            message=message,
            project_id=project_id,
            session_id=session_id,
            progress=progress,
            tokens_estimated=tokens_estimated,
            payload=payload if payload is not None else {},
        )
        self._last_event_id = event.event_id
        self.publish(event)
        return event

    def publish(self, event: Event) -> None:
        """Encola un Event ya construido (uso interno y de re-emision).

        No bloquea: la cola es ilimitada, asi que put_nowait nunca falla
        por capacidad. Preferir emit() salvo que ya se posea un Event con
        su event_id asignado (por ejemplo, una instruccion remota que
        reutiliza el esquema canonico, spec seccion 24).
        """
        if self._closed:
            msg = "el bus esta cerrado; no admite nuevos eventos"
            raise RuntimeError(msg)
        self._queue.put_nowait(event)

    # ------------------------------------------------------------------
    # Consumidor de fondo
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Arranca el consumidor de fondo (idempotente)."""
        if self._consumer is not None:
            return
        self._closed = False
        self._consumer = asyncio.create_task(self._run(), name="event-bus-consumer")

    async def _run(self) -> None:
        """Bucle que entrega cada evento encolado a todos los sinks."""
        while True:
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            finally:
                # Marcar SIEMPRE, incluso si _dispatch fallara, para que
                # aclose() (queue.join) no se quede colgado (spec 5).
                self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        """Entrega un evento a todos los sinks en paralelo y con aislamiento.

        En paralelo para que un sink lento no retrase a los demas del mismo
        evento; con return_exceptions=True porque _safe_call ya absorbe los
        fallos, pero nunca queremos que una excepcion escape y tumbe el
        consumidor (spec seccion 24: fallar ruidosamente, pero sin caer).
        """
        if not self._sinks:
            return
        await asyncio.gather(
            *(self._safe_call(sink, event) for sink in list(self._sinks)),
            return_exceptions=True,
        )

    async def _safe_call(self, sink: Sink, event: Event) -> None:
        """Invoca un sink aislando cualquier fallo (spec seccion 5).

        Un sink que lanza excepcion se registra y se ignora: no tumba el
        bus ni afecta a los demas sinks. CancelledError se re-lanza para
        respetar el cierre cooperativo de asyncio.
        """
        try:
            result = sink(event)
            if inspect.isawaitable(result):
                if self._sink_timeout is not None:
                    await asyncio.wait_for(result, self._sink_timeout)
                else:
                    await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "un sink fallo procesando el evento %s (%s); se ignora",
                event.event_id,
                event.type,
            )

    # ------------------------------------------------------------------
    # Cierre limpio (drenar lo pendiente; spec seccion 24)
    # ------------------------------------------------------------------
    async def drain(self) -> None:
        """Espera a que todo lo encolado se haya entregado."""
        await self._queue.join()

    async def aclose(self) -> None:
        """Cierre limpio: drena lo pendiente y detiene el consumidor.

        Tras aclose() el bus rechaza nuevos eventos. Es idempotente.
        """
        self._closed = True
        if self._consumer is None:
            return
        # Drenar lo pendiente ANTES de cancelar: nada de lo ya publicado
        # se pierde (spec seccion 24, fuente unica de eventos).
        await self._queue.join()
        self._consumer.cancel()
        try:
            await self._consumer
        except asyncio.CancelledError:
            pass
        finally:
            self._consumer = None

    async def __aenter__(self) -> EventBus:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
