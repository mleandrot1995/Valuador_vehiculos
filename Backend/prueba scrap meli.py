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

def extract_meli_details(client_sync, sess_id, results_url, max_publications, target_version, model_name):
    """Extrae detalles de publicaciones de MeLi recopilando URLs y navegando a cada una."""
    logger = logging.getLogger(__name__)
    usage_stats = {"total_tokens": 0}

    def log_token_usage(action_name):
        """Obtiene y muestra el uso de tokens acumulado y el delta de la acción."""
        try:
            metrics = client_sync.sessions.get_metrics(id=sess_id) # Retoma la sesión heredada
            new_total = metrics.data.total_tokens
            delta = new_total - usage_stats["total_tokens"]
            usage_stats["total_tokens"] = new_total
            logger.info(f"📊 [Tokens] {action_name} - Usados: {delta} | Total acumulado: {new_total}")
        except Exception as e:
            logger.debug(f"⚠️ No se pudieron obtener métricas: {e}")

    all_vehicles = []
    page_number = 1

    while True:
        logger.info(f"📄 [MeLi] Recopilando URLs de página {page_number} desde la sesión activa...")
        try:
            listings_info = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Localiza la lista principal de resultados. Extrae el título, la versión y la URL (href) de los vehículos (máximo {max_publications}). FILTRO CRÍTICO: Solo incluye vehículos cuya versión (Sin tener en cuenta la marca y el modelo) coincida al menos en un 82% con '{target_version}'.",
                schema={
                    "type": "object",
                    "properties": {
                        "vehicles": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "version": {"type": "string"},
                                    "url": {"type": "string", "format": "uri"}
                                }
                            }
                        }
                    }
                }
            )
            page_vehicles = listings_info.data.result.get("vehicles", [])
            all_vehicles.extend(page_vehicles)
            if len(all_vehicles) >= max_publications:
                all_vehicles = all_vehicles[:max_publications]
                break
        except Exception as e:
            logger.error(f"❌ Error en página {page_number}: {e}")

        pagination_check = client_sync.sessions.extract(
            id=sess_id,
            instruction="Verifica si existe un botón 'Siguiente' habilitado a nivel paginas.",
            schema={"type": "object", "properties": {"has_next": {"type": "boolean"}}}
        )
        
        if pagination_check.data.result.get("has_next"):
            client_sync.sessions.execute(
                id=sess_id,
                execute_options={"instruction": "Haz clic en 'Siguiente'.", "max_steps": 3},
                agent_config={"model": {"model_name": model_name}}
            )
            time.sleep(5)
            page_number += 1
        else:
            break

    all_extracted_items = []
    for i, v_data in enumerate(all_vehicles, 1):
        listing_url = v_data.get("url")
        if not listing_url: continue
        
        full_detail_url = urljoin(results_url, listing_url)
        logger.info(f"🚀 [{i}/{len(all_vehicles)}] Navegando a: {full_detail_url}")
        
        try:
            client_sync.sessions.navigate(id=sess_id, url=full_detail_url)
            time.sleep(3)
            
            detail_res = client_sync.sessions.extract(
                id=sess_id,
                instruction="Extrae el título principal, año, kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000), precio al contado (solo el número, sin símbolos ni separadores), moneda (ARS o USD), combustible, transmisión, marca, modelo, versión, ubicación y la URL actual de la página. REGLA CRÍTICA: Extrae el precio ÚNICAMENTE de la sección de información principal del vehículo. Si el vehículo está 'Reservado' y no tiene precio propio visible, pon 0. Ignora terminantemente precios de banners de 'Otras opciones de compra', carruseles de 'autos similares' o recomendaciones.",
                schema={
                    "type": "object", 
                    "properties": {
                        "title": {"type": "string"}, "year": {"type": "string"}, "km": {"type": "number"},
                        "precio_contado": {"type": "number"}, "moneda": {"type": "string"},
                        "combustible": {"type": "string"}, "transmision": {"type": "string"},
                        "marca": {"type": "string"}, "modelo": {"type": "string"},
                        "version": {"type": "string"}, "ubicacion": {"type": "string"},
                        "url": {"type": "string", "format": "uri"},
                        "reservado": {"type": "boolean", "description": "Indica si el vehículo aparece como 'Reservado'"}
                    }
                }
            )
            item = detail_res.data.result
            if item:
                item['link'] = full_detail_url
                all_extracted_items.append(item)
        except Exception as e:
            logger.error(f"⚠️ Error en vehículo {i}: {e}")

    return all_extracted_items

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    results_url = "https://autos.mercadolibre.com.ar/chevrolet/agile/2014/_ITEM*CONDITION_2230581#applied_filter_id%3DVEHICLE_YEAR%26applied_filter_name%3DA%C3%B1o%26applied_filter_order%3D8%26applied_value_id%3D%5B2014-2014%5D%26applied_value_name%3D2014%26applied_value_order%3D4%26applied_value_results%3D49%26is_custom%3Dfalse"
    
    target_version = "AGILE - 1.4 LT L09"
    max_publications = 5  # Límite de publicaciones a extraer
    
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

    # Llamada a la función modularizada para pruebas
    results = extract_meli_details(client_sync, sess_id, results_url, max_publications, target_version, model_name)
    for i, res in enumerate(results, 1):
        print(f"✅ Datos vehículo {i}: {res}")

    # End the session to clean up resources
    logger.info(f"🏁 Fin del proceso. Uso total de tokens: {usage_stats['total_tokens']}")
    client_sync.sessions.end(id=sess_id)
    client_sync.close()

if __name__ == "__main__":
    main()