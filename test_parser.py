# -*- coding: utf-8 -*-
"""
Tests del parser, con pytest.

Cubren los casos borde del formato de Moebius, los que descubrimos analizando
el archivo de la óptica, y el ciclo de corrección manual.

Todo lo que aparece en estos tests es INVENTADO: apellidos, nombres,
documentos, profesionales, fechas, graduaciones, modelos y observaciones. Los
textos imitan el FORMATO de las notas de Moebius, que es lo que se prueba, pero
no copian ninguna nota.

Para correrlos:

    cd etl-historial-optica-demo
    python -m pytest test_parser.py -v
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from parser import correcciones, extractor, lector, normalizador, patrones, segmentador
from parser.deduplicador import deduplicar
from parser.motivos import Motivo


# ===========================================================================
# AYUDANTES
# ===========================================================================


def parsear(texto_notas: str, apellido: str = "PRUEBA", nombre: str = "CASO"):
    """Segmenta y extrae un bloque de notas, como lo hace el ETL.

    Args:
        texto_notas: Contenido del campo NOTAS.
        apellido: Apellido del cliente ficticio.
        nombre: Nombre del cliente ficticio.

    Returns:
        Lista de recetas extraídas.
    """
    lineas = texto_notas.split("\n")
    visitas = segmentador.segmentar(lineas)
    return [extractor.extraer(v, apellido, nombre) for v in visitas]


def motivos_de(receta) -> set[Motivo]:
    """Devuelve el conjunto de motivos de incidencia de una receta."""
    return {motivo for motivo, _ in receta.incidencias}


# ===========================================================================
# CASO BORDE 1 · Cliente sin receta, sólo observaciones
# ===========================================================================


def test_cliente_solo_texto_libre_no_se_pierde():
    """Nota sin receta ni línea Doctor. NO debe desaparecer.

    Es el caso que perdía el intento anterior por anclar las observaciones a
    la existencia de una línea ``Doctor:``.
    """
    notas = (
        "\n"
        "<< FECHA: 09/03/2016 >>\n"
        "____________________________________________________________\n"
        "\n"
        " PASA A RETIRAR EL JUEVES\n"
    )
    recetas = parsear(notas, "INVENTADEZ", "CASIANA")

    assert len(recetas) == 1
    receta = recetas[0]
    assert receta.fecha == date(2016, 3, 9)
    assert receta.observaciones == "PASA A RETIRAR EL JUEVES"
    assert receta.doctor is None
    assert not receta.tiene_alguna_medida()
    # Se lista para revisión, pero el dato está: no se perdió en silencio.
    assert Motivo.BLOQUE_SIN_ESTRUCTURA in motivos_de(receta)


def test_observaciones_sin_doctor_con_medidas():
    """Una observación después de las medidas se recoge aunque no haya Doctor."""
    notas = (
        "<< FECHA: 14/06/2017 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. -1.25\n"
        "USA ARMAZON PROPIO\n"
    )
    receta = parsear(notas)[0]
    assert receta.od_lejos_esf == "-1.25"
    assert receta.observaciones == "USA ARMAZON PROPIO"


# ===========================================================================
# CASO BORDE 2 · Dos visitas con la misma fecha
# ===========================================================================


def test_dos_visitas_misma_fecha_se_conservan_ambas():
    """Dos visitas el 11/11/2013 con contenido distinto.

    NO se fusionan: dos anteojos comprados el mismo día es comercialmente
    normal en una óptica. Se conservan las dos y se marcan.
    """
    notas = (
        "<< FECHA: 11/11/2013 >>\n"
        "____________________________________________________________\n"
        "LEJOS:\n"
        "    O.D.  Esf. +1.50\n"
        "    O.I.  Esf. +1.50\n"
        "    ADD +2.25\n"
        "CERCA:\n"
        "    O.D.  Esf. +3.75\n"
        "    O.I.  Esf. +3.75\n"
        "BI/MULTIFOCAL: \n"
        "    BI.FLAP TOP ORG BLANCO  D.I. Lejos 64.00  Altura 16.00\n"
        "Doctor: QUIMERA MARIA SOLEDAD\n"
        "\n"
        "                   << FECHA: 11/11/2013 >>\n"
        "____________________________________________________________\n"
        "LEJOS:\n"
        "    O.D.  Esf. +1.50\n"
        "    O.I.  Esf. +1.50   Color 3_GRIS  ORGANICO \n"
        "\n"
        "Doctor: QUIMERA MARIA SOLEDAD\n"
    )
    recetas = parsear(notas, "FANTASIAGA", "ROGELIO ARMANDO")
    assert len(recetas) == 2
    assert all(r.fecha == date(2013, 11, 11) for r in recetas)

    resultado = deduplicar([("FANTASIAGA", "ROGELIO ARMANDO", None, recetas, [])])
    cliente = resultado.clientes[0]

    # Las dos sobreviven a la deduplicación.
    assert len(cliente.recetas) == 2
    assert resultado.visitas_fusionadas == 0
    for receta in cliente.recetas:
        assert Motivo.REVISAR_DUPLICADO_FECHA in motivos_de(receta)


def test_dos_visitas_identicas_si_se_fusionan():
    """Dos visitas con contenido normalizado idéntico sí se colapsan."""
    bloque = (
        "<< FECHA: 03/04/2012 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. -0.75\n"
        "Doctor: FULANO\n"
    )
    recetas = parsear(bloque + bloque)
    assert len(recetas) == 2

    resultado = deduplicar([("PRUEBA", "CASO", None, recetas, [])])
    assert len(resultado.clientes[0].recetas) == 1
    assert resultado.visitas_fusionadas == 1


def test_visitas_que_difieren_solo_en_la_receta_del_medico_no_se_fusionan():
    """Regresión: la firma de duplicados mira las DOS prescripciones.

    Con la vigente en el contactólogo, dos visitas con la misma adaptación pero
    distinta indicación del médico se veían idénticas y se fusionaban,
    perdiendo una receta del médico.
    """
    def bloque(esfera_medico: str) -> str:
        return (
            "<< FECHA: 22/09/2016 >>\n"
            "RP. MEDICO:\n"
            f"    O.D.  Esf. {esfera_medico}\n"
            "RP. CONTACTOLOGO:\n"
            "    O.D.  Esf. -3.25\n"
        )

    recetas = parsear(bloque("-3.75") + bloque("-4.25"))
    resultado = deduplicar([("PRUEBA", "CASO", None, recetas, [])])

    assert len(resultado.clientes[0].recetas) == 2
    assert resultado.visitas_fusionadas == 0


def test_adicion_normaliza_decimales_inconsistentes():
    """``ADD +1.5`` y ``ADD +1.50`` producen el mismo valor normalizado."""
    a = parsear("<< FECHA: 15/02/2016 >>\nLEJOS:\n    O.D. Esf. +0.50\n    ADD +1.5\n")[0]
    b = parsear("<< FECHA: 15/02/2016 >>\nLEJOS:\n    O.D. Esf. +0.50\n    ADD +1.50\n")[0]
    assert a.adicion == b.adicion == "+1.50"


# ===========================================================================
# CASO BORDE 3 · Línea de ojo sin etiqueta Esf.
# ===========================================================================


def test_lentes_contacto_potencia_sin_etiqueta_esf():
    """PRUEBA;PRUEBA: en lentes de contacto la potencia viene como número desnudo."""
    notas = (
        "\n"
        "<< FECHA: 19/08/2019 >>\n"
        "____________________________________________________________\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. -11.50\n"
    )
    receta = parsear(notas, "PRUEBA", "PRUEBA")[0]
    assert receta.lc_od_esf == "-11.50"
    assert receta.lc_oi_esf is None
    assert receta.tipo_lente == "LENTES DE CONTACTO"


def test_dialecto_manuscrito_dos_numeros_desnudos():
    """``O.D: +1.25 -0.50 EN 95``: el primer número es esfera, el segundo cilindro."""
    notas = "LEJOS: O.D: +1.25 -0.50 EN 95\n       O.I: +1.00\n\nAD: +2.00\n"
    receta = parsear(notas, "EJEMPLARES", "BENICIO")[0]
    assert receta.od_lejos_esf == "+1.25"
    assert receta.od_lejos_cil == "-0.50"
    assert receta.od_lejos_eje == "95"
    assert receta.oi_lejos_esf == "+1.00"
    assert receta.adicion == "+2.00"


def test_dialecto_manuscrito_eje_con_a_y_signo_separado():
    """``OD ESF. - 2.25 CIL. - 0.50 A 165``: eje con ``A`` y signo separado."""
    notas = (
        "LEJOS \n"
        "OD ESF. - 2.25 CIL. - 0.50 A 165 \n"
        "OI ESF. - 1.50 CIL. - 0.75 A 15 \n"
        "POLICARBONATO AR VERDE\n"
    )
    receta = parsear(notas, "MUESTRINI", "FILOMENA")[0]
    assert receta.od_lejos_esf == "-2.25"
    assert receta.od_lejos_cil == "-0.50"
    assert receta.od_lejos_eje == "165"
    assert receta.oi_lejos_eje == "15"
    assert Motivo.DIALECTO_MANUSCRITO in motivos_de(receta)


def test_ao_ambos_ojos_se_replica_en_od_y_oi():
    """``AO`` significa ambos ojos: el valor va a OD y a OI."""
    notas = "<< FECHA: 27/10/2014 >>\nLEJOS:\n   AO ESF. +2.75\n"
    receta = parsear(notas)[0]
    assert receta.od_lejos_esf == "+2.75"
    assert receta.oi_lejos_esf == "+2.75"


# ===========================================================================
# CASO BORDE 4 · Color con prefijo numérico
# ===========================================================================


def test_color_con_prefijo_numerico_separa_codigo_y_texto():
    """``Color 3_GRIS ORGANICO``: el ``3`` es un código interno, no el modelo."""
    notas = (
        "<< FECHA: 11/11/2013 >>\n"
        "LEJOS:\n"
        "    O.I.  Esf. +1.50   Color 3_GRIS  ORGANICO \n"
    )
    receta = parsear(notas)[0]
    assert receta.codigo_modelo == "3"
    assert receta.modelo_anteojo == "GRIS ORGANICO"


def test_color_sin_prefijo_no_inventa_codigo():
    """``Color AR VERDE FLEX`` no tiene código: la columna queda nula."""
    notas = (
        "<< FECHA: 08/05/2020 >>\n"
        "CERCA:\n"
        "    O.I.  Esf. +1.75  Cil. +0.75  En 35   Color AR VERDE FLEX\n"
    )
    receta = parsear(notas)[0]
    assert receta.codigo_modelo is None
    assert receta.modelo_anteojo == "AR VERDE FLEX"


# ===========================================================================
# CASO BORDE 5 · Marcador << >> vacío
# ===========================================================================


def test_marcador_vacio_no_genera_visita_fantasma():
    """``<< >>`` es un terminador de bloque, NO una fecha."""
    notas = (
        "<< FECHA: 02/12/2021 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. -0.75\n"
        "Doctor: LENTINI PABLO \n"
        "  << >>\n"
    )
    recetas = parsear(notas)
    assert len(recetas) == 1
    assert recetas[0].fecha == date(2021, 12, 2)


@pytest.mark.parametrize("terminador", ["<< >>", "<< .>>", "<< |>>", "<<  >>", "<< 0>>"])
def test_variantes_de_terminador_con_basura(terminador):
    """Las variantes con basura adentro tampoco son fechas.

    En el archivo de la óptica hay 13.828 marcadores no-fecha: ``<< .>>``
    (2.627), ``<< |>>`` (1.677), ``<<  >>`` (1.027) y ``<< 0>>`` (130). Escribir
    la regla como el literal ``<< >>`` deja afuera ~5.500 de ellos.
    """
    notas = f"<< FECHA: 04/08/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\nOBS  {terminador}\n"
    recetas = parsear(notas)
    assert len(recetas) == 1


def test_terminador_no_ensucia_las_observaciones():
    """El terminador se limpia del texto de la observación."""
    notas = (
        "<< FECHA: 16/03/2011 >>\n"
        "Doctor: VISTAMAR ELENA\n"
        "GRIS 0.75 !!!!!! CERCA   << >>\n"
    )
    receta = parsear(notas)[0]
    assert "<<" not in (receta.observaciones or "")
    assert receta.observaciones == "GRIS 0.75 !!!!!! CERCA"


# ===========================================================================
# CASO BORDE 6 · Registro con <Presupuesto>
# ===========================================================================


def test_presupuesto_se_marca_como_cotizacion():
    """``<Presupuesto>`` antes de la fecha marca cotización, no venta."""
    notas = (
        "<Presupuesto>      << FECHA: 30/01/2023 >>\n"
        "____________________________________________________________\n"
        "LEJOS:\n"
        "    O.D.  Esf. -6.50  Cil. +1.25  En 85\n"
        "    O.I.  Esf. -4.25  Cil. +0.75  En 95\n"
        "BI/MULTIFOCAL: \n"
        "    MONO.STK ORG AR VERDE\n"
    )
    receta = parsear(notas, "X", "X")[0]
    assert receta.tipo_registro == "PRESUPUESTO"
    assert receta.od_lejos_esf == "-6.50"
    assert receta.od_lejos_cil == "+1.25"
    assert receta.od_lejos_eje == "85"
    assert receta.oi_lejos_eje == "95"
    assert receta.modelo_anteojo == "MONO.STK ORG AR VERDE"


def test_sin_presupuesto_es_venta():
    """Sin la etiqueta, la visita es una venta."""
    receta = parsear("<< FECHA: 30/01/2023 >>\nLEJOS:\n    O.D. Esf. -2.50\n")[0]
    assert receta.tipo_registro == "VENTA"


# ===========================================================================
# CASO BORDE 7 · Documento 0 y registros basura
# ===========================================================================


def test_documento_cero_es_ausente_y_nunca_clave():
    """``NUMERODOCUMENTO = 0`` significa ausente, no un documento válido."""
    assert normalizador.normalizar_documento("0") is None
    assert normalizador.normalizar_documento("00000") is None
    assert normalizador.normalizar_documento("") is None
    assert normalizador.normalizar_documento("98765432") == "98765432"


def test_documento_de_menos_de_seis_digitos_es_implausible():
    """Un DNI argentino no tiene menos de 6 dígitos: se trata como ausente."""
    assert normalizador.normalizar_documento("123") is None
    assert normalizador.normalizar_documento("9876543") == "9876543"


def test_registro_basura_se_marca_pero_no_se_borra():
    """``X;X;0`` y ``PRUEBA;PRUEBA;0`` se marcan, NO se eliminan.

    La decisión de borrar historial clínico es de la óptica, no del ETL.
    """
    recetas = parsear("<< FECHA: 04/08/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\n")
    resultado = deduplicar(
        [
            ("X", "X", None, recetas, []),
            ("PRUEBA", "PRUEBA", None, recetas, []),
            ("INVENTADEZ", "TEODORA", "98765432", recetas, []),
        ]
    )
    por_nombre = {c.nombre_completo: c for c in resultado.clientes}
    assert por_nombre["X X"].posible_registro_basura == 1
    assert por_nombre["PRUEBA PRUEBA"].posible_registro_basura == 1
    assert por_nombre["INVENTADEZ TEODORA"].posible_registro_basura == 0
    # Ninguno se borró.
    assert len(resultado.clientes) == 3


# ===========================================================================
# DEDUPLICACIÓN
# ===========================================================================


def test_clave_de_deduplicacion_ignora_acentos_y_mayusculas():
    """``peñaficta;ángel`` y ``PEÑAFICTA;ANGEL`` son la misma persona.

    En el archivo de la óptica hay apellidos en minúscula y con apóstrofo
    (``D´EJEMPLO``).
    """
    assert normalizador.normalizar_clave("peñaficta") == normalizador.normalizar_clave(
        "PEÑAFICTA"
    )
    assert normalizador.normalizar_clave("D´EJEMPLO") == "D EJEMPLO"


def test_fusion_nunca_sobrescribe_agrega_al_historial():
    """Si el cliente ya existe, la visita se suma: no se pisa el historial."""
    primera = parsear("<< FECHA: 12/07/2010 >>\nLEJOS:\n    O.D. Esf. -0.50\n")
    segunda = parsear("<< FECHA: 19/02/2014 >>\nLEJOS:\n    O.D. Esf. -1.75\n")

    resultado = deduplicar(
        [
            ("INVENTAÑO", "LUCRECIA", None, primera, []),
            ("inventaño", "lucrecia", None, segunda, []),
        ]
    )
    assert len(resultado.clientes) == 1
    assert resultado.clientes_fusionados == 1
    assert len(resultado.clientes[0].recetas) == 2


def test_historial_queda_ordenado_por_fecha_ascendente():
    """El historial de cada cliente se ordena cronológicamente."""
    tardia = parsear("<< FECHA: 07/09/2019 >>\nLEJOS:\n    O.D. Esf. -2.25\n")
    temprana = parsear("<< FECHA: 14/05/2012 >>\nLEJOS:\n    O.D. Esf. -1.25\n")

    resultado = deduplicar(
        [
            ("SIMULADEZ", "CASIMIRO", None, tardia, []),
            ("SIMULADEZ", "CASIMIRO", None, temprana, []),
        ]
    )
    fechas = [r.fecha for r in resultado.clientes[0].recetas]
    assert fechas == sorted(fechas)
    assert fechas[0] == date(2012, 5, 14)


def test_documento_cero_no_pisa_uno_valido():
    """Si un registro trae ``0`` y otro un documento real, gana el real."""
    recetas = parsear("<< FECHA: 04/08/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\n")
    resultado = deduplicar(
        [
            ("INVENTADEZ", "TEODORA", None, recetas, []),
            ("INVENTADEZ", "TEODORA", "98765432", recetas, []),
        ]
    )
    assert resultado.clientes[0].documento == "98765432"


def test_documentos_en_conflicto_conservan_el_primero_y_marcan_revision():
    """Dos documentos válidos y distintos: se conserva el primero y se marca.

    Puede ser una homonimia real, y borrar al cliente equivocado es el peor
    error posible de este proyecto.
    """
    recetas = parsear("<< FECHA: 04/08/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\n")
    resultado = deduplicar(
        [
            ("PROBATORIA", "EULALIA", "97000001", recetas, []),
            ("PROBATORIA", "EULALIA", "97000002", recetas, []),
        ]
    )
    cliente = resultado.clientes[0]
    assert cliente.documento == "97000001"
    assert cliente.requiere_revision == 1
    assert Motivo.DOCUMENTO_EN_CONFLICTO in {m for m, _ in cliente.incidencias}
    assert resultado.conflictos_documento == 1


# ===========================================================================
# CICLO DE CORRECCIÓN MANUAL
# ===========================================================================


def test_correccion_manual_pisa_el_valor_parseado_y_marca_origen(tmp_path: Path):
    """Una corrección manual pisa lo parseado y deja ``origen = manual``."""
    receta = parsear("<< FECHA: 23/04/2019 >>\nLEJOS:\n    O.D. Esf. -1.50\n")[0]
    assert receta.od_lejos_esf == "-1.50"
    assert receta.origen == "parseado"

    archivo = tmp_path / "correcciones_manuales.csv"
    archivo.write_text(
        "id_bloque,od_lejos_esf,doctor\n"
        f"{receta.id_bloque},-1.75,DOCTORA EJEMPLO\n",
        encoding="utf-8-sig",
    )

    datos = correcciones.cargar(archivo)
    resultado = correcciones.aplicar({receta.id_bloque: receta}, datos)

    assert receta.od_lejos_esf == "-1.75"
    assert receta.doctor == "DOCTORA EJEMPLO"
    assert receta.origen == "manual"
    assert resultado.aplicadas == 1
    assert resultado.celdas_aplicadas == 2


def test_celda_vacia_no_pisa_lo_parseado(tmp_path: Path):
    """Una celda vacía en el CSV de correcciones no toca nada."""
    receta = parsear(
        "<< FECHA: 23/04/2019 >>\nLEJOS:\n    O.D. Esf. -1.50\nDoctor: ORIGINAL\n"
    )[0]

    archivo = tmp_path / "correcciones_manuales.csv"
    archivo.write_text(
        "id_bloque,od_lejos_esf,doctor\n" f"{receta.id_bloque},-1.75,\n",
        encoding="utf-8-sig",
    )

    datos = correcciones.cargar(archivo)
    correcciones.aplicar({receta.id_bloque: receta}, datos)

    assert receta.od_lejos_esf == "-1.75"
    assert receta.doctor == "ORIGINAL"


def test_id_bloque_es_estable_entre_dos_corridas():
    """El mismo bloque produce el mismo ``id_bloque`` en corridas distintas.

    Es lo que permite que las correcciones manuales sobrevivan a que volvamos
    a exportar de Moebius. El número de línea no serviría: cambia si el export
    cambia de orden.
    """
    notas = (
        "<< FECHA: 08/05/2020 >>\n"
        "CERCA:\n"
        "    O.D.  Esf. +1.75  Cil. +0.75  En 105   D.I. 60\n"
        "Doctor: OCULARI BRUNO \n"
    )
    primera = parsear(notas, "INVENTADEZ", "TEODORA")[0]
    segunda = parsear(notas, "INVENTADEZ", "TEODORA")[0]
    assert primera.id_bloque == segunda.id_bloque
    assert len(primera.id_bloque) == 12

    # Diferencias de espaciado irrelevantes no cambian el identificador.
    con_espacios = notas.replace("CERCA:", "CERCA:   ")
    tercera = parsear(con_espacios, "INVENTADEZ", "TEODORA")[0]
    assert tercera.id_bloque == primera.id_bloque

    # Pero un cliente distinto con el mismo texto sí tiene otro identificador.
    otro = parsear(notas, "INVENTADEZ", "CASIANA")[0]
    assert otro.id_bloque != primera.id_bloque


def test_correccion_huerfana_no_revienta(tmp_path: Path):
    """Un ``id_bloque`` inexistente se registra y se sigue."""
    archivo = tmp_path / "correcciones_manuales.csv"
    archivo.write_text(
        "id_bloque,doctor\nffffffffffff,NO EXISTE\n", encoding="utf-8-sig"
    )

    datos = correcciones.cargar(archivo)
    resultado = correcciones.aplicar({}, datos)

    assert resultado.aplicadas == 0
    assert resultado.huerfanas == ["ffffffffffff"]


def test_archivo_de_correcciones_inexistente_no_falla(tmp_path: Path):
    """Si el archivo no existe, el ETL corre igual sin quejarse."""
    assert correcciones.cargar(tmp_path / "no_existe.csv") == {}


def test_lineas_comentadas_se_ignoran(tmp_path: Path):
    """Las líneas que empiezan con ``#`` son comentarios de la plantilla."""
    archivo = tmp_path / "correcciones_manuales.csv"
    archivo.write_text(
        "# esto es un comentario\n"
        "# a1b2c3d4e5f6,ejemplo\n"
        "id_bloque,doctor\n"
        "abc123def456,REAL\n",
        encoding="utf-8-sig",
    )
    datos = correcciones.cargar(archivo)
    assert datos == {"abc123def456": {"doctor": "REAL"}}


