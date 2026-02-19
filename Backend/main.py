import asyncio
import sys
import logging
from typing import List
import json
import traceback
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
from datetime import date, timedelta, datetime
import calendar
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
    sites: List[str]
    brand: str
    model: str
    year: int
    version: str
    km_max: int
    api_key: str
    patente: str = None
    headless: bool = False

class InstructionUpdate(BaseModel):
    site_key: str
    navigation_instruction: str
    listing_instruction: str = None
    interaction_instruction: str = None
    extraction_instruction: str
    validation_rules: dict
    extraction_schema: dict
    steps: List[dict] = None
    is_active: bool = True

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

# Clase auxiliar para permitir acceso con punto {item.titulo} en las instrucciones
class ItemWrapper:
    def __init__(self, data):
        self._data = data
    def __getitem__(self, key):
        return self._data.get(key, "")
    def __getattr__(self, key):
        return self._data.get(key, "")
    def get(self, key, default=None):
        return self._data.get(key, default)

def clean_num(v):
    if v is None: return 0.0
    s = "".join(c for c in str(v).replace(',', '.') if c.isdigit() or c == '.')
    try:
        return float(s) if s else 0.0
    except: return 0.0

async def execute_steps(client, session_id, steps, context, log_callback, model_name):
    """Motor de ejecución de pasos secuenciales."""
    extracted_results = []
    
    for i, step in enumerate(steps):
        step_type = step.get("type")
        log_callback(f"👣 Paso {i+1}: {step_type.upper()}")
        
        try:
            if step_type == "navigate":
                url = step.get("url", "").format(**context)
                log_callback(f"🌐 Navegando a: {url}")
                client.sessions.navigate(id=session_id, url=url)
                
            elif step_type == "action":
                instruction = step.get("instruction", "").format(**context)
                log_callback(f"🤖 Acción: {instruction}")
                client.sessions.execute(
                    id=session_id, 
                    execute_options={"instruction": instruction},
                    agent_config={"model": {"model_name": model_name}}
                )
                
            elif step_type == "extract":
                instruction = step.get("instruction", "").format(**context)
                schema = step.get("schema", {})
                log_callback(f"📄 Extrayendo datos...")
                res = client.sessions.extract(id=session_id, instruction=instruction, schema=schema)
                data = res.data.result
                
                # Si es una variable intermedia
                if step.get("variable"):
                    context[step.get("variable")] = data
                    log_callback(f"💾 Dato guardado en variable '{step.get('variable')}'")
                else:
                    # Si es dato final, lo acumulamos
                    if isinstance(data, list): extracted_results.extend(data)
                    else: extracted_results.append(data)
                    
            elif step_type == "validate":
                instruction = step.get("instruction", "").format(**context)
                schema = step.get("schema", {})
                check_field = step.get("exit_on_false")
                
                res = client.sessions.extract(id=session_id, instruction=instruction, schema=schema)
                if check_field and not res.data.result.get(check_field):
                    log_callback(f"⛔ Validación fallida ({check_field}=False). Deteniendo proceso.")
                    return extracted_results # Salir del proceso
            
            elif step_type == "iterator":
                instruction = step.get("instruction", "").format(**context)
                limit = int(step.get("limit", 5))
                sub_steps = step.get("steps", [])
                schema = step.get("schema", {})
                
                log_callback(f"🔄 Iterando: {instruction} (Límite: {limit})")
                res = client.sessions.extract(id=session_id, instruction=instruction, schema=schema)
                data = res.data.result
                
                items = []
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, list): items = v; break
                elif isinstance(data, list): items = data
                
                items = items[:limit]
                log_callback(f"📊 Encontrados {len(items)} elementos.")
                
                for idx, item in enumerate(items):
                    log_callback(f"  ▶️ Procesando item {idx+1}/{len(items)}")
                    item_ctx = {**context, "item": ItemWrapper(item)}
                    
                    # Ejecutar sub-pasos recursivamente
                    sub_results = await execute_steps(client, session_id, sub_steps, item_ctx, log_callback, model_name)
                    
                    if sub_results:
                        for s_res in sub_results:
                            if isinstance(s_res, dict):
                                extracted_results.append({**item, **s_res})
                            else:
                                extracted_results.append(s_res)
                    else:
                        extracted_results.append(item)
                    
            elif step_type == "wait":
                sec = step.get("seconds", 1)
                log_callback(f"⏳ Esperando {sec} segundos...")
                time.sleep(sec)
                
        except Exception as e:
            log_callback(f"❌ Error en paso {i+1}: {str(e)}")
            logger.error(traceback.format_exc())
            
    return extracted_results

