"""Migraciones SQL numeradas (spec seccion 20).

Este __init__.py existe a proposito (auditoria M7): sin el, el
directorio es un paquete namespace que el discovery de setuptools no
lista y cuya resolucion via importlib.resources es fragil dentro del
bundle de PyInstaller — el .exe no podria ni crear la base de datos.
"""