# ===========================================================================
# LECTURA Y ENCODING
# ===========================================================================


def test_maquina_de_estados_no_se_rompe_con_punto_y_coma_en_la_nota(tmp_path: Path):
    """Una nota con ``;`` no debe abrir un cliente nuevo.

    En las notas hay renglones de texto libre con punto y coma, como
    ``CAMBIO ; ARMAZON EQUIVOCADO``. El criterio de inicio es estructural
    (``APELLIDO;NOMBRE;DÍGITOS;``), no un conteo de puntos y coma.
    """
    archivo = tmp_path / "crudo.csv"
    archivo.write_text(
        "APELLIDO;NOMBRE;NUMERODOCUMENTO;NOTAS\r\n"
        "SIMULADEZ;CASIMIRO;0;<< FECHA: 10/10/2018 >>\r\n"
        "CAMBIO ; ARMAZON EQUIVOCADO\r\n"
        "LEJOS:\r\n"
        "    O.D.  Esf. -1.00\r\n"
        "PROBATORIA;CLEMENTINA;123456789;<< FECHA: 05/06/2019 >>\r\n",
        encoding="cp1252",
    )
    registros = lector.leer_registros(archivo)

    assert len(registros) == 2
    assert registros[0].apellido == "SIMULADEZ"
    assert "CAMBIO ; ARMAZON EQUIVOCADO" in registros[0].texto_notas
    assert registros[1].apellido == "PROBATORIA"


