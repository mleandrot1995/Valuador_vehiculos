import asyncio
import os
import time
from stagehand import Stagehand

# --- CONFIGURACIÓN DE ENTORNO ---
# Seteamos las llaves antes de cualquier otra cosa.
# El proxy local las necesita para dejarte pasar.
os.environ["BROWSERBASE_API_KEY"] = "local"
os.environ["BROWSERBASE_PROJECT_ID"] = "local"

async def main():
    # --- CONFIGURACIÓN OLLAMA ---
    # Usamos gpt-4o como máscara (alias)
    MODEL_NAME = "gpt-4o" 
    OLLAMA_URL = "http://localhost:11434/v1"
    
    ollama_config = {
        "model": {
            "model_name": MODEL_NAME,
            "provider": "openai",
            "base_url": OLLAMA_URL
        }
    }

    # Inicialización limpia. Si el pip install -U funcionó, 
    # Stagehand() tomará las variables de entorno automáticamente.
    print(f"🚀 Iniciando Stagehand...")
    client = Stagehand() 

    try:
        print(f"🔧 Solicitando sesión al servidor local (Proxy: {MODEL_NAME})...")
        
        # Iniciamos la sesión
        start_response = client.sessions.start(
            model_name=MODEL_NAME,
            browser={
                "type": "local",
                "launchOptions": {"headless": False},
            },
        )
        session_id = start_response.data.session_id
        print(f"✅ Conexión establecida. ID: {session_id}")

        # Navegación
        target_url = "https://www.kavak.com/ar"
        print(f"📍 Navegando a {target_url}...")
        client.sessions.navigate(id=session_id, url=target_url)
        
        # Pausa para que el JS de Kavak termine de cargar
        await asyncio.sleep(5)

        # Ejecución con Ollama
        print("🤖 Consultando a Ollama para entrar al marketplace...")
        execute_response = client.sessions.execute(
            id=session_id,
            execute_options={
                "instruction": "Haz clic en el botón para ver todos los autos usados.",
                "max_steps": 5
            },
            agent_config=ollama_config
        )
        print(f"IA dice: {execute_response.data.message}")

    except Exception as e:
        print(f"❌ Error en el flujo: {e}")
    finally:
        if 'session_id' in locals():
            try:
                client.sessions.end(id=session_id)
            except:
                pass
        client.close()
        print("\n🔌 Proceso finalizado.")

if __name__ == "__main__":
    asyncio.run(main())