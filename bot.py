"""
Olly v5: sommelier de aceite de oliva de Olear.

- Responde con Gemini (Interactions API sin estado, store=False).
- Guarda la conversación de cada usuario en SQLite (db.py) y la envía como
  contexto en cada consulta, así recuerda lo hablado aunque se reinicie.
- Soporta function calling (v4) para consultar catálogo, maridajes y precios.
- Soporta análisis estructurado de reseñas (v5) con Pydantic y comandos /resena y /resenas.
- /olvidar borra la conversación del usuario.
"""

import json
import logging
import os

from dotenv import load_dotenv
from google import genai
from pydantic import ValidationError
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from analisis import analizar_resena
import db
from herramientas import DECLARACIONES, ejecutar_funcion
from prompts import PROMPT_SISTEMA

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# El modelo se lee del .env para poder cambiarlo sin tocar el código.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Mensajes anteriores que se envían al modelo (20 = 10 preguntas y respuestas).
MAX_MENSAJES_HISTORIAL = 20

# Límite máximo de vueltas del ciclo de function calling en un mismo mensaje.
MAX_VUELTAS_HERRAMIENTAS = 5

# Longitud máxima de un mensaje de Telegram.
LIMITE_TELEGRAM = 4096

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("olly")

# ---------------------------------------------------------------------------
# Conexión con Gemini
# ---------------------------------------------------------------------------
cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)


def armar_entrada(historial: list[tuple[str, str]], mensaje_nuevo: str) -> list[dict]:
    """Convierte el historial en los pasos que espera la Interactions API."""
    tipo_de_paso = {"user": "user_input", "model": "model_output"}
    pasos = [
        {"type": tipo_de_paso[rol], "content": [{"type": "text", "text": texto}]}
        for rol, texto in historial
    ]
    pasos.append({"type": "user_input", "content": [{"type": "text", "text": mensaje_nuevo}]})
    return pasos


async def consultar_gemini(historial: list[tuple[str, str]], mensaje: str) -> str:
    """Envía la conversación a Gemini y resuelve el ciclo de function calling."""
    entrada = armar_entrada(historial, mensaje)

    for vuelta in range(MAX_VUELTAS_HERRAMIENTAS):
        interaccion = await cliente_gemini.aio.interactions.create(
            model=GEMINI_MODEL,
            system_instruction=PROMPT_SISTEMA,
            input=entrada,
            tools=DECLARACIONES,
            store=False,  # la memoria la administra el bot, no Google
        )

        llamadas = [paso for paso in interaccion.steps if paso.type == "function_call"]

        if not llamadas:
            return interaccion.output_text or "No se me ocurrió nada para responder 🤔"

        for paso in interaccion.steps:
            entrada.append(paso.model_dump())

        for llamada in llamadas:
            resultado = await ejecutar_funcion(llamada.name, llamada.arguments)
            entrada.append({
                "type": "function_result",
                "call_id": llamada.id,
                "name": llamada.name,
                "result": [{"type": "text", "text": json.dumps(resultado, ensure_ascii=False)}],
            })

    logger.warning("Se alcanzó el máximo de %d vueltas de herramientas", MAX_VUELTAS_HERRAMIENTAS)
    return "No pude completar la consulta con las herramientas. ¿Podés reformular la pregunta? 🔄"


def describir_error(error: Exception) -> str:
    """Traduce un error de la API a un mensaje comprensible para el usuario."""
    codigo = getattr(error, "status_code", None)
    if codigo == 429:
        return "Estoy recibiendo demasiadas consultas. Probá de nuevo en un minuto, por favor. ⏳"
    if codigo in (401, 403):
        return "Tengo un problema de configuración. Avisale a quien me administra. 🔧"
    return "Tuve un problema para pensar la respuesta. ¿Me lo preguntás de nuevo? 🙏"

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /start."""
    nombre = update.effective_user.first_name
    logger.info("Nuevo /start de %s (id %s)", nombre, update.effective_user.id)
    await update.message.reply_text(
        f"¡Hola, {nombre}! Soy Olly 🫒, el sommelier de aceite de oliva de Olear.\n\n"
        "Contame qué vas a cocinar o qué aceite te gusta y te ayudo a elegir "
        "el ideal: variedades, maridajes, usos en la cocina y más.\n\n"
        "Escribí /help para ver lo que sé hacer."
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /help."""
    await update.message.reply_text(
        "Estos son mis comandos:\n\n"
        "/start - Presentación de Olly\n"
        "/help - Esta ayuda\n"
        "/olvidar - Borra nuestra conversación y empezamos de cero\n"
        "/resena <texto> - Dejá tu opinión sobre una experiencia\n"
        "/resenas - Ver el resumen de opiniones recibidas\n\n"
        "Y, sobre todo, podés escribirme lo que quieras saber sobre "
        "aceite de oliva. Me acuerdo de lo que hablamos y puedo consultar catálogos y precios."
    )


