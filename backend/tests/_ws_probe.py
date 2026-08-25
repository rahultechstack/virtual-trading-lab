"""Manual WebSocket probe: connects, prints a few frames, disconnects."""

import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/api/v1/stream/prices"
WANT = int(sys.argv[2]) if len(sys.argv) > 2 else 3


async def main() -> None:
    async with websockets.connect(URL) as socket:
        print("connected")
        await socket.send(json.dumps({"type": "ping"}))
        seen = 0
        while seen < WANT:
            raw = await asyncio.wait_for(socket.recv(), timeout=30)
            message = json.loads(raw)
            kind = message.get("type")
            data = message.get("data", {})
            if kind == "tick":
                print(
                    "TICK  last=%s bid=%s ask=%s (%s) vol=%s mode=%s mock=%s"
                    % (
                        data.get("last_price"),
                        data.get("bid"),
                        data.get("ask"),
                        data.get("bid_ask_source"),
                        data.get("volume"),
                        data.get("mode"),
                        data.get("is_mock"),
                    )
                )
                seen += 1
            elif kind == "status":
                print(
                    "STATUS provider=%s mode=%s mock=%s connections=%s"
                    % (
                        data.get("provider"),
                        data.get("mode"),
                        data.get("is_mock"),
                        data.get("connections"),
                    )
                )
            elif kind == "pong":
                print("PONG")
            else:
                print(kind.upper(), data)
    print("closed cleanly")


asyncio.run(main())
