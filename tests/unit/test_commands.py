"""Parser unico de comandos del usuario (spec seccion 5).

Compartido por cli.py y la UI Textual: ambas interfaces aceptan los
mismos comandos porque ambas llaman a core/commands.parse().
"""

from __future__ import annotations

from second_brain.core.commands import InputKind, parse


def test_comando_con_args() -> None:
    """/comando arg1 arg2 -> COMMAND con nombre en minusculas y args (spec 5)."""
    parsed = parse("/approve PLAN-001")
    assert parsed.kind is InputKind.COMMAND
    assert parsed.name == "approve"
    assert parsed.args == ["PLAN-001"]


def test_comando_se_normaliza_a_minusculas() -> None:
    """El nombre del comando se normaliza; los args se conservan tal cual."""
    parsed = parse('/REJECT PLAN-001 "No cambiar la base"')
    assert parsed.name == "reject"
    assert parsed.args == ["PLAN-001", '"No', "cambiar", "la", 'base"']


def test_comando_sin_args() -> None:
    """/status -> COMMAND sin argumentos."""
    parsed = parse("/status")
    assert parsed.kind is InputKind.COMMAND
    assert parsed.name == "status"
    assert parsed.args == []


def test_dirigido_a_fable() -> None:
    """@fable texto -> DIRECTED con destinatario y texto (spec 5)."""
    parsed = parse("@fable Explica tu arquitectura")
    assert parsed.kind is InputKind.DIRECTED
    assert parsed.target == "fable"
    assert parsed.text == "Explica tu arquitectura"


def test_dirigido_a_sol() -> None:
    """@sol -> DIRECTED con destinatario sol."""
    parsed = parse("@sol Revisa compatibilidad")
    assert parsed.kind is InputKind.DIRECTED
    assert parsed.target == "sol"
    assert parsed.text == "Revisa compatibilidad"


def test_dirigido_a_worker_conserva_el_id() -> None:
    """@worker:F-H01 -> DIRECTED; el id del worker va en el destinatario."""
    parsed = parse("@worker:F-H01 cancel")
    assert parsed.kind is InputKind.DIRECTED
    assert parsed.target == "worker:f-h01"
    assert parsed.text == "cancel"


def test_texto_libre_es_mensaje() -> None:
    """Cualquier otro texto -> MESSAGE (en la Fase 1, el objetivo del usuario)."""
    parsed = parse("Implementar autenticacion local")
    assert parsed.kind is InputKind.MESSAGE
    assert parsed.text == "Implementar autenticacion local"


def test_linea_vacia() -> None:
    """Una linea vacia o solo espacios -> EMPTY (spec 5)."""
    assert parse("").kind is InputKind.EMPTY
    assert parse("    ").kind is InputKind.EMPTY
    assert parse("\t\n").kind is InputKind.EMPTY


def test_barra_sola_es_vacia() -> None:
    """Una barra sin comando no es un comando valido."""
    assert parse("/").kind is InputKind.EMPTY
