"""Recursos de datos empaquetados con la aplicacion.

Paquete real (no solo carpeta) para que importlib.resources funcione
igual en desarrollo, en wheel y dentro del bundle de PyInstaller.

REGLA: ningun modulo accede a estos archivos con Path(__file__).
El unico acceso permitido es utils/paths.py -> resource_text().
"""
