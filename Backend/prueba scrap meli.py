import logging
import json
from urllib.parse import urljoin
import time
try:
    from stagehand import Stagehand
except ImportError:
    Stagehand = None

def extract_meli_details(client_sync, sess_id, results_url, max_publications, target_version, model_name, custom_instruction=None, custom_fields=None, progress_callback=None):
    """Extrae detalles de publicaciones de MeLi recopilando URLs y navegando a cada una."""
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

    all_vehicles = []
    page_number = 1

    while True:
        notify(f"📄 [MeLi] Recopilando URLs de página {page_number}...")
        try:
            listings_info = client_sync.sessions.extract(
                id=sess_id,
                instruction=f"Localiza la lista principal de resultados. Extrae el título, la versión y la URL (href) de los vehículos (máximo {max_publications}). FILTRO CRÍTICO: Solo incluye vehículos cuya versión (Sin tener en cuenta la marca y el modelo) coincida al menos en un 60% con '{target_version}'.",
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
            if page_number == 1 and not page_vehicles:
                notify(f"⚠️ No se encontraron vehículos que coincidan con '{target_version}' en el listado.")
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
        notify(f"🔍 Extrayendo detalles del vehículo {i} de {len(all_vehicles)}...")
        notify(f"🚀 [{i}/{len(all_vehicles)}] Extrayendo: {v_data.get('title', 'Vehículo')[:30]}...")
        
        try:
            client_sync.sessions.navigate(id=sess_id, url=full_detail_url)
            time.sleep(3)

            # Construir esquema dinámico
            properties = {
                "title": {"type": "string"}, "year": {"type": "string"}, "km": {"type": "number"},
                "precio_contado": {"type": "number"}, "moneda": {"type": "string"},
                "combustible": {"type": "string"}, "transmision": {"type": "string"},
                "marca": {"type": "string"}, "modelo": {"type": "string"},
                "version": {"type": "string"}, "ubicacion": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "reservado": {"type": "boolean"}
            }
            if custom_fields:
                for field in custom_fields:
                    properties[field] = {"type": "string"}

            instruction = custom_instruction or (
                "Extrae el título principal, año, kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000), "
                "precio al contado (solo el número, sin símbolos ni separadores), moneda (ARS o USD), combustible, transmisión, "
                "marca, modelo, versión, ubicación y la URL actual de la página. REGLA CRÍTICA: Extrae el precio ÚNICAMENTE de la "
                "sección de información principal del vehículo. Si el vehículo está 'Reservado' y no tiene precio propio visible, pon 0. "
                "Ignora terminantemente precios de banners de 'Otras opciones de compra', carruseles de 'autos similares' o recomendaciones.")

            detail_res = client_sync.sessions.extract(
                id=sess_id,
                instruction=instruction,
                schema={
                    "type": "object", "properties": properties
                }
            )
            item = detail_res.data.result
            if item:
                item['link'] = full_detail_url
                all_extracted_items.append(item)
        except Exception as e:
            logger.error(f"⚠️ Error en vehículo {i}: {e}")

    return all_extracted_items