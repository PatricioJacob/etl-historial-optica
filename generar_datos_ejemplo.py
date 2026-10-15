# -*- coding: utf-8 -*-
"""
Genera los datos de ejemplo de la demo: ``datos_ejemplo/``.

Todo lo que sale de acá es INVENTADO: clientes, documentos, profesionales,
fechas, graduaciones y observaciones. Lo único que se copia del sistema real es
el FORMATO del export de Moebius, que es lo que hace difícil el problema:

* CSV separado por ``;``, en ``cp1252`` y con saltos de línea ``CRLF``;
* el campo Notas es multilínea y va SIN comillas, así que el CSV está "roto"
  para cualquier lector estándar;
* cada visita empieza con ``<< FECHA: dd/mm/aaaa >>`` y a veces termina con
  ``<< >>`` o variantes con basura (``<< .>>``, ``<< |>>``);
* las secciones ``LEJOS:``, ``CERCA:``, ``BI/MULTIFOCAL:``, ``LENTES DE
  CONTACTO:``, ``RP. MEDICO:``, ``RP. CONTACTOLOGO:``, ``Tratamientos:``,
  ``Doctor:``, ``Color``, ``Marca L.C.`` y ``Tipo L.C.``;
* el documento viene en ``0`` en la mayoría de los registros.

Además de ~200 clientes al azar (con semilla fija, para que el resultado sea
siempre el mismo), agrega a mano al menos un caso de cada motivo de revisión
del ETL y un ``correcciones_manuales.csv`` chico.

Uso:

    python generar_datos_ejemplo.py
"""

from __future__ import annotations

import random
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CARPETA = RAIZ / "datos_ejemplo"
ARCHIVO_PLANILLA = CARPETA / "planilla_notas.csv"
ARCHIVO_CORRECCIONES = CARPETA / "correcciones_manuales.csv"

#: Semilla fija: con la misma semilla, los mismos datos byte a byte.
SEMILLA = 20261015

#: Clientes generados al azar. Los casos especiales se suman aparte.
CANTIDAD_CLIENTES = 190

CABECERA = "APELLIDO;NOMBRE;NUMERODOCUMENTO;NOTAS"
SEPARADOR = "_" * 60
SANGRIA_FECHA = " " * 19

# ---------------------------------------------------------------------------
# Vocabulario inventado
# ---------------------------------------------------------------------------

#: Apellidos claramente ficticios: una raíz de "prueba" y una terminación.
RAICES = ["INVENT", "FICT", "SIMUL", "PROB", "MUESTR", "EJEMPL",
          "QUIMER", "FANTAS", "TESTOL", "DEMOSTR", "IMAGIN", "SUPUEST"]
TERMINACIONES = ["ADEZ", "ARETTI", "OLINI", "IAGA", "OVICH",
                 "UGUEZ", "ASTEGUI", "ORENA", "ANI", "ELLI"]
APELLIDOS = [r + t for r in RAICES for t in TERMINACIONES] + ["PEÑAFICTA", "INVENTAÑO"]

NOMBRES = [
    "MARIA", "ANA", "LAURA", "SILVIA", "GRACIELA", "MARTA", "CLARA", "JULIETA",
    "LUCIA", "ROSA", "ELENA", "BEATRIZ", "NORA", "CAROLINA", "VALERIA", "SOFIA",
    "JUAN", "CARLOS", "JORGE", "RAUL", "PABLO", "MIGUEL", "SERGIO", "DIEGO",
    "MARTIN", "LUIS", "OSCAR", "HUGO", "TOMAS", "FEDERICO", "ANDRES", "RUBEN",
    "MARIA LAURA", "JUAN PABLO", "ANA MARIA", "LUIS ALBERTO",
]

#: Profesionales inventados. Uno lleva SOLEDAD a propósito: es la trampa que
#: el marcador de anteojos de sol no tiene que confundir.
PROFESIONALES = [
    "OCULARI BRUNO", "VISTAMAR ELENA", "LENTINI PABLO",
    "QUIMERA MARIA SOLEDAD", "MIRADOR JOAQUIN", "PUPILETTI CLARA",
]