def save_to_db(extracted_data, site_averages, request_data, progress_callback=None):
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
                    item.get('reservado'), item.get('url'), item.get('site')
                ) for item in extracted_data
            ]
            execute_values(cur, insert_query, values)

        # 2. Tabla de Resultados: PreciosAutosUsados
        if request_data.patente:
            # Obtener datos de stock_usados como referencia
            cur.execute("SELECT * FROM stock_usados WHERE Patente = %s", (request_data.patente,))
            stock_car = cur.fetchone()
            
            if stock_car:
                # Fechas de ejecución
                today = date.today()
                sunday = today - timedelta(days=(today.weekday() + 1) % 7)
                semana_ejecucion = sunday.strftime("%Y-%m-%d")
                id_transaccion = f"{request_data.patente}_{semana_ejecucion}"
                
                # Obtener registro previo si existe en la misma semana
                cur.execute("SELECT * FROM PreciosAutosUsados WHERE ID = %s", (id_transaccion,))
                prev = cur.fetchone()
                
                # Consolidar promedios: Priorizar nuevos resultados, sino mantener previos
                meli = site_averages.get("mercadolibre", float(prev['meli'] or 0) if prev else 0)
                kavak = site_averages.get("kavak", float(prev['kavak'] or 0) if prev else 0)
                tiendacars = site_averages.get("tiendacars", float(prev['tiendacars'] or 0) if prev else 0)
                motormax = site_averages.get("motormax", float(prev['motormax'] or 0) if prev else 0)
                autocity = site_averages.get("autocity", float(prev['autocity'] or 0) if prev else 0)
                randazzo = site_averages.get("randazzo", float(prev['randazzo'] or 0) if prev else 0)

                precio_toma = float(stock_car['preciodetoma'] or 0)
                costos_reparaciones = float(stock_car['costosreparaciones'] or 0)
                precio_toma_total = precio_toma + costos_reparaciones
                
                indice_mensual = float(stock_car['indice'] or 0)
                days_in_month = calendar.monthrange(today.year, today.month)[1]
                indice_diario = indice_mensual / days_in_month
                
                dias_lote = int(stock_car['diaslote'] or 0)

                # Precio Propuesto (Promedio de sitios con valor > 0)
                site_prices = [p for p in [meli, kavak, tiendacars, motormax, autocity, randazzo] if p > 0]
                precio_propuesto = round(sum(site_prices) / len(site_prices), 2) if site_prices else 0
                
                precio_de_lista = float(stock_car['preciodelista'] or 0)
                precio_de_venta = float(stock_car['preciodeventa'] or 0)
                
                # --- CÁLCULOS DE NEGOCIO ---
                margen_hist_compra = (precio_propuesto - precio_toma_total) / precio_propuesto if precio_propuesto > 0 else 0
                
                dias_calc = max(dias_lote, 45)
                costo_45_dias = float(precio_toma_total * ((indice_diario * dias_calc) / 100 + 1))
                
                dif_pp_pe = 1 - (precio_propuesto / precio_de_lista) if precio_de_lista > 0 else 0
                margen_hist_costo_pe = (precio_de_lista - precio_toma_total) / precio_de_lista if precio_de_lista > 0 else 0
                descuento_recargos = precio_de_venta - precio_de_lista
                
                # Margen Indexado de Costo y Valor de Venta
                margen_idx_costo_venta = (descuento_recargos - precio_de_lista) / descuento_recargos if descuento_recargos != 0 else 0
                
                # Diferencia ASOFIX y PE
                valor_asofix = float(prev['valor_propuesto_por_asofix'] or 0) if prev else 0
                dif_asofix_pe = 1 - (valor_asofix / precio_de_lista) if precio_de_lista > 0 else 0
                
                # Valor de Toma a X días
                valor_toma_x_dias = float(precio_toma_total * (1 + (indice_diario * dif_asofix_pe) / 100))
                
                cuenta = (((2024 - int(stock_car['anio'])) * 15000) - int(stock_car['km'] or 0)) / 5000.0 * 0.0075
                
                # Costo Indexado a X días de Venta
                costo_idx_venta_days = float(precio_toma_total * (1 + (0.04 / 30) * dias_lote))
                
                # Margen Indexado de Costo
                margen_idx_costo = (descuento_recargos - costo_idx_venta_days) / descuento_recargos if descuento_recargos != 0 else 0

                upsert_query = """
                    INSERT INTO PreciosAutosUsados (
                        ID, Patente, Marca, Modelo, Anio, km, Color, Chasis, CotizacionNro, Ubicacion, 
                        CanalDeVenta, PrecioDeLista, PrecioDeToma, DiasLote, FechaIngreso, Sucursal, 
                        CostosReparaciones, PrecioDeTomaTotal_ReparacionesMariano, Indice, 
                        Costo_a_45_Dias_ReparacionesMariano, CanalDeCompra, MargenHistorico_de_Gestion_de_Compra,
                        MargenIndexado_de_Gestion_de_Venta, PrecioPropuesto, MELI, KAVAK, TIENDACARS, MOTORMAX, AUTOCITY, RANDAZZO,
                        Diferencia_PP_y_PE, MargenHistorico_de_Costo_y_PE, PrecioDeVenta, DescuentoRecargos,
                        MargenIndexado_de_Costo_y_Valor_de_Venta, Valor_de_Toma_a_X_dias, Diferencia_ASOFIX_y_PE,
                        TieneVenta, SemanaEjecucion, FechaEjecucion, Cuenta, CostoIndexado_a_X_dias_de_Venta, MargenIndexado_de_Costo
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (ID) DO UPDATE SET
                        MELI = EXCLUDED.MELI, KAVAK = EXCLUDED.KAVAK,
                        TIENDACARS = EXCLUDED.TIENDACARS, MOTORMAX = EXCLUDED.MOTORMAX,
                        AUTOCITY = EXCLUDED.AUTOCITY, RANDAZZO = EXCLUDED.RANDAZZO,
                        PrecioPropuesto = EXCLUDED.PrecioPropuesto,
                        MargenHistorico_de_Gestion_de_Compra = EXCLUDED.MargenHistorico_de_Gestion_de_Compra,
                        MargenIndexado_de_Gestion_de_Venta = EXCLUDED.MargenIndexado_de_Gestion_de_Venta,
                        Diferencia_PP_y_PE = EXCLUDED.Diferencia_PP_y_PE,
                        MargenIndexado_de_Costo_y_Valor_de_Venta = EXCLUDED.MargenIndexado_de_Costo_y_Valor_de_Venta,
                        Valor_de_Toma_a_X_dias = EXCLUDED.Valor_de_Toma_a_X_dias,
                        Cuenta = EXCLUDED.Cuenta,
                        CostoIndexado_a_X_dias_de_Venta = EXCLUDED.CostoIndexado_a_X_dias_de_Venta,
                        MargenIndexado_de_Costo = EXCLUDED.MargenIndexado_de_Costo,
                        FechaEjecucion = EXCLUDED.FechaEjecucion
                """
                
                cur.execute(upsert_query, (
                    id_transaccion, stock_car['patente'], stock_car['marca'], stock_car['modelo'], stock_car['anio'], stock_car['km'], stock_car['color'], stock_car['chasis'], stock_car['cotizacionnro'], stock_car['ubicacion'],
                    stock_car['canaldeventa'], precio_de_lista, precio_toma, dias_lote, stock_car['fechaingreso'], stock_car['sucursal'],
                    costos_reparaciones, precio_toma_total, indice_diario,
                        costo_45_dias, stock_car['canaldecompra'], float(margen_hist_compra),
                        float(costo_45_dias), float(precio_propuesto), float(meli), float(kavak), float(tiendacars), float(motormax), float(autocity), float(randazzo),
                    dif_pp_pe, margen_hist_costo_pe, precio_de_venta, descuento_recargos,
                    margen_idx_costo_venta, valor_toma_x_dias, dif_asofix_pe,
                        stock_car['tieneventa'], semana_ejecucion, today, float(cuenta), float(costo_idx_venta_days), float(margen_idx_costo)
                ))
                
                if progress_callback:
                    progress_callback(f"✅ Valuación registrada en PreciosAutosUsados (Semana: {semana_ejecucion})")

            cur.execute("SELECT * FROM PreciosAutosUsados WHERE ID = %s", (id_transaccion,))
            updated_stock = cur.fetchall()

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Datos persistidos y cálculos actualizados en PostgreSQL correctamente.")
        return updated_stock
    except Exception as e:
        logger.error(f"❌ Error persistiendo en DB: {str(e)}")
        logger.error(traceback.format_exc())
        return []

