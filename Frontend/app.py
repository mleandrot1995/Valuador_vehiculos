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

    selected_sites = st.multiselect("Sitios a scrapear", ["Kavak", "Mercado Libre"], default=["Kavak", "Mercado Libre"])
    km_max = st.number_input("KM Máximo", min_value=0, step=5000, value=50000)
    
    scrape_btn = st.button("Iniciar Scraping", type="primary")

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
st.divider()
st.subheader("ℹ️ Notas del Agente")
st.info("El agente IA realiza navegación visual. Si ve que el navegador se queda detenido, verifique si hay algún CAPTCHA o interacción manual requerida.")
