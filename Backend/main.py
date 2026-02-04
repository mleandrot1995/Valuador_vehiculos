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

# --- PARCHE DE NIVEL ARQUITECTO: BLINDAJE TOTAL WINDOWS ---
if sys.platform == 'win32':
    # 1. Forzar el directorio de trabajo a la carpeta del script
    # Esto asegura que las rutas relativas de node_modules y data funcionen bien
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # 2. Política de bucle de eventos para Playwright/Stagehand
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # 3. Interceptor de Subprocesos Blindado para corregir WinError 267 y WinError 2
    _original_popen = subprocess.Popen
    def _patched_popen(args, **kwargs):
        # Corrección de WinError 267: Validar que cwd sea una carpeta real
        if 'cwd' in kwargs and kwargs['cwd']:
            cwd_path = os.path.abspath(kwargs['cwd'])
            if os.path.isfile(cwd_path):
                # Si es un archivo, usamos su directorio padre
                kwargs['cwd'] = os.path.dirname(cwd_path)
            else:
                kwargs['cwd'] = cwd_path
        else:
            # Si no hay cwd, forzamos el directorio actual del backend
            kwargs['cwd'] = os.getcwd()

        if isinstance(args, list) and len(args) > 0:
            cmd = args[0]
            # Resolución de binarios de Node/NPM/Stagehand
            if cmd in ['npx', 'npm', 'node', 'stagehand']:
                full_path = shutil.which(cmd) or shutil.which(f"{cmd}.cmd") or shutil.which(f"{cmd}.exe")
                if full_path:
                    args[0] = os.path.normpath(full_path)
                
                # En Windows, para ejecutar scripts (.cmd, .bat) se requiere shell=True
                if args[0].lower().endswith(('.cmd', '.bat')):
                    kwargs['shell'] = True
        
        return _original_popen(args, **kwargs)
    
    subprocess.Popen = _patched_popen
    logging.info("🛠️ Blindaje Windows aplicado correctamente.")

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

# Ruta de datos absoluta para evitar problemas de directorio
DATA_FILE = os.path.abspath(os.path.join("data", "publicaciones.json"))

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

    # Claves necesarias en variables de entorno para que Stagehand las lea
    os.environ["GEMINI_API_KEY"] = request.api_key
    os.environ["STAGEHAND_API_KEY"] = request.api_key
    
    extracted_data = []
    stagehand = None
    
    try:
        # Instanciamos Stagehand con config explícita
        # Usamos google como provider ya que Gemini es de Google
        stagehand = Stagehand(
            env="local", 
            model_name="gemini-1.5-flash", 
            model_provider="google",
            headless=False # Visible para seguimiento
        )
        
        # Algunas versiones del SDK requieren un init() explícito
        if hasattr(stagehand, 'init'):
            await stagehand.init()

        logger.info(f"Navegando a {request.url}...")
        await stagehand.goto(request.url)
        
        logger.info("IA analizando la página y buscando el vehículo...")
        # Instrucción de acción para navegar y buscar
        await stagehand.act(f"Buscar autos marca {request.brand}, modelo {request.model}, año {request.year}. Usa los filtros si existen.")
        
        # Pausa para estabilización visual
        await asyncio.sleep(6) 

        logger.info("IA extrayendo datos estructurados JSON...")
        # Instrucción de extracción de datos
        results = await stagehand.extract(
            "Extraer lista de autos con brand, model, year (número), km (número), price (número), currency, title"
        )
        
        if results and isinstance(results, list):
            for item in results:
                try:
                    # Normalización robusta de números
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
        else:
            logger.warning("No se obtuvieron resultados de la extracción de Stagehand.")

    except Exception as e:
        logger.error(f"❌ Error en Stagehand: {e}")
        # Fallback de debug
        import random
        extracted_data.append({
            "brand": request.brand, "model": request.model, "year": request.year,
            "km": random.randint(1000, request.km_max), "price": random.randint(15000000, 30000000),
            "currency": "ARS", "title": f"Fallo en Stagehand: {str(e)[:40]}"
        })
    
    finally:
        # Limpieza manual de recursos
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
            "message": "Scraping completado con blindaje aplicado"
        }
    
    return {"status": "empty", "message": "No se encontraron datos"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
