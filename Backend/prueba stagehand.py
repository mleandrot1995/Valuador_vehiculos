import asyncio
import sys
import logging
import json
import os
import re
import pandas as pd
from urllib.parse import urlparse, urljoin
import uvicorn
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
try:
    from stagehand import Stagehand
except ImportError:
    Stagehand = None

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    results_url = "https://www.kavak.com/ar/usados?maker=toyota&model=corolla&status=disponible&year=2021&order=relevance"
    
    # Variables para el medidor de tokens
    usage_stats = {"total_tokens": 0, "total_cost_approx": 0.0}

    def log_token_usage(action_name):
        """Obtiene y muestra el uso de tokens acumulado y el delta de la acción."""
        try:
            metrics = client_sync.sessions.get_metrics(id=sess_id)
            new_total = metrics.data.total_tokens
            delta = new_total - usage_stats["total_tokens"]
            usage_stats["total_tokens"] = new_total
            logger.info(f"📊 [Tokens] {action_name} - Usados: {delta} | Total acumulado: {new_total}")
        except Exception as e:
            logger.debug(f"⚠️ No se pudieron obtener métricas: {e}")

    # Create client using environment variables
    # Optimizaciones de costo: dom_cache=True reduce el procesamiento repetitivo del DOM
    client_sync = Stagehand(
        server="local",
        model_api_key="AIzaSyCF-XWzm-dQuPk45pPlEIsGzENjoPf1PHY",
        local_headless=False,
        local_ready_timeout_s=20.0, 
        timeout=300.0
    )
    
    # Usamos gemini-1.5-flash por ser el más costo-eficiente para tareas de navegación
    model_name = "google/gemini-2.5-flash"

    session = client_sync.sessions.start(
        model_name=model_name,
        browser={"type": "local", "launchOptions": {"headless": False}},
    )
    sess_id = session.data.session_id
    
    logger.info(f"📍 Navegando a la lista de resultados: {results_url}")
    client_sync.sessions.navigate(id=sess_id, url=results_url)
    time.sleep(5) # Espera aumentada para asegurar que el DOM esté completamente cargado

    # 1. Extraer datos de los primeros 5 vehículos en una sola llamada (Eficiencia)
    try:
        listings_info = client_sync.sessions.extract(
            id=sess_id,
            instruction="Localiza la lista principal de resultados (ignora anuncios y recomendados). Extrae el título, año y kilometraje de los primeros 5 vehículos.",
            schema={
                "type": "object",
                "properties": {
                    "vehicles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "year": {"type": "string"},
                                "km": {"type": "string"}
                            }
                        }
                    }
                }
            }
        )
        vehicles = listings_info.data.result.get("vehicles", [])
        logger.info(f"📊 TOTAL IDENTIFICADO: {len(vehicles)} publicaciones.")
    except Exception as e:
        logger.error(f"❌ Error identificando publicaciones: {e}")
        vehicles = []

    log_token_usage("Conteo inicial")
    
    for i, v_data in enumerate(vehicles, 1):
        logger.info(f"🖱️ Procesando vehículo #{i}...")
        listing_title = v_data.get("title", "")
        listing_year = v_data.get("year", "")
        listing_km = v_data.get("km", "")

        success = False
        for attempt in range(3):  # Reintento hasta 3 veces por publicación
            try:
                # 1. Navegar de vuelta solo si no estamos en la página de resultados
                if i > 1 or attempt > 0:
                    client_sync.sessions.navigate(id=sess_id, url=results_url)
                    time.sleep(2)

                # 2. Abrir la publicación usando execute para mayor precisión
                client_sync.sessions.execute(
                    id=sess_id,
                    execute_options={
                        "instruction": f"Localiza el vehículo en la posición {i} de la lista principal. Verifica que el título coincida con '{listing_title}', el año sea '{listing_year}' y el kilometraje sea '{listing_km}'. Si coincide, haz clic en él para abrir el detalle. Ignora anuncios.",
                        "max_steps": 5,
                    },
                    agent_config={"model": {"model_name": model_name}}
                )
                time.sleep(5)

                # 3. Extraer datos del detalle y URL en una sola llamada (Eficiencia)
                detail_check = client_sync.sessions.extract(
                    id=sess_id,
                    instruction="Extrae el título principal, año, kilometraje, precio al contado, combustible, transmisión, marca, modelo, versión, ubicación y la URL actual de la página.",
                    schema={
                        "type": "object", 
                        "properties": {
                            "title": {"type": "string"},
                            "year": {"type": "string"},
                            "km": {"type": "string"},
                            "precio_contado": {"type": "string"},
                            "combustible": {"type": "string"},
                            "transmision": {"type": "string"},
                            "marca": {"type": "string"},
                            "modelo": {"type": "string"},
                            "version": {"type": "string"},
                            "ubicacion": {"type": "string"},
                            "url": {"type": "string", "format": "uri"}
                        }
                    }
                )
                d_check = detail_check.data.result
                detail_title = d_check.get("title", "")
                detail_year = d_check.get("year", "")
                detail_km = d_check.get("km", "")
                logger.info(f"📄 Detalle: {detail_title} | {detail_year} | {detail_km}")

                # 4. Validación de Encabezado, Año y KM
                def norm(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
                
                title_match = norm(listing_title) in norm(detail_title) or norm(detail_title) in norm(listing_title)
                year_match = norm(listing_year) == norm(detail_year)
                km_match = norm(listing_km) == norm(detail_km)

                if title_match and year_match and km_match:
                    logger.info(f"✅ Validación exitosa para vehículo #{i}")
                    print(f"✅ Datos vehículo {i}: {d_check}")
                    log_token_usage(f"Procesado Vehículo #{i}")
                    success = True
                    break
                else:
                    logger.warning(f"⚠️ Desajuste de datos detectado. Reintentando carga del vehículo #{i}...")

            except Exception as e:
                logger.error(f"⚠️ Error en intento {attempt+1} para vehículo {i}: {e}")
        
        if not success:
            logger.error(f"❌ No se pudo validar la apertura del vehículo #{i} tras varios intentos.")

    # End the session to clean up resources
    logger.info(f"🏁 Fin del proceso. Uso total de tokens: {usage_stats['total_tokens']}")
    client_sync.sessions.end(id=sess_id)
    client_sync.close()

if __name__ == "__main__":
    main()