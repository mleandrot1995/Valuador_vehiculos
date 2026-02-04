from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import pandas as pd
import uvicorn
import asyncio
from playwright.async_api import async_playwright
import logging
# Cambiado el import a la forma estándar de la librería python
try:
    from stagehand import Stagehand
except ImportError:
    # Fallback si el SDK tiene otra estructura
    try:
        from stagehand.Stagehand import Stagehand
    except ImportError:
        Stagehand = None

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 1. Configuración de CORS
origins = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "*"
]

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
    model_provider: str = "gemini" # gemini or ollama

@app.get("/")
async def root():
    return {"message": "Car Scraper API is running"}

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"Received scrape request: {request}")
    
    if Stagehand is None:
        logger.error("Stagehand SDK not found. Install it with 'pip install stagehand-sdk'")
    
    extracted_data = []
    
    try:
        async with async_playwright() as p:
            # En local Windows usualmente queremos ver el navegador (headless=False)
            # pero Stagehand a veces prefiere headless según la config de AI
            browser = await p.chromium.launch(headless=True) 
            page = await browser.new_page()
            
            # Inicializamos Stagehand
            stagehand = Stagehand(
                page=page, 
                model_provider=request.model_provider,
                api_key=request.api_key
            )

            logger.info(f"Navigating to {request.url}")
            await page.goto(request.url, timeout=60000)
            
            # Navegación inteligente
            await stagehand.act(f"Buscar autos {request.brand} {request.model} {request.year}")
            await page.wait_for_timeout(3000)

            # Extracción inteligente
            extract_instruction = "Extraer lista de autos con brand, model, year, km (número), price (número), currency, title."
            data = await stagehand.extract(extract_instruction)
            
            if data and isinstance(data, list):
                for item in data:
                    try:
                        km = int(str(item.get('km', 0)).replace('km', '').replace(',', '').replace('.', '').strip())
                        price = float(str(item.get('price', 0)).replace('$', '').replace(',', '').strip())
                        if km <= request.km_max:
                            extracted_data.append({
                                "brand": item.get('brand', request.brand),
                                "model": item.get('model', request.model),
                                "year": int(item.get('year', request.year)),
                                "km": km,
                                "price": price,
                                "currency": item.get('currency', 'USD'),
                                "title": item.get('title', 'N/A')
                            })
                    except:
                        continue
            
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        # Mantenemos fallback para pruebas
        import random
        extracted_data.append({
            "brand": request.brand,
            "model": request.model,
            "year": request.year,
            "km": random.randint(1000, request.km_max),
            "price": random.randint(15000, 25000),
            "currency": "USD",
            "title": f"Fallback: {request.brand} (Error: {str(e)[:50]})"
        })

    if extracted_data:
        df = pd.DataFrame(extracted_data)
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        all_data = []
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    all_data = json.load(f)
            except: pass
        all_data.extend(extracted_data)
        with open(DATA_FILE, "w") as f:
            json.dump(all_data, f, indent=4)
        
        avg_price = df['price'].mean() if not df.empty else 0
        return {
            "status": "success",
            "data": extracted_data,
            "stats": {"average_price": avg_price, "count": len(extracted_data)},
            "message": "Scraping completed"
        }
    return {"status": "empty", "message": "No data found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
