from typing import Literal
from pydantic import BaseModel, Field

class AnalisisResena(BaseModel):
    """Estructura estricta que debe tener el análisis de una opinión o reseña."""
    sentimiento: Literal["positivo", "neutral", "negativo"] = Field(
        description="Sentimiento general de la opinión expresada por el usuario."
    )
    puntaje: int = Field(
        ge=1, le=5,
        description="Satisfacción estimada del cliente, de 1 (muy mala) a 5 (excelente)."
    )
    aspectos: list[str] = Field(
        description="Aspectos mencionados, en una o dos palabras cada uno (ej: sabor, precio, aroma, atención)."
    )
    resumen: str = Field(
        description="Resumen de la opinión en una sola oración breve."
    )

PROMPT_ANALISIS = """
Analizás opiniones y reseñas de clientes sobre los aceites de oliva virgen extra y la atención de Olear HUB.
Respondé únicamente con el análisis pedido en formato estructurado, en español y con voseo si corresponde.
""".strip()

async def analizar_resena(cliente, modelo: str, texto: str) -> AnalisisResena:
    """Envía la reseña a Gemini exigiendo una salida estructurada validada con Pydantic."""
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=PROMPT_ANALISIS,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": AnalisisResena.model_json_schema(),
        },
        store=False,
    )
    return AnalisisResena.model_validate_json(interaccion.output_text)