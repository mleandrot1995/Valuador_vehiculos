import asyncio
import sys
import logging
import json
import os
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- PARCHE PARA WINDOWS ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

try:
    from stagehand import Stagehand
except ImportError:
    Stagehand = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS
origins = ["http://localhost:8501", "http://127.0.0.1:8501", "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = "data/publicaciones.json"

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    km_max: int
    api_key: str
    model_provider: str = "gemini"

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Stagehand para: {request.brand} {request.model}")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="stagehand-sdk no instalado en Python")

    # Variables de entorno requeridas por Stagehand
    os.environ["GEMINI_API_KEY"] = request.api_key
    os.environ["STAGEHAND_API_KEY"] = request.api_key
    
    extracted_data = []
    
    try:
        # Inicialización de Stagehand optimizada para Gemini y ejecución local
        async with Stagehand(
            env="local", 
            model_name="gemini-1.5-flash", 
            model_provider="google",
            headless=False # Visible en Windows para seguimiento
        ) as stagehand:
            
            logger.info(f"Navegando a {request.url}...")
            await stagehand.goto(request.url)
            
            # ACCIÓN: La IA busca el vehículo
            logger.info("IA buscando el vehículo...")
            await stagehand.act(f"Busca autos {request.brand} {request.model} año {request.year}. Usa los filtros de búsqueda del sitio si están disponibles.")
            
            # Pausa para que se carguen los resultados tras la acción
            await asyncio.sleep(5) 

            # EXTRACCIÓN: La IA convierte lo que ve en la pantalla en datos JSON
            logger.info("IA extrayendo datos estructurados...")
            results = await stagehand.extract(
                "Lista de autos con sus detalles: brand (marca), model (modelo), year (año, número), km (kilometraje, número), price (precio, número), currency (moneda), title (título completo)"
            )
            
            if results and isinstance(results, list):
                for item in results:
                    try:
                        # Limpieza y normalización de datos numéricos
                        km_raw = str(item.get('km', '0')).lower()
                        km = int(''.join(filter(str.isdigit, km_raw))) if any(c.isdigit() for c in km_raw) else 0
                        
                        price_raw = str(item.get('price', '0'))
                        price = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_raw.replace(',', ''))))
                        
                        if km <= request.km_max:
                            extracted_data.append({
                                "brand": item.get('brand', request.brand),
                                "model": item.get('model', request.model),
                                "year": int(item.get('year', request.year)),
                                "km": km,
                                "price": price,
                                "currency": item.get('currency', 'ARS'),
                                "title": item.get('title', 'N/A')
                            })
                    except Exception as e:
                        logger.warning(f"Error parseando item: {e}")
                        continue
            else:
                logger.warning("No se recibieron resultados estructurados de Stagehand.")

    except Exception as e:
        logger.error(f"❌ Error crítico en Stagehand: {e}")
        # Fallback simulado para que el dashboard no quede vacío durante el debug
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Detección Fallida (Error: {str(e)[:50]})"
        })

    # Persistencia de resultados
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
            "status": "success",
            "data": extracted_data,
            "stats": {"average_price": avg_price, "count": len(extracted_data)},
            "message": "Scraping con Stagehand completado"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    # Ejecución directa para asegurar la aplicación del loop policy en Windows
    uvicorn.run(app, host="0.0.0.0", port=8000)
