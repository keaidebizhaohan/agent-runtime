#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Lowcode Agent App

从导出的 Agent JSON 配置加载并编译为 runtime 可运行 Agent 实例，
提供 HTTP 服务接口。

运行方式:
    PYTHONPATH=. python lowcode_agent_runner.py --port 8091
"""

import argparse
import json
from pathlib import Path
from typing import AsyncIterator, Tuple

from openjiuwen_runtime.service.app.agent_app import AgentApp
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent.agents.react_agent import ReActAgent
from openjiuwen_studio.lowcode import AgentCompiler
from openjiuwen_studio.lowcode.schemas import ModelOverride

FILE_PATH = ''

app = AgentApp(
    app_name="LowcodeAgent",
    app_description="A lowcode agent loaded from exported JSON config",
    version="0.1.0",
)


def _load_export_data(file_path) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_model_overrides() -> dict:
    return {
        "147": ModelOverride(
            provider="siliconflow",
            model_type="Qwen/Qwen3-8B",
            name="Qwen/Qwen3-8B",
            base_url="https://api.siliconflow.cn/v1",
            api_key="sk-qlkairmltpvsbmtduezxulxarypnwmijgvkpnuinoqmmwgjc",
            timeout=300,
            parameters={"top_p": 0.9, "temperature": 0.7, "max_tokens": 5000},
        )
    }


@app.init
async def init():
    """初始化并加载 Agent"""
    export_data = _load_export_data(FILE_PATH)
    model_overrides = _get_model_overrides()
    compiler = AgentCompiler()

    result = await compiler.compile_for_runtime(
        config=export_data,
        model_overrides=model_overrides,
        current_user={"user_id": "test-user"}
    )

    agent = ReActAgent(card=result["agent_card"])
    agent.configure(result["runtime_config"])

    app.agent = agent

    print(f"[OK] Agent 加载成功! Type: {type(app.agent).__name__}")
    print(f"[INFO] 使用配置文件: {FILE_PATH}")


@app.query
async def query(msgs, request) -> AsyncIterator[Tuple[dict, bool]]:
    """处理查询请求"""
    last_user_msg = None
    for msg in reversed(msgs):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    if not last_user_msg:
        yield {"type": "text", "content": "请输入您的问题"}, True
        return

    inputs = {"query": last_user_msg}

    async for chunk in Runner.run_agent_streaming(
            agent=app.agent,
            inputs=inputs,
            session=request.conversation_id
    ):
        if chunk:
            if hasattr(chunk, 'model_dump'):
                yield chunk.model_dump(), False
            elif hasattr(chunk, 'payload') and hasattr(chunk, 'type'):
                yield {"type": chunk.type, "index": getattr(chunk, 'index', 0), "payload": chunk.payload}, False
            else:
                yield {"type": "text", "content": str(chunk)}, False

    yield {"type": "text", "content": ""}, True


@app.shutdown
async def shutdown():
    """清理资源"""
    if app.agent:
        print("[OK] Agent 资源已清理")


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(
        description="Lowcode Agent Runner - 从导出的 JSON 配置加载并运行 Agent"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="导出的 Agent JSON 配置文件路径 (必需)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="监听地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8090,
        help="监听端口 (默认: 8090)"
    )

    args = parser.parse_args()

    # 设置导出文件路径
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(f"[ERROR] 配置文件不存在: {file_path}")
        exit(1)

    # 更新全局变量
    FILE_PATH = str(file_path)

    app.run(host=args.host, port=args.port)
