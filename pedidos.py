"""
Flujo guiado de compra (/comprar) con botones interactivos e IA (v6).

Un ConversationHandler conduce al usuario paso a paso:
  1. PRODUCTO: selección desde el catálogo en vivo con botones inline.
  2. CANTIDAD: selección con botones rápidos o texto natural (interpretado con IA).
  3. ENTREGA: fecha de entrega en lenguaje natural (interpretada con IA) o botón rápido.
  4. CONFIRMACION: resumen, generación de link en Mercado Pago Sandbox y guardado en SQLite.
"""

from datetime import date, timedelta
import logging
import warnings

from pydantic import BaseModel, Field, ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

import db
import herramientas

logger = logging.getLogger("olly")

PRODUCTO, CANTIDAD, ENTREGA, CONFIRMACION = range(4)

MAX_BOTELLAS_PEDIDO = 20
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ---------------------------------------------------------------------------
# 1. Interpretación de lenguaje natural con IA (salida estructurada)
# ---------------------------------------------------------------------------
class CantidadInterpretada(BaseModel):
    """Resultado estructurado al interpretar una cantidad escrita libremente."""

    entendida: bool = Field(
        description="true si el texto expresa una cantidad numérica concreta; false si no."
    )
    cantidad: int = Field(
        default=0,
        description="Cantidad entera de botellas interpretada, o 0 si no se entendió.",
    )


class FechaEntregaInterpretada(BaseModel):
    """Resultado estructurado al interpretar una fecha de entrega."""

    entendida: bool = Field(
        description="true si el texto indica una fecha concreta o relativa resoluble; false si no."
    )
    fecha: str = Field(
        default="",
        description="Fecha en formato AAAA-MM-DD, o cadena vacía si no se entendió.",
    )


async def interpretar_cantidad(cliente, modelo: str, texto: str) -> int | None:
    """Convierte expresiones como 'un par' o 'media docena' en un entero, o None."""
    instrucciones = (
        "Interpretás la cantidad de botellas que quiere comprar un cliente. "
        "Ejemplos: 'un par' -> 2, 'media docena' -> 6, 'una docena' -> 12. "
        "Si el texto no expresa una cantidad concreta, respondé entendida=false y cantidad=0."
    )
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=instrucciones,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": CantidadInterpretada.model_json_schema(),
        },
        store=False,
    )
    resultado = CantidadInterpretada.model_validate_json(interaccion.output_text)
    if not resultado.entendida or resultado.cantidad <= 0:
        return None
    return resultado.cantidad


async def interpretar_fecha_entrega(cliente, modelo: str, texto: str) -> date | None:
    """Convierte una fecha en lenguaje natural a date, o None si no se entiende."""
    hoy = date.today()
    instrucciones = (
        f"Hoy es {DIAS_SEMANA[hoy.weekday()]} {hoy.isoformat()}. "
        "Convertí la fecha de entrega que menciona el cliente al formato AAAA-MM-DD. "
        "Si el texto no indica una fecha concreta, respondé entendida=false."
    )
    interaccion = await cliente.aio.interactions.create(
        model=modelo,
        system_instruction=instrucciones,
        input=texto,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": FechaEntregaInterpretada.model_json_schema(),
        },
        store=False,
    )
    resultado = FechaEntregaInterpretada.model_validate_json(interaccion.output_text)
    if not resultado.entendida or not resultado.fecha:
        return None
    return date.fromisoformat(resultado.fecha)


def _proximo_dia_habil(desde: date) -> date:
    """Devuelve el próximo día hábil a partir de mañana."""
    candidato = desde + timedelta(days=1)
    while candidato.weekday() >= 5:  # 5 = sábado, 6 = domingo
        candidato += timedelta(days=1)
    return candidato


def _formato_ars(monto: int) -> str:
    return f"${monto:,}".replace(",", ".")


