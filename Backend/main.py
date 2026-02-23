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

SITE_URLS = {
    "kavak": "https://www.kavak.com/ar",
    "mercadolibre": "https://www.mercadolibre.com.ar/"
}

class ScrapeRequest(BaseModel):
    sites: List[str]
    brand: str
    model: str
    year: int
    version: str
    km_max: int
    api_key: str
    nav_instr_kavak: str = None
    ext_instr_kavak: str = None
    nav_instr_meli: str = None
    ext_instr_meli: str = None
    custom_fields: List[str] = []
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

def save_to_db(extracted_data, site_averages, request_data, progress_callback=None):
    """Persiste los datos en PostgreSQL: tabla transaccional y tabla de resultados."""
    updated_stock = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 0. Calcular promedios de mercado base (independiente de si hay stock o no)
        meli_avg = site_averages.get("mercadolibre", 0)
        kavak_avg = site_averages.get("kavak", 0)
        tiendacars_avg = site_averages.get("tiendacars", 0)
        motormax_avg = site_averages.get("motormax", 0)
        autocity_avg = site_averages.get("autocity", 0)
        randazzo_avg = site_averages.get("randazzo", 0)
        site_prices = [p for p in [meli_avg, kavak_avg, tiendacars_avg, motormax_avg, autocity_avg, randazzo_avg] if p > 0]
        precio_propuesto_base = round(sum(site_prices) / len(site_prices), 2) if site_prices else 0

        # 1. Tabla Transaccional: extractions
        if extracted_data:
            insert_query = """
                INSERT INTO extractions (brand, model, version, year, km, price, currency, title, combustible, transmision, zona, fecha_publicacion, reservado, url, site, datos_adicionales)
                VALUES %s
            """
            values = [
                (
                    item.get('brand'), item.get('model'), item.get('version'), item.get('year'), item.get('km'), 
                    item.get('price'), item.get('currency'), item.get('title'), item.get('combustible'), 
                    item.get('transmision'), item.get('zona'), item.get('fecha_publicacion'), 
                    item.get('reservado'), item.get('url'), item.get('site'),
                    json.dumps(item.get('custom_data', {}))
                ) for item in extracted_data
            ]
            execute_values(cur, insert_query, values)

        # 2. Tabla de Resultados: PreciosAutosUsados
        if request_data.patente:
            # Obtener datos de stock_usados como referencia
            cur.execute('SELECT * FROM stock_usados WHERE Patente = %s', (request_data.patente,))
            stock_car = cur.fetchone()
            
            if stock_car:
                # Normalizar claves a minúsculas para evitar KeyErrors con RealDictCursor
                stock_car = {k.lower(): v for k, v in stock_car.items()}
                
                # Fechas de ejecución
                today = date.today()
                sunday = today - timedelta(days=(today.weekday() + 1) % 7)
                semana_ejecucion = sunday.strftime("%Y-%m-%d")
                id_transaccion = f"{request_data.patente}_{semana_ejecucion}"
                
                # Obtener registro previo si existe en la misma semana
                cur.execute("SELECT * FROM PreciosAutosUsados WHERE ID = %s", (id_transaccion,))
                prev_raw = cur.fetchone()
                prev = {k.lower(): v for k, v in prev_raw.items()} if prev_raw else None
                
                # Consolidar promedios: Priorizar nuevos resultados, sino mantener previos
                meli = site_averages.get("mercadolibre") or float(prev.get('meli', 0) if prev else 0)
                kavak = site_averages.get("kavak") or float(prev.get('kavak', 0) if prev else 0)
                tiendacars = site_averages.get("tiendacars") or float(prev.get('tiendacars', 0) if prev else 0)
                motormax = site_averages.get("motormax") or float(prev.get('motormax', 0) if prev else 0)
                autocity = site_averages.get("autocity") or float(prev.get('autocity', 0) if prev else 0)
                randazzo = site_averages.get("randazzo") or float(prev.get('randazzo', 0) if prev else 0)

                precio_toma = float(stock_car.get('preciodetoma') or 0)
                costos_reparaciones = float(stock_car.get('costosreparaciones') or 0)
                precio_toma_total = precio_toma + costos_reparaciones
                
                indice_mensual = float(stock_car.get('indice') or 0)
                days_in_month = calendar.monthrange(today.year, today.month)[1]
                indice_diario = indice_mensual / days_in_month
                
                dias_lote = int(stock_car.get('diaslote') or 0)

                # Precio Propuesto (Promedio de sitios con valor > 0)
                site_prices = [p for p in [meli, kavak, tiendacars, motormax, autocity, randazzo] if p > 0]
                precio_propuesto = round(sum(site_prices) / len(site_prices), 2) if site_prices else 0
                
                precio_de_lista = float(stock_car.get('preciodelista') or 0)
                precio_de_venta = float(stock_car.get('preciodeventa') or 0)
                
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
                valor_asofix = float(prev.get('valor_propuesto_por_asofix', 0) if prev else 0)
                dif_asofix_pe = 1 - (valor_asofix / precio_de_lista) if precio_de_lista > 0 else 0
                
                # Valor de Toma a X días
                valor_toma_x_dias = float(precio_toma_total * (1 + (indice_diario * dif_asofix_pe) / 100))
                
                current_year = date.today().year
                cuenta = (((current_year - int(stock_car.get('anio') or current_year)) * 15000) - int(stock_car.get('km') or 0)) / 5000.0 * 0.0075
                
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
                    id_transaccion, stock_car.get('patente'), stock_car.get('marca'), stock_car.get('modelo'), stock_car.get('anio'), stock_car.get('km'), stock_car.get('color'), stock_car.get('chasis'), stock_car.get('cotizacionnro'), stock_car.get('ubicacion'),
                    stock_car.get('canaldeventa'), precio_de_lista, precio_toma, dias_lote, stock_car.get('fechaingreso'), stock_car.get('sucursal'),
                    costos_reparaciones, precio_toma_total, indice_diario,
                        costo_45_dias, stock_car.get('canaldecompra'), float(margen_hist_compra),
                        float(costo_45_dias), float(precio_propuesto), float(meli), float(kavak), float(tiendacars), float(motormax), float(autocity), float(randazzo),
                    dif_pp_pe, margen_hist_costo_pe, precio_de_venta, descuento_recargos,
                    margen_idx_costo_venta, valor_toma_x_dias, dif_asofix_pe,
                        stock_car.get('tieneventa'), semana_ejecucion, today, float(cuenta), float(costo_idx_venta_days), float(margen_idx_costo)
                ))
                
                if progress_callback:
                    progress_callback(f"✅ Valuación registrada en PreciosAutosUsados (Semana: {semana_ejecucion})")

                cur.execute("SELECT * FROM PreciosAutosUsados WHERE ID = %s", (id_transaccion,))
                rows = cur.fetchall()
                updated_stock = [{k.lower(): v for k, v in row.items()} for row in rows]
            else:
                if progress_callback:
                    progress_callback(f"⚠️ Patente {request_data.patente} no encontrada. Mostrando promedios de mercado.")
                updated_stock = [{
                    "patente": request_data.patente,
                    "preciopropuesto": precio_propuesto_base,
                    "meli": meli_avg,
                    "kavak": kavak_avg,
                    "marca": request_data.brand,
                    "modelo": request_data.model,
                    "anio": request_data.year
                }]
        else:
            # Si no hay patente, devolvemos los promedios de mercado para que la pestaña 'Resultados' no esté vacía
            updated_stock = [{
                "patente": "S/P",
                "preciopropuesto": precio_propuesto_base,
                "meli": meli_avg,
                "kavak": kavak_avg,
                "marca": request_data.brand,
                "modelo": request_data.model,
                "anio": request_data.year
            }]

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

