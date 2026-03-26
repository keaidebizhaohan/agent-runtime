#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Lowcode Agent App

从导出的 Agent JSON 配置加载并编译为 runtime 可运行 Agent 实例，
提供 HTTP 服务接口。

运行方式:
    python -m openjiuwen_runtime.examples.lowcode_agent --file config.json --port 8091
    lowcode-agent-runner --file config.json --port 8091
"""

import json
import os
import uuid
from typing import AsyncIterator, Tuple

from openjiuwen_runtime.service.app.agent_app import AgentApp
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent.agents.react_agent import ReActAgent
from openjiuwen_studio.lowcode import AgentCompiler
from openjiuwen_studio.lowcode.schemas import ModelOverride
from openjiuwen_runtime.examples.lowcode_agent.agui_converter import (
    agui_assistant_text_as_answer_events,
    agui_trace_context,
    convert_chunk_to_agui_events,
    finalize_agui_stream,
)

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
    # 从环境变量读取配置文件路径
    file_path = os.environ.get("RUNTIME_IR_PATH")
    export_data = _load_export_data(file_path)
    model_overrides = _get_model_overrides()
    compiler = AgentCompiler()

    # 从环境变量读取用户数据
    userdata = os.environ.get("RUNTIME_USERDATA")

    result = await compiler.compile_for_runtime(
        config=export_data,
        model_overrides=model_overrides,
        current_user={"user_id": "test-user"}
    )

    agent = ReActAgent(card=result["agent_card"])
    agent.configure(result["runtime_config"])

    app.agent = agent

    print(f"[OK] Agent 加载成功! Type: {type(app.agent).__name__}")
    print(f"[INFO] 使用配置文件: {file_path}")
    print(f"[INFO] 用户数据: {userdata}")


@app.query
async def query(msgs, request) -> AsyncIterator[Tuple[dict, bool]]:
    """处理查询请求"""
    conversation_id = request.conversation_id
    trace_context = agui_trace_context(msgs or [])
    last_user_msg = None
    for msg in reversed(msgs or []):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    if not last_user_msg:
        events = agui_assistant_text_as_answer_events(
            trace_context=trace_context,
            conversation_id=conversation_id,
            assistant_text="请输入您的问题",
        )
        for i, event in enumerate(events):
            yield event, i == len(events) - 1
        return

    inputs = {"query": last_user_msg}

    async for chunk in Runner.run_agent_streaming(
            agent=app.agent,
            inputs=inputs,
            session=conversation_id
    ):
        if chunk:
            events = convert_chunk_to_agui_events(
                chunk=chunk,
                trace_context=trace_context,
                conversation_id=conversation_id,
            )
            for event in events:
                yield event, False

    final_events = finalize_agui_stream(
        trace_context=trace_context,
        conversation_id=conversation_id,
    )

    for i, event in enumerate(final_events):
            yield event, i == len(final_events) - 1
        


@app.shutdown
async def shutdown():
    """清理资源"""
    if app.agent:
        print("[OK] Agent 资源已清理")