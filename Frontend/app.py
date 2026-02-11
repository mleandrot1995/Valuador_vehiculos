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

    target_url = st.text_input("URL Objetivo", value="https://www.kavak.com/ar")
    km_max = st.number_input("KM Máximo", min_value=0, step=5000, value=50000)
    
    scrape_btn = st.button("Iniciar Scraping", type="primary")

# 3. Visualización en tiempo real (Status Box)
status_placeholder = st.empty()

# Lógica principal
if scrape_btn:
    if not api_key:
        st.warning("Por favor ingrese una API Key.")
    else:
        with st.spinner("El proceso de IA puede tardar varios minutos (Navegación + Filtrado + Extracción)..."):
            status_placeholder.info("🚀 Conectando con el backend y lanzando agente IA...")
            
            payload = {
                "url": target_url,
                "brand": brand,
                "model": model,
                "year": year,
                "patente": default_patente,
                "version": version,
                "km_max": km_max,
                "api_key": api_key
            }
            
            try:
                # 2. Comunicación con la API
                # AUMENTO DE TIMEOUT: Stagehand realiza muchos pasos y la IA de Gemini 2.0 
                # puede tardar en razonar cada uno. Subimos a 10 minutos para dar margen total.
                response = httpx.post(
                    f"{BACKEND_URL}/scrape", 
                    json=payload, 
                    timeout=600.0 # 10 minutos en segundos
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get("status") == "success":
                        status_placeholder.success(f"✅ Scraping completado! {result['message']}")
                        
                        # 4. Tablas y Gráficos
                        if "data" in result and result["data"]:
                            df = pd.DataFrame(result["data"])
                            
                            st.subheader("Resultados Extraídos")
                            st.dataframe(df, use_container_width=True)
                            
                            st.divider()
                            c1, c2 = st.columns(2)
                            with c1:
                                st.metric(label="Precio Promedio", value=f"${result['stats']['average_price']:,.2f} ARS")
                            with c2:
                                st.metric(label="Vehículos Encontrados", value=len(df))

                            st.subheader("Distribución de Precios")
                            st.line_chart(df.sort_values("year").set_index("year")["price"])
                        else:
                            st.warning("El scraping terminó pero no se extrajeron vehículos válidos.")
                    else:
                        st.error(f"Error en el scraping: {result.get('message')}")
                        if "data" in result:
                            st.json(result["data"])
                else:
                    st.error(f"Error del servidor (Código {response.status_code}): {response.text}")
                    
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
