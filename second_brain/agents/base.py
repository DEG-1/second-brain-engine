"""Interfaz abstracta comun a todos los adaptadores de coordinador (spec 16).

Un adaptador traduce la interfaz uniforme de este modulo a la invocacion
concreta de una CLI (Claude Code para FABLE, Codex para SOL) o, en la
FASE 1, a respuestas simuladas en proceso (``fake_adapter``). El motor
(``core``) habla SIEMPRE con esta interfaz y NUNCA con una CLI concreta:
por eso la Fase 2 puede sustituir el fake por los adaptadores reales sin
tocar el orquestador.

DISENO ASINCRONO
----------------
Los metodos de ciclo de vida y de prompt son ``async`` porque en la Fase 2
lanzan subprocesos y drenan ``stdout``/``stderr`` en tareas concurrentes
(spec 16.1). Los metodos puros (``supports``, ``supports_subagents``,
``build_worker_command``, ``parse_output``) son sincronos: no tocan el
sistema y no deben introducir un ``await`` gratuito.

APROBACIONES EN FRONTERA DE TURNO (spec seccion 10)
---------------------------------------------------
Concepto clave que esta interfaz refleja: NO existe un proceso vivo
esperando una aprobacion. El agente termina su turno devolviendo la
solicitud (en su JSON de salida) y su proceso FINALIZA. La aprobacion la
resuelve el humano contra el orquestador; el turno siguiente se reanuda
con ``resume_session``. En consecuencia:

- ``send_prompt`` representa UN turno de proceso: arranca, produce salida
  y termina. No hay un canal ``stdin`` por el que aprobar a mitad de turno.
- ``time_limit_seconds`` del contrato aplica por TURNO de proceso, no por
  la vida de la tarea. Una tarea puede abarcar muchos turnos, cada uno con
  su propio limite.
- El estado ``BLOCKED`` significa "turno cerrado, sesion guardada,
  esperando resolucion": no hay timeout que pausar porque no hay proceso.

FALLAR RUIDOSAMENTE (spec 16.1, 19, 21)
---------------------------------------
Ningun adaptador degrada en silencio. Todo fallo se expresa con una
excepcion de ``second_brain.exceptions``: ``AdapterError`` (base),
``QuotaExhaustedError`` (cuota agotada) y ``OutputFormatError`` (salida que
no valida). En particular, entregar un ``PermissionMode`` no soportado por
el adaptador es ERROR explicito, nunca una degradacion callada
(``approved_commands`` no es expresable en ``codex exec``; spec 19).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from second_brain.exceptions import AdapterError
from second_brain.memory.models import (
    Coordinator,
    PermissionMode,
    Phase,
    Provider,
    WorkerTaskContract,
)

# Modelo de salida generico: cualquier subclase de los esquemas de la
# seccion 23 (DiscussionOutput, ClosingOutput, ...). Permite tipar
# parse_output sin acoplar la interfaz a un esquema concreto.
TOutput = TypeVar("TOutput", bound=BaseModel)


# ---------------------------------------------------------------------------
# Tipos de valor de la frontera del adaptador
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstallationInfo:
    """Resultado de ``validate_installation`` (spec 16.1).

    Se registra en el vault al arrancar para poder detectar despues un
    cambio de version de la CLI que rompa el formato de salida.
    """

    provider: Provider
    version: str
    executable_path: str


@dataclass(frozen=True, slots=True)
class Usage:
    """Uso de tokens de un turno (spec seccion 14).

    En la Fase 2 procede del evento final real de la CLI (``result`` de
    Claude, ``token_count`` de Codex); en la Fase 1 el fake lo simula de
    forma coherente para que ``core.budgets`` tenga con que trabajar. El
    campo ``is_estimate`` distingue ambos casos (spec 14: ``contains_estimates``).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    #: Tokens leidos de cache, APARTE de input (spec 14: se registran por
    #: separado y ponderan 0.1 en el computo del presupuesto; sumarlos a
    #: input falsearia el conteo de entrada fresca).
    cache_read_tokens: int = 0
    #: Tokens de CREACION de cache (consumo real facturable; auditoria F2).
    cache_creation_tokens: int = 0
    is_estimate: bool = True

    @property
    def total_tokens(self) -> int:
        """Entrada fresca + salida; el presupuesto se mide sobre este total.

        cache_read_tokens NO entra aqui: core/budgets lo pondera 0.1 por
        su cuenta (spec 14).
        """
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class SessionHandle:
    """Identifica una sesion de coordinador reanudable (spec 7.3, 16.1).

    ``provider_session_id`` es el id que devuelve la CLI y con el que se
    reanuda (``--resume`` en Claude, ``exec resume`` en Codex). Se persiste
    por fase en ``Session.provider_session_id`` y en el checkpoint.
    """

    provider_session_id: str
    coordinator: Coordinator
    provider: Provider
    phase: Phase
    permission_mode: PermissionMode
    # cwd de los turnos de ESTA sesion (Fase 5: el worktree del dueno,
    # spec 4.4/18). None = el workdir del adaptador (raiz del proyecto).
    # Los adaptadores DEBEN propagarlo al handle de cada respuesta: si se
    # pierde, el turno reanudado corre fuera del worktree (aislamiento
    # roto en silencio).
    workdir: Path | None = None


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    """Salida cruda de UN turno de proceso, antes de validar el esquema.

    ``raw_output`` es texto tal cual lo emitiria la CLI: puede llevar prosa
    y fences de markdown alrededor del JSON (spec 23.1). La validacion se
    hace aparte con ``parse_output`` para poder ejercitar la politica de
    reintento unico de la seccion 23.1 sin acoplarla al transporte.
    """

    raw_output: str
    session: SessionHandle
    usage: Usage


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerStreamEvent:
    """Evento de herramienta observado en el stream de un trabajador.

    Alimenta la vigilancia del contrato (spec 15, capa 3): cada evento
    cuenta contra maximum_tool_calls; ``file_path`` (si la herramienta
    toca un archivo concreto) cuenta contra maximum_files. ``writes``
    distingue lectura de escritura para el conteo de files_changed.
    """

    tool_name: str
    file_path: str | None = None
    writes: bool = False


