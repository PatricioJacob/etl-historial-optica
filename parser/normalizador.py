# -*- coding: utf-8 -*-
"""
Capa de TRANSFORMACIÓN: normalización de valores sueltos.

Funciones chicas, sin estado, que convierten un texto crudo en un valor
consistente. Ninguna inventa datos: si el valor no se puede interpretar,
devuelven ``None`` y el extractor decide qué hacer con eso.

REGLA DE ORO DEL MÓDULO
-----------------------
Ante la duda, ``None``. Son recetas médicas: un valor mal normalizado puede
terminar en un par de anteojos mal graduado. Es preferible una celda vacía que
la empleada consulta contra ``texto_original``, que un número plausible pero
falso.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date, datetime

from . import patrones

#: Valor con el que se representa un dato ausente en los CSV.
#: En SQLite se guarda ``NULL``; sólo se escribe ``N/A`` al exportar.
MARCA_AUSENTE: str = "N/A"

#: Rango admisible para el eje del cilindro, en grados.
EJE_MINIMO: int = 0
EJE_MAXIMO: int = 180

#: Rango admisible para dioptrías (esfera, cilindro, adición).
#: Fuera de esto el valor es casi seguro un error de tipeo o un número que en
#: realidad era otra cosa (un precio, un código de armazón).
DIOPTRIA_MINIMA: float = -40.0
DIOPTRIA_MAXIMA: float = 40.0

#: Rango admisible para la distancia interpupilar, en milímetros.
DI_MINIMA: float = 20.0
DI_MAXIMA: float = 90.0

#: Año mínimo aceptable para una fecha de visita. La óptica no tiene registros
#: informatizados anteriores.
ANIO_MINIMO: int = 1990


def quitar_acentos(texto: str) -> str:
    """Elimina tildes y diéresis dejando la letra base.

    Convierte ``PEÑALOZZA`` en ``PENALOZZA`` y ``D´EJEMPLO`` en ``D´EJEMPLO``
    (el apóstrofo lo saca :func:`normalizar_clave`, no esta función).

    Args:
        texto: Texto de entrada.

    Returns:
        El mismo texto sin marcas diacríticas.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar_nombre(texto: str) -> str:
    """Limpia un apellido o nombre para mostrarlo en pantalla.

    Pasa a mayúsculas y colapsa espacios, pero CONSERVA los acentos: es el
    valor que ve la empleada, y ``PEÑALOZZA`` se lee mejor que ``PENALOZZA``.

    Args:
        texto: Apellido o nombre crudo.

    Returns:
        El texto en mayúsculas con espacios colapsados.
    """
    return patrones.ESPACIOS_MULTIPLES.sub(" ", texto.strip().upper())


def normalizar_clave(texto: str) -> str:
    """Genera la forma canónica usada para comparar y deduplicar.

    A diferencia de :func:`normalizar_nombre`, acá sí se quitan los acentos y
    toda la puntuación. Es la clave con la que ``peñalozza`` y ``PEÑALOZZA`` se
    reconocen como la misma persona.

    Args:
        texto: Apellido o nombre crudo.

    Returns:
        Texto en mayúsculas, sin acentos, sin puntuación y con espacios
        colapsados.
    """
    sin_acentos = quitar_acentos(texto.upper())
    sin_puntuacion = patrones.NO_ALFANUMERICO.sub(" ", sin_acentos)
    return patrones.ESPACIOS_MULTIPLES.sub(" ", sin_puntuacion).strip()


