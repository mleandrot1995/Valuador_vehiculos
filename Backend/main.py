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

origins = ["http://localhost:8501", "http://127.0.0.1:8501", "*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DATA_FILE = os.path.abspath(os.path.join("data", "publicaciones.json"))
MAP_FILE = os.path.abspath(os.path.join("data", "navigation_map.json"))

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    km_max: int
    api_key: str

def get_full_navigation_instruction(domain: str, brand: str, model: str, year: int) -> str:
    """
    Genera la instrucción completa y robusta para el agente de IA.
    """
    base_instr = (
        "1. Si aparece un cartel de cookies o selección de país/región, acéptalo o ciérralo.\n"
        "2. Asegúrate de estar en la sección de compra de autos usados (Marketplace). Si estás en la home, busca el botón 'Comprar un auto' o similar.\n"
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
        return base_instr + f"4. Analiza la página para localizar los botones o menús de filtrado de 'Marca' y 'Modelo'. Haz clic en ellos y selecciona '{brand}' y '{model}' respectivamente.\n5. Busca el filtro de 'Condición' en la barra lateral y selecciona 'Usados' para filtrar los resultados.\n6. Haz scroll para cargar las publicaciones."
    else:
        return base_instr + f"4. Busca y filtra por Marca '{brand}', Modelo '{model}' y Año '{year}'.\n5. Haz scroll para cargar resultados."

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Scraping Optimizado: {request.brand} {request.model} ({request.year})")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    model_name = "google/gemini-3-flash-preview" 
    
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

            # --- EXTRACCIÓN DETALLADA (Navegando a cada publicación) ---
            logger.info("💎 Iniciando extracción detallada ingresando a las primeras 5 publicaciones...")
            
            # 1. Obtener los links de las primeras 5 publicaciones
            links_schema = {
                "type": "object",
                "properties": {
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "format": "uri", "description": "URL del atributo href."},
                                "data-testid": {
                                    "type": "string",
                                    "format": "uri-reference",
                                    "description": "El valor del atributo data-testid de la tarjeta (ej: card-product-485703)."
                                }
                            },
                            "required": ["url", "data-testid"]
                        }
                    }
                }
            }

            links_result = client_sync.sessions.extract(
                id=sess_id,
                instruction="Analiza las primeras 5 tarjetas de vehículos. Para cada una, extrae el 'href' en el campo 'url' y el valor del atributo 'data-testid'.",
                schema=links_schema
            )
            
            links_data = links_result.data.result
            logger.info(f"Sitios encontrados: {links_result}")
            if isinstance(links_data, str):
                try:
                    clean_json = links_data
                    if "```json" in clean_json: clean_json = clean_json.split("```json")[1].split("```")[0]
                    elif "```" in clean_json: clean_json = clean_json.split("```")[1].split("```")[0]
                    links_data = json.loads(clean_json.strip())
                except: links_data = {}
            
            # Manejo robusto de la respuesta (puede ser dict o list)
            links = []
            raw_list = []
            if isinstance(links_data, dict):
                raw_list = links_data.get("links", [])
            elif isinstance(links_data, list):
                raw_list = links_data
            
            for item in raw_list:
                if isinstance(item, dict):
                    url = item.get("url")
                    card_product = item.get("card_product", "")
                    unit_id = None
                    
                    if card_product:
                        # Extraer el ID numérico del data-testid
                        id_match = re.search(r'(\d+)', card_product)
                        if id_match:
                            unit_id = id_match.group(1)

                    # Reconstrucción de seguridad si la IA 'limpió' la URL pero capturó el ID
                    if url and unit_id and "id=" not in url:
                        connector = "&" if "?" in url else "?"
                        url = f"{url}{connector}id={unit_id}"
                    if url:
                        links.append(url)
                elif isinstance(item, str):
                    links.append(item)
            
            # Deduplicar enlaces manteniendo el orden para evitar navegar a la misma URL repetidamente
            unique_links = list(dict.fromkeys(links))
            if len(unique_links) < len(links):
                logger.warning(f"⚠️ Se detectaron {len(links) - len(unique_links)} enlaces duplicados. La IA podría estar capturando links genéricos.")
            links = unique_links
            logger.info(f"🔗 Enlaces únicos encontrados para procesar: {links}")
            
            links = links[:5]
            all_extracted_items = []
            
            # 2. Esquema para el detalle de cada auto
            detail_schema = {
                "type": "object",
                "properties": {
                    "marca": {"type": "string"},
                    "modelo": {"type": "string"},
                    "año": {"type": "integer"},
                    "km": {"type": "integer"},
                    "precio": {"type": "number"},
                    "moneda": {"type": "string"},
                    "titulo": {"type": "string"},
                    "zona": {"type": "string"},
                    "fecha_publicacion": {"type": "string"}
                },
                "required": ["precio", "titulo"]
            }

            # 3. Navegar a cada link y extraer información detallada
            for link in links:
                full_url = urljoin(request.url, link)
                logger.info(f"🔗 Navegando a detalle: {full_url}")
                try:
                    client_sync.sessions.navigate(id=sess_id, url=full_url)
                    time.sleep(2) # Espera para carga de contenido dinámico
                    
                    detail_result = client_sync.sessions.extract(
                        id=sess_id,
                        instruction="Extrae la información detallada del vehículo de esta página (marca, modelo, año, km, precio, moneda, título, zona, fecha de publicación).",
                        schema=detail_schema
                    )
                    
                    item = detail_result.data.result
                    logger.info(f"🔗 Información sobre el vehiculos: {item}")
                    if isinstance(item, str):
                        try:
                            clean_json = item
                            if "```json" in clean_json: clean_json = clean_json.split("```json")[1].split("```")[0]
                            item = json.loads(clean_json.strip())
                        except: item = None

                    if item:
                        item['link'] = full_url
                        all_extracted_items.append(item)
                except Exception as e:
                    logger.error(f"⚠️ Error extrayendo detalle de {full_url}: {e}")
                    continue

            client_sync.sessions.end(id=sess_id)
            client_sync.close()
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

                        price = clean_num(item.get('precio', item.get('price', 0)))
                        km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                        year = int(clean_num(item.get('año', item.get('year', request.year))))

                        # Reconstrucción de link
                        raw_link = str(item.get('link', item.get('url', '')))
                        
                        full_link = urljoin("https://www.kavak.com", raw_link) if "kavak" in request.url else urljoin(request.url, raw_link)

                        if price > 0:
                            extracted_data.append({
                                "brand": str(item.get('marca', item.get('brand', request.brand))),
                                "model": str(item.get('modelo', item.get('model', request.model))),
                                "year": year, "km": km, "price": price,
                                "currency": str(item.get('moneda', item.get('currency', 'ARS'))).upper(),
                                "title": str(item.get('titulo', item.get('title', 'N/A'))),
                                "zona": str(item.get('zona', 'N/A')),
                                "fecha_publicacion": str(item.get('fecha_publicacion', 'N/A')),
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
        # Filtro de seguridad post-IA
        df = df[(df['km'] <= request.km_max) & (df['year'].between(request.year - 1, request.year + 1))]
        
        if not df.empty:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            all_data = []
            if os.path.exists(DATA_FILE):
                try:
                    with open(DATA_FILE, "r") as f: all_data = json.load(f)
                except: pass
            all_data.extend(df.to_dict('records'))
            with open(DATA_FILE, "w") as f: json.dump(all_data, f, indent=4)
            
            return {
                "status": "success", "data": df.to_dict('records'),
                "stats": {"average_price": df['price'].mean(), "count": len(df)},
                "message": f"Se extrajeron {len(df)} publicaciones exitosamente."
            }
    
    return {"status": "empty", "message": "No se encontraron publicaciones válidas."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
