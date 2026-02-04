import asyncio
import os
import inspect
from stagehand import AsyncStagehand
from dotenv import load_dotenv

load_dotenv()

async def inspect_session_methods():
    api_key = os.environ.get("GEMINI_API_KEY", "dummy")
    client = AsyncStagehand(model_api_key=api_key, server="local")
    
    methods = ['navigate', 'act', 'extract', 'start']
    for m in methods:
        attr = getattr(client.sessions, m, None)
        if attr:
            try:
                print(f"\nSignature of client.sessions.{m}:")
                print(inspect.signature(attr))
            except Exception as e:
                print(f"Error inspecting {m}: {e}")
        else:
            print(f"\nMethod {m} not found on client.sessions")
            
    await client.close()

if __name__ == "__main__":
    asyncio.run(inspect_session_methods())
