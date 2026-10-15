# -*- coding: utf-8 -*-
"""
Catálogo cerrado de motivos de revisión manual.

POR QUÉ UN ENUM Y NO TEXTO LIBRE
--------------------------------
Con motivos fijos se puede ordenar ``revisar_manual.csv`` por frecuencia y ver
de una si un problema afecta a 1.800 registros (entonces falta una regla en
``patrones.py``) o a 7 (entonces se corrige a mano en
``correcciones_manuales.csv``). Con texto libre eso no se puede agrupar.

Para agregar un motivo nuevo: se suma un miembro acá y se le asigna una
severidad en :data:`SEVERIDAD_POR_MOTIVO`. Nunca se escribe el texto suelto en
el código.
"""

from __future__ import annotations

from enum import StrEnum


class Motivo(StrEnum):
    """Motivo por el cual un registro cae en ``revisar_manual.csv``."""

    #: La visita no tiene ninguna fecha reconocible.
    SIN_FECHA = "sin_fecha"

    #: La fecha existe pero es imposible (por ejemplo 31/02/2015) o está
    #: fuera del rango plausible.
    FECHA_INVALIDA = "fecha_invalida"

    #: El campo APELLIDO vino vacío.
    APELLIDO_VACIO = "apellido_vacio"

    #: Apareció un encabezado de sección que el parser no modela todavía.
    SECCION_DESCONOCIDA = "seccion_desconocida"

    #: Hubo líneas con contenido que ningún patrón supo interpretar.
    VALOR_NO_PARSEABLE = "valor_no_parseable"

    #: El bloque no tiene ninguna sección óptica ni ninguna medida: es sólo
    #: texto libre. NO es un error: son notas comerciales legítimas. Se lista
    #: para que la óptica sepa que existen.
    BLOQUE_SIN_ESTRUCTURA = "bloque_sin_estructura"

    #: Dos registros con el mismo Apellido+Nombre traen documentos válidos y
    #: distintos. Puede ser una homonimia real.
    DOCUMENTO_EN_CONFLICTO = "documento_en_conflicto"

    #: Dos visitas del mismo cliente comparten fecha pero difieren en
    #: contenido. Puede ser un duplicado de migración o un segundo par de
    #: anteojos legítimo.
    REVISAR_DUPLICADO_FECHA = "revisar_duplicado_fecha"

    # --- Motivos descubiertos al analizar el archivo real -------------------

    #: Receta tipeada a mano, sin marcadores ``<< FECHA >>``. Es una gramática
    #: distinta y sus fechas son las más recientes del archivo (hasta 2024).
    DIALECTO_MANUSCRITO = "dialecto_manuscrito"

    #: Marcador ``<< FECHA:`` sin el ``>>`` de cierre.
    MARCADOR_SIN_CIERRE = "marcador_sin_cierre"

    #: El registro parece de prueba: apellido igual al nombre, o de una sola
    #: letra. No se borra, se marca.
    POSIBLE_REGISTRO_BASURA = "posible_registro_basura"

    #: El campo ``Doctor:`` no contiene un médico sino una nota del empleado
    #: ("COPIA ANT.EN USO"). El valor se movió a observaciones.
    DOCTOR_NO_ES_MEDICO = "doctor_no_es_medico"

    #: La línea de observación viene cortada a 45 caracteres por el sistema de
    #: origen, con el marcador ``<<`` sin cerrar. Es pérdida de datos en el
    #: origen: no se puede recuperar, sólo declarar.
    OBSERVACION_TRUNCADA = "observacion_truncada"

    #: El documento tenía menos de 6 dígitos: imposible como DNI argentino.
    #: Se trató como ausente.
    DOCUMENTO_IMPLAUSIBLE = "documento_implausible"

    #: Un ``id_bloque`` del archivo de correcciones no existe en el crudo.
    CORRECCION_HUERFANA = "correccion_huerfana"

    #: En una lente de contacto, el nivel de adición (HIGH, MED, LOW, MID)
    #: aparece escrito en el lugar del cilindro: ``Cil. HIGH``. No se adivina:
    #: el cilindro queda nulo y el renglón va a observaciones.
    NIVEL_EN_CILINDRO = "nivel_en_cilindro"

    #: En una visita de lentes de contacto, un renglón de ojo trae más de un
    #: número sin etiqueta (``O.D. 8.40 -2.50 9.60``), o un número sin signo
    #: que no va seguido de un nivel (``O.D. 8.40``). Lo más probable es que
    #: sean curva base, potencia y diámetro, pero NO se asigna un número por
    #: el orden en que está escrito: el renglón va entero a observaciones.
    MEDIDAS_LC_SIN_ETIQUETA = "medidas_lc_sin_etiqueta"

    #: En una visita de lentes de contacto, el renglón de una prescripción no
    #: se leyó por la regla anterior y más abajo hay OTRO renglón de la misma
    #: prescripción y el mismo ojo que sí se puede leer. No se completa la
    #: prescripción con ese segundo renglón, aunque parezca la misma receta:
    #: queda vacía. En ``detalle`` van los dos renglones.
    RECETA_REPETIDA_DISTINTA = "receta_repetida_distinta"

    #: Receta de anteojos escrita a mano tras un ``R.P.:`` (``R.P.: LEJOS OD
    #: +3.25``). No es de lentes de contacto, y puede ser una copia de la
    #: sección ``LEJOS``: no se lee. Cada renglón va a observaciones y abre un
    #: caso, igual que los renglones de ojo sueltos de esa visita.
    RP_ANTEOJOS_SIN_LEER = "rp_anteojos_sin_leer"

    #: Visita sin ninguna sección, clasificada como lentes de contacto sólo
    #: porque un comentario nombra cajas o descartables, sin marca. La señal
    #: es débil: conviene mirarla.
    LC_CLASIFICADA_POR_CAJA = "lc_clasificada_por_caja"


