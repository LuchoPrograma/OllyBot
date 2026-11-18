"""
Prueba aislada del análisis de preferencias: consulta a Gemini sin pasar por Telegram.
"""

import asyncio
import os

from dotenv import load_dotenv
from google import genai

from analisis import analizar_preferencias

load_dotenv()
cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
modelo = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


async def main() -> None:
    consultas = [
        "Busco un aceite intenso, amargo y con notas picantes para carnes rojas a la parrilla.",
        "Quiero algo suave y frutado para ensaladas y pescados de todos los días.",
        "Necesito comprar ya 2 botellas de Arauco Reserva de 500 ml para regalar.",
    ]
    for texto in consultas:
        analisis = await analizar_preferencias(cliente, modelo, texto)
        print(
            f"- Perfil: {analisis.perfil_compra} | Intensidad: {analisis.intensidad_preferida} | "
            f"Cocción: {analisis.tipo_coccion} | Ingredientes: {analisis.ingredientes} | "
            f"Descriptores: {analisis.descriptores}\n  Resumen: {analisis.resumen}"
        )


if __name__ == "__main__":
    asyncio.run(main())
