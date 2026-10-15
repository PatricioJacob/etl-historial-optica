# -*- coding: utf-8 -*-
"""
Corre la demo de punta a punta con un solo comando.

    python correr_demo.py              # genera los datos si faltan y corre el ETL
    python correr_demo.py --regenerar  # vuelve a generar los datos antes

1. Si ``datos_ejemplo/`` no existe, lo genera con ``generar_datos_ejemplo.py``.
2. Corre el ETL (``etl_optica.py``) sobre esos datos y deja todo en ``salida/``.
3. Imprime un resumen: clientes, visitas, duplicados fusionados y casos de
   revisión por motivo.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import Counter

import etl_optica
import generar_datos_ejemplo
from parser import lector


def resumen() -> str:
    """Arma el resumen de la corrida leyendo las salidas del ETL."""
    salida = etl_optica.CARPETA_SALIDA
    registros = len(lector.leer_registros(etl_optica.ARCHIVO_ENTRADA))
    conexion = sqlite3.connect(salida / "optica_limpia.db")
    try:
        clientes = conexion.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
        visitas = conexion.execute("SELECT COUNT(*) FROM recetas").fetchone()[0]
    finally:
        conexion.close()
    with open(salida / "revisar_manual.csv", encoding="utf-8-sig", newline="") as archivo:
        motivos = Counter(fila["motivo"] for fila in csv.DictReader(archivo))

    lineas = [
        "",
        "RESUMEN DE LA DEMO",
        "------------------",
        f"Registros leídos de la planilla:  {registros}",
        f"Clientes únicos:                  {clientes}",
        f"Duplicados fusionados:            {registros - clientes}",
        f"Visitas (recetas):                {visitas}",
        f"Casos en revisar_manual.csv:      {sum(motivos.values())}",
    ]
    for motivo, cantidad in motivos.most_common():
        lineas.append(f"    {motivo:28s} {cantidad:4d}")
    lineas.append(f"\nSalidas en {salida}")
    return "\n".join(lineas)


def main() -> int:
    """Genera los datos si hace falta, corre el ETL e imprime el resumen."""
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    argumentos.add_argument("--regenerar", action="store_true",
                            help="vuelve a generar datos_ejemplo/ antes de correr")
    if argumentos.parse_args().regenerar or not etl_optica.ARCHIVO_ENTRADA.exists():
        generar_datos_ejemplo.generar()

    codigo = etl_optica.main([])
    if codigo == 0:
        print(resumen())
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
