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

def extract_kavak_details(client_sync, sess_id, results_url, max_publications, target_version, model_name, custom_instruction=None, custom_fields=None, progress_callback=None):
    """Extrae detalles de publicaciones de Kavak utilizando la lógica de navegación y clic."""
    logger = logging.getLogger(__name__)

    def notify(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

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

    # 1. Extraer datos de los vehículos en una sola llamada (Eficiencia)
    try:
        listings_info = client_sync.sessions.extract(
            id=sess_id,
            instruction=f"Localiza la lista principal de resultados (ignora anuncios y recomendados). Extrae el título, año y kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000) de los primeros {max_publications} vehículos.",
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
                                "km": {"type": "number"}
                            }
                        }
                    }
                }
            }
        )
        vehicles = listings_info.data.result.get("vehicles", [])
        if not vehicles:
            notify("⚠️ No se encontraron vehículos en el listado de resultados.")
            return []
        notify(f"📊 TOTAL IDENTIFICADO: {len(vehicles)} publicaciones.")
    except Exception as e:
        logger.error(f"❌ Error identificando publicaciones: {e}")
        vehicles = []

    log_token_usage("Conteo inicial")
    
    all_extracted_items = []
    for i, v_data in enumerate(vehicles, 1):
        notify(f"🖱️ Procesando vehículo #{i} de {len(vehicles)}...")
        listing_title = v_data.get("title", "")
        listing_year = v_data.get("year", "")
        listing_km = v_data.get("km", "")

        success = False
        for attempt in range(3):  # Reintento hasta 3 veces por publicación
            try:
                client_sync.sessions.navigate(id=sess_id, url=results_url) # Vuelve a la lista filtrada
                time.sleep(2)

                notify(f"🔍 Abriendo detalle del vehículo #{i}...")
                client_sync.sessions.execute(
                    id=sess_id,
                    execute_options={
                        "instruction": f"Localiza el vehículo en la posición {i} de la lista principal. Verifica que el título coincida con '{listing_title}', el año sea '{listing_year}' y el kilometraje sea '{listing_km}'. Si coincide, haz clic en él para abrir el detalle. Ignora anuncios.",
                        "max_steps": 5,
                    },
                    agent_config={"model": {"model_name": model_name}}
                )
                time.sleep(5)

                # Construir esquema dinámico para soportar campos personalizados
                properties = {
                    "title": {"type": "string"}, "year": {"type": "string"}, "km": {"type": "number"},
                    "precio_contado": {"type": "number"}, "moneda": {"type": "string"},
                    "combustible": {"type": "string"}, "transmision": {"type": "string"},
                    "marca": {"type": "string"}, "modelo": {"type": "string"},
                    "version": {"type": "string"}, "ubicacion": {"type": "string"},
                    "url": {"type": "string", "format": "uri"},
                    "reservado": {"type": "boolean", "description": "Indica si el vehículo aparece como 'Reservado'"}
                }
                if custom_fields:
                    for field in custom_fields:
                        properties[field] = {"type": "string"}

                instruction = custom_instruction or "Extrae el título principal, año, kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000), precio al contado (solo el número, sin símbolos ni separadores), moneda (ARS o USD), combustible, transmisión, marca, modelo, versión, ubicación y la URL actual de la página. REGLA CRÍTICA: Extrae el precio ÚNICAMENTE de la sección de información principal del vehículo. Si el vehículo está 'Reservado' y no tiene precio propio visible, pon 0. Ignora terminantemente precios de banners de 'Otras opciones de compra', carruseles de 'autos similares' o recomendaciones."

                detail_check = client_sync.sessions.extract(
                    id=sess_id,
                    instruction=instruction,
                    schema={
                        "type": "object", "properties": properties
                    }
                )
                item = detail_check.data.result
                if item:
                    detail_year = item.get("year", "")
                    detail_km = item.get("km", "")
                    notify(f"📄 Detalle: {detail_year} | {detail_km}")

                    # Validación de Encabezado, Año y KM
                    def norm(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
                    
                    year_match = norm(listing_year) == norm(detail_year)
                    km_match = norm(listing_km) == norm(detail_km)

                    if year_match and km_match:
                        logger.info(f"✅ Validación exitosa para vehículo #{i}")
                        all_extracted_items.append(item)
                        log_token_usage(f"Procesado Vehículo #{i}")
                        success = True
                        break
                    else:
                        notify(f"⚠️ Datos no coinciden en vehículo #{i} (Intento {attempt+1}).")
                        logger.warning(f"⚠️ Desajuste de datos detectado en intento {attempt+1}. Reintentando...")
            except Exception as e:
                logger.error(f"⚠️ Error en intento {attempt+1} para vehículo {i}: {e}")
        
        if not success:
            logger.error(f"❌ No se pudo validar la apertura del vehículo #{i} tras varios intentos.")
    
    return all_extracted_items

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    results_url = "https://www.kavak.com/ar/usados?maker=toyota&model=corolla&status=disponible&year=2021&order=relevance"
    target_version = "1.8 SE-G CVT L17"
    max_publications = 5  # Límite de publicaciones a extraer

    #results_url = "https://autos.mercadolibre.com.ar/toyota/corolla/2021/_ITEM*CONDITION_2230581#applied_filter_id%3DVEHICLE_YEAR%26applied_filter_name%3DA%C3%B1o%26applied_filter_order%3D8%26applied_value_id%3D%5B2021-2021%5D%26applied_value_name%3D2021%26applied_value_order%3D6%26applied_value_results%3D136%26is_custom%3Dfalse"
    
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
    results = extract_kavak_details(client_sync, sess_id, results_url, max_publications, target_version, model_name)
    for i, res in enumerate(results, 1):
        print(f"✅ Datos vehículo {i}: {res}")

    # End the session to clean up resources
    logger.info(f"🏁 Fin del proceso. Uso total de tokens: {usage_stats['total_tokens']}")
    client_sync.sessions.end(id=sess_id)
    client_sync.close()

if __name__ == "__main__":
    main()