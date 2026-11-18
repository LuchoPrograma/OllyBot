"""
Herramientas de Olly: funciones que Gemini puede pedir que se ejecuten.

El módulo tiene cuatro partes:
  1. Datos de referencia y normalización.
  2. Funciones asíncronas que consultan el backend de Olear HUB y Mercado Pago.
  3. Declaraciones en JSON Schema (lo único que el modelo ve de cada función).
  4. Despachador único que ejecuta la función pedida y captura errores como datos.
"""

import logging
import os
import unicodedata

from dotenv import load_dotenv
import httpx

load_dotenv()

logger = logging.getLogger("olly")

# Tiempo máximo de espera de cada consulta HTTP, en segundos.
TIEMPO_ESPERA = 10

# ---------------------------------------------------------------------------
# 1. Datos de referencia y utilidades
# ---------------------------------------------------------------------------
VARIETALES = ["Arauco", "Arbequina", "Frantoio", "Coratina", "Blend"]
INTENSIDADES = ["suave", "media", "intensa"]
_ALIAS_INTENSIDAD = {
    "medio": "media",
    "intenso": "intensa",
}

MP_PREFERENCES_URL = "https://api.mercadopago.com/checkout/preferences"


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita tildes para comparar textos de forma tolerante."""
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower().strip()


def _olear_api_url() -> str:
    """Devuelve la URL base del backend de Olear HUB sin barra final."""
    return os.getenv("OLEAR_API_URL", "http://localhost:8000").rstrip("/")


# ---------------------------------------------------------------------------
# 2. Funciones
# ---------------------------------------------------------------------------
async def consultar_catalogo(
    varietal: str | None = None,
    intensidad: str | None = None,
    solo_con_stock: bool = True,
) -> dict:
    """Consulta el catálogo y existencias en el backend de Olear HUB."""
    parametros: dict[str, str] = {
        "solo_con_stock": "true" if solo_con_stock else "false",
    }

    if varietal:
        varietal_norm = _normalizar(varietal)
        coincidencias = [v for v in VARIETALES if _normalizar(v) == varietal_norm]
        if not coincidencias:
            return {
                "error": f"Varietal no disponible en Olear: {varietal}",
                "varietales_disponibles": VARIETALES,
            }
        parametros["varietal"] = coincidencias[0]

    if intensidad:
        intensidad_norm = _normalizar(intensidad)
        intensidad_norm = _ALIAS_INTENSIDAD.get(intensidad_norm, intensidad_norm)
        if intensidad_norm not in INTENSIDADES:
            return {
                "error": f"Intensidad desconocida: {intensidad}",
                "intensidades_disponibles": INTENSIDADES,
            }
        parametros["intensidad"] = intensidad_norm

    url = f"{_olear_api_url()}/api/catalogo"
    try:
        async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
            respuesta = await cliente_http.get(url, params=parametros)
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.ConnectError:
        return {"error": "No se pudo conectar con el catálogo de Olear HUB en este momento."}

    productos = datos.get("productos", [])
    if not productos:
        return {
            "total": 0,
            "productos": [],
            "aviso": "No se encontraron aceites que coincidan con esos filtros.",
        }
    return {"total": len(productos), "productos": productos}


async def generar_link_pago(producto_id: str, cantidad: int = 1) -> dict:
    """Genera una preferencia de pago en Mercado Pago Sandbox para un producto del catálogo."""
    try:
        cantidad_int = int(cantidad)
    except (TypeError, ValueError):
        return {"error": "La cantidad debe ser un número entero válido."}

    if cantidad_int < 1 or cantidad_int > 20:
        return {"error": "La cantidad por pedido debe estar entre 1 y 20 unidades."}

    producto_id = producto_id.strip()
    if not producto_id:
        return {"error": "Falta el identificador del producto (producto_id)."}

    # Paso 1: obtener precio y stock autoritativos desde Olear HUB (nunca confiar en montos del modelo).
    url_producto = f"{_olear_api_url()}/api/productos/{producto_id}"
    try:
        async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
            resp_prod = await cliente_http.get(url_producto)
            if resp_prod.status_code == 404:
                return {
                    "error": f"Producto no encontrado: {producto_id}",
                    "sugerencia": "Usá consultar_catalogo primero para obtener un id válido.",
                }
            resp_prod.raise_for_status()
            producto = resp_prod.json()
    except httpx.ConnectError:
        return {"error": "No se pudo validar el producto contra el backend de Olear HUB."}

    stock = int(producto.get("stock_unidades", 0))
    if stock <= 0:
        return {"error": f"Actualmente no queda stock disponible de {producto['nombre']}."}
    if cantidad_int > stock:
        return {
            "error": f"Stock insuficiente de {producto['nombre']}: hay {stock} unidades disponibles.",
            "stock_disponible": stock,
        }

    # Paso 2: crear preferencia en Mercado Pago Sandbox.
    access_token = os.getenv("MP_ACCESS_TOKEN", "").strip()
    if not access_token:
        return {"error": "Falta configurar MP_ACCESS_TOKEN en las variables de entorno."}

    precio_unitario = float(producto["precio_ars"])
    titulo = f"{producto['nombre']} ({producto['presentacion_ml']} ml)"
    payload = {
        "items": [
            {
                "id": producto["id"],
                "title": titulo,
                "quantity": cantidad_int,
                "currency_id": "ARS",
                "unit_price": precio_unitario,
            }
        ],
        "external_reference": f"olly-{producto['id']}-x{cantidad_int}",
        "statement_descriptor": "OLEAR HUB",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
        resp_mp = await cliente_http.post(MP_PREFERENCES_URL, json=payload, headers=headers)
        if resp_mp.status_code in (401, 403):
            return {"error": "Credenciales de Mercado Pago inválidas o sin permisos."}
        resp_mp.raise_for_status()
        preferencia = resp_mp.json()

    link_pago = preferencia.get("sandbox_init_point") or preferencia.get("init_point")
    if not link_pago:
        return {"error": "Mercado Pago no devolvió un enlace de pago válido."}

    return {
        "preferencia_id": preferencia.get("id"),
        "producto": titulo,
        "cantidad": cantidad_int,
        "precio_unitario_ars": int(precio_unitario),
        "total_ars": int(precio_unitario * cantidad_int),
        "link_pago": link_pago,
        "entorno": "sandbox",
    }


async def consultar_lote(codigo_lote: str) -> dict:
    """Recupera información de trazabilidad de una botella a partir de su código de lote."""
    codigo = codigo_lote.strip().upper()
    if not codigo:
        return {"error": "Indicá un código de lote para consultar."}

    url = f"{_olear_api_url()}/api/lotes/{codigo}"
    try:
        async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente_http:
            respuesta = await cliente_http.get(url)
            if respuesta.status_code == 404:
                return {"error": f"No se encontró información para el lote {codigo}."}
            respuesta.raise_for_status()
            return respuesta.json()
    except httpx.ConnectError:
        return {"error": "No se pudo conectar con el backend de Olear HUB para consultar el lote."}


# ---------------------------------------------------------------------------
# 3. Declaraciones para el modelo
# ---------------------------------------------------------------------------
DECLARACIONES = [
    {
        "type": "function",
        "name": "consultar_catalogo",
        "description": (
            "Obtiene la lista real de aceites de Olear HUB con su id, nombre comercial, "
            "varietal, presentación en ml, precio en ARS, stock, intensidad, notas de cata "
            "y maridajes. Usala SIEMPRE al responder sobre maridajes, qué aceite conviene "
            "para una comida, precios, catálogo o stock. Si el usuario no indicó varietal "
            "ni intensidad, llamala igual sin filtros para ver todas las opciones con stock."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "varietal": {
                    "type": "string",
                    "enum": VARIETALES,
                    "description": "Filtrá por varietal solo si el usuario pidió uno específico.",
                },
                "intensidad": {
                    "type": "string",
                    "enum": INTENSIDADES,
                    "description": "Filtrá por intensidad (suave, media o intensa) si el usuario indicó preferencia.",
                },
                "solo_con_stock": {
                    "type": "boolean",
                    "description": "Por defecto true para mostrar solo aceites disponibles. Usá false si preguntan por todo el catálogo.",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "generar_link_pago",
        "description": (
            "Genera un enlace de pago de Mercado Pago (Checkout Pro Sandbox) para un aceite del "
            "catálogo de Olear HUB. Usala únicamente cuando el usuario confirme qué producto quiere "
            "comprar y la cantidad, usando el campo 'id' devuelto por consultar_catalogo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "producto_id": {
                    "type": "string",
                    "description": "Identificador exacto del producto en el catálogo (por ejemplo: 'arauco-reserva-500').",
                },
                "cantidad": {
                    "type": "integer",
                    "description": "Cantidad de botellas a comprar (entre 1 y 20). Por defecto 1.",
                },
            },
            "required": ["producto_id"],
        },
    },
    {
        "type": "function",
        "name": "consultar_lote",
        "description": (
            "Consulta la trazabilidad de una botella de Olear usando su código de lote impreso "
            "(finca de origen, fechas de cosecha y molienda, método de extracción, acidez y notas de cata). "
            "Usala cuando el usuario ingrese un código de lote (por ejemplo: LOT-2026-AR01)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "codigo_lote": {
                    "type": "string",
                    "description": "Código del lote tal como lo escribió el usuario.",
                },
            },
            "required": ["codigo_lote"],
        },
    },
]

# ---------------------------------------------------------------------------
# 4. Despachador
# ---------------------------------------------------------------------------
FUNCIONES = {
    "consultar_catalogo": consultar_catalogo,
    "generar_link_pago": generar_link_pago,
    "consultar_lote": consultar_lote,
}


async def ejecutar_funcion(nombre: str, argumentos: dict | None = None) -> dict:
    """Ejecuta la función pedida por el modelo y devuelve siempre un diccionario."""
    argumentos = argumentos or {}
    logger.info("El modelo pidió %s(%s)", nombre, argumentos)
    funcion = FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"Función desconocida: {nombre}"}
    try:
        return await funcion(**argumentos)
    except Exception as error:
        logger.exception("Falló la herramienta %s", nombre)
        return {"error": f"No se pudo completar la operación: {type(error).__name__}"}
