"""
Flujo guiado de reservas o compras paso a paso (/reservar).
Utiliza ConversationHandler para controlar el estado y Pydantic con Gemini
únicamente para interpretar fechas en lenguaje natural.
"""

from datetime import date
import logging
from pydantic import BaseModel, Field, ValidationError
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db

logger = logging.getLogger("olly")

# Estados de la conversación (números distintos para cada paso)
EXCURSION, FECHA, PERSONAS, CONFIRMACION = range(4)

# Opciones disponibles para el usuario
EXCURSIONES = [
    "Excursión Alta Montaña Cumbres Blancas",
    "Rafting Río Claro",
    "Cabalgata Quebrada del Cóndor",
    "Trekking Cerro Mirador",
]

MAX_PERSONAS = 10
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class FechaInterpretada(BaseModel):
    """Estructura esperada al interpretar una fecha con IA."""
    entendida: bool = Field(description="true si el texto indica una fecha concreta; false si no.")
    fecha: str = Field(description="La fecha en formato AAAA-MM-DD, o cadena vacía si no se entendió.")


async def interpretar_fecha(cliente, modelo: str, texto: str) -> date | None:
    """Convierte texto natural en un objeto date usando salida estructurada."""
    hoy = date.today()
    instrucciones = (
        f"Hoy es {DIAS_SEMANA[hoy.weekday()]} {hoy.isoformat()}. "
        "Convertí la fecha mencionada al formato AAAA-MM-DD. "
        "Si el texto no indica una fecha concreta, respondé entendida=false."
    )
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=instrucciones,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": FechaInterpretada.model_json_schema(),
        },
        store=False,
    )
    resultado = FechaInterpretada.model_validate_json(interaccion.output_text)
    if not resultado.entendida:
        return None
    return date.fromisoformat(resultado.fecha)


async def inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 0 (/reservar): inicia el flujo y muestra el teclado de opciones."""
    context.user_data["reserva"] = {}
    teclado = ReplyKeyboardMarkup([[nombre] for nombre in EXCURSIONES], one_time_keyboard=True)
    await update.message.reply_text(
        "¡Vamos a armar tu reserva! ¿Qué experiencia te interesa?\n"
        "(Podés cancelar en cualquier momento con /cancelar)",
        reply_markup=teclado,
    )
    return EXCURSION


async def elegir_excursion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 1: valida la opción elegida del teclado."""
    eleccion = update.message.text
    if eleccion not in EXCURSIONES:
        await update.message.reply_text("Elegí una de las opciones del teclado, por favor.")
        return EXCURSION

    context.user_data["reserva"]["excursion"] = eleccion
    await update.message.reply_text(
        "¿Para qué día? Podés escribirlo como quieras: 'el sábado', '25 de noviembre'…",
        reply_markup=ReplyKeyboardRemove(),
    )
    return FECHA


async def recibir_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 2: interpreta la fecha usando Gemini y valida que no sea pasada."""
    await update.message.chat.send_action(ChatAction.TYPING)
    cliente = context.bot_data["cliente_gemini"]
    modelo = context.bot_data["modelo"]

    try:
        fecha = await interpretar_fecha(cliente, modelo, update.message.text)
    except (ValidationError, ValueError):
        fecha = None
    except Exception:
        logger.exception("Error al interpretar la fecha")
        await update.message.reply_text("No pude procesar la fecha en este momento. Probá de nuevo.")
        return FECHA

    if fecha is None:
        await update.message.reply_text("No entendí la fecha. Probá, por ejemplo, con 'el sábado 22'.")
        return FECHA
    if fecha < date.today():
        await update.message.reply_text("Esa fecha ya pasó. ¿Para qué día querés reservar?")
        return FECHA

    context.user_data["reserva"]["fecha"] = fecha.isoformat()
    await update.message.reply_text(
        f"Perfecto: {DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d/%m/%Y')}. "
        f"¿Para cuántas personas? (de 1 a {MAX_PERSONAS})"
    )
    return PERSONAS


async def recibir_personas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 3: valida por código que la cantidad sea un número en rango válido."""
    texto = update.message.text.strip()
    if not texto.isdigit() or not 1 <= int(texto) <= MAX_PERSONAS:
        await update.message.reply_text(f"Escribí un número entre 1 y {MAX_PERSONAS}.")
        return PERSONAS

    reserva = context.user_data["reserva"]
    reserva["personas"] = int(texto)
    fecha = date.fromisoformat(reserva["fecha"])

    teclado = ReplyKeyboardMarkup([["Confirmar", "Cancelar"]], one_time_keyboard=True)
    await update.message.reply_text(
        "Revisá los datos de tu reserva:\n\n"
        f"Experiencia: {reserva['excursion']}\n"
        f"Fecha: {fecha.strftime('%d/%m/%Y')}\n"
        f"Personas: {reserva['personas']}\n\n"
        "¿Confirmás?",
        reply_markup=teclado,
    )
    return CONFIRMACION


async def confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 4: almacena la reserva de forma persistente si el usuario confirma."""
    reserva = context.user_data.pop("reserva", {})
    if update.message.text != "Confirmar":
        await update.message.reply_text("Reserva cancelada.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    numero = await db.guardar_reserva(
        update.effective_user.id, reserva["excursion"], reserva["fecha"], reserva["personas"]
    )
    await update.message.reply_text(
        f"¡Listo! Tu reserva quedó registrada con el número {numero}. 🎉\n"
        "(Reserva de prueba almacenada correctamente en SQLite).",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comando /cancelar: interrumpe el flujo guiado en cualquier estado."""
    context.user_data.pop("reserva", None)
    await update.message.reply_text("Reserva cancelada. ¿En qué más te ayudo?", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def crear_manejador() -> ConversationHandler:
    """Configura el ConversationHandler para registrarlo en el bot principal."""
    texto_filtro = filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[CommandHandler("reservar", inicio)],
        states={
            EXCURSION: [MessageHandler(texto_filtro, elegir_excursion)],
            FECHA: [MessageHandler(texto_filtro, recibir_fecha)],
            PERSONAS: [MessageHandler(texto_filtro, recibir_personas)],
            CONFIRMACION: [MessageHandler(texto_filtro, confirmar)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )