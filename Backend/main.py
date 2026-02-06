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
    logger.info(f"🚀 Iniciando Scraping Optimizado: {request.brand} {request.model} ({request.year})")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    model_name = "google/gemini-3-flash-preview" 
    
    extracted_data = []
    
    try:
        def run_stagehand_logic():
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=False,
                local_ready_timeout_s=20.0, 
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {}},
            )
            sess_id = session.data.session_id
            
            # 1. NAVEGACIÓN DIRECTA
            base_url = "https://www.kavak.com"
            start_url = f"{base_url}/ar/compra-de-autos"
            client_sync.sessions.navigate(id=sess_id, url=start_url)
            
            # ORQUESTACIÓN DE FILTROS Y PREPARACIÓN (Navegación robusta)
            print("🤖 Agente ejecutando orquestación de filtros y scroll...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": f"""
                    1. Acepta las cookies y cualquier popup de selección de país (elige Argentina).
                    2. Busca y aplica los filtros laterales: Marca '{request.brand}', Modelo '{request.model}' y Año '{request.year}'.
                    3. Verifica que la lista de resultados se actualice con los autos correspondientes.
                    4. Haz un scroll suave hacia abajo de forma repetida para asegurar que TODAS las tarjetas de autos carguen sus datos.
                    5. Asegúrate de que los precios de todas las publicaciones visibles aparezcan en pantalla.
                    """,
                    "max_steps": 15,
                },
                agent_config={"model": {"model_name": model_name}},
            )
            
            # Breve pausa para estabilización de renderizado final
            time.sleep(2) 

            print("💎 Extrayendo datos estructurados con Schema (Alta Velocidad)...")
            # OPTIMIZACIÓN: El uso de 'schema' acelera drásticamente la extracción al guiar a la IA.
            # Se especifica 'autos' como array para capturar múltiples elementos simultáneamente.
            schema = {
                "type": "object",
                "properties": {
                    "autos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "marca": {"type": "string"},
                                "modelo": {"type": "string"},
                                "año": {"type": "integer"},
                                "km": {"type": "integer"},
                                "precio": {"type": "number"},
                                "moneda": {"type": "string"},
                                "titulo": {"type": "string"},
                                "link": {"type": "string"}
                            },
                            "required": ["precio", "titulo", "link"]
                        }
                    }
                }
            }

            result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Extrae la lista completa de todos los autos visibles que sean {request.brand} {request.model} {request.year}. No omitas ninguno.",
                schema=schema
            )
            
            extracted_raw = result.data.result
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            return extracted_raw

        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
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
                        full_link = f"https://www.kavak.com{raw_link}" if raw_link.startswith('/') else raw_link

                        if price > 0:
                            extracted_data.append({
                                "brand": str(item.get('marca', item.get('brand', request.brand))),
                                "model": str(item.get('modelo', item.get('model', request.model))),
                                "year": year, "km": km, "price": price,
                                "currency": str(item.get('moneda', item.get('currency', 'ARS'))).upper(),
                                "title": str(item.get('titulo', item.get('title', 'N/A'))),
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
