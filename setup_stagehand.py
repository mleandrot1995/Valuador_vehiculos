import os
import sys
import urllib.request
import platform

def setup():
    print("🚀 Iniciando configuración de binarios para Stagehand...")
    
    # 1. Determinar el nombre del archivo según el sistema
    plat = "win32" if sys.platform.startswith("win") else ("darwin" if sys.platform == "darwin" else "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    filename = f"stagehand-{plat}-{arch}" + (".exe" if plat == "win32" else "")
    
    # 2. Crear carpeta de binarios en el proyecto
    bin_dir = os.path.join(os.getcwd(), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    target_path = os.path.join(bin_dir, filename)
    
    # 3. URL de descarga (Repositorio oficial de Stagehand)
    # Nota: Usamos la versión estable conocida
    url = f"https://github.com/browserbase/stagehand/releases/latest/download/{filename}"
    
    if os.path.exists(target_path):
        print(f"✅ El binario ya existe en: {target_path}")
    else:
        print(f"📥 Descargando binario desde: {url}")
        try:
            urllib.request.urlretrieve(url, target_path)
            print(f"✅ Descarga completada: {target_path}")
        except Exception as e:
            print(f"❌ Error al descargar: {e}")
            return

    # 4. Mostrar instrucciones para el .env
    print("\n" + "="*50)
    print("📋 PASO FINAL: Agregue esta línea a su archivo .env")
    print(f'STAGEHAND_SEA_BINARY={target_path}')
    print("="*50)

if __name__ == "__main__":
    setup()
