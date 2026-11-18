"""
Memoria de Olly: historial de conversación en SQLite.

Cada mensaje (del usuario o del modelo) se guarda como una fila de la tabla
`mensajes`. Se utiliza aiosqlite, la versión asíncrona de sqlite3, para que
las operaciones sobre la base no bloqueen al bot mientras atiende a otros
usuarios.
"""

import json  # convierte la lista de aspectos a texto para guardarla en SQLite
import aiosqlite  # SQLite con soporte para async/await

# Archivo de la base. Se crea en la carpeta desde la que se ejecuta el bot.
# Está excluido por .gitignore (*.db).
RUTA_DB = "olly.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,                -- orden de llegada
    user_id INTEGER NOT NULL,                            -- id de Telegram
    rol TEXT NOT NULL CHECK (rol IN ('user', 'model')),  -- quién escribió
    texto TEXT NOT NULL,                                 -- contenido
    fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP        -- fecha y hora
);
CREATE INDEX IF NOT EXISTS idx_mensajes_usuario ON mensajes (user_id, id);

-- Reseñas analizadas (v5). Cada columna corresponde a un campo del análisis.
CREATE TABLE IF NOT EXISTS resenas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,                -- orden de llegada
    user_id INTEGER NOT NULL,                            -- id de Telegram
    texto TEXT NOT NULL,                                 -- reseña original
    sentimiento TEXT NOT NULL,                           -- positivo, neutral o negativo
    puntaje INTEGER NOT NULL,                            -- de 1 a 5
    aspectos TEXT NOT NULL,                              -- lista guardada como texto JSON
    resumen TEXT NOT NULL,                               -- resumen en una oración
    fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP        -- fecha y hora
);

-- Reservas o compras simuladas (v6 - Flujo guiado).
CREATE TABLE IF NOT EXISTS reservas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    excursion  TEXT    NOT NULL,
    fecha      TEXT    NOT NULL,
    personas   INTEGER NOT NULL,
    creada     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def inicializar() -> None:
    """Crea la tabla y el índice si todavía no existen."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.executescript(ESQUEMA)
        await db.commit()


async def guardar_intercambio(user_id: int, pregunta: str, respuesta: str) -> None:
    """Guarda en una sola operación el mensaje del usuario y la respuesta del modelo."""
    async with aiosqlite.connect(RUTA_DB) as db:
        # Los ? son parámetros: SQLite inserta los valores de forma segura.
        await db.executemany(
            "INSERT INTO mensajes (user_id, rol, texto) VALUES (?, ?, ?)",
            [(user_id, "user", pregunta),
             (user_id, "model", respuesta)],
        )
        await db.commit()


async def obtener_historial(user_id: int, limite: int) -> list[tuple[str, str]]:
    """Devuelve los últimos `limite` mensajes del usuario, del más antiguo al más reciente."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "SELECT rol, texto FROM mensajes WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limite),
        )
        filas = await cursor.fetchall()
    # Se invierte para que el modelo lea la conversación en orden cronológico.
    return list(reversed(filas))


async def borrar_historial(user_id: int) -> int:
    """Borra la conversación de un usuario y devuelve cuántos mensajes eliminó."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("DELETE FROM mensajes WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount


async def guardar_resena(user_id: int, texto: str, analisis) -> None:
    """Guarda una reseña junto con su análisis estructurado (objeto AnalisisResena)."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.execute(
            "INSERT INTO resenas (user_id, texto, sentimiento, puntaje, aspectos, resumen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                texto,
                analisis.sentimiento,
                analisis.puntaje,
                # SQLite no tiene tipo lista: se guarda como texto JSON.
                json.dumps(analisis.aspectos, ensure_ascii=False),
                analisis.resumen,
            ),
        )
        await db.commit()


async def resumen_resenas() -> dict:
    """Devuelve la cantidad de reseñas, el puntaje promedio y el conteo por sentimiento."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("SELECT COUNT(*), AVG(puntaje) FROM resenas")
        cantidad, promedio = await cursor.fetchone()

        cursor = await db.execute(
            "SELECT sentimiento, COUNT(*) FROM resenas GROUP BY sentimiento"
        )
        por_sentimiento = dict(await cursor.fetchall())

    return {
        "cantidad": cantidad,
        "promedio": promedio,
        "por_sentimiento": por_sentimiento,
    }


async def guardar_reserva(user_id: int, excursion: str, fecha: str, personas: int) -> int:
    """Guarda una reserva confirmada y devuelve su número identificador."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "INSERT INTO reservas (user_id, excursion, fecha, personas) VALUES (?, ?, ?, ?)",
            (user_id, excursion, fecha, personas),
        )
        await db.commit()
        return cursor.lastrowid