def normalizar_decimal(texto: str | None) -> str | None:
    """Lleva un valor dioptrico a la forma ``+0.00`` / ``-0.00``.

    Resuelve tres inconsistencias del archivo:
      * decimales de distinta longitud (``+2.5`` y ``+2.50`` conviven);
      * coma en vez de punto como separador decimal;
      * signo separado del número por espacios (``- 1.75``), propio del
        dialecto manuscrito.

    Args:
        texto: Valor crudo, por ejemplo ``"- 1.75"`` o ``"+2,5"``.

    Returns:
        El valor con signo explícito y dos decimales, o ``None`` si no se
        puede interpretar o cae fuera del rango dioptrico plausible.
    """
    if texto is None:
        return None

    limpio = patrones.ESPACIOS_MULTIPLES.sub("", texto.strip()).replace(",", ".")
    if not limpio:
        return None

    try:
        valor = float(limpio)
    except ValueError:
        return None

    if not DIOPTRIA_MINIMA <= valor <= DIOPTRIA_MAXIMA:
        return None

    return f"{valor:+.2f}"


def normalizar_eje(texto: str | None) -> str | None:
    """Valida y normaliza el eje del cilindro.

    Args:
        texto: Valor crudo en grados, por ejemplo ``"75"``.

    Returns:
        El eje como entero en texto, o ``None`` si no es un número entre 0
        y 180. Un eje de 250 grados no existe: es un error de tipeo o un
        número que en realidad era otra cosa.
    """
    if texto is None:
        return None

    limpio = texto.strip()
    if not limpio.isdigit():
        return None

    valor = int(limpio)
    if not EJE_MINIMO <= valor <= EJE_MAXIMO:
        return None

    return str(valor)


def normalizar_milimetros(texto: str | None) -> str | None:
    """Normaliza una distancia interpupilar o una altura, en milímetros.

    Args:
        texto: Valor crudo, por ejemplo ``"66.00"`` o ``"58"``.

    Returns:
        El valor con dos decimales, o ``None`` si no se puede interpretar.
        Para la D.I. se valida además el rango anatómico plausible.
    """
    if texto is None:
        return None

    limpio = patrones.ESPACIOS_MULTIPLES.sub("", texto.strip()).replace(",", ".")
    if not limpio:
        return None

    try:
        valor = float(limpio)
    except ValueError:
        return None

    return f"{valor:.2f}"


def validar_di(texto: str | None) -> str | None:
    """Aplica el rango anatómico plausible a una distancia interpupilar.

    Args:
        texto: D.I. ya normalizada por :func:`normalizar_milimetros`.

    Returns:
        El mismo valor si cae dentro del rango, ``None`` si no.
    """
    normalizado = normalizar_milimetros(texto)
    if normalizado is None:
        return None
    if not DI_MINIMA <= float(normalizado) <= DI_MAXIMA:
        return None
    return normalizado


def normalizar_fecha(texto: str) -> date | None:
    """Convierte una fecha ``dd/mm/aaaa`` en un objeto ``date``.

    Acepta día y mes de uno o dos dígitos y año de dos o cuatro. Un año de dos
    dígitos se interpreta como 20xx si es menor o igual al año actual en dos
    dígitos, y como 19xx si no.

    Args:
        texto: Fecha cruda, por ejemplo ``"30/01/2023"`` o ``"9/3/16"``.

    Returns:
        La fecha, o ``None`` si es sintácticamente correcta pero imposible
        (``31/02/2015``) o cae fuera del rango plausible.
    """
    partes = texto.strip().split("/")
    if len(partes) != 3:
        return None

    try:
        dia, mes, anio = (int(p) for p in partes)
    except ValueError:
        return None

    if anio < 100:
        corte = datetime.now().year % 100
        anio += 2000 if anio <= corte else 1900

    try:
        resultado = date(anio, mes, dia)
    except ValueError:
        return None

    if resultado.year < ANIO_MINIMO or resultado > date.today():
        return None

    return resultado


def formatear_fecha(valor: date | None) -> str | None:
    """Formatea una fecha para las salidas, en ``dd/mm/aaaa``.

    Args:
        valor: Fecha a formatear.

    Returns:
        La fecha como texto, o ``None`` si el valor era ``None``.
    """
    return None if valor is None else valor.strftime("%d/%m/%Y")


