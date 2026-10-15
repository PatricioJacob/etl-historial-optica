# -*- coding: utf-8 -*-
"""
Catálogo único de expresiones regulares del ETL de la óptica.

Todas las regex del proyecto viven acá, con nombre y comentario. Ningún otro
módulo escribe una regex en medio de la lógica.

POR QUÉ ESTÁN TODAS JUNTAS
--------------------------
Cuando el parser falle con un caso nuevo (y va a fallar: son 20 años de texto
escrito por personas distintas), el arreglo va a ser tocar una de estas
constantes. Si estuvieran incrustadas en el código, habría que leer 600 líneas
para encontrar cuál. Acá se busca por nombre y se corrige en un solo lugar.

CONVENCIONES
------------
* Todas se compilan una única vez al importar el módulo. Con ~64.000 recetas y
  ~30 patrones son casi 2 millones de aplicaciones: recompilar en cada
  iteración es la diferencia entre 40 segundos y media hora.
* Se evitan los cuantificadores codiciosos con `.` (`.*`, `.*?`). En su lugar se
  usan clases negadas como `[^>]*`. Sobre las líneas más largas del archivo
  (553 caracteres) un `.*?` puede provocar backtracking catastrófico.
* Todo patrón se aplica sobre UNA línea, nunca sobre el bloque completo del
  cliente. La segmentación previa es la que garantiza ese contrato.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# 1. ESTRUCTURA DEL ARCHIVO
# ---------------------------------------------------------------------------

#: Cabecera esperada del CSV crudo exportado de Moebius.
CABECERA_ESPERADA: Final[str] = "APELLIDO;NOMBRE;NUMERODOCUMENTO;NOTAS"

#: Inicio de un registro de cliente.
#:
#: Una línea abre un cliente nuevo SOLO si tiene la forma
#: ``APELLIDO;NOMBRE;DOCUMENTO;`` al principio de la línea, donde el documento
#: es exclusivamente dígitos (puede estar vacío). Cualquier otra línea acumula
#: en el cliente actual.
#:
#: Por qué así y no contando ``;``: el campo NOTAS es texto libre y puede
#: contener punto y coma. Una observación como ``CAMBIO ; ARMAZON EQUIVOCADO``
#: la interpretaría mal un contador de ``;`` si tuviera tres. Exigir la forma completa con documento numérico elimina
#: la ambigüedad: verificado contra el archivo, matchea 32.194 líneas y ninguna
#: línea de contenido.
INICIO_REGISTRO: Final[re.Pattern[str]] = re.compile(
    r"^(?P<apellido>[^;\r\n]*);(?P<nombre>[^;\r\n]*);(?P<documento>\d*);"
)

#: Línea de guiones bajos: separador visual del sistema viejo, se descarta.
SEPARADOR_VISUAL: Final[re.Pattern[str]] = re.compile(r"^\s*_{3,}\s*$")


# ---------------------------------------------------------------------------
# 2. MARCADORES << ... >>  ·  DIVISIÓN EN VISITAS
# ---------------------------------------------------------------------------

#: Cualquier marcador entre << >>, sea fecha o terminador.
#:
#: Se usa ``[^>]*`` en vez de ``.*?`` para evitar backtracking: hay líneas con
#: cinco y seis marcadores encadenados.
MARCADOR: Final[re.Pattern[str]] = re.compile(r"<<(?P<contenido>[^>]*)>>")

#: Marcador que SÍ es una fecha de visita: ``<< FECHA: dd/mm/aaaa >>``.
#:
#: 63.665 apariciones en el archivo de la óptica.
MARCADOR_FECHA: Final[re.Pattern[str]] = re.compile(
    r"<<\s*FECHA:\s*(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s*>>"
)

#: Marcador de fecha SIN el ``>>`` de cierre.
#:
#: Existe exactamente 1 caso en el archivo de la óptica, con la forma
#: ``<< FECHA: 14/05/2021`` sin cierre. Se lo rescata igual y se marca para revisión: es
#: una receta real y perderla sería peor que aceptarla con una advertencia.
MARCADOR_FECHA_SIN_CIERRE: Final[re.Pattern[str]] = re.compile(
    r"<<\s*FECHA:\s*(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\s*(?!\s*>>)"
)

#: Marcador terminador: ``<< >>``, ``<< .>>``, ``<< |>>``, ``<<  >>``, ``<< 0>>``.
#:
#: NO es una fecha. Tratarlo como fecha genera visitas fantasma.
#: 13.828 apariciones. La regla operativa es: si el contenido del marcador no
#: matchea ``FECHA:``, es terminador. Escribir literalmente ``<< >>`` deja
#: afuera las ~5.500 variantes con basura adentro.
MARCADOR_TERMINADOR: Final[re.Pattern[str]] = re.compile(r"<<[^>]{0,10}>>")

#: Marcador EXPLÍCITO de venta de anteojos de sol.
#:
#: Los anteojos de sol no llevan graduación, así que el sistema viejo no tenía
#: receta que registrar y el empleado lo anotaba a mano en el texto libre.
#: A diferencia de un bloque vacío —del que NO se infiere nada, ver el README—
#: acá el texto lo dice, y por eso sí se captura.
#:
#: Variantes que existen en el archivo (161 ocurrencias):
#:     ANT SOL          110      ANT DE SOL         2
#:     ANT.SOL           20      ANT. SOL           2
#:     ANTEOJO DE SOL    13      ANTEOJOS DE SOL    2
#:     ANTEOJO SOL        6      ANT .SOL           1
#:     LENTE DE SOL       3      LENTES DE SOL      2
#:
#: CONTROL DE FALSOS POSITIVOS
#: ---------------------------
#: El archivo tiene 145 tokens distintos que contienen ``SOL`` (2.934
#: ocurrencias): ``SOLO`` (697), ``SOLEDAD`` (188), nombres y apellidos que
#: empiezan con ``SOL``, ``SOLDADURA``… y el nombre propio ``MARIA SOL`` (31),
#: que sobrevive incluso a ``\bSOL\b``.
#:
#: Por eso el patrón exige SIEMPRE el par ANT+SOL (o LENTE DE SOL) y nunca
#: ``SOL`` suelto. Verificado sobre el archivo completo: 0 falsos positivos.
#:
#: * ``\bANT(?:EOJOS?)?`` -- ANT, ANTEOJO o ANTEOJOS, con límite de palabra.
#:   Descarta ANTIRREF, ANTERIOR, ANTES y nombres como ANTONIETA.
#: * separador -- punto, guion, espacios o NADA entre las dos partes.
#: * ``[ \t]`` en vez de ``\s`` -- para NO cruzar saltos de línea, que uniría un
#:   ``ANT`` al final de un renglón con un ``SOL`` al principio del siguiente.
#: * ``LENTES?[ \t]+DE[ \t]+`` -- acá el ``DE`` es OBLIGATORIO. ``LENTE SOL``
#:   sin ``DE`` no existe en el archivo (0 casos) y admitirlo sólo abriría
#:   la puerta a falsos positivos.
#: * ``SOL\b`` -- límite de palabra: descarta SOLEDAD, SOLO, SOLANGE.
MARCADOR_ANTEOJO_SOL: Final[re.Pattern[str]] = re.compile(
    r"(?:\bANT(?:EOJOS?)?(?:[ \t]*[.\-][ \t]*|[ \t]+)?(?:DE[ \t]+)?"
    r"|\bLENTES?[ \t]+DE[ \t]+)SOL\b",
    re.IGNORECASE,
)

#: Contextos donde el marcador aparece pero NO es una venta de anteojos de sol.
#:
#: Son los casos que la óptica pidió excluir expresamente:
#:   * ``ANT SOL RECETADO``  -- anteojo de sol CON graduación. No cuenta como
#:     venta de anteojos de sol: es una receta común cuya observación aclara
#:     que el cristal es solar.
#:   * ``ANTEOJO DE SOL EN USO`` -- uno que el paciente ya tiene, no una compra.
#:   * ``SE EXTRAVIO ANT SOL``  -- un extravío, no una compra.
#:
#: Ante la duda el bloque queda en revisión, que es el lado seguro del error.
EXCLUSION_ANTEOJO_SOL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:RECETAD[OA]S?|GRADUAD[OA]S?|CON[ \t]+GRAD|EN[ \t]+USO"
    r"|EXTRAVI[OÓ]|SE[ \t]+EXTRAVI|PERDI[OÓ])\b",
    re.IGNORECASE,
)

#: Etiqueta ``<Presupuesto>``: la visita es una cotización, no una venta.
#:
#: 1.255 apariciones, siempre al inicio de la línea y siempre en la misma línea
#: que un ``<< FECHA >>``.
PRESUPUESTO: Final[re.Pattern[str]] = re.compile(r"<\s*Presupuesto\s*>", re.IGNORECASE)

#: Fecha suelta dd/mm/aaaa sin marcador, usada por el dialecto manuscrito.
#:
#: Aparece 153 veces, típicamente al final de la línea del doctor:
#: ``DRA VISTAMAR ELENA 14/05/2021``. Es la única fecha disponible en los
#: registros que no tienen ningún ``<< FECHA >>``.
FECHA_SUELTA: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4})\b"
)


# ---------------------------------------------------------------------------
# 3. SECCIONES DENTRO DE UNA VISITA
# ---------------------------------------------------------------------------

#: Encabezados de sección conocidos y a qué sección lógica corresponden.
#:
#: El orden de este diccionario importa: se prueba de arriba abajo y gana el
#: primero que matchea. ``BI/MULTIFOCAL`` va antes que nada porque contiene la
#: barra y no debe confundirse. Las variantes con espacio antes de los dos
#: puntos (``LEJOS :``) existen en el archivo de la óptica.
SECCIONES: Final[dict[str, re.Pattern[str]]] = {
    "LEJOS": re.compile(r"^\s*LEJOS\s*:?\s*$", re.IGNORECASE),
    "CERCA": re.compile(r"^\s*CERCA\s*:?\s*$", re.IGNORECASE),
    "INTERMEDIA": re.compile(r"^\s*INTERMEDIA\s*:?\s*$", re.IGNORECASE),
    "BI_MULTIFOCAL": re.compile(r"^\s*BI\s*/\s*MULTIFOCAL\s*:?\s*$", re.IGNORECASE),
    "LENTES_CONTACTO": re.compile(
        r"^\s*(?:LENTES DE CONTACTO|LTES\.?\s*CTO\.?)\s*:?\s*$", re.IGNORECASE
    ),
    "RP_MEDICO": re.compile(r"^\s*RP\.?\s*MEDICO\s*:?\s*$", re.IGNORECASE),
    "RP_CONTACTOLOGO": re.compile(
        r"^\s*(?:RP\.?\s*)?CONTACTOLOGO\s*:?\s*$", re.IGNORECASE
    ),
}

#: Encabezado de sección de LENTES DE CONTACTO con texto pegado después de los
#: dos puntos.
#:
#: Ejemplo: ``RP. MEDICO:NO ES DE ESTE CLIENTE !!!!!``
#:
#: Sin este patrón la línea no se reconoce como encabezado, ``seccion_actual``
#: queda en ``None`` y las líneas de ojo que siguen caen al destino por defecto
#: (LEJOS), escribiendo medidas de lentes de contacto en columnas de anteojos.
#: Es la causa raíz de la contaminación entre productos.
#:
#: El texto que viene después de los dos puntos NO se descarta: se manda a
#: observaciones, porque suele ser una nota del empleado.
#: También cubre los encabezados de contacto SIN los dos puntos, propios del
#: dialecto manuscrito. Formas observadas y su frecuencia:
#:
#:     RP. MEDICO:ES / RP. MEDICO: C / RP. CONTACTOLOGO: U   5   (ruido pegado)
#:     LENTES DE CONTACTO   sin dos puntos                  29
#:     LTES.CTO.            sin dos puntos                  15
#:     RX.: CONTACTOLOGO                                     1
#:     R.P. MEDICO OD ...                                    1
#:     R.P. CONTACTOLOGO                                     1
#:
#: Lo que viene después del encabezado NO se descarta: se devuelve en ``resto``
#: y el extractor lo sigue procesando. Si son medidas (``LENTES DE CONTACTO OD
#: -2.75 -1.25 A 170``) se leen como línea de ojo; si es una nota del empleado
#: (``RP. MEDICO:NO ES DE ESTE CLIENTE``) va a observaciones.
SECCION_CONTACTO_CON_RUIDO: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*"
    r"(?:R[ \t]*X[ \t]*[.:]{0,2}[ \t]*)?"
    r"(?P<seccion>"
    r"R[ \t]*\.?[ \t]*P[ \t]*\.?[ \t]*(?:MEDICO|CONTACTOLOGO)"
    r"|CONTACTOLOGO"
    r"|LENTES[ \t]+DE[ \t]+CONTACTO"
    r"|LTES?[ \t]*\.?[ \t]*CTO[ \t]*\.?"
    r")"
    r"[ \t]*:?[ \t]*(?P<resto>[^\r\n]*)$",
    re.IGNORECASE,
)

#: Prescriptor que NO es ni el médico ni el contactólogo.
#:
#: Hallado al implementar: ``R.P. EN USO`` (1 caso). Es la receta
#: que el paciente ya está usando, no una indicación nueva.
#:
#: NO se fuerza a ninguno de los dos prescriptores: sus medidas van al destino
#: sin etiquetar, para no atribuirle al médico algo que no firmó.
PRESCRIPTOR_SIN_IDENTIFICAR: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*R[ \t]*\.?[ \t]*P[ \t]*\.?[ \t]+EN[ \t]+USO\b",
    re.IGNORECASE,
)

#: Cualquier línea que parezca un encabezado de sección desconocido.
#:
#: Sirve para detectar secciones que todavía no modelamos y mandarlas a
#: ``revisar_manual.csv`` con motivo ``seccion_desconocida``, en vez de
#: descartarlas en silencio.
SECCION_CANDIDATA: Final[re.Pattern[str]] = re.compile(r"^\s*[A-ZÁÉÍÓÚÑ][^a-z\r\n]{1,38}:\s*$")

#: Encabezado de sección con contenido en la MISMA línea.
#:
#: Propio del dialecto manuscrito: ``LEJOS: O.D: +1.25 -0.50 EN 95``.
SECCION_CON_CONTENIDO: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<seccion>LEJOS|CERCA|INTERMEDIA|R\.?P\.?|LTES\.?\s*CTO\.?)\s*:\s*"
    r"(?P<resto>\S[^\r\n]*)$",
    re.IGNORECASE,
)

#: Lo que sigue a un ``R.P.:`` cuando la receta es de ANTEOJOS y no de lentes
#: de contacto: ``R.P.: LEJOS OD ESF. -1.25``, ``RP : CERCA AO +3.50``.
#: 5 visitas en el archivo.
RP_DE_ANTEOJOS: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:LEJOS|CERCA|INTERMEDIA)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 4. LÍNEAS DE OJO
# ---------------------------------------------------------------------------

#: Etiqueta de ojo al principio de la línea.
#:
#: Cubre las 13 variantes observadas: ``O.D.`` (79.958), ``O.I.`` (79.850),
#: ``OD``/``OI`` sin puntos (1.305, dialecto manuscrito), ``AO``/``A.O.``
#: (ambos ojos, 150) y las versiones en minúscula.
#: El grupo ``ojo`` se normaliza después en ``normalizador.normalizar_ojo``.
ETIQUETA_OJO: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<ojo>O\s*\.?\s*D|O\s*\.?\s*I|A\s*\.?\s*O)\s*\.?\s*:?\s*(?P<resto>[^\r\n]*)$",
    re.IGNORECASE,
)

#: Esfera con etiqueta explícita: ``Esf. -8.00`` / ``ESF. - 1.75`` / ``ESF +2``.
#:
#: El ``\s*`` entre signo y número es obligatorio: el dialecto manuscrito
#: escribe ``ESF. - 1.75`` con espacio en el medio.
#:
#: También admite el valor escrito sin el cero: ``Esf. +.75`` es ``+0.75``.
#: Son 4 casos en el archivo. Sólo vale con la etiqueta delante.
ESFERA: Final[re.Pattern[str]] = re.compile(
    r"\bE\s*S\s*F\s*\.?\s*:?\s*(?P<valor>[+-]?\s*(?:\d+(?:[.,]\d+)?|[.,]\d+))",
    re.IGNORECASE,
)

#: Cilindro con etiqueta explícita: ``Cil. +1.50`` / ``CIL. - 0.25``.
#:
#: También admite el valor escrito sin el cero: ``Cil. -.50`` es ``-0.50``.
#: Son 7 casos en el archivo. Sólo vale con la etiqueta delante.
CILINDRO: Final[re.Pattern[str]] = re.compile(
    r"\bC\s*I\s*L\s*\.?\s*:?\s*(?P<valor>[+-]?\s*(?:\d+(?:[.,]\d+)?|[.,]\d+))",
    re.IGNORECASE,
)

#: EJE en grados. Es el patrón menos evidente del archivo.
#:
#: Cuatro introductores observados, en este orden de frecuencia:
#:   ``En 75``  → 86.008 casos (formato Moebius)
#:   ``A 155``  →    608 casos (dialecto manuscrito)
#:   ``EJE 90`` →      8 casos
#:   ``X 90``   →      2 casos
#: El valor se valida después contra el rango 0-180 en el extractor.
EJE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:EN|A|EJE|X)\s+(?P<valor>\d{1,3})\b", re.IGNORECASE
)

#: Potencia sin etiqueta, como número desnudo al principio del resto de la línea.
#:
#: Se usa en LENTES DE CONTACTO (``O.D. -11.50``) y en el dialecto manuscrito
#: (``OD +1.75   ESF   CIL   EJE``). Anclado al inicio para no capturar por
#: accidente un número que venga más adelante en la línea.
NUMERO_DESNUDO_INICIAL: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<valor>[+-]\s*\d+(?:[.,]\d+)?|\d+[.,]\d+)"
)

#: Segundo número desnudo: es el cilindro cuando el primero fue la esfera.
#:
#: Caso ``LEJOS: O.D: +1.25 -0.50 EN 95`` → esfera +1.25, cilindro -0.50.
NUMERO_DESNUDO_SEGUNDO: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<primero>[+-]\s*\d+(?:[.,]\d+)?|\d+[.,]\d+)"
    r"\s+(?P<segundo>[+-]\s*\d+(?:[.,]\d+)?)"
)

#: Adición para cerca: ``ADD +2.5`` / ``ADD +3.00`` / ``AD: +2.50``.
#:
#: Los decimales son inconsistentes en el origen (``+2.5`` y ``+2.50``
#: conviven); el normalizador los lleva a dos decimales.
ADICION: Final[re.Pattern[str]] = re.compile(
    r"\bA\s*D\s*D?\s*\.?\s*:?\s*(?P<valor>[+-]?\s*\d+(?:[.,]\d+)?)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 5. DISTANCIA INTERPUPILAR Y ALTURA
# ---------------------------------------------------------------------------

#: D.I. calificada como Lejos o Cerca: ``D.I. Lejos 66.00`` / ``D.I. Cerca 58``.
#:
#: 12.939 casos de Lejos y 4.795 de Cerca. Se prueba ANTES que la genérica.
DI_CALIFICADA: Final[re.Pattern[str]] = re.compile(
    r"\bD\s*\.?\s*I\s*\.?\s*(?P<calificador>LEJOS|CERCA)\s*:?\s*(?P<valor>\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)

#: D.I. genérica sin calificador: ``D.I. 58``.
#:
#: 36.460 casos. El ``(?!\s*(?:LEJOS|CERCA))`` evita que capture el ``66`` de
#: ``D.I. Lejos 66`` cuando la calificada ya lo tomó.
DI_GENERICA: Final[re.Pattern[str]] = re.compile(
    r"\bD\s*\.?\s*I\s*\.?\s*(?!\s*(?:LEJOS|CERCA))\s*:?\s*(?P<valor>\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)

#: Altura de montaje del cristal: ``Altura 14.00``. 5.756 casos.
#: Viene pegada a la línea de modelo del bloque BI/MULTIFOCAL.
ALTURA: Final[re.Pattern[str]] = re.compile(
    r"\bALTURA\s*:?\s*(?P<valor>\d+(?:[.,]\d+)?)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 6. MODELO DEL ANTEOJO
# ---------------------------------------------------------------------------

#: La palabra ``Color`` introduce el MODELO/MATERIAL, no un color literal.
#:
#: 43.712 + 750 (mayúsculas) casos. Ejemplos con esa forma:
#:   ``Color AR VERDE FLEX``
#:   ``Color FOTOCROMATICO ORGANICO``
#: Ojo: también trae información comercial que NO interpretamos, sólo
#: guardamos: ``Color OBRA SOCIAL STK$40 4.00/2.00 ORGANICO`` mezcla obra
#: social, precio y material en el mismo campo.
COLOR_MODELO: Final[re.Pattern[str]] = re.compile(
    r"\bCOLOR\s+(?P<modelo>[^\r\n]+)$", re.IGNORECASE
)

#: Prefijo de código interno del modelo: ``Color 1_BLANCO``, ``Color 2_AR LITE``.
#:
#: Sólo existen los códigos 1 (16.967 casos) y 2 (7.736). Se separan en
#: ``codigo_modelo`` y ``modelo_anteojo``.
CODIGO_MODELO: Final[re.Pattern[str]] = re.compile(
    r"^(?P<codigo>\d+)_\s*(?P<resto>[^\r\n]*)$"
)

#: Tratamientos aplicados al cristal: ``Tratamientos: TINTE``.
#:
#: 4.286 casos. Valores repetidos como ``TINTE, TINTE`` significan un
#: tratamiento por ojo; se conservan tal cual porque esa repetición es
#: información, no ruido.
TRATAMIENTOS: Final[re.Pattern[str]] = re.compile(
    r"\bTRATAMIENTOS\s*:\s*(?P<valor>[^\r\n]*)$", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 7. LENTES DE CONTACTO
# ---------------------------------------------------------------------------

#: Curva base: ``C.B. 8.60`` / ``CB 9.20``. 106 casos.
CURVA_BASE: Final[re.Pattern[str]] = re.compile(
    r"\bC\s*\.?\s*B\s*\.?\s*(?P<valor>\d+(?:[.,]\d+)?)", re.IGNORECASE
)

#: Diámetro: se escribe con el símbolo Ø (0xD8 en cp1252) o como ``DIA. 14.2``.
#: 91 + 36 casos.
DIAMETRO: Final[re.Pattern[str]] = re.compile(
    r"(?:Ø|\bDIA\s*\.?)\s*(?P<valor>\d+(?:[.,]\d+)?)", re.IGNORECASE
)

#: Diámetro de una lente de contacto, también escrito ``DIAM 14.2`` o
#: ``DIAMETRO 14.2``.
#:
#: Se usa SÓLO dentro de una visita de lentes de contacto. En anteojos
#: ``DIAM 65`` es el diámetro del cristal, que es otra cosa: aplicar este
#: patrón ahí cambiaba 74 recetas de anteojos, y los anteojos no se tocan.
#:
#: ``DIA`` a secas sólo vale con punto (``DIA.14.2``). Sin punto es la palabra
#: "día": ``ENTREGADO EL DIA 23/06/2022`` se leía como un diámetro de 23, y eso
#: pasaba en 9 visitas que ni siquiera eran de lentes de contacto. Por lo mismo
#: el valor no puede ir seguido de una barra, que lo delata como fecha.
DIAMETRO_LC: Final[re.Pattern[str]] = re.compile(
    r"(?:Ø|\bDIAM(?:ETRO)?\s*\.?|\bDIA\s*\.)\s*(?P<valor>\d+(?:[.,]\d+)?)(?!\s*/)",
    re.IGNORECASE,
)

#: Texto de un renglón de lentes de contacto que lleva números pero NO es una
#: medida: lote, vencimiento, fechas y agudeza visual.
#:
#:     LOT 12345678     VTO 08/2019     2019/08     23/06/2022     A.V. 20/30
#:
#: La fecha completa con el año adelante (``2029/08/30``, ``2029-08-30``) vale
#: igual que el vencimiento sin día, si es una fecha posible: año 19xx o 20xx,
#: mes 1 a 12 y día 1 a 31. Va antes que la forma sin día para que el día no
#: quede afuera y se cuente como un número suelto.
#:
#: Se descuentan antes de contar los números sin etiqueta de un renglón, para
#: que un lote o un vencimiento no abran un caso de revisión por "medidas".
NO_ES_MEDIDA_LC: Final[re.Pattern[str]] = re.compile(
    r"\bLOTE?\s*\.?\s*:?\s*[\w/-]*\d[\w/-]*"
    r"|\b(?:VTO|VENC\w*|EXP)\s*\.?\s*:?\s*\d[\d/.-]*"
    r"|\b\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b"
    r"|\b(?:19|20)\d{2}\s*[-/]\s*(?:0?[1-9]|1[0-2])\s*[-/]\s*(?:0?[1-9]|[12]\d|3[01])\b"
    r"|\b(?:19|20)\d{2}\s*[-/]\s*(?:0?[1-9]|1[0-2])\b"
    r"|\b\d{1,2}\s*/\s*\d{4}\b"
    r"|\bA\s*\.?\s*V\s*\.?\s*:?\s*[+-]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?",
    re.IGNORECASE,
)

#: Nombres de producto que llevan un número: el número es parte del nombre y
#: no una medida, así que no abre un caso ``medidas_lc_sin_etiqueta``.
#:
#: La lista es CERRADA y cada nombre va con su número exacto. Salió de los
#: valores más frecuentes de ``lc_marca``: BIOMEDICS 55 (más de 550 veces, con
#: sus erratas), SOFLENS 59 (86), O2 OPTIX (85), TOP LENS 55 (49), WAICON 2
#: (41), ACUVUE 2 (36) y OPTIMA 38 (17).
#:
#: Nada dudoso entra acá: ``NEW TORIC 14`` puede ser un diámetro y sigue
#: yendo a revisión.
PRODUCTO_CON_NUMERO: Final[re.Pattern[str]] = re.compile(
    r"\bBIOME?D?I?C[IS]{1,2}\s*55\b"
    r"|\bSOFLENS\s*59\b"
    r"|\bO\s*2\s*OPTIX\b"
    r"|\bTOP\s*LENS\s*55\b"
    r"|\bWAICON\s*2\b"
    r"|\bACUVUE\s*2\b"
    r"|\bOPTIMA\s*38\b",
    re.IGNORECASE,
)

#: Un número seguido de un nivel de adición: ``+2.75/HIGH``, ``1.75 / MED``,
#: ``+2.50 ADD HIGH``. Es la única forma en que un número SIN signo y sin
#: etiqueta se acepta como potencia.
NUMERO_CON_NIVEL: Final[re.Pattern[str]] = re.compile(
    r"[+-]?\s*\d+(?:[.,]\d+)?\s*/?\s*(?:ADD\s*\.?\s*)?(?:HIGH|HI|MED|LOW|MID)"
    r"(?![A-Za-zÁÉÍÓÚÑáéíóúñ])",
    re.IGNORECASE,
)

#: Marca de lentes de contacto nombrada en texto libre.
#:
#: Sirve para clasificar como lentes de contacto una visita que no tiene
#: ninguna sección ni medida, sólo un comentario del tipo
#: ``1 PAR ESF.-5.50 <marca>``. Decisión del equipo: 40 visitas.
MARCA_LC_EN_TEXTO: Final[re.Pattern[str]] = re.compile(
    r"\bSOFLENS|AIR\s*OPTIX|\bACUVUE|\bBIOMEDICS|\bBIOFINITY|\bWAICON|\bFRESHLOOK"
    r"|\bO2\s*OPTIX|\bTORIC",
    re.IGNORECASE,
)

#: Líquidos y soluciones para lentes de contacto. Una visita que sólo los
#: nombra es una venta de líquido: queda en observaciones y no se reclasifica.
LIQUIDO_LC: Final[re.Pattern[str]] = re.compile(
    r"\bRENU\b|OPTI.?FREE|\bLIQUIDO|\bSOLUCION", re.IGNORECASE
)

#: "Lentes de contacto" nombrado en un comentario, en cualquiera de sus
#: abreviaturas. Solo NO alcanza para reclasificar: suele ser un anteojo "para
#: usar arriba del lente de contacto".
MENCION_LC: Final[re.Pattern[str]] = re.compile(
    r"LENTES?\s+DE\s+CONTACTO|LTES?\s*\.?\s*(?:DE\s+)?CTO|LTE\.?\s*CTO"
    r"|\bL\.?\s?C\.(?!\w)",
    re.IGNORECASE,
)

#: Cajas o descartables nombrados en un comentario, sin marca.
#:
#: Decisión del equipo: una visita sin tipo que los nombra se clasifica como
#: lentes de contacto, pero con un caso ``lc_clasificada_por_caja`` en
#: ``revisar_manual.csv``, porque la señal es más débil que una marca.
CAJA_O_DESCARTABLE: Final[re.Pattern[str]] = re.compile(
    r"DESCARTABLE|\bCAJAS?\b.{0,25}(?:ESF|[+-]\d)", re.IGNORECASE
)

#: Marca comercial de la lente de contacto: ``Marca L.C. ACUVUE OASYS``.
#: 4.306 casos. Es el dato que la empleada necesita para reponer la lente.
MARCA_LC: Final[re.Pattern[str]] = re.compile(
    r"\bMARCA\s+L\s*\.?\s*C\s*\.?\s*(?P<valor>[^\r\n]+)$", re.IGNORECASE
)

#: Tipo de lente de contacto: ``Tipo L.C. descartable`` / ``CONVENCIONALES``.
#: 1.233 casos.
TIPO_LC: Final[re.Pattern[str]] = re.compile(
    r"\bTIPO\s+L\s*\.?\s*C\s*\.?\s*(?P<valor>[^\r\n]+)$", re.IGNORECASE
)

#: Nivel de adición de una lente de contacto multifocal.
#:
#: Aparece en 416 visitas de lentes de contacto: ``HIGH`` (532 veces), ``MED``
#: (141), ``high`` (53), ``LOW`` (45), ``med`` (6), ``MID`` (2), ``low`` (2), y
#: la abreviatura ``HI`` (5). No se sabe con certeza qué significa cada uno, así
#: que NO se interpreta ni se unifica: se guarda tal como está escrito,
#: respetando mayúsculas y minúsculas.
#:
#: SÓLO se busca dentro de visitas de lentes de contacto. En anteojos ``MED``
#: quiere decir otra cosa: ``RGO.MED +5-7+1`` (rango medio) y ``MED.TABLET`` o
#: ``TOMAR MED.`` (medidas), en 77 visitas.
#:
#: Los límites impiden capturar el nivel dentro de otra palabra (``MEDICO``,
#: ``MEDIDAS``, ``LOWER``), pero admiten un dígito pegado adelante, porque en el
#: archivo existe el tipeo ``7HIGH``.
NIVEL_ADICION: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ])(?:HIGH|HI|MED|LOW|MID)(?![A-Za-zÁÉÍÓÚÑáéíóúñ])",
    re.IGNORECASE,
)

#: Renglón del LENTE entregado, dentro del tramo que va del encabezado
#: ``LENTES DE CONTACTO`` hasta ``Tipo L.C.`` o ``Marca L.C.``.
#:
#: Se aplica al texto que sigue a la etiqueta de ojo. Formas que existen:
#:
#:     +2.75/HIGH      +1.75 / HIGH      ESF. +3.25/ HIGH     +1.25/med
#:     +2.50 ADD HIGH  +1.75 /add HIGH   (con ADD en el medio)
#:     HIGH            ADD HIGH          ADD. HIGH            (sin número)
#:     -12.50          +1.50             (potencia sola, sin nivel)
#:
#: * ``potencia`` -- la potencia del lente que se entregó. NO es la esfera de la
#:   receta: coinciden en 526 apariciones y difieren en 222.
#: * ``nivel``    -- el nivel con el texto que lo rodea, sin el número.
#:
#: Los dos grupos son opcionales. El extractor acepta una potencia SIN signo
#: sólo si viene seguida de un nivel: un número sin signo y sin nivel puede ser
#: una curva base (``O.D. 8.40``), y no se adivina.
RENGLON_DE_LENTE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:E\s*S\s*F\s*\.?\s*:?\s*)?"
    r"(?P<potencia>[+-]\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)?"
    r"(?P<nivel>\s*/?\s*(?:ADD\s*\.?\s*)?(?:HIGH|HI|MED|LOW|MID))?"
    r"(?![A-Za-zÁÉÍÓÚÑáéíóúñ0-9.,])",
    re.IGNORECASE,
)

#: Nivel escrito en el lugar del cilindro: ``Cil. HIGH``. 1 visita conocida.
#:
#: No se adivina qué quiso decir el empleado: el cilindro queda nulo, el renglón
#: va a observaciones y se abre un caso en ``revisar_manual.csv``.
NIVEL_EN_CILINDRO: Final[re.Pattern[str]] = re.compile(
    r"\bC\s*I\s*L\s*\.?\s*:?\s*(?:HIGH|HI|MED|LOW|MID)(?![A-Za-z])", re.IGNORECASE
)

#: Dónde termina la marca cuando en el mismo renglón sigue otro texto.
#:
#:     Marca L.C. AIR OPTIX AO +1.50/ med           -> marca "AIR OPTIX"
#:     Marca L.C. BIOMEDICS 1 PAR DE PRUEBA !       -> marca "BIOMEDICS"
#:
#: La marca se corta donde empieza una cantidad con unidad, una etiqueta de ojo
#: seguida de una medida, o un número con signo. Lo que queda después va a
#: observaciones, sin repartirse en columnas. Un número suelto NO corta: forma
#: parte de marcas como ``BIOMEDICS 55``, ``WAICON 2`` o ``ACUVUE 2``.
CORTE_DE_MARCA: Final[re.Pattern[str]] = re.compile(
    r"\s(?:\d+\s*(?:CAJAS?|CJAS?|PAR(?:ES)?)\b"
    r"|(?:A\s*\.?\s*O|O\s*\.?\s*D|O\s*\.?\s*I)\s*\.?\s*:?\s*"
    r"(?:ESF|ADD|[+-]?\s*\d|/|HIGH|HI\b|MED|LOW|MID)"
    r"|[+-]\s?\d)",
    re.IGNORECASE,
)

#: Cualquier número, con o sin signo. Sirve para decidir si en un renglón de
#: lentes de contacto queda texto además de las medidas.
NUMERO_SUELTO: Final[re.Pattern[str]] = re.compile(r"[+-]?\s*\d+(?:[.,]\d+)?")

#: Cantidad entregada, con su unidad: ``1 CAJA``, ``2 PARES``, ``1 PAR``.
#:
#: Se guarda tal como está escrita. No se convierte a unidades: una caja no
#: trae siempre la misma cantidad de lentes.
CANTIDAD_LC: Final[re.Pattern[str]] = re.compile(
    r"(?<![\d.,/])\d+\s*(?:CAJAS?|CJAS?|PAR(?:ES)?)(?![A-Za-zÁÉÍÓÚÑáéíóúñ])",
    re.IGNORECASE,
)

#: Agudeza visual: ``A.V. 20/25``. 52 casos. Se guarda dentro de observaciones.
AGUDEZA_VISUAL: Final[re.Pattern[str]] = re.compile(
    r"\bA\s*\.?\s*V\s*\.?\s*(?P<valor>\d+\s*/\s*\d+)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 8. DOCTOR Y OBSERVACIONES
# ---------------------------------------------------------------------------

#: Línea de doctor del formato Moebius: ``Doctor: APELLIDO NOMBRE``.
#: 48.188 casos.
DOCTOR: Final[re.Pattern[str]] = re.compile(
    r"^\s*DOCTOR\s*:\s*(?P<valor>[^\r\n]*)$", re.IGNORECASE
)

#: Línea de doctor del dialecto manuscrito: ``DR.OCULARI  09/09/2016``,
#: ``DRA VISTAMAR ELENA 14/05/2021``. 99 casos.
#: La fecha que traiga al final se extrae aparte con ``FECHA_SUELTA``.
DOCTOR_MANUSCRITO: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<tratamiento>DRA?|DOCTORA?)\s*\.?\s*(?P<valor>[A-ZÁÉÍÓÚÑ][^\r\n]*)$",
    re.IGNORECASE,
)

#: Valores del campo Doctor que NO son un médico sino una nota del empleado.
#:
#: ~4.700 casos en total entre las tres grafías de "copia anterior en uso".
#: Se mueven a observaciones y el campo doctor queda nulo, para que el
#: recuento de derivaciones por médico de la óptica no salga envenenado.
DOCTOR_NO_ES_MEDICO: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:COPIA\s*(?:ANT|ANTERIOR)|ANT\s*\.?\s*USO|SIN\s*RECETA|S/RECETA|"
    r"NO\s*TRAE|PROPIA|IDEM)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 9. NORMALIZACIÓN
# ---------------------------------------------------------------------------

#: Espacios múltiples a colapsar en uno solo.
ESPACIOS_MULTIPLES: Final[re.Pattern[str]] = re.compile(r"\s+")

#: Caracteres a eliminar de la clave de deduplicación.
#:
#: Deja sólo letras, números y espacio. Elimina el apóstrofo de ``D´EJEMPLO``
#: (0xB4) y los signos sueltos (``¡``, ``!``, ``·``) que aparecen pegados a
#: apellidos por errores de tipeo.
NO_ALFANUMERICO: Final[re.Pattern[str]] = re.compile(r"[^A-Z0-9 ]")

#: Signo y número separados por espacios: ``- 1.75`` → ``-1.75``.
#: Propio del dialecto manuscrito.
SIGNO_SEPARADO: Final[re.Pattern[str]] = re.compile(r"^([+-])\s+(\d)")

#: Documento inválido: todo ceros, o menos de 6 dígitos.
#:
#: 28.107 documentos vienen en ``0`` y 11 tienen entre 2 y 5 dígitos, que es
#: imposible para un DNI argentino. Los tratamos como ausentes: un documento
#: falso que parece válido es peor que uno nulo declarado.
DOCUMENTO_INVALIDO: Final[re.Pattern[str]] = re.compile(r"^0*$|^\d{1,5}$")


# ---------------------------------------------------------------------------
# 10. RUIDO CONOCIDO
# ---------------------------------------------------------------------------

#: Líneas de plantilla vacía del dialecto manuscrito.
#:
#: ``OD    ESF           CIL      EJE`` es un formulario que quedó sin
#: completar. No aporta ningún valor y no debe generar una receta con datos.
PLANTILLA_VACIA: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:O\.?D\.?|O\.?I\.?|A\.?O\.?)?\s*"
    r"(?:ESF\.?\s*)?(?:CIL\.?\s*)?(?:EJE\s*)?\s*$",
    re.IGNORECASE,
)

#: Texto residual que queda tras extraer todos los campos y no significa nada.
RESIDUO_IGNORABLE: Final[re.Pattern[str]] = re.compile(
    r"^[\s\.\-_/|·´`¡!¿?,;:*+()\[\]0]*$"
)


#: Línea que fue a parar a observaciones pero HUELE a medida óptica.
#:
#: Sirve para el control de calidad: si una línea contiene una dioptría con
#: signo y dos decimales, o las palabras ESF/CIL/EJE/ADD, es casi seguro una
#: receta que el parser no supo leer y terminó guardada como texto libre.
#: No se pierde el dato (queda en ``observaciones``), pero se reporta como
#: ``valor_no_parseable`` para que sepamos qué regla falta en este archivo.
#:
#: Se excluyen a propósito los importes (``$1500``) y los números de orden
#: (``TR.N°5120``), que son comerciales y no ópticos.
SOSPECHA_MEDIDA: Final[re.Pattern[str]] = re.compile(
    # Dioptría con signo explícito y dos decimales: "-2.50", "+ 1.75".
    # El lookbehind evita los importes ($ 3.800) y los números de orden.
    r"(?<![$\w°º])[+-]\s?\d{1,2}[.,]\d{2}(?!\d)"
    # Palabras que sólo aparecen en un contexto de receta.
    r"|\b(?:ESF|CIL|EJE|ADD|DIOPT)\b",
    re.IGNORECASE,
)
