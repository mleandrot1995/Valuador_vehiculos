import streamlit as st
import httpx
import pandas as pd
import json
import time
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración básica de Streamlit
st.set_page_config(page_title="AI Car Scraper", layout="wide")

st.title("🚗 AI Assisted Car Scraper")
st.markdown("### Scraping inteligente para autos usados (ej. Kavak)")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# 1. Interfaz de Usuario: Sidebar
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("API Key (Gemini/Ollama)", type="password")
    model_provider = st.selectbox("Proveedor de IA", ["gemini", "ollama"])
    base_url = st.text_input("Base URL (Ollama)", value="http://localhost:11434")
    show_browser = st.checkbox("Mostrar navegador local", value=True)
    
    st.divider()
    st.info(f"Conectado al Backend en: {BACKEND_URL}")

# Función para obtener stock
def fetch_stock():
    try:
        response = httpx.get(f"{BACKEND_URL}/stock")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

def fetch_sites():
    try:
        response = httpx.get(f"{BACKEND_URL}/sites")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

# Cuerpo principal
tab_main, tab_config = st.tabs(["🔍 Scraping", "⚙️ Configuración de Sitios"])

with tab_main:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Selección de Vehículo")
        stock_list = fetch_stock()
        
        if not stock_list:
            st.error("No se pudo cargar el stock desde la base de datos.")
            st.stop()

        df_stock = pd.DataFrame(stock_list)
        # Separar modelo y versión del campo 'modelo' de la DB (formato: "MODELO - VERSION")
        split_data = df_stock['modelo'].str.split(" - ", n=1, expand=True)
        df_stock['model_name'] = split_data[0]
        df_stock['version_name'] = split_data[1].fillna("N/A")

        # 1. Selección de Marca
        brands = sorted(df_stock['marca'].unique().tolist())
        brand = st.selectbox("Marca", options=brands)
        
        # 2. Selección de Modelo (dependiente de Marca)
        models = sorted(df_stock[df_stock['marca'] == brand]['model_name'].unique().tolist())
        model = st.selectbox("Modelo", options=models)
        
        # 3. Selección de Versión (dependiente de Modelo)
        versions = sorted(df_stock[(df_stock['marca'] == brand) & (df_stock['model_name'] == model)]['version_name'].unique().tolist())
        version = st.selectbox("Versión", options=versions)
        
        # 4. Selección de Año (dependiente de Versión)
        years = sorted(df_stock[(df_stock['marca'] == brand) & 
                                (df_stock['model_name'] == model) & 
                                (df_stock['version_name'] == version)]['anio'].unique().tolist(), reverse=True)
        year = st.selectbox("Año", options=years)

        # Obtener datos del registro seleccionado para la patente
        selected_car = df_stock[(df_stock['marca'] == brand) & 
                                (df_stock['model_name'] == model) & 
                                (df_stock['version_name'] == version) &
                                (df_stock['anio'] == year)].iloc[0]
        
        default_patente = str(selected_car['patente'])

        sites_config = fetch_sites()
        site_options = {s['site_name']: s['site_key'] for s in sites_config}
        selected_site_names = st.multiselect("Sitios a scrapear", options=list(site_options.keys()), default=list(site_options.keys()))
        selected_sites = [site_options[name] for name in selected_site_names]
        
        km_max = st.number_input("KM Máximo", min_value=0, step=5000, value=50000)
        
        with st.expander("🛠️ Configuración Avanzada (IA)"):
            st.caption("Personaliza las instrucciones que recibe el agente de IA.")
            custom_nav = st.text_area("Instrucciones de Navegación", help="Sobrescribe la lógica de búsqueda y filtros.")
            custom_extract = st.text_area("Instrucciones de Extracción", help="Sobrescribe qué datos extraer de cada publicación.")
            extra_fields = st.text_input("Campos adicionales", placeholder="ej: color, puertas, dueño_unico", help="Lista separada por comas de campos JSON adicionales.")
        
        scrape_btn = st.button("Iniciar Scraping", type="primary")
    with col2:
        st.empty() # Columna vacía para mantener el layout si no hay contenido aquí

