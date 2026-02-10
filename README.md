# AI Car Scraper - Proyecto Fullstack

Este proyecto es una aplicación de scraping asistido por IA para autos usados, estructurada en un monorepo con un backend en FastAPI y un frontend en Streamlit.

## Estructura del Proyecto

*   `/Backend`: API REST construida con FastAPI, integración con Stagehand (IA) y Playwright.
*   `/Frontend`: Dashboard interactivo con Streamlit.

## 🚀 Guía de Instalación Local (Fuera de IDX)

### 1. Prerrequisitos
*   **Python 3.8+** instalado.
*   **Node.js 20+** instalado (Requerido por Stagehand). [Descargar aquí](https://nodejs.org/).
*   **Git** instalado.

### 2. Clonar el repositorio
```bash
git clone https://github.com/mleandrot1995/Valuador_vehiculos.git
cd Valuador_vehiculos
```

### 3. Configurar Entorno Virtual
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instalar Dependencias
```bash
pip install -r Backend/requirements.txt
pip install -r Frontend/requirements.txt
```

### 5. Configuración de Stagehand (Windows)
Es necesario inicializar el motor de Stagehand manualmente en la carpeta del Backend:
```powershell
cd Backend
npm install stagehand
node .\node_modules\stagehand\lib\index.js init
python download-binary.py
```

### 6. Instalar Navegadores de Playwright
```bash
playwright install
```

### 7. Ejecutar la Aplicación
```bash
python run_app.py
```

---

## 🛠️ Desarrollo en Firebase Studio / Nix
Este proyecto incluye configuración para **Project IDX/Nix** en `.idx/dev.nix`.
