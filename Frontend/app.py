import streamlit as st
import httpx
import pandas as pd
import json
import time
import os
import re
from datetime import datetime
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
@st.cache_data(ttl=60)
def fetch_stock():
    try:
        response = httpx.get(f"{BACKEND_URL}/stock")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

# Cuerpo principal
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

    selected_sites = st.multiselect("Sitios a scrapear", ["Kavak", "Mercado Libre"], default=["Kavak"])
    km_max = st.number_input("KM Máximo", min_value=0, step=5000, value=50000)

# --- SECCIÓN: CONFIGURACIÓN PERSONALIZADA (Fuera de columnas para máximo ancho) ---
st.divider()
with st.expander("🛠️ Personalizar Instrucciones de IA", expanded=False):
    # Definición de instrucciones por defecto (Itemizado agradable)
    DEFAULT_NAV_KAVAK = (
        "**Cookies:** Si aparece un cartel de cookies o selección de país/región, acéptalo o ciérralo.\n"
        "**Sección:** Asegúrate de estar en la sección de compra de autos o categoria de Vehiculos (Marketplace). Si estás en la home, busca el botón 'Comprar un auto', Categoria 'Vehiculos' o similar.\n"
        "**Verificación:** Verificar si se observan los filtros de búsqueda, en caso de que no se hallen hacer clic en la barra de búsqueda (entry point) para ver filtros si corresponde CASO CONTRARIO NO HACER NADA.\n"
        "**Regla Crítica:** Si no encuentras el valor exacto solicitado para CUALQUIERA de los filtros (Marca, Modelo, etc.), DETÉN el proceso inmediatamente. No intentes seleccionar valores similares ni continúes con el resto de los pasos.\n"
        "**Filtros:** Aplica los filtros: Marca (puede tener otros nombres considerar todas las variantes posibles): '{marca}', Modelo (puede tener otros nombres considerar todas las variantes posibles): '{modelo}', Año (puede tener otros nombres considerar todas las variantes posibles): '{anio}' y Disponibilidad de auto (puede tener otros nombres considerar todas las variantes posibles): 'Disponible' (o similar). Los filtros pueden aparecer como botones, enlaces o listas desplegables. Busca específicamente el botón o enlace con el texto '{anio}'. Si no lo ves, expande la sección correspondiente o busca un botón de 'Ver más'.\n"
        "**Orden:** Ordenar las publicaciones por 'Relevancia'.\n"
        "**Scroll:** Haz scroll para cargar los resultados."
    )
    DEFAULT_EXT_KAVAK = (
        "**Extracción:**"
        "   Extraer:.\n"
        "   *   Título principal.\n"
        "   *   Año.\n"
        "   *   Kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000).\n"
        "   *   Precio al contado (solo el número, sin símbolos ni separadores).\n"
        "   *   Moneda (ARS o USD).\n"
        "   *   Combustible.\n"
        "   *   transmisión.\n"
        "   *   Marca.\n"
        "   *   Modelo.\n"
        "   *   Versión.\n"
        "   *   Ubicación.\n"
        "   *   URL actual de la página.\n"
        "**Regla Críticas:**.\n"
        "   *   Extrae el precio ÚNICAMENTE de la sección de información principal del vehículo.\n"
        "   *   Si el vehículo está 'Reservado' y no tiene precio propio visible, pon 0. "
        "   *   Ignora terminantemente precios de banners de 'Otras opciones de compra', carruseles de 'autos similares' o recomendaciones."
    )
    
    DEFAULT_NAV_MELI = (
        "**Objetivo:** Encontrar un vehículo {marca} {modelo} usado del año {anio}, evitando accesorios o repuestos.\n"
        "**Búsqueda:** Localiza el buscador principal en la parte superior (header) y escribe '{marca} {modelo}'. Presiona Enter o haz clic en la lupa para buscar.\n"
        "**Condición:** En la barra lateral, busca la sección de 'Condición' y selecciona específicamente 'Usado'.\n"
        "**Año:** Busca la sección 'Año' en los filtros laterales. Selecciona exactamente el año '{anio}'. Si no ves el año '{anio}' en la lista, haz clic en 'Mostrar más' o 'Ver todos' dentro de esa sección hasta encontrarlo.\n"
        "**Verificación:** Si aparece un mensaje de 'No hay publicaciones que coincidan', informa 'Sin stock'. Si hay resultados, realiza un scroll suave para asegurar que se carguen las unidades y confirma que el catálogo sea de vehículos reales."
    )
    DEFAULT_EXT_MELI = (
        "**Extracción:**"
        "   Extraer:.\n"
        "   *   Título principal.\n"
        "   *   Año.\n"
        "   *   Kilometraje (solo el número, interpretando 'k' como mil, ej: 136k km = 136000).\n"
        "   *   Precio al contado (solo el número, sin símbolos ni separadores).\n"
        "   *   Moneda (ARS o USD).\n"
        "   *   Combustible.\n"
        "   *   transmisión.\n"
        "   *   Marca.\n"
        "   *   Modelo.\n"
        "   *   Versión.\n"
        "   *   Ubicación.\n"
        "   *   URL actual de la página.\n"
        "**Regla Críticas:**.\n"
        "   *   Extrae el precio ÚNICAMENTE de la sección de información principal del vehículo.\n"
        "   *   Si el vehículo está 'Reservado' y no tiene precio propio visible, pon 0. "
        "   *   Ignora terminantemente precios de banners de 'Otras opciones de compra', carruseles de 'autos similares' o recomendaciones."
    )

    # Inicialización de session state
    if "nav_kavak" not in st.session_state: st.session_state.nav_kavak = DEFAULT_NAV_KAVAK
    if "ext_kavak" not in st.session_state: st.session_state.ext_kavak = DEFAULT_EXT_KAVAK
    if "nav_meli" not in st.session_state: st.session_state.nav_meli = DEFAULT_NAV_MELI
    if "ext_meli" not in st.session_state: st.session_state.ext_meli = DEFAULT_EXT_MELI
    if "edit_mode_kavak" not in st.session_state: st.session_state.edit_mode_kavak = False
    if "edit_mode_meli" not in st.session_state: st.session_state.edit_mode_meli = False
    if "execution_logs" not in st.session_state: st.session_state.execution_logs = []

    tab_k, tab_m = st.tabs(["🏢 Kavak", "🛍️ Mercado Libre"])
    
    def render_instruction_editor(site_label, nav_key, ext_key, default_nav, default_ext):
        st.caption(f"Personaliza cómo el agente interactúa con {site_label}")
        
        def highlight_text(text):
            # Negrita verde oscuro para lo encerrado en ** (Encabezados)
            text = re.sub(r"\*\*(.*?)\*\*", r'<span style="color: #006400; font-weight: bold;">\1</span>', text)
            # Negrita azul oscuro para las variables {v} (Invocaciones)
            text = re.sub(r"\{(.*?)\}", r'<span style="color: #00008B; font-weight: bold;">{\1}</span>', text)
            return text.replace("\n", "<br>")

        edit_mode_key = f"edit_mode_{nav_key.split('_')[-1]}"

        if not st.session_state[edit_mode_key]:
            # --- MODO VISUALIZACIÓN ---
            with st.container(border=True):
                nav_val = st.session_state.get(nav_key, default_nav)
                ext_val = st.session_state.get(ext_key, default_ext)
                st.markdown(f"""
                    <div style="background-color: #fdfdfd; padding: 15px; border-radius: 8px; border: 1px solid #eee; font-family: sans-serif; font-size: 0.95em; line-height: 1.6;">
                        <div style="margin-bottom: 10px;">
                            <strong style="color: #555;">Instrucciones de navegación:</strong><br>
                            {highlight_text(nav_val)}
                        </div>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #ddd;">
                        <div>
                            <strong style="color: #555;">Instrucciones de extracción:</strong><br>
                            {highlight_text(ext_val)}
                        </div>
                    </div>
                """, unsafe_allow_html=True)

            if st.button(f"📝 Editar Instrucciones {site_label}", key=f"btn_edit_{nav_key}", use_container_width=True):
                st.session_state[edit_mode_key] = True
                # Inicializar valores temporales para la edición
                st.session_state[f"temp_{nav_key}"] = st.session_state.get(nav_key, default_nav)
                st.session_state[f"temp_{ext_key}"] = st.session_state.get(ext_key, default_ext)
                st.rerun()
        else:
            # --- MODO EDICIÓN ---
            st.markdown("**Variables dinámicas (Haz clic para insertar):**")
            v_cols = st.columns([1, 1, 1, 1, 2])
            if v_cols[0].button("🏷️ Marca", key=f"btn_marca_{nav_key}"): 
                st.session_state[f"temp_{nav_key}"] += " {marca}"
                st.rerun()
            if v_cols[1].button("🚘 Modelo", key=f"btn_modelo_{nav_key}"): 
                st.session_state[f"temp_{nav_key}"] += " {modelo}"
                st.rerun()
            if v_cols[2].button("📅 Año", key=f"btn_anio_{nav_key}"): 
                st.session_state[f"temp_{nav_key}"] += " {anio}"
                st.rerun()
            if v_cols[3].button("🔧 Versión", key=f"btn_version_{nav_key}"): 
                st.session_state[f"temp_{nav_key}"] += " {version}"
                st.rerun()
            
            if v_cols[4].button("🔄 Restablecer", key=f"btn_reset_{nav_key}", help="Vuelve a las instrucciones originales"):
                st.session_state[f"temp_{nav_key}"] = default_nav
                st.session_state[f"temp_{ext_key}"] = default_ext
                st.rerun()

            st.markdown('<strong style="color: #555;">Instrucciones de navegación:</strong>', unsafe_allow_html=True)
            st.text_area("Editor de Navegación", height=250, key=f"temp_{nav_key}", label_visibility="collapsed")
            
            st.markdown('<strong style="color: #555;">Instrucciones de extracción:</strong>', unsafe_allow_html=True)
            st.text_area("Editor de Extracción", height=200, key=f"temp_{ext_key}", label_visibility="collapsed")

            c1, c2 = st.columns(2)
            if c1.button("💾 Guardar", key=f"btn_save_{nav_key}", use_container_width=True, type="primary"):
                st.session_state[nav_key] = st.session_state[f"temp_{nav_key}"]
                st.session_state[ext_key] = st.session_state[f"temp_{ext_key}"]
                st.session_state[edit_mode_key] = False
                st.rerun()
            if c2.button("✖️ Cerrar sin guardar", key=f"btn_cancel_{nav_key}", use_container_width=True):
                st.session_state[edit_mode_key] = False
                st.rerun()

    with tab_k:
        render_instruction_editor("Kavak", "nav_kavak", "ext_kavak", DEFAULT_NAV_KAVAK, DEFAULT_EXT_KAVAK)

    with tab_m:
        render_instruction_editor("Mercado Libre", "nav_meli", "ext_meli", DEFAULT_NAV_MELI, DEFAULT_EXT_MELI)

    custom_fields = st.text_input("Campos adicionales (separados por coma)", 
                                placeholder="color, unico_dueño, garantia",
                                help="Escribe atributos extra que quieras que la IA busque (ej: color, estado, accesorios). Se guardarán en la base de datos como información adicional.")

