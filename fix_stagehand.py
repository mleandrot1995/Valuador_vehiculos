import os
import sys
import subprocess

def download_binary():
    print("🔍 Buscando binario de Stagehand para Windows...")
    
    # Intentamos ejecutar el script interno de la librería para descargar el binario
    try:
        import stagehand
        # La librería suele incluir un script para esto
        # Intentamos ejecutarlo via módulo
        print("📥 Descargando binario oficial...")
        subprocess.check_call([sys.executable, "-m", "stagehand.scripts.download_binary"])
        print("✅ Binario descargado exitosamente.")
    except Exception as e:
        print(f"❌ Error al descargar automáticamente: {e}")
        print("\n💡 Por favor, intenta ejecutar este comando manualmente en tu terminal:")
        print(f"source .venv/bin/activate  (o activa tu venv)")
        print(f"python -m stagehand.scripts.download_binary")

if __name__ == "__main__":
    download_binary()
