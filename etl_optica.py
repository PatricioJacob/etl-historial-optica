# -*- coding: utf-8 -*-
"""
ETL de la base histórica de la óptica.

Convierte el export crudo de Moebius (``planilla_notas.csv``, con 20 años de
historial atrapado en un campo de texto libre) en una base limpia,
estructurada, deduplicada y auditable.

ARQUITECTURA
------------
    extraer()      lee el CSV crudo y lo parsea a clientes y recetas
        v
    transformar()  deduplica y aplica las correcciones manuales
        v
    cargar()       escribe SQLite, los tres CSV y el reporte de calidad

IDEMPOTENCIA
------------
La base es una función pura de ``planilla_notas.csv`` +
``correcciones_manuales.csv`` + las reglas del código. Correrlo dos veces sobre
los mismos inputs da exactamente el mismo resultado: el ``.db`` se borra y se
reconstruye entero en cada corrida, y los identificadores no dependen del orden
de lectura.

USO
---
    python etl_optica.py
    python etl_optica.py --entrada otra_planilla.csv --salida otra_salida

Sin argumentos lee los datos de ejemplo de ``datos_ejemplo/``.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from parser import correcciones as mod_correcciones
from parser import deduplicador, extractor, lector, segmentador
from parser import normalizador
from parser.deduplicador import Cliente
from parser.extractor import Receta
from parser.motivos import ORDEN_SEVERIDAD, Motivo, severidad

# ===========================================================================
# ÚNICO PUNTO DE CONFIGURACIÓN
# ===========================================================================

#: Carpeta donde vive este script. Todas las rutas se resuelven relativas a
#: acá, para que el ETL corra igual desde cualquier directorio de trabajo.
RAIZ = Path(__file__).resolve().parent

#: Carpeta con los datos de ejemplo inventados que trae el repositorio.
CARPETA_DATOS = RAIZ / "datos_ejemplo"

#: Archivo crudo exportado de Moebius. Es el input principal.
ARCHIVO_ENTRADA = CARPETA_DATOS / "planilla_notas.csv"

#: Correcciones cargadas a mano por nosotros. Es opcional: si no existe, el
#: ETL corre igual.
ARCHIVO_CORRECCIONES = CARPETA_DATOS / "correcciones_manuales.csv"

#: Carpeta donde se escriben todas las salidas.
CARPETA_SALIDA = RAIZ / "salida"

# Las tres rutas se pueden cambiar al correr, sin tocar el código:
#     python etl_optica.py --entrada ... --correcciones ... --salida ...

# --- Fin de la configuración. Nada más para tocar. -------------------------

#: Encoding de los CSV de salida. UTF-8 CON BOM, porque los van a abrir con
#: Excel en Windows y sin BOM los acentos salen rotos.
ENCODING_SALIDA = "utf-8-sig"

#: Texto con el que se representa un dato ausente en los CSV.
MARCA_AUSENTE = normalizador.MARCA_AUSENTE

_log = logging.getLogger("etl_optica")


# ===========================================================================
# ESQUEMA DE LA BASE
# ===========================================================================

#: Columnas de la tabla ``recetas``, en orden. Se usa tanto para crear la tabla
#: como para exportar el CSV, así no puede haber desfasaje entre las dos.
COLUMNAS_RECETAS: tuple[str, ...] = (
    "id_receta",
    "id_bloque",
    "id_cliente",
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
    # Lentes de contacto · prescripción VIGENTE (la que muestra la aplicación)
    "lc_od_esf",
    "lc_od_cil",
    "lc_od_eje",
    "lc_oi_esf",
    "lc_oi_cil",
    "lc_oi_eje",
    "lc_prescriptor_vigente",
    # Lentes de contacto · lo que indicó el MÉDICO
    "lc_med_od_esf",
    "lc_med_od_cil",
    "lc_med_od_eje",
    "lc_med_oi_esf",
    "lc_med_oi_cil",
    "lc_med_oi_eje",
    # Lentes de contacto · lo que adaptó el CONTACTÓLOGO
    "lc_cont_od_esf",
    "lc_cont_od_cil",
    "lc_cont_od_eje",
    "lc_cont_oi_esf",
    "lc_cont_oi_cil",
    "lc_cont_oi_eje",
    # Lentes de contacto · el LENTE que se entregó
    "lc_od_potencia_lente",
    "lc_od_nivel",
    "lc_oi_potencia_lente",
    "lc_oi_nivel",
    # Lentes de contacto · datos físicos
    "lc_od_curva_base",
    "lc_oi_curva_base",
    "lc_od_diametro",
    "lc_oi_diametro",
    "lc_marca",
    "lc_tipo",
    "lc_cantidad",
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
    "origen",
    "texto_original",
)

#: Columnas de la tabla ``clientes``, en orden.
COLUMNAS_CLIENTES: tuple[str, ...] = (
    "id_cliente",
    "apellido",
    "nombre",
    "nombre_completo",
    "documento",
    "cantidad_visitas",
    "primera_visita",
    "ultima_visita",
    "posible_registro_basura",
    "requiere_revision",
)

#: Columnas de ``revisar_manual.csv``.
COLUMNAS_REVISION: tuple[str, ...] = (
    "id_bloque",
    "apellido",
    "nombre",
    "severidad",
    "motivo",
    "detalle",
    "texto_original",
)

#: Columnas de ``lentes_contacto.csv``, en el orden que pidió la óptica.
COLUMNAS_LENTES_CONTACTO: tuple[str, ...] = (
    "id_cliente",
    "apellido",
    "nombre",
    "fecha",
    "id_bloque",
    "prescriptor",
    "orden_prescriptor",
    "es_la_que_se_muestra",
    "od_esf",
    "od_cil",
    "od_eje",
    "oi_esf",
    "oi_cil",
    "oi_eje",
    "signo_cil_distinto",
    "od_potencia_lente",
    "od_nivel",
    "oi_potencia_lente",
    "oi_nivel",
    "od_curva_base",
    "oi_curva_base",
    "od_diametro",
    "oi_diametro",
    "marca",
    "tipo",
    "cantidad",
    "observaciones",
    "texto_original",
)

#: Valor de ``tipo_lente`` que identifica una visita de lentes de contacto.
TIPO_LENTES_CONTACTO = "LENTES DE CONTACTO"

ESQUEMA_SQL = """
DROP TABLE IF EXISTS recetas;
DROP TABLE IF EXISTS clientes;

