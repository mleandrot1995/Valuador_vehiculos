import asyncio
import sys
import logging
import json
import os
import pandas as pd
import uvicorn
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

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

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    km_max: int
    api_key: str

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Scraping Robusto: {request.brand} {request.model}")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    model_name = "google/gemini-2.0-flash" 
    
    extracted_data = []
    
    try:
        def run_stagehand_logic():
            print("🚀 Iniciando cliente Stagehand...")
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=False,
                local_ready_timeout_s=30.0,
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {}},
            )
            sess_id = session.data.session_id
            
            # Navegación Determinista: Intentamos ir directo a Argentina si es Kavak
            start_url = request.url
            if "kavak.com" in start_url and "/ar" not in start_url:
                start_url = "https://www.kavak.com/ar/compra-de-autos"
            
            print(f"📍 Navegando a {start_url}...")
            client_sync.sessions.navigate(id=sess_id, url=start_url)
            time.sleep(5)
            
            # FLUJO DE NAVEGACIÓN BLINDADO
            print("🤖 Ejecutando secuencia de comandos del agente...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": f"""
                    OBJETIVO: Filtrar y preparar la vista para extracción.
                    PASOS:
                    1. Si aparece un cartel de cookies o país, selecciona 'Argentina' y acepta.
                    2. Localiza el filtro de 'Marca'. Seleccióna '{request.brand}'. 
                       Espera 3 segundos a que la página se refresque.
                    3. Localiza el filtro de 'Modelo'. Busca y selecciona '{request.model}'.
                       IMPORTANTE: Si el modelo no aparece, busca un botón 'Ver más' en la lista de modelos.
                    4. Una vez aplicados los filtros, verifica que el contador de resultados sea mayor a 0.
                    5. Realiza un scroll hasta el final de los resultados visibles para que carguen todos los precios y links.
                    6. QUÉDATE EN LA VISTA DE RESULTADOS. No entres en ninguna publicación individual.
                    """,
                    "max_steps": 25,
                },
                agent_config={"model": {"model_name": model_name}},
            )
            
            # Pausa táctica post-navegación
            time.sleep(6)
            
            print("🔍 Extrayendo datos estructurados...")
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction="""
                Extrae CADA vehículo de la lista actual. Devuelve un JSON con:
                - brand: la marca (ej: Toyota)
                - model: el modelo (ej: Corolla)
                - year: el año (número entero)
                - km: kilometraje (número entero, limpia 'km' o puntos)
                - price: precio (valor numérico, limpia '$' y puntos)
                - currency: ARS o USD
                - title: el título que aparece en la tarjeta
                - link: el URL que lleva a la publicación
                """
            )
            
            extracted_raw = result.data.result
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            return extracted_raw

        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        # PROCESAMIENTO DE DATOS CON DOBLE VALIDACIÓN
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

            # Normalización a lista de diccionarios
            if isinstance(items, dict):
                for key in ['autos', 'cars', 'results', 'data', 'items', 'result']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): items = [items]
            
            if isinstance(items, list):
                for item in items:
                    try:
                        # Limpieza profunda de datos para Pandas
                        def clean_num(v):
                            s = ''.join(filter(lambda x: x.isdigit() or x == '.', str(v).replace(',', '.')))
                            return float(s) if s else 0.0

                        price = clean_num(item.get('price', item.get('precio', 0)))
                        km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                        year = int(clean_num(item.get('year', item.get('año', request.year))))

                        if price > 0: # Solo guardamos si hay precio válido
                            extracted_data.append({
                                "brand": item.get('brand', item.get('marca', request.brand)),
                                "model": item.get('model', item.get('modelo', request.model)),
                                "year": year,
                                "km": km,
                                "price": price,
                                "currency": item.get('currency', item.get('moneda', 'ARS')),
                                "title": item.get('title', item.get('titulo', 'N/A')),
                                "url": item.get('link', item.get('url', ''))
                            })
                    except: continue

        except Exception as parse_err:
            logger.error(f"Error procesando JSON de IA: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")

    # Persistencia y Respuesta Final
    if extracted_data:
        df = pd.DataFrame(extracted_data)
        # Filtrado adicional por el año y KM solicitado por el usuario (en caso de que la IA trajera extras)
        df = df[df['km'] <= request.km_max]
        
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        # Mezclar con datos históricos
        all_data = []
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f: all_data = json.load(f)
            except: pass
        all_data.extend(df.to_dict('records'))
        with open(DATA_FILE, "w") as f: json.dump(all_data, f, indent=4)
        
        return {
            "status": "success", 
            "data": df.to_dict('records'),
            "stats": {"average_price": df['price'].mean(), "count": len(df)},
            "message": f"Se extrajeron {len(df)} vehículos correctamente."
        }
    
    return {"status": "empty", "message": "La navegación fue exitosa pero la IA no logró capturar datos válidos. Intente con una búsqueda más específica."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
