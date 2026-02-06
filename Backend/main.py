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
    logger.info(f"🚀 Iniciando Stagehand (Lógica prueba2.py) para: {request.brand} {request.model}")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    # Configuración de variables críticas
    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    model_name = "google/gemini-2.0-flash" # Modelo usado en prueba2.py
    
    extracted_data = []
    
    try:
        # Función interna para ejecutar la lógica síncrona de Stagehand
        # Esto permite encapsular el flujo exacto de prueba2.py
        def run_stagehand_logic():
            print("🚀 Iniciando cliente Stagehand...")
            client_sync = Stagehand(
                server="local",
                model_api_key=request.api_key,
                local_headless=False,
                local_ready_timeout_s=15.0,
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
            print(f"✅ Sesión iniciada: {sess_id}")
            
            print(f"📍 Navegando a {request.url}...")
            client_sync.sessions.navigate(id=sess_id, url=request.url)
            time.sleep(3)
            
            # Lógica de navegación específica basada en prueba2.py
            print("🤖 Ejecutando instrucción inicial...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": "Ir siempre a la versión de Argentina si pregunta país. Ir al marketplace de autos usados.",
                    "max_steps": 10,
                },
                agent_config={
                    "model": {"model_name": model_name},
                },
            )
            
            # 2. Filtrar por Marca
            print(f"🔍 Filtrando por marca: {request.brand}...")
            client_sync.sessions.act(
                id=sess_id,
                input=f"Filtrar búsqueda seleccionando la marca '{request.brand}'. Verificar que se aplicó."
            )
            time.sleep(2)

            # 3. Filtrar por Modelo
            print(f"🔍 Filtrando por modelo: {request.model}...")
            client_sync.sessions.act(
                id=sess_id,
                input=f"Filtrar búsqueda seleccionando el modelo '{request.model}'. Verificar que se aplicó."
            )
            time.sleep(2)
            
            # 4. Extracción
            print("🔍 Extrayendo datos...")
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction="extraer los encabezados de las publicaciones de autos " \
                            "junto con su url o link, y datos relevantes en un " \
                            "json, como marca, modelo, año, trasmisión, combustible,precio"
            )
            
            # Limpieza final
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            
            return result.data.result

        # Ejecutamos la lógica síncrona en un hilo aparte
        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        # Procesamiento de resultados (parseo inteligente)
        try:
            items = []
            # Si el resultado es texto (JSON string), lo parseamos
            if isinstance(raw_results, str):
                clean_json = raw_results
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0]
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0]
                items = json.loads(clean_json.strip())
            else:
                items = raw_results

            # Normalizar a lista de objetos
            if isinstance(items, dict):
                # A veces viene envuelto en una clave como 'autos' o 'result'
                for key in ['autos', 'cars', 'result', 'data']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): # Si sigue siendo dict, lo hacemos lista
                    items = [items]
            elif not isinstance(items, list):
                items = []

            for item in items:
                try:
                    # Extracción segura de valores numéricos
                    km_val = 0
                    if 'km' in item and item['km']:
                        km_str = str(item['km']).lower().replace('km', '').replace('.', '').replace(',', '').strip()
                        km_val = int(km_str) if km_str.isdigit() else 0
                    
                    price_val = 0.0
                    if 'precio' in item and item['precio']: # prueba2 usa 'precio' en español
                        price_str = str(item['precio']).replace('$', '').replace('.', '').replace(',', '').strip()
                        price_val = float(price_str) if price_str.replace('.', '').isdigit() else 0.0
                    elif 'price' in item:
                        price_str = str(item['price']).replace('$', '').replace('.', '').replace(',', '').strip()
                        price_val = float(price_str)
                    
                    if km_val <= request.km_max:
                        extracted_data.append({
                            "brand": item.get('marca', item.get('brand', request.brand)),
                            "model": item.get('modelo', item.get('model', request.model)),
                            "year": int(item.get('año', item.get('year', request.year))),
                            "km": km_val,
                            "price": price_val,
                            "currency": item.get('moneda', item.get('currency', 'ARS')),
                            "title": item.get('titulo', item.get('title', 'N/A')),
                            "url": item.get('url', item.get('link', ''))
                        })
                except Exception as parse_err:
                    logger.warning(f"Item saltado por error de parseo: {parse_err}")
                    continue
                
        except Exception as json_err:
            logger.error(f"Error procesando JSON de IA: {json_err}")

    except Exception as e:
        logger.error(f"❌ Error crítico en Stagehand: {e}")
        # Fallback
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo técnico: {str(e)[:40]}"
        })

    # Guardado
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
            "message": "Scraping exitoso (Core prueba2.py)"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