MODELOS = ["BLANCO  ORGANICO BCO.", "1_BLANCO  ORGANICO", "2_AR LITE",
           "AR VERDE FLEX", "FOTOCROMATICO ORGANICO", "POLICARBONATO AR"]
MODELOS_BI = ["BI.FLAP TOP ORG BLANCO", "MONO.STK ORG AR VERDE", "MULTIF.ORG AR CONFORT"]
TRATAMIENTOS = ["TINTE", "TINTE, TINTE", "ANTIRREFLEJO"]
MARCAS_LC = ["SOFLENS", "AIR OPTIX", "ACUVUE OASYS", "BIOFINITY", "BIOMEDICS 55", "WAICON 2"]
MARCAS_LC_MULTIFOCAL = ["SOFLENS MULTIFOCAL", "AIR OPTIX MULTIFOCAL"]
TIPOS_LC = ["DESCARTABLES", "CONVENCIONALES"]
NIVELES = ["HIGH", "MED", "LOW", "high"]
OBSERVACIONES = [
    "RETIRA EL VIERNES", "USA ARMAZON PROPIO", "SEÑA CON TARJETA",
    "CONTROL EN UN AÑO", "ARMAZON DE LA CASA", "CAMBIO DE CRISTALES",
    "PAGA EN 3 CUOTAS", "LLEVA ESTUCHE NUEVO",
]
NOTAS_SUELTAS = [
    "CONSULTA POR PRESUPUESTO DE ARMAZON", "ARREGLO DE PATILLA SIN CARGO",
    "PASA A RETIRAR EL JUEVES", "CAMBIO DE TORNILLOS", "AJUSTE DE ARMAZON",
]
TERMINADORES = ["<< >>", "<< .>>", "<< |>>", "<<  >>"]


# ---------------------------------------------------------------------------
# Piezas de una visita
# ---------------------------------------------------------------------------


def dioptria(r: random.Random, minimo: float, maximo: float) -> str:
    """Un valor en pasos de 0,25, con signo y dos decimales; nunca 0."""
    while True:
        valor = r.randint(round(minimo * 4), round(maximo * 4)) / 4
        if valor:
            return f"{valor:+.2f}"


def fecha(r: random.Random, desde: int = 2004, hasta: int = 2023) -> str:
    """Una fecha posible ``dd/mm/aaaa``."""
    return f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/{r.randint(desde, hasta)}"


def ojo(etiqueta: str, esfera: str, cilindro: str | None = None,
        eje: int | None = None, extra: str = "", sangria: str = "    ") -> str:
    """Renglón de ojo con el formato de Moebius."""
    texto = f"{sangria}{etiqueta}  Esf. {esfera}"
    if cilindro is not None:
        texto += f"  Cil. {cilindro}  En {eje}"
    return texto + extra


def anteojos(r: random.Random) -> list[str]:
    """Visita de anteojos: monofocal de lejos o de cerca, o multifocal."""
    lineas: list[str] = []
    con_cilindro = r.random() < 0.5
    esf_od, esf_oi = dioptria(r, -6, 4), dioptria(r, -6, 4)
    cil_od = dioptria(r, 0.25, 2.5) if con_cilindro else None
    cil_oi = dioptria(r, 0.25, 2.5) if con_cilindro else None
    eje_od, eje_oi = r.randint(0, 180), r.randint(0, 180)
    modelo = f"   Color {r.choice(MODELOS)}" if r.random() < 0.7 else ""
    di = f"   D.I. {r.randint(56, 68)}" if r.random() < 0.4 else ""
    tipo = r.random()

    if tipo < 0.55:
        lineas.append(r.choice(["LEJOS:", "LEJOS:", "CERCA:"]))
        lineas.append(ojo("O.D.", esf_od, cil_od, eje_od, di))
        lineas.append(ojo("O.I.", esf_oi, cil_oi, eje_oi, modelo))
        if r.random() < 0.25:
            lineas.append(f"      Tratamientos: {r.choice(TRATAMIENTOS)}")
    else:
        adicion = r.choice(["+1.50", "+2.00", "+2.5", "+2.50", "+3.00"])
        suma = float(adicion)
        lineas.append("LEJOS:")
        lineas.append(ojo("O.D.", esf_od, cil_od, eje_od))
        lineas.append(ojo("O.I.", esf_oi, cil_oi, eje_oi))
        lineas.append(f"    ADD {adicion}")
        lineas.append("CERCA:")
        lineas.append(ojo("O.D.", f"{float(esf_od) + suma:+.2f}", cil_od, eje_od))
        lineas.append(ojo("O.I.", f"{float(esf_oi) + suma:+.2f}", cil_oi, eje_oi))
        lineas.append("BI/MULTIFOCAL: ")
        armado = f"    {r.choice(MODELOS_BI)}  D.I. Lejos {r.randint(58, 68)}.00"
        if r.random() < 0.4:
            armado += f"  D.I. Cerca {r.randint(55, 64)}"
        armado += f"  Altura {r.choice([14, 16, 18, 20])}.00"
        lineas.append(armado)
    return lineas


