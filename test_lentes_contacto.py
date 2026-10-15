# -*- coding: utf-8 -*-
"""
Tests del lente de contacto entregado y de ``salida/lentes_contacto.csv``.

Cubren dos cosas:

* la potencia del lente y el nivel de adición (HIGH / MED / LOW / MID), que se
  leen del renglón de la sección ``LENTES DE CONTACTO``;
* la vista de exportación ``lentes_contacto.csv``: una fila por prescripción.

Todo lo que aparece en estos tests es INVENTADO: fechas, graduaciones,
modelos y comentarios. Los textos imitan el FORMATO de las notas de Moebius,
que es lo que se prueba, pero no copian ninguna nota.

Para correrlos:

    python -m pytest test_lentes_contacto.py -v
"""

from __future__ import annotations

import sqlite3

import pytest

import etl_optica
from parser import extractor, patrones, segmentador
from parser.deduplicador import deduplicar
from parser.motivos import Motivo

FECHA = "<< FECHA: 17/06/2022 >>\n"


def parsear(texto_notas: str):
    """Segmenta y extrae un bloque de notas, como lo hace el ETL."""
    visitas = segmentador.segmentar(texto_notas.split("\n"))
    return [extractor.extraer(v, "INVENTADO", "CLIENTE") for v in visitas]


def filas_csv(texto_notas: str) -> list[dict[str, object]]:
    """Devuelve las filas de ``lentes_contacto.csv`` para un bloque de notas."""
    return etl_optica.filas_lentes_contacto(visitas_como_en_la_base(texto_notas))


def visitas_como_en_la_base(texto_notas: str) -> list[dict[str, object]]:
    """Devuelve las visitas como filas de ``recetas``, igual que salen de la base.

    El CSV se arma sólo con columnas de la base. Acá se pasa por el mismo
    formato para que el test no dependa de nada que no se guarde.
    """
    recetas = parsear(texto_notas)
    cliente = deduplicar([("INVENTADO", "CLIENTE", None, recetas, [])]).clientes[0]
    filas = []
    for numero, receta in enumerate(cliente.recetas, start=1):
        fila = etl_optica._fila_receta(receta, numero, cliente.id_cliente)
        fila["apellido"] = cliente.apellido
        fila["nombre"] = cliente.nombre
        filas.append(fila)
    return filas


def motivos_de(receta) -> set[Motivo]:
    """Devuelve el conjunto de motivos de incidencia de una receta."""
    return {motivo for motivo, _ in receta.incidencias}


# ===========================================================================
# PARTE 1 · Potencia del lente y nivel de adición
# ===========================================================================


def test_la_potencia_del_lente_no_pisa_la_esfera_de_la_receta():
    """Receta del médico +2.75, lente entregado +2.50/HIGH: son datos distintos.

    La potencia del lente coincide con la esfera de alguna receta de la visita
    en 526 apariciones del archivo y difiere en 222.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. +2.75\n"
        "    O.I.  Esf. +2.25\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. +2.50/HIGH\n"
        "      O.I. +2.50/HIGH\n"
        "      Marca L.C. SOFLENS\n"
    )
    receta = parsear(notas)[0]

    # La receta queda como la escribió el médico.
    assert receta.lc_med_od_esf == "+2.75"
    assert receta.lc_med_oi_esf == "+2.25"
    assert receta.lc_od_esf == "+2.75"

    # El lente entregado va aparte.
    assert receta.lc_od_potencia_lente == "+2.50"
    assert receta.lc_od_nivel == "HIGH"
    assert receta.lc_oi_potencia_lente == "+2.50"
    assert receta.lc_oi_nivel == "HIGH"
    assert receta.lc_marca == "SOFLENS"


@pytest.mark.parametrize(
    ("renglon", "potencia", "nivel"),
    [
        # Potencia y nivel separados por una barra.
        ("+2.75/HIGH", "+2.75", "HIGH"),
        ("+1.75 / HIGH", "+1.75", "HIGH"),
        ("ESF. +3.25/ HIGH", "+3.25", "HIGH"),
        ("-0.50/LOW", "-0.50", "LOW"),
        ("+1.50/MID", "+1.50", "MID"),
        # En minúscula: se respeta tal como está escrito.
        ("+1.25/med", "+1.25", "med"),
        ("+2.25/high", "+2.25", "high"),
        # Con ADD en el medio: el texto que rodea al nivel se conserva.
        ("+2.50 ADD HIGH", "+2.50", "ADD HIGH"),
        ("+1.75 /add HIGH", "+1.75", "/add HIGH"),
        # Sin número.
        ("HIGH", None, "HIGH"),
        ("ADD HIGH", None, "ADD HIGH"),
        ("ADD. HIGH", None, "ADD. HIGH"),
        # Abreviatura que existe en el archivo: tampoco se interpreta.
        ("+0.75/HI", "+0.75", "HI"),
        # Potencia sola, sin nivel.
        ("-12.50", "-12.50", None),
    ],
)
def test_formas_del_renglon_del_lente(renglon, potencia, nivel):
    """Cada forma del renglón da su potencia y su nivel, sin interpretar."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. {renglon}\n      Marca L.C. SOFLENS\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_potencia_lente == potencia
    assert receta.lc_od_nivel == nivel
    # El otro ojo no se inventa.
    assert receta.lc_oi_potencia_lente is None
    assert receta.lc_oi_nivel is None


def test_nivel_sin_numero_en_los_dos_ojos():
    """``O.D. ADD. HIGH`` / ``O.I. ADD HIGH``: nivel sí, potencia no."""
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      O.D. ADD. HIGH\n"
        "      O.I. ADD HIGH\n"
        "      Marca L.C. SOFLENS\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_nivel == "ADD. HIGH"
    assert receta.lc_oi_nivel == "ADD HIGH"
    assert receta.lc_od_potencia_lente is None
    assert receta.lc_oi_potencia_lente is None


def test_ao_copia_potencia_y_nivel_en_los_dos_ojos():
    """``AO`` es ambos ojos: el valor va a OD y a OI."""
    notas = FECHA + "LENTES DE CONTACTO:\n      AO +1.75 / HIGH\n      Marca L.C. SOFLENS\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_potencia_lente == receta.lc_oi_potencia_lente == "+1.75"
    assert receta.lc_od_nivel == receta.lc_oi_nivel == "HIGH"


