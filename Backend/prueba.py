import os
import asyncio
from stagehand import Stagehand
from dotenv import load_dotenv

load_dotenv()

async def main():
    # 1. Conectamos al servidor local (el binario SEA)
    # Importante: No usamos 'async with' porque esta versión no lo soporta
    client = Stagehand(
        server="local",
        local_openai_api_key=os.environ.get("GEMINI_API_KEY"),
        local_ready_timeout_s=30.0,
    )

    session_id = None

    try:
        print("⏳ Iniciando sesión en el servidor local...")
        # Pasamos el parámetro para que NO sea headless
        session = client.sessions.start(
            model_name="gemini-2.5-flash-preview-04-17",
            browser={
                "type": "local",
                "launchOptions": {
                    "headless": False  # <--- Esto debería abrir la ventana
                }
            }
        )
        session_id = session.data.session_id
        print(f"✅ Sesión iniciada: {session_id}")

        print("🌐 Navegando a Kavak...")
        client.sessions.navigate(id=session_id, url="https://www.kavak.com")
        
        # AUMENTAMOS EL TIEMPO: Dale 10 segundos para que tú puedas ver 
        # qué aparece en la ventana (si es que se abre)
        print("⏳ Esperando carga visual (mira si se abrió una ventana)...")
        import time
        time.sleep(10) 

        print("🔍 Intentando extracción simple...")
        extract_response = client.sessions.extract(
            id=session_id,
            instruction="Dime qué dice el botón principal de la página."
        )
        print(f"📄 Resultado: {extract_response.data.result}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if session_id:
            print("🛑 Cerrando sesión...")
            client.sessions.end(id=session_id)
        client.close()
        input("Presiona Enter para terminar...")

if __name__ == "__main__":
    # Esta versión de la librería parece ser síncrona en sus llamadas de cliente
    # Si te da error el asyncio.run, simplemente llama a main() sin async
    asyncio.run(main())