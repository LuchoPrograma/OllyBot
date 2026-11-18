"""
Análisis de preferencias gastronómicas con salida estructurada (v5).

Extrae entidades y preferencias del texto del usuario (ingredientes, tipo de
cocción, descriptores sensoriales, intensidad sugerida y perfil de compra)
exigiendo a Gemini una respuesta JSON validada con Pydantic.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AnalisisPreferencias(BaseModel):
    """Estructura del análisis gastronómico y comercial de una consulta."""

    ingredientes: list[str] = Field(
        description=(
            "Ingredientes, platos o comidas mencionados en el texto (por ejemplo: "
            "carnes rojas, pastas, ensalada verde, pescado). Lista vacía si no hay."
        )
    )
    tipo_coccion: Literal[
        "crudo", "parrilla", "horno", "salteado", "fritura", "mixto", "no_especificado"
    ] = Field(
        description=(
            "Método de cocción o uso principal. Si se mencionan varios usos distintos, "
            "usar 'mixto'. Si no surge del texto, usar 'no_especificado'."
        )
    )
    descriptores: list[
        Literal["suave", "intenso", "frutado", "amargo", "picante", "equilibrado"]
    ] = Field(
        description=(
            "Descriptores sensoriales deseados o mencionados explícitamente en el texto. "
            "Lista vacía si el texto no aporta pistas sensoriales."
        )
    )
    intensidad_preferida: Literal["suave", "media", "intensa", "indefinida"] = Field(
        description=(
            "Intensidad de aceite preferida o más adecuada según el gusto o plato "
            "mencionado. Si no puede inferirse, usar 'indefinida'."
        )
    )
    perfil_compra: Literal[
        "explorador_gourmet", "uso_diario", "regalo", "compra_directa", "indefinido"
    ] = Field(
        description=(
            "Perfil del cliente: 'explorador_gourmet' si busca maridajes o notas de cata; "
            "'uso_diario' si prioriza cocina cotidiana o rendimiento; 'regalo' si busca "
            "para obsequiar; 'compra_directa' si ya pide precio, stock o link de compra; "
            "'indefinido' si no hay suficiente contexto."
        )
    )
    resumen: str = Field(
        description="Resumen de la búsqueda o preferencia del usuario en una sola oración breve."
    )


PROMPT_ANALISIS = """
Analizás consultas de clientes de Olear HUB (aceites de oliva virgen extra de Mendoza).
Respondé únicamente con el análisis estructurado pedido, en español.

Reglas de clasificación:
- Extraé en `ingredientes` solo comidas o ingredientes presentes en el texto.
- Usá `tipo_coccion` según la preparación indicada (por ejemplo, ensaladas y bruschettas
  van como "crudo"; asado o bife a las brasas como "parrilla"). Si combina crudo y cocción,
  usá "mixto".
- En `descriptores`, incluí únicamente valores de la lista permitida que surjan del pedido.
- Clasificá `perfil_compra` priorizando "compra_directa" si el cliente menciona comprar,
  pedir precio o link de pago; "regalo" si es para obsequiar; "uso_diario" si habla de
  cocina cotidiana; y "explorador_gourmet" si busca maridajes específicos o notas de cata.
""".strip()


async def analizar_preferencias(cliente, modelo: str, texto: str) -> AnalisisPreferencias:
    """Envía el texto del usuario a Gemini y devuelve el análisis estructurado validado."""
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=PROMPT_ANALISIS,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": AnalisisPreferencias.model_json_schema(),
        },
        store=False,
    )
    return AnalisisPreferencias.model_validate_json(interaccion.output_text)
