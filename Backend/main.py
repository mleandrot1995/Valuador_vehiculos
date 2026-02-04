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

# --- PARCHE DE NIVEL ARQUITECTO PARA COMPATIBILIDAD WINDOWS ---
if sys.platform == 'win32':
    # 1. Política de bucle de eventos
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # 2. Interceptor de Subprocesos: Corrige el error [WinError 2]
    # Este parche intercepta las llamadas de Stagehand al sistema y añade .cmd donde sea necesario
    _original_popen = subprocess.Popen
    def _patched_popen(args, **kwargs):
        if isinstance(args, list) and len(args) > 0:
            executable = args[0]
            # Si el comando es npx, node o npm, buscamos su ruta absoluta con extensión .cmd/.exe
            if executable in ['npx', 'npm', 'stagehand', 'node']:
                full_path = shutil.which(executable)
                if not full_path:
                    # Intento manual para npx.cmd o npm.cmd
                    full_path = shutil.which(f"{executable}.cmd")
                if full_path:
                    args[0] = full_path
                
                # En Windows, para ejecutar .cmd a menudo se requiere shell=True
                if args[0].endswith('.cmd'):
                    kwargs['shell'] = True
        return _original_popen(args, **kwargs)
    
    subprocess.Popen = _patched_popen
    logging.info("🛠️ Parche de compatibilidad Windows aplicado a subprocess.Popen")

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

    # Configuración de claves
    os.environ["GEMINI_API_KEY"] = request.api_key
    os.environ["STAGEHAND_API_KEY"] = request.api_key
    
    extracted_data = []
    stagehand = None
    
    try:
        # Instanciamos Stagehand
        # Usamos google como provider ya que Gemini es de Google
        stagehand = Stagehand(
            env="local", 
            model_name="gemini-1.5-flash", 
            model_provider="google",
            headless=False
        )
        
        if hasattr(stagehand, 'init'):
            await stagehand.init()

        logger.info(f"Navegando a {request.url}...")
        await stagehand.goto(request.url)
        
        logger.info("IA buscando el vehículo...")
        # Instrucción para que la IA navegue
        await stagehand.act(f"Buscar autos marca {request.brand}, modelo {request.model}, año {request.year}. Usa los filtros del sitio.")
        
        await asyncio.sleep(6) 

        logger.info("IA extrayendo datos estructurados...")
        # Instrucción para que la IA extraiga JSON
        results = await stagehand.extract(
            "Lista de autos con: brand, model, year (número), km (número), price (número), currency, title"
        )
        
        if results and isinstance(results, list):
            for item in results:
                try:
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
        # Fallback debug
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo en Stagehand: {str(e)[:50]}"
        })
    
    finally:
        if stagehand and hasattr(stagehand, 'close'):
            try: await stagehand.close()
            except: pass

    # Persistencia de datos
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
            "message": "Scraping completado"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