def lentes_de_contacto(r: random.Random) -> list[str]:
    """Visita de lentes de contacto: receta del médico, del contactólogo y lente."""
    lineas: list[str] = []
    esf_od, esf_oi = dioptria(r, -8, 3), dioptria(r, -8, 3)
    torica = r.random() < 0.3
    cil = dioptria(r, -2.5, -0.5) if torica else None
    eje_od, eje_oi = r.randint(0, 180), r.randint(0, 180)

    if r.random() < 0.8:
        lineas.append("RP. MEDICO:")
        lineas.append(ojo("O.D.", esf_od, cil, eje_od))
        lineas.append(ojo("O.I.", esf_oi, cil, eje_oi))
    if r.random() < 0.6:
        # El contactólogo adapta: suele bajar un cuarto o medio punto.
        ajuste = r.choice([0.25, 0.5])
        lineas.append("RP. CONTACTOLOGO:")
        lineas.append(ojo("O.D.", f"{float(esf_od) + ajuste:+.2f}", cil, eje_od))
        lineas.append(ojo("O.I.", f"{float(esf_oi) + ajuste:+.2f}", cil, eje_oi))

    lineas.append("LENTES DE CONTACTO:")
    multifocal = r.random() < 0.3
    if multifocal:
        potencia = dioptria(r, 0.5, 3.5)
        nivel = r.choice(NIVELES)
        if r.random() < 0.5:
            lineas.append(f"      AO {potencia} / {nivel}")
        else:
            lineas.append(f"      O.D. {potencia}/{nivel}")
            lineas.append(f"      O.I. {potencia}/{nivel}")
        marca = r.choice(MARCAS_LC_MULTIFOCAL)
    else:
        if r.random() < 0.5:
            lineas.append(f"      O.D. {esf_od}")
            lineas.append(f"      O.I. {esf_oi}")
        marca = r.choice(MARCAS_LC)
    if r.random() < 0.3:
        lineas.append(f"      O.D. CB {r.choice(['8.40', '8.50', '8.60', '8.70'])}")
        lineas.append(f"      Ø  {r.choice(['14.0', '14.2', '14.5'])}")
    cantidad = f" {r.choice(['1 CAJA', '2 CAJAS', '1 PAR'])}" if r.random() < 0.3 else ""
    if r.random() < 0.5:
        lineas.append(f"      Tipo L.C. {r.choice(TIPOS_LC)}      Marca L.C. {marca}{cantidad}")
    else:
        lineas.append(f"      Marca L.C. {marca}{cantidad}")
    return lineas


def cierre(r: random.Random, con_doctor: float = 0.7) -> list[str]:
    """Línea ``Doctor:`` (o la nota que la reemplaza) y una observación."""
    lineas: list[str] = [""]
    sorteo = r.random()
    if sorteo < con_doctor:
        lineas.append(f"Doctor: {r.choice(PROFESIONALES)}")
    elif sorteo < con_doctor + 0.1:
        lineas.append("Doctor: COPIA ANT.EN USO")
    if r.random() < 0.4:
        lineas.append(r.choice(OBSERVACIONES))
    if r.random() < 0.3:
        lineas[-1] = f"{lineas[-1]}   {r.choice(TERMINADORES)}"
    return lineas


