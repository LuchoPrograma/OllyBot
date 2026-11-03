import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("olly")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Responde al comando /start
    nombre = update.effective_user.first_name
    logger.info("Nuevo /start de %s (id %s)", nombre, update.effective_user.id)
    await update.message.reply_text(
        f"¡Hola, {nombre}! Soy Olly, tu asistente Sommelier de Olear."
    )


# Comando /help
async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Responder al comando /help
    await update.message.reply_text(
        "Estos son mis comandos:\n\n"
        "/start - Presentación de Olly\n"
        "/help - Esta ayuda\n\n"
        "Tambien podes escribirme cualquier mensaje y te lo repito."
    )


# Responder un texto (funcion eco)
async def eco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Repite cualquier mensaje de texto que no sea un comando
    texto = update.message.text
    logger.info("Mensaje recibido: %s", texto)
    await update.message.reply_text(f"Me dijiste {texto}")


# Manejo de errores
async def manejo_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Registra cualquier error para que el bot no se detenga en silencio.
    logger.error("Error al procesar una actualización", exc_info=context.error)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise SystemExit(
            "Falta TELEGRAM_TOKEN."
        )
    #logger.info("Token cargado: %s...", TELEGRAM_TOKEN[:12])
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, eco))
    app.add_error_handler(manejo_error)

    logger.info("Olly está en línea. Presiona Ctrl+c para detenerlo.")

    # Polling: el bot le pregunta a TG, una y otra vez, si hay mensajes nuevos
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