def test_deteccion_de_encoding_cp1252(tmp_path: Path):
    """El encoding se detecta, no se asume."""
    archivo = tmp_path / "crudo.csv"
    archivo.write_bytes(
        "APELLIDO;NOMBRE;NUMERODOCUMENTO;NOTAS\r\npeñaficta;ángeles;0;nota\r\n".encode(
            "cp1252"
        )
    )
    assert lector.detectar_encoding(archivo) in ("cp1252", "latin-1")
    registros = lector.leer_registros(archivo)
    assert registros[0].apellido == "peñaficta"


# ===========================================================================
# NORMALIZACIÓN · NADA SE INVENTA
# ===========================================================================


def test_fecha_imposible_devuelve_nulo_no_una_fecha_inventada():
    """``31/02/2015`` no existe: devuelve ``None``, no el 28/02 ni el 03/03."""
    assert normalizador.normalizar_fecha("31/02/2015") is None
    assert normalizador.normalizar_fecha("30/01/2023") == date(2023, 1, 30)


def test_eje_fuera_de_rango_devuelve_nulo():
    """El eje va de 0 a 180 grados. 250 es un error de tipeo."""
    assert normalizador.normalizar_eje("250") is None
    assert normalizador.normalizar_eje("105") == "105"
    assert normalizador.normalizar_eje("0") == "0"
    assert normalizador.normalizar_eje("180") == "180"


