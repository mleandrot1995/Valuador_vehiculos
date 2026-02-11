import asyncio
import sys
import logging
import json
import os
import re
import pandas as pd
from urllib.parse import urlparse, urljoin
import uvicorn
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
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

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "valuador_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "password")
    )

def save_to_db(extracted_data, stats, domain, request_data):
    """Persiste los datos en PostgreSQL: tabla transaccional y tabla de resultados."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

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
        if request_data.patente:
            site_map = {"kavak": "kavak", "mercadolibre": "meli", "tiendacars": "tienda_cars", "motormax": "motor_max", "autocity": "auto_city", "randazzo": "randazzo"}
            col = next((v for k, v in site_map.items() if k in domain), None)
            
            if col:
                avg_price = stats.get("average_price", 0)
                cur.execute(f"UPDATE stock_comparison SET {col} = %s WHERE patente = %s", (avg_price, request_data.patente))

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Datos persistidos en PostgreSQL correctamente.")
    except Exception as e:
        logger.error(f"❌ Error persistiendo en DB: {e}")

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
    base_instr = (
        "1. Si aparece un cartel de cookies o selección de país/región, acéptalo o ciérralo.\n"
        "2. Asegúrate de estar en la sección de compra de autos o categoria de Vehiculos (Marketplace). Si estás en la home, busca el botón 'Comprar un auto', Categoria 'Vehiculos' o similar.\n"
        "3. Verificar si se observan los filtros de búsqueda, en caso de que no se hallen hacer clic en la barra de búsqueda (entry point) para ver filtros si corresponde CASO CONTRARIO NO HACER NADA.\n"
        "REGLA CRÍTICA: Si no encuentras el valor exacto solicitado para CUALQUIERA de los filtros (Marca, Modelo, Año, Disponibilidad, KM, etc.), DETÉN el proceso inmediatamente. No intentes seleccionar valores similares ni continúes con el resto de los pasos.\n"
    )
    
    if "kavak" in domain:
        return base_instr + (
            f"4. Aplica los filtros: Marca (puede tener otros nombres considerar todas las variantes posibles): '{brand}', Modelo (puede tener otros nombres considerar todas las variantes posibles): '{model}', Año (puede tener otros nombres considerar todas las variantes posibles): '{year}' y Disponibilidad de auto (puede tener otros nombres considerar todas las variantes posibles): 'Disponible' (o similar). Los filtros pueden aparecer como botones, enlaces o listas desplegables. Busca específicamente el botón o enlace con el texto '{year}'. Si no lo ves, expande la sección correspondiente o busca un botón de 'Ver más'.\n"
            "6. Ordenar las publicaciones por 'Relevancia'.\n"
            "7. Haz scroll para cargar los resultados."
        )
    elif "mercadolibre" in domain:
        return base_instr + (
            f"4. Analiza la página para localizar los botones o menús de filtrado de 'Marca' y 'Modelo'. Haz clic en ellos y selecciona '{brand}' y '{model}' respectivamente y si se especifica que deben ser autos 'USADOS'.\n"
            f"5. Una vez aplicados los filtros anteriores, busca el filtro de 'Año' en la barra lateral o lista de opciones y selecciona el año '{year}'.\n"
            "6. Busca el filtro de 'Condición' en la barra lateral y selecciona 'Usados' para filtrar los resultados si ya esta filtrado por Usados, NO HACER NADA.\n"
            "7. Haz scroll para cargar las publicaciones.\n"
        )
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
    model_name = "google/gemini-2.5-flash" 
    
    extracted_data = []
    
    try:
        def run_stagehand_logic():
            # Extraer el dominio dinámicamente de la URL solicitada
            parsed_url = urlparse(request.url)
            domain = parsed_url.netloc.replace("www.", "")
            
            # --- NAVEGACIÓN ASISTIDA POR IA (Stagehand) ---
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=False,
                local_ready_timeout_s=20.0, 
                timeout=300.0
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {"headless": False}},
            )
            sess_id = session.data.session_id
            
            client_sync.sessions.navigate(id=sess_id, url=request.url)

            instruction = get_full_navigation_instruction(domain, request.brand, request.model, request.year)
            
            logger.info("🤖 Agente IA ejecutando navegación y filtrado...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": instruction,
                    "max_steps": 15,
                },
                agent_config={"model": {"model_name": model_name}},
            )

            # Verificación rápida de resultados para detener el proceso si no hay nada
            logger.info("🧐 Verificando si existen resultados...")
            check_result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Analiza la página actual. ¿Se aplicaron correctamente los filtros de Marca (puede tener otros nombres considerar todas las variantes posibles): '{request.brand}', Modelo  (puede tener otros nombres considerar todas las variantes posibles): '{request.model}' y Año  (puede tener otros nombres considerar todas las variantes posibles): '{request.year}'? ¿La página muestra resultados que coinciden con estos filtros, o muestra un mensaje de '0 resultados' o 'No se encontraron vehículos'? Responde false si los filtros no se aplicaron correctamente o si no hay resultados que coincidan con la búsqueda.",
                schema={"type": "object", "properties": {"has_results": {"type": "boolean"}}}
            )
            
            if not check_result.data.result.get("has_results", False):
                logger.info("❌ No se encontraron resultados para la búsqueda.")
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
            logger.info(f"✅ Resultados confirmados. Continuando scraping desde: {current_url}")

            # --- EXTRACCIÓN DETALLADA (Navegando a cada publicación) ---
            logger.info("💎 Iniciando extracción detallada modularizada...")
            all_extracted_items = []
            max_pubs = 5  # Límite heredado a los módulos
            
            if "kavak" in domain:
                kavak_module = load_scraper_module("prueba scrap kavak.py")
                all_extracted_items = kavak_module.extract_kavak_details(
                    client_sync, sess_id, current_url, max_pubs, model_name
                )
            elif "mercadolibre" in domain:
                meli_module = load_scraper_module("prueba scrap meli.py")
                all_extracted_items = meli_module.extract_meli_details(
                    client_sync, sess_id, current_url, max_pubs, request.version, model_name
                )
            else:
                logger.warning(f"⚠️ Dominio {domain} no tiene un scraper modularizado configurado.")

            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            logger.info(f"✅ autos: {all_extracted_items}")
            return {"autos": all_extracted_items}
            
        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        if raw_results == "NO_RESULTS":
            return {"status": "empty", "message": "No se hallaron valores."}

        # PROCESAMIENTO RÁPIDO Y ROBUSTO
        try:
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
                for item in items:
                    try:
                        def clean_num(v):
                            if v is None: return 0.0
                            s = "".join(c for c in str(v).replace(',', '.') if c.isdigit() or c == '.')
                            try:
                                return float(s) if s else 0.0
                            except: return 0.0

                        price = clean_num(item.get('precio', item.get('price', item.get('precio_contado', 0))))
                        km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                        year = int(clean_num(item.get('año', item.get('year', request.year))))

                        # Reconstrucción de link
                        raw_link = str(item.get('link', item.get('url', '')))
                        
                        full_link = urljoin("https://www.kavak.com", raw_link) if "kavak" in request.url else urljoin(request.url, raw_link)

                        extracted_data.append({
                            "brand": str(item.get('marca', item.get('brand', request.brand))),
                            "model": str(item.get('modelo', item.get('model', request.model))),
                            "version": str(item.get('version', 'N/A')),
                            "year": year, 
                            "km": km, 
                            "price": price,
                            "currency": str(item.get('moneda', item.get('currency', 'ARS'))).upper(),
                            "title": str(item.get('titulo', item.get('title', 'N/A'))),
                            "combustible": str(item.get('combustible', 'N/A')),
                            "transmision": str(item.get('transmision', 'N/A')),
                            "zona": str(item.get('zona', item.get('ubicacion', 'N/A'))),
                            "fecha_publicacion": str(item.get('fecha_publicacion', 'N/A')),
                            "reservado": bool(item.get('reservado', False)),
                            "url": full_link
                        })
                    except: continue

        except Exception as parse_err:
            logger.error(f"Error parseando resultados de IA: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")

    # Respuesta Final
    if extracted_data:
        df = pd.DataFrame(extracted_data)
        # Se elimina el filtro de seguridad post-IA para permitir visualizar todas las publicaciones halladas.
        # La IA ya realiza el filtrado por versión y año durante la navegación.
        
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
                "average_price": df[df['price'] > 0]['price'].mean() if not df[df['price'] > 0].empty else 0, 
                "count": len(df)
            }

            # Persistencia en DB
            parsed_url = urlparse(request.url)
            domain = parsed_url.netloc.replace("www.", "")
            save_to_db(extracted_data, res_stats, domain, request)

            return {
                "status": "success", "data": df.to_dict('records'),
                "stats": res_stats,
                "message": f"Se extrajeron {len(df)} publicaciones exitosamente."
            }
    
    return {"status": "empty", "message": "No se encontraron publicaciones válidas."}

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)