# 3. Visualización en tiempo real (Status Box)
status_placeholder = st.empty()

# Lógica principal
if scrape_btn:
    if not api_key or not selected_sites:
        st.warning("Por favor ingrese una API Key y seleccione al menos un sitio.")
    else:
        with st.spinner("El proceso de IA puede tardar varios minutos (Navegación + Filtrado + Extracción)..."):
            status_placeholder.info("🚀 Conectando con el backend y lanzando agente IA...")
            
            payload = {
                "sites": selected_sites,
                "brand": brand,
                "model": model,
                "year": year,
                "patente": default_patente,
                "version": version,
                "km_max": km_max,
                "api_key": api_key,
                "headless": not show_browser,
                "custom_nav": custom_nav if custom_nav else None,
                "custom_extract": custom_extract if custom_extract else None,
                "extra_fields": [f.strip() for f in extra_fields.split(",")] if extra_fields else []
            }
            
            try:
                # Usamos httpx.stream para recibir actualizaciones en tiempo real
                with httpx.stream("POST", f"{BACKEND_URL}/scrape", json=payload, timeout=600.0) as response:
                    if response.status_code != 200:
                        st.error(f"Error del servidor: {response.status_code}")
                        st.stop()

                    # Contenedor para los mensajes de progreso
                    with st.status("Ejecutando proceso de IA...", expanded=True) as status_container:
                        result = None
                        for line in response.iter_lines():
                            if not line: continue
                            event = json.loads(line)
                            
                            if event["type"] == "status":
                                st.write(event["message"])
                            elif event["type"] == "final":
                                result = event
                                status_container.update(label="✅ Proceso finalizado", state="complete", expanded=True)

                    if result and result.get("status") == "success":
                        status_placeholder.success(f"✅ Scraping completado! {result['message']}")
                        
                        # 4. Tablas y Gráficos
                        if "data" in result and result["data"]:
                            tab1, tab2 = st.tabs(["🔍 Resultados de Scraping", "📈 Resultados"])
                            
                            with tab1:
                                df = pd.DataFrame(result["data"])
                                
                                # Formateo de precio para visualización con conversión
                                def display_price(row):
                                    if row['currency'] == 'USD':
                                        return f"USD {row['price']:,.0f} (≈ ${row['price_ars']:,.0f} ARS)"
                                    return f"${row['price']:,.0f} ARS"
                                
                                df['Precio'] = df.apply(display_price, axis=1)
                                
                                st.subheader("Publicaciones Encontradas")
                                
                                # Preparar DataFrame para visualización
                                df_display = df[['brand', 'model', 'version', 'year', 'km', 'Precio', 'zona', 'reservado', 'site', 'url']].copy()
                                df_display.columns = ['Marca', 'Modelo', 'Versión', 'Año', 'KM', 'Precio', 'Zona', 'Reservado', 'Sitio', 'Link']
                                df_display['Reservado'] = df_display['Reservado'].apply(lambda x: "✅" if x else "❌")

                                st.dataframe(
                                    df_display,
                                    use_container_width=True,
                                    column_config={
                                        "Link": st.column_config.LinkColumn("Link", display_text="🔗")
                                    },
                                    hide_index=True
                                )
                                
                                st.divider()
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.metric(label="Precio Promedio", value=f"${result['stats']['average_price']:,.2f} ARS")
                                with c2:
                                    st.metric(label="Vehículos Encontrados", value=len(df))
                            
                            with tab2:
                                if "updated_stock" in result and result["updated_stock"]:
                                    st.subheader("Valuación Final y Cálculos de Negocio")
                                    df_updated = pd.DataFrame(result["updated_stock"])
                                    
                                    # Convertir ratios a porcentajes (0.15 -> 15.0) para el formateador %.2f%%
                                    pct_cols = [
                                        'margenhistorico_de_gestion_de_compra', 'diferencia_pp_y_pe', 
                                        'margenhistorico_de_costo_y_pe', 'margenindexado_de_costo'
                                    ]
                                    for col in pct_cols:
                                        if col in df_updated.columns:
                                            df_updated[col] = df_updated[col].astype(float) * 100

                                    # Configuración de columnas con tooltips (help)
                                    column_config = {
                                        "patente": st.column_config.TextColumn("Patente"),
                                        "preciopropuesto": st.column_config.NumberColumn(
                                            "PM (Mercado)", 
                                            help="Precio Mercado (PM): Promedio de precios encontrados en MeLi y Kavak.",
                                            format="$%.2f"
                                        ),
                                        "margenhistorico_de_gestion_de_compra": st.column_config.NumberColumn(
                                            "Mg. Hist. Compra",
                                            help="Fórmula: (Precio Propuesto - Precio de Toma Total) / Precio Propuesto",
                                            format="%.2f%%"
                                        ),
                                        "margenindexado_de_gestion_de_venta": st.column_config.NumberColumn(
                                            "Costo 45d",
                                            help="Costo indexado a 45 días: Precio Toma Total * ((Indice Diario * max(Dias Lote, 45)) / 100 + 1)",
                                            format="$%.2f"
                                        ),
                                        "diferencia_pp_y_pe": st.column_config.NumberColumn(
                                            "Dif. PP/PE",
                                            help="Fórmula: 1 - (Precio Propuesto / Precio de Lista)",
                                            format="%.2f%%"
                                        ),
                                        "margenhistorico_de_costo_y_pe": st.column_config.NumberColumn(
                                            "Mg. Hist. Costo/PE",
                                            help="Fórmula: (Precio de Lista - Precio de Toma Total) / Precio de Lista",
                                            format="%.2f%%"
                                        ),
                                        "descuentorecargos": st.column_config.NumberColumn(
                                            "Desc./Recargos",
                                            help="Fórmula: Precio de Venta - Precio de Lista",
                                            format="$%.2f"
                                        ),
                                        "margenindexado_de_costo": st.column_config.NumberColumn(
                                            "Mg. Idx. Costo",
                                            help="Fórmula: (Descuento Recargo - Costo Indexado a X días de Venta) / Descuento Recargo",
                                            format="%.2f%%"
                                        ),
                                        "cuenta": st.column_config.NumberColumn(
                                            "Cuenta",
                                            help="Fórmula: (((2024 - Año) * 15000) - KM) / 5000 * 0.75%",
                                            format="%.4f"
                                        ),
                                        "preciodeventa": st.column_config.NumberColumn("P. Venta", format="$%.2f"),
                                        "meli": st.column_config.NumberColumn("MeLi", format="$%.2f"),
                                        "kavak": st.column_config.NumberColumn("Kavak", format="$%.2f"),
                                    }

                                    # Seleccionar columnas para mostrar
                                    cols_to_show = [
                                        'patente', 'preciopropuesto', 'margenhistorico_de_gestion_de_compra', 
                                        'margenindexado_de_gestion_de_venta', 'diferencia_pp_y_pe', 
                                        'margenhistorico_de_costo_y_pe', 'descuentorecargos', 
                                        'margenindexado_de_costo', 'cuenta', 'preciodeventa', 'meli', 'kavak'
                                    ]
                                    
                                    existing_cols = [c for c in cols_to_show if c in df_updated.columns]
                                    
                                    st.dataframe(
                                        df_updated[existing_cols],
                                        use_container_width=True,
                                        column_config=column_config,
                                        hide_index=True
                                    )
                                    
                        else:
                            st.warning("El scraping terminó pero no se extrajeron vehículos válidos.")
                    elif result:
                        st.error(f"Error en el scraping: {result.get('message')}")
                        if "data" in result:
                            st.json(result["data"])
                    else:
                        st.error("No se recibió una respuesta final del servidor.")
                    
            except httpx.ReadTimeout:
                st.error("⏳ Error: La solicitud tardó demasiado (Timeout). El backend sigue trabajando, pero la conexión se cerró.")
            except httpx.ConnectError:
                st.error("🔌 No se pudo conectar al Backend. Asegúrese de que esté corriendo en el puerto 8000.")
            except Exception as e:
                st.error(f"❌ Ocurrió un error inesperado: {str(e)}")

