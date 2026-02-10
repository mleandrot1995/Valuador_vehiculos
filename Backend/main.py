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

def parse_ai_json(data: any, default: any = None) -> any:
    """Helper to safely parse JSON from AI responses, handling markdown blocks."""
    if not isinstance(data, str):
        return data
    try:
        # Remove markdown code blocks if present
        clean_json = re.sub(r'```json\s*|```\s*', '', data).strip()
        return json.loads(clean_json)
    except Exception:
        logger.warning(f"Failed to parse AI JSON response: {data[:100]}...")
        return default

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
    # Optimizamos usando gemini-1.5-flash (más económico y estable para scraping)
    model_name = "google/gemini-1.5-flash" 
    
    extracted_data = []
    usage_stats = {"total_tokens": 0}
    
    try:
        def log_token_usage(client, sess_id, action_name):
            """Obtiene y muestra el uso de tokens acumulado y el delta de la acción."""
            try:
                metrics = client.sessions.get_metrics(id=sess_id)
                new_total = metrics.data.total_tokens
                delta = new_total - usage_stats["total_tokens"]
                usage_stats["total_tokens"] = new_total
                logger.info(f"📊 [Tokens] {action_name} - Usados: {delta} | Total acumulado: {new_total}")
            except Exception:
                pass

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
            log_token_usage(client_sync, sess_id, "Navegación/Filtrado")

            # Verificación rápida de resultados para detener el proceso si no hay nada
            logger.info("🧐 Verificando si existen resultados...")
            check_result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Analiza la página actual. ¿Se aplicaron correctamente los filtros de Marca (puede tener otros nombres considerar todas las variantes posibles): '{request.brand}', Modelo  (puede tener otros nombres considerar todas las variantes posibles): '{request.model}' y Año  (puede tener otros nombres considerar todas las variantes posibles): '{request.year}'? ¿La página muestra resultados que coinciden con estos filtros, o muestra un mensaje de '0 resultados' o 'No se encontraron vehículos'? Responde false si los filtros no se aplicaron correctamente o si no hay resultados que coincidan con la búsqueda.",
                schema={"type": "object", "properties": {"has_results": {"type": "boolean"}}}
            )
            log_token_usage(client_sync, sess_id, "Verificación Resultados")
            
            if not check_result.data.result.get("has_results", False):
                logger.info("❌ No se encontraron resultados para la búsqueda.")
                client_sync.sessions.end(id=sess_id)
                client_sync.close()
                return "NO_RESULTS"

            # --- EXTRACCIÓN DETALLADA (Navegando uno por uno como usuario) ---
            logger.info("💎 Iniciando extracción detallada ingresando uno por uno a las publicaciones...")
            
            all_extracted_items = []
            
            # Capturamos la URL de resultados actual para poder volver después de cada clic
            results_page_info = client_sync.sessions.extract(
            # 1. Extraemos los IDs y URLs de una vez para evitar volver a la lista de resultados
            listings_info = client_sync.sessions.extract(
                id=sess_id,
                instruction="Obtén la URL actual de la página de resultados.",
                schema={"type": "object", "properties": {"url": {"type": "string"}}}
                instruction="Localiza la lista principal de resultados. Para los primeros 5 vehículos, extrae el valor del atributo 'data-testid' de su etiqueta <a> y su URL (href).",
                schema={
                    "type": "object", 
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "url": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            )
            results_data = parse_ai_json(results_page_info.data.result, default={})
            results_url = results_data.get("url", request.url)
            
            results_data = parse_ai_json(listings_info.data.result, default={})
            vehicles_to_process = results_data.get("items", [])
            logger.info(f"📊 TOTAL IDENTIFICADO: {len(vehicles_to_process)} publicaciones reales.")
            
            # --- EXTRACCIÓN DETALLADA (Simulando usuario con pestañas) ---
            logger.info("💎 Iniciando extracción detallada simulando apertura en pestañas...")
            all_extracted_items = []

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
                    "fecha_publicacion": {"type": "string"},
                    "url": {"type": "string"}
                },
                "required": ["precio", "titulo"]
            }

            for i in range(1, 6):
                logger.info(f"🖱️ Intentando ingresar al vehículo #{i}...")
            for i, v in enumerate(vehicles_to_process, 1):
                target_url = urljoin(request.url, v.get("url", ""))
                target_id = re.search(r'(\d+)', v.get("id", "")).group(1) if re.search(r'(\d+)', v.get("id", "")) else None
                
                logger.info(f"🚀 Navegando directamente al vehículo #{i} (ID: {target_id})...")
                logger.info(f"🖱️ Procesando vehículo #{i}...")
                try:
                    # Asegurarnos de estar en la lista de resultados
                    client_sync.sessions.navigate(id=sess_id, url=results_url)
                    # Navegación directa: mucho más rápida que act()
                    client_sync.sessions.navigate(id=sess_id, url=target_url)
                    time.sleep(2)
                    # Solo navegar de vuelta si no es la primera iteración
                    if i > 1:
                        client_sync.sessions.navigate(id=sess_id, url=results_url)
                        time.sleep(3)
                    # 1. Extraer info del catálogo para validación posterior
                    listing_info = client_sync.sessions.extract(
                        id=sess_id,
                        instruction=f"Extrae el 'data-testid' y el título del vehículo número {i} en la lista principal.",
                        instruction=f"Extrae el título y precio del vehículo número {i} en la lista principal.",
                        schema={
                            "type": "object",
                            "properties": {
                                "data_testid": {"type": "string"},
                                "title": {"type": "string"}
                            }
                        }
                    )
                    l_data = parse_ai_json(listing_info.data.result, default={})
                    target_id_attr = l_data.get("data_testid", "")
                    listing_title = l_data.get("title", "")

                    # Acción: Click en el i-ésimo resultado como un usuario
                    # 2. Simular click derecho y abrir en pestaña nueva
                    client_sync.sessions.act(
                    
                    # Validación rápida de URL vs ID
                    url_info = client_sync.sessions.extract(
                        id=sess_id,
                        input=f"Haz clic en la tarjeta o título del vehículo número {i} de la lista de resultados. Asegúrate de no hacer clic en publicidad."
                        input=f"Ignora anuncios, banners y secciones de 'Recomendados'. En la lista principal de resultados, haz clic en el vehículo número {i}. Si es el número 1, asegúrate de que sea el primer resultado real de la búsqueda."
                        instruction="Obtén la URL actual.",
                        schema={"type": "object", "properties": {"url": {"type": "string"}}}
                        input=f"Haz clic derecho en el vehículo número {i} de la lista principal y ábrelo en una pestaña nueva. Cambia el foco a esa pestaña."
                    )
                    log_token_usage(client_sync, sess_id, f"Click Vehículo #{i}")
                    # Nota: act() puede no devolver uso de tokens en todas las versiones
                    time.sleep(3) # Espera para carga del detalle
                    current_url = parse_ai_json(url_info.data.result, default={}).get("url", "")
                    time.sleep(4)
                    
                    if target_id and target_id not in current_url:
                        logger.warning(f"⚠️ Validación fallida: La URL {current_url} no contiene el ID {target_id}. Reintentando...")
                        # Aquí podrías implementar un reintento o simplemente saltar
                        continue
                    

                    detail_result = client_sync.sessions.extract(
                        id=sess_id,
                        instruction="Extrae la información detallada del vehículo de esta página (marca, modelo, año, km, precio, moneda, título, zona, fecha de publicación).",
                        instruction="Extrae la información detallada del vehículo y la URL actual de la página.",
                        schema=detail_schema
                    )
                    log_token_usage(client_sync, sess_id, f"Extracción Vehículo #{i}")
                    
                    item = parse_ai_json(detail_result.data.result)
                    logger.info(f"✅ Datos extraídos del vehículo #{i}: {item}")
                    current_url = item.get("url", "")
                    detail_title = item.get("titulo", "")

                    # 3. Validación de ID y Encabezado
                    id_in_url = re.search(r'id=(\d+)', current_url)
                    id_in_attr = re.search(r'(\d+)', target_id_attr)
                    
                    if id_in_url and id_in_attr and id_in_url.group(1) == id_in_attr.group(1):
                        logger.info(f"✅ Validación de ID exitosa para vehículo #{i}")
                        if listing_title.lower() in detail_title.lower() or detail_title.lower() in listing_title.lower():
                            logger.info(f"✅ Validación de encabezado exitosa para vehículo #{i}")
                            all_extracted_items.append(item)
                        else:
                            logger.warning(f"⚠️ El título no coincide: '{listing_title}' vs '{detail_title}'")
                    else:
                        logger.warning(f"⚠️ Fallo en validación de ID: Atributo {target_id_attr} vs URL {current_url}")

                    if item:
                        # Obtener la URL del detalle para el registro
                        url_info = client_sync.sessions.extract(
                            id=sess_id,
                            instruction="Obtén la URL actual de la página.",
                            schema={"type": "object", "properties": {"url": {"type": "string"}}}
                        )
                        log_token_usage(client_sync, sess_id, f"URL Vehículo #{i}")
                        url_data = parse_ai_json(url_info.data.result, default={})
                        item['link'] = url_data.get("url", "")
                    # 3. Validación de Encabezado
                    if listing_title.lower() in detail_title.lower() or detail_title.lower() in listing_title.lower():
                        logger.info(f"✅ Validación de encabezado exitosa para vehículo #{i}")
                        item['link'] = current_url
                        all_extracted_items.append(item)
                    else:
                        logger.warning(f"⚠️ El título no coincide: '{listing_title}' vs '{detail_title}'")

                    # 4. Cerrar pestaña y volver a la lista
                    client_sync.sessions.act(
                        id=sess_id,
                        input="Cierra la pestaña actual y vuelve a la pestaña de la lista de resultados."
                    )
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"⚠️ Error procesando vehículo #{i}: {e}")
                    continue

            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            return {"autos": all_extracted_items}

        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        if raw_results == "NO_RESULTS":
            return {"status": "empty", "message": "No se hallaron valores."}

        # PROCESAMIENTO RÁPIDO Y ROBUSTO
        try:
            items = parse_ai_json(raw_results, default=[])

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