# ---------------------------------------------------------------------------
# 2. Pasos del flujo guiado
# ---------------------------------------------------------------------------
async def inicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 0 (/comprar): consulta stock en Olear HUB y muestra botones inline."""
    await update.message.chat.send_action(ChatAction.TYPING)
    catalogo = await herramientas.consultar_catalogo(solo_con_stock=True)
    productos = catalogo.get("productos", [])
    if "error" in catalogo or not productos:
        await update.message.reply_text(
            "En este momento no pude cargar aceites disponibles desde Olear HUB. "
            "Probá de nuevo en unos instantes, por favor. 🙏"
        )
        return ConversationHandler.END

    context.user_data["catalogo_pedido"] = {p["id"]: p for p in productos}
    context.user_data["pedido"] = {}

    sugerencia = ""
    ultima_pref = await db.obtener_ultima_preferencia(update.effective_user.id)
    if ultima_pref and ultima_pref.get("intensidad_preferida") not in (None, "indefinida"):
        sugerencia = (
            f"Según tu último perfil guardado, te inclinás por una intensidad "
            f"{ultima_pref['intensidad_preferida']}.\n\n"
        )

    filas = [
        [
            InlineKeyboardButton(
                f"{p['nombre']} ({p['presentacion_ml']} ml) · {_formato_ars(p['precio_ars'])}",
                callback_data=f"prod:{p['id']}",
            )
        ]
        for p in productos
    ]
    filas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

    await update.message.reply_text(
        "¡Vamos a armar tu pedido en Olear HUB! 🫒\n\n"
        f"{sugerencia}"
        "Elegí el aceite que querés comprar (podés salir en cualquier momento con /cancelar):",
        reply_markup=InlineKeyboardMarkup(filas),
    )
    return PRODUCTO


async def elegir_producto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 1: guarda el aceite elegido y ofrece cantidades disponibles."""
    query = update.callback_query
    await query.answer()

    catalogo = context.user_data.get("catalogo_pedido")
    if not catalogo:
        await query.edit_message_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    producto_id = query.data.removeprefix("prod:")
    producto = catalogo.get(producto_id)
    if producto is None:
        await query.edit_message_text("Ese producto ya no está disponible. Escribí /comprar para actualizar el catálogo.")
        return ConversationHandler.END

    context.user_data["pedido"] = {
        "producto_id": producto["id"],
        "producto_nombre": f"{producto['nombre']} ({producto['presentacion_ml']} ml)",
        "precio_ars": int(producto["precio_ars"]),
        "stock_unidades": int(producto["stock_unidades"]),
    }

    stock = int(producto["stock_unidades"])
    max_permitido = min(MAX_BOTELLAS_PEDIDO, stock)
    opciones = [n for n in (1, 2, 3, 6) if n <= max_permitido]
    filas = []
    if opciones:
        filas.append([InlineKeyboardButton(f"{n} u.", callback_data=f"cant:{n}") for n in opciones])
    filas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

    await query.edit_message_text(
        f"Elegiste: {producto['nombre']} ({producto['presentacion_ml']} ml) · "
        f"{_formato_ars(producto['precio_ars'])} c/u\n"
        f"Stock disponible: {stock} unidades.\n\n"
        "¿Cuántas botellas querés? Tocá un botón o escribilo como prefieras "
        "(por ejemplo: \"2\", \"un par\", \"media docena\"):",
        reply_markup=InlineKeyboardMarkup(filas),
    )
    return CANTIDAD


async def recordar_boton_producto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pide usar los botones inline si el usuario envía texto en el paso 1."""
    await update.message.reply_text(
        "Tocá uno de los botones de productos de arriba para continuar, o escribí /cancelar."
    )
    return PRODUCTO


async def _pedir_entrega(enviar_fn, context: ContextTypes.DEFAULT_TYPE, cantidad: int) -> int:
    """Guarda la cantidad validada y solicita la fecha de entrega."""
    pedido = context.user_data["pedido"]
    pedido["cantidad"] = cantidad
    pedido["total_ars"] = pedido["precio_ars"] * cantidad

    teclado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚚 Lo antes posible (próximo día hábil)", callback_data="entrega:pronto")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )
    await enviar_fn(
        f"Anotado: {cantidad} x {pedido['producto_nombre']} "
        f"({_formato_ars(pedido['total_ars'])}).\n\n"
        "¿Para qué día te gustaría recibirlo o retirarlo? Podés tocar el botón o "
        "escribirlo con tus palabras (ej: \"mañana\", \"el sábado\", \"25 de noviembre\"):",
        reply_markup=teclado,
    )
    return ENTREGA


async def elegir_cantidad_boton(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 2 (botón): toma la cantidad elegida y pasa a fecha de entrega."""
    query = update.callback_query
    await query.answer()

    pedido = context.user_data.get("pedido")
    if not pedido:
        await query.edit_message_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    cantidad = int(query.data.removeprefix("cant:"))
    stock = pedido["stock_unidades"]
    if not 1 <= cantidad <= min(MAX_BOTELLAS_PEDIDO, stock):
        await query.edit_message_text("Cantidad fuera de rango disponible. Probá de nuevo con /comprar.")
        return ConversationHandler.END

    return await _pedir_entrega(query.edit_message_text, context, cantidad)


