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
import logging
import os
import sys
import uuid
from datetime import datetime
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


# ==================== 日志脱敏工具 ====================
def mask_userdata(userdata: str | None, max_bytes: int = 10) -> str:
    """
    对userdata进行脱敏处理，只保留前N字节，其余隐藏

    Args:
        userdata: 用户数据字符串
        max_bytes: 保留的最大字节数，默认10字节

    Returns:
        脱敏后的字符串
    """
    if userdata is None:
        return "None"

    if not isinstance(userdata, str):
        userdata = str(userdata)

    # 编码为字节获取准确长度
    userdata_bytes = userdata.encode('utf-8')

    if len(userdata_bytes) <= max_bytes:
        return userdata

    # 只保留前max_bytes字节
    masked_bytes = userdata_bytes[:max_bytes]
    try:
        masked_str = masked_bytes.decode('utf-8', errors='ignore')
    except UnicodeDecodeError:
        # 如果解码失败，直接返回截断前的原始字符串前几个字符
        masked_str = userdata[:max_bytes]

    return f"{masked_str}***"


# ==================== 日志配置 ====================
def _get_venv_path() -> str:
    """动态获取虚拟环境路径"""
    if hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix:
        return sys.prefix
    venv_env = os.environ.get('VIRTUAL_ENV')
    if venv_env:
        return venv_env
    # 回退到可执行文件的父目录
    return os.path.dirname(os.path.dirname(sys.executable))

def _setup_logging():
    """配置日志系统"""
    venv_path = _get_venv_path()
    log_dir = os.path.join(venv_path, "logs")

    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "agent_execution.log")

    # 配置日志格式
    log_format = "%(asctime)s | %(name)s | %(filename)s:%(lineno)d | %(levelname)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 配置 root logger
    logger = logging.getLogger("lowcode_agent")
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 控制台 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(log_format, datefmt=date_format)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # ==================== 捕获 openjiuwen 模块日志 ====================
        # 将我们的 handler 添加到 openjiuwen 的各个 logger 中
        openjiuwen_loggers = [
            "common",        # 通用日志 (ReAct迭代、工具执行等)
            "agent",         # Agent 执行日志
            "llm",           # LLM 调用日志
            "tool",          # 工具调用日志
            "session",       # 会话管理日志
            "workflow",      # 工作流日志
            "memory",        # 内存管理日志
            "retrieval",     # 检索日志
            "context_engine",# 上下文引擎日志
            "openjiuwen_runtime.service.app.agent_app",  # AgentApp /query 异常日志
        ]

        for logger_name in openjiuwen_loggers:
            oj_logger = logging.getLogger(logger_name)
            # 添加文件 handler（不添加控制台 handler，避免重复输出）
            oj_logger.addHandler(file_handler)
            oj_logger.setLevel(logging.DEBUG)

        logger.info("=" * 60)
        logger.info(f"Lowcode Agent Runner 启动")
        logger.info(f"虚拟环境路径: {venv_path}")
        logger.info(f"日志文件路径: {log_file}")
        logger.info(f"已捕获 openjiuwen 模块日志: {', '.join(openjiuwen_loggers)}")
        logger.info("=" * 60)

    return logger

# 初始化 logger
logger = _setup_logging()
VENV_PATH = _get_venv_path()

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
    logger.info("开始初始化 Agent...")

    # 从环境变量读取配置文件路径
    file_path = os.environ.get("RUNTIME_IR_PATH")
    logger.info(f"读取配置文件: {file_path}")

    export_data = _load_export_data(file_path)
    model_overrides = _get_model_overrides()
    compiler = AgentCompiler()

    # 从环境变量读取用户数据
    userdata = os.environ.get("RUNTIME_USERDATA")
    logger.info(f"用户数据: {mask_userdata(userdata)}")

    logger.info("开始编译 Agent 配置...")
    result = await compiler.compile_for_runtime(
        config=export_data,
        model_overrides=model_overrides,
        current_user={"user_id": "test-user"}
    )

    agent = ReActAgent(card=result["agent_card"])
    agent.configure(result["runtime_config"])

    app.agent = agent

    logger.info(f"Agent 加载成功! Type: {type(app.agent).__name__}")
    logger.info(f"Agent Card: {result['agent_card'].name}")
    print(f"[OK] Agent 加载成功! Type: {type(app.agent).__name__}")
    print(f"[INFO] 使用配置文件: {file_path}")
    print(f"[INFO] 用户数据: {mask_userdata(userdata)}")


@app.query
async def query(msgs, request) -> AsyncIterator[Tuple[dict, bool]]:
    """处理查询请求"""
    conversation_id = request.conversation_id
    logger.info(f"收到查询请求 - conversation_id: {conversation_id}")

    trace_context = agui_trace_context(msgs or [])
    last_user_msg = None
    for msg in reversed(msgs or []):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    if not last_user_msg:
        logger.warning(f"未找到用户消息 - conversation_id: {conversation_id}")
        events = agui_assistant_text_as_answer_events(
            trace_context=trace_context,
            conversation_id=conversation_id,
            assistant_text="请输入您的问题",
        )
        for i, event in enumerate(events):
            yield event, i == len(events) - 1
        return

    logger.info(f"用户查询内容: {last_user_msg[:100]}...")
    inputs = {"query": last_user_msg}

    try:
        chunk_count = 0
        async for chunk in Runner.run_agent_streaming(
                agent=app.agent,
                inputs=inputs,
                session=conversation_id
        ):
            if chunk:
                chunk_count += 1
                logger.debug(f"[chunk #{chunk_count}] type={type(chunk).__name__}, content={chunk}")
                events = convert_chunk_to_agui_events(
                    chunk=chunk,
                    trace_context=trace_context,
                    conversation_id=conversation_id,
                )
                for event in events:
                    yield event, False

        logger.info(f"Agent 执行完成 - conversation_id: {conversation_id}, chunks: {chunk_count}")

    except Exception as e:
        logger.error(f"Agent 执行出错 - conversation_id: {conversation_id}, error: {str(e)}", exc_info=True)
        raise

    final_events = finalize_agui_stream(
        trace_context=trace_context,
        conversation_id=conversation_id,
    )

    for i, event in enumerate(final_events):
            yield event, i == len(final_events) - 1
        


@app.shutdown
async def shutdown():
    """清理资源"""
    logger.info("开始关闭 Agent Runner...")
    if app.agent:
        logger.info("清理 Agent 资源...")
        print("[OK] Agent 资源已清理")
    logger.info("=" * 60)
    logger.info("Lowcode Agent Runner 已关闭")
    logger.info("=" * 60)