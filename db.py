"""
Memoria de Olly: historial de conversación en SQLite.

Cada mensaje (del usuario o del modelo) se guarda como una fila de la tabla
`mensajes`. Se utiliza aiosqlite, la versión asíncrona de sqlite3, para que
las operaciones sobre la base no bloqueen al bot mientras atiende a otros
usuarios.
"""

import json  # convierte listas de ingredientes y descriptores a texto para guardarlas

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

-- Preferencias y entidades gastronómicas extraídas con salida estructurada (v5).
CREATE TABLE IF NOT EXISTS preferencias (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL,
    texto                TEXT    NOT NULL,
    ingredientes         TEXT    NOT NULL,               -- lista guardada como JSON
    tipo_coccion         TEXT    NOT NULL,
    descriptores         TEXT    NOT NULL,               -- lista guardada como JSON
    intensidad_preferida TEXT    NOT NULL,
    perfil_compra        TEXT    NOT NULL,
    resumen              TEXT    NOT NULL,
    fecha                TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_preferencias_usuario ON preferencias (user_id, id);
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


async def guardar_preferencias(user_id: int, texto: str, analisis) -> None:
    """Guarda una consulta junto con su análisis estructurado (AnalisisPreferencias)."""
    async with aiosqlite.connect(RUTA_DB) as db:
        await db.execute(
            "INSERT INTO preferencias "
            "(user_id, texto, ingredientes, tipo_coccion, descriptores, "
            "intensidad_preferida, perfil_compra, resumen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                texto,
                json.dumps(analisis.ingredientes, ensure_ascii=False),
                analisis.tipo_coccion,
                json.dumps(analisis.descriptores, ensure_ascii=False),
                analisis.intensidad_preferida,
                analisis.perfil_compra,
                analisis.resumen,
            ),
        )
        await db.commit()


async def obtener_ultima_preferencia(user_id: int) -> dict | None:
    """Devuelve el último perfil analizado del usuario, o None si aún no tiene."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute(
            "SELECT ingredientes, tipo_coccion, descriptores, intensidad_preferida, "
            "perfil_compra, resumen, fecha "
            "FROM preferencias WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        fila = await cursor.fetchone()
    if fila is None:
        return None
    return {
        "ingredientes": json.loads(fila[0]),
        "tipo_coccion": fila[1],
        "descriptores": json.loads(fila[2]),
        "intensidad_preferida": fila[3],
        "perfil_compra": fila[4],
        "resumen": fila[5],
        "fecha": fila[6],
    }


async def resumen_preferencias() -> dict:
    """Devuelve el total de análisis y el conteo agrupado por perfil e intensidad."""
    async with aiosqlite.connect(RUTA_DB) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM preferencias")
        (cantidad,) = await cursor.fetchone()

        cursor = await db.execute(
            "SELECT perfil_compra, COUNT(*) FROM preferencias GROUP BY perfil_compra"
        )
        por_perfil = dict(await cursor.fetchall())

        cursor = await db.execute(
            "SELECT intensidad_preferida, COUNT(*) FROM preferencias GROUP BY intensidad_preferida"
        )
        por_intensidad = dict(await cursor.fetchall())

        cursor = await db.execute(
            "SELECT tipo_coccion, COUNT(*) FROM preferencias GROUP BY tipo_coccion"
        )
        por_coccion = dict(await cursor.fetchall())

    return {
        "cantidad": cantidad,
        "por_perfil": por_perfil,
        "por_intensidad": por_intensidad,
        "por_coccion": por_coccion,
    }
