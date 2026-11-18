"""
Servidor mock HTTP local del backend de Olear HUB.

Simula los endpoints de catálogo, productos y trazabilidad de lotes usando
únicamente la librería estándar de Python para no agregar dependencias ni
depender de un despliegue remoto mientras el backend real no esté en línea.

Uso:
    python mock_olear.py
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import unicodedata
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mock_olear")

CATALOGO = [
    {
        "id": "arauco-reserva-500",
        "nombre": "Arauco Reserva",
        "varietal": "Arauco",
        "presentacion_ml": 500,
        "precio_ars": 12500,
        "stock_unidades": 18,
        "intensidad": "intensa",
        "notas_cata": (
            "Frutado verde intenso, con notas de tomate, hierba fresca, "
            "amargo equilibrado y picante persistente."
        ),
        "maridajes": ["carnes rojas", "pastas con salsas intensas", "parrilla", "quesos curados", "guisos"],
        "lote_actual": "LOT-2026-AR01",
    },
    {
        "id": "arbequina-clasico-500",
        "nombre": "Arbequina Clásico",
        "varietal": "Arbequina",
        "presentacion_ml": 500,
        "precio_ars": 10800,
        "stock_unidades": 25,
        "intensidad": "suave",
        "notas_cata": (
            "Frutado maduro suave, aroma a manzana verde, almendra dulce "
            "y banana, sin amargor marcado."
        ),
        "maridajes": ["pescados blancos", "ensaladas verdes", "repostería", "tostadas", "frutas"],
        "lote_actual": "LOT-2026-AQ02",
    },
    {
        "id": "arbequina-clasico-250",
        "nombre": "Arbequina Clásico",
        "varietal": "Arbequina",
        "presentacion_ml": 250,
        "precio_ars": 6400,
        "stock_unidades": 14,
        "intensidad": "suave",
        "notas_cata": (
            "Frutado maduro suave, aroma a manzana verde y almendra dulce, "
            "ideal para uso cotidiano delicado."
        ),
        "maridajes": ["pescados", "ensaladas", "mayonesas caseras", "desayunos"],
        "lote_actual": "LOT-2026-AQ02",
    },
    {
        "id": "frantoio-seleccion-500",
        "nombre": "Frantoio Selección",
        "varietal": "Frantoio",
        "presentacion_ml": 500,
        "precio_ars": 11900,
        "stock_unidades": 11,
        "intensidad": "media",
        "notas_cata": (
            "Perfil medio y elegante, notas herbáceas, alcachofa, "
            "almendra fresca y picor amable en garganta."
        ),
        "maridajes": ["pastas", "verduras grilladas", "risotto", "pollo al horno", "quesos semiduros"],
        "lote_actual": "LOT-2026-FR03",
    },
    {
        "id": "blend-mediterraneo-500",
        "nombre": "Blend Mediterráneo Olear",
        "varietal": "Blend",
        "presentacion_ml": 500,
        "precio_ars": 11200,
        "stock_unidades": 20,
        "intensidad": "media",
        "notas_cata": (
            "Corte equilibrado de Arauco y Arbequina, fresco y versátil "
            "para cocina diaria y terminación de platos."
        ),
        "maridajes": ["pizzas", "vegetales asados", "carnes blancas", "panes artesanales", "cocina diaria"],
        "lote_actual": "LOT-2026-BL05",
    },
    {
        "id": "coratina-edicion-limitada-500",
        "nombre": "Coratina Edición Limitada",
        "varietal": "Coratina",
        "presentacion_ml": 500,
        "precio_ars": 14800,
        "stock_unidades": 0,
        "intensidad": "intensa",
        "notas_cata": (
            "Altos polifenoles, intensidad muy alta, notas de rúcula, "
            "pimienta negra y hoja de olivo."
        ),
        "maridajes": ["bife de chorizo", "cordero", "bruschettas", "legumbres"],
        "lote_actual": "LOT-2026-CO04",
    },
]

LOTES = {
    "LOT-2026-AR01": {
        "codigo_lote": "LOT-2026-AR01",
        "varietal": "Arauco",
        "producto": "Arauco Reserva",
        "finca_origen": "Finca Los Olivos - Maipú, Mendoza",
        "fecha_cosecha": "2026-04-12",
        "fecha_molienda": "2026-04-12",
        "metodo_extraccion": "Extracción en frío (< 24 °C), primera prensa centrífuga",
        "acidez_pct": 0.18,
        "notas_cata": "Frutado verde intenso, hoja de tomate, amargo limpio y picante persistente.",
    },
    "LOT-2026-AQ02": {
        "codigo_lote": "LOT-2026-AQ02",
        "varietal": "Arbequina",
        "producto": "Arbequina Clásico",
        "finca_origen": "Finca Alto Valle - Luján de Cuyo, Mendoza",
        "fecha_cosecha": "2026-04-28",
        "fecha_molienda": "2026-04-29",
        "metodo_extraccion": "Extracción en frío (< 24 °C)",
        "acidez_pct": 0.21,
        "notas_cata": "Frutado dulce y delicado, notas a manzana verde y almendra fresca.",
    },
    "LOT-2026-FR03": {
        "codigo_lote": "LOT-2026-FR03",
        "varietal": "Frantoio",
        "producto": "Frantoio Selección",
        "finca_origen": "Finca Piedra Blanca - San Martín, Mendoza",
        "fecha_cosecha": "2026-04-19",
        "fecha_molienda": "2026-04-19",
        "metodo_extraccion": "Extracción en frío (< 24 °C)",
        "acidez_pct": 0.19,
        "notas_cata": "Herbáceo equilibrado con notas de alcachofa y almendra verde.",
    },
    "LOT-2026-CO04": {
        "codigo_lote": "LOT-2026-CO04",
        "varietal": "Coratina",
        "producto": "Coratina Edición Limitada",
        "finca_origen": "Finca Los Olivos - Maipú, Mendoza",
        "fecha_cosecha": "2026-04-05",
        "fecha_molienda": "2026-04-05",
        "metodo_extraccion": "Extracción en frío (< 22 °C), cosecha temprana",
        "acidez_pct": 0.14,
        "notas_cata": "Muy intenso y rico en polifenoles, con rúcula fresca y pimienta negra.",
    },
    "LOT-2026-BL05": {
        "codigo_lote": "LOT-2026-BL05",
        "varietal": "Blend",
        "producto": "Blend Mediterráneo Olear",
        "finca_origen": "Finca Alto Valle - Luján de Cuyo, Mendoza",
        "fecha_cosecha": "2026-05-03",
        "fecha_molienda": "2026-05-04",
        "metodo_extraccion": "Extracción en frío (< 24 °C)",
        "acidez_pct": 0.22,
        "notas_cata": "Corte armónico Arauco/Arbequina, fresco y balanceado.",
    },
}


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").lower().strip()


def _filtrar_catalogo(parametros: dict[str, list[str]]) -> list[dict]:
    """Aplica filtros opcionales sobre la lista del catálogo."""
    varietal = _normalizar(parametros["varietal"][0]) if "varietal" in parametros else ""
    intensidad = _normalizar(parametros["intensidad"][0]) if "intensidad" in parametros else ""
    solo_stock_raw = _normalizar(parametros.get("solo_con_stock", ["true"])[0])
    solo_con_stock = solo_stock_raw != "false"
    consulta = _normalizar(parametros["q"][0]) if "q" in parametros else ""

    resultados = []
    for producto in CATALOGO:
        if solo_con_stock and producto["stock_unidades"] <= 0:
            continue
        if varietal and varietal not in _normalizar(producto["varietal"]):
            continue
        if intensidad and _normalizar(producto["intensidad"]) != intensidad:
            continue
        if consulta:
            texto_busqueda = _normalizar(
                f"{producto['nombre']} {producto['varietal']} {producto['notas_cata']} "
                f"{' '.join(producto['maridajes'])}"
            )
            if consulta not in texto_busqueda:
                continue
        resultados.append(producto)
    return resultados


class OlearMockHandler(BaseHTTPRequestHandler):
    """Atiende las peticiones HTTP GET del mock de Olear HUB."""

    def _enviar_json(self, codigo: int, payload: dict) -> None:
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        ruta = url.path.rstrip("/") or "/"
        parametros = parse_qs(url.query)

        if ruta == "/health":
            self._enviar_json(200, {"status": "ok", "servicio": "Olear HUB Mock"})
            return

        if ruta == "/api/catalogo":
            productos = _filtrar_catalogo(parametros)
            self._enviar_json(200, {"total": len(productos), "productos": productos})
            return

        if ruta.startswith("/api/productos/"):
            producto_id = ruta.removeprefix("/api/productos/").strip("/")
            for producto in CATALOGO:
                if producto["id"] == producto_id:
                    self._enviar_json(200, producto)
                    return
            self._enviar_json(404, {"error": f"Producto no encontrado: {producto_id}"})
            return

        if ruta.startswith("/api/lotes/"):
            codigo = ruta.removeprefix("/api/lotes/").strip("/").upper()
            lote = LOTES.get(codigo)
            if lote is None:
                self._enviar_json(404, {"error": f"Lote no encontrado: {codigo}"})
                return
            self._enviar_json(200, lote)
            return

        self._enviar_json(404, {"error": f"Ruta no encontrada: {ruta}"})


def crear_servidor(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Crea la instancia del servidor HTTP sin bloquear el hilo actual."""
    return ThreadingHTTPServer((host, port), OlearMockHandler)


def main() -> None:
    url = urlparse(os.getenv("OLEAR_API_URL", "http://localhost:8000"))
    host = url.hostname or "127.0.0.1"
    port = url.port or 8000
    servidor = crear_servidor(host, port)
    logger.info("Olear HUB Mock escuchando en http://%s:%d", host, port)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        logger.info("Deteniendo Olear HUB Mock...")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
