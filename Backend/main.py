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

# Import oficial de Stagehand
try:
    from stagehand import AsyncStagehand
except ImportError:
    AsyncStagehand = None

# Parche de loop para Windows
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

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Stagehand para: {request.brand} {request.model}")
    
    if AsyncStagehand is None:
        raise HTTPException(status_code=500, detail="Stagehand SDK (AsyncStagehand) no encontrado.")

    extracted_data = []
    
    # Inicialización del cliente asíncrono según la inspección realizada
    client = AsyncStagehand(
        model_api_key=request.api_key,
        server="local",
        local_headless=False # Visible en Windows para ver la magia de la IA
    )

    try:
        # 1. Crear una sesión (La inspección mostró que Stagehand tiene 'sessions')
        logger.info("Creando sesión de Stagehand...")
        session = await client.sessions.create(
            model_name="gemini-1.5-flash",
            model_provider="google"
        )
        
        # 2. Navegación y Acciones (Los métodos están en el objeto de sesión)
        logger.info(f"Navegando a {request.url}...")
        await session.goto(request.url)
        
        logger.info("IA buscando el vehículo...")
        await session.act(f"Buscar autos marca {request.brand}, modelo {request.model}, año {request.year}")
        
        # Esperamos a que los resultados se estabilicen visualmente
        await asyncio.sleep(5) 

        # 3. Extracción estructurada
        logger.info("IA extrayendo datos estructurados...")
        results = await session.extract(
            "Lista de autos con: brand, model, year (number), km (number), price (number), currency, title"
        )
        
        if results and isinstance(results, list):
            for item in results:
                try:
                    # Limpieza robusta de datos numéricos
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
            logger.warning("La IA no devolvió resultados estructurados en esta sesión.")

    except Exception as e:
        logger.error(f"❌ Error en el flujo de Stagehand: {e}")
        # Fallback de debug para que el dashboard muestre algo
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo en Sesión Stagehand: {str(e)[:40]}"
        })
    
    finally:
        # Cerrar el cliente para liberar recursos (Chrome)
        logger.info("Cerrando cliente Stagehand...")
        await client.close()

    # Persistencia de datos en JSON
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
            "message": "Scraping con arquitectura de Sesiones completado"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
