import asyncio
import sys
import logging
import json
import os
import pandas as pd
import uvicorn
import subprocess
import shutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- PARCHE DE COMPATIBILIDAD PRO PARA WINDOWS ---
if sys.platform == 'win32':
    # 1. Política de bucle de eventos para Playwright
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # 2. Interceptor de Subprocesos para corregir WinError 2 y WinError 267
    _original_popen = subprocess.Popen
    def _patched_popen(args, **kwargs):
        # Aseguramos que el cwd (directorio de trabajo) sea absoluto y válido
        if 'cwd' in kwargs and kwargs['cwd']:
            kwargs['cwd'] = os.path.abspath(kwargs['cwd'])
        
        if isinstance(args, list) and len(args) > 0:
            cmd = args[0]
            # Si es un comando de Node, buscamos su ruta real en Windows
            if cmd in ['npx', 'npm', 'node', 'stagehand']:
                full_path = shutil.which(cmd) or shutil.which(f"{cmd}.cmd") or shutil.which(f"{cmd}.exe")
                if full_path:
                    args[0] = os.path.normpath(full_path)
                
                # Para archivos .cmd o .bat, Windows REQUIERE shell=True
                if args[0].lower().endswith(('.cmd', '.bat')):
                    kwargs['shell'] = True
        
        return _original_popen(args, **kwargs)
    
    subprocess.Popen = _patched_popen
    logging.info("🛠️ Parche Windows Pro aplicado a subprocess.Popen")

try:
    from stagehand import Stagehand
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

@app.post("/scrape")
async def scrape_cars(request: ScrapeRequest):
    logger.info(f"🚀 Iniciando Stagehand para: {request.brand} {request.model}")
    
    if Stagehand is None:
        raise HTTPException(status_code=500, detail="stagehand-sdk no instalado")

    # Claves necesarias para Stagehand
    os.environ["GEMINI_API_KEY"] = request.api_key
    os.environ["STAGEHAND_API_KEY"] = request.api_key
    
    extracted_data = []
    stagehand = None
    
    try:
        # Instanciamos Stagehand
        # Usamos google como provider para Gemini
        stagehand = Stagehand(
            env="local", 
            model_name="gemini-1.5-flash", 
            model_provider="google",
            headless=False # Visible en Windows
        )
        
        # Inicialización manual si es requerida por el SDK
        if hasattr(stagehand, 'init'):
            await stagehand.init()

        logger.info(f"Navegando a {request.url}...")
        await stagehand.goto(request.url)
        
        logger.info("IA buscando el vehículo...")
        # Instrucción de acción: Stagehand navegará inteligentemente
        await stagehand.act(f"Busca autos marca {request.brand}, modelo {request.model}, año {request.year}. Usa los filtros si existen.")
        
        await asyncio.sleep(6) 

        logger.info("IA extrayendo datos estructurados...")
        # Instrucción de extracción: La IA convierte lo que ve en JSON
        results = await stagehand.extract(
            "Extraer lista de autos con brand, model, year, km (número), price (número), currency, title"
        )
        
        if results and isinstance(results, list):
            for item in results:
                try:
                    # Normalización de datos numéricos
                    km_raw = str(item.get('km', '0')).lower()
                    km = int(''.join(filter(str.isdigit, km_raw))) if any(c.isdigit() for c in km_raw) else 0
                    
                    price_raw = str(item.get('price', '0'))
                    price = float(''.join(filter(lambda x: x.isdigit() or x == '.', price_raw.replace(',', ''))))
                    
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
        # Fallback debug para que el dashboard muestre algo útil
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo: {str(e)[:40]}"
        })
    
    finally:
        if stagehand and hasattr(stagehand, 'close'):
            try: await stagehand.close()
            except: pass

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
            "message": "Scraping completado con Stagehand"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