def test_dioptria_fuera_de_rango_devuelve_nulo():
    """Un valor de +1500 dioptrías es un precio, no una graduación."""
    assert normalizador.normalizar_decimal("+1500") is None
    assert normalizador.normalizar_decimal("-6.50") == "-6.50"


def test_distancia_interpupilar_fuera_de_rango_devuelve_nulo():
    """Una D.I. de 200 mm no es anatómicamente posible."""
    assert normalizador.validar_di("200") is None
    assert normalizador.validar_di("60") == "60.00"


def test_fecha_sin_visita_no_se_completa_por_interpolacion():
    """Una visita sin fecha queda con fecha nula y se marca.

    No se le asigna la fecha de la visita anterior ni la del cliente: son
    recetas médicas y un dato inventado puede terminar en un par de anteojos
    mal graduado.
    """
    receta = parsear("LEJOS \nOD ESF. -1.25\n")[0]
    assert receta.fecha is None
    assert Motivo.SIN_FECHA in motivos_de(receta)


# ===========================================================================
# DOCTOR
# ===========================================================================


def test_copia_ant_en_uso_no_se_toma_como_doctor():
    """``Doctor: COPIA ANT.EN USO`` es una nota, no un médico.

    Son ~4.700 casos en el archivo de la óptica. Tomarlos como médico envenena
    cualquier recuento de derivaciones por doctor.
    """
    receta = parsear(
        "<< FECHA: 18/11/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\n"
        "Doctor: COPIA ANT.EN USO\n"
    )[0]
    assert receta.doctor is None
    assert "COPIA ANT.EN USO" in (receta.observaciones or "")