#: Severidad de cada motivo. Es una extensión propia a la especificación.
#:
#: POR QUÉ: con ~3.000 filas y una sola columna ``motivo``, no se puede decidir
#: por dónde empezar. ``bloque_sin_estructura`` (1.837 casos, ruido conocido) y
#: ``documento_en_conflicto`` (7 casos, puede borrar al cliente equivocado)
#: compiten por la atención como si fueran lo mismo. Con severidad, lo urgente
#: queda arriba y el ruido esperado abajo.
#:
#:   ``alta``  → dato clínico perdido o cliente que puede desaparecer.
#:   ``media`` → dato comercial dudoso.
#:   ``baja``  → ruido conocido y esperado.
SEVERIDAD_POR_MOTIVO: dict[Motivo, str] = {
    Motivo.DOCUMENTO_EN_CONFLICTO: "alta",
    Motivo.DIALECTO_MANUSCRITO: "alta",
    Motivo.MARCADOR_SIN_CIERRE: "alta",
    Motivo.CORRECCION_HUERFANA: "alta",
    Motivo.FECHA_INVALIDA: "alta",
    Motivo.APELLIDO_VACIO: "alta",
    Motivo.SECCION_DESCONOCIDA: "media",
    Motivo.REVISAR_DUPLICADO_FECHA: "media",
    Motivo.VALOR_NO_PARSEABLE: "media",
    Motivo.SIN_FECHA: "media",
    Motivo.OBSERVACION_TRUNCADA: "media",
    Motivo.DOCUMENTO_IMPLAUSIBLE: "media",
    Motivo.NIVEL_EN_CILINDRO: "media",
    Motivo.MEDIDAS_LC_SIN_ETIQUETA: "media",
    Motivo.RECETA_REPETIDA_DISTINTA: "media",
    Motivo.RP_ANTEOJOS_SIN_LEER: "media",
    Motivo.LC_CLASIFICADA_POR_CAJA: "baja",
    Motivo.BLOQUE_SIN_ESTRUCTURA: "baja",
    Motivo.POSIBLE_REGISTRO_BASURA: "baja",
    Motivo.DOCTOR_NO_ES_MEDICO: "baja",
}

#: Orden con el que se ordena ``revisar_manual.csv``.
ORDEN_SEVERIDAD: dict[str, int] = {"alta": 0, "media": 1, "baja": 2}


def severidad(motivo: Motivo) -> str:
    """Devuelve la severidad asignada a un motivo.

    Args:
        motivo: Motivo a consultar.

    Returns:
        ``"alta"``, ``"media"`` o ``"baja"``. Si el motivo es nuevo y todavía
        no tiene severidad asignada, devuelve ``"media"``, que es el default
        conservador: se lo mira, pero no bloquea.
    """
    return SEVERIDAD_POR_MOTIVO.get(motivo, "media")
