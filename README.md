# OllyBot 🫒

Asistente virtual y sommelier de aceite de oliva virgen extra para **Olear HUB** (Mendoza, Argentina), implementado como bot de Telegram con **Gemini** (`google-genai` Interactions API), herramientas mediante *function calling*, salida estructurada con **Pydantic**, persistencia en **SQLite** y cobros en **Mercado Pago (Sandbox)**.

---

## Funcionalidades actuales (v6)

- **Asesoramiento de sommelier con memoria:** recomienda varietales, maridajes y usos culinarios en español rioplatense recordando los últimos mensajes de cada usuario en SQLite (`olly.db`).
- **Catálogo y existencias en vivo (`consultar_catalogo`):** consulta el catálogo de Olear HUB por varietal, intensidad o stock antes de informar precios, presentaciones o disponibilidad.
- **Generación automática de cobros (`generar_link_pago`):** valida el `producto_id` y el stock contra el backend y crea una preferencia real en **Mercado Pago Checkout Pro (Sandbox)** devolviendo el link de pago.
- **Trazabilidad por lote (`consultar_lote`):** a partir de un código de lote, recupera finca de origen, fechas de cosecha y molienda, método de extracción, acidez y notas de cata.
- **Análisis estructurado de preferencias (`/preferencias` y `/perfiles`):** extrae entidades (`ingredientes`, `tipo_coccion`, `descriptores`, `intensidad_preferida`) y clasifica el `perfil_compra` mediante JSON Schema validado con Pydantic, guardando cada análisis en SQLite para consultar estadísticas agregadas.
- **Módulo Flujo guiado (`/comprar` y `/cancelar`):** conduce la compra paso a paso con botones interactivos inline (`InlineKeyboardMarkup`) e interpretación de cantidades/fechas en lenguaje natural con IA, registrando el pedido en SQLite (`pedidos`) junto con el link de pago de Mercado Pago Sandbox.
- **Módulo Multimodalidad (fotos y notas de voz):** procesa imágenes enviadas por Telegram (platos, botellas o etiquetas) y notas de voz (hasta 60 segundos), integrándolas directamente en la conversación y herramientas de Olly.

---

## Estructura del proyecto

```text
OllyBot/
├── bot.py                  # Punto de entrada, handlers (comandos, multimodalidad) y ciclo de herramientas
├── pedidos.py              # Flujo guiado /comprar con ConversationHandler, botones inline e IA
├── prompts.py              # Prompt de sistema (personalidad, herramientas, multimodalidad y límites)
├── herramientas.py         # Funciones externas (Olear HUB + Mercado Pago), declaraciones y despachador
├── analisis.py             # Esquema Pydantic y función de análisis estructurado de preferencias
├── db.py                   # Esquema y operaciones asíncronas en SQLite (mensajes, preferencias y pedidos)
├── mock_olear.py           # Servidor HTTP local mock de Olear HUB (solo librería estándar de Python)
├── prueba_herramientas.py  # Pruebas aisladas de herramientas y manejo de errores
├── prueba_analisis.py      # Pruebas aisladas del análisis estructurado con Gemini
├── requirements.txt        # Dependencias del proyecto
└── .env.example            # Plantilla de variables de entorno
```

---

## Requisitos previos

- **Python 3.11+** (probado con Python 3.12)
- Token de bot de Telegram obtenido con `@BotFather`
- API key de Gemini (Google AI Studio)
- Access Token de vendedor de prueba en Mercado Pago (Sandbox)

---

## Instalación y configuración

1. **Clonar el repositorio y activar el entorno virtual:**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Configurar variables de entorno:**

   Copiá `.env.example` a `.env` y completá tus credenciales:

   ```env
   TELEGRAM_TOKEN=tu_token_de_telegram
   GEMINI_API_KEY=tu_api_key_de_gemini
   GEMINI_MODEL=gemini-3.5-flash-lite
   MP_ACCESS_TOKEN=tu_access_token_sandbox_de_mercadopago
   OLEAR_API_URL=http://localhost:8000
   ```

   > `.env` y `*.db` están excluidos en `.gitignore` para no subir credenciales ni bases locales al repositorio.