def test_numero_sin_signo_y_sin_nivel_no_se_toma_como_potencia():
    """``O.D. 8.40`` puede ser una curva base: no se adivina."""
    notas = FECHA + "LENTES DE CONTACTO:\n      O.D. 8.40\n      Marca L.C. WAICON\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_potencia_lente is None
    assert receta.lc_od_nivel is None
    assert receta.lc_od_esf is None
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)


# --- El nivel fuera del tramo del lente va a observaciones ------------------


def test_texto_despues_de_la_marca_en_el_mismo_renglon_va_a_observaciones():
    """``Marca L.C. AIR OPTIX AO +1.50/ med``: la marca se corta, el resto no se reparte."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. +2.25\n"
        "    O.I.  Esf. +2.25\n"
        "LENTES DE CONTACTO:\n"
        "      Tipo L.C. DESCARTABLES      Marca L.C. AIR OPTIX AO +1.50/ med\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_marca == "AIR OPTIX"
    assert receta.lc_tipo == "DESCARTABLES"
    assert receta.observaciones == "AO +1.50/ med"
    # No se repartió en las columnas del lente.
    assert receta.lc_od_nivel is None
    assert receta.lc_od_potencia_lente is None
    # Y la receta del contactólogo quedó intacta.
    assert receta.lc_cont_od_esf == "+2.25"


def test_nivel_en_el_renglon_siguiente_a_la_marca_se_lee_y_queda_en_observaciones():
    """Un renglón con nivel DEBAJO de la marca se lee como renglón del lente.

    Potencia y nivel van a sus columnas y, además, el renglón queda entero en
    observaciones. Si no se leyera, la visita se quedaría sin graduación: pasó
    en 13 visitas del archivo.
    """
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      Marca L.C. SOFLENS MULTIFOCAL\n"
        " AO +2.25 / HIGH\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_marca == "SOFLENS MULTIFOCAL"
    assert receta.lc_od_potencia_lente == receta.lc_oi_potencia_lente == "+2.25"
    assert receta.lc_od_nivel == receta.lc_oi_nivel == "HIGH"
    assert receta.observaciones == "AO +2.25 / HIGH"
    # Sin prescriptor, el número también alimenta la graduación sin etiquetar.
    assert receta.lc_od_esf == "+2.25"
    assert receta.lc_prescriptor_vigente == "SIN_ESPECIFICAR"


def test_nivel_dentro_de_un_comentario_queda_en_observaciones():
    """Un nivel dentro de texto libre no se copia a las columnas del ojo."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. +1.50\n"
        "CONTROL DE ADAPTACION - SE CAMBIA A AO +1.75/ HIGH VE MEJOR DE CERCA\n"
    )
    receta = parsear(notas)[0]
    assert "AO +1.75/ HIGH" in (receta.observaciones or "")
    assert receta.lc_od_nivel is None
    assert receta.lc_oi_nivel is None


def test_nivel_en_el_renglon_de_una_receta_no_se_pierde():
    """Un nivel pegado a la esfera de una receta va a observaciones."""
    notas = FECHA + "RP. CONTACTOLOGO:\n    O.D.  Esf. +2.50/HIGH\n"
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf == "+2.50"
    assert "HIGH" in (receta.observaciones or "")
    assert receta.lc_od_nivel is None