def load_scraper_module(file_name):
    """Carga dinámicamente un módulo de scraping desde un archivo."""
    path = os.path.join(os.path.dirname(__file__), file_name)
    spec = importlib.util.spec_from_file_location(file_name.replace(" ", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def get_site_instruction(site_key: str):
    """Recupera la instrucción activa para un sitio desde la DB."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT i.*, s.base_url, s.site_name
            FROM scraping_instructions i 
            JOIN site_configs s ON i.site_key = s.site_key 
            WHERE i.site_key = %s AND i.is_active = TRUE 
            ORDER BY i.version DESC LIMIT 1
        """, (site_key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"❌ Error obteniendo instrucciones: {e}")
        return None

@app.get("/stock")
async def get_stock():
    """Obtiene la lista de vehículos en stock."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT Patente as patente, Marca as marca, Modelo as modelo, Anio as anio, km, PrecioDeVenta as precio_venta FROM stock_usados ORDER BY Marca, Modelo")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sites")
async def get_sites():
    """Obtiene la lista de sitios configurados."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM site_configs WHERE is_active = TRUE")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/instructions/{site_key}")
async def get_instructions(site_key: str):
    """Obtiene las instrucciones para un sitio."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM scraping_instructions WHERE site_key = %s ORDER BY version DESC", (site_key,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/instructions")
async def update_instructions(instr: InstructionUpdate):
    """Guarda una nueva versión de instrucciones."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(version), 0) FROM scraping_instructions WHERE site_key = %s", (instr.site_key,))
        new_ver = cur.fetchone()[0] + 1
        
        if instr.is_active:
            cur.execute("UPDATE scraping_instructions SET is_active = FALSE WHERE site_key = %s", (instr.site_key,))
            
        cur.execute("""
            INSERT INTO scraping_instructions (site_key, version, navigation_instruction, listing_instruction, interaction_instruction, extraction_instruction, validation_rules, extraction_schema, steps, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (instr.site_key, new_ver, instr.navigation_instruction, instr.listing_instruction, instr.interaction_instruction, instr.extraction_instruction, 
              json.dumps(instr.validation_rules), json.dumps(instr.extraction_schema), json.dumps(instr.steps) if instr.steps else None, instr.is_active))
        
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "version": new_ver}
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
    #model_name = "google/gemini-3-flash-preview"

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

        def run_site_scraping(site_key, progress_callback):
            # Obtener instrucciones de la DB
            config = get_site_instruction(site_key)
            if not config:
                progress_callback(f"❌ [{site_key.upper()}] No hay instrucciones configuradas.")
                return "NO_RESULTS"

            target_url = config['base_url']
            site_name = config['site_name']
            
            # Contexto para variables dinámicas
            context = {
                "brand": request.brand, "model": request.model, 
                "year": request.year, "version": request.version,
                "base_url": target_url
            }

            # --- NAVEGACIÓN ASISTIDA POR IA (Stagehand) ---
            progress_callback(f"🌐 [{site_name.upper()}] Iniciando navegador local...")
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=request.headless,
                local_ready_timeout_s=20.0, 
                timeout=600.0
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {"headless": request.headless}},
            )
            sess_id = session.data.session_id
            
            all_extracted_items = []
            
            # Si hay pasos definidos en la DB, usar el motor modular
            if config.get('steps'):
                progress_callback(f"⚙️ Ejecutando flujo modular de {len(config['steps'])} pasos...")
                # Ejecutar motor de pasos (síncrono dentro del thread)
                all_extracted_items = asyncio.run(execute_steps(client_sync, sess_id, config['steps'], context, progress_callback, model_name))
            else:
                # Fallback a lógica legacy (archivos python)
                progress_callback("⚠️ Usando lógica legacy (sin pasos definidos)...")
                # ... (Lógica de navegación legacy si fuera necesaria) ...
                # Por brevedad, asumimos que se migrará a pasos.
                pass

            client_sync.sessions.end(id=sess_id)
            client_sync.close()

            if not all_extracted_items:
                progress_callback(f"⚠️ [{site_name.upper()}] No se extrajeron publicaciones.")

            return {"site": site_name, "autos": all_extracted_items}

        try:
            # Ejecutar lógica en paralelo para ambos sitios
            tasks = []
            for site_key in request.sites:
                site_key_lower = site_key.lower().replace(" ", "")
                tasks.append(asyncio.create_task(asyncio.to_thread(run_site_scraping, site_key_lower, log_status)))
            
            # Monitorear la cola de mensajes mientras las tareas corren
            while any(not t.done() for t in tasks) or not queue.empty():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield json.dumps(msg) + "\n"
                except asyncio.TimeoutError:
                    continue

            # Recopilar resultados de todas las tareas
            all_site_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            log_status("📊 Procesando datos extraídos de todos los sitios...")
            
            site_averages = {}
            for raw_results in all_site_results:
                if isinstance(raw_results, Exception):
                    logger.error(f"❌ Error en tarea de scraping: {raw_results}")
                    continue
                
                if raw_results == "NO_RESULTS": continue

                items = raw_results.get("autos", [])
                site_name = raw_results.get("site", "Desconocido").lower()
                base_url = raw_results.get("base_url", "")
                
                if items:
                    log_status(f"📝 Procesando {len(items)} publicaciones de {site_name}...")
                    processed_items_for_site = []
                    for item in items:
                        try:
                            price = clean_num(item.get('precio', item.get('price', item.get('precio_contado', 0))))
                            currency = str(item.get('moneda', item.get('currency', 'ARS'))).upper()
                            price_ars = price * exchange_rate if currency == 'USD' else price
                            km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                            year = int(clean_num(item.get('año', item.get('year', request.year))))
                            raw_link = str(item.get('link', item.get('url', '')))
                            full_link = urljoin(base_url, raw_link)

                            extracted_data.append({
                                "brand": str(item.get('marca', item.get('brand', request.brand))),
                                "model": str(item.get('modelo', item.get('model', request.model))),
                                "version": str(item.get('version', 'N/A')),
                                "year": year, "km": km, "price": price, "currency": currency,
                                "price_ars": price_ars, "title": str(item.get('titulo', item.get('title', 'N/A'))),
                                "combustible": str(item.get('combustible', 'N/A')),
                                "transmision": str(item.get('transmision', 'N/A')),
                                "zona": str(item.get('zona', item.get('ubicacion', 'N/A'))),
                                "fecha_publicacion": str(item.get('fecha_publicacion', 'N/A')),
                                "reservado": bool(item.get('reservado', False)),
                                "url": full_link, "site": site_name.capitalize()
                            })
                            processed_items_for_site.append(extracted_data[-1])
                        except: continue
                    
                    if processed_items_for_site:
                        site_df = pd.DataFrame(processed_items_for_site)
                        site_averages[site_name] = float(site_df[site_df['price_ars'] > 0]['price_ars'].mean())

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

                    # Persistencia en DB por sitio para actualizar columnas específicas
                    updated_stock = save_to_db(extracted_data, site_averages, request, progress_callback=log_status)
                    
                    log_status("✨ Proceso de guardado y análisis finalizado correctamente.")

                    # Helper para serializar tipos no estándar de la base de datos (Decimal, datetime, date)
                    def json_serial(obj):
                        if isinstance(obj, (datetime, date)):
                            return obj.isoformat()
                        if isinstance(obj, Decimal):
                            return float(obj)
                        raise TypeError(f"Type {type(obj)} not serializable")

                    yield json.dumps({
                        "type": "final",
                        "status": "success", "data": df.to_dict('records'),
                        "stats": res_stats,
                        "updated_stock": updated_stock,
                        "message": f"Se extrajeron {len(df)} publicaciones exitosamente."
                    }, default=json_serial) + "\n"
                else:
                    yield json.dumps({"type": "final", "status": "empty", "message": "No se encontraron publicaciones válidas."}) + "\n"
            else:
                yield json.dumps({"type": "final", "status": "empty", "message": "No se encontraron publicaciones válidas."}) + "\n"

        except Exception as e:
            logger.error(f"❌ Error en el proceso de scraping: {str(e)}")
            logger.error(traceback.format_exc())
            yield json.dumps({"type": "final", "status": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)