# -*- coding: utf-8 -*-
"""
Capa de TRANSFORMACIÓN: fusiona clientes duplicados y visitas repetidas.

REGLA DE ORO DEL MÓDULO
-----------------------
Ningún dato desaparece en silencio. Todo lo que se fusiona o se descarta queda
registrado y es contable en el reporte de calidad.

CLAVE DE UNIFICACIÓN
--------------------
``Apellido + Nombre`` normalizados: mayúsculas, sin acentos, sin puntuación,
espacios colapsados.

El documento NO sirve como clave: el 87,3 % de los registros lo trae en ``0``.
Se descartaron dos alternativas:

* **Documento como clave.** Colapsaría 28.107 registros distintos en uno solo.
* **Similitud difusa (Levenshtein) sobre el nombre.** Fusionaría homónimos
  reales. En una óptica hay muchos ``INVENTAÑO LUCRECIA``, y borrar el historial
  clínico del paciente equivocado es el peor error posible de este proyecto.
  Se prefiere quedarse corto: dos fichas separadas de la misma persona son un
  problema menor y visible; una ficha con dos personas mezcladas es invisible
  y peligroso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from . import normalizador
from .extractor import Receta
from .motivos import Motivo

_log = logging.getLogger(__name__)


@dataclass
class Cliente:
    """Un cliente unificado, con todo su historial.

    Attributes:
        id_cliente: Identificador numérico asignado al cargar en la base.
        apellido: Apellido para mostrar (mayúsculas, con acentos).
        nombre: Nombre para mostrar.
        clave: Forma canónica ``APELLIDO|NOMBRE`` usada para deduplicar.
        documento: Documento válido, o ``None``.
        recetas: Historial completo, ordenado por fecha ascendente.
        posible_registro_basura: ``1`` si parece un registro de prueba.
        requiere_revision: ``1`` si algo de este cliente necesita una mirada
            humana.
        incidencias: Incidencias a nivel cliente, como pares
            ``(Motivo, detalle)``.
        registros_fusionados: Cuántos registros crudos se unificaron acá.
    """

    id_cliente: int
    apellido: str
    nombre: str
    clave: str
    documento: str | None = None
    recetas: list[Receta] = field(default_factory=list)
    posible_registro_basura: int = 0
    requiere_revision: int = 0
    incidencias: list[tuple[Motivo, str]] = field(default_factory=list)
    registros_fusionados: int = 1

    @property
    def nombre_completo(self) -> str:
        """Nombre completo para mostrar y para buscar en la app de Fase 2."""
        return f"{self.apellido} {self.nombre}".strip()

    @property
    def primera_visita(self) -> date | None:
        """Fecha de la visita más antigua con fecha conocida."""
        fechas = [r.fecha for r in self.recetas if r.fecha is not None]
        return min(fechas) if fechas else None

    @property
    def ultima_visita(self) -> date | None:
        """Fecha de la visita más reciente con fecha conocida."""
        fechas = [r.fecha for r in self.recetas if r.fecha is not None]
        return max(fechas) if fechas else None


@dataclass
class ResultadoDeduplicacion:
    """Salida del proceso de deduplicación, con sus métricas.

    Attributes:
        clientes: Clientes unificados, en orden alfabético.
        registros_entrada: Cuántos registros crudos se procesaron.
        clientes_fusionados: Cuántos registros se absorbieron en otro cliente.
        visitas_fusionadas: Cuántas visitas idénticas se colapsaron.
        conflictos_documento: Cuántos clientes tienen documentos en conflicto.
    """

    clientes: list[Cliente] = field(default_factory=list)
    registros_entrada: int = 0
    clientes_fusionados: int = 0
    visitas_fusionadas: int = 0
    conflictos_documento: int = 0


def _es_registro_basura(apellido: str, nombre: str) -> bool:
    """Detecta un registro de prueba del sistema viejo.

    Se consideran de prueba los que tienen apellido igual al nombre
    (``PRUEBA;PRUEBA``), o alguno de los dos campos de una sola letra (``X;X``), o
    alguno vacío.

    NO se borran: la decisión de borrar historial clínico es de la óptica, no
    nuestra. Sólo se marcan y se cuentan.

    Args:
        apellido: Apellido ya normalizado como clave.
        nombre: Nombre ya normalizado como clave.

    Returns:
        ``True`` si el registro parece de prueba.
    """
    if not apellido or not nombre:
        return True
    if apellido == nombre:
        return True
    return len(apellido) <= 1 or len(nombre) <= 1


def _firma_de_receta(receta: Receta) -> tuple:
    """Calcula la firma de contenido de una receta, para comparar duplicados.

    Incluye todos los campos clínicos y comerciales, pero NO el
    ``texto_original`` ni el ``id_bloque``: dos bloques con distinto espaciado
    pero las mismas medidas son la misma receta.

    Args:
        receta: Receta a firmar.

    Returns:
        Tupla hasheable que representa el contenido normalizado.
    """
    return (
        receta.fecha,
        receta.tipo_registro,
        receta.od_lejos_esf,
        receta.od_lejos_cil,
        receta.od_lejos_eje,
        receta.oi_lejos_esf,
        receta.oi_lejos_cil,
        receta.oi_lejos_eje,
        receta.adicion,
        receta.od_cerca_esf,
        receta.od_cerca_cil,
        receta.od_cerca_eje,
        receta.oi_cerca_esf,
        receta.oi_cerca_cil,
        receta.oi_cerca_eje,
        receta.lc_od_esf,
        receta.lc_oi_esf,
        # Las dos prescripciones completas forman parte de la firma. Si sólo
        # se comparara la vigente, dos visitas que difieren en la receta del
        # otro prescriptor se verían idénticas y se fusionarían, perdiendo un
        # dato clínico. Además así el resultado de la deduplicación no depende
        # de cuánto valga PRESCRIPCION_VIGENTE.
        receta.lc_od_cil,
        receta.lc_od_eje,
        receta.lc_oi_cil,
        receta.lc_oi_eje,
        receta.lc_med_od_esf,
        receta.lc_med_od_cil,
        receta.lc_med_od_eje,
        receta.lc_med_oi_esf,
        receta.lc_med_oi_cil,
        receta.lc_med_oi_eje,
        receta.lc_cont_od_esf,
        receta.lc_cont_od_cil,
        receta.lc_cont_od_eje,
        receta.lc_cont_oi_esf,
        receta.lc_cont_oi_cil,
        receta.lc_cont_oi_eje,
        receta.lc_od_potencia_lente,
        receta.lc_od_nivel,
        receta.lc_oi_potencia_lente,
        receta.lc_oi_nivel,
        receta.lc_od_curva_base,
        receta.lc_oi_curva_base,
        receta.lc_od_diametro,
        receta.lc_oi_diametro,
        receta.lc_cantidad,
        receta.lc_marca,
        receta.lc_tipo,
        receta.di,
        receta.di_lejos,
        receta.di_cerca,
        receta.altura,
        receta.tipo_lente,
        receta.modelo_anteojo,
        receta.codigo_modelo,
        receta.tratamientos,
        receta.doctor,
        receta.observaciones,
    )


def _resolver_documento(
    cliente: Cliente, candidato: str | None
) -> None:
    """Aplica la regla de conflicto de documentos.

    * Si el cliente no tiene documento, se toma el candidato.
    * Si el candidato es ``None``, no se hace nada.
    * Si ambos son válidos e iguales, no se hace nada.
    * Si ambos son válidos y distintos, se CONSERVA EL PRIMERO, se registra la
      incidencia y se marca ``requiere_revision``.

    Nunca se sobrescribe. Puede ser una homonimia real, y quedarse con el
    documento equivocado hace que la ficha apunte a otra persona.

    Args:
        cliente: Cliente ya existente.
        candidato: Documento del registro que se está fusionando.
    """
    if candidato is None:
        return

    if cliente.documento is None:
        cliente.documento = candidato
        return

    if cliente.documento == candidato:
        return

    cliente.requiere_revision = 1
    cliente.incidencias.append(
        (
            Motivo.DOCUMENTO_EN_CONFLICTO,
            f"se conservó {cliente.documento} y se descartó {candidato}",
        )
    )
    _log.warning(
        "Documento en conflicto para %s %s: se conserva %s, se descarta %s",
        cliente.apellido,
        cliente.nombre,
        cliente.documento,
        candidato,
    )


def _fusionar_visitas(cliente: Cliente) -> int:
    """Fusiona las visitas duplicadas de un cliente.

    Dos visitas se fusionan SÓLO si su contenido normalizado es idéntico. Si
    comparten fecha pero difieren en algo, se conservan las dos y se marcan
    con ``revisar_duplicado_fecha``.

    POR QUÉ: dos anteojos comprados el mismo día es un caso comercialmente
    normal en una óptica. Colapsarlos borraría una venta real.

    Args:
        cliente: Cliente cuyo historial se va a depurar.

    Returns:
        Cuántas visitas se fusionaron.
    """
    vistas: dict[tuple, Receta] = {}
    conservadas: list[Receta] = []
    fusionadas = 0

    for receta in cliente.recetas:
        firma = _firma_de_receta(receta)
        previa = vistas.get(firma)

        if previa is not None:
            # Contenido idéntico: es un duplicado de migración. Se fusiona,
            # pero se deja constancia en el log para que sea contable.
            fusionadas += 1
            _log.debug(
                "Visita duplicada fusionada para %s (id_bloque %s absorbido "
                "por %s)",
                cliente.nombre_completo,
                receta.id_bloque,
                previa.id_bloque,
            )
            continue

        vistas[firma] = receta
        conservadas.append(receta)

    # Ahora se buscan las que comparten fecha pero NO contenido.
    por_fecha: dict[date, list[Receta]] = {}
    for receta in conservadas:
        if receta.fecha is not None:
            por_fecha.setdefault(receta.fecha, []).append(receta)

    for fecha, grupo in por_fecha.items():
        if len(grupo) < 2:
            continue
        cliente.requiere_revision = 1
        for receta in grupo:
            receta.incidencias.append(
                (
                    Motivo.REVISAR_DUPLICADO_FECHA,
                    f"{len(grupo)} visitas distintas el {fecha:%d/%m/%Y}; "
                    "puede ser un segundo par legítimo",
                )
            )

    # Orden cronológico ascendente. Las visitas sin fecha van al final, porque
    # no se puede afirmar cuándo ocurrieron.
    conservadas.sort(key=lambda r: (r.fecha is None, r.fecha or date.min))
    cliente.recetas = conservadas
    return fusionadas


def deduplicar(
    registros: list[tuple[str, str, str | None, list[Receta], list[tuple[Motivo, str]]]]
) -> ResultadoDeduplicacion:
    """Unifica los registros crudos en clientes únicos.

    Args:
        registros: Lista de tuplas
            ``(apellido, nombre, documento, recetas, incidencias)``, una por
            registro crudo del archivo.

    Returns:
        El resultado con los clientes unificados y las métricas del proceso.
    """
    resultado = ResultadoDeduplicacion(registros_entrada=len(registros))
    por_clave: dict[str, Cliente] = {}
    proximo_id = 1

    for apellido, nombre, documento, recetas, incidencias in registros:
        clave_apellido = normalizador.normalizar_clave(apellido)
        clave_nombre = normalizador.normalizar_clave(nombre)
        clave = f"{clave_apellido}|{clave_nombre}"

        existente = por_clave.get(clave)

        if existente is None:
            cliente = Cliente(
                id_cliente=proximo_id,
                apellido=normalizador.normalizar_nombre(apellido),
                nombre=normalizador.normalizar_nombre(nombre),
                clave=clave,
                documento=documento,
                recetas=list(recetas),
                incidencias=list(incidencias),
            )
            proximo_id += 1

            if _es_registro_basura(clave_apellido, clave_nombre):
                cliente.posible_registro_basura = 1
                cliente.incidencias.append(
                    (
                        Motivo.POSIBLE_REGISTRO_BASURA,
                        f"apellido {apellido!r} y nombre {nombre!r} parecen de prueba",
                    )
                )

            if not clave_apellido:
                cliente.requiere_revision = 1
                cliente.incidencias.append(
                    (Motivo.APELLIDO_VACIO, "el campo APELLIDO vino vacío")
                )

            por_clave[clave] = cliente
            continue

        # El cliente ya existe: NUNCA se sobrescribe, se fusiona.
        resultado.clientes_fusionados += 1
        existente.registros_fusionados += 1
        existente.recetas.extend(recetas)
        existente.incidencias.extend(incidencias)
        _resolver_documento(existente, documento)

    for cliente in por_clave.values():
        resultado.visitas_fusionadas += _fusionar_visitas(cliente)
        if any(
            motivo is Motivo.DOCUMENTO_EN_CONFLICTO for motivo, _ in cliente.incidencias
        ):
            resultado.conflictos_documento += 1
    resultado.clientes = sorted(
        por_clave.values(), key=lambda c: (c.clave, c.id_cliente)
    )

    # Se reasignan los identificadores para que sean estables entre corridas:
    # dependen sólo del orden alfabético de la clave, no del orden del archivo.
    for nuevo_id, cliente in enumerate(resultado.clientes, start=1):
        cliente.id_cliente = nuevo_id

    _log.info(
        "Deduplicación: %d registros -> %d clientes (%d fusiones, "
        "%d visitas duplicadas colapsadas, %d conflictos de documento)",
        resultado.registros_entrada,
        len(resultado.clientes),
        resultado.clientes_fusionados,
        resultado.visitas_fusionadas,
        resultado.conflictos_documento,
    )
    return resultado