async def recibir_cantidad_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 2 (texto libre): valida dígitos o interpreta lenguaje natural con Gemini."""
    pedido = context.user_data.get("pedido")
    if not pedido:
        await update.message.reply_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    texto = update.message.text.strip()
    if texto.isdigit():
        cantidad = int(texto)
    else:
        await update.message.chat.send_action(ChatAction.TYPING)
        cliente = context.bot_data["cliente_gemini"]
        modelo = context.bot_data["modelo"]
        try:
            cantidad = await interpretar_cantidad(cliente, modelo, texto)
        except ValidationError:
            cantidad = None
        except Exception:
            logger.exception("Error al interpretar la cantidad")
            await update.message.reply_text("No pude procesar esa cantidad en este momento. Probá escribir un número.")
            return CANTIDAD

    if cantidad is None:
        await update.message.reply_text(
            "No entendí la cantidad. Probá con un número (ej: 2) o una frase como \"un par\"."
        )
        return CANTIDAD

    stock = pedido["stock_unidades"]
    limite = min(MAX_BOTELLAS_PEDIDO, stock)
    if not 1 <= cantidad <= limite:
        await update.message.reply_text(
            f"Podés pedir entre 1 y {limite} unidades según el stock disponible. ¿Cuántas querés?"
        )
        return CANTIDAD

    return await _pedir_entrega(update.message.reply_text, context, cantidad)


async def _mostrar_confirmacion(enviar_fn, pedido: dict, fecha: date) -> int:
    """Guarda la fecha de entrega y pide confirmación final con botones inline."""
    pedido["fecha_entrega"] = fecha.isoformat()
    teclado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar y generar link de pago", callback_data="confirmar:si")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )
    await enviar_fn(
        "Revisá los datos de tu pedido antes de generar el pago:\n\n"
        f"Producto: {pedido['producto_nombre']}\n"
        f"Cantidad: {pedido['cantidad']}\n"
        f"Total: {_formato_ars(pedido['total_ars'])} ARS\n"
        f"Entrega estimada: {DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d/%m/%Y')}\n\n"
        "¿Confirmás la compra?",
        reply_markup=teclado,
    )
    return CONFIRMACION


async def elegir_entrega_pronto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 3 (botón): asigna el próximo día hábil como entrega."""
    query = update.callback_query
    await query.answer()

    pedido = context.user_data.get("pedido")
    if not pedido:
        await query.edit_message_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    fecha = _proximo_dia_habil(date.today())
    return await _mostrar_confirmacion(query.edit_message_text, pedido, fecha)