def test_nivel_en_el_lugar_del_cilindro_no_se_adivina():
    """``Cil. HIGH``: el cilindro queda nulo y se abre un caso de revisión."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. +2.00  Cil. HIGH\n"
        "    O.I.  Esf. +2.25  Cil. HIGH\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf == "+2.00"
    assert receta.lc_cont_od_cil is None
    assert receta.lc_cont_oi_cil is None
    assert Motivo.NIVEL_EN_CILINDRO in motivos_de(receta)
    # Un solo caso por visita, aunque pase en los dos ojos.
    assert sum(1 for m, _ in receta.incidencias if m is Motivo.NIVEL_EN_CILINDRO) == 1
    # El texto no se pierde.
    assert "Cil. HIGH" in (receta.observaciones or "")


# --- En anteojos MED significa otra cosa -----------------------------------


@pytest.mark.parametrize(
    "renglon",
    ["RGO.MED +5-7+1", "MED.TABLET TR.N 5120", "TOMAR MED. NUEVAS"],
)
def test_med_en_anteojos_no_toca_las_columnas_del_lente(renglon):
    """``RGO.MED`` es rango medio y ``MED.TABLET`` son medidas: no es un nivel."""
    notas = (
        FECHA
        + "LEJOS:\n"
        "    O.D.  Esf. +4.50\n"
        "    O.I.  Esf. +5.00\n"
        f"{renglon}\n"
    )
    receta = parsear(notas)[0]
    assert receta.tipo_lente == "MONOFOCAL"
    for columna in (
        "lc_od_potencia_lente",
        "lc_od_nivel",
        "lc_oi_potencia_lente",
        "lc_oi_nivel",
    ):
        assert getattr(receta, columna) is None


def test_el_nivel_no_se_reconoce_dentro_de_otra_palabra():
    """``MEDICO``, ``MEDIDAS`` y ``LOWER`` no son niveles."""
    for texto in ("RP. MEDICO", "MEDIDAS TABLET", "LOWER", "MIDI"):
        assert patrones.NIVEL_ADICION.search(texto) is None
    for texto in ("+3.50/HIGH", "+0.75/med", "ADD. HIGH", "7HIGH"):
        assert patrones.NIVEL_ADICION.search(texto) is not None


# --- Comentarios: nada se descarta ------------------------------------------


def test_lote_y_vencimiento_van_a_observaciones():
    """Lo que no es una medida, en un renglón de lentes de contacto, se conserva."""
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      O.D. -1.50\n"
        "      O.I. LOT 12345678\n"
        "      Marca L.C. O2OPTIX\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_potencia_lente == "-1.50"
    assert "LOT 12345678" in (receta.observaciones or "")


def test_marca_con_numero_no_se_corta():
    """``BIOMEDICS 55`` y ``WAICON 2`` son marcas: el número es parte del nombre."""
    for marca in ("BIOMEDICS 55", "WAICON 2", "ACUVUE OASYS"):
        receta = parsear(FECHA + f"LENTES DE CONTACTO:\n      Marca L.C. {marca}\n")[0]
        assert receta.lc_marca == marca
        assert receta.observaciones is None


# ===========================================================================
# PARTE 2 · lentes_contacto.csv
# ===========================================================================


def test_csv_columnas_en_el_orden_pedido():
    """Las columnas del CSV son las que pidió la óptica, en ese orden."""
    assert etl_optica.COLUMNAS_LENTES_CONTACTO == (
        "id_cliente", "apellido", "nombre", "fecha", "id_bloque",
        "prescriptor", "orden_prescriptor", "es_la_que_se_muestra",
        "od_esf", "od_cil", "od_eje", "oi_esf", "oi_cil", "oi_eje",
        "signo_cil_distinto",
        "od_potencia_lente", "od_nivel", "oi_potencia_lente", "oi_nivel",
        "od_curva_base", "oi_curva_base", "od_diametro", "oi_diametro",
        "marca", "tipo", "cantidad", "observaciones", "texto_original",
    )


def test_csv_dos_prescripciones_dan_dos_filas_con_el_contactologo_primero():
    """Médico y contactólogo: dos filas; el cilindro queda como lo escribió cada uno."""
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -3.25  Cil. -1.25  En 170\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -4.50  Cil. +1.25  En 80\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. -3.75/LOW\n"
        "      Marca L.C. BIOFINITY\n"
    )
    filas = filas_csv(notas)
    assert len(filas) == 2

    primera, segunda = filas
    assert primera["prescriptor"] == "CONTACTOLOGO"
    assert primera["orden_prescriptor"] == 1
    assert primera["es_la_que_se_muestra"] == "SI"
    assert segunda["prescriptor"] == "MEDICO"
    assert segunda["orden_prescriptor"] == 2
    assert segunda["es_la_que_se_muestra"] == "NO"

    # Cilindro tal como está escrito: sin transponer ni cambiar el signo.
    assert primera["od_cil"] == "+1.25" and primera["od_eje"] == "80"
    assert segunda["od_cil"] == "-1.25" and segunda["od_eje"] == "170"
    assert primera["signo_cil_distinto"] == segunda["signo_cil_distinto"] == "SI"

    # Los datos del lente son de la visita: se repiten en las dos filas.
    for fila in filas:
        assert fila["od_potencia_lente"] == "-3.75"
        assert fila["od_nivel"] == "LOW"
        assert fila["marca"] == "BIOFINITY"


def test_csv_un_solo_prescriptor_da_una_fila_que_es_la_que_se_muestra():
    """Sólo el médico: una fila, orden 2, y es la que se muestra."""
    filas = filas_csv(FECHA + "RP. MEDICO:\n    O.D.  Esf. -2.75\n")
    assert len(filas) == 1
    assert filas[0]["prescriptor"] == "MEDICO"
    assert filas[0]["orden_prescriptor"] == 2
    assert filas[0]["es_la_que_se_muestra"] == "SI"
    assert filas[0]["signo_cil_distinto"] == "NO"
    assert filas[0]["od_esf"] == "-2.75"


def test_csv_sin_prescriptor_da_una_fila_sin_especificar():
    """Sólo datos del lente: una fila con ``prescriptor = SIN_ESPECIFICAR``."""
    notas = FECHA + "LENTES DE CONTACTO:\n      O.D. ADD. HIGH\n      Marca L.C. SOFLENS\n"
    filas = filas_csv(notas)
    assert len(filas) == 1
    assert filas[0]["prescriptor"] == "SIN_ESPECIFICAR"
    assert filas[0]["orden_prescriptor"] is None
    assert filas[0]["od_nivel"] == "ADD. HIGH"
    assert filas[0]["od_potencia_lente"] is None


def test_csv_cantidad_tal_como_esta_escrita():
    """``1 PAR`` queda con su unidad; el comentario sigue en observaciones."""
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      Marca L.C. BIOMEDICS 1 PAR DE PRUEBA ! + OPTI FREE 300ML\n"
    )
    fila = filas_csv(notas)[0]
    assert fila["marca"] == "BIOMEDICS"
    assert fila["cantidad"] == "1 PAR"
    assert "DE PRUEBA" in fila["observaciones"]
    assert "OPTI FREE 300ML" in fila["observaciones"]


@pytest.mark.parametrize(
    ("texto", "cantidad"),
    [("3 CAJAS AIR OPTIX", "3 CAJAS"), ("RETIRA 1 CAJA", "1 CAJA"), ("4 PARES", "4 PARES")],
)
def test_csv_cantidad_no_se_convierte_a_unidades(texto, cantidad):
    """La cantidad se copia con su unidad, sin convertirla."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      Marca L.C. SOFLENS\n{texto}\n"
    assert filas_csv(notas)[0]["cantidad"] == cantidad


def test_csv_curva_base_y_diametro_sin_ojo_van_a_los_dos():
    """Un valor escrito sin ojo vale para OD y OI; con ojo, sólo para ése."""
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      O.D. CB 8.50\n"
        "      O.I. CB 8.70\n"
        "      Ø  14.0\n"
        "      Marca L.C. WAICON\n"
    )
    fila = filas_csv(notas)[0]
    assert fila["od_curva_base"] == "8.50"
    assert fila["oi_curva_base"] == "8.70"
    assert fila["od_diametro"] == fila["oi_diametro"] == "14.00"


def test_csv_ordena_por_fecha_real_y_no_como_texto():
    """04/03/2022 va antes que 03/04/2022, aunque como texto sea al revés."""
    notas = (
        "<< FECHA: 03/04/2022 >>\nRP. MEDICO:\n    O.D.  Esf. -2.50\n"
        "<< FECHA: 04/03/2022 >>\nRP. MEDICO:\n    O.D.  Esf. -1.50\n"
    )
    filas = filas_csv(notas)
    assert [f["od_esf"] for f in filas] == ["-1.50", "-2.50"]


