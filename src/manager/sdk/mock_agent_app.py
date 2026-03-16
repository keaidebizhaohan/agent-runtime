"""Mock Agent for testing"""

import asyncio
from fastapi import FastAPI
from uvicorn import Config, Server


app = FastAPI(title="TestAgent")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    # 使用 uvicorn 运行
    config = Config(app=app, host=args.host, port=args.port, log_level="info")
    server = Server(config)

    print(f"Starting TestAgent on http://{args.host}:{args.port}")
    asyncio.run(server.serve())