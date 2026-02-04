import subprocess
import time
import sys
import os

def run_services():
    print("🚀 Iniciando servicios...")

    backend_dir = "Backend"
    frontend_dir = "Frontend"
    
    # Detectar el ejecutable de python del entorno virtual
    if os.name == 'nt':  # Windows
        venv_python = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")
    else:  # Linux / Mac
        venv_python = os.path.join(os.getcwd(), ".venv", "bin", "python")
    
    if os.path.exists(venv_python):
        print(f"✅ Usando entorno virtual: {venv_python}")
        python_exec = venv_python
    else:
        print(f"⚠️ Entorno virtual no detectado. Usando python del sistema.")
        python_exec = sys.executable

    env = os.environ.copy()
    # PYTHONPATH configurado para que Backend sea un paquete visible
    env["PYTHONPATH"] = os.path.abspath(backend_dir) + os.pathsep + os.getcwd()

    # CAMBIO: Lanzamos main.py directamente en lugar de '-m uvicorn'
    print("🔹 Levantando Backend (FastAPI)...")
    backend_process = subprocess.Popen(
        [python_exec, "main.py"],
        cwd=backend_dir,
        env=env
    )

    time.sleep(3)

    print("🔹 Levantando Frontend (Streamlit)...")
    frontend_process = subprocess.Popen(
        [python_exec, "-m", "streamlit", "run", "app.py", "--server.port", "8501"],
        cwd=frontend_dir,
        env=env
    )

    print("✅ Servicios corriendo. Frontend en http://localhost:8501")

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