def test_csv_no_incluye_visitas_de_anteojos():
    """Una visita de anteojos no tiene ningún dato de lentes de contacto."""
    visitas = visitas_como_en_la_base(FECHA + "LEJOS:\n    O.D.  Esf. -2.00\n")
    assert len(visitas) == 1
    assert visitas[0]["tipo_lente"] != etl_optica.TIPO_LENTES_CONTACTO
    # Ninguna columna de lentes de contacto quedó cargada, así que la consulta
    # que arma el CSV no la trae.
    assert not any(visitas[0][c] for c in etl_optica.COLUMNAS_CON_DATO_DE_LC)


# ===========================================================================
# Un número sin etiqueta no se asigna por su posición
# ===========================================================================


def test_renglon_de_lente_rigido_sin_etiquetas_no_llena_ninguna_columna():
    """``O.D. 8.40 -2.50 9.60``: no se asume qué es cada número por su orden.

    Lo más probable es curva base, potencia y diámetro, pero el renglón no
    llena ninguna columna: va entero a observaciones y a revisión manual.
    """
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      O.D. 8.40 -2.50 9.60\n"
        "      Marca L.C. RGP INVENTADA\n"
    )
    receta = parsear(notas)[0]
    for columna in (
        "lc_od_esf",
        "lc_od_cil",
        "lc_od_eje",
        "lc_od_potencia_lente",
        "lc_od_nivel",
        "lc_od_curva_base",
        "lc_od_diametro",
    ):
        assert getattr(receta, columna) is None, columna
    assert receta.observaciones == "O.D. 8.40 -2.50 9.60"
    casos = [d for m, d in receta.incidencias if m is Motivo.MEDIDAS_LC_SIN_ETIQUETA]
    assert casos == ["O.D. 8.40 -2.50 9.60"]
    assert receta.lc_marca == "RGP INVENTADA"


def test_los_mismos_numeros_con_etiqueta_se_leen_por_la_etiqueta():
    """``O.D. CB 8.40 -2.50 DIA. 9.60``: cada valor va donde dice su etiqueta."""
    notas = FECHA + "LENTES DE CONTACTO:\n      O.D. CB 8.40 -2.50 DIA. 9.60\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_curva_base == "8.40"
    assert receta.lc_od_diametro == "9.60"
    # Un solo número con signo es una potencia.
    assert receta.lc_od_potencia_lente == "-2.50"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)
    # El otro ojo no se inventa.
    assert receta.lc_oi_curva_base is None


@pytest.mark.parametrize(
    "renglon",
    ["8.50/14.00", "8.40", "-3.25 -1.25 A 170", "7.90 -5.25"],
)
def test_renglones_que_no_se_pueden_leer_sin_adivinar(renglon):
    """Más de un número sin etiqueta, o uno sin signo y sin nivel: no se lee."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. {renglon}\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_esf is None
    assert receta.lc_od_cil is None
    assert receta.lc_od_potencia_lente is None
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)
    assert renglon in receta.observaciones


@pytest.mark.parametrize(
    "renglon",
    ["-12.50", "+2.75/HIGH", "1.75/HIGH", "Esf. -3.25 Cil. -1.25 En 170", "LOT 12345678"],
)
def test_renglones_que_siguen_leyendose_como_siempre(renglon):
    """Un número con signo, uno con nivel o uno con etiqueta no abren un caso."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. {renglon}\n"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(parsear(notas)[0])


@pytest.mark.parametrize(
    "renglon",
    [
        "Esf. -2.50 8.40 14.0",          # el ejemplo de la regla estricta
        "Esf. -3.25 RC. 8.50 x 14.00",
        "Esf. -2.50 8.40",               # un solo número suelto junto a la esfera
        "CB 8.40 -2.50 9.60",            # la etiqueta no salva al renglón
        "Esf. -1.25 Cil. -0.75 En 35 14.0",
    ],
)
def test_regla_estricta_con_un_numero_suelto_no_se_lee_nada_del_renglon(renglon):
    """Si hay algún número suelto no se lee NADA, tampoco lo que tiene etiqueta.

    Hasta que el encargado confirme qué son esos números, nada que dependa de
    la posición de un número llega a una columna.
    """
    notas = FECHA + f"RP. CONTACTOLOGO:\n    O.D.  {renglon}\n"
    receta = parsear(notas)[0]
    for columna in (
        "lc_od_esf",
        "lc_od_cil",
        "lc_od_eje",
        "lc_cont_od_esf",
        "lc_cont_od_cil",
        "lc_cont_od_eje",
        "lc_od_potencia_lente",
        "lc_od_curva_base",
        "lc_od_diametro",
    ):
        assert getattr(receta, columna) is None, columna
    assert renglon in receta.observaciones
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)


def test_regla_estricta_el_otro_ojo_se_sigue_leyendo():
    """La regla es por renglón: el renglón limpio del otro ojo no se pierde."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -2.50 8.40 14.0\n"
        "    O.I.  Esf. -1.75  Cil. -1.25  En 165\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf is None
    assert receta.lc_cont_oi_esf == "-1.75"
    assert receta.lc_cont_oi_cil == "-1.25"
    assert receta.lc_cont_oi_eje == "165"


@pytest.mark.parametrize(
    ("renglon", "marca"),
    [
        ("BIOMEDICS 55", "BIOMEDICS 55"),
        ("SOFLENS 59", "SOFLENS 59"),
        ("-3.75 WAICON 2", "WAICON 2"),
        ("-0.75 ACUVUE 2", "ACUVUE 2"),
    ],
)
def test_nombre_de_producto_con_numero_no_abre_un_caso(renglon, marca):
    """El número de ``BIOMEDICS 55`` es parte del nombre, no una medida."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. {renglon}\n"
    receta = parsear(notas)[0]
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)
    # El nombre no se pierde: el renglón queda en observaciones.
    assert marca in receta.observaciones


def test_un_numero_dudoso_junto_a_un_nombre_sigue_en_revision():
    """``NEW TORIC 14`` puede ser un diámetro: no se filtra."""
    notas = FECHA + "LENTES DE CONTACTO:\n      O.I. NEW TORIC 14\n"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(parsear(notas)[0])


