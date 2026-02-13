import asyncio
import sys
import logging
import json
import os
import re
import pandas as pd
from fastapi.responses import StreamingResponse
from urllib.parse import urlparse, urljoin
import uvicorn
import time
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from decimal import Decimal
import importlib.util
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

# Cargar variables de entorno
load_dotenv()

try:
    from stagehand import Stagehand
except ImportError:
    Stagehand = None

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

frontend_port = os.getenv("FRONTEND_PORT", "8501")
origins = [f"http://localhost:{frontend_port}", f"http://127.0.0.1:{frontend_port}", "*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DATA_FILE = os.path.abspath(os.path.join("data", "publicaciones.json"))
MAP_FILE = os.path.abspath(os.path.join("data", "navigation_map.json"))

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    version: str
    km_max: int
    api_key: str
    patente: str = None
    headless: bool = False

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "valuador_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "password")
    )

def get_latest_dollar_from_db():
    """Recupera el último valor del dólar guardado en la base de datos."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT venta FROM dolar_value WHERE casa = 'oficial' ORDER BY fecha_carga DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return float(row[0]) if row else None
    except Exception as e:
        logger.error(f"❌ Error obteniendo dólar de DB: {e}")
        return None

def save_dollars_to_db(dollar_list):
    """Guarda todos los tipos de dólar en la tabla dolar_value."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        insert_query = """
            INSERT INTO dolar_value (casa, nombre, compra, venta, fecha_actualizacion)
            VALUES %s
        """
        values = [
            (d.get('casa'), d.get('nombre'), d.get('compra'), d.get('venta'), d.get('fechaActualizacion'))
            for d in dollar_list
        ]
        execute_values(cur, insert_query, values)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error guardando dólar en DB: {e}")

async def get_exchange_rate():
    """Obtiene el valor del dólar oficial (venta) desde la API o el último guardado en DB."""
    url = "https://dolarapi.com/v1/dolares"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                # Guardamos todos los tipos de dólar recibidos para historial
                save_dollars_to_db(data)
                
                oficial = next((d for d in data if d.get('casa') == 'oficial'), None)
                if oficial:
                    return float(oficial.get("venta"))
        raise Exception("Falla en la respuesta de la API")
    except Exception as e:
        logger.error(f"⚠️ Error API Dólar: {e}. Buscando respaldo en DB...")
        valor_db = get_latest_dollar_from_db()
        if valor_db: return valor_db
        logger.error("🚨 Sin respaldo de dólar. Usando 1.0 como fallback.")
        return 1.0

def save_to_db(extracted_data, stats, domain, request_data, progress_callback=None):
    """Persiste los datos en PostgreSQL: tabla transaccional y tabla de resultados."""
    updated_stock = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Tabla Transaccional: extractions
        if extracted_data:
            insert_query = """
                INSERT INTO extractions (brand, model, version, year, km, price, currency, title, combustible, transmision, zona, fecha_publicacion, reservado, url, site)
                VALUES %s
            """
            values = [
                (
                    item.get('brand'), item.get('model'), item.get('version'), item.get('year'), item.get('km'), 
                    item.get('price'), item.get('currency'), item.get('title'), item.get('combustible'), 
                    item.get('transmision'), item.get('zona'), item.get('fecha_publicacion'), 
                    item.get('reservado'), item.get('url'), domain
                ) for item in extracted_data
            ]
            execute_values(cur, insert_query, values)

        # 2. Tabla de Resultados: stock_comparison
        site_map = {"kavak": "kavak", "mercadolibre": "meli", "tiendacars": "tienda_cars", "motormax": "motor_max", "autocity": "auto_city", "randazzo": "randazzo"}
        col = next((v for k, v in site_map.items() if k in domain), None)
        
        if col:
            avg_price = stats.get("average_price", 0)
            # Reconstruimos el modelo como se guarda en la DB: "MODELO - VERSION"
            db_modelo = f"{request_data.model} - {request_data.version}"
            
            # Update the specific site price
            update_site_query = f"UPDATE stock_comparison SET {col} = %s WHERE marca = %s AND modelo = %s AND anio = %s"
            cur.execute(update_site_query, (avg_price, request_data.brand, db_modelo, request_data.year))
            
            # Fetch records to perform calculations
            select_query = "SELECT * FROM stock_comparison WHERE marca = %s AND modelo = %s AND anio = %s"
            cur.execute(select_query, (request_data.brand, db_modelo, request_data.year))
            rows = cur.fetchall()
            
            for row in rows:
                # Calculations
                meli = float(row['meli'] or 0)
                kavak = float(row['kavak'] or 0)
                precio_toma = float(row['precio_toma'] or 0)
                precio_venta = float(row['precio_venta'] or 0)
                ancianidad = float(row['ancianidad_actualizada'] or 0)
                anio = int(row['anio'])
                km = int(row['km'] or 0)
                
                # PRECIO MERCADO (Columna PM) = PROMEDIO(Meli + kavak) rounded to 4 decimals
                # ignore 0 or null
                prices = [p for p in [meli, kavak] if p > 0]
                pm = round(sum(prices) / len(prices), 4) if prices else 0
                
                # MARGEN % HISTORICO DE COSTO Y PM = (pm - precio_toma) / pm
                margen_hist = (pm - precio_toma) / pm if pm > 0 else 0
                
                # MARGEN INDEXADO DE COSTO Y PM = (pm - ancianidad) / pm
                margen_idx = (pm - ancianidad) / pm if pm > 0 else 0
                
                # DIF % PV CO y Kavak = 1 - (precio_venta / kavak)
                dif_pv_kavak = 1 - (precio_venta / kavak) if kavak > 0 else 0
                
                # CUENTA = (((2024 - anio) * 15000) - km) / 5000 * 0.75%
                cuenta = (((2024 - anio) * 15000) - km) / 5000.0 * 0.0075
                
                # Update the record
                update_calc_query = """
                    UPDATE stock_comparison 
                    SET pm = %s, margen_hist_costo_pm = %s, margen_idx_costo_pm = %s, dif_pv_co_kavak = %s, cuenta = %s
                    WHERE patente = %s
                """
                cur.execute(update_calc_query, (pm, margen_hist, margen_idx, dif_pv_kavak, cuenta, row['patente']))
                
                msg = (f"📈 Cálculos para {row['patente']} ({row['marca']} {row['modelo']}):\n"
                       f"   - PM: ${pm:,.2f}\n"
                       f"   - Margen Hist: {margen_hist:.2%}\n"
                       f"   - Margen Idx: {margen_idx:.2%}\n"
                       f"   - Dif PV/Kavak: {dif_pv_kavak:.2%}\n"
                       f"   - Cuenta: {cuenta:.4f}")
                
                if progress_callback:
                    progress_callback(msg)
                else:
                    logger.info(msg)
            
            # Recuperar el estado final de los registros actualizados para devolver al frontend
            cur.execute("SELECT * FROM stock_comparison WHERE marca = %s AND modelo = %s AND anio = %s", 
                        (request_data.brand, db_modelo, request_data.year))
            updated_stock = cur.fetchall()

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Datos persistidos y cálculos actualizados en PostgreSQL correctamente.")
        return updated_stock
    except Exception as e:
        logger.error(f"❌ Error persistiendo en DB: {e}")
        return []

def load_scraper_module(file_name):
    """Carga dinámicamente un módulo de scraping desde un archivo."""
    path = os.path.join(os.path.dirname(__file__), file_name)
    spec = importlib.util.spec_from_file_location(file_name.replace(" ", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def get_full_navigation_instruction(domain: str, brand: str, model: str, year: int) -> str:
    """
    Genera la instrucción completa y robusta para el agente de IA.
    """
    base_instr = ""
    
    if "kavak" in domain:
        return base_instr + (
            "1. Si aparece un cartel de cookies o selección de país/región, acéptalo o ciérralo.\n"
            "2. Asegúrate de estar en la sección de compra de autos o categoria de Vehiculos (Marketplace). Si estás en la home, busca el botón 'Comprar un auto', Categoria 'Vehiculos' o similar.\n"
            "3. Verificar si se observan los filtros de búsqueda, en caso de que no se hallen hacer clic en la barra de búsqueda (entry point) para ver filtros si corresponde CASO CONTRARIO NO HACER NADA.\n"
            "REGLA CRÍTICA: Si no encuentras el valor exacto solicitado para CUALQUIERA de los filtros (Marca, Modelo, etc.), DETÉN el proceso inmediatamente. No intentes seleccionar valores similares ni continúes con el resto de los pasos.\n"
            f"4. Aplica los filtros: Marca (puede tener otros nombres considerar todas las variantes posibles): '{brand}', Modelo (puede tener otros nombres considerar todas las variantes posibles): '{model}', Año (puede tener otros nombres considerar todas las variantes posibles): '{year}' y Disponibilidad de auto (puede tener otros nombres considerar todas las variantes posibles): 'Disponible' (o similar). Los filtros pueden aparecer como botones, enlaces o listas desplegables. Busca específicamente el botón o enlace con el texto '{year}'. Si no lo ves, expande la sección correspondiente o busca un botón de 'Ver más'.\n"
            "6. Ordenar las publicaciones por 'Relevancia'.\n"
            "7. Haz scroll para cargar los resultados."
        )
    elif "mercadolibre" in domain:
        return base_instr + (
                f"""OBJETIVO: Encontrar un vehículo {brand} {model} usado del año {year}, evitando accesorios o repuestos.

                PASOS:
                1. BÚSQUEDA INICIAL: Localiza el buscador principal en la parte superior (header) y escribe '{brand} {model}'. Presiona Enter o haz clic en la lupa para buscar.

                2. FILTRO DE CONDICIÓN: En la barra lateral, busca la sección de 'Condición' y selecciona específicamente 'Usado'.

                3. FILTRO DE AÑO: Busca la sección 'Año' en los filtros laterales.
                - Selecciona exactamente el año '{year}'. 
                - Si no ves el año '{year}' en la lista, haz clic en 'Mostrar más' o 'Ver todos' dentro de esa sección hasta encontrarlo.

                4. VERIFICACIÓN FINAL: 
                - Si aparece un mensaje de 'No hay publicaciones que coincidan', informa 'Sin stock'.
                - Si hay resultados, realiza un scroll suave para asegurar que se carguen las unidades y confirma que el catálogo sea de vehículos reales.
                """      )
    else:
        return base_instr + f"4. Busca y filtra por Marca '{brand}', Modelo '{model}' y Año '{year}'.\n5. Haz scroll para cargar resultados."

@app.get("/stock")
async def get_stock():
    """Obtiene la lista de vehículos en stock."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT patente, marca, modelo, anio, km, precio_venta FROM stock_comparison ORDER BY marca, modelo")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Scraping Optimizado: {request.brand} {request.model} ({request.year})")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    model_name = "google/gemini-2.5-flash"  # Modelo optimizado para tareas de navegación y extracción con contexto amplio
    
    async def event_generator():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        extracted_data = []

        def log_status(msg):
            # Mantenemos los mensajes por terminal
            logger.info(msg)
            # Enviamos al frontend de forma segura entre hilos
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "status", "message": msg})

        # 1. Obtener tipo de cambio
        log_status(f"🚀 Iniciando proceso para {request.brand} {request.model} {request.year}...")
        log_status("💵 Obteniendo tipo de cambio actualizado...")
        exchange_rate = await get_exchange_rate()
        log_status(f"✅ Tipo de cambio: {exchange_rate} ARS/USD")

        def run_stagehand_logic(progress_callback):
            # Extraer el dominio dinámicamente de la URL solicitada
            parsed_url = urlparse(request.url)
            domain = parsed_url.netloc.replace("www.", "")
            
            # --- NAVEGACIÓN ASISTIDA POR IA (Stagehand) ---
            progress_callback(f"🌐 Iniciando navegador local en modo {'oculto' if request.headless else 'visible'}...")
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=request.headless,
                local_ready_timeout_s=20.0, 
                timeout=300.0
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {"headless": request.headless}},
            )
            sess_id = session.data.session_id
            
            client_sync.sessions.navigate(id=sess_id, url=request.url)

            instruction = get_full_navigation_instruction(domain, request.brand, request.model, request.year)
            
            progress_callback(f"🤖 Agente IA navegando en {domain}...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": instruction,
                    "max_steps": 20,
                },
                agent_config={"model": {"model_name": model_name}},
            )

            # Verificación rápida de resultados para detener el proceso si no hay nada
            progress_callback("🧐 Verificando si existen resultados de búsqueda...")
            check_result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Analiza la página actual. ¿Se aplicaron correctamente los filtros de Marca (puede tener otros nombres considerar todas las variantes posibles): '{request.brand}', Modelo  (puede tener otros nombres considerar todas las variantes posibles): '{request.model}' y Año  (puede tener otros nombres considerar todas las variantes posibles): '{request.year}'? ¿La página muestra resultados que coinciden con estos filtros, o muestra un mensaje de '0 resultados' o 'No se encontraron vehículos'? Responde false si los filtros no se aplicaron correctamente o si no hay resultados que coincidan con la búsqueda.",
                schema={"type": "object", "properties": {"has_results": {"type": "boolean"}}}
            )
            
            if not check_result.data.result.get("has_results", False):
                progress_callback("❌ No se encontraron resultados para los filtros aplicados. Deteniendo proceso.")
                client_sync.sessions.end(id=sess_id)
                client_sync.close()
                return "NO_RESULTS"

            # Si hay resultados, capturamos la URL actual con filtros aplicados y continuamos
            url_res = client_sync.sessions.extract(
                id=sess_id,
                instruction="Obtén la URL actual de la página.",
                schema={"type": "object", "properties": {"url": {"type": "string","format": "uri"}}}
            )
            current_url = url_res.data.result.get("url", request.url)
            progress_callback("✅ Resultados confirmados. Iniciando extracción detallada...")

            # --- EXTRACCIÓN DETALLADA (Navegando a cada publicación) ---
            all_extracted_items = []
            max_pubs = 5  # Límite heredado a los módulos
            
            if "kavak" in domain:
                kavak_module = load_scraper_module("prueba scrap kavak.py")
                all_extracted_items = kavak_module.extract_kavak_details(
                    client_sync, sess_id, current_url, max_pubs, request.version, model_name, progress_callback=progress_callback
                )
            elif "mercadolibre" in domain:
                meli_module = load_scraper_module("prueba scrap meli.py")
                all_extracted_items = meli_module.extract_meli_details(
                    client_sync, sess_id, current_url, max_pubs, request.version, model_name, progress_callback=progress_callback
                )
            else:
                progress_callback(f"⚠️ El sitio {domain} no está soportado para extracción detallada.")
                logger.warning(f"⚠️ Dominio {domain} no soportado.")

            client_sync.sessions.end(id=sess_id)
            client_sync.close()

            if not all_extracted_items:
                progress_callback("⚠️ No se extrajeron publicaciones válidas después de filtrar.")

            return {"autos": all_extracted_items}

        try:
            # Ejecutar lógica en hilo y capturar mensajes
            task = asyncio.create_task(asyncio.to_thread(run_stagehand_logic, log_status))
            
            while not task.done() or not queue.empty():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield json.dumps(msg) + "\n"
                except asyncio.TimeoutError:
                    continue

            raw_results = await task
            
            if raw_results == "NO_RESULTS":
                log_status("⚠️ No se hallaron resultados que coincidan con los criterios de búsqueda.")
                yield json.dumps({"type": "final", "status": "empty", "message": "No se hallaron valores."}) + "\n"
                return

            # PROCESAMIENTO RÁPIDO Y ROBUSTO
            log_status("📊 Procesando datos extraídos y calculando estadísticas...")
            items = []
            if isinstance(raw_results, str):
                clean_json = raw_results
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0]
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0]
                items = json.loads(clean_json.strip())
            else:
                items = raw_results

            # Extraer lista del objeto Schema
            if isinstance(items, dict) and 'autos' in items:
                items = items['autos']
            elif isinstance(items, dict):
                # Fallback por si la IA ignoró el nombre de la llave del schema
                for key in ['autos', 'cars', 'results', 'data']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): items = [items]
            
            if isinstance(items, list):
                log_status(f"📝 Limpiando y formateando {len(items)} publicaciones halladas...")
                for item in items:
                    try:
                        def clean_num(v):
                            if v is None: return 0.0
                            s = "".join(c for c in str(v).replace(',', '.') if c.isdigit() or c == '.')
                            try:
                                return float(s) if s else 0.0
                            except: return 0.0

                        price = clean_num(item.get('precio', item.get('price', item.get('precio_contado', 0))))
                        currency = str(item.get('moneda', item.get('currency', 'ARS'))).upper()
                        
                        # Calculamos el valor en ARS para estadísticas, pero mantenemos el original para la BD
                        price_ars = price * exchange_rate if currency == 'USD' else price

                        km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                        year = int(clean_num(item.get('año', item.get('year', request.year))))

                        # Reconstrucción de link
                        raw_link = str(item.get('link', item.get('url', '')))
                        
                        full_link = urljoin("https://www.kavak.com", raw_link) if "kavak" in request.url else urljoin(request.url, raw_link)

                        site_name = "Kavak" if "kavak" in request.url else "Mercado Libre"

                        extracted_data.append({
                            "brand": str(item.get('marca', item.get('brand', request.brand))),
                            "model": str(item.get('modelo', item.get('model', request.model))),
                            "version": str(item.get('version', 'N/A')),
                            "year": year, 
                            "km": km, 
                            "price": price,
                            "currency": currency,
                            "price_ars": price_ars,
                            "title": str(item.get('titulo', item.get('title', 'N/A'))),
                            "combustible": str(item.get('combustible', 'N/A')),
                            "transmision": str(item.get('transmision', 'N/A')),
                            "zona": str(item.get('zona', item.get('ubicacion', 'N/A'))),
                            "fecha_publicacion": str(item.get('fecha_publicacion', 'N/A')),
                            "reservado": bool(item.get('reservado', False)),
                            "url": full_link,
                            "site": site_name
                        })
                    except: continue

            # Respuesta Final
            if extracted_data:
                df = pd.DataFrame(extracted_data)
                
                if not df.empty:
                    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
                    all_data = []
                    if os.path.exists(DATA_FILE):
                        try:
                            with open(DATA_FILE, "r") as f: all_data = json.load(f)
                        except: pass
                    all_data.extend(df.to_dict('records'))
                    with open(DATA_FILE, "w") as f: json.dump(all_data, f, indent=4)
                    
                    res_stats = {
                        "average_price": float(df[df['price_ars'] > 0]['price_ars'].mean()) if not df[df['price_ars'] > 0].empty else 0.0, 
                        "count": len(df)
                    }

                    # Persistencia en DB
                    parsed_url = urlparse(request.url)
                    domain = parsed_url.netloc.replace("www.", "")
                    updated_stock = save_to_db(extracted_data, res_stats, domain, request, progress_callback=log_status)
                    log_status("✨ Proceso de guardado y análisis finalizado correctamente.")

                    # Helper para serializar Decimals de la base de datos
                    def decimal_default(obj):
                        if isinstance(obj, Decimal):
                            return float(obj)
                        raise TypeError

                    yield json.dumps({
                        "type": "final",
                        "status": "success", "data": df.to_dict('records'),
                        "stats": res_stats,
                        "updated_stock": updated_stock,
                        "message": f"Se extrajeron {len(df)} publicaciones exitosamente."
                    }, default=decimal_default) + "\n"
                else:
                    yield json.dumps({"type": "final", "status": "empty", "message": "No se encontraron publicaciones válidas."}) + "\n"
            else:
                yield json.dumps({"type": "final", "status": "empty", "message": "No se encontraron publicaciones válidas."}) + "\n"

        except Exception as e:
            logger.error(f"❌ Error en el proceso de scraping: {e}")
            yield json.dumps({"type": "final", "status": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)