---

## Cómo levantar el bot en local

Mientras el backend online de Olear HUB no esté desplegado, el bot consume el servidor mock local incluido en `mock_olear.py`.

1. **Terminal 1 — Levantar el mock de Olear HUB:**

   ```powershell
   python mock_olear.py
   ```

   Expone en `http://localhost:8000`:
   - `GET /health`
   - `GET /api/catalogo` (acepta `varietal`, `intensidad`, `solo_con_stock` y `q`)
   - `GET /api/productos/<id>`
   - `GET /api/lotes/<codigo>`

   > Cuando el backend real esté en línea, solo hay que actualizar `OLEAR_API_URL` en `.env`.

2. **Terminal 2 — Levantar OllyBot:**

   ```powershell
   python bot.py
   ```

---

## Comandos de Telegram

| Comando | Descripción |
| --- | --- |
| `/start` | Presentación de Olly |
| `/help` | Lista de comandos y capacidades |
| `/comprar` | Flujo guiado de compra paso a paso con botones, fecha de entrega y Mercado Pago |
| `/cancelar` | Cancela un pedido en curso dentro de `/comprar` |
| `/preferencias <texto>` | Analiza ingredientes, cocción, descriptores y perfil de compra y lo guarda en SQLite |
| `/perfiles` | Muestra el resumen estadístico de los análisis guardados |
| `/olvidar` | Borra el historial conversacional del usuario en SQLite |

Para registrar el menú en `@BotFather` con `/setcommands`:

```text
start - Presentación de Olly
help - Lista de comandos
comprar - Armar un pedido paso a paso
cancelar - Cancelar el pedido en curso
preferencias - Analizar tus gustos y perfil de compra
perfiles - Ver el resumen de perfiles analizados
olvidar - Borrar la conversación
```

---

## Pruebas y verificación

### 1. Pruebas aisladas (sin Telegram)

- **Herramientas (catálogo, lote, Mercado Pago Sandbox y errores controlados):**

  ```powershell
  python prueba_herramientas.py
  ```

  *(Si `mock_olear.py` no está ejecutándose en `localhost:8000`, el script levanta una instancia temporal durante la prueba).*

- **Análisis estructurado de preferencias (Gemini + Pydantic):**

  ```powershell
  python prueba_analisis.py
  ```

### 2. Pruebas recomendadas en Telegram

- *«Hola, busco un aceite para una cena con carnes rojas y pastas. ¿Qué tenés y cuánto sale?»* → consulta `consultar_catalogo` y recomienda opciones con precios reales.
- *«Quiero comprar una botella de Arauco Reserva de 500 ml»* → llama a `generar_link_pago` y devuelve el enlace de Checkout Pro Sandbox.
- *«Tengo el código de lote LOT-2026-AR01, ¿de qué finca viene?»* → llama a `consultar_lote` y responde con finca, fecha de molienda y acidez.
- `/preferencias Busco un aceite intenso y picante para carnes rojas a la parrilla` → guarda el análisis estructurado en la tabla `preferencias` de `olly.db`.
- `/perfiles` → devuelve los totales agrupados desde SQLite.
- `/comprar` → elegí producto con los botones, ingresá cantidad (por botón o texto como *«un par»*), elegí fecha (botón o texto como *«el sábado»*) y confirmá para generar el link de pago y guardar la fila en la tabla `pedidos`.
- Enviar una **foto** (por ejemplo de un plato o etiqueta) y una **nota de voz** (< 60 s) para probar multimodalidad en conversación.

### Datos disponibles en el mock para probar

- **Productos:** `arauco-reserva-500` (\$12.500), `arbequina-clasico-500` (\$10.800), `arbequina-clasico-250` (\$6.400), `frantoio-seleccion-500` (\$11.900), `blend-mediterraneo-500` (\$11.200) y `coratina-edicion-limitada-500` (stock `0`, útil para probar faltantes).
- **Lotes:** `LOT-2026-AR01`, `LOT-2026-AQ02`, `LOT-2026-FR03`, `LOT-2026-CO04`, `LOT-2026-BL05`.
