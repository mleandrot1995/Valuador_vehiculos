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
    logger.info(f"🚀 Iniciando Scraping Ultra-Robusto: {request.brand} {request.model} ({request.year})")
    
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
                local_ready_timeout_s=40.0, # Aumentado para mayor estabilidad
            )
            
            session = client_sync.sessions.start(
                model_name=model_name,
                browser={"type": "local", "launchOptions": {}},
            )
            sess_id = session.data.session_id
            
            # Navegación Determinista
            start_url = request.url
            if "kavak.com" in start_url and "/ar" not in start_url:
                start_url = "https://www.kavak.com/ar/compra-de-autos"
            
            print(f"📍 Navegando a {start_url}...")
            client_sync.sessions.navigate(id=sess_id, url=start_url)
            time.sleep(6)
            
            # FLUJO DE NAVEGACIÓN COMPLEJO Y BLINDADO
            print("🤖 Ejecutando secuencia de comandos avanzada del agente...")
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={
                    "instruction": f"""
                    OBJETIVO: Filtrar estrictamente por Marca, Modelo y Año para extraer resultados precisos.
                    PASOS OBLIGATORIOS:
                    1. Si aparece un selector de país, selecciona 'Argentina' y acepta cookies/popups.
                    2. Localiza el filtro de 'Marca'. Selecciona exactamente '{request.brand}'. 
                       Espera 3 segundos a que la página actualice los modelos.
                    3. Localiza el filtro de 'Modelo'. Busca y selecciona exactamente '{request.model}'.
                       - Si el modelo no es visible, haz clic en 'Ver más' o despliega la lista completa.
                       - No continúes hasta estar seguro de que '{request.model}' está seleccionado.
                    4. Busca el filtro de 'Año' (o 'Modelo' refiriéndose al año). Selecciona el año '{request.year}'.
                       - Si el año se selecciona mediante un rango o lista, asegúrate de marcar solo el año '{request.year}'.
                    5. Una vez aplicados los 3 filtros (Marca: {request.brand}, Modelo: {request.model}, Año: {request.year}), verifica el contador de resultados.
                    6. Realiza un scroll descendente pausado (3-4 veces) para forzar la carga de precios, kilometraje y links de cada tarjeta de auto.
                    7. Mantente en la vista de cuadrícula/lista de resultados.
                    """,
                    "max_steps": 35, # Aumentado para permitir más interacciones
                },
                agent_config={"model": {"model_name": model_name}},
            )
            
            # Pausa táctica post-navegación para renderizado final
            time.sleep(8)
            
            print("🔍 Extrayendo datos estructurados de alta precisión...")
            result = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"""
                Extrae los datos de TODOS los vehículos visibles que coincidan con {request.brand} {request.model} {request.year}.
                Devuelve un JSON con una lista de objetos, cada uno con:
                - brand: la marca (ej: {request.brand})
                - model: el modelo (ej: {request.model})
                - year: el año (número entero, debe ser {request.year})
                - km: kilometraje (número entero, limpia puntos, comas y texto)
                - price: precio (valor numérico flotante, limpia símbolos de moneda y puntos de miles)
                - currency: moneda detectada (ej: ARS o USD)
                - title: título completo de la publicación
                - link: URL completa de la publicación
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
                # Limpiar bloques de código markdown
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0]
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0]
                items = json.loads(clean_json.strip())
            else:
                items = raw_results

            # Normalización robusta a lista de diccionarios
            if isinstance(items, dict):
                # Intentar encontrar la lista dentro de llaves comunes
                for key in ['autos', 'vehiculos', 'cars', 'results', 'data', 'items', 'result']:
                    if key in items and isinstance(items[key], list):
                        items = items[key]
                        break
                if isinstance(items, dict): items = [items]
            
            if isinstance(items, list):
                for item in items:
                    try:
                        # Función auxiliar para limpieza numérica agresiva
                        def clean_num(v, is_float=False):
                            if v is None: return 0.0
                            # Eliminar todo lo que no sea dígito o punto decimal
                            s = str(v).replace(',', '.') # Convertir coma decimal a punto
                            # Si hay múltiples puntos (ej: 1.500.000), eliminar los de miles
                            if s.count('.') > 1:
                                parts = s.split('.')
                                s = "".join(parts[:-1]) + "." + parts[-1]
                            
                            cleaned = "".join(c for c in s if c.isdigit() or c == '.')
                            try:
                                return float(cleaned) if is_float else int(float(cleaned))
                            except:
                                return 0.0

                        price = clean_num(item.get('price', item.get('precio', 0)), is_float=True)
                        km = clean_num(item.get('km', item.get('kilometraje', 0)))
                        year = clean_num(item.get('year', item.get('año', request.year)))

                        # Validaciones de integridad
                        if price > 0: 
                            extracted_data.append({
                                "brand": str(item.get('brand', item.get('marca', request.brand))).strip(),
                                "model": str(item.get('model', item.get('modelo', request.model))).strip(),
                                "year": int(year),
                                "km": int(km),
                                "price": float(price),
                                "currency": str(item.get('currency', item.get('moneda', 'ARS'))).upper().strip(),
                                "title": str(item.get('title', item.get('titulo', 'N/A'))).strip(),
                                "url": str(item.get('link', item.get('url', ''))).strip()
                            })
                    except Exception as e:
                        logger.warning(f"Error procesando un item individual: {e}")
                        continue

        except Exception as parse_err:
            logger.error(f"Error procesando JSON de IA: {parse_err}")

    except Exception as e:
        logger.error(f"❌ Error crítico en Stagehand: {e}")

    # Persistencia y Respuesta Final
    if extracted_data:
        df = pd.DataFrame(extracted_data)
        
        # Filtro de seguridad post-IA: Asegurar que los datos respeten el KM y el Año (margen de +/- 1 año)
        df = df[(df['km'] <= request.km_max) & (df['year'].between(request.year - 1, request.year + 1))]
        
        if not df.empty:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            # Mezclar con datos históricos de forma segura
            all_data = []
            if os.path.exists(DATA_FILE):
                try:
                    with open(DATA_FILE, "r") as f: all_data = json.load(f)
                except: pass
            
            new_records = df.to_dict('records')
            all_data.extend(new_records)
            
            with open(DATA_FILE, "w") as f: 
                json.dump(all_data, f, indent=4)
            
            return {
                "status": "success", 
                "data": new_records,
                "stats": {"average_price": df['price'].mean(), "count": len(df)},
                "message": f"Se extrajeron {len(df)} vehículos con éxito aplicando filtros de Marca, Modelo y Año ({request.year})."
            }
    
    return {
        "status": "empty", 
        "message": "La IA no logró capturar datos válidos que coincidan con los criterios de Año y KM. Verifique que existan publicaciones en el sitio para estos parámetros."
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