def test_vencimiento_con_guion_no_es_una_medida():
    """``2019-08`` es un vencimiento, igual que ``2019/08``."""
    notas = FECHA + "LENTES DE CONTACTO:\n      O.I. 2019-08\n      O.D. -1.25\n"
    receta = parsear(notas)[0]
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)
    assert "2019-08" in receta.observaciones


@pytest.mark.parametrize("fecha", ["2029/08/30", "2029-08-30", "2029/8/3", "1998-11-02"])
def test_fecha_completa_no_es_un_numero_suelto(fecha):
    """``2029/08/30`` vale como el vencimiento sin día: el renglón se lee."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. ESF. -1.75 CIL. -1.25 A 165  {fecha}\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_esf == "-1.75"
    assert receta.lc_od_cil == "-1.25"
    assert receta.lc_od_eje == "165"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)
    # La fecha no se pierde: el renglón queda en observaciones.
    assert fecha in receta.observaciones


@pytest.mark.parametrize("texto", ["2028/13/31", "2028/05/32", "2128/05/31"])
def test_fecha_imposible_sigue_contando_como_numero_suelto(texto):
    """Mes 13, día 32 o un año que no es 19xx ni 20xx: no es una fecha."""
    notas = FECHA + f"LENTES DE CONTACTO:\n      O.D. ESF. -1.75  {texto}\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_esf is None
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)


# ===========================================================================
# Receta repetida en dos renglones
# ===========================================================================


def casos_de_receta_repetida(receta) -> list[str]:
    """Devuelve el detalle de los casos ``receta_repetida_distinta``."""
    return [d for m, d in receta.incidencias if m is Motivo.RECETA_REPETIDA_DISTINTA]


def test_receta_repetida_la_prescripcion_queda_vacia():
    """El primer renglón no se lee: la prescripción no se completa con el otro.

    La visita trae la receta del médico dos veces y difieren (-9.50 y
    -8.75). El primer renglón tiene un número suelto. La columna no pasa a
    mostrar el segundo: queda vacía, y los dos renglones van a revisión.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.I.  Esf. -9.50   RC. 43.00x44.25 a 160\n"
        "    O.I.  Esf. -8.75  Cil. -1.50  En 165\n"
    )
    receta = parsear(notas)[0]
    for columna in (
        "lc_med_oi_esf",
        "lc_med_oi_cil",
        "lc_med_oi_eje",
        "lc_oi_esf",
        "lc_oi_cil",
        "lc_oi_eje",
    ):
        assert getattr(receta, columna) is None, columna
    # La vigente queda vacía, pero dice de quién era la receta que no se leyó.
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_MEDICO
    assert casos_de_receta_repetida(receta) == [
        "no se lee: 'O.I.  Esf. -9.50   RC. 43.00x44.25 a 160'"
        " / no se usa: 'O.I.  Esf. -8.75  Cil. -1.50  En 165'"
    ]
    # Ninguno de los dos renglones se pierde.
    assert "O.I. Esf. -9.50 RC. 43.00x44.25 a 160" in receta.observaciones
    assert "O.I. Esf. -8.75 Cil. -1.50 En 165" in receta.observaciones


def test_receta_repetida_aunque_los_dos_renglones_parezcan_iguales():
    """Del renglón que no se lee no se lee nada: no se sabe si coinciden."""
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -8.25   RC. 42.50x43.75 a 10\n"
        "    O.D.  Esf. -8.25\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_med_od_esf is None
    assert receta.lc_od_esf is None
    assert len(casos_de_receta_repetida(receta)) == 1


def test_receta_repetida_con_el_encabezado_escrito_dos_veces():
    """Vale también si la prescripción vuelve a aparecer más abajo."""
    notas = (
        "R.P. CONTACTOLOGO\n"
        "OD   CIL. -2.25 A 25   8.5\n"
        + FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Cil. -1.75  En 20\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_cil is None
    assert receta.lc_cont_od_eje is None
    assert len(casos_de_receta_repetida(receta)) == 1


def test_receta_repetida_es_por_ojo():
    """Sólo queda vacío el ojo cuyo renglón no se leyó."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  -5.25 -1.75 A 95\n"
        "    O.D.  Esf. -5.00  Cil. -1.50  En 90\n"
        "    O.I.  Esf. -3.75  Cil. -0.75  En 140\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf is None
    assert receta.lc_cont_od_cil is None
    assert receta.lc_cont_od_eje is None
    assert receta.lc_cont_oi_esf == "-3.75"
    assert receta.lc_cont_oi_cil == "-0.75"
    assert receta.lc_cont_oi_eje == "140"
    assert len(casos_de_receta_repetida(receta)) == 1


def test_receta_repetida_con_ao_deja_vacios_los_dos_ojos():
    """Un renglón ``AO`` que no se lee vale por los dos ojos."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    AO  -4.75 8.40\n"
        "    O.D.  Esf. -4.75\n"
        "    O.I.  Esf. -5.00\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf is None
    assert receta.lc_cont_oi_esf is None
    assert len(casos_de_receta_repetida(receta)) == 2


def test_receta_repetida_no_toca_la_otra_prescripcion():
    """La regla es por prescripción: la del médico se lee igual.

    Pero la vigente NO pasa a ser la del médico: el contactólogo escribió algo
    que no se pudo leer. Queda vacía y dice ``CONTACTOLOGO``.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -5.75  Cil. -1.00  En 85\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  -5.25 -1.75 A 95\n"
        "    O.D.  Esf. -5.00  Cil. -1.50  En 90\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf is None
    assert receta.lc_med_od_esf == "-5.75"
    assert receta.lc_med_od_cil == "-1.00"
    for columna in ("lc_od_esf", "lc_od_cil", "lc_od_eje", "lc_oi_esf"):
        assert getattr(receta, columna) is None, columna
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_CONTACTOLOGO
    assert len(casos_de_receta_repetida(receta)) == 1


def test_contactologo_sin_leer_la_vigente_queda_vacia_aunque_no_haya_repetida():
    """Alcanza con que el renglón del contactólogo no se lea.

    No hace falta que la receta esté repetida: la vigente no se completa con
    la del médico.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -3.50\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -3.25 8.40\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_med_od_esf == "-3.50"
    assert receta.lc_od_esf is None
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_CONTACTOLOGO
    assert casos_de_receta_repetida(receta) == []
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)


