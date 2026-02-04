import streamlit as st
import httpx
import pandas as pd
import json
import time

# Configuración básica de Streamlit
st.set_page_config(page_title="AI Car Scraper", layout="wide")

st.title("🚗 AI Assisted Car Scraper")
st.markdown("### Scraping inteligente para autos usados (ej. Kavak)")

# 1. Interfaz de Usuario: Sidebar
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("API Key (Gemini/Ollama)", type="password")
    model_provider = st.selectbox("Proveedor de IA", ["gemini", "ollama"])
    base_url = st.text_input("Base URL (Ollama)", value="http://localhost:11434")
    
    st.divider()
    st.info("Asegúrese de que el Backend esté corriendo en http://localhost:8000")

# Cuerpo principal
col1, col2 = st.columns(2)

with col1:
    st.subheader("Parámetros de Búsqueda")
    target_url = st.text_input("URL Objetivo", value="https://www.kavak.com/ar")
    brand = st.text_input("Marca", value="Toyota")
    model = st.text_input("Modelo", value="Corolla")
    year = st.number_input("Año", min_value=2000, max_value=2025, value=2020)
    km_max = st.number_input("KM Máximo", min_value=0, step=5000, value=50000)
    
    scrape_btn = st.button("Iniciar Scraping", type="primary")

# 3. Visualización en tiempo real (Status Box)
status_placeholder = st.empty()

# Lógica principal
if scrape_btn:
    if not api_key:
        st.warning("Por favor ingrese una API Key.")
    else:
        with st.spinner("Iniciando el scraping..."):
            status_placeholder.text("Conectando con el backend...")
            
            payload = {
                "url": target_url,
                "brand": brand,
                "model": model,
                "year": year,
                "km_max": km_max,
                "api_key": api_key,
                "model_provider": model_provider
            }
            
            try:
                # 2. Comunicación con la API
                # Using a slightly longer timeout for scraping
                response = httpx.post("http://localhost:8000/scrape", json=payload, timeout=60.0)
                
                if response.status_code == 200:
                    result = response.json()
                    status_placeholder.success("Scraping completado con éxito!")
                    
                    st.json(result)
                    
                    # 4. Tablas y Gráficos
                    if "data" in result and result["data"]:
                        df = pd.DataFrame(result["data"])
                        
                        st.subheader("Resultados")
                        st.dataframe(df)
                        
                        st.subheader("Análisis de Precios")
                        st.line_chart(df.set_index("year")["price"])
                        
                        st.metric(label="Precio Promedio", value=f"${result['stats']['average_price']:,.2f}")
                        
                    else:
                        st.warning("No se encontraron datos.")
                else:
                    st.error(f"Error del servidor: {response.text}")
                    
            except httpx.ConnectError:
                st.error("No se pudo conectar al Backend. Asegúrese de que esté corriendo en el puerto 8000.")
            except Exception as e:
                st.error(f"Ocurrió un error inesperado: {str(e)}")

# Sección de historial (simulada leyendo el archivo json si existe)
st.divider()
st.subheader("Historial Local")
try:
    # Intenta leer el archivo localmente si estuviera en la misma máquina, 
    # pero en una arquitectura real debería ser un endpoint del backend.
    # Para simplicidad de la demo, asumimos acceso compartido o endpoint.
    pass 
except:
    pass