class CoordinatorAdapter(ABC):
    """Contrato que implementan ``claude_adapter``, ``codex_adapter`` y el fake.

    Cada instancia representa a UN coordinador (``coordinator``) servido por
    UN motor (``provider``). El motor y el alias son independientes por
    diseno (spec 1): FABLE no es "Claude" ni SOL es "Codex" de forma fija,
    aunque esa sea la asignacion por defecto.
    """

    #: Modos de permiso que ESTE adaptador acepta. Cada subclase lo declara;
    #: la seccion 19 exige que un modo fuera de este conjunto sea error.
    supported_modes: frozenset[PermissionMode] = frozenset()

    def __init__(self, coordinator: Coordinator, provider: Provider) -> None:
        self.coordinator = coordinator
        self.provider = provider

    # -- Verificacion previa ------------------------------------------------

    @abstractmethod
    async def validate_installation(self) -> InstallationInfo:
        """Comprueba que la CLI existe y su version es soportada (spec 16.1).

        Devuelve la version y la ruta absoluta del ejecutable (resuelta con
        ``shutil.which`` en los adaptadores reales, para encontrar
        ``claude.cmd``/``codex.cmd`` via PATHEXT en Windows).

        Lanza:
            AdapterError: comando ausente o version por debajo de la minima.
        """

    @abstractmethod
    async def validate_authentication(self) -> None:
        """Comprueba que la sesion del proveedor esta autenticada (spec 16).

        Lanza:
            AdapterError: autenticacion vencida o ausente.
            QuotaExhaustedError: la cuenta existe pero la cuota esta agotada.
        """

    # -- Ciclo de vida de la sesion ----------------------------------------

    @abstractmethod
    async def start_session(
        self,
        phase: Phase,
        *,
        permission_mode: PermissionMode = PermissionMode.READ_ONLY,
        model: str | None = None,
        workdir: Path | None = None,
    ) -> SessionHandle:
        """Abre una sesion nueva para una fase (spec 7.3, 16.1).

        La sesion es la unidad reanudable: en la discusion cada coordinador
        mantiene UNA sesion durante los tres turnos, reanudada turno a turno
        (spec 7.3). ``permission_mode`` se traduce a los flags de la CLI
        (spec 19) y DEBE estar en ``supported_modes``; si no, es error.
        ``workdir`` (Fase 5) fija el cwd de los turnos de la sesion — el
        worktree del dueno en EXECUTING/CORRECTING, el del REVISADO en
        CROSS_REVIEW (spec 7.6); None = raiz del proyecto.

        Lanza:
            AdapterError: ``permission_mode`` no soportado, o fallo al abrir.
        """

    @abstractmethod
    async def resume_session(
        self,
        provider_session_id: str,
        phase: Phase,
        *,
        permission_mode: PermissionMode = PermissionMode.READ_ONLY,
        model: str | None = None,
        workdir: Path | None = None,
    ) -> SessionHandle:
        """Reanuda una sesion existente por su id de proveedor (spec 16.1, 25).

        Es el mecanismo de la recuperacion (seccion 25) y de la visibilidad
        turno a turno de la discusion (seccion 7.3): la sesion conserva los
        mensajes propios y del otro ya inyectados; nunca se reinyecta el
        historial completo.

        Lanza:
            AdapterError: la sesion no existe o el modo no esta soportado.
        """

    @abstractmethod
    async def send_prompt(
        self,
        session: SessionHandle,
        prompt: str,
        *,
        time_limit_seconds: int | None = None,
    ) -> AdapterResponse:
        """Ejecuta UN turno de proceso y devuelve su salida cruda (spec 16.1).

        Un turno arranca el proceso, produce salida y TERMINA (no queda vivo
        esperando aprobacion; spec 10). ``time_limit_seconds`` es el limite
        de ESTE turno, no de la tarea completa. La cancelacion (``cancel``)
        durante el turno aborta el arbol de procesos y hace fallar la llamada.

        No valida el esquema: eso es ``parse_output``, para poder ejercitar
        el reintento unico de la seccion 23.1 por separado.

        Lanza:
            AdapterError: proceso bloqueado, cancelado o con salida inutilizable.
            QuotaExhaustedError: la cuota se agoto durante el turno (spec 16).

        Timeout:
            Superar ``time_limit_seconds`` cancela el arbol de procesos y
            lanza ``AdapterError``; el turno se contabiliza como consumido.
        """

    @abstractmethod
    async def cancel(self) -> None:
        """Cancela el turno en curso de este adaptador (spec 16.1).

        En los adaptadores reales cancela el ARBOL COMPLETO de procesos
        (hijos recursivos) con gracia de 5 s: matar solo el hijo directo
        dejaria nietos escribiendo en el worktree. Es idempotente y no lanza
        si no hay nada que cancelar.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Libera todos los recursos del adaptador (spec 16.1).

        Cierra procesos vivos y pipes. Idempotente: llamarla dos veces no es
        error. Tras ``shutdown`` el adaptador no debe reutilizarse.
        """

    # -- Analisis de salida y uso ------------------------------------------

    @abstractmethod
    def parse_output(self, raw: str, model: type[TOutput]) -> TOutput:
        """Extrae y valida el JSON de la salida cruda (spec 23, 23.1).

        Tolera prosa alrededor, fences ```json y comas colgantes: extrae el
        primer bloque JSON y lo valida contra ``model``. Con ``extra=forbid``
        en los modelos (spec 10), un campo inventado hace fallar la
        validacion en vez de aceptarse en silencio.

        Devuelve:
            Una instancia de ``model`` ya validada.

        Lanza:
            OutputFormatError: no hay JSON extraible o no valida contra el
            modelo. El orquestador decide el reintento unico (seccion 23.1);
            el adaptador NO reintenta ni completa campos por defecto.
        """

    @abstractmethod
    async def request_usage(self) -> Usage:
        """Devuelve el uso de tokens del ultimo turno (spec 14, 16.1).

        En la Fase 2 procede del evento final real de la CLI; el adaptador
        no estima si la CLI reporta el dato. En la Fase 1 el fake lo simula.
        """

    # -- Capacidades (puras) -----------------------------------------------

    @abstractmethod
    def supports_subagents(self) -> bool:
        """Indica si el motor puede desplegar subagentes propios (spec 15).

        Gobierna si ``core`` delega la creacion de trabajadores a la CLI o
        los gestiona el propio orquestador como procesos separados.
        """

    @abstractmethod
    def build_worker_command(self, contract: WorkerTaskContract) -> list[str]:
        """Construye la linea de comando de un trabajador (spec 15, 16.1).

        Devuelve una lista de argumentos para ``shell=False`` (nunca una
        cadena de shell). Traduce ``contract.permission_mode`` a los flags
        del motor (spec 19); el modo DEBE estar soportado.

        Lanza:
            AdapterError: ``contract.permission_mode`` no soportado.
        """

    def parse_worker_stream_line(self, line: str) -> WorkerStreamEvent | None:
        """Interpreta una linea del stream de un TRABAJADOR (spec 15, capa 3).

        La vigilancia del contrato (worker_manager, Fase 6) cuenta eventos
        de herramienta y archivos tocados para aplicar maximum_tool_calls y
        maximum_files con tolerancia +20 %. Cada motor sabe leer su propio
        stream (stream-json de Claude, ThreadEvent de Codex); una linea que
        no es un evento de herramienta devuelve None.

        Implementacion por defecto: None siempre (motor sin stream
        interpretable; la vigilancia queda en las capas 1, 2 y 4).
        """
        return None

    def supports(self, mode: PermissionMode) -> bool:
        """True si este adaptador acepta ``mode`` (spec 19).

        Implementacion por defecto sobre ``supported_modes``. Se separa de
        ``require_mode_supported`` a proposito: consultar no es lo mismo que
        exigir. ``core`` puede preguntar ``supports`` para elegir un modo
        viable; los puntos de entrada (``start_session``,
        ``build_worker_command``) EXIGEN con ``require_mode_supported`` y
        fallan si el modo no esta.
        """
        return mode in self.supported_modes

    def require_mode_supported(self, mode: PermissionMode) -> None:
        """Exige que ``mode`` este soportado; si no, ERROR (spec 19).

        Nunca degrada en silencio: ``approved_commands`` es expresable en
        Claude via ``--allowedTools "Bash(cmd:*)"`` pero NO en ``codex exec``,
        y entregarselo a un adaptador que no lo soporta debe fallar de forma
        visible, no convertirse callandamente en ``read_only``.

        Lanza:
            AdapterError: ``mode`` no esta en ``supported_modes``.
        """
        if not self.supports(mode):
            supported = ", ".join(sorted(m.value for m in self.supported_modes))
            msg = (
                f"el adaptador {self.provider.value} no soporta el modo de "
                f"permiso '{mode.value}'; soportados: [{supported}]. "
                "No se degrada en silencio (spec 19)."
            )
            raise AdapterError(msg)
