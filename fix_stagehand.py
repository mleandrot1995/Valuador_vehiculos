import os
import sys

def download_manual():
    print("🔍 Buscando función de descarga en stagehand.lib.sea_binary...")
    try:
        # Intentamos importar la función desde la ruta que vimos en el error
        from stagehand.lib.sea_binary import download_binary
        print("📥 Iniciando descarga del binario SEA...")
        download_binary()
        print("✅ ¡Binario descargado exitosamente!")
        
        # Verificamos la ruta donde debería estar
        target_path = os.path.join(sys.prefix, "Lib", "bin", "sea", "stagehand-win32-x64.exe")
        if os.path.exists(target_path):
            print(f"📍 Confirmado: El archivo existe en {target_path}")
        else:
            print(f"⚠️ El archivo se descargó pero no lo encuentro en la ruta esperada: {target_path}")
            
    except ImportError as e:
        print(f"❌ No se pudo encontrar el módulo de descarga: {e}")
    except Exception as e:
        print(f"❌ Ocurrió un error durante la descarga: {e}")

if __name__ == "__main__":
    download_manual()
