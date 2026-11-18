"""
Prueba aislada de las herramientas, sin Telegram ni Gemini.

Llama a cada función directamente (catálogo, trazabilidad de lote y generación
de preferencia en Mercado Pago Sandbox) y verifica que los errores se devuelvan
como diccionarios con la clave "error" sin lanzar excepciones.

Si OLEAR_API_URL apunta a localhost y no hay un servidor escuchando, inicia
temporalmente el mock local durante la prueba.
"""

import asyncio
import json
import os
import threading
from urllib.parse import urlparse

import httpx

from herramientas import (
    consultar_catalogo,
    consultar_lote,
    ejecutar_funcion,
    generar_link_pago,
)
import mock_olear


def _asegurar_mock_local():
    """Si el backend local no está activo en localhost, levanta un servidor temporal."""
    url = os.getenv("OLEAR_API_URL", "http://localhost:8000").rstrip("/")
    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return None
    try:
        resp = httpx.get(f"{url}/health", timeout=1.5)
        if resp.status_code == 200:
            return None
    except httpx.HTTPError:
        pass

    servidor = mock_olear.crear_servidor(parsed.hostname or "127.0.0.1", parsed.port or 8000)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    print(f"[info] Mock local iniciado temporalmente en {url}")
    return servidor


async def main() -> None:
    servidor = _asegurar_mock_local()
    try:
        print("--- 1. Catálogo (intensidad intensa, con stock) ---")
        print(json.dumps(await consultar_catalogo(intensidad="intensa"), ensure_ascii=False, indent=2))

        print("\n--- 2. Trazabilidad de lote ---")
        print(json.dumps(await consultar_lote("LOT-2026-AR01"), ensure_ascii=False, indent=2))

        print("\n--- 3. Link de pago en Mercado Pago Sandbox ---")
        print(json.dumps(await generar_link_pago("arauco-reserva-500", 1), ensure_ascii=False, indent=2))

        print("\n--- 4. Casos de error controlados (deben devolver 'error') ---")
        print("Varietal inexistente:", await consultar_catalogo(varietal="Picual"))
        print("Intensidad inválida:", await consultar_catalogo(intensidad="extremadamente fuerte"))
        print("Lote inexistente:", await consultar_lote("LOT-9999-XX"))
        print("Producto sin stock:", await generar_link_pago("coratina-edicion-limitada-500", 1))
        print("Stock insuficiente:", await generar_link_pago("frantoio-seleccion-500", 15))
        print("Cantidad fuera de rango:", await generar_link_pago("arauco-reserva-500", 999))
        print("Producto inexistente:", await generar_link_pago("inexistente-500", 1))
        print("Función desconocida:", await ejecutar_funcion("funcion_inexistente", {}))
    finally:
        if servidor is not None:
            servidor.shutdown()
            servidor.server_close()


if __name__ == "__main__":
    asyncio.run(main())
