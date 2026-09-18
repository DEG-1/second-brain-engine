"""Modelos Pydantic y enums (spec seccion 10, politica 23.1).

Verifica las reglas que memory/models.py hace cumplir: serializacion UTC
con sufijo Z, enums cerrados, extra="forbid", profundidad de agentes 1,
rechazo de datetimes naive y Plan.unassigned_tasks().
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from second_brain.memory.models import (
    Coordinator,
    Event,
    EventType,
    Objective,
    ObjectiveStatus,
    Plan,
    Task,
    TaskStatus,
    WorkerTaskContract,
)


def test_timestamp_se_serializa_en_utc_con_sufijo_z() -> None:
    """Los timestamps se guardan en UTC ISO-8601 con sufijo Z (spec 10)."""
    momento = datetime(2026, 7, 18, 15, 30, 0, tzinfo=UTC)
    obj = Objective(id="OBJ-001", project_id="PRJ-1", text="x", created_at=momento)
    volcado = obj.model_dump(mode="json")
    assert volcado["created_at"] == "2026-07-18T15:30:00Z"
    assert volcado["created_at"].endswith("Z")
    assert "+00:00" not in volcado["created_at"]


def test_timestamp_con_offset_se_normaliza_a_utc_z() -> None:
    """Un instante con offset se convierte a UTC antes de serializar (spec 10)."""
    bogota = timezone(timedelta(hours=-5))
    momento = datetime(2026, 7, 18, 10, 0, 0, tzinfo=bogota)
    ev = Event(event_id="EVT-001", actor="fable", type=EventType.WARNING, timestamp=momento)
    assert ev.model_dump(mode="json")["timestamp"] == "2026-07-18T15:00:00Z"


def test_enum_cerrado_rechaza_valor_invalido() -> None:
    """Todo campo de estado es un enum cerrado, nunca cadena libre (spec 10)."""
    with pytest.raises(ValidationError):
        Objective(id="OBJ-001", project_id="PRJ-1", text="x", status="en_progreso")


def test_extra_forbid_rechaza_campo_inventado() -> None:
    """Un campo inventado dispara la validacion, no se acepta (spec 10, 23.1)."""
    with pytest.raises(ValidationError):
        Objective(
            id="OBJ-001",
            project_id="PRJ-1",
            text="x",
            campo_inventado=True,
        )


def test_can_spawn_agents_true_es_error() -> None:
    """Profundidad maxima de agentes 1: los trabajadores no crean otros (spec 2)."""
    with pytest.raises(ValidationError):
        WorkerTaskContract(
            task_id="TASK-001",
            worker_id="F-H01",
            worker_type="repository_explorer",
            provider="claude",
            objective="explorar",
            can_spawn_agents=True,
        )


def test_can_spawn_agents_false_es_valido() -> None:
    """can_spawn_agents=False es el unico valor admitido (spec 2)."""
    contrato = WorkerTaskContract(
        task_id="TASK-001",
        worker_id="F-H01",
        worker_type="repository_explorer",
        provider="claude",
        objective="explorar",
        can_spawn_agents=False,
    )
    assert contrato.can_spawn_agents is False


def test_datetime_naive_rechazado() -> None:
    """Un datetime sin zona horaria produce desfases silenciosos: se rechaza."""
    with pytest.raises(ValidationError):
        Objective(
            id="OBJ-001",
            project_id="PRJ-1",
            text="x",
            created_at=datetime(2026, 7, 18, 15, 30, 0),
        )


def test_plan_unassigned_tasks() -> None:
    """unassigned_tasks() devuelve las tareas del plan sin coordinador (spec 7.4)."""
    plan = Plan(
        id="PLAN-001",
        objective_id="OBJ-001",
        tasks=["TASK-001", "TASK-002", "TASK-003"],
        assignments={"TASK-001": Coordinator.FABLE, "TASK-003": Coordinator.SOL},
    )
    assert plan.unassigned_tasks() == ["TASK-002"]


def test_plan_sin_huerfanas_devuelve_lista_vacia() -> None:
    """Un plan con todas las tareas asignadas no bloquea la aprobacion."""
    plan = Plan(
        id="PLAN-001",
        objective_id="OBJ-001",
        tasks=["TASK-001"],
        assignments={"TASK-001": Coordinator.FABLE},
    )
    assert plan.unassigned_tasks() == []


def test_alias_invalido_rechazado() -> None:
    """El alias humano sigue el patron PREFIJO-NNN (spec 10)."""
    with pytest.raises(ValidationError):
        Task(id="tarea-1", objective_id="OBJ-001", title="x")


def test_task_status_por_defecto_es_pending() -> None:
    """Una tarea nace pending salvo indicacion contraria (spec 10)."""
    task = Task(id="TASK-001", objective_id="OBJ-001", title="x")
    assert task.status is TaskStatus.PENDING
    assert task.status.value == "pending"
    assert ObjectiveStatus.ACTIVE.value == "active"
