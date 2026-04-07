#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Lowcode Agent App

从导出的 Agent JSON 配置加载并编译为 runtime 可运行 Agent 实例，
提供 HTTP 服务接口。

运行方式:
    python -m openjiuwen_runtime.examples.lowcode_agent --file config.json --port 8091
    lowcode-agent-runner --file config.json --port 8091

环境变量配置:
    RUNTIME_IR_PATH          - Agent 配置文件路径
    RUNTIME_USERDATA         - 用户数据 (JSON格式，支持 env_vars 字段)
    WORKFLOW_EXECUTE_TIMEOUT - 工作流执行超时时间(秒)，默认 300
    CODE_SANDBOX_URL         - 代码沙箱服务地址，默认 http://localhost:8188/run

userdata JSON 格式:
    {
        "api_keys": {...},
        "env_vars": {
            "WORKFLOW_EXECUTE_TIMEOUT": "600",
            "CODE_SANDBOX_URL": "http://code-sandbox:8080/run"
        }
    }
"""

import json
import logging
import os
import sys
import uuid
import asyncio
from datetime import datetime
from typing import AsyncIterator, Tuple

# 设置 DB_TYPE=none，避免数据库配置检查
# 注意：使用直接赋值而不是 setdefault，确保覆盖从 runtime 服务继承的 DB_TYPE
os.environ["DB_TYPE"] = "none"

def _parse_userdata_env_vars():
    """
    从 RUNTIME_USERDATA 环境变量解析并设置环境变量

    支持通过 userdata 传递环境变量配置，优先级：
    1. 系统环境变量 (最高)
    2. userdata.env_vars
    3. 默认值 (最低)

    注意：DB_TYPE 环境变量由 lowcode_agent_runner 控制，不应该被 userdata 覆盖
    """
    userdata_str = os.getenv("RUNTIME_USERDATA", "")
    env_vars = {}

    if userdata_str:
        try:
            userdata = json.loads(userdata_str)
            if isinstance(userdata, dict):
                env_vars = userdata.get("env_vars", {})
        except (json.JSONDecodeError, TypeError):
            pass

    for key, value in env_vars.items():
        if key not in os.environ and key != "DB_TYPE":
            os.environ[key] = str(value)

    return env_vars

_userdata_env_vars = _parse_userdata_env_vars()

_WORKFLOW_TIMEOUT = os.getenv("WORKFLOW_EXECUTE_TIMEOUT", "300")
os.environ.setdefault("WORKFLOW_EXECUTE_TIMEOUT", _WORKFLOW_TIMEOUT)
os.environ.setdefault("WORKFLOW_STREAM_FRAME_TIMEOUT", _WORKFLOW_TIMEOUT)
os.environ.setdefault("WORKFLOW_STREAM_FIRST_FRAME_TIMEOUT", _WORKFLOW_TIMEOUT)

_CODE_SANDBOX_URL = os.getenv("CODE_SANDBOX_URL", "")
if not _CODE_SANDBOX_URL:
    _CODE_SANDBOX_URL = "http://localhost:8188/run"

from openjiuwen_studio.core.executor.component.code_runner.remote import remote_code_runner
remote_code_runner.code_sandbox_url = _CODE_SANDBOX_URL

from openjiuwen_runtime.service.app.agent_app import AgentApp
from openjiuwen.core.runner import Runner
from openjiuwen.core.application.llm_agent import LLMAgent, ReActAgentConfig as LegacyReActAgentConfig
from openjiuwen.core.application.workflow_agent import WorkflowAgent
from openjiuwen.core.single_agent.legacy import WorkflowAgentConfig as LegacyWorkflowAgentConfig
from openjiuwen_studio.lowcode import AgentCompiler
from openjiuwen_studio.lowcode.config_adapter import ConfigAdapter
from openjiuwen_studio.lowcode.runtime_workflow_runner import RuntimeWorkflowRunner
from openjiuwen_runtime.examples.lowcode_agent.agui_converter import (
    agui_assistant_text_as_answer_events,
    agui_append_text_and_finish_events,
    agui_error_events,
    agui_trace_context,
    convert_chunk_to_agui_events,
    finalize_agui_stream,
    flush_buffered_agui_text_events,
    merge_agui_events_for_stream,
)
from openjiuwen_runtime.examples.lowcode_agent.workflow_registration import (
    normalize_workflow_providers_for_agent,
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
    log_level_name = os.environ.get("LOWCODE_AGENT_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "agent_execution.log")

    # 配置日志格式
    log_format = "%(asctime)s | %(name)s | %(filename)s:%(lineno)d | %(levelname)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 配置 root logger
    logger = logging.getLogger("lowcode_agent")
    logger.setLevel(log_level)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 控制台 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
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
            "openjiuwen_studio.lowcode.compiler",  # Agent 编译日志
            "openjiuwen_studio.lowcode.config_adapter",  # 配置适配器日志
        ]

        for logger_name in openjiuwen_loggers:
            oj_logger = logging.getLogger(logger_name)
            # 添加文件 handler（不添加控制台 handler，避免重复输出）
            oj_logger.addHandler(file_handler)
            oj_logger.setLevel(log_level)

        logger.info("=" * 60)
        logger.info(f"Lowcode Agent Runner 启动")
        logger.info(f"虚拟环境路径: {venv_path}")
        logger.info(f"日志文件路径: {log_file}")
        logger.info(f"已捕获 openjiuwen 模块日志: {', '.join(openjiuwen_loggers)}")
        logger.info("=" * 60)

    return logger


def _summarize_chunk_for_log(chunk) -> str:
    chunk_type = type(chunk).__name__
    schema_type = getattr(chunk, "type", None)
    index = getattr(chunk, "index", None)
    payload = getattr(chunk, "payload", None)

    summary = [f"type={chunk_type}"]
    if schema_type is not None:
        summary.append(f"schema={schema_type}")
    if index is not None:
        summary.append(f"index={index}")

    if isinstance(payload, dict):
        output = payload.get("output") or payload.get("content") or payload.get("response")
        result_type = payload.get("result_type")
        if result_type:
            summary.append(f"result_type={result_type}")
        if isinstance(output, str) and output:
            preview = output.replace("\n", "\\n")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            summary.append(f"preview={preview!r}")
        elif output is not None:
            summary.append(f"payload_keys={sorted(payload.keys())}")
        else:
            summary.append(f"payload_keys={sorted(payload.keys())}")
    elif payload is not None:
        payload_str = str(payload).replace("\n", "\\n")
        if len(payload_str) > 80:
            payload_str = payload_str[:77] + "..."
        summary.append(f"payload={payload_str!r}")

    return ", ".join(summary)

# 初始化 logger
logger = _setup_logging()
VENV_PATH = _get_venv_path()

FILE_PATH = ''
_STREAM_IDLE_HEARTBEAT_SECONDS = 15.0
_AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS = float(
    os.environ.get("AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS", "0.12")
)

app = AgentApp(
    app_name="LowcodeAgent",
    app_description="A lowcode agent loaded from exported JSON config",
    version="0.1.0",
)


def _load_export_data(file_path) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_model_overrides() -> dict:
    return {}


@app.init
async def init():
    """初始化并加载 Agent"""
    logger.info("开始初始化 Agent...")

    if _userdata_env_vars:
        logger.info(f"从 userdata 加载的环境变量: {_userdata_env_vars}")

    # 从环境变量读取配置文件路径
    file_path = os.environ.get("RUNTIME_IR_PATH")
    logger.info(f"读取配置文件: {file_path}")

    export_data = _load_export_data(file_path)
    app.ir_data = export_data
    app.ir_file_path = file_path
    model_overrides = _get_model_overrides()

    config_model_refs = export_data.get("model_references", {})
    if config_model_refs:
        logger.info(f"使用配置文件中的 model_references: {list(config_model_refs.keys())}")

    # 创建 RuntimeWorkflowRunner，用于从 export_data 中解析工作流
    logger.info("创建 RuntimeWorkflowRunner...")
    workflow_runner = RuntimeWorkflowRunner(
        export_config=export_data,
        current_user={"user_id": "test-user"},
        space_id=export_data.get("agent", {}).get("space_id", "default"),
    )

    # 创建 AgentCompiler，传入 workflow_runner
    compiler = AgentCompiler(workflow_runner=workflow_runner)

    # 从环境变量读取用户数据
    userdata = os.environ.get("RUNTIME_USERDATA")
    logger.info(f"用户数据: {mask_userdata(userdata)}")

    # 启动 Runner
    logger.info("启动 Runner...")
    from openjiuwen.core.runner import Runner

    # 设置工作流超时时间（支持从环境变量获取，默认 5 分钟）
    workflow_timeout = os.environ.get("WORKFLOW_EXECUTE_TIMEOUT", "300")
    os.environ["WORKFLOW_EXECUTE_TIMEOUT"] = workflow_timeout
    logger.info(f"设置 WORKFLOW_EXECUTE_TIMEOUT={workflow_timeout} 秒")

    runner_started = await Runner.start()
    logger.info(f"Runner 启动状态: {runner_started}")

    logger.info("开始编译 Agent 配置...")
    result = await compiler.compile_for_runtime(
        config=export_data,
        model_overrides=model_overrides,
        current_user={"user_id": "test-user"}
    )

    adapted_agent_config = ConfigAdapter.adapt(result["agent_config"])
    if isinstance(adapted_agent_config, LegacyReActAgentConfig):
        agent = LLMAgent(adapted_agent_config)
    elif isinstance(adapted_agent_config, LegacyWorkflowAgentConfig):
        agent = WorkflowAgent(adapted_agent_config)
    else:
        raise TypeError(f"Unsupported agent config type: {type(adapted_agent_config)}")

    workflow_providers = result.get("workflow_providers", [])
    workflow_factories = result.get("workflow_factories", [])
    plugin_tools = result.get("plugin_tools", [])

    # 优先使用 workflow_factories（使用 WorkflowFactory 包装）
    # WorkflowFactory 确保每次调用工作流时都获取全新的实例，避免状态泄漏导致连续调用卡住
    # 这是与 Studio 侧保持一致的关键修改
    if workflow_factories:
        logger.info(f"准备注册 {len(workflow_factories)} 个工作流工厂（WorkflowFactory 包装）...")
        for workflow_factory in workflow_factories:
            # workflow_factory 是 WorkflowFactory 实例，具有 id, version, name 等属性
            logger.info(f"正在注册工作流工厂: {getattr(workflow_factory, 'name', 'unknown')} (id={getattr(workflow_factory, 'workflow_id', 'unknown')})")
        agent.add_workflows(workflow_factories)
        logger.info(f"已通过 add_workflows 注册 {len(workflow_factories)} 个工作流工厂")
    elif workflow_providers:
        # 回退到 workflow_providers（没有 WorkflowFactory 包装）
        logger.info(f"准备注册 {len(workflow_providers)} 个工作流...")
        for workflow_card, workflow_provider in workflow_providers:
            logger.info(f"正在注册工作流: {workflow_card.name} (id={workflow_card.id})")
            logger.info(f"工作流 input_params: {workflow_card.input_params}")
        normalized_workflow_providers = normalize_workflow_providers_for_agent(workflow_providers)
        agent.add_workflows(normalized_workflow_providers)
        logger.info(f"已通过 add_workflows 注册 {len(normalized_workflow_providers)} 个工作流 provider")

    logger.info(f"准备注册 {len(plugin_tools)} 个插件工具...")
    for tool_instance in plugin_tools:
        tool_card = tool_instance.card
        logger.info(f"正在注册插件工具: {tool_card.name} (id={tool_card.id})")
    if plugin_tools:
        agent.add_tools(plugin_tools)
        logger.info(f"已通过 add_tools 注册 {len(plugin_tools)} 个插件工具")

    app.agent = agent

    # 统计实际注册的工作流数量
    registered_workflow_count = len(workflow_factories) if workflow_factories else len(workflow_providers)
    logger.info(f"Agent 加载成功! Type: {type(app.agent).__name__}")
    logger.info(f"Agent Card: {result['agent_card'].name}")
    logger.info(f"已注册 {registered_workflow_count} 个工作流, {len(plugin_tools)} 个插件")
    print(f"[OK] Agent 加载成功! Type: {type(app.agent).__name__}")
    print(f"[INFO] 使用配置文件: {file_path}")
    print(f"[INFO] 用户数据: {mask_userdata(userdata)}")
    print(f"[INFO] 已注册 {registered_workflow_count} 个工作流, {len(plugin_tools)} 个插件")


@app.agent_detail
async def agent_detail() -> dict:
    """返回当前加载 Agent 的完整 IR JSON。"""
    file_path = os.environ.get("RUNTIME_IR_PATH")
    ir_data = getattr(app, "ir_data", None)

    # 如果启动后缓存丢失，则按当前环境变量路径重新读取
    if ir_data is None and file_path:
        ir_data = _load_export_data(file_path)

    if not ir_data:
        return {
            "status": "error",
            "message": "IR data not loaded"
        }
    return {
        "status": "ok",
        "message": "success",
        "data": ir_data,
    }


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
        buffered_text_event = None
        buffered_text_delta = ""
        last_text_flush_at = asyncio.get_running_loop().time()
        overall_timeout = float(os.environ.get("WORKFLOW_EXECUTE_TIMEOUT", "300"))
        deadline = asyncio.get_running_loop().time() + overall_timeout
        pending_chunk_task = None
        stream_iter = Runner.run_agent_streaming(
            agent=app.agent,
            inputs=inputs,
            session=conversation_id
        )

        while True:
            try:
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                wait_timeout = min(_STREAM_IDLE_HEARTBEAT_SECONDS, remaining)
                if buffered_text_event is not None and buffered_text_delta:
                    wait_timeout = min(wait_timeout, _AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS)
                if wait_timeout <= 0:
                    raise asyncio.TimeoutError
                if pending_chunk_task is None:
                    pending_chunk_task = asyncio.create_task(stream_iter.__anext__())
                chunk = await asyncio.wait_for(
                    asyncio.shield(pending_chunk_task),
                    timeout=wait_timeout
                )
                pending_chunk_task = None
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                if asyncio.get_running_loop().time() >= deadline:
                    if pending_chunk_task is not None:
                        pending_chunk_task.cancel()
                    raise
                if (
                    buffered_text_event is not None
                    and buffered_text_delta
                    and (asyncio.get_running_loop().time() - last_text_flush_at) >= _AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS
                ):
                    events, buffered_text_event, buffered_text_delta = flush_buffered_agui_text_events(
                        buffered_text_event,
                        buffered_text_delta,
                    )
                    last_text_flush_at = asyncio.get_running_loop().time()
                    for event in events:
                        yield event, False
                    continue
                logger.info(
                    "Agent still running with no new chunks yet - conversation_id: %s, chunks=%s",
                    conversation_id,
                    chunk_count,
                )
                continue

            if chunk:
                chunk_count += 1
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[chunk #%s] %s", chunk_count, _summarize_chunk_for_log(chunk))
                events = convert_chunk_to_agui_events(
                    chunk=chunk,
                    trace_context=trace_context,
                    conversation_id=conversation_id,
                )
                events, buffered_text_event, buffered_text_delta = merge_agui_events_for_stream(
                    events,
                    buffered_text_event,
                    buffered_text_delta,
                )
                if events:
                    last_text_flush_at = asyncio.get_running_loop().time()
                for event in events:
                    yield event, False

        logger.info(f"Agent 执行完成 - conversation_id: {conversation_id}, chunks: {chunk_count}")

    except asyncio.TimeoutError:
        logger.error(f"Agent 执行超时 - conversation_id: {conversation_id}")
        events = agui_error_events(
            trace_context=trace_context,
            conversation_id=conversation_id,
            message="抱歉，响应超时，请重试",
            code="TIMEOUT",
        )
        for i, event in enumerate(events):
            yield event, i == len(events) - 1
        return

    except asyncio.CancelledError:
        logger.warning(f"Agent 查询流被取消 - conversation_id: {conversation_id}")
        raise

    except Exception as e:
        logger.error(f"Agent 执行出错 - conversation_id: {conversation_id}, error: {str(e)}", exc_info=True)
        events = agui_error_events(
            trace_context=trace_context,
            conversation_id=conversation_id,
            message=f"执行失败：{str(e)}",
            code="EXECUTION_FAILED",
        )
        for i, event in enumerate(events):
            yield event, i == len(events) - 1
        return

    # 检查是否没有任何chunk输出，目前报错会被底层吞掉，不会走到except，无法被捕获
    if chunk_count == 0:
        logger.error(f"Agent 执行未产生任何输出 - conversation_id: {conversation_id}，可能发生了内部错误")
        events = agui_error_events(
            trace_context=trace_context,
            conversation_id=conversation_id,
            message="AGENT或模型调用失败，请在Studio中测试AGENT或检查模型配置（API Key、Base URL、模型名称等）",
            code="0101",
        )
        for i, event in enumerate(events):
            yield event, i == len(events) - 1
        return  # 提前返回，error、finalize二选一

    final_events = finalize_agui_stream(
        trace_context=trace_context,
        conversation_id=conversation_id,
    )
    final_events, buffered_text_event, buffered_text_delta = merge_agui_events_for_stream(
        final_events,
        buffered_text_event,
        buffered_text_delta,
        force_flush=True,
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