def normalizar_documento(texto: str) -> str | None:
    """Valida un número de documento.

    Args:
        texto: Campo NUMERODOCUMENTO crudo.

    Returns:
        El documento sin ceros a la izquierda, o ``None`` si es ausente.
        Se consideran ausentes el ``0`` (28.107 casos en el archivo real) y
        cualquier número de menos de 6 dígitos (11 casos), que es imposible
        para un DNI argentino.
    """
    limpio = texto.strip()
    if not limpio or patrones.DOCUMENTO_INVALIDO.match(limpio):
        return None
    return limpio.lstrip("0") or None


def normalizar_texto_libre(texto: str) -> str | None:
    """Limpia una observación o un texto descriptivo.

    Colapsa espacios, quita los marcadores ``<< >>`` residuales y descarta el
    resultado si queda sólo puntuación o ruido.

    Args:
        texto: Texto crudo.

    Returns:
        El texto limpio, o ``None`` si no queda nada con contenido.
    """
    sin_marcadores = patrones.MARCADOR.sub(" ", texto)
    colapsado = patrones.ESPACIOS_MULTIPLES.sub(" ", sin_marcadores).strip()

    if not colapsado or patrones.RESIDUO_IGNORABLE.match(colapsado):
        return None

    return colapsado


def normalizar_para_hash(texto: str) -> str:
    """Prepara un texto para calcular su hash de identidad.

    Se colapsan los espacios y se pasa a mayúsculas para que diferencias de
    formato irrelevantes (un espacio de más, un salto de línea extra) no
    cambien el identificador.

    Args:
        texto: Bloque de texto original de una receta.

    Returns:
        La forma canónica sobre la que se calcula el hash.
    """
    return patrones.ESPACIOS_MULTIPLES.sub(" ", texto.strip().upper())


def calcular_id_bloque(apellido: str, nombre: str, texto_original: str) -> str:
    """Calcula el identificador estable de un bloque de texto crudo.

    Es un SHA-256 truncado a 12 caracteres hexadecimales sobre la clave del
    cliente más el texto original normalizado.

    POR QUÉ EL HASH DEL CONTENIDO Y NO EL NÚMERO DE LÍNEA
    -----------------------------------------------------
    El identificador tiene que sobrevivir a que se vuelva a exportar desde
    Moebius. El número de línea cambia si el export cambia de orden y dejaría
    huérfanas todas las correcciones manuales. El hash del contenido no.

    Se incluye la clave del cliente en el hash porque dos clientes distintos
    pueden tener bloques de texto idénticos (dos recetas con las mismas
    medidas), y necesitamos poder corregirlos por separado.

    Args:
        apellido: Apellido del cliente.
        nombre: Nombre del cliente.
        texto_original: Bloque de texto crudo de la receta.

    Returns:
        Identificador de 12 caracteres hexadecimales.
    """
    material = "|".join(
        (
            normalizar_clave(apellido),
            normalizar_clave(nombre),
            normalizar_para_hash(texto_original),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:12]


def normalizar_ojo(etiqueta: str) -> str | None:
    """Convierte cualquier variante de etiqueta de ojo a ``OD``, ``OI`` o ``AO``.

    Cubre las 13 grafías observadas en el archivo: ``O.D.``, ``O.I.``, ``OD``,
    ``OI``, ``AO``, ``A.O.`` y sus versiones en minúscula.

    Args:
        etiqueta: Etiqueta cruda capturada por ``patrones.ETIQUETA_OJO``.

    Returns:
        ``"OD"``, ``"OI"``, ``"AO"``, o ``None`` si no se reconoce.
    """
    compacta = patrones.NO_ALFANUMERICO.sub("", quitar_acentos(etiqueta.upper()))
    compacta = compacta.replace(" ", "")
    if compacta in ("OD", "OI", "AO"):
        return compacta
    return None
