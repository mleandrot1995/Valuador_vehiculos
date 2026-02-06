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
    logger.info(f"🚀 Iniciando Extracción Robusta para: {request.brand} {request.model}")
    
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
                local_ready_timeout_s=25.0,
            )
            
            print("🔧 Iniciando sesión...")
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {}},
            )
            sess_id = session.data.session_id
            
            print(f"📍 Navegando a {request.url}...")
            client_sync.sessions.navigate(id=sess_id, url=request.url)
            time.sleep(5)
            
            # FLUJO DE NAVEGACIÓN Y FILTRADO
            print("🤖 Aplicando filtros y cargando contenido...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": f"""
                    1. Si aparece un selector de país, selecciona 'Argentina'.
                    2. Ve al catálogo de autos usados.
                    3. Aplica el filtro de Marca '{request.brand}' y el filtro de Modelo '{request.model}'.
                    4. Verifica que aparezcan resultados en pantalla.
                    5. Realiza un scroll suave hacia abajo para asegurar que todas las tarjetas de autos carguen sus datos y precios.
                    """,
                    "max_steps": 15,
                },
                agent_config={"model": {"model_name": model_name}},
            )
            
            # Pausa de renderizado tras el scroll
            time.sleep(4)
            
            print("🔍 Ejecutando extracción de datos visibles...")
            # Instrucción simplificada para maximizar acierto de la IA
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction="""
                Extrae la lista de vehículos que se muestran en el catálogo. 
                Para cada vehículo necesito: 
                - marca
                - modelo
                - año (solo el número)
                - kilometraje (solo el número)
                - precio (valor numérico)
                - moneda (ARS o USD)
                - titulo_publicacion
                - link_directo
                """
            )
            
            extracted_raw = result.data.result
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            return extracted_raw

        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        # PROCESAMIENTO INTELIGENTE DEL JSON
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

            # Normalizar a lista
            if isinstance(items, dict):
                # Buscar listas dentro del diccionario (llaves comunes de LLMs)
                possible_keys = ['autos', 'vehiculos', 'cars', 'results', 'data', 'items']
                found = False
                for key in possible_keys:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        found = True
                        break
                if not found: items = [items]
            
            if isinstance(items, list):
                for item in items:
                    try:
                        # Mapeo flexible de llaves (Español/Inglés)
                        brand_val = item.get('marca', item.get('brand', request.brand))
                        model_val = item.get('modelo', item.get('model', request.model))
                        year_val = item.get('año', item.get('year', request.year))
                        
                        # Limpieza de KM
                        km_raw = str(item.get('kilometraje', item.get('km', '0'))).lower()
                        km_val = int(''.join(filter(str.isdigit, km_raw))) if any(c.isdigit() for c in km_raw) else 0
                        
                        # Limpieza de PRECIO
                        price_raw = str(item.get('precio', item.get('price', '0')))
                        price_val = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_raw.replace(',', ''))))
                        
                        if price_val > 0: # Validar que al menos trajo un precio
                            extracted_data.append({
                                "brand": brand_val,
                                "model": model_val,
                                "year": int(year_val),
                                "km": km_val,
                                "price": price_val,
                                "currency": item.get('moneda', item.get('currency', 'ARS')),
                                "title": item.get('titulo_publicacion', item.get('title', 'N/A')),
                                "url": item.get('link_directo', item.get('url', ''))
                            })
                    except: continue

        except Exception as parse_err:
            logger.error(f"Error procesando JSON: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")
        # Mantenemos un dummy solo si falló todo para no romper el front
        if not extracted_data:
            extracted_data.append({"brand": request.brand, "model": request.model, "year": request.year, "km": 0, "price": 0, "currency": "N/A", "title": "Error de detección visual", "url": ""})

    # Persistencia y Respuesta
    if extracted_data and extracted_data[0]['price'] > 0:
        df = pd.DataFrame(extracted_data)
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        all_data = []
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f: all_data = json.load(f)
            except: pass
        all_data.extend(extracted_data)
        with open(DATA_FILE, "w") as f: json.dump(all_data, f, indent=4)
        
        avg_price = df[df['price']>0]['price'].mean()
        return {
            "status": "success", "data": extracted_data,
            "stats": {"average_price": avg_price, "count": len(extracted_data)},
            "message": "Datos extraídos correctamente."
        }
    
    return {"status": "empty", "message": "La IA navegó correctamente pero no pudo leer los datos de las tarjetas de autos."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
