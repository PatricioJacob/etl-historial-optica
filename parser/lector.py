# -*- coding: utf-8 -*-
"""
Capa de EXTRACCIÓN: lee el CSV crudo y lo convierte en registros de cliente.

Responsabilidades:
  1. Detectar el encoding del archivo (no asumirlo).
  2. Recorrer el archivo línea por línea con una máquina de estados y agrupar
     cada bloque de NOTAS con su cliente.

POR QUÉ UNA MÁQUINA DE ESTADOS Y NO ``csv.reader`` NI ``pandas.read_csv``
------------------------------------------------------------------------
El campo NOTAS es multilínea y NO está entrecomillado. Para cualquier parser
de CSV que respete el estándar RFC 4180, un salto de línea sin comillas termina
el registro. Sobre este archivo, ``pandas.read_csv`` produce cientos de miles
de filas basura en vez de 32.194 clientes.

La única forma de leerlo bien es decidir a mano dónde empieza un registro.
El criterio es estructural: una línea abre cliente nuevo sólo si tiene la forma
``APELLIDO;NOMBRE;DOCUMENTO;`` con documento numérico. Todo lo demás acumula.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import patrones

_log = logging.getLogger(__name__)

#: Encodings a probar, en orden. cp1252 primero porque el archivo es un export
#: de un sistema de gestión viejo sobre Windows en español.
ENCODINGS_CANDIDATOS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


@dataclass
class RegistroCrudo:
    """Un registro tal como salió del archivo, sin interpretar todavía.

    Attributes:
        apellido: Campo APELLIDO sin normalizar.
        nombre: Campo NOMBRE sin normalizar.
        documento: Campo NUMERODOCUMENTO sin normalizar (puede ser "0").
        lineas_notas: Líneas del campo NOTAS, en orden y sin recortar. Los
            espacios y las líneas vacías se conservan porque son significativos
            para la segmentación posterior.
        numero_linea: Línea del archivo donde empieza el registro. Sirve sólo
            para mensajes de log; NO se usa como identificador, porque cambia
            si Moebius reordena el export.
    """

    apellido: str
    nombre: str
    documento: str
    lineas_notas: list[str] = field(default_factory=list)
    numero_linea: int = 0

    @property
    def texto_notas(self) -> str:
        """Devuelve el bloque de notas completo como un único texto."""
        return "\n".join(self.lineas_notas)


def detectar_encoding(ruta: Path) -> str:
    """Determina el encoding del archivo probando candidatos en orden.

    No se asume el encoding: se verifica que el archivo decodifique entero sin
    errores. Se devuelve el primer candidato que funciona.

    Args:
        ruta: Ruta al archivo CSV crudo.

    Returns:
        Nombre del encoding que decodifica el archivo completo.

    Raises:
        UnicodeDecodeError: Si ningún candidato logra decodificar el archivo.
    """
    datos = ruta.read_bytes()
    ultimo_error: UnicodeDecodeError | None = None

    for encoding in ENCODINGS_CANDIDATOS:
        try:
            datos.decode(encoding)
        except UnicodeDecodeError as exc:
            ultimo_error = exc
            _log.debug("Encoding %s descartado: %s", encoding, exc)
            continue
        _log.info("Encoding detectado: %s", encoding)
        return encoding

    assert ultimo_error is not None
    raise ultimo_error


def leer_registros(ruta: Path, encoding: str | None = None) -> list[RegistroCrudo]:
    """Lee el CSV crudo y devuelve la lista de registros de cliente.

    Implementa la máquina de estados descrita en el encabezado del módulo.

    Args:
        ruta: Ruta al archivo ``planilla_notas.csv``.
        encoding: Encoding a usar. Si es ``None`` se detecta automáticamente.

    Returns:
        Lista de :class:`RegistroCrudo` en el orden en que aparecen en el
        archivo.
    """
    if encoding is None:
        encoding = detectar_encoding(ruta)

    texto = ruta.read_bytes().decode(encoding)
    # Se normalizan los finales de línea para que el resto del pipeline no
    # tenga que preocuparse por CRLF. El archivo real usa CRLF en todas
    # sus 820.079 líneas.
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    if lineas and lineas[0].strip() != patrones.CABECERA_ESPERADA:
        _log.warning(
            "La primera línea no es la cabecera esperada. Se esperaba %r y se "
            "encontró %r. Se continúa igual.",
            patrones.CABECERA_ESPERADA,
            lineas[0][:120],
        )

    registros: list[RegistroCrudo] = []
    actual: RegistroCrudo | None = None

    for indice, linea in enumerate(lineas[1:], start=2):
        coincidencia = patrones.INICIO_REGISTRO.match(linea)

        if coincidencia is not None:
            # Se cierra el registro anterior y se abre uno nuevo.
            if actual is not None:
                registros.append(actual)
            actual = RegistroCrudo(
                apellido=coincidencia.group("apellido"),
                nombre=coincidencia.group("nombre"),
                documento=coincidencia.group("documento"),
                lineas_notas=[linea[coincidencia.end():]],
                numero_linea=indice,
            )
        elif actual is not None:
            actual.lineas_notas.append(linea)
        elif linea.strip():
            # Contenido antes del primer registro: no debería pasar nunca.
            _log.warning(
                "Línea %d descartada por estar antes del primer registro: %r",
                indice,
                linea[:120],
            )

    if actual is not None:
        registros.append(actual)

    _log.info("Se leyeron %d registros crudos de %s", len(registros), ruta.name)
    return registros
