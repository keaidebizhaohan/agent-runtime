#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Lowcode Agent App

从导出的 Agent JSON 配置加载并编译为 runtime 可运行 Agent 实例，
提供 HTTP 服务接口。

运行方式:
    PYTHONPATH=. python lowcode_agent_runner.py --port 8091
"""

import json
from pathlib import Path
from typing import AsyncIterator, Tuple

from openjiuwen_runtime.service import AgentApp
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent.agents.react_agent import ReActAgent
from openjiuwen_studio.lowcode import AgentCompiler
from openjiuwen_studio.lowcode.schemas import ModelOverride

EXPORT_FILE_PATH = Path(__file__).resolve().parents[0] / "test-export-simpleAgent.json"


def _load_export_data() -> dict:
    with open(EXPORT_FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_model_overrides() -> dict:
    return {
        "147": ModelOverride(
            provider="siliconflow",
            model_type="Qwen/Qwen3-8B",
            name="Qwen/Qwen3-8B",
            base_url="https://api.siliconflow.cn/v1",
            api_key="sk-xxx",
            timeout=300,
            parameters={"top_p": 0.9, "temperature": 0.7, "max_tokens": 5000},
        )
    }


app = AgentApp(
    app_name="LowcodeAgent",
    app_description="A lowcode agent loaded from exported JSON config",
    version="0.1.0",
)


@app.init
async def init():
    """初始化并加载 Agent"""
    export_data = _load_export_data()
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
            yield {"type": "text", "content": chunk}, False

    yield {"type": "text", "content": ""}, True


@app.shutdown
async def shutdown():
    """清理资源"""
    if app.agent:
        print("[OK] Agent 资源已清理")


if __name__ == "__main__":
    print("""
Starting LowcodeAgent...
Usage: python lowcode_agent_runner.py [--host HOST] [--port PORT]
Example: curl -X POST http://127.0.0.1:8091/query -H 'Content-Type: application/json' \
  -d '{"messages": [{"role": "user", "content": "你好"}], "conversation_id": "test-123"}'
    """)
    app.run()
