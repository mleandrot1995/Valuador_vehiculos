# AI Car Scraper - Proyecto Fullstack

Este proyecto es una aplicación de scraping asistido por IA para autos usados, estructurada en un monorepo con un backend en FastAPI y un frontend en Streamlit.

## Estructura del Proyecto

*   `/Backend`: API REST construida con FastAPI, integración con Playwright y lógica de procesamiento de datos.
*   `/Frontend`: Dashboard interactivo construido con Streamlit.

## 🚀 Guía de Instalación Local (Fuera de IDX)

Si descargas este repositorio para ejecutarlo en tu máquina local (Windows/Mac/Linux), sigue estos pasos:

### 1. Prerrequisitos
*   **Python 3.8+** instalado.
*   **Git** instalado.

### 2. Clonar el repositorio
```bash
git clone https://github.com/mleandrot1995/Valuador_vehiculos.git
cd Valuador_vehiculos
```

### 3. Configurar Entorno Virtual
Se recomienda usar un entorno virtual único para simplificar la gestión.

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instalar Dependencias
Instala las librerías de ambos servicios:

```bash
pip install -r Backend/requirements.txt
pip install -r Frontend/requirements.txt
```

### 5. Instalar Navegadores de Playwright
Necesario para que el scraping funcione:

```bash
playwright install
```

### 6. Configuración de Variables
Copia el archivo de ejemplo y configura tus claves (API Keys de Gemini/Ollama):

```bash
cp .env.example .env
# Edita .env con tus credenciales reales
```

### 7. Ejecutar la Aplicación
Hemos incluido un script para levantar ambos servicios simultáneamente:

```bash
python run_app.py
```
*   Backend: `http://localhost:8000`
*   Frontend: `http://localhost:8501`

---

## 🛠️ Desarrollo en Firebase Studio / Nix

Este proyecto incluye configuración para **Project IDX/Nix**.
El archivo `.idx/dev.nix` gestiona las dependencias del sistema automáticamente.
