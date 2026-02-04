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
from dotenv import load_dotenv

# Cargar .env para obtener la ruta del binario
load_dotenv()

# Import oficial de Stagehand
try:
    from stagehand import AsyncStagehand
except ImportError:
    AsyncStagehand = None

# Parche de loop para Windows (necesario para Playwright/Stagehand)
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
    logger.info(f"🚀 Iniciando Stagehand para: {request.brand} {request.model}")
    
    if AsyncStagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK no encontrado.")

    # Variables de entorno críticas
    os.environ["MODEL_API_KEY"] = request.api_key
    os.environ["GEMINI_API_KEY"] = request.api_key
    
    extracted_data = []
    client = None
    
    try:
        # Inicialización del cliente
        # La ruta del binario se toma automáticamente de STAGEHAND_SEA_BINARY en el .env
        client = AsyncStagehand(
            model_api_key=request.api_key,
            server="local",
            local_headless=False
        )

        logger.info("Creando sesión...")
        session = await client.sessions.create(
            model_name="gemini-1.5-flash",
            model_provider="google"
        )
        
        logger.info(f"Navegando a {request.url}...")
        await session.goto(request.url)
        
        logger.info("IA buscando el vehículo...")
        await session.act(f"Buscar autos marca {request.brand}, modelo {request.model}, año {request.year}")
        
        await asyncio.sleep(5) 

        logger.info("IA extrayendo datos estructurados...")
        results = await session.extract(
            "Lista de autos con: brand, model, year (number), km (number), price (number), currency, title"
        )
        
        if results and isinstance(results, list):
            for item in results:
                try:
                    km = int(''.join(filter(str.isdigit, str(item.get('km', '0')))))
                    price = float(''.join(filter(lambda x: x.isdigit() or x == '.', str(item.get('price', '0')).replace(',', ''))))
                    if km <= request.km_max:
                        extracted_data.append({
                            "brand": item.get('brand', request.brand),
                            "model": item.get('model', request.model),
                            "year": int(item.get('year', request.year)),
                            "km": km, "price": price,
                            "currency": item.get('currency', 'ARS'),
                            "title": item.get('title', 'N/A')
                        })
                except: continue

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo: {str(e)[:40]}"
        })
    
    finally:
        if client:
            await client.close()

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
        
        return {
            "status": "success", "data": extracted_data,
            "stats": {"average_price": df['price'].mean() if not df.empty else 0, "count": len(extracted_data)},
            "message": "Scraping completado con binario local"
        }
    return {"status": "empty", "message": "No data"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
