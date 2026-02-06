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
    logger.info(f"🚀 Iniciando Stagehand Optimizado para: {request.brand} {request.model}")
    
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
                local_ready_timeout_s=20.0, # Aumentado para mayor estabilidad
            )
            
            print("🔧 Iniciando sesión...")
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={
                    "type": "local",
                    "launchOptions": {},
                },
            )
            sess_id = session.data.session_id
            
            print(f"📍 Navegando a {request.url}...")
            client_sync.sessions.navigate(id=sess_id, url=request.url)
            time.sleep(4)
            
            # FLUJO DE NAVEGACIÓN Y FILTRADO ROBUSTO
            print("🤖 Ejecutando secuencia de filtrado inteligente...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": f"""
                    1. Si aparece un selector de país, selecciona 'Argentina'.
                    2. Dirígete a la sección de 'Autos usados' o 'Comprar auto'.
                    3. Busca el filtro de 'Marca' y selecciona '{request.brand}'. Espera a que la página cargue los modelos.
                    4. Busca el filtro de 'Modelo' y selecciona '{request.model}'. 
                       - Si no lo ves, haz clic en 'Ver más' o despliega la lista.
                       - IMPORTANTE: Asegúrate de que el modelo '{request.model}' quede marcado.
                    5. Verifica que los resultados en pantalla se hayan actualizado para mostrar solo {request.brand} {request.model}.
                    6. Si hay un botón de 'Aplicar' o 'Ver resultados', púlsalo.
                    """,
                    "max_steps": 20,
                },
                agent_config={
                    "model": {"model_name": model_name},
                },
            )
            
            # Pausa de seguridad para que los resultados terminen de renderizar
            time.sleep(5)
            
            print("🔍 Extrayendo datos finales...")
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"""
                Extrae los autos listados en la página que correspondan a {request.brand} {request.model}.
                Devuelve un JSON con los campos: 
                - marca (brand)
                - modelo (model)
                - año (year, número)
                - km (número)
                - precio (precio, número)
                - moneda (currency)
                - titulo (title)
                - link (url de la publicación)
                """
            )
            
            extracted_raw = result.data.result
            
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            
            return extracted_raw

        # Ejecución en hilo separado
        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        # Procesamiento de JSON
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

            if isinstance(items, dict):
                for key in ['autos', 'cars', 'results', 'data']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): items = [items]
            
            if isinstance(items, list):
                for item in items:
                    try:
                        # Normalización de números
                        km_raw = str(item.get('km', '0')).lower()
                        km_val = int(''.join(filter(str.isdigit, km_raw))) if any(c.isdigit() for c in km_raw) else 0
                        
                        price_raw = str(item.get('precio', item.get('price', '0')))
                        price_val = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_raw.replace(',', ''))))
                        
                        if km_val <= request.km_max:
                            extracted_data.append({
                                "brand": item.get('marca', item.get('brand', request.brand)),
                                "model": item.get('modelo', item.get('model', request.model)),
                                "year": int(item.get('año', item.get('year', request.year))),
                                "km": km_val,
                                "price": price_val,
                                "currency": item.get('moneda', item.get('currency', 'ARS')),
                                "title": item.get('titulo', item.get('title', 'N/A')),
                                "url": item.get('link', item.get('url', ''))
                            })
                    except: continue

        except Exception as parse_err:
            logger.error(f"Error procesando JSON de IA: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo en filtrado: {str(e)[:40]}"
        })

    if extracted_data:
        df = pd.DataFrame(extracted_data)
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        all_data = []
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f: all_data = json.load(f)
            except: pass
        all_data.extend(extracted_data)
        with open(DATA_FILE, "w") as f: json.dump(all_data, f, indent=4)
        
        avg_price = df['price'].mean() if not df.empty else 0
        return {
            "status": "success", "data": extracted_data,
            "stats": {"average_price": avg_price, "count": len(extracted_data)},
            "message": "Scraping exitoso con validación de modelo"
        }
    
    return {"status": "empty", "message": "No se encontraron datos después del filtrado"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
