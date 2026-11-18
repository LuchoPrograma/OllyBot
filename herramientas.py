import logging
import unicodedata
import httpx

logger = logging.getLogger("malbi")

# Tiempo máximo de espera para llamadas HTTP externas
TIEMPO_ESPERA = 10

# Catálogo simulado de Olear HUB para las funciones propias
CATALOGO_OLEAR = {
    "Arauco": {
        "varietal": "Arauco Reserva",
        "perfil": "Intenso, amargo y con notas picantes",
        "maridaje": "Carnes rojas, guisos, pastas con salsas robustas y quesos estacionados",
        "precio_500ml": 12500,
        "stock": True
    },
    "Frantoio": {
        "varietal": "Frantoio",
        "perfil": "Frutado medio, notas herbáceas y toque almendrado",
        "maridaje": "Pescados grasos, verduras al horno, bruschettas y pastas sin TACC",
        "precio_500ml": 11800,
        "stock": True
    },
    "Coratina": {
        "varietal": "Coratina",
        "perfil": "Muy robusto, alto contenido de polifenoles, picor marcado",
        "maridaje": "Legumbres, sopas de verduras, carnes a la parrilla y pizzas",
        "precio_500ml": 13000,
        "stock": True
    },
    "Blend": {
        "varietal": "Blend Robusto Olear",
        "perfil": "Equilibrado, complejo, con entrada frutada y final persistente",
        "maridaje": "Todo tipo de picadas, embutidos, ensaladas complejas y cocina italiana",
        "precio_500ml": 11500,
        "stock": True
    }
}

def _normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita tildes."""
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower().strip()

# 1. Funciones Propias de Olear HUB
async def recomendar_aceite_catalogo(plato_o_preferencia: str) -> dict:
    """Busca en el catálogo de Olear el varietal ideal según el plato o preferencia del cliente."""
    termino = _normalizar(plato_o_preferencia)
    
    # Búsqueda sencilla basada en palabras clave dentro del catálogo
    resultados = []
    for clave, datos in CATALOGO_OLEAR.items():
        if termino in _normalizar(datos["maridaje"]) or termino in _normalizar(datos["perfil"]) or termino in _normalizar(clave):
            resultados.append(datos)
            
    if not resultados:
        # Si no hay coincidencia exacta, devolvemos todo el catálogo resumido para que el modelo elija
        return {
            "mensaje": f"No encontré un maridaje exacto para '{plato_o_preferencia}', pero aquí tenés nuestros principales varietales disponibles:",
            "catalogo": list(CATALOGO_OLEAR.values())
        }
    return {"recomendaciones": resultados}

async def consultar_precio_stock(varietal: str) -> dict:
    """Consulta el precio y disponibilidad de stock de un varietal específico."""
    clave_buscada = _normalizar(varietal)
    for clave, datos in CATALOGO_OLEAR.items():
        if clave_buscada in _normalizar(clave) or clave_buscada in _normalizar(datos["varietal"]):
            return datos
            
    return {"error": f"Varietal desconocido: {varietal}", "varietales_disponibles": list(CATALOGO_OLEAR.keys())}

# 2. Declaraciones para el Modelo (JSON Schema)
DECLARACIONES = [
    {
        "type": "function",
        "name": "recomendar_aceite_catalogo",
        "description": (
            "Busca en el catálogo de Olear HUB el aceite de oliva virgen extra ideal "
            "según el plato, ingrediente o preferencia gastronómica que mencione el usuario. "
            "Usala cuando el usuario pregunte con qué acompañar una comida o pida una recomendación."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plato_o_preferencia": {
                    "type": "string",
                    "description": "El plato, tipo de comida (ej: pastas, carnes, celíaco) o característica buscada."
                }
            },
            "required": ["plato_o_preferencia"]
        }
    },
    {
        "type": "function",
        "name": "consultar_precio_stock",
        "description": (
            "Consulta el precio en pesos y la disponibilidad de stock de un varietal de aceite de oliva de Olear. "
            "Usala cuando el usuario pregunte explícitamente cuánto sale una botella o si hay stock."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "varietal": {
                    "type": "string",
                    "enum": list(CATALOGO_OLEAR.keys()),
                    "description": "Nombre del varietal consultado."
                }
            },
            "required": ["varietal"]
        }
    }
]

# 3. Despachador
FUNCIONES = {
    "recomendar_aceite_catalogo": recomendar_aceite_catalogo,
    "consultar_precio_stock": consultar_precio_stock,
}

async def ejecutar_funcion(nombre: str, argumentos: dict) -> dict:
    """Ejecuta la función pedida por el modelo y devuelve siempre un diccionario seguro."""
    logger.info("El modelo pidió %s(%s)", nombre, argumentos)
    funcion = FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"Función desconocida: {nombre}"}
    try:
        return await funcion(**argumentos)
    except Exception as error:
        logger.exception("Falló la herramienta %s", nombre)
        return {"error": f"No se pudo obtener el dato: {type(error).__name__}"}