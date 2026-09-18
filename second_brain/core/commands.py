"""Parser único de comandos del usuario (spec sección 5).

Compartido por cli.py (fases 1-6) y la UI Textual (fase 7): ambas
interfaces aceptan exactamente los mismos comandos porque ambas llaman
aquí. La UI no tiene parser propio.

Gramática soportada:

    /comando arg1 arg2 ...      → ParsedInput(kind=COMMAND)
    @fable texto...             → ParsedInput(kind=DIRECTED, target=fable)
    @sol / @both / @worker:ID   → ídem con su destinatario
    cualquier otro texto        → ParsedInput(kind=MESSAGE) — en la CLI
                                  de la Fase 1, un mensaje suelto es el
                                  objetivo del usuario.

Este módulo solo parsea: la semántica (qué hace /pause con procesos en
curso, que @worker solo acepte cancel...) vive en el orquestador y está
definida en la sección 5 del spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class InputKind(StrEnum):
    """Naturaleza de la línea escrita por el usuario."""

    EMPTY = "empty"
    COMMAND = "command"
    DIRECTED = "directed"
    MESSAGE = "message"


@dataclass(frozen=True, slots=True)
class ParsedInput:
    """Resultado del parseo de una línea del usuario."""

    kind: InputKind
    name: str = ""
    args: list[str] = field(default_factory=list)
    target: str = ""
    text: str = ""

    @property
    def rest(self) -> str:
        """Los argumentos como cadena única (para notas y textos libres)."""
        return " ".join(self.args)


def parse(line: str) -> ParsedInput:
    """Parsea una línea de entrada del usuario (spec sección 5)."""
    stripped = line.strip()
    if not stripped:
        return ParsedInput(kind=InputKind.EMPTY)

    if stripped.startswith("/"):
        parts = stripped[1:].split()
        if not parts:
            return ParsedInput(kind=InputKind.EMPTY)
        return ParsedInput(
            kind=InputKind.COMMAND,
            name=parts[0].lower(),
            args=parts[1:],
        )

    if stripped.startswith("@"):
        head, _, rest = stripped.partition(" ")
        return ParsedInput(
            kind=InputKind.DIRECTED,
            target=head[1:].lower(),
            text=rest.strip(),
        )

    return ParsedInput(kind=InputKind.MESSAGE, text=stripped)