async def olvidar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /olvidar: borra el historial del usuario."""
    borrados = await db.borrar_historial(update.effective_user.id)
    logger.info("Usuario %s borró %d mensajes", update.effective_user.id, borrados)
    await update.message.reply_text("Listo, empezamos de cero. ¿En qué te ayudo? 🙂")


async def resena(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /resena: analiza la opinión y la guarda estructurada en SQLite."""
    texto = " ".join(context.args).strip()
    if not texto:
        await update.message.reply_text(
            "Escribí tu opinión después del comando. Por ejemplo:\n"
            "/resena El varietal Arauco tiene un carácter intenso ideal para mis pastas."
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        analisis = await analizar_resena(cliente_gemini, GEMINI_MODEL, texto)
    except ValidationError:
        logger.exception("Análisis de reseña con formato inválido")
        await update.message.reply_text("No pude analizar tu opinión. ¿Probás escribirla de nuevo?")
        return
    except Exception as error:
        logger.exception("Error al analizar la reseña")
        await update.message.reply_text(describir_error(error))
        return

    await db.guardar_resena(update.effective_user.id, texto, analisis)

    emoji = {"positivo": "🟢", "neutral": "🟡", "negativo": "🔴"}[analisis.sentimiento]
    await update.message.reply_text(
        f"¡Gracias por tu opinión! {emoji}\n\n"
        f"Sentimiento: {analisis.sentimiento}\n"
        f"Puntaje: {'★' * analisis.puntaje} ({analisis.puntaje}/5)\n"
        f"Aspectos: {', '.join(analisis.aspectos)}\n"
        f"Resumen: {analisis.resumen}"
    )


async def resenas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde al comando /resenas: muestra el resumen de todas las opiniones recibidas."""
    datos = await db.resumen_resenas()
    if datos["cantidad"] == 0:
        await update.message.reply_text("Todavía no recibí opiniones. Podés dejar la tuya con /resena.")
        return

    conteo = datos["por_sentimiento"]
    await update.message.reply_text(
        f"📊 Resumen de opiniones de Olear HUB:\n\n"
        f"Opiniones recibidas: {datos['cantidad']}\n"
        f"Puntaje promedio: {datos['promedio']:.1f}/5\n"
        f"Positivas: {conteo.get('positivo', 0)}\n"
        f"Neutrales: {conteo.get('neutral', 0)}\n"
        f"Negativas: {conteo.get('negativo', 0)}"
    )


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde con Gemini, teniendo en cuenta la conversación previa y las herramientas."""
    user_id = update.effective_user.id
    texto = update.message.text
    logger.info("Mensaje de %s: %s", user_id, texto)

    await update.message.chat.send_action(ChatAction.TYPING)

    # Paso 1: recuperar lo que ya se habló con este usuario.
    historial = await db.obtener_historial(user_id, MAX_MENSAJES_HISTORIAL)

    # Paso 2: consultar al modelo con el historial más el mensaje nuevo y herramientas.
    try:
        respuesta = await consultar_gemini(historial, texto)
    except Exception as error:
        logger.exception("Error al consultar a Gemini")
        await update.message.reply_text(describir_error(error))
        return  # si falla, no se guarda nada

    # Paso 3: guardar la pregunta y la respuesta para la próxima consulta.
    await db.guardar_intercambio(user_id, texto, respuesta)

    for inicio in range(0, len(respuesta), LIMITE_TELEGRAM):
        await update.message.reply_text(respuesta[inicio:inicio + LIMITE_TELEGRAM])


async def manejo_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra cualquier error no previsto para que el bot no falle en silencio."""
    logger.error("Error al procesar una actualización", exc_info=context.error)

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
async def al_iniciar(app: Application) -> None:
    """Se ejecuta una vez, antes de recibir mensajes: prepara la base."""
    await db.inicializar()
    logger.info("Base de datos lista (%s).", db.RUTA_DB)


def main() -> None:
    faltantes = [nombre for nombre, valor in [("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
                                              ("GEMINI_API_KEY", GEMINI_API_KEY)]
                 if not valor]
    if faltantes:
        raise SystemExit(f"Faltan variables en el .env: {', '.join(faltantes)}")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(al_iniciar).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("olvidar", olvidar))
    app.add_handler(CommandHandler("resena", resena))
    app.add_handler(CommandHandler("resenas", resenas))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.add_error_handler(manejo_error)

    logger.info("Olly v5 en línea con el modelo %s.", GEMINI_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()