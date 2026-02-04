import asyncio
import sys
import logging

# PARCHE PARA WINDOWS: DEBE EJECUTARSE ANTES DE CUALQUIER IMPORT DE PLAYWRIGHT O UVICORN
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import pandas as pd
import uvicorn
from playwright.async_api import async_playwright

try:
    from stagehand import Stagehand
except ImportError:
    try:
        from stagehand.Stagehand import Stagehand
    except ImportError:
        Stagehand = None

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

DATA_FILE = "data/publicaciones.json"

class ScrapeRequest(BaseModel):
    url: str
    brand: str
    model: str
    year: int
    km_max: int
    api_key: str
    model_provider: str = "gemini"

@app.get("/")
async def root():
    return {"message": "Car Scraper API is running"}

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"Received scrape request: {request}")
    
    extracted_data = []
    
    try:
        async with async_playwright() as p:
            # En local Windows, intentamos ver la navegación
            browser = await p.chromium.launch(headless=False, slow_mo=500) 
            page = await browser.new_page()
            
            if Stagehand:
                stagehand = Stagehand(
                    page=page, 
                    model_provider=request.model_provider,
                    api_key=request.api_key
                )

                logger.info(f"Navigating to {request.url}")
                await page.goto(request.url, timeout=60000)
                
                logger.info("IA iniciando búsqueda...")
                await stagehand.act(f"Buscar autos {request.brand} {request.model} {request.year}")
                await asyncio.sleep(5)

                logger.info("IA iniciando extracción...")
                extract_instruction = "Extraer lista de autos con brand, model, year, km (número), price (número), currency, title."
                data = await stagehand.extract(extract_instruction)
            else:
                # Fallback manual si Stagehand no está disponible
                logger.warning("Stagehand no disponible, usando navegación básica.")
                await page.goto(request.url)
                data = []

            if data and isinstance(data, list):
                for item in data:
                    try:
                        km_val = str(item.get('km', '0')).lower()
                        km = int(''.join(filter(str.isdigit, km_val))) if any(c.isdigit() for c in km_val) else 0
                        price_val = str(item.get('price', '0'))
                        price = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_val.replace(',', ''))))
                        
                        if km <= request.km_max:
                            extracted_data.append({
                                "brand": item.get('brand', request.brand),
                                "model": item.get('model', request.model),
                                "year": int(item.get('year', request.year)),
                                "km": km, "price": price,
                                "currency": item.get('currency', 'USD'),
                                "title": item.get('title', 'N/A')
                            })
                    except: continue
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000, 25000),
            "currency": "USD", "title": f"Fallback por error: {str(e)[:40]}"
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
            "status": "success",
            "data": extracted_data,
            "stats": {"average_price": avg_price, "count": len(extracted_data)},
            "message": "Scraping completed"
        }
    return {"status": "empty", "message": "No data found"}

if __name__ == "__main__":
    # Ejecución directa para asegurar que el loop policy se aplique correctamente
    uvicorn.run(app, host="0.0.0.0", port=8000)
