import streamlit as st
import httpx
import pandas as pd
import json
import time
import os
import re
import base64
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración básica de Streamlit
st.set_page_config(page_title="AI assistant", layout="wide", initial_sidebar_state="collapsed")

# Aplicar Look & Feel de Carone
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&display=swap');
    /* Importar Material Icons Round para asegurar que los iconos se rendericen correctamente */
    @import url('https://fonts.googleapis.com/icon?family=Material+Icons+Round');

    /* Aplicar fuente Montserrat a toda la aplicación */
    html, body, [class*="css"], [class*="st-"], .stApp {
        font-family: 'Montserrat', sans-serif !important;
        color: rgb(0, 129, 186) !important;
    }

    /* REGLA CRÍTICA PARA ICONOS: Restaurar la fuente de iconos */
    [data-testid="stIconMaterial"], 
    .st-emotion-cache-16idsys, 
    .st-emotion-cache-1pbqdg3,
    .material-icons-round,
    span[class*="material-symbols"],
    span[class*="material-icons"] {
        font-family: 'Material Icons Round', 'Material Icons', sans-serif !important;
        font-weight: normal !important;
        font-style: normal !important;
        font-feature-settings: "liga" !important;
        -webkit-font-feature-settings: "liga" !important;
        text-transform: none !important;
        letter-spacing: normal !important;
        word-wrap: normal !important;
        white-space: nowrap !important;
        direction: ltr !important;
    }

    /* Color institucional para textos generales */
    .stMarkdown, p, label, li, .stMetric div, [data-testid="stExpander"] p, .stSelectbox div, .stMultiSelect div, h1, h2, h3, h4, h5, h6 {
        color: rgb(0, 129, 186) !important;
    }

    /* Azul Carone para encabezados */
    h1, h2, h3, .stSubheader {
        color: #0081BA !important;
        font-weight: 700 !important;
    }

    /* Estilo del Sidebar */
    [data-testid="stSidebar"] {
        background-color: #f0f2f6;
        margin-top: 110px !important;
        z-index: 99999 !important;
    }

    /* Ajustar el botón de colapsar/expandir para que no quede bajo el header */
    [data-testid="stSidebarCollapsedControl"] {
        top: 120px !important;
        left: 20px !important;
        z-index: 1000001 !important;
        background-color: rgb(0, 129, 186) !important;
        border-radius: 8px !important;
        width: auto !important;
        height: auto !important;
        padding: 6px 10px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        border: 1px solid white !important;
        transition: background-color 0.3s ease !important;
    }
    [data-testid="stSidebarCollapsedControl"]:hover {
        background-color: #005f8a !important;
    }
    [data-testid="stSidebarCollapsedControl"] svg {
        fill: white !important;
        width: 24px !important;
        height: 24px !important;
    }
    
    /* Botones Primarios */
    div.stButton > button:first-child {
        background-color: #0081BA;
        color: white !important;
        border-radius: 4px;
        border: none;
        font-weight: 600;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }
    div.stButton > button p, div.stButton > button span {
        color: white !important;
    }
    
    div.stButton > button:first-child:hover {
        background-color: #005f8a;
        border: none;
        color: white !important;
    }
    div.stButton > button:first-child:hover p, div.stButton > button:first-child:hover span {
        color: white !important;
    }

    /* Multiselect Tags (Sitios a scrapear) */
    [data-baseweb="tag"] {
        background-color: #0081BA !important;
    }
    [data-baseweb="tag"] span {
        color: white !important;
    }
    [data-baseweb="tag"] svg {
        fill: white !important;
    }

    /* Métricas */
    [data-testid="stMetricValue"] {
        color: #0081BA;
        font-weight: 700;
        font-family: 'Montserrat', sans-serif !important;
    }
    
    /* Pestañas (Tabs) */
    [data-baseweb="tab-list"] {
        gap: 8px;
    }
    button[data-baseweb="tab"] {
        font-weight: 600;
        background-color: #0081BA !important;
        border-radius: 8px 8px 0px 0px !important;
        padding: 10px 20px !important;
    }
    button[data-baseweb="tab"] p, button[data-baseweb="tab"] span {
        color: white !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #005f8a !important;
        border-bottom: 3px solid white !important;
    }

    /* Clase para forzar texto blanco en fondos oscuros (Instrucciones) */
    .instruction-box, .instruction-box p, .instruction-box span, .instruction-box strong { color: white !important; }

    /* Ocultar el botón de Deploy de Streamlit */
    [data-testid="stDeployButton"] {
        display: none;
    }

    /* Hacer el header original invisible pero permitir que el botón sea visible debajo de nuestro header */
    header[data-testid="stHeader"] {
        background: transparent !important;
        color: transparent !important;
        z-index: 1000001 !important;
        height: 0px !important;
        overflow: visible !important;
    }

    /* Encabezado Fijo */
    .fixed-header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background-color: white;
        z-index: 1000000;
        padding: 5px 40px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 3px solid #0081BA;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        height: 110px;
    }

    /* Ajuste para que el contenido no se oculte tras el header */
    .main .block-container {
        padding-top: 110px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# Lógica para imágenes en el header fijo y sitios
logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo_carone.png")
auto_path = os.path.join(os.path.dirname(__file__), "assets", "auto.png")
kavak_path = os.path.join(os.path.dirname(__file__), "assets", "kavak.png")
meli_path = os.path.join(os.path.dirname(__file__), "assets", "mercadolibre.png")

def get_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

logo_base64 = get_base64(logo_path)
auto_base64 = get_base64(auto_path)
kavak_base64 = get_base64(kavak_path)
meli_base64 = get_base64(meli_path)

logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="height: 80px;">' if logo_base64 else ""
auto_html = f'<img src="data:image/png;base64,{auto_base64}" style="height: 50px; margin-right: 15px;">' if auto_base64 else ""

# Iconos pequeños para estados
kavak_icon_inline = f'<img src="data:image/png;base64,{kavak_base64}" style="height: 18px; vertical-align: middle; margin-right: 5px;">' if kavak_base64 else "🏢 "
meli_icon_inline = f'<img src="data:image/png;base64,{meli_base64}" style="height: 18px; vertical-align: middle; margin-right: 5px;">' if meli_base64 else "🛍️ "

st.markdown(f"""
    <div class="fixed-header">
        <div style="display: flex; align-items: center; margin-left: 20px;">
            {auto_html}
            <div style="color: #0081BA; font-size: 2.2rem; font-weight: 700; letter-spacing: -0.5px;">AI assistant</div>
        </div>
        <div style="margin-right: 20px;">{logo_html}</div>
    </div>
""", unsafe_allow_html=True)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# 1. Interfaz de Usuario: Sidebar
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("API Key (Gemini/Ollama)", type="password")
    model_provider = st.selectbox("Proveedor de IA", ["gemini", "ollama"])
    base_url = st.text_input("Base URL (Ollama)", value="http://localhost:11434")
    show_browser = st.checkbox("Mostrar navegador local", value=True)
    
    view = st.radio("Navegación", ["🚀 Scraper", "📜 Historial"])

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

@st.cache_data(ttl=60)
def fetch_history_extractions():
    try:
        response = httpx.get(f"{BACKEND_URL}/history/extractions")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

@st.cache_data(ttl=60)
def fetch_history_valuations():
    try:
        response = httpx.get(f"{BACKEND_URL}/history/valuations")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

# Cuerpo principal
if view == "🚀 Scraper":
    st.subheader("🔍 Selección de Vehículo")
    stock_list = fetch_stock()
    if not stock_list:
        st.error("No se pudo cargar el stock.")
        st.stop()

    df_stock = pd.DataFrame(stock_list)
    split_data = df_stock['modelo'].str.split(" - ", n=1, expand=True)
    df_stock['model_name'] = split_data[0]
    if split_data.shape[1] > 1:
        df_stock['version_name'] = split_data[1].fillna("N/A")
    else:
        df_stock['version_name'] = "N/A"

    # --- FILTROS HORIZONTALES ---
    f1, f2, f3, f4 = st.columns(4)
    brand = f1.selectbox("Marca", options=sorted(df_stock['marca'].unique().tolist()))
    model = f2.selectbox("Modelo", options=sorted(df_stock[df_stock['marca'] == brand]['model_name'].unique().tolist()))
    version = f3.selectbox("Versión", options=sorted(df_stock[(df_stock['marca'] == brand) & (df_stock['model_name'] == model)]['version_name'].unique().tolist()))
    year = f4.selectbox("Año", options=sorted(df_stock[(df_stock['marca'] == brand) & (df_stock['model_name'] == model) & (df_stock['version_name'] == version)]['anio'].unique().tolist(), reverse=True))

    # --- COINCIDENCIAS EN STOCK (Full Width) ---
    matches = df_stock[(df_stock['marca'] == brand) & (df_stock['model_name'] == model) & (df_stock['version_name'] == version) & (df_stock['anio'] == year)]
    with st.expander(f"📋 Coincidencias en Stock ({len(matches)})", expanded=False):
        # Excluir columnas técnicas model_name y version_name de la visualización para el usuario
        display_matches = matches.drop(columns=['model_name', 'version_name'], errors='ignore')
        st.dataframe(display_matches, use_container_width=True, hide_index=True)

    selected_car = matches.iloc[0] if not matches.empty else None
    default_patente = str(selected_car['patente']) if selected_car is not None else ""

    c1, c2 = st.columns([1, 1])
    with c1:
        selected_sites = st.multiselect("Sitios a scrapear", ["Kavak", "Mercado Libre"], default=["Kavak", "Mercado Libre"])
    with c2:
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
            "   Extraer:\n"
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
            "**Regla Críticas:**\n"
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
            "   Extraer:\n"
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
            "**Regla Críticas:**\n"
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
        
        def render_instruction_editor(site_label, nav_key, ext_key, default_nav, default_ext, icon_base64=None):
            if icon_base64:
                st.markdown(f'<img src="data:image/png;base64,{icon_base64}" style="height: 40px; margin-bottom: 10px;">', unsafe_allow_html=True)
            st.caption(f"Personaliza cómo el agente interactúa con {site_label}")
            
            def highlight_text(text):
                # Colores claros con !important para contraste sobre fondo azul
                text = re.sub(r"\*\*(.*?)\*\*", r'<span style="color: #90EE90 !important; font-weight: bold;">\1</span>', text)
                # Dorado para las variables {v} con !important
                text = re.sub(r"\{(.*?)\}", r'<span style="color: #FFD700 !important; font-weight: bold;">{\1}</span>', text)
                return text.replace("\n", "<br>")

            edit_mode_key = f"edit_mode_{nav_key.split('_')[-1]}"

            if not st.session_state[edit_mode_key]:
                # --- MODO VISUALIZACIÓN ---
                with st.container(border=True):
                    nav_val = st.session_state.get(nav_key, default_nav)
                    ext_val = st.session_state.get(ext_key, default_ext)
                    st.markdown(f"""
                        <div class="instruction-box" style="background-color: #0081BA; padding: 15px; border-radius: 8px; font-family: 'Montserrat', sans-serif; font-size: 0.95em; line-height: 1.6; box-shadow: inset 0 0 10px rgba(0,0,0,0.1);">
                            <div style="margin-bottom: 10px;">
                                <strong style="text-transform: uppercase; font-size: 0.8em; opacity: 0.9;">Navegación:</strong><br>
                                <span>{highlight_text(nav_val)}</span>
                            </div>
                            <hr style="margin: 15px 0; border: 0; border-top: 1px solid rgba(255,255,255,0.2);">
                            <div>
                                <strong style="text-transform: uppercase; font-size: 0.8em; opacity: 0.9;">Extracción:</strong><br>
                                <span>{highlight_text(ext_val)}</span>
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

                st.markdown('<strong style="color: #0081BA;">Instrucciones de navegación:</strong>', unsafe_allow_html=True)
                st.text_area("Editor de Navegación", height=250, key=f"temp_{nav_key}", label_visibility="collapsed")
                
                st.markdown('<strong style="color: #0081BA;">Instrucciones de extracción:</strong>', unsafe_allow_html=True)
                st.text_area("Editor de Extracción", height=200, key=f"temp_{ext_key}", label_visibility="collapsed")

                c1, c2 = st.columns(2)
                if c1.button("💾 Guardar", key=f"btn_save_{nav_key}", use_container_width=True, type="primary"):
                    # VALIDACIÓN DE VARIABLES CRÍTICAS
                    nav_txt = st.session_state[f"temp_{nav_key}"]
                    if "{marca}" not in nav_txt or "{modelo}" not in nav_txt:
                        st.error("⚠️ Error: Las instrucciones deben contener {marca} y {modelo}.")
                    else:
                        st.session_state[nav_key] = st.session_state[f"temp_{nav_key}"]
                        st.session_state[ext_key] = st.session_state[f"temp_{ext_key}"]
                        st.session_state[edit_mode_key] = False
                        st.rerun()

                if c2.button("✖️ Cerrar sin guardar", key=f"btn_cancel_{nav_key}", use_container_width=True):
                    st.session_state[edit_mode_key] = False
                    st.rerun()

        with tab_k:
            render_instruction_editor("Kavak", "nav_kavak", "ext_kavak", DEFAULT_NAV_KAVAK, DEFAULT_EXT_KAVAK, kavak_base64)

        with tab_m:
            render_instruction_editor("Mercado Libre", "nav_meli", "ext_meli", DEFAULT_NAV_MELI, DEFAULT_EXT_MELI, meli_base64)

        custom_fields = st.text_input("Campos adicionales (separados por coma)", 
                                    placeholder="color, unico_dueño, garantia",
                                    help="Escribe atributos extra que quieras que la IA busque (ej: color, estado, accesorios). Se guardarán en la base de datos como información adicional.")

    scrape_btn = st.button("Iniciar Scraping", type="primary", use_container_width=True)

    # Lógica principal
    if scrape_btn:
        if not api_key or not selected_sites:
            st.warning("Por favor ingrese una API Key y seleccione al menos un sitio.")
        else:
            st.session_state.execution_logs = [] # Reiniciar logs para nueva ejecución
            
            # --- BARRA DE PROGRESO E INDICADORES ---
            progress_bar = st.progress(0, text="Iniciando Agente IA...")
            site_badges = {s: st.empty() for s in selected_sites}
            for s in selected_sites: 
                s_icon = kavak_icon_inline if "KAVAK" in s.upper() else meli_icon_inline
                site_badges[s].markdown(f"⚪ {s_icon} **{s}**: Esperando...", unsafe_allow_html=True)

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
                                msg = event["message"]; now = datetime.now().strftime("%H:%M:%S")
                                st.session_state.execution_logs.append({"message": msg, "time": now})
                                st.markdown(f"{msg} <span style='float:right; color:gray; font-size:0.85em;'>{now}</span>", unsafe_allow_html=True)
                                
                                # --- UNIFICACIÓN DE BARRA DE PROGRESO ---
                                if "Iniciando proceso" in msg: progress_bar.progress(5, text="Iniciando Agente...")
                                elif "tipo de cambio" in msg: progress_bar.progress(15, text="Consultando divisas...")
                                elif "Agente IA navegando" in msg: progress_bar.progress(35, text="Navegando por portales...")
                                elif "Resultados confirmados" in msg: progress_bar.progress(55, text="Filtros aplicados. Extrayendo...")
                                elif "Procesando vehículo" in msg: progress_bar.progress(75, text="Extrayendo detalles técnicos...")
                                elif "Procesando datos extraídos" in msg: progress_bar.progress(90, text="Finalizando análisis...")

                                # --- UNIFICACIÓN DE INDICADORES POR SITIO ---
                                for s in selected_sites:
                                    s_key = s.upper().replace(" ", "")
                                    if f"[{s_key}]" in msg.upper():
                                        clean_msg = msg.split(']')[-1].strip()
                                        clean_msg = re.sub(r'^[^\w\s]+', '', clean_msg).strip() # Quitar emojis iniciales
                                        
                                        icon = "⚪"
                                        if "Iniciando" in msg: icon = "🟠"
                                        elif "navegando" in msg: icon = "🔵"
                                        elif "Verificando" in msg: icon = "🔍"
                                        elif "Extrayendo" in msg or "Procesando" in msg: icon = "📥"
                                        elif "✅" in msg or "finalizado" in msg: icon = "🟢"
                                        elif "Error" in msg or "❌" in msg: icon = "🔴"
                                        
                                        s_icon = kavak_icon_inline if "KAVAK" in s.upper() else meli_icon_inline
                                        site_badges[s].markdown(f"{icon} {s_icon} **{s}**: {clean_msg}", unsafe_allow_html=True)

                            elif event["type"] == "error":
                                st.error(f"❌ Error: {event['message']}")
                                if event.get("screenshot"):
                                    st.image(f"data:image/png;base64,{event['screenshot']}", caption="Captura de pantalla del error")
                            elif event["type"] == "final":
                                result = event
                                status_container.update(label="✅ Proceso finalizado", state="complete", expanded=True)

                    if result and result.get("status") == "success":
                        st.success(f"✅ Scraping completado!")
                        
                        if "data" in result and result["data"]:
                            progress_bar.progress(100, text="¡Completado!")
                            tab1, tab2, tab3 = st.tabs(["🔍 Resultados de Scraping", "📈 Resultados", "📋 Log de Proceso"])
                            
                            with tab1:
                                # Extraer datos de updated_stock para las métricas específicas
                                stock_info = result.get("updated_stock", [{}])[0]
                                meli_val = float(stock_info.get("meli", 0))
                                kavak_val = float(stock_info.get("kavak", 0))
                                precio_mercado = float(stock_info.get("preciopropuesto", 0))

                                # --- MÉTRICAS EN COLUMNAS ---
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Promedio MeLi", f"${meli_val:,.0f} ARS" if meli_val > 0 else "N/A")
                                m2.metric("Promedio Kavak", f"${kavak_val:,.0f} ARS" if kavak_val > 0 else "N/A")
                                m3.metric("Precio Mercado", f"${precio_mercado:,.0f} ARS" if precio_mercado > 0 else "N/A", 
                                          help="Promedio calculado entre Mercado Libre y Kavak")
                                m4.metric("Dólar Aplicado", f"${result.get('exchange_rate', 0):,.2f}")
                                st.divider()

                                df = pd.DataFrame(result["data"])
                                
                                # Formateo de precio para visualización con conversión
                                def display_price(row):
                                    if row['currency'] == 'USD':
                                        return f"USD {row['price']:,.0f} (≈ ${row['price_ars']:,.0f} ARS)"
                                    return f"${row['price']:,.0f} ARS"
                                
                                df['Precio'] = df.apply(display_price, axis=1)
                                
                                # Seleccionar columnas existentes para evitar KeyError
                                cols_to_show_scraping = ['brand', 'model', 'version', 'year', 'km', 'Precio', 'zona', 'reservado', 'site', 'url']
                                existing_cols_scraping = [c for c in cols_to_show_scraping if c in df.columns]
                                df_display = df[existing_cols_scraping].copy()
                                
                                # Renombrar solo las columnas que existen
                                rename_map = {'brand': 'Marca', 'model': 'Modelo', 'version': 'Versión', 'year': 'Año', 'km': 'KM', 'Precio': 'Precio', 'zona': 'Zona', 'reservado': 'Reservado', 'site': 'Sitio', 'url': 'Link'}
                                df_display = df_display.rename(columns={k: v for k, v in rename_map.items() if k in df_display.columns})
                                
                                if 'Reservado' in df_display.columns:
                                    df_display['Reservado'] = df_display['Reservado'].apply(lambda x: "✅" if x else "❌")

                                # --- DETECCIÓN DE OUTLIERS ---
                                avg = result['stats']['average_price']
                                def style_outliers(row):
                                    p_ars = df.loc[row.name]['price_ars']
                                    if p_ars < avg * 0.8: return ['background-color: #d4edda'] * len(row)
                                    if p_ars > avg * 1.2: return ['background-color: #f8d7da'] * len(row)
                                    return [''] * len(row)

                                st.dataframe(df_display.style.apply(style_outliers, axis=1), use_container_width=True, hide_index=True, column_config={"Link": st.column_config.LinkColumn("Link", display_text="🔗")})
                            
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
                                    st.info("No se generó valuación de negocio. Verifique si la patente existe en el stock.")
                            
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
else:
    st.header("📜 Historial de Ejecuciones")
    hist_tab1, hist_tab2, hist_tab3 = st.tabs(["🔍 Extracciones", "📊 Valuaciones", "📈 Tendencias y Comparativa"])
    
    with hist_tab3:
        val_data = fetch_history_valuations()
        if val_data:
            df_h = pd.DataFrame(val_data)
            
            # Split modelo to get version if possible (consistent with Scraper view)
            if 'modelo' in df_h.columns:
                split_h = df_h['modelo'].str.split(" - ", n=1, expand=True)
                df_h['model_name'] = split_h[0]
                if split_h.shape[1] > 1:
                    df_h['version_name'] = split_h[1].fillna("N/A")
                else:
                    df_h['version_name'] = "N/A"

            # --- GRÁFICO DE TENDENCIA ---
            st.subheader("📈 Evolución de Precio Propuesto")
            
            # Hierarchical filters: Brand, Model, Version, Year
            h_f1, h_f2, h_f3, h_f4 = st.columns(4)
            h_brand = h_f1.selectbox("Marca", options=sorted(df_h['marca'].unique().tolist()), key="h_brand")
            h_model = h_f2.selectbox("Modelo", options=sorted(df_h[df_h['marca'] == h_brand]['model_name'].unique().tolist()), key="h_model")
            h_version = h_f3.selectbox("Versión", options=sorted(df_h[(df_h['marca'] == h_brand) & (df_h['model_name'] == h_model)]['version_name'].unique().tolist()), key="h_version")
            h_year = h_f4.selectbox("Año", options=sorted(df_h[(df_h['marca'] == h_brand) & (df_h['model_name'] == h_model) & (df_h['version_name'] == h_version)]['anio'].unique().tolist(), reverse=True), key="h_year")

            df_pat = df_h[
                (df_h['marca'] == h_brand) & (df_h['model_name'] == h_model) & 
                (df_h['version_name'] == h_version) & (df_h['anio'] == h_year)
            ].sort_values('fechaejecucion')
            
            if not df_pat.empty:
                st.line_chart(df_pat, x='fechaejecucion', y='preciopropuesto')
            
                # --- COMPARADOR DE DELTAS ---
                st.divider()
                st.subheader("⚖️ Comparador de Ejecuciones")
                c_cols = st.columns(2)
                id1 = c_cols[0].selectbox("Ejecución A (Base)", options=df_pat['id'].tolist(), key="ca")
                id2 = c_cols[1].selectbox("Ejecución B (Nueva)", options=df_pat['id'].tolist(), key="cb")
                if id1 and id2:
                    r1 = df_pat[df_pat['id'] == id1].iloc[0]
                    r2 = df_pat[df_pat['id'] == id2].iloc[0]
                    delta = ((r2['preciopropuesto'] / r1['preciopropuesto']) - 1) * 100
                    st.metric("Variación de Precio", f"${r2['preciopropuesto']:,.0f}", f"{delta:.2f}%")
            else:
                st.info("No hay datos para la combinación seleccionada.")
    
    with hist_tab1:
        if st.button("🔄 Refrescar Historial de Extracciones"):
            st.cache_data.clear()
            st.rerun()
        
        ext_data = fetch_history_extractions()
        if ext_data:
            df_ext = pd.DataFrame(ext_data)
            
            # Parsear datos_adicionales para que sean legibles en la tabla
            def format_extra_data(val):
                if isinstance(val, dict):
                    return ", ".join([f"{k}: {v}" for k, v in val.items()])
                return str(val) if val else ""

            if 'datos_adicionales' in df_ext.columns:
                df_ext['Campos Extra'] = df_ext['datos_adicionales'].apply(format_extra_data)
            
            # Renombrar columnas para una mejor presentación
            df_ext = df_ext.rename(columns={
                'brand': 'Marca', 'model': 'Modelo', 'version': 'Versión', 
                'year': 'Año', 'km': 'KM', 'price': 'Precio', 
                'currency': 'Moneda', 'site': 'Sitio', 'zona': 'Zona', 
                'fecha_transaccion': 'Fecha', 'url': 'Link'
            })
            
            # Seleccionar y ordenar columnas
            cols_to_show = ['Fecha', 'Sitio', 'Marca', 'Modelo', 'Versión', 'Año', 'KM', 'Precio', 'Moneda', 'Zona', 'Campos Extra', 'Link']
            existing_cols = [c for c in cols_to_show if c in df_ext.columns]

            st.dataframe(df_ext[existing_cols], use_container_width=True, hide_index=True, column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="🔗")
            })
        else:
            st.info("No hay extracciones registradas en la base de datos.")
            
    with hist_tab2:
        if st.button("🔄 Refrescar Historial de Valuaciones"):
            st.cache_data.clear()
            st.rerun()
            
        val_data = fetch_history_valuations()
        if val_data:
            df_val = pd.DataFrame(val_data)
            
            # Aplicar formato de porcentaje a columnas de margen
            pct_cols = [
                'margenhistorico_de_gestion_de_compra', 'diferencia_pp_y_pe', 
                'margenhistorico_de_costo_y_pe', 'margenindexado_de_costo'
            ]
            for col in pct_cols:
                if col in df_val.columns:
                    df_val[col] = df_val[col].astype(float) * 100
            
            # Reordenar para mostrar lo más importante primero
            important_cols = [
                'patente', 'marca', 'modelo', 'anio', 'preciopropuesto', 
                'margenhistorico_de_gestion_de_compra', 'preciodeventa', 
                'semanaejecucion', 'fechaejecucion'
            ]
            cols_to_show = [c for c in important_cols if c in df_val.columns]
            other_cols = [c for c in df_val.columns if c not in important_cols]
            
            st.dataframe(
                df_val[cols_to_show + other_cols], 
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.info("No hay valuaciones calculadas registradas.")

# Sección de historial (simulada)
st.divider()
st.subheader("ℹ️ Notas del Agente")
st.info("El agente IA realiza navegación visual. Si ve que el navegador se queda detenido, verifique si hay algún CAPTCHA o interacción manual requerida.")