async def recibir_entrega_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 3 (texto libre): interpreta la fecha en lenguaje natural con IA."""
    pedido = context.user_data.get("pedido")
    if not pedido:
        await update.message.reply_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    await update.message.chat.send_action(ChatAction.TYPING)
    cliente = context.bot_data["cliente_gemini"]
    modelo = context.bot_data["modelo"]
    try:
        fecha = await interpretar_fecha_entrega(cliente, modelo, update.message.text)
    except (ValidationError, ValueError):
        fecha = None
    except Exception:
        logger.exception("Error al interpretar fecha de entrega")
        await update.message.reply_text("No pude procesar esa fecha en este momento. Probá de nuevo.")
        return ENTREGA

    if fecha is None:
        await update.message.reply_text(
            "No entendí la fecha. Probá con algo como \"el sábado\" o \"25 de noviembre\"."
        )
        return ENTREGA
    if fecha < date.today():
        await update.message.reply_text("Esa fecha ya pasó. Indicame una fecha a partir de hoy.")
        return ENTREGA

    return await _mostrar_confirmacion(update.message.reply_text, pedido, fecha)


async def confirmar_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 4: genera la preferencia en Mercado Pago Sandbox y guarda el pedido."""
    query = update.callback_query
    await query.answer()

    pedido = context.user_data.pop("pedido", None)
    context.user_data.pop("catalogo_pedido", None)
    if not pedido:
        await query.edit_message_text("La sesión del pedido expiró. Escribí /comprar para empezar de nuevo.")
        return ConversationHandler.END

    await query.edit_message_text("Generando tu orden y link de pago en Mercado Pago... ⏳")
    resultado_mp = await herramientas.generar_link_pago(pedido["producto_id"], pedido["cantidad"])
    if "error" in resultado_mp:
        await query.edit_message_text(
            f"No se pudo completar el pedido: {resultado_mp['error']}\n"
            "Podés intentar nuevamente con /comprar."
        )
        return ConversationHandler.END

    numero = await db.guardar_pedido(
        user_id=update.effective_user.id,
        producto_id=pedido["producto_id"],
        producto_nombre=pedido["producto_nombre"],
        cantidad=pedido["cantidad"],
        total_ars=resultado_mp["total_ars"],
        fecha_entrega=pedido["fecha_entrega"],
        preferencia_mp=resultado_mp.get("preferencia_id") or "",
        link_pago=resultado_mp["link_pago"],
    )

    fecha_fmt = date.fromisoformat(pedido["fecha_entrega"]).strftime("%d/%m/%Y")
    teclado_pago = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 Pagar en Mercado Pago (Sandbox)", url=resultado_mp["link_pago"])]]
    )
    await query.edit_message_text(
        f"¡Pedido #{numero} registrado! 🎉\n\n"
        f"Producto: {pedido['cantidad']} x {pedido['producto_nombre']}\n"
        f"Total: {_formato_ars(resultado_mp['total_ars'])} ARS\n"
        f"Entrega programada: {fecha_fmt}\n\n"
        f"También podés abrir el enlace directo:\n{resultado_mp['link_pago']}",
        reply_markup=teclado_pago,
    )
    return ConversationHandler.END


async def recordar_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pide usar los botones de confirmación si el usuario escribe texto al final."""
    await update.message.reply_text(
        "Tocá el botón \"Confirmar y generar link de pago\" o \"Cancelar\" (o usá /cancelar)."
    )
    return CONFIRMACION


async def cancelar_comando(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancelar: interrumpe el pedido en cualquier paso."""
    context.user_data.pop("pedido", None)
    context.user_data.pop("catalogo_pedido", None)
    await update.message.reply_text("Pedido cancelado. ¿En qué más te ayudo? 🫒")
    return ConversationHandler.END


async def cancelar_boton(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botón Cancelar: interrumpe el pedido desde cualquier teclado inline."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("pedido", None)
    context.user_data.pop("catalogo_pedido", None)
    await query.edit_message_text("Pedido cancelado. Cuando quieras, podés empezar otro con /comprar. 🫒")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# 3. Armado del ConversationHandler
# ---------------------------------------------------------------------------
def crear_manejador() -> ConversationHandler:
    """Arma el ConversationHandler que se registra en bot.py."""
    texto = filters.TEXT & ~filters.COMMAND
    cancel_btn = CallbackQueryHandler(cancelar_boton, pattern=r"^cancelar$")
    # per_message=False es intencional: el flujo combina botones inline y texto libre por usuario.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PTBUserWarning)
        return ConversationHandler(
            entry_points=[CommandHandler("comprar", inicio)],
            states={
                PRODUCTO: [
                    CallbackQueryHandler(elegir_producto, pattern=r"^prod:"),
                    cancel_btn,
                    MessageHandler(texto, recordar_boton_producto),
                ],
                CANTIDAD: [
                    CallbackQueryHandler(elegir_cantidad_boton, pattern=r"^cant:"),
                    cancel_btn,
                    MessageHandler(texto, recibir_cantidad_texto),
                ],
                ENTREGA: [
                    CallbackQueryHandler(elegir_entrega_pronto, pattern=r"^entrega:pronto$"),
                    cancel_btn,
                    MessageHandler(texto, recibir_entrega_texto),
                ],
                CONFIRMACION: [
                    CallbackQueryHandler(confirmar_pedido, pattern=r"^confirmar:si$"),
                    cancel_btn,
                    MessageHandler(texto, recordar_confirmacion),
                ],
            },
            fallbacks=[
                CommandHandler("cancelar", cancelar_comando),
                cancel_btn,
            ],
            allow_reentry=True,
        )
