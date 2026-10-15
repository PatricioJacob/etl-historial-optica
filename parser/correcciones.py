# -*- coding: utf-8 -*-
"""
Ciclo de corrección con intervención humana.

Lee ``correcciones_manuales.csv`` y lo aplica ENCIMA de lo que parseó el
parser. Es el tercer input del ETL, y es opcional: si el archivo no existe, la
corrida sigue sin quejarse.

POR QUÉ ASÍ Y NO EDITANDO LA BASE
---------------------------------
El ETL reconstruye ``optica_limpia.db`` desde cero en cada corrida. Si los
casos difíciles se cargaran a mano en el ``.db``, la siguiente corrida los
borraría. Para no perderlos habría que dejar de correr el script, o sea
congelar el parser en su primera versión y no poder mejorarlo nunca.

Con este esquema se puede re-correr las veces que haga falta y el resultado
sigue siendo reproducible.

REGLA DE APLICACIÓN
-------------------
Una celda vacía en el CSV no pisa nada. Una celda con valor manda. Las recetas
tocadas quedan con ``origen = manual``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import normalizador
from .extractor import Receta

_log = logging.getLogger(__name__)

#: Columna obligatoria del archivo de correcciones: es la clave de enganche.
COLUMNA_CLAVE: str = "id_bloque"

#: Columnas de ``recetas`` que se pueden corregir a mano.
#:
#: Se excluyen a propósito ``id_bloque`` (es la clave), ``texto_original`` (es
#: la evidencia: si se pudiera editar, se perdería la trazabilidad contra el
#: dato original) y ``origen`` (lo fija el ETL, no la persona).
COLUMNAS_CORREGIBLES: tuple[str, ...] = (
    "fecha",
    "tipo_registro",
    "od_lejos_esf",
    "od_lejos_cil",
    "od_lejos_eje",
    "oi_lejos_esf",
    "oi_lejos_cil",
    "oi_lejos_eje",
    "adicion",
    "od_cerca_esf",
    "od_cerca_cil",
    "od_cerca_eje",
    "oi_cerca_esf",
    "oi_cerca_cil",
    "oi_cerca_eje",
    "lc_od_esf",
    "lc_od_cil",
    "lc_od_eje",
    "lc_oi_esf",
    "lc_oi_cil",
    "lc_oi_eje",
    "lc_prescriptor_vigente",
    "lc_med_od_esf",
    "lc_med_od_cil",
    "lc_med_od_eje",
    "lc_med_oi_esf",
    "lc_med_oi_cil",
    "lc_med_oi_eje",
    "lc_cont_od_esf",
    "lc_cont_od_cil",
    "lc_cont_od_eje",
    "lc_cont_oi_esf",
    "lc_cont_oi_cil",
    "lc_cont_oi_eje",
    "lc_od_potencia_lente",
    "lc_od_nivel",
    "lc_oi_potencia_lente",
    "lc_oi_nivel",
    "lc_od_curva_base",
    "lc_oi_curva_base",
    "lc_od_diametro",
    "lc_oi_diametro",
    "lc_cantidad",
    "lc_marca",
    "lc_tipo",
    "di",
    "di_lejos",
    "di_cerca",
    "altura",
    "tipo_lente",
    "modelo_anteojo",
    "codigo_modelo",
    "tratamientos",
    "doctor",
    "observaciones",
)

#: Campos que se guardan como fecha y hay que convertir al aplicarlos.
CAMPOS_FECHA: frozenset[str] = frozenset({"fecha"})

#: Contenido del archivo de ejemplo que se genera cuando no existe.
PLANTILLA_EJEMPLO: str = (
    "# correcciones_manuales.csv -- INPUT OPCIONAL DEL ETL\n"
    "#\n"
    "# COMO SE USA\n"
    "#   1. Abrir salida/revisar_manual.csv y elegir un caso a resolver.\n"
    "#   2. Copiar su id_bloque a la primera columna de este archivo.\n"
    "#   3. Completar SOLO las columnas cuyo valor se pudo determinar leyendo\n"
    "#      la columna texto_original. Las demas se dejan vacias.\n"
    "#   4. Volver a correr etl_optica.py. La base se reconstruye entera y las\n"
    "#      correcciones se aplican encima.\n"
    "#\n"
    "# REGLAS\n"
    "#   * Una celda vacia NO pisa lo que parseo el script.\n"
    "#   * Una celda con valor manda, y la receta queda con origen = manual.\n"
    "#   * Las lineas que empiezan con # se ignoran.\n"
    "#   * NUNCA se edita optica_limpia.db a mano: se borra en cada corrida.\n"
    "#\n"
    "# EJEMPLO (borrar el # inicial para activarlo):\n"
    "# a1b2c3d4e5f6,15/03/2018,VENTA,-2.00,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
    "#\n"
)


@dataclass
class ResultadoCorrecciones:
    """Métricas de la aplicación de correcciones manuales.

    Attributes:
        aplicadas: Cuántas recetas se modificaron.
        huerfanas: ``id_bloque`` del archivo que no existen en el crudo.
        celdas_aplicadas: Cuántas celdas concretas se pisaron.
        columnas_desconocidas: Columnas del CSV que no son corregibles.
    """

    aplicadas: int = 0
    huerfanas: list[str] = field(default_factory=list)
    celdas_aplicadas: int = 0
    columnas_desconocidas: set[str] = field(default_factory=set)


def generar_plantilla(ruta: Path) -> None:
    """Crea ``correcciones_manuales.csv`` con cabecera y ejemplo comentado.

    Sólo se crea si el archivo no existe. Nunca se sobrescribe uno que ya
    tenga correcciones cargadas.

    Args:
        ruta: Dónde crear el archivo.
    """
    if ruta.exists():
        return

    cabecera = ",".join((COLUMNA_CLAVE,) + COLUMNAS_CORREGIBLES)
    contenido = PLANTILLA_EJEMPLO + cabecera + "\n"
    ruta.write_text(contenido, encoding="utf-8-sig")
    _log.info("Se generó la plantilla vacía %s", ruta.name)


def cargar(ruta: Path) -> dict[str, dict[str, str]]:
    """Lee el archivo de correcciones manuales.

    Args:
        ruta: Ruta a ``correcciones_manuales.csv``.

    Returns:
        Diccionario ``{id_bloque: {columna: valor}}`` con sólo las celdas no
        vacías. Devuelve un diccionario vacío si el archivo no existe.
    """
    if not ruta.exists():
        _log.info(
            "No hay archivo de correcciones manuales (%s). Es opcional; se "
            "continúa.",
            ruta.name,
        )
        return {}

    correcciones: dict[str, dict[str, str]] = {}

    with ruta.open("r", encoding="utf-8-sig", newline="") as archivo:
        # Se descartan las líneas de comentario antes de pasárselas al lector.
        utiles = (linea for linea in archivo if not linea.lstrip().startswith("#"))
        lector = csv.DictReader(utiles)

        if lector.fieldnames is None or COLUMNA_CLAVE not in lector.fieldnames:
            _log.error(
                "El archivo %s no tiene la columna obligatoria %r. Se ignora.",
                ruta.name,
                COLUMNA_CLAVE,
            )
            return {}

        for fila in lector:
            clave = (fila.get(COLUMNA_CLAVE) or "").strip()
            if not clave:
                continue

            valores = {
                columna: valor.strip()
                for columna, valor in fila.items()
                if columna and columna != COLUMNA_CLAVE and valor and valor.strip()
            }
            if valores:
                correcciones.setdefault(clave, {}).update(valores)

    _log.info(
        "Se cargaron correcciones manuales para %d bloques desde %s",
        len(correcciones),
        ruta.name,
    )
    return correcciones


def aplicar(
    recetas_por_bloque: dict[str, Receta],
    correcciones: dict[str, dict[str, str]],
) -> ResultadoCorrecciones:
    """Aplica las correcciones encima de las recetas parseadas.

    Args:
        recetas_por_bloque: Recetas indexadas por ``id_bloque``.
        correcciones: Salida de :func:`cargar`.

    Returns:
        Las métricas de lo que se aplicó.
    """
    resultado = ResultadoCorrecciones()

    for id_bloque, valores in correcciones.items():
        receta = recetas_por_bloque.get(id_bloque)

        if receta is None:
            # No se revienta: probablemente cambió el export de Moebius.
            resultado.huerfanas.append(id_bloque)
            _log.warning(
                "Corrección huérfana: el id_bloque %s no existe en el archivo "
                "crudo. Se ignora y se sigue.",
                id_bloque,
            )
            continue

        toco_algo = False

        for columna, valor in valores.items():
            if columna not in COLUMNAS_CORREGIBLES:
                resultado.columnas_desconocidas.add(columna)
                _log.warning(
                    "La columna %r del archivo de correcciones no es "
                    "corregible. Se ignora para el bloque %s.",
                    columna,
                    id_bloque,
                )
                continue

            if columna in CAMPOS_FECHA:
                convertido = normalizador.normalizar_fecha(valor)
                if convertido is None:
                    _log.warning(
                        "La fecha %r del bloque %s no es válida. Se ignora.",
                        valor,
                        id_bloque,
                    )
                    continue
                setattr(receta, columna, convertido)
            else:
                setattr(receta, columna, valor)

            resultado.celdas_aplicadas += 1
            toco_algo = True

        if toco_algo:
            # Trazabilidad: si el dato lo completamos nosotros a ojo, la
            # óptica tiene que poder saberlo.
            receta.origen = "manual"
            resultado.aplicadas += 1

    _log.info(
        "Correcciones manuales: %d recetas modificadas, %d celdas aplicadas, "
        "%d huérfanas",
        resultado.aplicadas,
        resultado.celdas_aplicadas,
        len(resultado.huerfanas),
    )
    return resultado
