import asyncio
import os
import inspect
from stagehand import AsyncStagehand
from dotenv import load_dotenv

load_dotenv()

async def inspect_start_sig():
    api_key = os.environ.get("GEMINI_API_KEY", "dummy")
    client = AsyncStagehand(model_api_key=api_key, server="local")
    try:
        print(f"Signature of client.sessions.start: {inspect.signature(client.sessions.start)}")
    except Exception as e:
        print(f"Error inspecting start signature: {e}")
    await client.close()

if __name__ == "__main__":
    asyncio.run(inspect_start_sig())
