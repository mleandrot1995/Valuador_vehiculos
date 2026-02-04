import subprocess
import time
import sys
import os

def run_services():
    print("🚀 Iniciando servicios...")

    # Define paths
    backend_dir = "Backend"
    frontend_dir = "Frontend"
    
    # Determine the correct python executable
    # Check if we are in a virtual environment
    venv_python = os.path.join(os.getcwd(), ".venv", "bin", "python")
    
    if os.path.exists(venv_python):
        print(f"✅ Usando entorno virtual: {venv_python}")
        python_exec = venv_python
    else:
        print(f"⚠️ Entorno virtual no detectado en {venv_python}. Usando python del sistema: {sys.executable}")
        python_exec = sys.executable

    # Environment variables if needed
    env = os.environ.copy()
    # Add project root to PYTHONPATH so modules can be found if needed
    env["PYTHONPATH"] = os.getcwd()

    # Start FastAPI
    print("🔹 Levantando Backend (FastAPI)...")
    # Using python_exec explicitly
    backend_process = subprocess.Popen(
        [python_exec, "-m", "uvicorn", "main:app", "--reload", "--port", "8000"],
        cwd=backend_dir,
        env=env
    )

    # Give backend a moment to start
    time.sleep(3)

    # Start Streamlit
    print("🔹 Levantando Frontend (Streamlit)...")
    # Using python_exec explicitly
    frontend_process = subprocess.Popen(
        [python_exec, "-m", "streamlit", "run", "app.py", "--server.port", "8501"],
        cwd=frontend_dir,
        env=env
    )

    print("✅ Servicios corriendo. Presiona Ctrl+C para detener.")

    try:
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo servicios...")
        backend_process.terminate()
        frontend_process.terminate()
        print("Servicios detenidos.")

if __name__ == "__main__":
    run_services()
