import asyncio
import os
from stagehand import AsyncStagehand
from dotenv import load_dotenv

# Cargar .env para que encuentre el binario
load_dotenv()

async def inspect_sessions():
    api_key = os.environ.get("GEMINI_API_KEY", "dummy")
    
    print(f"STAGEHAND_SEA_BINARY actual: {os.environ.get('STAGEHAND_SEA_BINARY')}")
    
    try:
        client = AsyncStagehand(model_api_key=api_key, server="local")
        print(f"Sessions object: {client.sessions}")
        print(f"Attributes of client.sessions: {dir(client.sessions)}")
        
        # Intentar ver si hay un método para iniciar o crear algo
        await client.close()
    except Exception as e:
        print(f"Error durante la inspección: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_sessions())
