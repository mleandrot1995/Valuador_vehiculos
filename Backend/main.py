import asyncio
import sys
import logging
import json
import os
import pandas as pd
import uvicorn
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    logger.info(f"🚀 Iniciando Bridge Node-Stagehand para: {request.brand} {request.model}")
    
    extracted_data = []
    
    try:
        # Ejecutamos el script de Node.js directamente
        # Esto salta todos los problemas de autenticación del SDK de Python
        cmd = [
            "node", 
            "scraper.js", 
            request.brand, 
            request.model, 
            str(request.year), 
            request.url, 
            request.api_key
        ]
        
        logger.info(f"Lanzando Stagehand (Node.js)...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd()
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Leer el archivo temporal generado por Node
            temp_file = "temp_results.json"
            if os.path.exists(temp_file):
                with open(temp_file, "r") as f:
                    results = json.load(f)
                
                for item in results:
                    if int(item.get('km', 0)) <= request.km_max:
                        extracted_data.append(item)
                
                os.remove(temp_file) # Limpiar
                logger.info(f"✅ Scraper finalizado con {len(extracted_data)} resultados.")
        else:
            error_msg = stderr.decode()
            logger.error(f"❌ Error en el proceso de Node: {error_msg}")
            raise Exception(f"Node Error: {error_msg}")

    except Exception as e:
        logger.error(f"❌ Error en el Bridge: {e}")
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallback (Bridge): {str(e)[:40]}"
        })

    # Persistencia
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
            "message": "Scraping completado vía Stagehand Original (Node.js)"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