def visita_al_azar(r: random.Random) -> tuple[list[str], bool]:
    """Contenido de una visita y si es un presupuesto."""
    sorteo = r.random()
    if sorteo < 0.62:
        cuerpo = anteojos(r) + cierre(r)
    elif sorteo < 0.85:
        cuerpo = lentes_de_contacto(r) + cierre(r, con_doctor=0.4)
    elif sorteo < 0.93:
        cuerpo = ["", f" {r.choice(NOTAS_SUELTAS)}"]
    else:
        cuerpo = ["", f" ANT SOL {r.choice(['MODELO AVIADOR', 'POLARIZADO MARRON', 'CARRERA'])}"]
    return cuerpo, r.random() < 0.06


# ---------------------------------------------------------------------------
# Registros
# ---------------------------------------------------------------------------


def registro(apellido: str, nombre: str, documento: str,
             visitas: list[tuple[str, list[str], bool]], r: random.Random) -> list[str]:
    """Arma las líneas de un registro: cabecera del cliente y sus visitas.

    Args:
        visitas: Tuplas ``(fecha, cuerpo, es_presupuesto)``.
    """
    lineas: list[str] = []
    for numero, (dia, cuerpo, presupuesto) in enumerate(visitas):
        marcador = f"<< FECHA: {dia} >>"
        if presupuesto:
            marcador = f"<Presupuesto>      {marcador}"
        if numero == 0 and r.random() < 0.6:
            lineas.append(f"{apellido};{nombre};{documento};{marcador}")
        else:
            if numero == 0:
                lineas.append(f"{apellido};{nombre};{documento};")
            lineas += ["", "", "", f"{SANGRIA_FECHA}{marcador}"]
        lineas.append(SEPARADOR)
        lineas += cuerpo
    lineas += ["", "", ""]
    return lineas


def registro_crudo(apellido: str, nombre: str, documento: str, cuerpo: list[str]) -> list[str]:
    """Registro escrito a mano, sin ningún marcador ``<< FECHA >>``."""
    return [f"{apellido};{nombre};{documento};"] + cuerpo + ["", ""]


def documento_inventado(r: random.Random) -> str:
    """Documento ``0`` en la mayoría; si no, un número al azar de 8 dígitos.

    Es inventado: sale de la semilla, no de ninguna persona. Antes de publicar
    se verificó, fuera de este repositorio, que ninguno coincide con un
    documento de la base de la óptica.
    """
    return "0" if r.random() < 0.87 else str(r.randint(90_000_000, 99_999_999))


def clientes_al_azar(r: random.Random) -> tuple[list[list[str]], list[tuple[str, str]]]:
    """Clientes generados al azar, con algunos duplicados como en el original."""
    registros: list[list[str]] = []
    usados: set[tuple[str, str]] = set()
    elegidos: list[tuple[str, str, str]] = []
    while len(elegidos) < CANTIDAD_CLIENTES:
        clave = (r.choice(APELLIDOS), r.choice(NOMBRES))
        if clave in usados:
            continue
        usados.add(clave)
        elegidos.append((clave[0], clave[1], documento_inventado(r)))

    for apellido, nombre, documento in elegidos:
        fechas = sorted({fecha(r) for _ in range(r.choice([1, 1, 1, 2, 2, 3, 4]))},
                        key=lambda f: (f[6:], f[3:5], f[:2]))
        visitas = []
        for dia in fechas:
            cuerpo, presupuesto = visita_al_azar(r)
            visitas.append((dia, cuerpo, presupuesto))
        registros.append(registro(apellido, nombre, documento, visitas, r))

    # Duplicados: el mismo cliente vuelve a aparecer en otra fila, a veces en
    # minúscula, con otras visitas. Es lo que pasa en el export real.
    duplicados = r.sample(elegidos, 12)
    for numero, (apellido, nombre, documento) in enumerate(duplicados):
        if numero % 3 == 0:
            apellido, nombre = apellido.lower(), nombre.lower()
        cuerpo, presupuesto = visita_al_azar(r)
        registros.append(registro(apellido, nombre, "0", [(fecha(r), cuerpo, presupuesto)], r))
    return registros, [(a, n) for a, n, _ in elegidos]


