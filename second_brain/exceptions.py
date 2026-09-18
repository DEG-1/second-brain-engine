"""Jerarquia propia de errores: sustento de la regla "fallar ruidosamente".

Ningun adaptador ni modulo degrada en silencio: todo fallo se expresa
con una de estas excepciones y un evento error en el bus. (Spec 16.1, 21)
"""


class SecondBrainError(Exception):
    """Base de todos los errores del sistema."""


class AdapterError(SecondBrainError):
    """Fallo de un adaptador de CLI (comando ausente, salida inesperada)."""


class QuotaExhaustedError(AdapterError):
    """Cuota del proveedor agotada; dispara la politica de modo degradado (spec 16)."""


class OutputFormatError(AdapterError):
    """La salida de la CLI no coincide con el formato esperado; nunca degradar en silencio."""


class BudgetExceededError(SecondBrainError):
    """Presupuesto de tokens excedido (spec 14)."""


class ApprovalRequiredError(SecondBrainError):
    """Accion sensible intentada sin aprobacion humana (spec 4.5, 19)."""


class IllegalTransitionError(SecondBrainError):
    """Transicion de estado no listada en la tabla de la spec seccion 6."""


class ConfigurationError(SecondBrainError):
    """Configuracion ausente, ilegible o invalida (spec seccion 22)."""


class DatabaseError(SecondBrainError):
    """Fallo de la capa de persistencia (spec seccion 20).

    Incluye el rechazo a abrir una base cuya version de esquema supera la
    ultima migracion conocida: hay que actualizar la aplicacion.
    """