CREATE TABLE clientes (
    id_cliente              INTEGER PRIMARY KEY,
    apellido                TEXT NOT NULL,
    nombre                  TEXT NOT NULL,
    nombre_completo         TEXT NOT NULL,
    documento               TEXT,
    cantidad_visitas        INTEGER NOT NULL DEFAULT 0,
    primera_visita          TEXT,
    ultima_visita           TEXT,
    posible_registro_basura INTEGER NOT NULL DEFAULT 0,
    requiere_revision       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE recetas (
    id_receta      INTEGER PRIMARY KEY,
    id_bloque      TEXT NOT NULL,
    id_cliente     INTEGER NOT NULL REFERENCES clientes(id_cliente),
    fecha          TEXT,
    tipo_registro  TEXT,
    od_lejos_esf   TEXT,
    od_lejos_cil   TEXT,
    od_lejos_eje   TEXT,
    oi_lejos_esf   TEXT,
    oi_lejos_cil   TEXT,
    oi_lejos_eje   TEXT,
    adicion        TEXT,
    od_cerca_esf   TEXT,
    od_cerca_cil   TEXT,
    od_cerca_eje   TEXT,
    oi_cerca_esf   TEXT,
    oi_cerca_cil   TEXT,
    oi_cerca_eje   TEXT,
    -- Lentes de contacto · prescripción VIGENTE (la que muestra la app).
    -- Cuál de las dos la llena lo decide extractor.PRESCRIPCION_VIGENTE.
    lc_od_esf      TEXT,
    lc_od_cil      TEXT,
    lc_od_eje      TEXT,
    lc_oi_esf      TEXT,
    lc_oi_cil      TEXT,
    lc_oi_eje      TEXT,
    -- De dónde salió el número que está en las columnas vigentes:
    -- MEDICO, CONTACTOLOGO o SIN_ESPECIFICAR.
    lc_prescriptor_vigente TEXT,
    -- Lentes de contacto · lo que indicó el MÉDICO (RP. MEDICO:)
    lc_med_od_esf  TEXT,
    lc_med_od_cil  TEXT,
    lc_med_od_eje  TEXT,
    lc_med_oi_esf  TEXT,
    lc_med_oi_cil  TEXT,
    lc_med_oi_eje  TEXT,
    -- Lentes de contacto · lo que adaptó el CONTACTÓLOGO (RP. CONTACTOLOGO:)
    lc_cont_od_esf TEXT,
    lc_cont_od_cil TEXT,
    lc_cont_od_eje TEXT,
    lc_cont_oi_esf TEXT,
    lc_cont_oi_cil TEXT,
    lc_cont_oi_eje TEXT,
    -- Lentes de contacto · el LENTE que se entregó. Sale del renglón de la
    -- sección LENTES DE CONTACTO. La potencia no es la esfera de la receta; el
    -- nivel (HIGH, MED, LOW, MID) va tal como está escrito.
    lc_od_potencia_lente TEXT,
    lc_od_nivel          TEXT,
    lc_oi_potencia_lente TEXT,
    lc_oi_nivel          TEXT,
    -- Lentes de contacto · datos físicos de la lente
    -- Curva base y diámetro van por ojo. Un valor escrito sin ojo, o con AO,
    -- se copia en los dos.
    lc_od_curva_base TEXT,
    lc_oi_curva_base TEXT,
    lc_od_diametro   TEXT,
    lc_oi_diametro   TEXT,
    lc_marca       TEXT,
    lc_tipo        TEXT,
    -- Cantidad entregada, tal como está escrita: "1 CAJA", "2 PARES".
    lc_cantidad    TEXT,
    di             TEXT,
    di_lejos       TEXT,
    di_cerca       TEXT,
    altura         TEXT,
    tipo_lente     TEXT,
    modelo_anteojo TEXT,
    codigo_modelo  TEXT,
    tratamientos   TEXT,
    doctor         TEXT,
    observaciones  TEXT,
    origen         TEXT NOT NULL DEFAULT 'parseado',
    texto_original TEXT NOT NULL
);

-- Índices sobre los campos por los que busca la app de la Fase 2.
CREATE INDEX idx_clientes_apellido        ON clientes(apellido);
CREATE INDEX idx_clientes_nombre_completo ON clientes(nombre_completo);
CREATE INDEX idx_recetas_cliente          ON recetas(id_cliente);
CREATE INDEX idx_recetas_fecha            ON recetas(fecha);

-- El id_bloque identifica un bloque de texto crudo y no puede repetirse:
-- es la clave con la que se enganchan las correcciones manuales.
CREATE UNIQUE INDEX idx_recetas_id_bloque ON recetas(id_bloque);
"""


# ===========================================================================
# ESTRUCTURAS DE TRABAJO
# ===========================================================================


@dataclass
class FilaRevision:
    """Una fila de ``revisar_manual.csv``."""

    id_bloque: str
    apellido: str
    nombre: str
    severidad: str
    motivo: str
    detalle: str
    texto_original: str


@dataclass
class Metricas:
    """Contadores del pipeline, para el reporte de calidad."""

    registros_entrada: int = 0
    clientes_unicos: int = 0
    clientes_fusionados: int = 0
    visitas_fusionadas: int = 0
    conflictos_documento: int = 0
    recetas_totales: int = 0
    registros_basura: int = 0
    clientes_requieren_revision: int = 0
    recetas_por_anio: Counter[int] = field(default_factory=Counter)
    recetas_por_tipo: Counter[str] = field(default_factory=Counter)
    recetas_por_origen: Counter[str] = field(default_factory=Counter)
    motivos: Counter[str] = field(default_factory=Counter)
    ejemplos_no_interpretados: list[str] = field(default_factory=list)
    correcciones_aplicadas: int = 0
    correcciones_celdas: int = 0
    correcciones_huerfanas: int = 0
    huerfanas_ids: list[str] = field(default_factory=list)
    encoding_detectado: str = ""
    duracion_segundos: float = 0.0
    # Recuentos de lentes_contacto.csv, para el reporte de calidad.
    lc_filas: int = 0
    lc_visitas: int = 0
    lc_por_prescriptor: Counter[str] = field(default_factory=Counter)
    lc_niveles: Counter[str] = field(default_factory=Counter)
    lc_filas_signo_distinto: int = 0
    lc_visitas_signo_distinto: int = 0


# ===========================================================================
# 1. EXTRAER
# ===========================================================================


def extraer(
    ruta_entrada: Path, metricas: Metricas
) -> list[tuple[str, str, str | None, list[Receta], list[tuple[Motivo, str]]]]:
    """Lee el archivo crudo y lo convierte en registros con sus recetas.

    Args:
        ruta_entrada: Ruta a ``planilla_notas.csv``.
        metricas: Contadores a completar.

    Returns:
        Lista de tuplas ``(apellido, nombre, documento, recetas, incidencias)``,
        una por registro crudo del archivo.
    """
    _log.info("=" * 70)
    _log.info("FASE 1 - EXTRACCIÓN")
    _log.info("=" * 70)

    encoding = lector.detectar_encoding(ruta_entrada)
    metricas.encoding_detectado = encoding

    registros_crudos = lector.leer_registros(ruta_entrada, encoding)
    metricas.registros_entrada = len(registros_crudos)

    salida: list[
        tuple[str, str, str | None, list[Receta], list[tuple[Motivo, str]]]
    ] = []

    for indice, crudo in enumerate(registros_crudos, start=1):
        if indice % 5000 == 0:
            _log.info("  procesados %d / %d registros", indice, len(registros_crudos))

        incidencias_registro: list[tuple[Motivo, str]] = []
        documento = normalizador.normalizar_documento(crudo.documento)

        # Un documento de menos de 6 dígitos es imposible como DNI argentino.
        # Se trató como ausente, pero se deja constancia.
        crudo_doc = crudo.documento.strip()
        if documento is None and crudo_doc and crudo_doc.strip("0"):
            incidencias_registro.append(
                (
                    Motivo.DOCUMENTO_IMPLAUSIBLE,
                    f"documento {crudo_doc!r} tiene menos de 6 dígitos",
                )
            )

        recetas: list[Receta] = []

        # Tolerancia a fallos absoluta: un cliente malformado nunca aborta la
        # corrida. Se registra el problema y se sigue con el siguiente.
        try:
            visitas = segmentador.segmentar(crudo.lineas_notas)
            for visita in visitas:
                recetas.append(
                    extractor.extraer(visita, crudo.apellido, crudo.nombre)
                )
        except Exception as error:  # noqa: BLE001 - es deliberado
            _log.exception(
                "Error procesando el registro de la línea %d (%s %s): %s. "
                "Se continúa con el siguiente.",
                crudo.numero_linea,
                crudo.apellido,
                crudo.nombre,
                error,
            )
            incidencias_registro.append(
                (Motivo.BLOQUE_SIN_ESTRUCTURA, f"error de parseo: {error}")
            )

        salida.append(
            (crudo.apellido, crudo.nombre, documento, recetas, incidencias_registro)
        )

    _log.info(
        "Extracción terminada: %d registros, %d recetas en bruto",
        len(salida),
        sum(len(r[3]) for r in salida),
    )
    return salida


# ===========================================================================
# 2. TRANSFORMAR
# ===========================================================================


def transformar(
    registros: list[tuple[str, str, str | None, list[Receta], list[tuple[Motivo, str]]]],
    ruta_correcciones: Path,
    metricas: Metricas,
) -> list[Cliente]:
    """Deduplica los clientes y aplica las correcciones manuales.

    Args:
        registros: Salida de :func:`extraer`.
        ruta_correcciones: Ruta a ``correcciones_manuales.csv``.
        metricas: Contadores a completar.

    Returns:
        Los clientes unificados, ordenados alfabéticamente.
    """
    _log.info("=" * 70)
    _log.info("FASE 2 - TRANSFORMACIÓN")
    _log.info("=" * 70)

    resultado = deduplicador.deduplicar(registros)
    metricas.clientes_unicos = len(resultado.clientes)
    metricas.clientes_fusionados = resultado.clientes_fusionados
    metricas.visitas_fusionadas = resultado.visitas_fusionadas
    metricas.conflictos_documento = resultado.conflictos_documento

    # --- Correcciones manuales ---------------------------------------------
    indice_bloques: dict[str, Receta] = {}
    for cliente in resultado.clientes:
        for receta in cliente.recetas:
            indice_bloques[receta.id_bloque] = receta

    datos_correcciones = mod_correcciones.cargar(ruta_correcciones)
    aplicacion = mod_correcciones.aplicar(indice_bloques, datos_correcciones)

    metricas.correcciones_aplicadas = aplicacion.aplicadas
    metricas.correcciones_celdas = aplicacion.celdas_aplicadas
    metricas.correcciones_huerfanas = len(aplicacion.huerfanas)

    # Las correcciones huérfanas se anotan en el primer cliente sólo para que
    # aparezcan en revisar_manual.csv; no pertenecen a ningún cliente real.
    for id_bloque in aplicacion.huerfanas:
        _log.warning("Corrección huérfana sin destino: %s", id_bloque)

    metricas.huerfanas_ids = list(aplicacion.huerfanas)

    return resultado.clientes


# ===========================================================================
# 3. CARGAR
# ===========================================================================


def _valor_csv(valor: object) -> str:
    """Formatea un valor para el CSV, usando ``N/A`` para los ausentes.

    Args:
        valor: Valor a formatear.

    Returns:
        El valor como texto, o ``N/A`` si es ``None`` o cadena vacía.
    """
    if valor is None or valor == "":
        return MARCA_AUSENTE
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _fila_receta(receta: Receta, id_receta: int, id_cliente: int) -> dict[str, object]:
    """Arma el diccionario de una receta con las claves del esquema.

    Args:
        receta: Receta a volcar.
        id_receta: Identificador secuencial.
        id_cliente: Cliente al que pertenece.

    Returns:
        Diccionario con una clave por cada columna de ``recetas``.
    """
    fila: dict[str, object] = {
        "id_receta": id_receta,
        "id_bloque": receta.id_bloque,
        "id_cliente": id_cliente,
        "fecha": normalizador.formatear_fecha(receta.fecha),
    }
    for columna in COLUMNAS_RECETAS:
        if columna in fila:
            continue
        fila[columna] = getattr(receta, columna, None)
    return fila


def _crear_base(ruta_db: Path) -> sqlite3.Connection:
    """Crea la base desde cero, borrando la anterior si existía.

    POR QUÉ SE BORRA: el ETL es idempotente. La base es una función pura de los
    inputs, no un acumulador. Si se conservara la anterior, dos corridas darían
    resultados distintos y se perdería la reproducibilidad.

    Args:
        ruta_db: Ruta al archivo ``.db``.

    Returns:
        Conexión abierta a la base recién creada.
    """
    if ruta_db.exists():
        ruta_db.unlink()
        _log.info("Base anterior eliminada: se reconstruye desde cero")

    conexion = sqlite3.connect(ruta_db)
    conexion.executescript(ESQUEMA_SQL)
    conexion.commit()
    return conexion


def cargar(
    clientes: list[Cliente],
    carpeta_salida: Path,
    metricas: Metricas,
) -> list[FilaRevision]:
    """Escribe la base SQLite y los CSV de salida.

    Args:
        clientes: Clientes ya deduplicados y corregidos.
        carpeta_salida: Carpeta donde escribir.
        metricas: Contadores a completar.

    Returns:
        Las filas de ``revisar_manual.csv``, ya ordenadas.
    """
    _log.info("=" * 70)
    _log.info("FASE 3 - CARGA")
    _log.info("=" * 70)

    carpeta_salida.mkdir(parents=True, exist_ok=True)
    conexion = _crear_base(carpeta_salida / "optica_limpia.db")

    filas_clientes: list[dict[str, object]] = []
    filas_recetas: list[dict[str, object]] = []
    filas_revision: list[FilaRevision] = []
    id_receta = 0
    bloques_vistos: set[str] = set()

    for cliente in clientes:
        if cliente.posible_registro_basura:
            metricas.registros_basura += 1

        # Un cliente requiere revisión si alguna de sus recetas tiene una
        # incidencia de severidad alta.
        for receta in cliente.recetas:
            for motivo, _ in receta.incidencias:
                if severidad(motivo) == "alta":
                    cliente.requiere_revision = 1

        if cliente.requiere_revision:
            metricas.clientes_requieren_revision += 1

        filas_clientes.append(
            {
                "id_cliente": cliente.id_cliente,
                "apellido": cliente.apellido,
                "nombre": cliente.nombre,
                "nombre_completo": cliente.nombre_completo,
                "documento": cliente.documento,
                "cantidad_visitas": len(cliente.recetas),
                "primera_visita": normalizador.formatear_fecha(cliente.primera_visita),
                "ultima_visita": normalizador.formatear_fecha(cliente.ultima_visita),
                "posible_registro_basura": cliente.posible_registro_basura,
                "requiere_revision": cliente.requiere_revision,
            }
        )

        # --- Incidencias a nivel cliente -----------------------------------
        for motivo, detalle in cliente.incidencias:
            metricas.motivos[str(motivo)] += 1
            filas_revision.append(
                FilaRevision(
                    id_bloque=cliente.recetas[0].id_bloque if cliente.recetas else "",
                    apellido=cliente.apellido,
                    nombre=cliente.nombre,
                    severidad=severidad(motivo),
                    motivo=str(motivo),
                    detalle=detalle,
                    texto_original=(
                        cliente.recetas[0].texto_original if cliente.recetas else ""
                    ),
                )
            )

        # --- Recetas --------------------------------------------------------
        for receta in cliente.recetas:
            if receta.id_bloque in bloques_vistos:
                # Dos bloques con el mismo hash son, por construcción, texto
                # idéntico del mismo cliente. El deduplicador ya debería
                # haberlos fusionado; si llega uno acá se lo salta para no
                # violar el índice único, y se deja constancia.
                _log.warning(
                    "id_bloque repetido %s en %s: se omite la segunda copia",
                    receta.id_bloque,
                    cliente.nombre_completo,
                )
                continue
            bloques_vistos.add(receta.id_bloque)

            id_receta += 1
            filas_recetas.append(
                _fila_receta(receta, id_receta, cliente.id_cliente)
            )

            metricas.recetas_por_tipo[receta.tipo_registro or "SIN TIPO"] += 1
            metricas.recetas_por_origen[receta.origen] += 1
            if receta.fecha is not None:
                metricas.recetas_por_anio[receta.fecha.year] += 1

            for motivo, detalle in receta.incidencias:
                metricas.motivos[str(motivo)] += 1
                filas_revision.append(
                    FilaRevision(
                        id_bloque=receta.id_bloque,
                        apellido=cliente.apellido,
                        nombre=cliente.nombre,
                        severidad=severidad(motivo),
                        motivo=str(motivo),
                        detalle=detalle,
                        texto_original=receta.texto_original,
                    )
                )
                if (
                    motivo is Motivo.VALOR_NO_PARSEABLE
                    and len(metricas.ejemplos_no_interpretados) < 15
                ):
                    metricas.ejemplos_no_interpretados.append(detalle)

    metricas.recetas_totales = len(filas_recetas)

    # --- Correcciones huérfanas: también van a revisar_manual --------------
    for id_bloque in metricas.huerfanas_ids:
        filas_revision.append(
            FilaRevision(
                id_bloque=id_bloque,
                apellido="",
                nombre="",
                severidad=severidad(Motivo.CORRECCION_HUERFANA),
                motivo=str(Motivo.CORRECCION_HUERFANA),
                detalle=(
                    "el id_bloque del archivo de correcciones no existe en el "
                    "crudo; probablemente cambió el export de Moebius"
                ),
                texto_original="",
            )
        )
        metricas.motivos[str(Motivo.CORRECCION_HUERFANA)] += 1

    # --- Escritura en SQLite -----------------------------------------------
    conexion.executemany(
        f"INSERT INTO clientes ({', '.join(COLUMNAS_CLIENTES)}) "
        f"VALUES ({', '.join(':' + c for c in COLUMNAS_CLIENTES)})",
        filas_clientes,
    )
    conexion.executemany(
        f"INSERT INTO recetas ({', '.join(COLUMNAS_RECETAS)}) "
        f"VALUES ({', '.join(':' + c for c in COLUMNAS_RECETAS)})",
        filas_recetas,
    )
    conexion.commit()
    conexion.close()
    _log.info(
        "SQLite escrito: %d clientes, %d recetas",
        len(filas_clientes),
        len(filas_recetas),
    )

    # --- CSV de clientes ----------------------------------------------------
    _escribir_csv(
        carpeta_salida / "clientes.csv",
        COLUMNAS_CLIENTES,
        (
            {c: _valor_csv(fila[c]) for c in COLUMNAS_CLIENTES}
            for fila in filas_clientes
        ),
    )

    # --- CSV de recetas -----------------------------------------------------
    #
    # Se repiten las columnas del cliente al inicio para que el archivo se lea
    # sin hacer joins: la empleada lo abre con Excel y filtra por apellido.
    columnas_cliente_en_recetas = (
        "apellido",
        "nombre",
        "documento",
        "nombre_completo",
    )
    columnas_recetas_csv = (
        ("id_receta", "id_bloque", "id_cliente")
        + columnas_cliente_en_recetas
        + tuple(
            c
            for c in COLUMNAS_RECETAS
            if c not in ("id_receta", "id_bloque", "id_cliente")
        )
    )
    clientes_por_id = {c.id_cliente: c for c in clientes}

    def _filas_recetas_csv():
        for fila in filas_recetas:
            cliente = clientes_por_id[fila["id_cliente"]]
            enriquecida = dict(fila)
            enriquecida["apellido"] = cliente.apellido
            enriquecida["nombre"] = cliente.nombre
            enriquecida["documento"] = cliente.documento
            enriquecida["nombre_completo"] = cliente.nombre_completo
            yield {c: _valor_csv(enriquecida.get(c)) for c in columnas_recetas_csv}

    _escribir_csv(
        carpeta_salida / "recetas.csv", columnas_recetas_csv, _filas_recetas_csv()
    )

    # --- CSV de revisión manual ---------------------------------------------
    #
    # Ordenado por severidad y después por frecuencia del motivo: lo urgente
    # queda arriba y el ruido conocido abajo.
    frecuencias = metricas.motivos
    filas_revision.sort(
        key=lambda f: (
            ORDEN_SEVERIDAD.get(f.severidad, 9),
            -frecuencias[f.motivo],
            f.motivo,
            f.apellido,
        )
    )
    _escribir_csv(
        carpeta_salida / "revisar_manual.csv",
        COLUMNAS_REVISION,
        (
            {
                "id_bloque": f.id_bloque,
                "apellido": f.apellido,
                "nombre": f.nombre,
                "severidad": f.severidad,
                "motivo": f.motivo,
                "detalle": f.detalle,
                "texto_original": f.texto_original,
            }
            for f in filas_revision
        ),
    )

    # --- CSV de lentes de contacto ------------------------------------------
    #
    # Se arma LEYENDO LA BASE recién escrita, no los objetos en memoria: así
    # queda garantizado que el archivo se puede reconstruir sólo desde
    # optica_limpia.db.
    filas_lc = exportar_lentes_contacto(
        carpeta_salida / "optica_limpia.db", carpeta_salida / "lentes_contacto.csv"
    )
    _contar_lentes_contacto(filas_lc, metricas)

    return filas_revision


#: Columnas de ``recetas`` que guardan algún dato de lentes de contacto. Una
#: visita con cualquiera de ellas cargada entra a ``lentes_contacto.csv``, sea
#: cual sea su ``tipo_lente``: hay visitas mixtas, con anteojos y lentes de
#: contacto en el mismo bloque, que están clasificadas como anteojos.
COLUMNAS_CON_DATO_DE_LC: tuple[str, ...] = tuple(
    columna
    for columna in COLUMNAS_RECETAS
    if columna.startswith("lc_")
)


def _tiene_prescripcion(visita: dict[str, object], prefijo: str) -> bool:
    """Indica si la visita trae alguna medida de ese prescriptor.

    Args:
        visita: Fila de ``recetas``.
        prefijo: ``"lc_med"`` o ``"lc_cont"``.

    Returns:
        ``True`` si hay esfera, cilindro o eje en alguno de los dos ojos.
    """
    return any(
        visita.get(f"{prefijo}_{ojo}_{campo}") not in (None, "")
        for ojo in ("od", "oi")
        for campo in ("esf", "cil", "eje")
    )


def _signo(valor: object) -> int:
    """Devuelve el signo de un cilindro: ``1``, ``-1`` o ``0`` si no hay.

    Args:
        valor: Cilindro normalizado (``"+0.75"``, ``"-1.25"``) o ``None``.

    Returns:
        El signo, o ``0`` para un valor ausente, nulo o ilegible.
    """
    try:
        numero = float(str(valor)) if valor not in (None, "") else 0.0
    except ValueError:
        return 0
    return (numero > 0) - (numero < 0)


def _signo_de_cilindro_distinto(visita: dict[str, object]) -> bool:
    """Indica si médico y contactólogo escribieron el cilindro con otro signo.

    Se compara ojo por ojo. No se transpone ni se corrige nada: el cilindro
    queda tal como lo escribió cada uno, y esto sólo lo señala.

    Args:
        visita: Fila de ``recetas``.

    Returns:
        ``True`` si en algún ojo los dos cilindros tienen signo opuesto.
    """
    for ojo in ("od", "oi"):
        medico = _signo(visita.get(f"lc_med_{ojo}_cil"))
        contactologo = _signo(visita.get(f"lc_cont_{ojo}_cil"))
        if medico and contactologo and medico != contactologo:
            return True
    return False


def _fecha_real(texto: object) -> date | None:
    """Convierte la fecha guardada como ``dd/mm/aaaa`` en una fecha real.

    Args:
        texto: Valor de la columna ``fecha``.

    Returns:
        La fecha, o ``None`` si está ausente o no se puede leer.
    """
    try:
        return datetime.strptime(str(texto), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def filas_lentes_contacto(visitas: list[dict[str, object]]) -> list[dict[str, object]]:
    """Arma las filas de ``lentes_contacto.csv``.

    Es una VISTA de exportación: no agrega nada al modelo y se arma sólo con
    columnas de la base (``recetas`` más el apellido y el nombre del cliente),
    así que se puede reconstruir desde ``optica_limpia.db``.

    Una fila por prescripción (visita × prescriptor):

    * una visita con receta del médico y del contactólogo da DOS filas;
    * una con un solo prescriptor da una;
    * una sin prescriptor (sólo datos del lente) da una, con
      ``prescriptor = SIN_ESPECIFICAR``.

    Los datos del lente (potencia, nivel, curva base, diámetro, marca, tipo,
    cantidad, observaciones) son de la visita y se repiten igual en sus filas.

    Orden: por cliente, por fecha real y, dentro de la visita, el contactólogo
    primero. Las visitas sin fecha van al final de cada cliente.

    Args:
        visitas: Filas de ``recetas`` con datos de lentes de contacto, cada
            una con ``apellido`` y ``nombre`` agregados.

    Returns:
        Lista de diccionarios con las claves de
        :data:`COLUMNAS_LENTES_CONTACTO`.
    """
    def clave(visita: dict[str, object]) -> tuple:
        fecha = _fecha_real(visita.get("fecha"))
        return (visita["id_cliente"], fecha is None, fecha or date.min, visita["id_bloque"])

    filas: list[dict[str, object]] = []
    for visita in sorted(visitas, key=clave):
        # (prescriptor, orden, prefijo de las columnas de donde salen las medidas)
        prescripciones: list[tuple[str, object, str]] = []
        # La fila del contactólogo también va cuando su prescripción no se
        # pudo leer: queda vacía y es la que se muestra, para que no parezca
        # que la vigente es la del médico.
        contactologo_sin_leer = (
            visita.get("lc_prescriptor_vigente") == extractor.PRESCRIPTOR_CONTACTOLOGO
        )
        if _tiene_prescripcion(visita, "lc_cont") or contactologo_sin_leer:
            prescripciones.append((extractor.PRESCRIPTOR_CONTACTOLOGO, 1, "lc_cont"))
        medico_sin_leer = (
            visita.get("lc_prescriptor_vigente") == extractor.PRESCRIPTOR_MEDICO
        )
        if _tiene_prescripcion(visita, "lc_med") or medico_sin_leer:
            prescripciones.append((extractor.PRESCRIPTOR_MEDICO, 2, "lc_med"))
        if not prescripciones:
            # Sin prescriptor identificado: las medidas, si las hay, son las
            # de la sección sin etiquetar, que ya están en las columnas vigentes.
            prescripciones.append((extractor.PRESCRIPTOR_SIN_ESPECIFICAR, None, "lc"))

        comunes: dict[str, object] = {
            "id_cliente": visita["id_cliente"],
            "apellido": visita.get("apellido"),
            "nombre": visita.get("nombre"),
            "fecha": visita.get("fecha"),
            "id_bloque": visita["id_bloque"],
            "signo_cil_distinto": "SI" if _signo_de_cilindro_distinto(visita) else "NO",
            "od_potencia_lente": visita.get("lc_od_potencia_lente"),
            "od_nivel": visita.get("lc_od_nivel"),
            "oi_potencia_lente": visita.get("lc_oi_potencia_lente"),
            "oi_nivel": visita.get("lc_oi_nivel"),
            "od_curva_base": visita.get("lc_od_curva_base"),
            "oi_curva_base": visita.get("lc_oi_curva_base"),
            "od_diametro": visita.get("lc_od_diametro"),
            "oi_diametro": visita.get("lc_oi_diametro"),
            "marca": visita.get("lc_marca"),
            "tipo": visita.get("lc_tipo"),
            "cantidad": visita.get("lc_cantidad"),
            "observaciones": visita.get("observaciones"),
            "texto_original": visita.get("texto_original"),
        }

        for posicion, (prescriptor, orden, prefijo) in enumerate(prescripciones):
            fila = dict(comunes)
            fila["prescriptor"] = prescriptor
            fila["orden_prescriptor"] = orden
            # La primera de la lista es la que muestra la regla "contactólogo
            # primero; si no hay, el médico".
            fila["es_la_que_se_muestra"] = "SI" if posicion == 0 else "NO"
            for ojo in ("od", "oi"):
                for campo in ("esf", "cil", "eje"):
                    fila[f"{ojo}_{campo}"] = visita.get(f"{prefijo}_{ojo}_{campo}")
            filas.append(fila)

    return filas


def leer_visitas_lc(ruta_db: Path) -> list[dict[str, object]]:
    """Lee de la base las visitas que tienen datos de lentes de contacto.

    Entra toda visita clasificada como lentes de contacto y también toda la
    que tenga cargada alguna columna ``lc_*``, sea cual sea su ``tipo_lente``.

    Args:
        ruta_db: Ruta a ``optica_limpia.db``.

    Returns:
        Una lista de diccionarios, uno por visita, con todas las columnas de
        ``recetas`` más ``apellido`` y ``nombre``.
    """
    con_dato = " OR ".join(
        f"(r.{columna} IS NOT NULL AND r.{columna} <> '')"
        for columna in COLUMNAS_CON_DATO_DE_LC
    )
    conexion = sqlite3.connect(ruta_db)
    conexion.row_factory = sqlite3.Row
    try:
        filas = conexion.execute(
            "SELECT r.*, c.apellido, c.nombre FROM recetas r "
            "JOIN clientes c USING (id_cliente) "
            f"WHERE r.tipo_lente = ? OR {con_dato}",
            (TIPO_LENTES_CONTACTO,),
        ).fetchall()
        return [dict(fila) for fila in filas]
    finally:
        conexion.close()


def exportar_lentes_contacto(ruta_db: Path, ruta_csv: Path) -> list[dict[str, object]]:
    """Genera ``lentes_contacto.csv`` leyendo únicamente la base.

    Es la misma función que usa el ETL, y se puede llamar sola para rehacer el
    archivo sin volver a correr todo::

        python -c "import etl_optica as e; e.exportar_lentes_contacto(
            e.CARPETA_SALIDA / 'optica_limpia.db',
            e.CARPETA_SALIDA / 'lentes_contacto.csv')"

    Args:
        ruta_db: Ruta a ``optica_limpia.db``.
        ruta_csv: Dónde escribir el CSV.

    Returns:
        Las filas escritas, antes de formatear.
    """
    filas = filas_lentes_contacto(leer_visitas_lc(ruta_db))
    _escribir_csv(
        ruta_csv,
        COLUMNAS_LENTES_CONTACTO,
        (
            {c: _valor_csv(fila.get(c)) for c in COLUMNAS_LENTES_CONTACTO}
            for fila in filas
        ),
    )
    return filas


def _contar_lentes_contacto(filas: list[dict[str, object]], metricas: Metricas) -> None:
    """Completa los recuentos de ``lentes_contacto.csv`` para el reporte.

    Args:
        filas: Filas del CSV, tal como las devuelve
            :func:`exportar_lentes_contacto`.
        metricas: Contadores a completar.
    """
    metricas.lc_filas = len(filas)
    visitas: dict[object, dict[str, object]] = {}
    for fila in filas:
        metricas.lc_por_prescriptor[str(fila["prescriptor"])] += 1
        visitas[fila["id_bloque"]] = fila
        if fila["signo_cil_distinto"] == "SI":
            metricas.lc_filas_signo_distinto += 1

    metricas.lc_visitas = len(visitas)
    for fila in visitas.values():
        if fila["signo_cil_distinto"] == "SI":
            metricas.lc_visitas_signo_distinto += 1
        # El nivel se cuenta por celda (ojo), tal como quedó escrito.
        for columna in ("od_nivel", "oi_nivel"):
            if fila.get(columna) not in (None, ""):
                metricas.lc_niveles[str(fila[columna])] += 1


def _escribir_csv(ruta: Path, columnas: tuple[str, ...], filas) -> None:
    """Escribe un CSV en UTF-8 con BOM.

    El BOM es obligatorio: los archivos se abren con Excel en Windows y sin él
    los acentos salen rotos.

    Args:
        ruta: Archivo a escribir.
        columnas: Cabecera, en orden.
        filas: Iterable de diccionarios con esas claves.
    """
    with ruta.open("w", encoding=ENCODING_SALIDA, newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(columnas))
        escritor.writeheader()
        cantidad = 0
        for fila in filas:
            escritor.writerow(fila)
            cantidad += 1
    _log.info("Escrito %s (%d filas)", ruta.name, cantidad)


# ===========================================================================
# REPORTE DE CALIDAD
# ===========================================================================


def _completitud(ruta_db: Path) -> list[tuple[str, int, float]]:
    """Calcula el porcentaje de no nulos de cada columna de ``recetas``.

    Args:
        ruta_db: Ruta a la base ya escrita.

    Returns:
        Lista de tuplas ``(columna, no_nulos, porcentaje)``, de mayor a menor.
    """
    conexion = sqlite3.connect(ruta_db)
    total = conexion.execute("SELECT COUNT(*) FROM recetas").fetchone()[0]
    if total == 0:
        conexion.close()
        return []

    seleccion = ", ".join(
        f"SUM(CASE WHEN {c} IS NOT NULL AND {c} <> '' THEN 1 ELSE 0 END)"
        for c in COLUMNAS_RECETAS
    )
    valores = conexion.execute(f"SELECT {seleccion} FROM recetas").fetchone()
    conexion.close()

    return sorted(
        (
            (columna, int(cantidad or 0), 100.0 * (cantidad or 0) / total)
            for columna, cantidad in zip(COLUMNAS_RECETAS, valores)
        ),
        key=lambda t: -t[2],
    )


def generar_reporte(
    metricas: Metricas,
    filas_revision: list[FilaRevision],
    carpeta_salida: Path,
) -> str:
    """Arma el reporte de calidad en Markdown.

    Args:
        metricas: Contadores del pipeline.
        filas_revision: Filas de ``revisar_manual.csv``.
        carpeta_salida: Carpeta de salida, donde está la base.

    Returns:
        El reporte completo como texto.
    """
    lineas: list[str] = []
    agregar = lineas.append

    agregar("# Reporte de calidad · ETL de la óptica")
    agregar("")
    agregar(f"Generado el {datetime.now():%d/%m/%Y a las %H:%M:%S}.")
    agregar(f"Duración de la corrida: {metricas.duracion_segundos:.1f} segundos.")
    agregar(f"Encoding detectado en el archivo crudo: `{metricas.encoding_detectado}`.")
    agregar("")

    # --- 1. Volumen ---------------------------------------------------------
    agregar("## 1. Volumen procesado")
    agregar("")
    agregar("| Métrica | Valor |")
    agregar("|---|---:|")
    agregar(f"| Registros de entrada leídos | {metricas.registros_entrada:,} |")
    agregar(f"| Clientes únicos resultantes | {metricas.clientes_unicos:,} |")
    agregar(f"| Registros fusionados por duplicado | {metricas.clientes_fusionados:,} |")
    agregar(f"| Visitas duplicadas colapsadas | {metricas.visitas_fusionadas:,} |")
    agregar(f"| Recetas extraídas | {metricas.recetas_totales:,} |")
    agregar(
        f"| Clientes marcados como posible registro basura | "
        f"{metricas.registros_basura:,} |"
    )
    agregar(
        f"| Clientes que requieren revisión | "
        f"{metricas.clientes_requieren_revision:,} |"
    )
    agregar(f"| Conflictos de documento | {metricas.conflictos_documento:,} |")
    agregar("")

    # --- 2. Recetas ---------------------------------------------------------
    agregar("## 2. Recetas")
    agregar("")
    agregar("### Ventas vs. presupuestos")
    agregar("")
    agregar("| Tipo | Cantidad | % |")
    agregar("|---|---:|---:|")
    total_recetas = max(metricas.recetas_totales, 1)
    for tipo, cantidad in metricas.recetas_por_tipo.most_common():
        agregar(f"| {tipo} | {cantidad:,} | {100 * cantidad / total_recetas:.1f} % |")
    agregar("")

    agregar("### Origen del dato")
    agregar("")
    agregar("| Origen | Cantidad |")
    agregar("|---|---:|")
    for origen, cantidad in metricas.recetas_por_origen.most_common():
        agregar(f"| {origen} | {cantidad:,} |")
    agregar("")

    agregar("### Distribución por año")
    agregar("")
    agregar("| Año | Recetas |")
    agregar("|---:|---:|")
    for anio in sorted(metricas.recetas_por_anio):
        agregar(f"| {anio} | {metricas.recetas_por_anio[anio]:,} |")
    sin_fecha = metricas.recetas_totales - sum(metricas.recetas_por_anio.values())
    agregar(f"| (sin fecha) | {sin_fecha:,} |")
    agregar("")

    # --- 3. Completitud ------------------------------------------------------
    agregar("## 3. Tasa de completitud por columna")
    agregar("")
    agregar("Porcentaje de recetas con valor no nulo en cada columna.")
    agregar("")
    agregar("| Columna | Con dato | % |")
    agregar("|---|---:|---:|")
    for columna, cantidad, porcentaje in _completitud(
        carpeta_salida / "optica_limpia.db"
    ):
        agregar(f"| `{columna}` | {cantidad:,} | {porcentaje:.1f} % |")
    agregar("")

    # --- 4. Revisión manual --------------------------------------------------
    agregar("## 4. Casos marcados para revisión manual")
    agregar("")
    agregar(f"Total de filas en `revisar_manual.csv`: **{len(filas_revision):,}**")
    agregar("")
    agregar("| Severidad | Motivo | Casos |")
    agregar("|---|---|---:|")
    por_motivo = Counter((f.severidad, f.motivo) for f in filas_revision)
    for (sev, motivo), cantidad in sorted(
        por_motivo.items(), key=lambda t: (ORDEN_SEVERIDAD.get(t[0][0], 9), -t[1])
    ):
        agregar(f"| {sev} | `{motivo}` | {cantidad:,} |")
    agregar("")

    # --- 5. Líneas no interpretadas -------------------------------------------
    agregar("## 5. Líneas que ningún patrón supo interpretar")
    agregar("")
    if metricas.ejemplos_no_interpretados:
        agregar(
            f"Recetas afectadas: "
            f"**{metricas.motivos.get(str(Motivo.VALOR_NO_PARSEABLE), 0):,}**. "
            "Ejemplos textuales:"
        )
        agregar("")
        agregar("```")
        for ejemplo in metricas.ejemplos_no_interpretados:
            agregar(ejemplo[:200])
        agregar("```")
    else:
        agregar("No quedó ninguna línea sin interpretar.")
    agregar("")

    # --- 6. Correcciones manuales ---------------------------------------------
    agregar("## 6. Ciclo de corrección manual")
    agregar("")
    agregar("| Métrica | Valor |")
    agregar("|---|---:|")
    agregar(f"| Recetas corregidas a mano | {metricas.correcciones_aplicadas:,} |")
    agregar(f"| Celdas concretas aplicadas | {metricas.correcciones_celdas:,} |")
    agregar(
        f"| Correcciones huérfanas (id_bloque inexistente) | "
        f"{metricas.correcciones_huerfanas:,} |"
    )
    agregar(f"| Registros que siguen en revisar_manual.csv | {len(filas_revision):,} |")
    agregar("")

    # --- 7. Lentes de contacto -------------------------------------------------
    agregar("## 7. Lentes de contacto")
    agregar("")
    agregar("Recuentos de `lentes_contacto.csv`: una fila por prescripción.")
    agregar("")
    agregar("| Métrica | Valor |")
    agregar("|---|---:|")
    agregar(f"| Filas del archivo | {metricas.lc_filas:,} |")
    agregar(f"| Visitas con datos de lentes de contacto | {metricas.lc_visitas:,} |")
    for prescriptor, cantidad in metricas.lc_por_prescriptor.most_common():
        agregar(f"| Filas con prescriptor `{prescriptor}` | {cantidad:,} |")
    agregar(
        f"| Filas con `signo_cil_distinto = SI` | "
        f"{metricas.lc_filas_signo_distinto:,} |"
    )
    agregar(
        f"| Visitas con `signo_cil_distinto = SI` | "
        f"{metricas.lc_visitas_signo_distinto:,} |"
    )
    for motivo in (
        Motivo.NIVEL_EN_CILINDRO,
        Motivo.MEDIDAS_LC_SIN_ETIQUETA,
        Motivo.RECETA_REPETIDA_DISTINTA,
        Motivo.RP_ANTEOJOS_SIN_LEER,
        Motivo.LC_CLASIFICADA_POR_CAJA,
    ):
        agregar(
            f"| Casos `{motivo}` en revisar_manual.csv | "
            f"{metricas.motivos.get(str(motivo), 0):,} |"
        )
    agregar("")
    agregar("### Nivel de adición, tal como está escrito")
    agregar("")
    agregar("Se cuenta por celda (`od_nivel` y `oi_nivel`), una vez por visita.")
    agregar("")
    if metricas.lc_niveles:
        agregar("| Nivel | Celdas |")
        agregar("|---|---:|")
        for nivel, cantidad in sorted(
            metricas.lc_niveles.items(), key=lambda par: (-par[1], par[0])
        ):
            agregar(f"| `{nivel}` | {cantidad:,} |")
    else:
        agregar("No hay ninguna visita con nivel de adición.")
    agregar("")

    return "\n".join(lineas)


# ===========================================================================
# ORQUESTACIÓN
# ===========================================================================


def configurar_logging(carpeta_salida: Path) -> None:
    """Configura el logging a consola y a ``salida/etl.log``.

    Args:
        carpeta_salida: Carpeta donde escribir el archivo de log.
    """
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%H:%M:%S",
    )

    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.handlers.clear()

    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    raiz.addHandler(consola)

    archivo = logging.FileHandler(
        carpeta_salida / "etl.log", mode="w", encoding="utf-8"
    )
    archivo.setFormatter(formato)
    raiz.addHandler(archivo)


#: Archivos que el ETL reescribe en cada corrida.
ARCHIVOS_DE_SALIDA: tuple[str, ...] = (
    "optica_limpia.db",
    "clientes.csv",
    "recetas.csv",
    "revisar_manual.csv",
    "lentes_contacto.csv",
    "reporte_calidad.md",
)


def salidas_bloqueadas(carpeta_salida: Path) -> list[str]:
    """Devuelve las salidas que no se pueden reescribir en este momento.

    En Windows, un CSV abierto en Excel no se puede sobrescribir. Antes el ETL
    lo descubría a mitad de camino, cuando ya había reescrito la base, y dejaba
    ``salida/`` con archivos de dos corridas distintas. Ahora se comprueba
    antes de empezar y no se toca nada.

    Args:
        carpeta_salida: Carpeta de salida.

    Returns:
        Los nombres de los archivos existentes que no se pueden abrir para
        escritura. Lista vacía si se puede escribir en todos.
    """
    bloqueados: list[str] = []
    for nombre in ARCHIVOS_DE_SALIDA:
        ruta = carpeta_salida / nombre
        if not ruta.exists():
            continue
        try:
            with ruta.open("a"):
                pass
        except OSError:
            bloqueados.append(nombre)
    return bloqueados


def leer_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    """Lee las rutas de la línea de comandos; sin argumentos usa las de arriba."""
    lector_args = argparse.ArgumentParser(description="ETL de la base histórica de la óptica.")
    lector_args.add_argument("--entrada", type=Path, default=ARCHIVO_ENTRADA,
                             help="CSV crudo exportado de Moebius")
    lector_args.add_argument("--correcciones", type=Path, default=ARCHIVO_CORRECCIONES,
                             help="CSV de correcciones manuales (opcional)")
    lector_args.add_argument("--salida", type=Path, default=CARPETA_SALIDA,
                             help="carpeta donde se escriben las salidas")
    return lector_args.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del ETL.

    Args:
        argv: Argumentos de la línea de comandos. ``None`` lee los de ``sys.argv``.

    Returns:
        ``0`` si la corrida terminó bien, ``1`` si falló de forma irrecuperable.
    """
    argumentos = leer_argumentos(argv)
    archivo_entrada = argumentos.entrada
    archivo_correcciones = argumentos.correcciones
    carpeta_salida = argumentos.salida

    inicio = datetime.now()
    configurar_logging(carpeta_salida)

    _log.info("ETL de la óptica - inicio")
    _log.info("Entrada:      %s", archivo_entrada)
    _log.info("Correcciones: %s", archivo_correcciones)
    _log.info("Salida:       %s", carpeta_salida)

    if not archivo_entrada.exists():
        _log.error("No se encontró el archivo de entrada: %s", archivo_entrada)
        return 1

    bloqueados = salidas_bloqueadas(carpeta_salida)
    if bloqueados:
        _log.error(
            "No se puede escribir en %s. Cerrá el archivo en el programa que lo "
            "tenga abierto (por ejemplo Excel) y volvé a correr. No se modificó "
            "ninguna salida.",
            ", ".join(bloqueados),
        )
        return 1

    # Se genera la plantilla de correcciones si todavía no existe, para que
    # sepamos qué formato llenar sin adivinar.
    mod_correcciones.generar_plantilla(archivo_correcciones)

    metricas = Metricas()

    registros = extraer(archivo_entrada, metricas)
    clientes = transformar(registros, archivo_correcciones, metricas)
    filas_revision = cargar(clientes, carpeta_salida, metricas)

    metricas.duracion_segundos = (datetime.now() - inicio).total_seconds()

    reporte = generar_reporte(metricas, filas_revision, carpeta_salida)
    (carpeta_salida / "reporte_calidad.md").write_text(reporte, encoding="utf-8")

    _log.info("=" * 70)
    _log.info("REPORTE DE CALIDAD")
    _log.info("=" * 70)
    for linea in reporte.split("\n"):
        _log.info(linea)

    _log.info(
        "ETL terminado en %.1f segundos. Salidas en %s",
        metricas.duracion_segundos,
        carpeta_salida,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
