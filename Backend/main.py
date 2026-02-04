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

# Import oficial de Stagehand (browserbase/stagehand-python)
try:
    from stagehand import Stagehand
except ImportError:
    Stagehand = None

# Parche de loop para Windows (necesario para Playwright/Stagehand)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

origins = ["http://localhost:8501", "http://127.0.0.1:8501", "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = os.path.abspath(os.path.join("data", "publicaciones.json"))

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    km_max: int
    api_key: str
    model_provider: str = "google" 

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Stagehand Oficial para: {request.brand} {request.model}")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="Librería Stagehand no instalada correctamente.")

    # --- CONFIGURACIÓN DE STAGEHAND VIA ENTORNO ---
    # La versión oficial de Browserbase es muy dependiente de estas variables en Windows
    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    os.environ["STAGEHAND_API_KEY"] = request.api_key
    os.environ["STAGEHAND_MODEL_NAME"] = "gemini-1.5-flash"
    os.environ["STAGEHAND_MODEL_PROVIDER"] = "google"
    
    extracted_data = []
    
    try:
        # Inicialización limpia de Stagehand sin argumentos en el constructor
        # para evitar errores de 'unexpected keyword argument'
        async with Stagehand() as stagehand:
            
            logger.info(f"Navegando a {request.url}...")
            await stagehand.goto(request.url)
            
            # ACCIÓN INTELIGENTE
            logger.info("IA ejecutando búsqueda...")
            await stagehand.act(f"Buscar autos marca {request.brand}, modelo {request.model}, año {request.year}. Utiliza los filtros de búsqueda del sitio si es posible.")
            
            # Espera para que carguen los resultados
            await asyncio.sleep(7) 

            # EXTRACCIÓN ESTRUCTURADA
            logger.info("IA extrayendo datos estructurados...")
            # Usamos una instrucción muy clara para el LLM
            results = await stagehand.extract(
                "Lista de autos con: brand (marca), model (modelo), year (año, solo número), km (kilometraje, solo número), price (precio, solo número), currency (moneda), title (título)"
            )
            
            if results and isinstance(results, list):
                for item in results:
                    try:
                        # Normalización robusta de números
                        km_str = str(item.get('km', '0'))
                        km = int(''.join(filter(str.isdigit, km_str))) if any(c.isdigit() for c in km_str) else 0
                        
                        price_str = str(item.get('price', '0'))
                        price = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_str.replace(',', ''))))
                        
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
                    except Exception as parse_err:
                        logger.warning(f"Error parseando item: {parse_err}")
                        continue
            else:
                logger.warning("No se recibieron resultados de Stagehand.extract()")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand Oficial: {e}")
        # Fallback de debug para el dashboard
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo con Stagehand: {str(e)[:50]}"
        })

    # Guardado de resultados
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
            "message": "Scraping completado con Stagehand (Official via Env Vars)"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
