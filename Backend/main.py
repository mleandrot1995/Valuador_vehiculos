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
    logger.info(f"🚀 Iniciando Scraping Modular Robusto: {request.brand} {request.model} ({request.year})")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    # Aseguramos que las variables de entorno estén para el SEA
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
            
            print("🔧 Iniciando sesión...")
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {}},
            )
            sess_id = session.data.session_id
            
            # 1. NAVEGACIÓN INICIAL
            start_url = "https://www.kavak.com/ar/compra-de-autos"
            print(f"📍 Paso 1: Navegando a {start_url}")
            client_sync.sessions.navigate(id=sess_id, url=start_url)
            time.sleep(5)

            # 2. MANEJO DE BLOQUEOS (Cookies/País)
            print("🛡️ Paso 2: Limpiando obstáculos visuales...")
            try:
                client_sync.sessions.act(id=sess_id, input="Si aparece un cartel de selección de país o cookies, acéptalo o ciérralo inmediatamente.")
                time.sleep(2)
            except: pass

            # 3. FILTRO DE MARCA
            print(f"🔍 Paso 3: Filtrando Marca -> {request.brand}")
            client_sync.sessions.act(
                id=sess_id, 
                input=f"Busca el filtro de 'Marca' en la barra lateral o menús, haz clic en '{request.brand}'. Si no está visible, despliega la lista de marcas primero."
            )
            time.sleep(5) 

            # 4. FILTRO DE MODELO
            print(f"🔍 Paso 4: Filtrando Modelo -> {request.model}")
            client_sync.sessions.act(
                id=sess_id, 
                input=f"Busca el filtro de 'Modelo', selecciona exactamente '{request.model}'. Asegúrate de que el checkbox o la opción quede marcada. Si hay un botón de 'Ver más' para modelos, úsalo."
            )
            time.sleep(5)

            # 5. FILTRO DE AÑO
            print(f"🔍 Paso 5: Filtrando Año -> {request.year}")
            client_sync.sessions.act(
                id=sess_id, 
                input=f"Busca el filtro de 'Año' o 'Modelo' (referido al año). Selecciona el año '{request.year}' o el rango que lo incluya específicamente."
            )
            time.sleep(5)

            # 6. CARGA DE CONTENIDO (Scroll) - CORRECCIÓN DE ARGUMENTOS
            print("📜 Paso 6: Cargando tarjetas de autos...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": "Realiza scroll hacia abajo de forma pausada para asegurar que las tarjetas de autos carguen sus precios y títulos. Hazlo 3 veces.",
                    "max_steps": 5,
                },
                agent_config={
                    "model": {"model_name": model_name},
                },
            )
            time.sleep(4)

            # 7. EXTRACCIÓN FINAL
            print("💎 Paso 7: Extrayendo datos estructurados...")
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"""
                Extrae la lista de todos los autos visibles que coincidan con la marca {request.brand} y modelo {request.model}.
                Devuelve un JSON con una lista llamada 'autos' donde cada objeto tenga:
                - marca (brand)
                - modelo (model)
                - año (year, número entero)
                - km (número entero)
                - precio (número entero)
                - moneda (ARS o USD)
                - titulo (title)
                - link (url completa de la publicación)
                """
            )
            
            extracted_raw = result.data.result
            client_sync.sessions.end(id=sess_id)
            client_sync.close()
            return extracted_raw

        # Ejecución en hilo separado para no bloquear FastAPI
        raw_results = await asyncio.to_thread(run_stagehand_logic)
        
        # PROCESAMIENTO DE RESULTADOS
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

            # Normalizar a lista de diccionarios
            if isinstance(items, dict):
                for key in ['autos', 'vehiculos', 'cars', 'data', 'items', 'result']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): items = [items]
            
            if isinstance(items, list):
                for item in items:
                    try:
                        def clean_num(v):
                            s = "".join(c for c in str(v).replace(',', '.') if c.isdigit() or c == '.')
                            return float(s) if s else 0.0

                        price = clean_num(item.get('precio', item.get('price', 0)))
                        km = int(clean_num(item.get('km', item.get('kilometraje', 0))))
                        year = int(clean_num(item.get('año', item.get('year', request.year))))

                        if price > 0:
                            extracted_data.append({
                                "brand": str(item.get('marca', item.get('brand', request.brand))),
                                "model": str(item.get('modelo', item.get('model', request.model))),
                                "year": year,
                                "km": km,
                                "price": price,
                                "currency": str(item.get('moneda', item.get('currency', 'ARS'))).upper(),
                                "title": str(item.get('titulo', item.get('title', 'N/A'))),
                                "url": str(item.get('link', item.get('url', '')))
                            })
                    except: continue

        except Exception as parse_err:
            logger.error(f"Error procesando JSON de IA: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")

    # Persistencia y Respuesta
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
                "message": f"Se extrajeron {len(df)} vehículos con éxito."
            }
    
    return {"status": "empty", "message": "No se encontraron datos válidos después del filtrado modular."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