def casos_especiales(r: random.Random) -> list[list[str]]:
    """Al menos un caso de cada motivo de revisión, más otras trampas del formato."""
    regs: list[list[str]] = []
    doc = PROFESIONALES

    # Anteojos de sol vendidos (marcador explícito) y una receta común con
    # cristal de sol, que NO es venta de anteojos de sol.
    regs.append(registro("FANTASADEZ", "IRMA", "0", [
        ("21/11/2016", ["", " ANT.SOL MODELO AVIADOR", " PAGO CON TARJETA"], False),
        ("12/12/2018", ["LEJOS:", ojo("O.D.", "-0.75", "+0.50", 60, "   D.I. 65"),
                        "BI/MULTIFOCAL: ", "    MONO.ORG.LAB.SOL GRIS DEGRADE",
                        "1 ANT DE SOL Y 2 BLANCOS CON MARCO PROPIO"], False),
    ], r))

    # revisar_duplicado_fecha: dos visitas distintas el mismo día.
    regs.append(registro("FANTASARETTI", "ROGELIO", "0", [
        ("11/11/2013", ["LEJOS:", ojo("O.D.", "+1.50"), ojo("O.I.", "+1.50"), "    ADD +2.25",
                        "", f"Doctor: {doc[3]}"], False),
        ("11/11/2013", ["LEJOS:", ojo("O.D.", "+1.50"),
                        ojo("O.I.", "+1.50", extra="   Color 3_GRIS  ORGANICO "),
                        "", f"Doctor: {doc[3]}"], False),
    ], r))

    # Visita duplicada idéntica en dos filas del mismo cliente: se colapsa.
    igual = [("03/04/2012", ["LEJOS:", ojo("O.D.", "-0.75"), ojo("O.I.", "-1.00"),
                             "", f"Doctor: {doc[0]}"], False)]
    regs.append(registro("SIMULORENA", "AMANDA", "0", igual, r))
    regs.append(registro("SIMULORENA", "AMANDA", "0", igual, r))

    # documento_en_conflicto: el mismo cliente con dos documentos distintos.
    regs.append(registro("PROBASTEGUI", "EULALIA", "97000001", [
        ("04/08/2018", ["LEJOS:", ojo("O.D.", "-1.00"), ojo("O.I.", "-1.25")], False)], r))
    regs.append(registro("PROBASTEGUI", "EULALIA", "97000002", [
        ("05/06/2019", ["CERCA:", ojo("O.D.", "+2.00"), ojo("O.I.", "+2.25")], False)], r))

    # Documento en 0 en una fila y válido en otra: gana el válido.
    regs.append(registro("INVENTADEZ", "TEODORA", "0", [
        ("10/10/2018", ["LEJOS:", ojo("O.D.", "-2.00"), "CAMBIO ; ARMAZON EQUIVOCADO"], False)], r))
    regs.append(registro("inventadez", "teodora", "98765432", [
        ("08/05/2020", ["CERCA:", ojo("O.D.", "+1.75", "+0.75", 105, "   D.I. 60"),
                        ojo("O.I.", "+1.75", "+0.75", 35, "   Color AR VERDE FLEX"),
                        "BI/MULTIFOCAL: ", "  D.I. Cerca 60", f"Doctor: {doc[0]} ",
                        "FLEX AR VERDE PARA LEER.  << >>"], False)], r))

    # documento_implausible: menos de 6 dígitos.
    regs.append(registro("MUESTROVICH", "ANSELMO", "1234", [
        ("15/02/2016", ["LEJOS:", ojo("O.D.", "+0.50"), "    ADD +1.5"], False)], r))

    # posible_registro_basura: X;X y PRUEBA;PRUEBA.
    regs.append(registro("X", "X", "0", [("04/08/2018", ["LEJOS:", ojo("O.D.", "-1.00")], False)], r))
    regs.append(registro("PRUEBA", "PRUEBA", "0", [
        ("19/08/2019", ["LENTES DE CONTACTO:", "      O.D. -11.50"], False)], r))

    # apellido vacío.
    regs.append(registro("", "SIN APELLIDO", "0", [
        ("14/06/2017", ["LEJOS:", ojo("O.D.", "-1.25"), "USA ARMAZON PROPIO"], False)], r))

    # dialecto_manuscrito con fecha suelta en la línea del doctor, y sin_fecha.
    regs.append(registro_crudo("EJEMPLUGUEZ", "BENICIO", "0", [
        "LEJOS: O.D: +1.25 -0.50 EN 95", "       O.I: +1.00", "", "AD: +2.00",
        "DRA VISTAMAR ELENA 14/05/2024",
    ]))
    regs.append(registro_crudo("MUESTRINI", "FILOMENA", "0", [
        "LEJOS ", "OD ESF. - 2.25 CIL. - 0.50 A 165 ", "OI ESF. - 1.50 CIL. - 0.75 A 15 ",
        "POLICARBONATO AR VERDE",
    ]))
    regs.append(registro_crudo("IMAGINELLI", "OSVALDO", "0", ["ANT SOL POLARIZADO MARRON"]))

    # marcador_sin_cierre: << FECHA: sin el >>.
    regs.append(registro_crudo("SUPUESTANI", "LUCRECIA", "0", [
        "<< FECHA: 14/05/2021", SEPARADOR, "LEJOS:", ojo("O.D.", "-0.50"), ojo("O.I.", "-0.75"),
    ]))

    # seccion_desconocida.
    regs.append(registro("DEMOSTRIAGA", "CASIMIRO", "0", [
        ("23/04/2019", ["RP. OFTALMOLOGO:", ojo("O.D.", "-1.00")], False)], r))

    # valor_no_parseable: una línea que huele a medida y ningún patrón lee.
    regs.append(registro("TESTOLUGUEZ", "AURELIO", "0", [
        ("18/11/2018", ["LEJOS:", ojo("O.D.", "-1.50"), ojo("O.I.", "-1.75"), "",
                        f"Doctor: {doc[2]}", "ANTERIOR -2.25 Y -2.50 REVISAR"], False)], r))

    # Encabezado de contacto con ruido pegado.
    regs.append(registro("QUIMERANI", "ESTELA", "0", [
        ("13/09/2013", ["RP. MEDICO:NO ES DE ESTE CLIENTE !!!!!",
                        ojo("O.D.", "-3.75", "-0.25", 25)], False)], r))

    # nivel_en_cilindro.
    regs.append(registro("QUIMEROLINI", "NORBERTO", "0", [
        ("17/06/2022", ["RP. CONTACTOLOGO:", "    O.D.  Esf. +2.00  Cil. HIGH",
                        "    O.I.  Esf. +2.25  Cil. HIGH", "LENTES DE CONTACTO:",
                        "      Marca L.C. SOFLENS MULTIFOCAL"], False)], r))

    # medidas_lc_sin_etiqueta: números sin etiqueta en lentes de contacto.
    regs.append(registro("FICTOVICH", "GENOVEVA", "0", [
        ("17/06/2022", ["LENTES DE CONTACTO:", "      O.D. 8.40 -2.50 9.60",
                        "      O.I. CB 8.40 -2.25 DIA. 9.60", "      Marca L.C. RGP INVENTADA"], False)], r))

    # receta_repetida_distinta: la misma receta del médico en dos renglones.
    regs.append(registro("FICTASTEGUI", "ROMUALDO", "0", [
        ("09/09/2016", ["RP. MEDICO:", "    O.I.  Esf. -9.50   RC. 43.00x44.25 a 160",
                        "    O.I.  Esf. -8.75  Cil. -1.50  En 165"], False)], r))

    # rp_anteojos_sin_leer: R.P.: con una receta de anteojos.
    regs.append(registro("PROBORENA", "HERMINIA", "0", [
        ("03/03/2020", ["R.P.: LEJOS OD ESF. -1.25 CIL. -0.50 A 175",
                        "            OI ESF. -1.00 CIL. -0.75 A 5"], False)], r))

    # lc_clasificada_por_caja y clasificación por marca, sin secciones.
    regs.append(registro("PROBANI", "LEOPOLDO", "0", [
        ("17/06/2022", ["", " 1 CAJA ESF.-2.25"], False),
        ("28/09/2023", ["", " 1 PAR ESF.-5.50 BIOMEDICS"], False),
    ], r))

    # Lente multifocal con nivel debajo de la marca y comentario de adaptación.
    regs.append(registro("SIMULIAGA", "OFELIA", "0", [
        ("17/06/2022", ["RP. CONTACTOLOGO:", ojo("O.D.", "+1.50"), ojo("O.I.", "+1.50"),
                        "LENTES DE CONTACTO:", "      Marca L.C. SOFLENS MULTIFOCAL",
                        " AO +2.25 / HIGH",
                        "CONTROL DE ADAPTACION - SE CAMBIA A AO +1.75/ HIGH VE MEJOR DE CERCA"], False)], r))

    # Fecha imposible.
    regs.append(registro("DEMOSTRANI", "OTILIA", "0", [
        ("31/02/2015", ["LEJOS:", ojo("O.D.", "-0.25")], False)], r))

    # Sólo texto libre: bloque_sin_estructura.
    regs.append(registro("IMAGINADEZ", "CASIANA", "0", [
        ("09/03/2016", ["", " PASA A RETIRAR EL JUEVES"], False)], r))

    return regs


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def escribir_planilla(ruta: Path, registros: list[list[str]]) -> None:
    """Escribe la planilla como el export de Moebius: cp1252 y CRLF, sin comillas."""
    lineas = [CABECERA] + [linea for reg in registros for linea in reg]
    ruta.write_bytes(("\r\n".join(lineas) + "\r\n").encode("cp1252"))