def test_doctor_real_se_conserva():
    """Un nombre de médico normal sí va a la columna ``doctor``."""
    receta = parsear(
        "<< FECHA: 18/11/2018 >>\nLEJOS:\n    O.D. Esf. -1.00\nDoctor: OCULARI BRUNO \n"
    )[0]
    assert receta.doctor == "OCULARI BRUNO"


def test_observacion_despues_del_doctor_no_se_toma_como_modelo():
    """La línea después de ``Doctor:`` es observación, aunque haya BI/MULTIFOCAL.

    ``FLEX AR VERDE PARA LEER.`` debe ir a observaciones, no a
    ``modelo_anteojo``.
    """
    notas = (
        "<< FECHA: 08/05/2020 >>\n"
        "CERCA:\n"
        "    O.I.  Esf. +1.75  Cil. +0.75  En 35   Color AR VERDE FLEX\n"
        "BI/MULTIFOCAL: \n"
        "  D.I. Cerca 60\n"
        "Doctor: OCULARI BRUNO \n"
        "FLEX AR VERDE PARA LEER.  << >>\n"
    )
    receta = parsear(notas, "INVENTADEZ", "TEODORA")[0]
    assert receta.modelo_anteojo == "AR VERDE FLEX"
    assert receta.observaciones == "FLEX AR VERDE PARA LEER."
    assert receta.di_cerca == "60.00"


# ===========================================================================
# D.I. Y ALTURA
# ===========================================================================