def test_contactologo_con_un_ojo_leido_sigue_siendo_la_vigente():
    """Si del contactólogo se leyó algo, la vigente es eso, como siempre."""
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -3.50\n"
        "    O.I.  Esf. -3.75\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -3.25 8.40\n"
        "    O.I.  Esf. -3.00\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf is None
    assert receta.lc_oi_esf == "-3.00"
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_CONTACTOLOGO


def test_csv_contactologo_sin_leer_es_la_fila_que_se_muestra():
    """La fila vacía del contactólogo lleva ``SI``; la del médico, ``NO``."""
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -3.50\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -3.25 8.40\n"
    )
    filas = filas_csv(notas)
    assert [(f["prescriptor"], f["es_la_que_se_muestra"]) for f in filas] == [
        ("CONTACTOLOGO", "SI"),
        ("MEDICO", "NO"),
    ]
    assert filas[0]["od_esf"] is None
    assert filas[1]["od_esf"] == "-3.50"


def test_medico_sin_leer_la_vigente_queda_vacia_y_no_muestra_el_lente():
    """Regla general: vale también para el médico cuando no hay contactólogo.

    La vigente no se completa con la potencia del lente entregado.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.I.  Esf. +9.25  Cil. +0.75  En 150   RC. 7.85\n"
        "LENTES DE CONTACTO:\n"
        "      O.I. +9.75\n"
        "      Marca L.C. INVENTADA\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_oi_esf is None
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_MEDICO
    # El lente entregado es otro dato y se conserva.
    assert receta.lc_oi_potencia_lente == "+9.75"
    filas = filas_csv(notas)
    assert [(f["prescriptor"], f["es_la_que_se_muestra"]) for f in filas] == [
        ("MEDICO", "SI")
    ]
    assert filas[0]["oi_esf"] is None


def test_contactologo_leido_manda_aunque_el_medico_no_se_lea():
    """Si la que corresponde mostrar se leyó, la otra no la vacía."""
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.D.  Esf. -3.50  RC. 7.85\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -3.25\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf == "-3.25"
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_CONTACTOLOGO


def test_si_el_primer_renglon_se_lee_la_columna_lo_conserva():
    """Caso inverso: vale el primer renglón, y el caso se abre igual.

    Acá el que no se lee es el segundo. La columna conserva el primero, pero
    son dos versiones de la misma receta: van las dos a revisión.
    """
    notas = (
        FECHA
        + "RP. MEDICO:\n"
        "    O.I.  Esf. -7.25  Cil. -2.50  En 15\n"
        "    O.I.  -6.50 -1.75 A 170\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_med_oi_esf == "-7.25"
    assert receta.lc_med_oi_cil == "-2.50"
    assert receta.lc_med_oi_eje == "15"
    assert casos_de_receta_repetida(receta) == [
        "se usa: 'O.I.  Esf. -7.25  Cil. -2.50  En 15'"
        " / no se lee: 'O.I.  -6.50 -1.75 A 170'"
    ]
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA in motivos_de(receta)
    assert "O.I. -6.50 -1.75 A 170" in receta.observaciones


def test_un_renglon_sin_graduacion_no_abre_un_caso_de_receta_repetida():
    """Sólo cuenta el renglón que traía esfera, cilindro o eje.

    La curva base con etiqueta no es parte de la prescripción: se lee igual.
    """
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      O.D. -2.25   7.50\n"
        "      O.D. CB 8.50\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf is None
    assert receta.lc_od_curva_base == "8.50"
    assert casos_de_receta_repetida(receta) == []


def test_receta_repetida_distinta_tiene_severidad_media():
    """El motivo nuevo tiene su severidad asignada, no la de por defecto."""
    from parser.motivos import SEVERIDAD_POR_MOTIVO

    assert SEVERIDAD_POR_MOTIVO[Motivo.RECETA_REPETIDA_DISTINTA] == "media"


# ===========================================================================
# "R.P.:" escrito a mano con una receta de anteojos
# ===========================================================================


def casos_de_rp(receta) -> list[str]:
    """Devuelve el detalle de los casos ``rp_anteojos_sin_leer``."""
    return [d for m, d in receta.incidencias if m is Motivo.RP_ANTEOJOS_SIN_LEER]


COLUMNAS_DE_GRADUACION = tuple(
    f"{prefijo}_{ojo}_{campo}"
    for prefijo in ("lc", "lc_med", "lc_cont")
    for ojo in ("od", "oi")
    for campo in ("esf", "cil", "eje")
) + tuple(
    f"{ojo}_{seccion}_{campo}"
    for ojo in ("od", "oi")
    for seccion in ("lejos", "cerca")
    for campo in ("esf", "cil", "eje")
)


def test_rp_lejos_no_llena_columnas_de_lentes_de_contacto_ni_de_anteojos():
    """``R.P.: LEJOS OD ...`` no se lee: va a observaciones y a revisión."""
    notas = (
        FECHA
        + "R.P.: LEJOS OD ESF. -1.25 CIL. -0.50 A 175\n"
        "            OI ESF. -1.00 CIL. -0.75 A 5\n"
    )
    receta = parsear(notas)[0]
    for columna in COLUMNAS_DE_GRADUACION:
        assert getattr(receta, columna) is None, columna
    assert receta.lc_prescriptor_vigente is None
    assert receta.tipo_lente is None
    assert casos_de_rp(receta) == [
        "R.P.: LEJOS OD ESF. -1.25 CIL. -0.50 A 175",
        "OI ESF. -1.00 CIL. -0.75 A 5",
    ]
    assert "R.P.: LEJOS OD ESF. -1.25 CIL. -0.50 A 175" in receta.observaciones
    assert "OI ESF. -1.00 CIL. -0.75 A 5" in receta.observaciones


def test_rp_cerca_en_una_visita_de_anteojos_no_la_vuelve_de_contacto():
    """La visita sigue siendo de anteojos y su sección ``CERCA:`` no cambia."""
    notas = (
        FECHA
        + "CERCA:\n"
        "    O.D.  Esf. +2.50\n"
        "    O.I.  Esf. +2.25\n"
        "R.P.: CERCA OD ESF. +2.00\n"
        "      OI ESF. +2.00\n"
    )
    receta = parsear(notas)[0]
    assert receta.tipo_lente == "MONOFOCAL"
    assert receta.od_cerca_esf == "+2.50"
    assert receta.oi_cerca_esf == "+2.25"
    assert receta.lc_oi_esf is None
    assert receta.lc_prescriptor_vigente is None
    assert len(casos_de_rp(receta)) == 2


def test_rp_de_anteojos_un_renglon_suelto_despues_del_doctor_tampoco_se_lee():
    """Tras la línea del doctor no hay sección: el renglón no cae en LEJOS."""
    notas = (
        FECHA
        + "CERCA:\n"
        "    O.D.  Esf. +2.50\n"
        "R.P.: LEJOS OD +1.75\n"
        "Doctor: INVENTADO\n"
        "OI +2.25 -0.50 A 135\n"
    )
    receta = parsear(notas)[0]
    assert receta.oi_lejos_esf is None
    assert receta.lc_oi_esf is None
    assert "OI +2.25 -0.50 A 135" in casos_de_rp(receta)


def test_rp_de_anteojos_no_impide_leer_la_seccion_de_lentes_de_contacto():
    """Una sección de lentes de contacto posterior se lee como siempre."""
    notas = (
        FECHA
        + "R.P.: LEJOS OD ESF. -0.75\n"
        "            OI ESF. -0.50\n"
        "RP. CONTACTOLOGO:\n"
        "    O.I.  Esf. -1.25\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_oi_esf == "-1.25"
    assert receta.lc_oi_esf == "-1.25"
    assert receta.lc_od_esf is None
    assert receta.tipo_lente == "LENTES DE CONTACTO"


def test_rp_con_el_ojo_directo_sigue_yendo_a_lentes_de_contacto():
    """``R.P.: OD ...`` sin LEJOS ni CERCA no cambia: sin prescriptor."""
    receta = parsear(FECHA + "R.P.: OD ESF. -1.25\n")[0]
    assert receta.lc_od_esf == "-1.25"
    assert receta.lc_prescriptor_vigente == extractor.PRESCRIPTOR_SIN_ESPECIFICAR
    assert casos_de_rp(receta) == []


# ===========================================================================
# Valor sin el cero, con etiqueta
# ===========================================================================


@pytest.mark.parametrize(
    ("renglon", "esfera", "cilindro"),
    [
        ("Esf. -1.25  Cil. -.75  En 170", "-1.25", "-0.75"),
        ("Esf. +.50", "+0.50", None),
        ("Esf. -.75  Cil. +.25  En 95", "-0.75", "+0.25"),
        ("ESF. - .25", "-0.25", None),
    ],
)
def test_valor_sin_el_cero_con_etiqueta_en_anteojos(renglon, esfera, cilindro):
    """``Cil. -.50`` es ``-0.50`` y ``Esf. +.75`` es ``+0.75``."""
    receta = parsear(FECHA + f"LEJOS:\n    O.D.  {renglon}\n")[0]
    assert receta.od_lejos_esf == esfera
    assert receta.od_lejos_cil == cilindro


def test_valor_sin_el_cero_con_etiqueta_en_lentes_de_contacto():
    """Vale en todas las secciones, y el renglón ya no cae en revisión."""
    notas = FECHA + "RP. CONTACTOLOGO:\n    O.I.  Esf. -1.50  Cil. -.25  En 175\n"
    receta = parsear(notas)[0]
    assert receta.lc_cont_oi_esf == "-1.50"
    assert receta.lc_cont_oi_cil == "-0.25"
    assert receta.lc_cont_oi_eje == "175"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)


def test_valor_sin_el_cero_necesita_la_etiqueta():
    """Sin etiqueta, ``.50`` no se lee como medida."""
    receta = parsear(FECHA + "LEJOS:\n    O.D.  .50\n")[0]
    assert receta.od_lejos_esf is None


def test_en_anteojos_los_numeros_por_posicion_siguen_valiendo():
    """La regla es sólo de lentes de contacto: los anteojos no se tocan."""
    receta = parsear("LEJOS: O.D: +1.25 -0.50 EN 95\n")[0]
    assert receta.od_lejos_esf == "+1.25"
    assert receta.od_lejos_cil == "-0.50"
    assert receta.od_lejos_eje == "95"
    assert Motivo.MEDIDAS_LC_SIN_ETIQUETA not in motivos_de(receta)


def test_el_dia_de_una_fecha_no_es_un_diametro():
    """``ENTREGADO EL DIA 23/06/2022`` se leía como un diámetro de 23."""
    notas = FECHA + "LEJOS:\n    O.D.  Esf. -1.75\nENTREGADO EL DIA 23/06/2022\n"
    receta = parsear(notas)[0]
    assert receta.lc_od_diametro is None
    assert receta.lc_oi_diametro is None
    assert "ENTREGADO EL DIA 23/06/2022" in receta.observaciones


# ===========================================================================
# Cantidad, curva base y diámetro en la base
# ===========================================================================


def test_la_cantidad_y_las_medidas_por_ojo_son_columnas_de_la_base():
    """El CSV se arma sólo con la base: lo que muestra tiene que estar guardado."""
    notas = (
        FECHA
        + "LENTES DE CONTACTO:\n"
        "      Marca L.C. BIOMEDICS 1 PAR DE PRUEBA ! + OPTI FREE 300ML\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cantidad == "1 PAR"
    for columna in (
        "lc_cantidad",
        "lc_od_curva_base",
        "lc_oi_curva_base",
        "lc_od_diametro",
        "lc_oi_diametro",
    ):
        assert columna in etl_optica.COLUMNAS_RECETAS
    # Las dos columnas únicas ya no existen.
    assert "lc_curva_base" not in etl_optica.COLUMNAS_RECETAS
    assert "lc_diametro" not in etl_optica.COLUMNAS_RECETAS


# ===========================================================================
# Clasificación de visitas sin secciones
# ===========================================================================


def test_visita_sin_secciones_con_marca_se_clasifica_como_lentes_de_contacto():
    """Un comentario que nombra una marca de la lista alcanza para clasificar."""
    receta = parsear(FECHA + "\n 1 PAR ESF.-5.50 BIOMEDICS\n")[0]
    assert receta.tipo_lente == "LENTES DE CONTACTO"
    assert Motivo.LC_CLASIFICADA_POR_CAJA not in motivos_de(receta)
    # Sólo se extrae lo que tiene etiqueta: la esfera no tiene ojo, no se asigna.
    assert receta.lc_od_esf is None
    assert receta.lc_cantidad == "1 PAR"
    assert receta.observaciones == "1 PAR ESF.-5.50 BIOMEDICS"


def test_visita_sin_secciones_con_caja_se_clasifica_y_abre_un_caso():
    """Cajas sin marca: se clasifica, pero la señal es débil y va a revisión."""
    receta = parsear(FECHA + "\n 1 CAJA ESF.-2.25\n")[0]
    assert receta.tipo_lente == "LENTES DE CONTACTO"
    assert Motivo.LC_CLASIFICADA_POR_CAJA in motivos_de(receta)
    assert receta.lc_cantidad == "1 CAJA"


@pytest.mark.parametrize(
    "comentario",
    ["USA ARRIBA DE LTE.CTO.", "RENU FRESH.", "PAGA EN 3 CUOTAS"],
)
def test_visita_sin_secciones_que_no_se_reclasifica(comentario):
    """Nombrar "lentes de contacto" o un líquido en un comentario no alcanza."""
    receta = parsear(FECHA + f"\n {comentario}\n")[0]
    assert receta.tipo_lente is None


def test_anteojo_que_nombra_una_marca_de_lc_sigue_siendo_anteojo():
    """Una visita de anteojos no se reclasifica por un comentario."""
    notas = FECHA + "LEJOS:\n    O.D.  Esf. -2.00\nPREGUNTA POR O2OPTIX PARA MAS ADELANTE\n"
    assert parsear(notas)[0].tipo_lente == "MONOFOCAL"


def test_potencia_con_nivel_en_un_comentario_no_es_un_dato_perdido():
    """Queda en observaciones por regla: no se reporta como no interpretada."""
    notas = (
        FECHA
        + "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. +1.25\n"
        "SOFLENS MULTIFOCAL  AO +2.00 / HIGH\n"
    )
    receta = parsear(notas)[0]
    assert "AO +2.00 / HIGH" in receta.observaciones
    assert Motivo.VALOR_NO_PARSEABLE not in motivos_de(receta)


# ===========================================================================
# El CSV se arma sólo desde la base
# ===========================================================================


def test_visita_mixta_entra_al_csv_aunque_sea_de_anteojos():
    """Toda visita con datos de lentes de contacto tiene sus filas."""
    notas = (
        FECHA
        + "LEJOS:\n"
        "    O.D.  Esf. -0.75\n"
        "BI/MULTIFOCAL: \n"
        "    MONO.STK ORG AR VERDE\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. -1.00\n"
    )
    visitas = visitas_como_en_la_base(notas)
    assert visitas[0]["tipo_lente"] == "BI/MULTIFOCAL"
    assert any(visitas[0][c] for c in etl_optica.COLUMNAS_CON_DATO_DE_LC)
    filas = etl_optica.filas_lentes_contacto(visitas)
    assert len(filas) == 1
    assert filas[0]["od_potencia_lente"] == "-1.00"


def test_el_csv_se_reconstruye_solo_desde_la_base(tmp_path):
    """Exportar dos veces desde la misma base da el mismo archivo, byte a byte."""
    visitas = visitas_como_en_la_base(
        FECHA
        + "RP. MEDICO:\n    O.D.  Esf. -3.25  Cil. -1.25  En 170\n"
        "RP. CONTACTOLOGO:\n    O.D.  Esf. -4.50  Cil. +1.25  En 80\n"
        "LENTES DE CONTACTO:\n      O.D. CB 8.50\n      O.D. -3.75/LOW\n"
        "      Marca L.C. BIOFINITY 3 CAJAS\n"
    )
    ruta_db = tmp_path / "optica_limpia.db"
    conexion = sqlite3.connect(ruta_db)
    conexion.executescript(etl_optica.ESQUEMA_SQL)
    conexion.execute(
        "INSERT INTO clientes (id_cliente, apellido, nombre, nombre_completo) "
        "VALUES (?, ?, ?, ?)",
        (visitas[0]["id_cliente"], "INVENTADO", "CLIENTE", "INVENTADO CLIENTE"),
    )
    columnas = etl_optica.COLUMNAS_RECETAS
    conexion.executemany(
        f"INSERT INTO recetas ({', '.join(columnas)}) "
        f"VALUES ({', '.join(':' + c for c in columnas)})",
        [{c: v[c] for c in columnas} for v in visitas],
    )
    conexion.commit()
    conexion.close()

    primero, segundo = tmp_path / "a.csv", tmp_path / "b.csv"
    filas = etl_optica.exportar_lentes_contacto(ruta_db, primero)
    etl_optica.exportar_lentes_contacto(ruta_db, segundo)

    assert primero.read_bytes() == segundo.read_bytes()
    assert len(filas) == 2
    assert filas[0]["prescriptor"] == "CONTACTOLOGO"
    assert filas[0]["od_curva_base"] == "8.50"
    assert filas[0]["cantidad"] == "3 CAJAS"
    assert filas[0]["signo_cil_distinto"] == "SI"


def test_el_etl_frena_si_una_salida_esta_abierta(tmp_path):
    """Sin archivos bloqueados la lista es vacía; los que faltan no cuentan."""
    assert etl_optica.salidas_bloqueadas(tmp_path) == []
    (tmp_path / "clientes.csv").write_text("x", encoding="utf-8")
    assert etl_optica.salidas_bloqueadas(tmp_path) == []
