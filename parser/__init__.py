# -*- coding: utf-8 -*-
"""
Paquete de parseo del campo NOTAS de Moebius.

Módulos, en el orden en que los usa el pipeline:

* :mod:`patrones`      -- todas las expresiones regulares del proyecto.
* :mod:`motivos`       -- catálogo cerrado de motivos de revisión manual.
* :mod:`lector`        -- detección de encoding y máquina de estados de registros.
* :mod:`segmentador`   -- división del bloque de notas en visitas.
* :mod:`extractor`     -- extracción de campos por sección.
* :mod:`normalizador`  -- limpieza de nombres, decimales, fechas y acentos.
* :mod:`deduplicador`  -- fusión de clientes y de visitas.
* :mod:`correcciones`  -- carga y aplicación de ``correcciones_manuales.csv``.
"""

from __future__ import annotations

__all__ = [
    "correcciones",
    "deduplicador",
    "extractor",
    "lector",
    "motivos",
    "normalizador",
    "patrones",
    "segmentador",
]
