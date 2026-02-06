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
        with st.spinner("El proceso de IA puede tardar varios minutos (Navegación + Filtrado + Extracción)..."):
            status_placeholder.info("🚀 Conectando con el backend y lanzando agente IA...")
            
            payload = {
                "url": target_url,
                "brand": brand,
                "model": model,
                "year": year,
                "km_max": km_max,
                "api_key": api_key
            }
            
            try:
                # 2. Comunicación con la API
                # AUMENTO DE TIMEOUT: Stagehand realiza muchos pasos y la IA de Gemini 2.0 
                # puede tardar en razonar cada uno. Subimos a 10 minutos para dar margen total.
                response = httpx.post(
                    "http://localhost:8000/scrape", 
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