def ids_de_visitas(ruta: Path) -> dict[tuple[str, str], list[str]]:
    """``id_bloque`` de cada visita, calculado con el mismo parser del ETL."""
    from parser import extractor, lector, segmentador

    ids: dict[tuple[str, str], list[str]] = {}
    for crudo in lector.leer_registros(ruta):
        for visita in segmentador.segmentar(crudo.lineas_notas):
            receta = extractor.extraer(visita, crudo.apellido, crudo.nombre)
            ids.setdefault((crudo.apellido, crudo.nombre), []).append(receta.id_bloque)
    return ids


def escribir_correcciones(ruta_planilla: Path, ruta: Path) -> None:
    """Un ``correcciones_manuales.csv`` chico, para mostrar cómo se usa.

    * le pone fecha a la visita manuscrita que no la tenía;
    * completa la esfera de la visita con un valor que el parser no leyó;
    * trae un ``id_bloque`` que no existe, para mostrar la corrección huérfana.
    """
    ids = ids_de_visitas(ruta_planilla)
    sin_fecha = ids[("MUESTRINI", "FILOMENA")][0]
    no_leido = ids[("TESTOLUGUEZ", "AURELIO")][0]
    lineas = [
        "# correcciones_manuales.csv -- datos de ejemplo INVENTADOS",
        "#",
        "# Cada fila corrige una visita, identificada por su id_bloque.",
        "# Una celda vacía no pisa nada; una celda con valor manda.",
        "id_bloque,fecha,od_lejos_esf,doctor,observaciones",
        f"{sin_fecha},12/04/2024,,MIRADOR JOAQUIN,",
        f"{no_leido},,,,REVISADO: LA GRADUACION ANTERIOR ERA -2.25 Y -2.50",
        "ffffffffffff,,-1.00,,",
    ]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8-sig", newline="\n")


def generar() -> None:
    """Genera ``datos_ejemplo/planilla_notas.csv`` y ``correcciones_manuales.csv``."""
    r = random.Random(SEMILLA)
    CARPETA.mkdir(exist_ok=True)
    registros, _ = clientes_al_azar(r)
    registros += casos_especiales(r)
    escribir_planilla(ARCHIVO_PLANILLA, registros)
    escribir_correcciones(ARCHIVO_PLANILLA, ARCHIVO_CORRECCIONES)
    print(f"Generado {ARCHIVO_PLANILLA.relative_to(RAIZ)} ({len(registros)} registros)")
    print(f"Generado {ARCHIVO_CORRECCIONES.relative_to(RAIZ)}")


if __name__ == "__main__":
    generar()
