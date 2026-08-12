import asyncio
import json

import websockets


async def main() -> None:
    async with websockets.connect("ws://localhost:8080/ws") as ws:
        await ws.send(json.dumps({"type": "session_start"}))

        for i in range(5):
            await ws.send(bytes([i]) * 320)

        await ws.send(json.dumps({"type": "session_end"}))

        response = await ws.recv()
        print("CLIENT RECEIVED:", response)


if __name__ == "__main__":
    asyncio.run(main())