scrape_btn = st.button("Iniciar Scraping", type="primary", use_container_width=True)


# 3. Visualización en tiempo real (Status Box)
status_placeholder = st.empty()

# Lógica principal
if scrape_btn:
    if not api_key or not selected_sites:
        st.warning("Por favor ingrese una API Key y seleccione al menos un sitio.")
    else:
        st.session_state.execution_logs = [] # Reiniciar logs para nueva ejecución
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
                "nav_instr_kavak": st.session_state.nav_kavak,
                "ext_instr_kavak": st.session_state.ext_kavak,
                "nav_instr_meli": st.session_state.nav_meli,
                "ext_instr_meli": st.session_state.ext_meli,
                "custom_fields": [f.strip() for f in custom_fields.split(",")] if custom_fields else [],
                "headless": not show_browser
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
                                now = datetime.now().strftime("%H:%M:%S")
                                msg = event["message"]
                                st.session_state.execution_logs.append({"message": msg, "time": now})
                                # Mostrar con la hora a la derecha usando HTML
                                st.markdown(f"{msg} <span style='float:right; color:gray; font-size:0.85em;'>{now}</span>", unsafe_allow_html=True)
                            elif event["type"] == "final":
                                result = event
                                status_container.update(label="✅ Proceso finalizado", state="complete", expanded=True)

                    if result and result.get("status") == "success":
                        status_placeholder.success(f"✅ Scraping completado! {result['message']}")
                        
                        # 4. Tablas y Gráficos
                        if "data" in result and result["data"]:
                            tab1, tab2, tab3 = st.tabs(["🔍 Resultados de Scraping", "📈 Resultados", "📋 Log de Proceso"])
                            
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
                                    
                            with tab3:
                                st.subheader("Historial detallado del proceso")
                                for log in st.session_state.execution_logs:
                                    st.markdown(f"<div style='display: flex; justify-content: space-between; border-bottom: 1px solid #eee; padding: 5px 0;'><span>{log['message']}</span><span style='color: gray; font-family: monospace;'>{log['time']}</span></div>", unsafe_allow_html=True)

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
st.divider()
st.subheader("ℹ️ Notas del Agente")
st.info("El agente IA realiza navegación visual. Si ve que el navegador se queda detenido, verifique si hay algún CAPTCHA o interacción manual requerida.")