# Sección de historial (simulada)

with tab_config:
    st.subheader("Gestión de Framework Modular")
    sites = fetch_sites()
    if sites:
        site_to_edit = st.selectbox("Seleccionar Sitio para configurar", options=[s['site_key'] for s in sites])
        
        instr_resp = httpx.get(f"{BACKEND_URL}/instructions/{site_to_edit}")
        if instr_resp.status_code == 200:
            all_instr = instr_resp.json()
            if all_instr:
                current = all_instr[0]
                st.write(f"Versión actual activa: {current['version']}")
                
                # Inicializar buffer de pasos en session_state
                if "steps_buffer" not in st.session_state or st.session_state.get("current_site_key") != site_to_edit:
                    st.session_state.steps_buffer = current.get('steps') or []
                    st.session_state.current_site_key = site_to_edit

                st.markdown("### 🛠️ Constructor Visual de Pasos")
                st.info("Define la secuencia de acciones. Usa variables como `{brand}`, `{model}`, `{year}`, `{version}`.")
                
                # Visualizador de Pasos Actuales
                if st.session_state.steps_buffer:
                    for i, step in enumerate(st.session_state.steps_buffer):
                        step_type = step.get('type', 'unknown')
                        
                        # Descripción amigable
                        desc = ""
                        if step_type == "navigate": desc = f"🌐 Ir a: {step.get('url', '')}"
                        elif step_type == "action": desc = f"🤖 Acción: {step.get('instruction', '')}"
                        elif step_type == "extract": desc = f"📄 Extraer: {step.get('instruction', '')}"
                        elif step_type == "validate": desc = f"⛔ Validar: {step.get('instruction', '')}"
                        elif step_type == "wait": desc = f"⏳ Esperar {step.get('seconds', '')}s"
                        elif step_type == "iterator": desc = f"🔄 Bucle: {step.get('instruction', '')}"
                        
                        with st.expander(f"Paso {i+1}: {desc[:80]}...", expanded=False):
                            # Edición de campos del paso
                            for key in step.keys():
                                if key == "type": continue
                                if isinstance(step[key], (str, int, float)):
                                    step[key] = st.text_input(f"Campo: {key}", value=str(step[key]), key=f"edit_{i}_{key}")
                                elif isinstance(step[key], dict):
                                    step[key] = json.loads(st.text_area(f"Campo: {key} (JSON)", value=json.dumps(step[key], indent=2), key=f"edit_{i}_{key}"))
                            
                            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                            with c1:
                                if i > 0 and st.button("⬆️", key=f"up_{i}", help="Subir paso"):
                                    st.session_state.steps_buffer[i], st.session_state.steps_buffer[i-1] = st.session_state.steps_buffer[i-1], st.session_state.steps_buffer[i]
                                    st.rerun()
                            with c2:
                                if i < len(st.session_state.steps_buffer)-1 and st.button("⬇️", key=f"dw_{i}", help="Bajar paso"):
                                    st.session_state.steps_buffer[i], st.session_state.steps_buffer[i+1] = st.session_state.steps_buffer[i+1], st.session_state.steps_buffer[i]
                                    st.rerun()
                            with c3:
                                if st.button("📋", key=f"dup_{i}", help="Duplicar paso"):
                                    st.session_state.steps_buffer.insert(i+1, step.copy())
                                    st.rerun()
                            with c4:
                                if st.button("🗑️", key=f"del_{i}", type="primary", help="Eliminar paso"):
                                    st.session_state.steps_buffer.pop(i)
                                    st.rerun()
                else:
                    st.info("No hay pasos definidos.")

                st.divider()
                
                # Formulario para Agregar Nuevo Paso
                with st.container(border=True):
                    st.markdown("#### ➕ Nuevo Paso")
                    step_type = st.selectbox("Tipo", ["navigate", "action", "extract", "validate", "wait", "iterator"], key="new_step_type")
                    new_step_data = {"type": step_type}
                    
                    if step_type == "navigate":
                        new_step_data["url"] = st.text_input("URL", placeholder="https://www.sitio.com/autos?marca={brand}")
                    elif step_type == "action":
                        new_step_data["instruction"] = st.text_area("Instrucción", placeholder="Haz clic en el botón 'Buscar'...")
                    elif step_type == "extract":
                        new_step_data["instruction"] = st.text_area("Instrucción", placeholder="Extrae los detalles del vehículo...")
                        # Autocompletado visual de campos
                        original_fields = ["titulo", "precio", "moneda", "km", "año", "marca", "modelo", "version", "combustible", "transmision", "zona", "reservado", "fecha_publicacion"]
                        selected_fields = st.multiselect("Campos a extraer", options=original_fields, default=original_fields)
                        new_step_data["schema"] = {"type": "object", "properties": {f: {"type": "string" if f not in ["precio", "km", "año", "reservado"] else "number" if f != "reservado" else "boolean"} for f in selected_fields}}
                    elif step_type == "validate":
                        new_step_data["instruction"] = st.text_area("Instrucción", placeholder="Verifica si hay resultados...")
                        new_step_data["schema"] = {"type": "object", "properties": {"check": {"type": "boolean"}}}
                        new_step_data["exit_on_false"] = "check"
                    elif step_type == "wait":
                        new_step_data["seconds"] = st.number_input("Segundos", min_value=1, value=3)
                    elif step_type == "iterator":
                        new_step_data["instruction"] = st.text_area("Instrucción de Lista", placeholder="Extrae la lista de vehículos...")
                        new_step_data["limit"] = st.number_input("Límite", min_value=1, value=5)
                        new_step_data["schema"] = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"url": {"type": "string"}}}}}}
                        # Sub-pasos por defecto para el bucle
                        new_step_data["steps"] = [
                            {"type": "navigate", "url": "{item.url}"},
                            {"type": "wait", "seconds": 3},
                            {"type": "extract", "instruction": "Extrae detalles.", "schema": {"type": "object", "properties": {"precio": {"type": "number"}}}}
                        ]

                    if st.button("➕ Agregar Paso"):
                        st.session_state.steps_buffer.append(new_step_data)
                        st.rerun()

                st.divider()

                with st.form(f"edit_form_{site_to_edit}"):
                    st.caption("Guarda la configuración completa")
                    new_rules = st.text_area("Reglas Globales (JSON)", value=json.dumps(current.get('validation_rules') or {}, indent=2), height=100)
                    
                    if st.form_submit_button("Guardar y Activar Nueva Versión"):
                        try:
                            payload = {
                                "site_key": site_to_edit,
                                "navigation_instruction": "MODULAR_FLOW",
                                "extraction_instruction": "MODULAR_FLOW",
                                "validation_rules": json.loads(new_rules),
                                "extraction_schema": {},
                                "steps": st.session_state.steps_buffer,
                                "is_active": True
                            }
                            save_resp = httpx.post(f"{BACKEND_URL}/instructions", json=payload)
                            if save_resp.status_code == 200:
                                st.success(f"Versión {save_resp.json()['version']} activada correctamente.")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error en formato JSON: {e}")
            else:
                st.warning("No hay instrucciones para este sitio.")
    else:
        st.error("No se encontraron sitios configurados.")

st.divider()
st.subheader("ℹ️ Notas del Framework")
st.info("Este sistema utiliza un enfoque modular. Cada sitio tiene su propia lógica definida en la base de datos y un archivo Python correspondiente en el backend.")
