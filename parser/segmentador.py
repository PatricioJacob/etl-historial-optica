# -*- coding: utf-8 -*-
"""
Capa de TRANSFORMACIÓN: divide el bloque de NOTAS de un cliente en visitas.

Una visita es una compra o una cotización. En el archivo hay DOS gramáticas
distintas para delimitarlas, y las dos hay que soportarlas:

DIALECTO MOEBIUS (31.936 registros, 63.665 visitas)
---------------------------------------------------
Las visitas están separadas por marcadores ``<< FECHA: dd/mm/aaaa >>``.
La primera fecha puede venir en la misma línea del registro o en la siguiente.

DIALECTO MANUSCRITO (258 registros)
-----------------------------------
No hay ningún ``<< FECHA >>``. Son recetas tipeadas a mano directamente en el
campo Notas de Moebius, con la fecha suelta al final de la línea del doctor
(``DRA VISTAMAR ELENA 14/05/2021``) o directamente sin fecha.

POR QUÉ IMPORTA EL SEGUNDO DIALECTO
-----------------------------------
Sus fechas llegan a 2024, mientras que el máximo de ``<< FECHA >>`` es
27/12/2023. Son los pacientes MÁS RECIENTES: justo los que la empleada va a
buscar. Un parser anclado sólo a ``<< FECHA >>`` los emitiría como "cliente sin
receta" y desaparecerían en silencio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from . import normalizador, patrones

_log = logging.getLogger(__name__)

#: Tope de visitas por cliente. Si un registro corrupto genera más, se corta y
#: se marca para revisión. Un cliente malformado no puede colgar la corrida:
#: el máximo legítimo observado en el archivo real es de 27 visitas.
MAXIMO_VISITAS_POR_CLIENTE: int = 400


@dataclass
class Visita:
    """Un bloque de texto correspondiente a una compra o cotización.

    Attributes:
        fecha: Fecha de la visita, o ``None`` si no se pudo determinar.
        fecha_cruda: Texto exacto de la fecha tal como venía, para poder
            reportarlo en ``revisar_manual.csv`` cuando es inválida.
        es_presupuesto: ``True`` si el bloque venía marcado ``<Presupuesto>``.
        lineas: Líneas de contenido de la visita, sin el marcador de fecha ni
            los separadores visuales.
        texto_original: Bloque crudo completo, marcador de fecha incluido. Es
            lo que se guarda en la columna ``texto_original`` de la base.
        dialecto: ``"moebius"`` o ``"manuscrito"``.
        incidencias: Motivos de revisión detectados durante la segmentación,
            como pares ``(motivo, detalle)``.
    """

    fecha: date | None = None
    fecha_cruda: str = ""
    es_presupuesto: bool = False
    lineas: list[str] = field(default_factory=list)
    texto_original: str = ""
    dialecto: str = "moebius"
    incidencias: list[tuple[str, str]] = field(default_factory=list)


def _es_linea_descartable(linea: str) -> bool:
    """Indica si una línea es ruido estructural que no aporta contenido.

    Args:
        linea: Línea del bloque de notas.

    Returns:
        ``True`` para líneas vacías y para los separadores de guiones bajos.
    """
    if not linea.strip():
        return True
    return bool(patrones.SEPARADOR_VISUAL.match(linea))


def _limpiar_lineas(lineas: list[str]) -> list[str]:
    """Quita del bloque las líneas que no aportan contenido.

    Args:
        lineas: Líneas crudas de una visita.

    Returns:
        Las líneas con contenido, en el mismo orden.
    """
    return [ln for ln in lineas if not _es_linea_descartable(ln)]


def _segmentar_moebius(lineas_notas: list[str]) -> list[Visita]:
    """Divide el bloque de notas usando los marcadores ``<< FECHA >>``.

    Recorre las líneas acumulando en la visita actual. Cada vez que encuentra
    un marcador de fecha, cierra la visita anterior y abre una nueva.

    Los marcadores que NO son fecha (``<< >>``, ``<< .>>``, ``<< |>>``,
    ``<<  >>``, ``<< 0>>``) se ignoran como delimitadores: son terminadores de
    bloque. Tratarlos como fecha generaría 13.828 visitas fantasma.

    Args:
        lineas_notas: Líneas del campo NOTAS del registro.

    Returns:
        Lista de visitas, en el orden en que aparecen.
    """
    visitas: list[Visita] = []
    actual: Visita | None = None
    # Texto que aparece antes del primer marcador de fecha. En la muestra, el
    # cliente QUIROGUEZ;MIRTA tiene la fecha en la línea siguiente al registro,
    # así que este preámbulo suele estar vacío; pero no siempre lo está.
    preambulo: list[str] = []

    for linea in lineas_notas:
        coincidencia = patrones.MARCADOR_FECHA.search(linea)

        if coincidencia is None:
            # Rescate del único caso del archivo con ``<< FECHA:`` sin cerrar.
            coincidencia = patrones.MARCADOR_FECHA_SIN_CIERRE.search(linea)
            fecha_sin_cierre = coincidencia is not None
        else:
            fecha_sin_cierre = False

        if coincidencia is None:
            destino = actual.lineas if actual is not None else preambulo
            destino.append(linea)
            if actual is not None:
                actual.texto_original += "\n" + linea
            continue

        if len(visitas) >= MAXIMO_VISITAS_POR_CLIENTE:
            _log.warning(
                "Se alcanzó el tope de %d visitas para un cliente; se corta.",
                MAXIMO_VISITAS_POR_CLIENTE,
            )
            break

        if actual is not None:
            visitas.append(actual)

        fecha_cruda = coincidencia.group("fecha")
        nueva = Visita(
            fecha=normalizador.normalizar_fecha(fecha_cruda),
            fecha_cruda=fecha_cruda,
            es_presupuesto=bool(patrones.PRESUPUESTO.search(linea)),
            texto_original=linea,
            dialecto="moebius",
        )

        if nueva.fecha is None:
            nueva.incidencias.append(("fecha_invalida", f"fecha {fecha_cruda}"))
        if fecha_sin_cierre:
            nueva.incidencias.append(
                ("marcador_sin_cierre", f"<< FECHA: {fecha_cruda} sin >>")
            )

        # Lo que quede en la línea después del marcador es contenido.
        resto = linea[coincidencia.end():]
        if resto.strip():
            nueva.lineas.append(resto)

        # El preámbulo, si tenía contenido, pertenece a esta primera visita:
        # son las líneas que el sistema viejo dejó antes del marcador.
        if not visitas and preambulo:
            utiles = _limpiar_lineas(preambulo)
            if utiles:
                nueva.lineas = utiles + nueva.lineas
                nueva.texto_original = "\n".join(preambulo) + "\n" + nueva.texto_original
            preambulo = []

        actual = nueva

    if actual is not None:
        visitas.append(actual)

    for visita in visitas:
        visita.lineas = _limpiar_lineas(visita.lineas)

    return visitas


def _segmentar_manuscrito(lineas_notas: list[str]) -> list[Visita]:
    """Trata un registro sin ningún ``<< FECHA >>`` como una única visita.

    Busca la fecha entre las fechas sueltas ``dd/mm/aaaa`` que aparezcan en el
    texto. Si hay varias se toma la más reciente, porque en el dialecto
    manuscrito las fechas anteriores suelen ser referencias a recetas viejas
    (``SEÑA DEL 12/6/14``, ``HOY 05/02/10 SOLO 1 CAJA OD``) y la última es la
    de la consulta.

    Si no hay ninguna fecha, la visita se emite igual con fecha nula y se
    marca ``sin_fecha``. El cliente NO se pierde: es la trampa que mata a los
    registros de nota puramente libre.

    Args:
        lineas_notas: Líneas del campo NOTAS del registro.

    Returns:
        Una lista con una única visita, o vacía si el bloque no tiene nada.
    """
    utiles = _limpiar_lineas(lineas_notas)
    if not utiles:
        return []

    texto = "\n".join(lineas_notas)
    candidatas: list[tuple[date, str]] = []
    for coincidencia in patrones.FECHA_SUELTA.finditer(texto):
        cruda = coincidencia.group("fecha")
        interpretada = normalizador.normalizar_fecha(cruda)
        if interpretada is not None:
            candidatas.append((interpretada, cruda))

    visita = Visita(
        lineas=utiles,
        texto_original=texto.strip("\n"),
        dialecto="manuscrito",
        es_presupuesto=bool(patrones.PRESUPUESTO.search(texto)),
    )

    if candidatas:
        visita.fecha, visita.fecha_cruda = max(candidatas, key=lambda par: par[0])
    else:
        visita.incidencias.append(
            ("sin_fecha", "registro sin << FECHA >> ni fecha suelta reconocible")
        )

    visita.incidencias.append(
        (
            "dialecto_manuscrito",
            "receta tipeada a mano, sin marcadores << FECHA >>",
        )
    )
    return [visita]


def segmentar(lineas_notas: list[str]) -> list[Visita]:
    """Divide el bloque de NOTAS de un cliente en visitas.

    Elige el dialecto según haya o no marcadores ``<< FECHA >>`` en el bloque.

    Args:
        lineas_notas: Líneas del campo NOTAS del registro crudo.

    Returns:
        Lista de visitas. Puede ser vacía si el bloque no tiene contenido.
    """
    texto = "\n".join(lineas_notas)

    if patrones.MARCADOR_FECHA.search(texto) or patrones.MARCADOR_FECHA_SIN_CIERRE.search(
        texto
    ):
        return _segmentar_moebius(lineas_notas)

    return _segmentar_manuscrito(lineas_notas)