def get_full_navigation_instruction(domain: str, brand: str, model: str, year: int, version: str, custom_template: str = None) -> str:
    """
    Genera la instrucción completa y robusta para el agente de IA.
    """
    if custom_template:
        # Reemplazar variables en el template del usuario
        return custom_template.format(marca=brand, modelo=model, anio=year, version=version)

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
        cur.execute("""
            SELECT Patente as patente, Marca as marca, Modelo as modelo, Anio as anio, km,
                   Ubicacion as ubicacion, PrecioDeLista as precio_lista, PrecioDeToma as precio_toma, 
                   DiasLote as dias_lote, PrecioDeVenta as precio_venta, TieneVenta as tiene_venta 
            FROM stock_usados ORDER BY Marca, Modelo
        """)
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

        def send_error(msg, screenshot=None):
            logger.error(f"❌ {msg}")
            # Enviamos el error y la captura opcional al frontend
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": msg, "screenshot": screenshot})

        # 1. Obtener tipo de cambio
        log_status(f" Buscando {request.brand} {request.model} ({request.year})...")
        log_status("💵 Actualizando tipo de cambio...")
        exchange_rate = await get_exchange_rate()
        log_status(f"✅ Tipo de cambio: {exchange_rate} ARS/USD")

        def run_site_scraping(site_name, target_url, progress_callback):
            # Extraer el dominio dinámicamente de la URL solicitada
            parsed_url = urlparse(target_url)
            domain = site_name
            
            # --- NAVEGACIÓN ASISTIDA POR IA (Stagehand) ---
            progress_callback(f"🌐 [{site_name.upper()}] Iniciando Agente...")
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
            
            client_sync.sessions.navigate(id=sess_id, url=target_url)

            # Seleccionar instrucción según el sitio
            site_nav_instr = request.nav_instr_kavak if "kavak" in site_name else request.nav_instr_meli
            site_ext_instr = request.ext_instr_kavak if "kavak" in site_name else request.ext_instr_meli

            instruction = get_full_navigation_instruction(domain, request.brand, request.model, request.year, request.version, site_nav_instr)
            
            try:
                progress_callback(f"🤖 [{site_name.upper()}] Agente IA navegando...")
                client_sync.sessions.execute(
                    id=sess_id,
                    execute_options={
                        "instruction": instruction,
                        "max_steps": 20,
                    },
                    agent_config={"model": {"model_name": model_name}},
                )
            except Exception as e:
                screenshot = None
                try:
                    ss = client_sync.sessions.screenshot(id=sess_id)
                    screenshot = ss.data.base64
                except: pass
                send_error(f"Error en {site_name}: {str(e)}", screenshot)
                return "ERROR"

            # Verificación rápida de resultados para detener el proceso si no hay nada
            progress_callback(f"🧐 [{site_name.upper()}] Verificando resultados...")
            check_result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Analiza la página actual. ¿Se aplicaron correctamente los filtros de Marca (puede tener otros nombres considerar todas las variantes posibles): '{request.brand}', Modelo  (puede tener otros nombres considerar todas las variantes posibles): '{request.model}' y Año  (puede tener otros nombres considerar todas las variantes posibles): '{request.year}'? ¿La página muestra resultados que coinciden con estos filtros, o muestra un mensaje de '0 resultados' o 'No se encontraron vehículos'? Responde false si los filtros no se aplicaron correctamente o si no hay resultados que coincidan con la búsqueda.",
                schema={"type": "object", "properties": {"has_results": {"type": "boolean"}}}
            )
            
            if not check_result.data.result.get("has_results", False):
                progress_callback(f"❌ [{site_name.upper()}] Sin resultados.")
                client_sync.sessions.end(id=sess_id)
                client_sync.close()
                return "NO_RESULTS"

            # Si hay resultados, capturamos la URL actual con filtros aplicados y continuamos
            url_res = client_sync.sessions.extract(
                id=sess_id,
                instruction="Obtén la URL actual de la página.",
                schema={"type": "object", "properties": {"url": {"type": "string","format": "uri"}}}
            )
            current_url = url_res.data.result.get("url", target_url)
            progress_callback(f"✅ [{site_name.upper()}] Resultados confirmados. Extrayendo...")

            # --- EXTRACCIÓN DETALLADA (Navegando a cada publicación) ---
            all_extracted_items = []
            max_pubs = 5  # Límite heredado a los módulos
            
            if "kavak" in site_name:
                kavak_module = load_scraper_module("prueba scrap kavak.py")
                all_extracted_items = kavak_module.extract_kavak_details(
                    client_sync, sess_id, current_url, max_pubs, request.version, model_name, site_ext_instr, request.custom_fields, progress_callback=lambda m: progress_callback(f"[{site_name.upper()}] {m}")
                )
            elif "mercadolibre" in site_name:
                meli_module = load_scraper_module("prueba scrap meli.py")
                all_extracted_items = meli_module.extract_meli_details(
                    client_sync, sess_id, current_url, max_pubs, request.version, model_name, site_ext_instr, request.custom_fields, progress_callback=lambda m: progress_callback(f"[{site_name.upper()}] {m}")
                )
            else:
                progress_callback(f"⚠️ [{site_name.upper()}] No soportado.")

            client_sync.sessions.end(id=sess_id)
            client_sync.close()

            if not all_extracted_items:
                progress_callback(f"⚠️ [{site_name.upper()}] No se extrajeron publicaciones.")
            else:
                progress_callback(f"✅ [{site_name.upper()}] Extracción finalizada.")

            return {"site": site_name, "autos": all_extracted_items}

        try:
            # Ejecutar lógica en paralelo para ambos sitios
            tasks = []
            for site_key in request.sites:
                site_key_lower = site_key.lower().replace(" ", "")
                if site_key_lower in SITE_URLS:
                    tasks.append(asyncio.create_task(asyncio.to_thread(run_site_scraping, site_key_lower, SITE_URLS[site_key_lower], log_status)))
            
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
                
                if raw_results in ("NO_RESULTS", "ERROR"): continue

                items = raw_results.get("autos", [])
                site_name = raw_results.get("site", "Desconocido").lower()
                
                if items:
                    log_status(f" Analizando {len(items)} resultados de {site_name.upper()}...")
                    processed_items_for_site = []
                    for idx, item in enumerate(items, 1):
                        log_status(f"⚙️ [{site_name.upper()}] Procesando publicación {idx}/{len(items)}...")
                        try:
                            def clean_num(v):
                                if v is None: return 0.0
                                s = "".join(c for c in str(v).replace(',', '.') if c.isdigit() or c == '.')
                                try:
                                    return float(s) if s else 0.0
                                except: return 0.0

                            price = clean_num(item.get('precio', item.get('price', item.get('precio_contado', 0))))
                            currency = str(item.get('moneda', item.get('currency', 'ARS'))).upper()
                            price_ars = price * exchange_rate if currency == 'USD' else price
                            km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                            year = int(clean_num(item.get('año', item.get('year', request.year))))
                            raw_link = str(item.get('link', item.get('url', '')))
                            full_link = urljoin(SITE_URLS.get(site_name, ""), raw_link)
                            
                            # Definir campos que ya son parte del esquema estándar (incluyendo sinónimos)
                            standard_keys = {
                                'title', 'titulo', 'year', 'año', 'km', 'kilometraje', 'precio', 'price', 
                                'precio_contado', 'moneda', 'currency', 'combustible', 'transmision', 
                                'marca', 'brand', 'modelo', 'model', 'version', 'ubicacion', 'zona', 
                                'url', 'link', 'fecha_publicacion', 'reservado'
                            }
                            # Guardar en custom_data SOLO los campos que el usuario solicitó explícitamente
                            # y que no colisionan con los campos estándar ya procesados.
                            custom_data = {k: v for k, v in item.items() if k in request.custom_fields and k not in standard_keys}


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
                                "custom_data": custom_data,
                                "url": full_link, "site": site_name.capitalize()
                            })
                            processed_items_for_site.append(extracted_data[-1])
                        except: continue
                    
                    if processed_items_for_site:
                        site_df = pd.DataFrame(processed_items_for_site)
                        site_averages[site_name] = float(site_df[site_df['price_ars'] > 0]['price_ars'].mean())
                        log_status(f"✅ [{site_name.upper()}] Datos normalizados correctamente.")

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
                    
                    log_status("✅ Scraping y valuación finalizados con éxito.")

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
                        "exchange_rate": exchange_rate,
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

@app.get("/history/extractions")
async def get_extractions_history():
    """Obtiene el historial de extracciones crudas."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT brand, model, version, year, km, price, currency, site, zona, fecha_transaccion, url, datos_adicionales 
            FROM extractions 
            ORDER BY fecha_transaccion DESC 
            LIMIT 500
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for r in rows:
            if isinstance(r['price'], Decimal): r['price'] = float(r['price'])
            if r['fecha_transaccion']: r['fecha_transaccion'] = r['fecha_transaccion'].isoformat()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/valuations")
async def get_valuations_history():
    """Obtiene el historial de valuaciones calculadas de negocio."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM PreciosAutosUsados ORDER BY FechaEjecucion DESC, SemanaEjecucion DESC LIMIT 100")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        processed_rows = []
        for row in rows:
            new_row = {}
            for k, v in row.items():
                val = float(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, (datetime, date)) else v)
                new_row[k.lower()] = val
            processed_rows.append(new_row)
        return processed_rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)