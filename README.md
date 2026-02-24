# AI Car Scraper 🚗🤖

Sistema inteligente de scraping de vehículos utilizando FastAPI, Streamlit y Stagehand (IA).

## 📋 Requisitos Previos

- **Python 3.10+**
- **Node.js 18+** (Requerido para Stagehand)
- **PostgreSQL**

## 🛠️ Instalación

1. **Clonar el repositorio e ingresar a la carpeta:**
   ```bash
   cd Valuador_vehiculos
   ```

2. **Crear y activar entorno virtual:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/Mac:
   source .venv/bin/activate
   ```

3. **Instalar dependencias de Python:**
   ```bash
   pip install -r Backend/requirements.txt
   pip install -r Frontend/requirements.txt
   ```

4. **Instalar Playwright y Stagehand:**
   ```bash
   playwright install
   npm install -g stagehand
   ```

5. **Configurar variables de entorno:**
   Copia el archivo `.env.example` a `.env` y completa tus credenciales.

## 🚀 Ejecución

Para iniciar tanto el Backend como el Frontend simultáneamente, ejecuta:

```bash
python run_app.py
```