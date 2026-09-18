"""Configuracion raiz de pytest.

Aisla la suite del entorno real del usuario ANTES de que se importe nada
de second_brain: sin esto, un test de config.py podria sobrescribir el
userdata/config.yaml real.
"""

import os
import tempfile
from pathlib import Path

# SECOND_BRAIN_HOME tiene prioridad sobre paths.user_data_dir y
# paths.user_state_dir (ver resources/config.default.yaml). Apuntarlo a un
# directorio temporal deja userdata/ intacto durante los tests.
_TEST_HOME = Path(tempfile.gettempdir()) / "second_brain_tests_home"
_TEST_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("SECOND_BRAIN_HOME", str(_TEST_HOME))
