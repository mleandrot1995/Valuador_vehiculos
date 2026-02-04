import asyncio
from stagehand import AsyncStagehand
import os

async def inspect_sessions():
    api_key = os.environ.get("GEMINI_API_KEY", "dummy")
    client = AsyncStagehand(model_api_key=api_key, server="local")
    print(f"Sessions object: {client.sessions}")
    print(f"Attributes of client.sessions: {dir(client.sessions)}")
    await client.close()

if __name__ == "__main__":
    asyncio.run(inspect_sessions())