def test_di_calificada_y_generica_van_a_columnas_distintas():
    """``D.I. 64``, ``D.I. Lejos 65.00`` y ``D.I. Cerca 61`` son tres columnas."""
    notas = (
        "<< FECHA: 04/08/2018 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. -2.00   D.I. 64\n"
        "BI/MULTIFOCAL: \n"
        "    BI.FLAP TOP  D.I. Lejos 65.00  D.I. Cerca 61  Altura 18.00\n"
    )
    receta = parsear(notas)[0]
    assert receta.di == "64.00"
    assert receta.di_lejos == "65.00"
    assert receta.di_cerca == "61.00"
    assert receta.altura == "18.00"
    assert receta.modelo_anteojo == "BI.FLAP TOP"


def test_lente_de_contacto_torica_guarda_cilindro_y_eje():
    """Una lente tórica trae cilindro y eje, y los dos se guardan.

    El esquema original sólo tenía la esfera, así que el parser leía el
    cilindro y el eje y después los descartaba porque no tenían dónde ir.
    """
    notas = (
        "<< FECHA: 17/03/2010 >>\n"
        "LENTES DE CONTACTO:\n"
        "    O.D.  Esf. -2.75  Cil. -1.00  En 70\n"
        "    O.I.  Esf. -3.50  Cil. -1.50  En 160\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf == "-2.75"
    assert receta.lc_od_cil == "-1.00"
    assert receta.lc_od_eje == "70"
    assert receta.lc_oi_esf == "-3.50"
    assert receta.lc_oi_cil == "-1.50"
    assert receta.lc_oi_eje == "160"
    # Nada de esto puede haber caído en columnas de anteojos.
    assert receta.od_lejos_cil is None
    assert receta.od_lejos_eje is None


def test_doble_prescripcion_guarda_las_dos_completas():
    """Médico -7.50, contactólogo -6.75: las dos son ciertas y las dos se guardan.

    La lente apoya sobre el ojo y el anteojo está a 12 mm, así que la potencia
    efectiva no es la misma.
    """
    notas = (
        "<< FECHA: 17/03/2010 >>\n"
        "____________________________________________________________\n"
        "RP. MEDICO:\n"
        "    O.D.  Esf. -7.50  Cil. -1.75  En 90\n"
        "    O.I.  Esf. -0.50  Cil. -1.00  En 85\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -6.75  Cil. -1.75  En 90\n"
        "    O.I.  Esf. -0.50  Cil. -1.00  En 80\n"
    )
    receta = parsear(notas)[0]

    # Lo que indicó el médico.
    assert receta.lc_med_od_esf == "-7.50"
    assert receta.lc_med_od_cil == "-1.75"
    assert receta.lc_med_od_eje == "90"
    assert receta.lc_med_oi_esf == "-0.50"

    # Lo que adaptó el contactólogo. NO se pierde.
    assert receta.lc_cont_od_esf == "-6.75"
    assert receta.lc_cont_od_cil == "-1.75"
    assert receta.lc_cont_oi_eje == "80"

    # La vigente es la del contactólogo: regla confirmada por el encargado de
    # la óptica el 05/10/2026. Es la lente que la persona efectivamente usa.
    assert extractor.PRESCRIPCION_VIGENTE == "CONTACTOLOGO"
    assert receta.lc_od_esf == "-6.75"
    assert receta.lc_oi_eje == "80"
    assert receta.lc_prescriptor_vigente == "CONTACTOLOGO"


def test_regresion_el_cilindro_de_contacto_no_cae_en_od_lejos_cil():
    """Regresión: el cilindro leído bajo `RP. MEDICO:` es de lentes de contacto.

    Nunca puede terminar en `od_lejos_cil` ni en ninguna otra columna de
    anteojos. Es la contaminación entre productos.
    """
    notas = (
        "<< FECHA: 17/03/2010 >>\n"
        "RP. MEDICO:\n"
        "    O.D.  Esf. -7.50  Cil. -1.75  En 90\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -6.75  Cil. -1.75  En 90\n"
    )
    receta = parsear(notas)[0]
    for columna in (
        "od_lejos_esf", "od_lejos_cil", "od_lejos_eje",
        "oi_lejos_esf", "oi_lejos_cil", "oi_lejos_eje",
        "od_cerca_esf", "od_cerca_cil", "od_cerca_eje",
        "oi_cerca_esf", "oi_cerca_cil", "oi_cerca_eje",
    ):
        assert getattr(receta, columna) is None, f"{columna} quedó contaminada"
    assert receta.lc_od_cil == "-1.75"


def test_una_sola_prescripcion_no_se_completa_con_la_otra():
    """Si sólo hay `RP. MEDICO:`, las columnas del contactólogo quedan nulas.

    Copiar los valores del médico ahí sería inventar una adaptación que nadie
    hizo.
    """
    notas = (
        "<< FECHA: 26/02/2015 >>\n"
        "RP. MEDICO:\n"
        "    O.D.  Esf. -2.00  Cil. -1.25  En 170\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_med_od_esf == "-2.00"
    assert receta.lc_cont_od_esf is None
    assert receta.lc_cont_od_cil is None
    assert receta.lc_prescriptor_vigente == "MEDICO"


def test_solo_contactologo_llena_las_vigentes_y_lo_declara():
    """Con sólo el contactólogo, las vigentes las llena él y la columna lo dice."""
    notas = (
        "<< FECHA: 26/02/2015 >>\n"
        "RP. CONTACTOLOGO:\n"
        "    O.D.  Esf. -1.75\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_cont_od_esf == "-1.75"
    assert receta.lc_med_od_esf is None
    assert receta.lc_od_esf == "-1.75"
    assert receta.lc_prescriptor_vigente == "CONTACTOLOGO"


def test_seccion_sin_etiquetar_queda_sin_especificar():
    """`LENTES DE CONTACTO:` suelta no se atribuye a ningún prescriptor."""
    notas = (
        "<< FECHA: 19/08/2019 >>\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. -11.50\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf == "-11.50"
    assert receta.lc_prescriptor_vigente == "SIN_ESPECIFICAR"
    assert receta.lc_med_od_esf is None
    assert receta.lc_cont_od_esf is None


def test_encabezado_de_contacto_con_ruido_pegado_se_reconoce():
    """`RP. MEDICO:NO ES DE ESTE CLIENTE` es un encabezado, no texto suelto.

    Sin reconocerlo, la sección no se abre y las líneas de ojo caen a columnas
    de anteojos.
    """
    notas = (
        "<< FECHA: 13/09/2013 >>\n"
        "RP. MEDICO:NO ES DE ESTE CLIENTE !!!!!\n"
        "    O.D.  Esf. -3.75  Cil. -0.25  En 25\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_med_od_esf == "-3.75"
    assert receta.lc_med_od_cil == "-0.25"
    assert receta.od_lejos_esf is None
    # La nota pegada al encabezado no se pierde.
    assert "ESTE CLIENTE" in (receta.observaciones or "")


def test_rp_generico_no_se_atribuye_al_medico():
    """`R.P.` a secas no dice quién firmó: no se le adjudica al médico."""
    receta = parsear("<< FECHA: 03/03/2020 >>\nR.P.: OD ESF. -2.25 CIL. -0.50 A 40\n")[0]
    assert receta.lc_med_od_esf is None
    assert receta.lc_cont_od_esf is None
    assert receta.lc_od_esf == "-2.25"
    assert receta.lc_prescriptor_vigente == "SIN_ESPECIFICAR"


def test_marca_y_tipo_de_lente_de_contacto():
    """``Marca L.C.`` y ``Tipo L.C.`` se separan en columnas propias."""
    notas = (
        "<< FECHA: 04/08/2018 >>\n"
        "LENTES DE CONTACTO:\n"
        "      O.D. -3.25\n"
        "      Ø  14.2\n"
        "      Tipo L.C. CONVENCIONALES      Marca L.C. ACUVUE 2\n"
    )
    receta = parsear(notas)[0]
    assert receta.lc_od_esf == "-3.25"
    assert receta.lc_od_diametro == receta.lc_oi_diametro == "14.20"
    assert receta.lc_tipo == "CONVENCIONALES"
    assert receta.lc_marca == "ACUVUE 2"


# ===========================================================================
# TOLERANCIA A FALLOS
# ===========================================================================


def test_bloque_vacio_no_genera_receta_fantasma():
    """Un bloque de notas sin contenido no produce ninguna receta."""
    assert parsear("\n\n\n   \n") == []


def test_cliente_sin_ojo_izquierdo_no_aborta():
    """Falta el O.I.: se inserta nulo y se sigue."""
    receta = parsear("<< FECHA: 04/08/2018 >>\nLEJOS:\n    O.D. Esf. -2.75\n")[0]
    assert receta.od_lejos_esf == "-2.75"
    assert receta.oi_lejos_esf is None


def test_seccion_desconocida_se_reporta_no_se_descarta():
    """Un encabezado que no modelamos se lista en revisar_manual."""
    notas = (
        "<< FECHA: 04/08/2018 >>\n"
        "RP. OFTALMOLOGO:\n"
        "    O.D. Esf. -1.00\n"
    )
    receta = parsear(notas)[0]
    assert Motivo.SECCION_DESCONOCIDA in motivos_de(receta)


# ===========================================================================
# VENTA DE ANTEOJOS DE SOL · marcador explícito en el texto
# ===========================================================================
#
# Regla aportada por los empleados de la óptica y confirmada contra el archivo:
# cuando el texto DICE que la compra fue de anteojos de sol, el bloque deja de
# ser un caso dudoso. Los anteojos de sol no llevan graduación, así que el
# sistema viejo no tenía receta que registrar.
#
# Es lo contrario del caso de los bloques vacíos, donde se DESCARTÓ inferir la
# venta desde la ausencia de datos. Acá el dato está escrito.


#: Las 10 grafías que existen en el archivo de la óptica, con su frecuencia.
#: Salieron de un barrido del archivo.
VARIANTES_ANTEOJO_SOL = [
    ("ANT SOL", 110),
    ("ANT.SOL", 20),
    ("ANTEOJO DE SOL", 13),
    ("ANTEOJO SOL", 6),
    ("ANT DE SOL", 2),
    ("ANT. SOL", 2),
    ("ANTEOJOS DE SOL", 2),
    ("ANT .SOL", 1),
    ("LENTE DE SOL", 3),
    ("LENTES DE SOL", 2),
]


@pytest.mark.parametrize(
    "variante",
    [v for v, _ in VARIANTES_ANTEOJO_SOL],
    ids=[v for v, _ in VARIANTES_ANTEOJO_SOL],
)
def test_cada_variante_se_reconoce_como_venta_de_anteojos_de_sol(variante):
    """Las 10 grafías del archivo se reconocen como venta de sol.

    Un test por variante, como pidió la óptica: si mañana alguien toca la regex
    y rompe una sola grafía, el test que falla dice exactamente cuál.
    """
    notas = f"<< FECHA: 21/11/2016 >>\n____________________\n\n {variante} MODELO AVIADOR\n"
    receta = parsear(notas)[0]

    assert extractor.es_venta_anteojo_sol(receta)
    # Deja de ser un caso dudoso.
    assert Motivo.BLOQUE_SIN_ESTRUCTURA not in motivos_de(receta)
    # Y el dato queda en observaciones, con la descripción completa.
    assert receta.observaciones is not None
    assert "AVIADOR" in receta.observaciones


@pytest.mark.parametrize("variante", [v.lower() for v, _ in VARIANTES_ANTEOJO_SOL])
def test_las_variantes_en_minuscula_tambien(variante):
    """El marcador es insensible a mayúsculas: en el archivo hay `ant. sol`."""
    notas = f"<< FECHA: 21/11/2016 >>\n\n {variante}\n"
    assert extractor.es_venta_anteojo_sol(parsear(notas)[0])


# --- Control de falsos positivos -------------------------------------------


def test_doctor_con_nombre_soledad_no_es_anteojo_de_sol():
    """`Doctor: QUIMERA MARIA SOLEDAD` NO se clasifica como anteojo de sol.

    Es el test negativo que pidió la óptica. `SOLEDAD` aparece 188 veces en el
    archivo; un patrón flojo sobre `sol` se las lleva todas por delante.
    """
    notas = (
        "<< FECHA: 11/11/2013 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. +1.50\n"
        "Doctor: QUIMERA MARIA SOLEDAD\n"
    )
    receta = parsear(notas)[0]
    assert not extractor.es_venta_anteojo_sol(receta)
    assert receta.doctor == "QUIMERA MARIA SOLEDAD"


@pytest.mark.parametrize(
    "texto",
    [
        "Doctor: QUIMERA MARIA SOLEDAD",
        "MARIA SOL",              # nombre propio: 31 casos en el archivo
        "SOLO LEJOS",             # 697 casos
        "ANT.SOLEDAD",
        "ANTIRREF SOL",           # antirreflejo solar, no un anteojo
        "ANTONIETA SOL",          # nombre propio
        "LENTE SOL",              # sin "DE": no existe en el archivo
        "AN SOL",                 # probable tipeo, deliberadamente afuera
        "EL DE SOL",              # referencia sin sustantivo
        "TRAER DE SOL",
        "ARREGLO DE SOL",
        "Doctor: SOLANGE INVENTADA",
        "COLOR SOL",              # cristal solar graduado (233 casos)
        "LAB. SOL",               # ídem (304 casos)
        "PROMO SOL",              # ídem (110 casos)
        "MONO.ORG.LAB.SOL GRIS DEGRADE",
    ],
)
def test_no_matchea_los_falsos_positivos_conocidos(texto):
    """Ninguna de las trampas de `SOL` del archivo dispara el marcador."""
    assert patrones.MARCADOR_ANTEOJO_SOL.search(texto) is None


# --- Exclusiones: el marcador está pero no es una venta ---------------------


@pytest.mark.parametrize(
    "texto",
    [
        "ANT SOL RECETADO.",            # anteojo de sol CON graduación
        "ANTEOJO DE SOL EN USO",        # uno que ya tiene, no una compra
        "SE EXTRAVIO ANT SOL.",         # extravío
        "ANT SOL GRADUADO",
        "ANT SOL CON GRAD. LEJOS",
    ],
)
def test_contextos_excluidos_no_cuentan_como_venta(texto):
    """Con el marcador presente pero en contexto de exclusión, no es una venta.

    Ante la duda el bloque se queda en revisión, que es el lado seguro del
    error: un caso visible es mejor que una venta inventada.
    """
    notas = f"<< FECHA: 28/04/2017 >>\n____________________\n\n {texto}\n"
    receta = parsear(notas)[0]
    assert not extractor.es_venta_anteojo_sol(receta)
    assert Motivo.BLOQUE_SIN_ESTRUCTURA in motivos_de(receta)


def test_anteojo_de_sol_recetado_es_una_receta_comun():
    """Un anteojo de sol con graduación NO es venta de anteojos de sol.

    Es una receta común cuya observación aclara que el cristal es solar. El
    dato queda donde estaba y el bloque no se reclasifica.
    """
    notas = (
        "<< FECHA: 12/12/2018 >>\n"
        "LEJOS:\n"
        "    O.D.  Esf. -0.75  Cil. +0.50  En 60   D.I. 65\n"
        "BI/MULTIFOCAL: \n"
        "    MONO.ORG.LAB.SOL GRIS DEGRADE\n"
        "1 ANT DE SOL Y 2 BLANCOS CON MARCO PROPIO\n"
    )
    receta = parsear(notas)[0]
    assert not extractor.es_venta_anteojo_sol(receta)
    assert receta.od_lejos_esf == "-0.75"
    # La mención igual queda registrada como observación de la receta.
    assert "ANT DE SOL" in (receta.observaciones or "")


def test_bloque_vacio_sin_marcador_no_es_anteojo_de_sol():
    """Sin marcador explícito NO se infiere nada.

    Un bloque vacío sigue siendo un caso dudoso: la regla captura un marcador
    escrito, no la ausencia de datos.
    """
    notas = "<< FECHA: 15/05/2011 >>\n____________________________\n\n\n"
    receta = parsear(notas)[0]
    assert not extractor.es_venta_anteojo_sol(receta)
    assert Motivo.BLOQUE_SIN_ESTRUCTURA in motivos_de(receta)


# --- Qué motivos resuelve y cuáles no --------------------------------------


def test_tambien_resuelve_el_dialecto_manuscrito():
    """Un bloque manuscrito con el marcador deja de estar en revisión por eso."""
    receta = parsear("ANT SOL POLARIZADO MARRON\n")[0]
    assert extractor.es_venta_anteojo_sol(receta)
    assert Motivo.BLOQUE_SIN_ESTRUCTURA not in motivos_de(receta)
    assert Motivo.DIALECTO_MANUSCRITO not in motivos_de(receta)


def test_los_demas_motivos_sobreviven():
    """Si el bloque tenía otro motivo pendiente, sigue en revisión por ése.

    Bloque manuscrito, con marcador y sin fecha: el marcador resuelve dos
    motivos, pero `sin_fecha` queda.
    """
    receta = parsear("ANT SOL POLARIZADO MARRON\n")[0]
    assert receta.fecha is None
    assert Motivo.SIN_FECHA in motivos_de(receta)


def test_no_pisa_una_observacion_existente():
    """La descripción se agrega con `|`, nunca reemplaza lo que ya había."""
    notas = (
        "<< FECHA: 07/07/2008 >>\n"
        "____________________\n"
        "ANT.SOL CARRERA \n"
        " PAGO CON TARJETA \n"
    )
    receta = parsear(notas)[0]
    assert receta.observaciones == "ANT.SOL CARRERA | PAGO CON TARJETA"
    assert extractor.es_venta_anteojo_sol(receta)
