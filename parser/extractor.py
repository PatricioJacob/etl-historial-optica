# -*- coding: utf-8 -*-
"""
Capa de TRANSFORMACIÓN: extrae los campos estructurados de una visita.

Recibe una :class:`~parser.segmentador.Visita` y devuelve una :class:`Receta`
con las medidas, el modelo, el doctor y las observaciones.

CONTRATO DEL MÓDULO
-------------------
1. Ninguna regex se aplica al bloque completo: se recorre línea por línea y
   cada patrón ve como máximo una línea. Es lo que evita el backtracking
   catastrófico sobre las líneas de 553 caracteres del archivo.
2. Nada se inventa. Si un valor no está en el texto, queda ``None``.
3. Nada se pierde en silencio. Toda línea que ningún patrón supo interpretar
   queda registrada como incidencia con el texto exacto que falló.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import normalizador, patrones
from .motivos import Motivo
from .segmentador import Visita

#: Secciones cuyas medidas se guardan en las columnas de lejos.
SECCIONES_LEJOS: frozenset[str] = frozenset({"LEJOS"})

#: Secciones cuyas medidas se guardan en las columnas de cerca.
#: ``INTERMEDIA`` se agrupa con cerca porque son sólo 221 casos y no justifica
#: seis columnas propias; queda anotado en ``observaciones`` que era intermedia.
SECCIONES_CERCA: frozenset[str] = frozenset({"CERCA", "INTERMEDIA"})

#: Secciones cuyas medidas se guardan en las columnas de lentes de contacto.
SECCIONES_CONTACTO: frozenset[str] = frozenset(
    {"LENTES_CONTACTO", "RP_MEDICO", "RP_CONTACTOLOGO"}
)

# ===========================================================================
# PRESCRIPCIÓN VIGENTE DE LENTES DE CONTACTO
# ===========================================================================

#: Cuál de las dos prescripciones se considera vigente cuando el bloque trae
#: ambas.
#:
#: CONFIRMADO por el encargado de la óptica el 05/10/2026: si hay prescripción
#: del contactólogo, ésa es la vigente; si no, la del médico.
#:
#: Un bloque de lentes de contacto puede traer DOS graduaciones distintas y las
#: dos son ciertas:
#:
#:   ``RP. MEDICO:``       lo que el oftalmólogo indicó
#:   ``RP. CONTACTOLOGO:`` lo que el contactólogo adaptó
#:
#: Difieren de forma normal: la lente apoya sobre el ojo y el anteojo está a
#: 12 mm, así que la potencia efectiva no es la misma.
#:
#: Las dos se guardan SIEMPRE y completas en ``lc_med_*`` y ``lc_cont_*``. Esta
#: constante decide únicamente cuál de las dos se copia a las columnas
#: "vigentes" (``lc_od_esf`` y compañía), que son las que va a mostrar la
#: aplicación de la Fase 2.
#:
#: Valores admitidos: ``"MEDICO"`` o ``"CONTACTOLOGO"``.
#:
#: Vale ``"CONTACTOLOGO"`` porque la lente que la persona efectivamente usa es
#: la que adaptó el contactólogo. Hasta el 05/10/2026 valió ``"MEDICO"``, a la
#: espera de esa confirmación. Cambiarla es editar esta línea y volver a correr
#: el ETL: nada más.
PRESCRIPCION_VIGENTE: str = "CONTACTOLOGO"

#: Destino interno de las medidas según el prescriptor que las firma.
DESTINO_LC_MEDICO: str = "LC_MED"
DESTINO_LC_CONTACTOLOGO: str = "LC_CONT"
DESTINO_LC_SIN_ETIQUETA: str = "LC_SIN"

#: Valores admitidos en la columna ``lc_prescriptor_vigente``.
PRESCRIPTOR_MEDICO: str = "MEDICO"
PRESCRIPTOR_CONTACTOLOGO: str = "CONTACTOLOGO"
PRESCRIPTOR_SIN_ESPECIFICAR: str = "SIN_ESPECIFICAR"

#: Sección interna de una receta de anteojos escrita a mano tras ``R.P.:``.
#: No tiene columnas: sus renglones no se leen.
SECCION_RP_DE_ANTEOJOS: str = "RP_ANTEOJOS"

#: Los tres destinos de lentes de contacto.
DESTINOS_LC: frozenset[str] = frozenset(
    {DESTINO_LC_MEDICO, DESTINO_LC_CONTACTOLOGO, DESTINO_LC_SIN_ETIQUETA}
)

#: Qué sección del texto alimenta cada destino de lentes de contacto.
_SECCION_A_DESTINO_LC: dict[str, str] = {
    "RP_MEDICO": DESTINO_LC_MEDICO,
    "RP_CONTACTOLOGO": DESTINO_LC_CONTACTOLOGO,
    "LENTES_CONTACTO": DESTINO_LC_SIN_ETIQUETA,
}


@dataclass
class Receta:
    """Una receta ya estructurada, lista para cargar en la base.

    Los nombres de los atributos coinciden con los de las columnas de la tabla
    ``recetas``, para que la carga sea directa y no haya un mapeo intermedio
    que mantener.
    """

    id_bloque: str = ""
    fecha: date | None = None
    tipo_registro: str = "VENTA"

    od_lejos_esf: str | None = None
    od_lejos_cil: str | None = None
    od_lejos_eje: str | None = None
    oi_lejos_esf: str | None = None
    oi_lejos_cil: str | None = None
    oi_lejos_eje: str | None = None

    adicion: str | None = None

    od_cerca_esf: str | None = None
    od_cerca_cil: str | None = None
    od_cerca_eje: str | None = None
    oi_cerca_esf: str | None = None
    oi_cerca_cil: str | None = None
    oi_cerca_eje: str | None = None

    # --- Lentes de contacto · prescripción VIGENTE -------------------------
    #
    # Es la que muestra la aplicación. La llena el prescriptor que indique
    # PRESCRIPCION_VIGENTE, y ``lc_prescriptor_vigente`` dice cuál fue.
    lc_od_esf: str | None = None
    lc_od_cil: str | None = None
    lc_od_eje: str | None = None
    lc_oi_esf: str | None = None
    lc_oi_cil: str | None = None
    lc_oi_eje: str | None = None
    lc_prescriptor_vigente: str | None = None

    # --- Lentes de contacto · lo que indicó el MÉDICO ----------------------
    lc_med_od_esf: str | None = None
    lc_med_od_cil: str | None = None
    lc_med_od_eje: str | None = None
    lc_med_oi_esf: str | None = None
    lc_med_oi_cil: str | None = None
    lc_med_oi_eje: str | None = None

    # --- Lentes de contacto · lo que adaptó el CONTACTÓLOGO ----------------
    lc_cont_od_esf: str | None = None
    lc_cont_od_cil: str | None = None
    lc_cont_od_eje: str | None = None
    lc_cont_oi_esf: str | None = None
    lc_cont_oi_cil: str | None = None
    lc_cont_oi_eje: str | None = None

    # --- Lentes de contacto · el LENTE que se entregó ----------------------
    #
    # Sale del renglón de la sección ``LENTES DE CONTACTO``, antes de ``Tipo
    # L.C.`` o ``Marca L.C.``. La potencia del lente NO es la esfera de la
    # receta y nunca la pisa. El nivel (HIGH, MED, LOW, MID) se guarda tal como
    # está escrito, sin interpretarlo.
    lc_od_potencia_lente: str | None = None
    lc_od_nivel: str | None = None
    lc_oi_potencia_lente: str | None = None
    lc_oi_nivel: str | None = None

    # --- Lentes de contacto · datos físicos de la lente --------------------
    #
    # Curva base y diámetro van POR OJO. Un valor escrito sin ojo, o con
    # ``AO``, se copia en los dos. Sólo se leen en una visita de lentes de
    # contacto y sólo con su etiqueta (``CB``, ``Ø``, ``DIAM``).
    lc_od_curva_base: str | None = None
    lc_oi_curva_base: str | None = None
    lc_od_diametro: str | None = None
    lc_oi_diametro: str | None = None
    lc_marca: str | None = None
    lc_tipo: str | None = None
    # Cantidad entregada, tal como está escrita y con su unidad: "1 CAJA",
    # "2 PARES". Si hay más de una, van separadas por " | ".
    lc_cantidad: str | None = None

    di: str | None = None
    di_lejos: str | None = None
    di_cerca: str | None = None
    altura: str | None = None

    tipo_lente: str | None = None
    modelo_anteojo: str | None = None
    codigo_modelo: str | None = None
    tratamientos: str | None = None
    doctor: str | None = None
    observaciones: str | None = None

    origen: str = "parseado"
    texto_original: str = ""

    #: Incidencias detectadas, como pares ``(Motivo, detalle)``.
    incidencias: list[tuple[Motivo, str]] = field(default_factory=list)

    def tiene_alguna_medida(self) -> bool:
        """Indica si la receta contiene al menos un valor óptico.

        Returns:
            ``True`` si hay alguna esfera, cilindro, adición o medida de
            lente de contacto.
        """
        campos = (
            self.od_lejos_esf,
            self.oi_lejos_esf,
            self.od_cerca_esf,
            self.oi_cerca_esf,
            self.adicion,
            self.lc_od_esf,
            self.lc_oi_esf,
            self.od_lejos_cil,
            self.oi_lejos_cil,
        )
        return any(campo is not None for campo in campos)


class _AcumuladorOjos:
    """Guarda las medidas por sección y ojo mientras se recorre la visita.

    Se usa un acumulador en vez de escribir directo en la receta porque la
    misma sección puede aparecer más de una vez en un bloque, y porque el ojo
    ``AO`` (ambos ojos) tiene que replicarse en OD y OI.
    """

    def __init__(self) -> None:
        self._datos: dict[tuple[str, str], dict[str, str]] = {}
        # Renglón que la regla estricta de lentes de contacto dejó sin leer,
        # por prescripción y ojo. Esa prescripción queda vacía para ese ojo.
        self._sin_leer: dict[tuple[str, str], str] = {}
        #: Pares ``(renglón que no se leyó, renglón que no se usó)``, en el
        #: orden en que aparecen. Cada par abre un caso
        #: ``receta_repetida_distinta``.
        self.repetidas: list[tuple[str, str]] = []
        # Primer renglón que cargó algún valor, por prescripción y ojo.
        self._renglon_leido: dict[tuple[str, str], str] = {}
        #: Pares ``(renglón que se usa, renglón que no se leyó)``: el caso
        #: inverso. La columna conserva el primero, pero el caso se abre igual.
        self.repetidas_despues: list[tuple[str, str]] = []

    def quedo_sin_leer(self, seccion: str) -> bool:
        """Indica si una prescripción existe pero no se pudo leer nada de ella.

        Args:
            seccion: Destino de lentes de contacto (``LC_MED``, ...).

        Returns:
            ``True`` si algún renglón suyo no se leyó por la regla estricta y
            no tiene ningún valor cargado, en ninguno de los dos ojos.
        """
        tiene_datos = any(clave[0] == seccion for clave in self._datos)
        sin_leer = any(clave[0] == seccion for clave in self._sin_leer)
        return sin_leer and not tiene_datos

    def bloquear(self, seccion: str, ojo: str, renglon: str) -> None:
        """Deja vacía una prescripción cuyo renglón no se pudo leer.

        REGLA: si el renglón de una prescripción no se lee por la regla
        estricta, esa prescripción queda vacía. No se completa con otro renglón
        de la misma visita, aunque parezca la misma receta: las dos copias
        pueden diferir (``Esf. -9.50`` en una y ``-8.75`` en la otra) y no se
        sabe cuál vale.

        Sólo bloquea si la prescripción todavía no tiene nada para ese ojo. Si
        un renglón anterior ya se leyó, la columna conserva ése, como siempre,
        y el par de renglones queda en ``repetidas_despues`` para abrir el
        caso igual: son dos versiones de la misma receta.

        Args:
            seccion: Destino de lentes de contacto (``LC_MED``, ...).
            ojo: ``OD``, ``OI`` o ``AO``.
            renglon: El renglón que no se leyó, para el caso de revisión.
        """
        objetivos = ("OD", "OI") if ojo == "AO" else (ojo,)
        for destino in objetivos:
            if (seccion, destino) not in self._datos:
                self._sin_leer.setdefault((seccion, destino), renglon)
                continue
            par = (self._renglon_leido.get((seccion, destino), ""), renglon)
            if par not in self.repetidas_despues:
                self.repetidas_despues.append(par)

    def guardar(
        self, seccion: str, ojo: str, campo: str, valor: str | None, renglon: str = ""
    ) -> None:
        """Registra un valor, sin pisar uno ya guardado.

        Se conserva el PRIMER valor encontrado: en los bloques que repiten
        sección, el primero es el de la receta y los siguientes suelen ser
        anotaciones posteriores.

        Si la prescripción está bloqueada para ese ojo (ver :meth:`bloquear`)
        el valor no se guarda, y el par de renglones queda en ``repetidas``.

        Args:
            seccion: Sección lógica (``LEJOS``, ``CERCA``, ...).
            ojo: ``OD``, ``OI`` o ``AO``.
            campo: ``esf``, ``cil`` o ``eje``.
            valor: Valor ya normalizado, o ``None`` para no hacer nada.
            renglon: El renglón del que sale el valor.
        """
        if valor is None:
            return

        objetivos = ("OD", "OI") if ojo == "AO" else (ojo,)
        for destino in objetivos:
            sin_leer = self._sin_leer.get((seccion, destino))
            if sin_leer is not None:
                par = (sin_leer, renglon)
                if par not in self.repetidas:
                    self.repetidas.append(par)
                continue
            celda = self._datos.setdefault((seccion, destino), {})
            celda.setdefault(campo, valor)
            self._renglon_leido.setdefault((seccion, destino), renglon)

    def obtener(self, seccion: str, ojo: str, campo: str) -> str | None:
        """Recupera un valor guardado.

        Args:
            seccion: Sección lógica.
            ojo: ``OD`` o ``OI``.
            campo: ``esf``, ``cil`` o ``eje``.

        Returns:
            El valor, o ``None`` si no se registró.
        """
        return self._datos.get((seccion, ojo), {}).get(campo)

    def secciones_con_datos(self) -> set[str]:
        """Devuelve las secciones para las que se guardó algún valor.

        Returns:
            Conjunto de nombres de sección.
        """
        return {seccion for seccion, _ in self._datos}


def _identificar_seccion(linea: str) -> str | None:
    """Reconoce un encabezado de sección.

    Args:
        linea: Línea del bloque.

    Returns:
        El nombre lógico de la sección, o ``None`` si la línea no es un
        encabezado conocido.
    """
    for nombre, patron in patrones.SECCIONES.items():
        if patron.match(linea):
            return nombre
    return None


def _extraer_medidas_de_linea(
    resto: str, seccion: str
) -> tuple[str | None, str | None, str | None]:
    """Extrae esfera, cilindro y eje del contenido de una línea de ojo.

    Aplica los patrones en orden de confiabilidad decreciente:

    1. Etiquetas explícitas ``Esf.`` y ``Cil.`` (formato Moebius, mayoritario).
    2. Dos números desnudos consecutivos: el primero es la esfera y el segundo
       el cilindro. Caso ``LEJOS: O.D: +1.25 -0.50 EN 95`` del dialecto
       manuscrito.
    3. Un único número desnudo al principio: es la potencia. Caso
       ``O.D. -11.50`` de lentes de contacto.

    Args:
        resto: Contenido de la línea después de la etiqueta de ojo.
        seccion: Sección en la que aparece, para decidir si el número desnudo
            es admisible.

    Returns:
        Tupla ``(esfera, cilindro, eje)``, cada uno normalizado o ``None``.
    """
    esfera: str | None = None
    cilindro: str | None = None

    coincidencia_esf = patrones.ESFERA.search(resto)
    if coincidencia_esf is not None:
        esfera = normalizador.normalizar_decimal(coincidencia_esf.group("valor"))

    coincidencia_cil = patrones.CILINDRO.search(resto)
    if coincidencia_cil is not None:
        cilindro = normalizador.normalizar_decimal(coincidencia_cil.group("valor"))

    # Sin etiqueta explícita: se leen los números desnudos.
    if esfera is None:
        par = patrones.NUMERO_DESNUDO_SEGUNDO.match(resto)
        if par is not None:
            esfera = normalizador.normalizar_decimal(par.group("primero"))
            if cilindro is None:
                cilindro = normalizador.normalizar_decimal(par.group("segundo"))
        else:
            solo = patrones.NUMERO_DESNUDO_INICIAL.match(resto)
            if solo is not None:
                esfera = normalizador.normalizar_decimal(solo.group("valor"))

    # El eje se busca sobre el texto posterior al cilindro, si lo hubo. Así el
    # patrón de eje no puede confundirse con el propio valor del cilindro.
    desde = coincidencia_cil.end() if coincidencia_cil is not None else 0
    coincidencia_eje = patrones.EJE.search(resto[desde:])
    eje = (
        normalizador.normalizar_eje(coincidencia_eje.group("valor"))
        if coincidencia_eje is not None
        else None
    )

    return esfera, cilindro, eje


def _clasificar_tipo_lente(secciones_vistas: set[str]) -> str | None:
    """Determina el tipo de lente a partir de las secciones presentes.

    Args:
        secciones_vistas: Secciones que aparecieron en el bloque.

    Returns:
        ``"BI/MULTIFOCAL"``, ``"LENTES DE CONTACTO"``, ``"MONOFOCAL"`` o
        ``None`` si el bloque no tiene ninguna sección óptica.
    """
    if "BI_MULTIFOCAL" in secciones_vistas:
        return "BI/MULTIFOCAL"
    if secciones_vistas & SECCIONES_CONTACTO:
        return "LENTES DE CONTACTO"
    if secciones_vistas & (SECCIONES_LEJOS | SECCIONES_CERCA):
        return "MONOFOCAL"
    return None


def _leer_renglon_de_lente(resto: str) -> tuple[str | None, str | None]:
    """Lee la potencia y el nivel de un renglón del lente entregado.

    Los dos valores se devuelven TAL COMO ESTÁN ESCRITOS, sin normalizar:

    * la potencia, con el signo pegado al número (``+2.75``);
    * el nivel, con el texto que lo rodea y sin el número (``HIGH``,
      ``ADD. HIGH``, ``/add HIGH``, ``med``). Cuando lo único que hay delante es
      la barra que lo separa de la potencia (``+2.75/HIGH``), la barra se quita.

    Una potencia SIN signo sólo se acepta si viene seguida de un nivel. Un
    número sin signo y sin nivel puede ser una curva base (``O.D. 8.40``), y no
    se adivina.

    Args:
        resto: Texto del renglón después de la etiqueta de ojo.

    Returns:
        Tupla ``(potencia, nivel)``; cada uno ``None`` si no está.
    """
    coincidencia = patrones.RENGLON_DE_LENTE.match(resto)
    if coincidencia is None:
        return None, None

    potencia = coincidencia.group("potencia")
    nivel = coincidencia.group("nivel")

    if nivel is not None:
        nivel = patrones.ESPACIOS_MULTIPLES.sub(" ", nivel).strip()
        sin_barra = nivel.lstrip("/").strip()
        if patrones.NIVEL_ADICION.fullmatch(sin_barra):
            nivel = sin_barra

    if potencia is not None:
        potencia = patrones.ESPACIOS_MULTIPLES.sub("", potencia)
        if potencia[0] not in "+-" and nivel is None:
            potencia = None

    return potencia, nivel


def _sin_lo_etiquetado(resto: str) -> str:
    """Quita de un renglón todo lo que viene con su etiqueta.

    Saca ``Esf.``, ``Cil.``, el eje, la curva base, el diámetro, la adición y
    lo que lleva números sin ser una medida (lote, vencimiento, fechas,
    agudeza visual, y los nombres de producto con número como ``BIOMEDICS
    55``). Lo que queda son los números SIN etiqueta y el texto.

    Args:
        resto: Texto del renglón después de la etiqueta de ojo.

    Returns:
        El renglón con cada tramo etiquetado reemplazado por un espacio.
    """
    texto = resto
    for patron in (
        patrones.NO_ES_MEDIDA_LC,
        patrones.PRODUCTO_CON_NUMERO,
        patrones.ESFERA,
        patrones.CILINDRO,
        patrones.EJE,
        patrones.CURVA_BASE,
        patrones.DIAMETRO_LC,
        patrones.ADICION,
    ):
        texto = patron.sub(" ", texto)
    return texto


def _unico_numero_sin_etiqueta(resto: str) -> str | None:
    """Devuelve el renglón a partir de su único número sin etiqueta.

    Sirve para leer la potencia cuando no está al principio del renglón:
    ``O.D. CB 8.40 -2.50 DIA. 9.60``. Sólo se llama después de comprobar con
    :func:`_medidas_sin_etiqueta` que el renglón se puede leer sin adivinar.

    Args:
        resto: Texto del renglón después de la etiqueta de ojo.

    Returns:
        El texto desde ese número en adelante, o ``None`` si no hay ninguno.
    """
    texto = _sin_lo_etiquetado(resto)
    numero = patrones.NUMERO_SUELTO.search(texto)
    return texto[numero.start():] if numero is not None else None


def _medidas_sin_etiqueta(resto: str) -> bool:
    """Indica si un renglón de lentes de contacto trae números sin asignar.

    REGLA: un número sin etiqueta no se asigna por su posición.

    ``O.D. 8.40 -2.50 9.60`` es casi seguro curva base, potencia y diámetro de
    una lente rígida, pero qué es cada número depende del orden en que lo
    escribió el empleado, y eso no se asume. Se devuelve ``True`` cuando el
    renglón tiene algún NÚMERO SUELTO: un número sin etiqueta que no es la
    única potencia con signo del renglón. Es decir cuando, quitado todo lo que
    viene con su etiqueta (``Esf.``, ``Cil.``, ``En``, ``CB``, ``Ø``, ``DIAM``,
    ``ADD``, lote, vencimiento, ``A.V.``, nombres de producto con número):

    * queda MÁS DE UN número; o
    * queda un único número SIN signo que no va seguido de un nivel; o
    * queda un único número y el renglón YA tiene una esfera con etiqueta: la
      potencia es la esfera, así que ese otro número está suelto
      (``O.D. Esf. -2.50 8.40``).

    Sigue valiendo lo de siempre: un solo número con signo (``O.D. -11.50``)
    es una potencia, y un número con nivel (``1.75/HIGH``) también.

    Cuando devuelve ``True`` NO SE LEE NADA del renglón, tampoco lo que tiene
    etiqueta: hasta que el encargado confirme qué son esos números, nada que
    dependa de la posición de un número llega a una columna.

    Args:
        resto: Texto del renglón después de la etiqueta de ojo.

    Returns:
        ``True`` si el renglón no se puede leer sin adivinar.
    """
    texto = _sin_lo_etiquetado(resto)
    numeros = list(patrones.NUMERO_SUELTO.finditer(texto))
    if len(numeros) > 1:
        return True
    if len(numeros) == 1:
        if patrones.ESFERA.search(resto):
            return True
        numero = numeros[0].group(0).strip()
        con_signo = numero[0] in "+-"
        con_nivel = patrones.NUMERO_CON_NIVEL.match(texto, numeros[0].start())
        return not con_signo and con_nivel is None
    return False


def _cantidad_entregada(receta: Receta) -> str | None:
    """Busca la cantidad entregada, tal como está escrita y con su unidad.

    ``1 CAJA``, ``2 PARES``, ``1 PAR``. No se convierte a unidades: una caja no
    trae siempre la misma cantidad de lentes. Se busca en las observaciones,
    la marca y el tipo de la visita. Si hay más de una, se devuelven todas
    separadas por ``" | "``, en el orden en que aparecen.

    Args:
        receta: Visita de lentes de contacto.

    Returns:
        La cantidad o cantidades, o ``None`` si no hay ninguna.
    """
    halladas: list[str] = []
    for texto in (receta.observaciones, receta.lc_marca, receta.lc_tipo):
        for coincidencia in patrones.CANTIDAD_LC.finditer(texto or ""):
            cantidad = " ".join(coincidencia.group(0).split())
            if cantidad not in halladas:
                halladas.append(cantidad)
    return " | ".join(halladas) or None


def _clasificar_por_texto_libre(texto_libre: str) -> tuple[bool, bool]:
    """Decide si una visita sin ninguna sección es de lentes de contacto.

    Decisiones del equipo sobre el diagnóstico del 08/10/2026:

    * nombra una MARCA de lentes de contacto -> es de lentes de contacto;
    * no nombra marca, pero sí CAJAS o DESCARTABLES -> también, pero la señal
      es más débil y se abre un caso ``lc_clasificada_por_caja``;
    * sólo nombra líquidos, o sólo dice "lentes de contacto" en un comentario
      -> NO se reclasifica. Lo segundo suele ser un anteojo "para usar arriba
      del lente de contacto".

    Args:
        texto_libre: Las observaciones de la visita.

    Returns:
        Tupla ``(es_lente_de_contacto, fue_por_caja)``.
    """
    if patrones.MARCA_LC_EN_TEXTO.search(texto_libre):
        return True, False
    if patrones.LIQUIDO_LC.search(texto_libre) or patrones.MENCION_LC.search(texto_libre):
        return False, False
    if patrones.CAJA_O_DESCARTABLE.search(texto_libre):
        return True, True
    return False, False


def _queda_texto_ademas_de_medidas(resto: str, es_renglon_de_lente: bool) -> bool:
    """Indica si un renglón de ojo trae texto además de sus medidas.

    Se usa sólo en lentes de contacto. Ahí, lo que no es una medida es un
    comentario del empleado (lote, vencimiento, agudeza visual, marca, un nivel
    fuera de lugar) y tiene que quedar en observaciones en vez de descartarse.

    Args:
        resto: Texto del renglón después de la etiqueta de ojo.
        es_renglon_de_lente: Si el renglón está en el tramo del lente, donde
            la potencia y el nivel ya se leyeron y no cuentan como sobrante.

    Returns:
        ``True`` si, quitadas todas las medidas reconocidas, quedan al menos
        dos letras.
    """
    # Un lote, un vencimiento o una agudeza visual son comentarios aunque no
    # dejen ninguna letra suelta ("O.D. 2016/05").
    if patrones.NO_ES_MEDIDA_LC.search(resto):
        return True

    texto = resto
    if es_renglon_de_lente:
        coincidencia = patrones.RENGLON_DE_LENTE.match(texto)
        if coincidencia is not None:
            texto = texto[coincidencia.end():]

    for patron in (
        patrones.ESFERA,
        patrones.CILINDRO,
        patrones.EJE,
        patrones.CURVA_BASE,
        patrones.DIAMETRO_LC,
        patrones.NUMERO_SUELTO,
    ):
        texto = patron.sub(" ", texto)

    return sum(1 for caracter in texto if caracter.isalpha()) >= 2


def _guardar_curva_base_y_diametro(
    receta: Receta, texto: str, ojos: tuple[str, ...]
) -> None:
    """Guarda la curva base y el diámetro en el ojo que corresponde.

    Nunca pisa un valor ya cargado para ese ojo.

    Args:
        receta: Receta que se está construyendo.
        texto: Renglón, o resto del renglón, a inspeccionar.
        ojos: Ojos a los que aplica: ``("OD",)``, ``("OI",)`` o los dos cuando
            el valor viene sin ojo o con ``AO``.
    """
    for patron, campo in (
        (patrones.CURVA_BASE, "curva_base"),
        (patrones.DIAMETRO_LC, "diametro"),
    ):
        coincidencia = patron.search(texto)
        if coincidencia is None:
            continue
        valor = normalizador.normalizar_milimetros(coincidencia.group("valor"))
        if valor is None:
            continue
        for ojo in ojos:
            atributo = f"lc_{ojo.lower()}_{campo}"
            if getattr(receta, atributo) is None:
                setattr(receta, atributo, valor)


def _volcar_lentes_de_contacto(receta: Receta, acumulador: _AcumuladorOjos) -> None:
    """Vuelca las medidas de lentes de contacto a sus columnas.

    Guarda las DOS prescripciones completas y sin elegir entre ellas, y después
    copia una de las dos a las columnas vigentes según
    :data:`PRESCRIPCION_VIGENTE`.

    Nunca se completa una prescripción con la otra: si el bloque trae sólo
    ``RP. MEDICO:``, las columnas ``lc_cont_*`` quedan nulas. Copiar los valores
    del médico ahí sería inventar una adaptación que nadie hizo.

    Args:
        receta: Receta a completar. Se modifica en el lugar.
        acumulador: Medidas ya acumuladas por destino y ojo.
    """
    # --- Las dos prescripciones, completas y separadas ---------------------
    for prefijo, destino in (
        ("lc_med", DESTINO_LC_MEDICO),
        ("lc_cont", DESTINO_LC_CONTACTOLOGO),
    ):
        for ojo in ("od", "oi"):
            for campo in ("esf", "cil", "eje"):
                valor = acumulador.obtener(destino, ojo.upper(), campo)
                setattr(receta, f"{prefijo}_{ojo}_{campo}", valor)

    # --- Cuál manda en las columnas vigentes -------------------------------
    #
    # Orden de preferencia: el prescriptor elegido, después el otro, y por
    # último la sección sin etiquetar. Se elige el PRIMERO que tenga algún dato.
    if PRESCRIPCION_VIGENTE == PRESCRIPTOR_CONTACTOLOGO:
        preferencia = (
            (DESTINO_LC_CONTACTOLOGO, PRESCRIPTOR_CONTACTOLOGO),
            (DESTINO_LC_MEDICO, PRESCRIPTOR_MEDICO),
        )
    else:
        preferencia = (
            (DESTINO_LC_MEDICO, PRESCRIPTOR_MEDICO),
            (DESTINO_LC_CONTACTOLOGO, PRESCRIPTOR_CONTACTOLOGO),
        )
    preferencia += ((DESTINO_LC_SIN_ETIQUETA, PRESCRIPTOR_SIN_ESPECIFICAR),)

    # REGLA GENERAL: si la prescripción que corresponde mostrar (la del
    # prescriptor elegido; si no existe, la del otro) existe pero no se pudo
    # leer, porque su renglón tiene un número suelto, la vigente queda VACÍA y
    # con la etiqueta de ese prescriptor. No se completa con otra: se sabe que
    # escribió algo que no pudimos leer. Vale para el médico y el contactólogo;
    # la sección sin prescriptor no tiene a quién atribuirle una vigente vacía.
    for destino, etiqueta in preferencia:
        if destino != DESTINO_LC_SIN_ETIQUETA and acumulador.quedo_sin_leer(destino):
            receta.lc_prescriptor_vigente = etiqueta
            return
        valores = {
            f"lc_{ojo}_{campo}": acumulador.obtener(destino, ojo.upper(), campo)
            for ojo in ("od", "oi")
            for campo in ("esf", "cil", "eje")
        }
        if not any(v is not None for v in valores.values()):
            continue
        for columna, valor in valores.items():
            setattr(receta, columna, valor)
        receta.lc_prescriptor_vigente = etiqueta
        return


def _seccion_destino(seccion: str) -> str | None:
    """Traduce una sección del texto al grupo de columnas donde se guarda.

    Las tres secciones de lentes de contacto van a destinos SEPARADOS, para no
    mezclar la indicación del médico con la adaptación del contactólogo: son
    datos clínicos distintos y los dos son ciertos.

    Args:
        seccion: Nombre lógico de la sección.

    Returns:
        ``"LEJOS"``, ``"CERCA"``, ``"LC_MED"``, ``"LC_CONT"``, ``"LC_SIN"``
        o ``None``.
    """
    if seccion in SECCIONES_LEJOS:
        return "LEJOS"
    if seccion in SECCIONES_CERCA:
        return "CERCA"
    return _SECCION_A_DESTINO_LC.get(seccion)


def extraer(visita: Visita, apellido: str, nombre: str) -> Receta:
    """Convierte una visita en una receta estructurada.

    Args:
        visita: Visita ya segmentada.
        apellido: Apellido del cliente, para calcular el ``id_bloque``.
        nombre: Nombre del cliente, para calcular el ``id_bloque``.

    Returns:
        La receta con todos los campos que se pudieron extraer y la lista de
        incidencias detectadas.
    """
    receta = Receta(
        id_bloque=normalizador.calcular_id_bloque(
            apellido, nombre, visita.texto_original
        ),
        fecha=visita.fecha,
        tipo_registro="PRESUPUESTO" if visita.es_presupuesto else "VENTA",
        texto_original=visita.texto_original,
    )

    for motivo_texto, detalle in visita.incidencias:
        receta.incidencias.append((Motivo(motivo_texto), detalle))

    acumulador = _AcumuladorOjos()
    secciones_vistas: set[str] = set()
    seccion_actual: str | None = None
    observaciones: list[str] = []
    lineas_sin_interpretar: list[str] = []
    # Línea de armado del cristal que sigue al encabezado BI/MULTIFOCAL:.
    armado_cristal: str | None = None
    # ¿El bloque ya mostró ser de lentes de contacto? Decide a dónde van las
    # líneas de ojo que aparecen sin ninguna sección abierta.
    vio_contacto = False
    # ¿Estamos en el tramo del LENTE? Va del encabezado "LENTES DE CONTACTO"
    # hasta "Tipo L.C." o "Marca L.C.". Sólo ahí un renglón de ojo describe el
    # lente entregado (potencia y nivel) y no una receta.
    tramo_lente = False
    # ¿Ya pasó la marca dentro de la sección de lentes de contacto? Un nivel
    # escrito después de la marca es un comentario: va entero a observaciones.
    paso_marca = False
    # ¿La visita trae una receta de anteojos escrita a mano tras un "R.P.:"
    # ("R.P.: LEJOS OD ...")? No se lee: ni como lentes de contacto ni, por
    # ahora, como anteojos. Sus renglones van a observaciones y a revisión.
    vio_rp_de_anteojos = False

    def anotar(texto_crudo: str) -> None:
        """Agrega un renglón a observaciones, sin repetirlo."""
        nota = normalizador.normalizar_texto_libre(texto_crudo)
        if nota is not None and nota not in observaciones:
            observaciones.append(nota)

    # NOTA DELIBERADA: no existe ninguna variable "despues_de_doctor".
    #
    # El intento anterior anclaba las observaciones a la existencia de una
    # línea "Doctor:", y por eso perdía a todos los clientes cuya nota es sólo
    # texto libre (QUIROGUEZ;MIRTA -> "LLEVO E ARDEN"). Acá el texto libre se
    # recoge SIEMPRE, haya o no línea de doctor.

    for linea in visita.lineas:
        # --- Encabezado de sección en línea propia -------------------------
        seccion = _identificar_seccion(linea)
        if seccion is not None:
            seccion_actual = seccion
            secciones_vistas.add(seccion)
            if seccion in SECCIONES_CONTACTO:
                vio_contacto = True
            tramo_lente = seccion == "LENTES_CONTACTO"
            paso_marca = False
            continue

        # --- Encabezado de CONTACTO con texto pegado tras los dos puntos ---
        #
        # Ejemplo: "RP. MEDICO:NO ES DE ESTE CLIENTE !!!!!".
        # Si no se reconoce, la sección queda sin abrir y las líneas de ojo que
        # siguen caen al destino por defecto (LEJOS), escribiendo medidas de
        # lentes de contacto en columnas de anteojos.
        # Una prescripción que no es del médico ni del contactólogo
        # ("R.P. EN USO") no se atribuye a ninguno de los dos.
        if patrones.PRESCRIPTOR_SIN_IDENTIFICAR.match(linea):
            seccion_actual = "LENTES_CONTACTO"
            secciones_vistas.add("LENTES_CONTACTO")
            vio_contacto = True
            # Es una receta ("R.P. EN USO"), no el renglón del lente.
            tramo_lente = False
            paso_marca = False

        con_ruido = patrones.SECCION_CONTACTO_CON_RUIDO.match(linea)
        if con_ruido is not None:
            etiqueta = normalizador.normalizar_clave(con_ruido.group("seccion"))
            mapa_contacto = {
                "RP MEDICO": "RP_MEDICO",
                "R P MEDICO": "RP_MEDICO",
                "RP CONTACTOLOGO": "RP_CONTACTOLOGO",
                "R P CONTACTOLOGO": "RP_CONTACTOLOGO",
                "CONTACTOLOGO": "RP_CONTACTOLOGO",
                "LENTES DE CONTACTO": "LENTES_CONTACTO",
                "LTES CTO": "LENTES_CONTACTO",
                "LTS CTO": "LENTES_CONTACTO",
            }
            nueva_seccion = mapa_contacto.get(etiqueta)
            if nueva_seccion is not None:
                seccion_actual = nueva_seccion
                secciones_vistas.add(nueva_seccion)
                vio_contacto = True
                tramo_lente = nueva_seccion == "LENTES_CONTACTO"
                paso_marca = False
                # Lo que sigue al encabezado NO se descarta: se sigue
                # procesando. Si son medidas se leen como línea de ojo; si es
                # una nota del empleado termina en observaciones.
                linea = con_ruido.group("resto")
                if not linea.strip():
                    continue

        # --- Encabezado de sección con contenido en la misma línea ---------
        con_contenido = patrones.SECCION_CON_CONTENIDO.match(linea)
        if con_contenido is not None:
            etiqueta = normalizador.normalizar_clave(con_contenido.group("seccion"))
            if etiqueta in ("RP", "R P") and patrones.RP_DE_ANTEOJOS.match(
                con_contenido.group("resto")
            ):
                # "R.P.: LEJOS OD +1.75" es una receta de ANTEOJOS, no de
                # lentes de contacto, y puede ser una copia de la sección
                # LEJOS. No se lee nada de ella.
                seccion_actual = SECCION_RP_DE_ANTEOJOS
                vio_rp_de_anteojos = True
                tramo_lente = False
                paso_marca = False
                anotar(linea)
                receta.incidencias.append((Motivo.RP_ANTEOJOS_SIN_LEER, linea.strip()))
                continue
            mapa = {
                "LEJOS": "LEJOS",
                "CERCA": "CERCA",
                "INTERMEDIA": "INTERMEDIA",
                # `R.P.` a secas NO dice quién firmó la receta. No se le
                # atribuye al médico: va al destino sin etiquetar.
                "RP": "LENTES_CONTACTO",
                "R P": "LENTES_CONTACTO",
                "LTES CTO": "LENTES_CONTACTO",
            }
            seccion_actual = mapa.get(etiqueta, seccion_actual)
            if seccion_actual is not None:
                secciones_vistas.add(seccion_actual)
                if seccion_actual in SECCIONES_CONTACTO:
                    vio_contacto = True
            # `R.P.:` a secas es una receta, no el renglón del lente. Sólo
            # `LTES.CTO.:` abre el tramo del lente.
            tramo_lente = etiqueta == "LTES CTO"
            paso_marca = False
            linea = con_contenido.group("resto")

        # --- Línea de doctor ----------------------------------------------
        coincidencia_doctor = patrones.DOCTOR.match(linea)
        if coincidencia_doctor is None:
            coincidencia_doctor = patrones.DOCTOR_MANUSCRITO.match(linea)

        if coincidencia_doctor is not None:
            crudo = coincidencia_doctor.group("valor").strip()
            # La fecha suelta que traiga la línea ya la tomó el segmentador;
            # acá se la saca del nombre del doctor.
            crudo = patrones.FECHA_SUELTA.sub("", crudo).strip()

            if patrones.DOCTOR_NO_ES_MEDICO.match(crudo):
                # "COPIA ANT.EN USO" y sus variantes no son un médico: son una
                # nota del empleado. Van a observaciones y el campo doctor
                # queda nulo, para no envenenar el recuento de derivaciones.
                nota = normalizador.normalizar_texto_libre(crudo)
                if nota:
                    observaciones.append(nota)
            else:
                receta.doctor = normalizador.normalizar_texto_libre(crudo)

            # La línea "Doctor:" CIERRA la sección óptica en curso. Todo lo que
            # viene después es texto libre del empleado.
            #
            # Sin esto, en un bloque que termina con
            #     BI/MULTIFOCAL:
            #       D.I. Cerca 60
            #     Doctor: OCULARI BRUNO
            #     FLEX AR VERDE PARA LEER.
            # la última línea se toma como armado del cristal en vez de como
            # observación, porque la sección BI/MULTIFOCAL seguiría abierta.
            seccion_actual = None
            tramo_lente = False
            continue

        # --- Línea de ojo --------------------------------------------------
        coincidencia_ojo = patrones.ETIQUETA_OJO.match(linea)
        if coincidencia_ojo is not None and not patrones.PLANTILLA_VACIA.match(linea):
            ojo = normalizador.normalizar_ojo(coincidencia_ojo.group("ojo"))
            resto = coincidencia_ojo.group("resto")
            if seccion_actual == SECCION_RP_DE_ANTEOJOS or (
                seccion_actual is None and vio_rp_de_anteojos
            ):
                # Renglón de la receta de anteojos escrita a mano, o un
                # renglón suelto de una visita que la trae: no se lee.
                anotar(linea)
                receta.incidencias.append((Motivo.RP_ANTEOJOS_SIN_LEER, linea.strip()))
                continue
            # Sin sección abierta hay que elegir un destino por defecto. Si el
            # bloque YA mostró ser de lentes de contacto, la línea NO puede ir
            # a columnas de anteojos: va al destino sin etiquetar, que tampoco
            # se la atribuye al médico ni al contactólogo.
            #
            # Es la salvaguarda contra la contaminación entre productos: sin
            # ella, un encabezado que el parser no reconoce manda medidas de
            # lentes de contacto a `od_lejos_cil` y `od_lejos_eje`.
            por_defecto = DESTINO_LC_SIN_ETIQUETA if vio_contacto else "LEJOS"
            destino = _seccion_destino(seccion_actual) if seccion_actual else por_defecto

            if ojo is not None and destino is not None:
                es_contacto = destino in DESTINOS_LC
                ojos = ("OD", "OI") if ojo == "AO" else (ojo,)

                # REGLA ESTRICTA: un número sin etiqueta no se asigna por su
                # posición. Si el renglón tiene algún número suelto ("O.D. 8.40
                # -2.50 9.60", "O.D. Esf. -2.50 8.40 14.0") NO SE LEE NADA de
                # él, tampoco lo que tiene etiqueta: va entero a observaciones
                # y a revisión. Pendiente de consultar con el encargado qué son
                # esos números.
                if es_contacto and _medidas_sin_etiqueta(resto):
                    anotar(linea)
                    receta.incidencias.append(
                        (Motivo.MEDIDAS_LC_SIN_ETIQUETA, linea.strip())
                    )
                    # Esa prescripción queda vacía para ese ojo: no se completa
                    # con otro renglón de la visita.
                    ya_despues = len(acumulador.repetidas_despues)
                    acumulador.bloquear(destino, ojo, linea.strip())
                    # Caso inverso: la prescripción ya estaba cargada con un
                    # renglón anterior. La columna lo conserva; el caso se abre.
                    for usado, sin_leer in acumulador.repetidas_despues[ya_despues:]:
                        receta.incidencias.append(
                            (
                                Motivo.RECETA_REPETIDA_DISTINTA,
                                f"se usa: {usado!r} / no se lee: {sin_leer!r}",
                            )
                        )
                    continue

                # Un renglón con nivel escrito DEBAJO de la marca ("AO +2.25 /
                # HIGH" después de "Marca L.C. SOFLENS") se lee igual que un
                # renglón del tramo del lente, y además queda entero en
                # observaciones.
                nivel_tras_la_marca = (
                    es_contacto
                    and seccion_actual == "LENTES_CONTACTO"
                    and paso_marca
                    and patrones.NIVEL_ADICION.search(resto) is not None
                )
                if nivel_tras_la_marca:
                    anotar(linea)

                es_renglon_de_lente = es_contacto and (tramo_lente or nivel_tras_la_marca)
                if es_renglon_de_lente:
                    # El renglón describe el LENTE entregado: su potencia y su
                    # nivel. Es un dato distinto de la receta y no la pisa.
                    potencia, nivel = _leer_renglon_de_lente(resto)
                    if potencia is None:
                        # La potencia puede no estar al principio:
                        # "O.D. CB 8.40 -2.50 DIA. 9.60".
                        desde_el_numero = _unico_numero_sin_etiqueta(resto)
                        if desde_el_numero is not None:
                            potencia, nivel_bis = _leer_renglon_de_lente(desde_el_numero)
                            nivel = nivel or nivel_bis
                    for un_ojo in ojos:
                        prefijo = f"lc_{un_ojo.lower()}"
                        if potencia is not None and getattr(receta, f"{prefijo}_potencia_lente") is None:
                            setattr(receta, f"{prefijo}_potencia_lente", potencia)
                        if nivel is not None and getattr(receta, f"{prefijo}_nivel") is None:
                            setattr(receta, f"{prefijo}_nivel", nivel)

                esfera, cilindro, eje = _extraer_medidas_de_linea(resto, destino)
                if es_contacto and esfera is None:
                    # Mismo caso: la potencia es el único número sin etiqueta
                    # del renglón, aunque no esté al principio.
                    desde_el_numero = _unico_numero_sin_etiqueta(resto)
                    if desde_el_numero is not None:
                        solo = patrones.NUMERO_DESNUDO_INICIAL.match(desde_el_numero)
                        if solo is not None:
                            esfera = normalizador.normalizar_decimal(solo.group("valor"))
                ya_repetidas = len(acumulador.repetidas)
                acumulador.guardar(destino, ojo, "esf", esfera, linea.strip())
                acumulador.guardar(destino, ojo, "cil", cilindro, linea.strip())
                acumulador.guardar(destino, ojo, "eje", eje, linea.strip())
                if len(acumulador.repetidas) > ya_repetidas:
                    # RECETA REPETIDA: el renglón de esta prescripción no se
                    # leyó por la regla estricta, y éste no la completa. Queda
                    # entero en observaciones y los dos van a revisión.
                    anotar(linea)
                    for sin_leer, sin_usar in acumulador.repetidas[ya_repetidas:]:
                        receta.incidencias.append(
                            (
                                Motivo.RECETA_REPETIDA_DISTINTA,
                                f"no se lee: {sin_leer!r} / no se usa: {sin_usar!r}",
                            )
                        )

                if seccion_actual is None:
                    secciones_vistas.add("LEJOS")

                # Lo que sobra de la línea de ojo puede traer modelo, D.I.,
                # curva base, diámetro o agudeza visual.
                _extraer_accesorios(resto, receta)

                if es_contacto:
                    _guardar_curva_base_y_diametro(receta, resto, ojos)

                    if patrones.NIVEL_EN_CILINDRO.search(resto) and not any(
                        motivo is Motivo.NIVEL_EN_CILINDRO
                        for motivo, _ in receta.incidencias
                    ):
                        # "Cil. HIGH": no se adivina qué quiso decir. El
                        # cilindro queda nulo y el renglón va a observaciones.
                        receta.incidencias.append(
                            (
                                Motivo.NIVEL_EN_CILINDRO,
                                f"nivel en el lugar del cilindro: {linea.strip()!r}",
                            )
                        )

                    # En lentes de contacto nada se descarta: si el renglón
                    # trae texto además de las medidas (lote, vencimiento,
                    # agudeza visual, un nivel fuera del tramo del lente), va
                    # entero a observaciones. También el renglón de un lente
                    # tórico, cuyo cilindro y eje no caben en la potencia.
                    lente_torico = es_renglon_de_lente and (
                        cilindro is not None or eje is not None
                    )
                    if lente_torico or _queda_texto_ademas_de_medidas(
                        resto, es_renglon_de_lente
                    ):
                        anotar(linea)
            continue

        # --- Adición -------------------------------------------------------
        coincidencia_add = patrones.ADICION.match(linea.strip())
        if coincidencia_add is not None:
            valor = normalizador.normalizar_decimal(coincidencia_add.group("valor"))
            if valor is not None and receta.adicion is None:
                receta.adicion = valor
            continue

        # --- Tratamientos --------------------------------------------------
        coincidencia_tr = patrones.TRATAMIENTOS.search(linea)
        if coincidencia_tr is not None:
            if receta.tratamientos is None:
                receta.tratamientos = normalizador.normalizar_texto_libre(
                    coincidencia_tr.group("valor")
                )
            continue

        # --- Sección desconocida -------------------------------------------
        if patrones.SECCION_CANDIDATA.match(linea):
            receta.incidencias.append(
                (Motivo.SECCION_DESCONOCIDA, f"sección {linea.strip()!r}")
            )
            continue

        # --- Marca de la lente de contacto ----------------------------------
        coincidencia_marca = patrones.MARCA_LC.search(linea)
        if coincidencia_marca is not None:
            # Si después de la marca sigue otro texto en el mismo renglón
            # ("Marca L.C. AIR OPTIX AO +1.50/ med"), la marca se corta ahí y
            # el resto va a observaciones, sin repartirse en columnas.
            valor_marca = coincidencia_marca.group("valor")
            corte = patrones.CORTE_DE_MARCA.search(valor_marca)
            if corte is not None:
                anotar(valor_marca[corte.start():])
                linea = linea[: coincidencia_marca.start("valor") + corte.start()]

        if coincidencia_marca is not None or patrones.TIPO_LC.search(linea):
            # "Tipo L.C." y "Marca L.C." cierran el tramo del lente.
            tramo_lente = False
            paso_marca = True

        # --- Línea de modelo, accesorios u observación ----------------------
        antes = (
            receta.modelo_anteojo,
            receta.di,
            receta.di_lejos,
            receta.di_cerca,
            receta.altura,
            receta.lc_marca,
            receta.lc_tipo,
            receta.lc_od_curva_base,
            receta.lc_oi_curva_base,
            receta.lc_od_diametro,
            receta.lc_oi_diametro,
        )
        _extraer_accesorios(linea, receta)
        # Curva base y diámetro escritos sin ojo valen para los dos. Sólo en
        # una visita de lentes de contacto: en anteojos "DIAM 65" es el
        # diámetro del cristal, y "EL DIA 23" es una fecha.
        if vio_contacto:
            _guardar_curva_base_y_diametro(receta, linea, ("OD", "OI"))
        despues = (
            receta.modelo_anteojo,
            receta.di,
            receta.di_lejos,
            receta.di_cerca,
            receta.altura,
            receta.lc_marca,
            receta.lc_tipo,
            receta.lc_od_curva_base,
            receta.lc_oi_curva_base,
            receta.lc_od_diametro,
            receta.lc_oi_diametro,
        )

        if antes != despues:
            # La línea aportó algún campo estructurado. Lo que venga ANTES del
            # primer campo es el armado del cristal, que en el archivo de la óptica
            # viene pegado a la D.I. y a la altura en la misma línea:
            #
            #     BI.FLAP TOP ORG BLANCO  D.I. Lejos 64.00  Altura 16.00
            #
            # Sin este rescate, ese modelo se perdía entero.
            prefijo = normalizador.normalizar_texto_libre(_prefijo_util(linea))
            if prefijo is not None and armado_cristal is None:
                armado_cristal = prefijo
            continue

        # Nada estructurado: o es el armado del cristal, o es texto libre.
        texto = normalizador.normalizar_texto_libre(linea)

        if texto is None:
            # La línea no dejó texto útil. Sólo se reporta como "no
            # interpretada" si tenía contenido real: una línea formada
            # únicamente por terminadores << >> es ruido conocido del sistema
            # viejo y NO es un fallo del parser. Sin este filtro, los 13.828
            # terminadores del archivo inundan revisar_manual.csv y tapan los
            # problemas que sí hay que mirar.
            sin_marcadores = patrones.MARCADOR.sub(" ", linea)
            if sin_marcadores.strip() and not patrones.RESIDUO_IGNORABLE.match(
                sin_marcadores
            ):
                lineas_sin_interpretar.append(linea.strip())
            continue

        if seccion_actual == "BI_MULTIFOCAL" and armado_cristal is None:
            # La línea que sigue a "BI/MULTIFOCAL:" describe cómo se arma el
            # cristal ("BI.FLAP TOP ORG FOTO.LITE", "MONO.STK AMPL AR ASFERIC").
            # No es una observación del empleado: es el modelo del anteojo.
            armado_cristal = texto
            continue

        # Texto libre. Se recoge SIEMPRE, haya o no línea "Doctor:".
        observaciones.append(texto)

        # Control de calidad: el dato NO se pierde (quedó en observaciones),
        # pero si la línea contiene algo que parece una medida óptica es que
        # falta una regla en patrones.py, y hay que saberlo.
        if patrones.SOSPECHA_MEDIDA.search(texto):
            lineas_sin_interpretar.append(texto)

    # --- Volcado del acumulador a las columnas de la receta ----------------
    receta.od_lejos_esf = acumulador.obtener("LEJOS", "OD", "esf")
    receta.od_lejos_cil = acumulador.obtener("LEJOS", "OD", "cil")
    receta.od_lejos_eje = acumulador.obtener("LEJOS", "OD", "eje")
    receta.oi_lejos_esf = acumulador.obtener("LEJOS", "OI", "esf")
    receta.oi_lejos_cil = acumulador.obtener("LEJOS", "OI", "cil")
    receta.oi_lejos_eje = acumulador.obtener("LEJOS", "OI", "eje")

    receta.od_cerca_esf = acumulador.obtener("CERCA", "OD", "esf")
    receta.od_cerca_cil = acumulador.obtener("CERCA", "OD", "cil")
    receta.od_cerca_eje = acumulador.obtener("CERCA", "OD", "eje")
    receta.oi_cerca_esf = acumulador.obtener("CERCA", "OI", "esf")
    receta.oi_cerca_cil = acumulador.obtener("CERCA", "OI", "cil")
    receta.oi_cerca_eje = acumulador.obtener("CERCA", "OI", "eje")

    _volcar_lentes_de_contacto(receta, acumulador)

    receta.tipo_lente = _clasificar_tipo_lente(secciones_vistas)

    # El modelo que viene con "Color" tiene prioridad sobre el armado del
    # cristal, porque es el que identifica el producto vendido. Si están los
    # dos, se conservan ambos separados por " | ": ninguno se descarta.
    if armado_cristal is not None:
        if receta.modelo_anteojo is None:
            receta.modelo_anteojo = armado_cristal
        elif armado_cristal not in receta.modelo_anteojo:
            receta.modelo_anteojo = f"{receta.modelo_anteojo} | {armado_cristal}"

    if observaciones:
        receta.observaciones = " | ".join(observaciones)

    # --- Visita sin secciones: ¿es de lentes de contacto? -------------------
    #
    # Sólo si no hay ninguna sección y el texto no declara un anteojo de sol.
    if receta.tipo_lente is None and not patrones.MARCADOR_ANTEOJO_SOL.search(
        receta.texto_original
    ):
        es_lc, por_caja = _clasificar_por_texto_libre(receta.observaciones or "")
        if es_lc:
            receta.tipo_lente = "LENTES DE CONTACTO"
            vio_contacto = True
            # De estos comentarios sólo se extrae lo que viene con etiqueta:
            # la curva base y el diámetro. Van sin ojo, así que a los dos. El
            # texto sigue entero en observaciones.
            for comentario in observaciones:
                _guardar_curva_base_y_diametro(receta, comentario, ("OD", "OI"))
            if por_caja:
                receta.incidencias.append(
                    (
                        Motivo.LC_CLASIFICADA_POR_CAJA,
                        (receta.observaciones or "")[:200],
                    )
                )

    if vio_contacto:
        receta.lc_cantidad = _cantidad_entregada(receta)
        # Una potencia con nivel dentro de un comentario ya no es un dato
        # perdido: la regla es que quede en observaciones. No se reporta como
        # línea sin interpretar.
        lineas_sin_interpretar = [
            renglon
            for renglon in lineas_sin_interpretar
            if not patrones.NUMERO_CON_NIVEL.search(renglon)
        ]

    # --- Incidencias finales -----------------------------------------------
    if lineas_sin_interpretar:
        muestra = " / ".join(lineas_sin_interpretar[:3])
        receta.incidencias.append(
            (Motivo.VALOR_NO_PARSEABLE, f"líneas no interpretadas: {muestra}")
        )

    if not secciones_vistas and not receta.tiene_alguna_medida():
        detalle = receta.observaciones or "bloque vacío"
        receta.incidencias.append(
            (Motivo.BLOQUE_SIN_ESTRUCTURA, detalle[:200])
        )

    if visita.fecha is None and not any(
        motivo in (Motivo.SIN_FECHA, Motivo.FECHA_INVALIDA)
        for motivo, _ in receta.incidencias
    ):
        receta.incidencias.append((Motivo.SIN_FECHA, "la visita no tiene fecha"))

    # --- Venta de anteojos de sol ------------------------------------------
    #
    # Si el bloque declara EXPLÍCITAMENTE que fue una compra de anteojos de
    # sol, deja de ser un caso dudoso: es una venta completa que no tiene
    # receta porque los anteojos de sol no llevan graduación.
    if es_venta_anteojo_sol(receta):
        receta.incidencias = [
            (motivo, detalle)
            for motivo, detalle in receta.incidencias
            if motivo not in MOTIVOS_QUE_RESUELVE_ANTEOJO_SOL
        ]

    return receta


#: Motivos que deja de tener un bloque cuando se confirma que es una venta de
#: anteojos de sol.
#:
#: * ``bloque_sin_estructura`` -- el marcador explica por qué no hay receta.
#: * ``dialecto_manuscrito``  -- el bloque se escribió a mano justamente porque
#:   no había campos estructurados que completar.
#:
#: Los demás motivos NO se tocan: si el bloque además no tiene fecha, o tiene
#: un documento en conflicto, sigue en revisión por eso.
MOTIVOS_QUE_RESUELVE_ANTEOJO_SOL: frozenset[Motivo] = frozenset(
    {Motivo.BLOQUE_SIN_ESTRUCTURA, Motivo.DIALECTO_MANUSCRITO}
)


def es_venta_anteojo_sol(receta: Receta) -> bool:
    """Indica si el bloque declara explícitamente una venta de anteojos de sol.

    Exige TRES condiciones. Las tres tienen que cumplirse:

    1. El texto contiene el marcador explícito (``ANT SOL``, ``ANTEOJO DE
       SOL``, ``LENTE DE SOL`` y sus variantes). **Nunca se infiere**: un
       bloque vacío sin marcador no es un anteojo de sol (ver el README).
    2. No aparece ningún contexto de exclusión (``RECETADO``, ``EN USO``,
       ``SE EXTRAVIO``).
    3. La receta NO tiene ninguna medida ni tipo de lente. Un anteojo de sol
       **recetado** no cuenta como venta de anteojos de sol: es una receta
       común cuya observación aclara que el cristal es solar, y el dato queda
       donde ya estaba.

    Args:
        receta: Receta ya construida, con su ``texto_original``.

    Returns:
        ``True`` sólo si las tres condiciones se cumplen.
    """
    if not patrones.MARCADOR_ANTEOJO_SOL.search(receta.texto_original):
        return False

    if patrones.EXCLUSION_ANTEOJO_SOL.search(receta.texto_original):
        return False

    if receta.tiene_alguna_medida() or receta.tipo_lente:
        return False

    return True


#: Patrones que marcan dónde termina la parte descriptiva de una línea y
#: empieza un campo estructurado. Se usan para recortar el armado del cristal.
_CORTES_DE_LINEA = (
    "DI_CALIFICADA",
    "DI_GENERICA",
    "ALTURA",
    "MARCA_LC",
    "TIPO_LC",
    "CURVA_BASE",
    "DIAMETRO",
    "TRATAMIENTOS",
    "COLOR_MODELO",
)


def _prefijo_util(linea: str) -> str:
    """Devuelve el texto de la línea anterior al primer campo estructurado.

    Args:
        linea: Línea completa.

    Returns:
        El prefijo descriptivo. Cadena vacía si la línea empieza directamente
        con un campo estructurado.
    """
    corte = len(linea)
    for nombre in _CORTES_DE_LINEA:
        patron = getattr(patrones, nombre)
        coincidencia = patron.search(linea)
        if coincidencia is not None:
            corte = min(corte, coincidencia.start())
    return linea[:corte]


def _extraer_accesorios(linea: str, receta: Receta) -> None:
    """Busca en una línea los campos que pueden aparecer en cualquier lado.

    D.I., altura, modelo, tratamientos y los campos de lentes de contacto no
    tienen posición fija: vienen sueltos, pegados a la línea de modelo del
    bloque BI/MULTIFOCAL, o al final de una línea de ojo. Por eso se buscan
    con la misma función desde varios puntos del recorrido.

    Modifica ``receta`` en el lugar. Nunca pisa un valor ya cargado: se
    conserva el primero encontrado.

    Args:
        linea: Línea o fragmento de línea a inspeccionar.
        receta: Receta que se está construyendo.
    """
    # --- Distancia interpupilar calificada (Lejos / Cerca) -----------------
    for coincidencia in patrones.DI_CALIFICADA.finditer(linea):
        calificador = coincidencia.group("calificador").upper()
        valor = normalizador.validar_di(coincidencia.group("valor"))
        if valor is None:
            continue
        if calificador == "LEJOS" and receta.di_lejos is None:
            receta.di_lejos = valor
        elif calificador == "CERCA" and receta.di_cerca is None:
            receta.di_cerca = valor

    # --- Distancia interpupilar genérica -----------------------------------
    if receta.di is None:
        coincidencia = patrones.DI_GENERICA.search(linea)
        if coincidencia is not None:
            receta.di = normalizador.validar_di(coincidencia.group("valor"))

    # --- Altura de montaje --------------------------------------------------
    if receta.altura is None:
        coincidencia = patrones.ALTURA.search(linea)
        if coincidencia is not None:
            receta.altura = normalizador.normalizar_milimetros(
                coincidencia.group("valor")
            )

    # --- Lentes de contacto -------------------------------------------------
    if receta.lc_marca is None:
        coincidencia = patrones.MARCA_LC.search(linea)
        if coincidencia is not None:
            receta.lc_marca = normalizador.normalizar_texto_libre(
                coincidencia.group("valor")
            )

    if receta.lc_tipo is None:
        coincidencia = patrones.TIPO_LC.search(linea)
        if coincidencia is not None:
            # "Tipo L.C. CONVENCIONALES      Marca L.C. ACUVUE 2" viene todo
            # en la misma línea: se corta el tipo donde empieza la marca.
            bruto = coincidencia.group("valor")
            corte = patrones.MARCA_LC.search(bruto)
            if corte is not None:
                bruto = bruto[: corte.start()]
            receta.lc_tipo = normalizador.normalizar_texto_libre(bruto)

    # --- Tratamientos --------------------------------------------------------
    if receta.tratamientos is None:
        coincidencia = patrones.TRATAMIENTOS.search(linea)
        if coincidencia is not None:
            receta.tratamientos = normalizador.normalizar_texto_libre(
                coincidencia.group("valor")
            )

    # --- Modelo del anteojo --------------------------------------------------
    #
    # La palabra "Color" introduce el MODELO/MATERIAL, no un color literal.
    if receta.modelo_anteojo is None:
        coincidencia = patrones.COLOR_MODELO.search(linea)
        if coincidencia is not None:
            bruto = coincidencia.group("modelo")
            # Se recortan los campos que puedan venir pegados después.
            for patron in (
                patrones.TRATAMIENTOS,
                patrones.DI_CALIFICADA,
                patrones.DI_GENERICA,
                patrones.ALTURA,
            ):
                corte = patron.search(bruto)
                if corte is not None:
                    bruto = bruto[: corte.start()]

            limpio = normalizador.normalizar_texto_libre(bruto)
            if limpio is not None:
                codigo = patrones.CODIGO_MODELO.match(limpio)
                if codigo is not None:
                    receta.codigo_modelo = codigo.group("codigo")
                    limpio = normalizador.normalizar_texto_libre(codigo.group("resto"))
                receta.modelo_anteojo = limpio
