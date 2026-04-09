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
import copy
import logging
import os
import sys
import uuid
import asyncio
import threading
import traceback
import time
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
# 流式首帧/帧间超时默认值不应与总超时一致（300s 会导致客户端超时后服务端长时间悬挂）。
# 允许通过环境变量覆盖，默认 12 秒。
os.environ.setdefault("WORKFLOW_STREAM_FRAME_TIMEOUT", "12")
os.environ.setdefault("WORKFLOW_STREAM_FIRST_FRAME_TIMEOUT", "12")

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

_STRICT_LOGGER_HANDLER_NAMES = (
    "common",
    "agent",
    "llm",
    "tool",
    "session",
    "workflow",
    "memory",
    "retrieval",
    "context_engine",
    "openjiuwen_runtime.service.app.agent_app",
)
_ALLOWED_LOG_HANDLER_IDS: set[int] = set()


def _sanitize_runtime_logger_handlers(reason: str) -> None:
    """只保留白名单 handler，避免运行期动态注入阻塞型日志通道。"""
    if not _ALLOWED_LOG_HANDLER_IDS:
        return
    for logger_name in _STRICT_LOGGER_HANDLER_NAMES:
        target_logger = logging.getLogger(logger_name)
        removed = 0
        for h in list(target_logger.handlers):
            if id(h) not in _ALLOWED_LOG_HANDLER_IDS:
                target_logger.removeHandler(h)
                removed += 1
        target_logger.propagate = False
        if removed > 0:
            logging.getLogger("lowcode_agent").warning(
                "[runtime_handler_sanitize] reason=%s logger=%s removed=%s",
                reason,
                logger_name,
                removed,
            )


def _setup_logging():
    """配置日志系统"""
    venv_path = _get_venv_path()
    log_dir = os.path.join(venv_path, "logs")
    log_level_name = os.environ.get("LOWCODE_AGENT_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    enable_console_log = os.environ.get("LOWCODE_AGENT_CONSOLE_LOG", "0").lower() in ("1", "true", "yes", "on")
    disable_global_stream_log = os.environ.get("LOWCODE_AGENT_DISABLE_GLOBAL_STREAM_LOG", "1").lower() in ("1", "true", "yes", "on")
    log_emit_slow_threshold_seconds = float(
        os.environ.get("LOWCODE_AGENT_LOG_EMIT_SLOW_THRESHOLD_SECONDS", "0.2")
    )

    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "agent_execution.log")
    log_emit_diag_file = os.path.join(log_dir, "log_emit_diagnostics.log")
    # 启动即创建诊断文件，避免“未触发慢日志就看不到文件”带来的误判
    with open(log_emit_diag_file, "a", encoding="utf-8"):
        pass

    # 配置日志格式
    log_format = "%(asctime)s | %(name)s | %(filename)s:%(lineno)d | %(levelname)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    global _ALLOWED_LOG_HANDLER_IDS

    # 配置 root logger
    logger = logging.getLogger("lowcode_agent")
    logger.setLevel(log_level)

    def _handler_desc(handler: logging.Handler) -> str:
        stream_name = ""
        if hasattr(handler, "stream") and getattr(handler, "stream") is not None:
            stream_name = getattr(getattr(handler, "stream"), "name", "")
        return (
            f"{type(handler).__name__}"
            f"(level={logging.getLevelName(handler.level)}, stream={stream_name or 'n/a'})"
        )

    emit_diag_lock = threading.Lock()
    wrapped_handler_ids: set[int] = set()
    emit_probe_last_begin_ts: dict[str, float] = {}

    def _append_emit_diag(message: str) -> None:
        try:
            with emit_diag_lock:
                with open(log_emit_diag_file, "a", encoding="utf-8") as f:
                    f.write(message + "\n")
        except Exception:
            pass

    def _append_emit_diag_raw(message: str) -> None:
        """低层追加写，尽量减少被 logging 自身锁链路影响。"""
        try:
            fd = os.open(log_emit_diag_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, (message + "\n").encode("utf-8", errors="ignore"))
            finally:
                os.close(fd)
        except Exception:
            pass

    def _install_emit_probe(logger_name: str, target_logger: logging.Logger) -> None:
        for handler in list(target_logger.handlers):
            hid = id(handler)
            if hid in wrapped_handler_ids:
                continue
            original_emit = handler.emit
            handler_name = type(handler).__name__
            stream_name = ""
            if hasattr(handler, "stream") and getattr(handler, "stream") is not None:
                stream_name = getattr(getattr(handler, "stream"), "name", "")

            def _emit_with_probe(record, _orig=original_emit, _lname=logger_name, _hname=handler_name, _sname=stream_name):
                started = time.perf_counter()
                try:
                    return _orig(record)
                finally:
                    elapsed = time.perf_counter() - started
                    if elapsed >= log_emit_slow_threshold_seconds:
                        _append_emit_diag(
                            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                            f"logger={_lname or 'root'} handler={_hname} stream={_sname or 'n/a'} "
                            f"level={record.levelname} elapsed={elapsed:.3f}s msg={record.getMessage()[:200]}"
                        )

            handler.emit = _emit_with_probe
            wrapped_handler_ids.add(hid)

    # 全局兜底探针：覆盖所有 Handler（包括运行期动态创建的 handler）
    # 仅记录耗时，不改变原语义，避免遗漏未被 _install_emit_probe 扫描到的 logger/handler。
    if not getattr(logging.Handler, "_lowcode_probe_patched", False):
        original_handle = logging.Handler.handle

        def _handle_with_probe(self, record):
            # 进入 handle 前先落一条 begin，避免卡在 flush 时 finally 无法执行导致无诊断。
            # 节流：同一 logger/handler 每秒最多 1 条 begin。
            logger_name = record.name or "root"
            handler_name = type(self).__name__
            begin_key = f"{logger_name}:{handler_name}"
            now = time.perf_counter()
            last_ts = emit_probe_last_begin_ts.get(begin_key, 0.0)
            if (now - last_ts) >= 1.0 and (
                logger_name.startswith("common")
                or logger_name.startswith("llm")
                or logger_name.startswith("session")
                or logger_name.startswith("openjiuwen")
            ):
                stream_name = ""
                if hasattr(self, "stream") and getattr(self, "stream") is not None:
                    stream_name = getattr(getattr(self, "stream"), "name", "")
                _append_emit_diag_raw(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"BEGIN logger={logger_name} handler={handler_name} stream={stream_name or 'n/a'} "
                    f"level={record.levelname} msg={record.getMessage()[:200]}"
                )
                emit_probe_last_begin_ts[begin_key] = now

            started = time.perf_counter()
            try:
                return original_handle(self, record)
            finally:
                elapsed = time.perf_counter() - started
                if elapsed >= log_emit_slow_threshold_seconds:
                    _append_emit_diag(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                        f"logger={record.name or 'root'} handler={type(self).__name__} "
                        f"level={record.levelname} elapsed={elapsed:.3f}s msg={record.getMessage()[:200]}"
                    )

        logging.Handler.handle = _handle_with_probe
        setattr(logging.Handler, "_lowcode_probe_patched", True)

    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        _ALLOWED_LOG_HANDLER_IDS = {id(file_handler)}

        # 控制台 handler（默认关闭，避免高并发时 stdout flush 阻塞事件循环）
        if enable_console_log:
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
            # 切断向 root logger 传播，避免命中其他 StreamHandler 导致阻塞
            oj_logger.propagate = False

        # 防止运行时二次挂载 stdout/server 日志 handler 导致 flush 阻塞
        original_add_handler = logging.Logger.addHandler
        if not getattr(logging.Logger, "_lowcode_strict_add_handler_patched", False):
            def _strict_add_handler(self, hdlr):
                target_name = getattr(self, "name", "")
                if target_name in _STRICT_LOGGER_HANDLER_NAMES and id(hdlr) not in _ALLOWED_LOG_HANDLER_IDS:
                    logger.warning(
                        "[runtime_handler_blocked] logger=%s handler=%s stream=%s",
                        target_name,
                        type(hdlr).__name__,
                        getattr(getattr(hdlr, "stream", None), "name", "n/a"),
                    )
                    return
                return original_add_handler(self, hdlr)
            logging.Logger.addHandler = _strict_add_handler
            setattr(logging.Logger, "_lowcode_strict_add_handler_patched", True)

        if disable_global_stream_log:
            # 先清理 openjiuwen 相关 logger 上的 stdout/stderr StreamHandler（保留 FileHandler）
            prune_logger_names = list(dict.fromkeys(openjiuwen_loggers + ["openjiuwen", "lowcode_agent"]))
            for name in prune_logger_names:
                target_logger = logging.getLogger(name)
                removed = 0
                for h in list(target_logger.handlers):
                    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                        target_logger.removeHandler(h)
                        removed += 1
                if removed > 0:
                    logger.info(
                        "已移除非文件 StreamHandler - logger=%s removed=%s",
                        name,
                        removed,
                    )

            target_logger_names = ["", "root", "uvicorn", "uvicorn.error", "uvicorn.access"]
            for name in target_logger_names:
                target_logger = logging.getLogger(name)
                removed = 0
                for h in list(target_logger.handlers):
                    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                        target_logger.removeHandler(h)
                        removed += 1
                if removed > 0:
                    logger.info(
                        "已移除非文件 StreamHandler - logger=%s removed=%s",
                        name or "root",
                        removed,
                    )

        _sanitize_runtime_logger_handlers(reason="startup")

        # 输出关键 logger 的 handler 详情，便于定位异常日志通道
        inspect_logger_names = [
            "",
            "lowcode_agent",
            "session",
            "common",
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
        ]
        for name in inspect_logger_names:
            inspect_logger = logging.getLogger(name)
            handlers_desc = ", ".join(_handler_desc(h) for h in inspect_logger.handlers) or "no-handlers"
            logger.info(
                "logger_handlers - logger=%s propagate=%s handlers=[%s]",
                name or "root",
                inspect_logger.propagate,
                handlers_desc,
            )
            _install_emit_probe(name or "root", inspect_logger)

        logger.info("=" * 60)
        logger.info(f"Lowcode Agent Runner 启动")
        logger.info(f"虚拟环境路径: {venv_path}")
        logger.info(f"日志文件路径: {log_file}")
        logger.info(f"控制台日志: {'开启' if enable_console_log else '关闭'}")
        logger.info(f"全局 StreamHandler 移除: {'开启' if disable_global_stream_log else '关闭'}")
        logger.info(f"慢日志探针文件: {log_emit_diag_file}")
        logger.info(f"慢日志阈值: {log_emit_slow_threshold_seconds:.3f}s")
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


def _log_main_thread_stack(prefix: str) -> None:
    """从后台线程抓取主线程堆栈，定位卡死位置。"""
    try:
        frames = sys._current_frames()
        main_frame = frames.get(_MAIN_THREAD_ID) if _MAIN_THREAD_ID is not None else None
        if not main_frame:
            logger.warning("%s | 无法获取主线程栈", prefix)
            return
        stack_text = "".join(traceback.format_stack(main_frame))
        logger.error("%s | 主线程栈:\n%s", prefix, stack_text)
    except Exception:
        logger.exception("%s | 抓取主线程栈失败", prefix)

# 初始化 logger
logger = _setup_logging()
VENV_PATH = _get_venv_path()

FILE_PATH = ''
_STREAM_IDLE_HEARTBEAT_SECONDS = 15.0
_AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS = float(
    os.environ.get("AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS", "0.12")
)
_STREAM_WAIT_DIAGNOSTIC_INTERVAL_SECONDS = float(
    os.environ.get("WORKFLOW_STREAM_WAIT_DIAGNOSTIC_INTERVAL_SECONDS", "3")
)
_STREAM_NEXT_POLL_SECONDS = float(
    os.environ.get("WORKFLOW_STREAM_NEXT_POLL_SECONDS", "0.8")
)
_STREAM_BLOCK_STACK_DUMP_SECONDS = float(
    os.environ.get("WORKFLOW_STREAM_BLOCK_STACK_DUMP_SECONDS", "4")
)
_MAIN_THREAD_ID = threading.main_thread().ident

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


def _enrich_agent_workflows_with_dependency_inputs(agent_config: dict, export_data: dict) -> dict:
    """Backfill workflow input parameters from dependencies into agent.workflows.

    In multi-workflow agents, `agent.workflows` may only contain id/name/version, while
    `dependencies.workflows` has complete `input_parameters`. WorkflowController builds
    task inputs from agent config cards, so we must merge dependency input definitions.
    """
    if not isinstance(agent_config, dict):
        return agent_config
    dependencies = export_data.get("dependencies", {}) if isinstance(export_data, dict) else {}
    dep_workflows = dependencies.get("workflows", [])
    if not isinstance(dep_workflows, list) or not dep_workflows:
        return agent_config

    merged = copy.deepcopy(agent_config)
    workflows = merged.get("workflows", [])
    if not isinstance(workflows, list) or not workflows:
        return merged

    dep_index = {}
    for wf in dep_workflows:
        if not isinstance(wf, dict):
            continue
        wf_id = wf.get("workflow_id") or wf.get("id")
        wf_ver = wf.get("workflow_version") or wf.get("version") or "draft"
        if wf_id:
            dep_index[(str(wf_id), str(wf_ver))] = wf
            dep_index[(str(wf_id), "")] = wf

    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        wf_id = wf.get("workflow_id") or wf.get("id")
        wf_ver = wf.get("workflow_version") or wf.get("version") or ""
        dep = dep_index.get((str(wf_id), str(wf_ver))) or dep_index.get((str(wf_id), ""))
        if not dep:
            continue
        if not wf.get("input_params") and not wf.get("input_parameters"):
            dep_input = dep.get("input_params") or dep.get("input_parameters") or []
            if dep_input:
                wf["input_parameters"] = dep_input
    return merged


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

    enriched_agent_config = _enrich_agent_workflows_with_dependency_inputs(result["agent_config"], export_data)
    adapted_agent_config = ConfigAdapter.adapt(enriched_agent_config)
    if isinstance(adapted_agent_config, LegacyReActAgentConfig):
        agent = LLMAgent(adapted_agent_config)
    elif isinstance(adapted_agent_config, LegacyWorkflowAgentConfig):
        agent = WorkflowAgent(adapted_agent_config)
    else:
        raise TypeError(f"Unsupported agent config type: {type(adapted_agent_config)}")

    workflow_providers = result.get("workflow_providers", [])
    workflow_factories = result.get("workflow_factories", [])
    plugin_tools = result.get("plugin_tools", [])

    # 优先使用 workflow_providers，确保 input_params 元数据完整可见。
    # 部分 Runtime 版本在 WorkflowFactory 路径下可能拿不到预期 schema，导致任务入参退化为 {"query": ...}。
    if workflow_providers:
        logger.info(f"准备注册 {len(workflow_providers)} 个工作流...")
        for workflow_card, workflow_provider in workflow_providers:
            logger.info(f"正在注册工作流: {workflow_card.name} (id={workflow_card.id})")
            logger.info(f"工作流 input_params: {workflow_card.input_params}")
        normalized_workflow_providers = normalize_workflow_providers_for_agent(workflow_providers)
        agent.add_workflows(normalized_workflow_providers)
        logger.info(f"已通过 add_workflows 注册 {len(normalized_workflow_providers)} 个工作流 provider")
    elif workflow_factories:
        # 回退到 workflow_factories（仅当 provider 不可用）
        logger.info(f"准备注册 {len(workflow_factories)} 个工作流工厂（WorkflowFactory 包装）...")
        for workflow_factory in workflow_factories:
            logger.info(
                f"正在注册工作流工厂: {getattr(workflow_factory, 'name', 'unknown')} "
                f"(id={getattr(workflow_factory, 'workflow_id', 'unknown')})"
            )
        agent.add_workflows(workflow_factories)
        logger.info(f"已通过 add_workflows 注册 {len(workflow_factories)} 个工作流工厂")

    logger.info(f"准备注册 {len(plugin_tools)} 个插件工具...")
    for tool_instance in plugin_tools:
        tool_card = tool_instance.card
        logger.info(f"正在注册插件工具: {tool_card.name} (id={tool_card.id})")
    if plugin_tools:
        agent.add_tools(plugin_tools)
        logger.info(f"已通过 add_tools 注册 {len(plugin_tools)} 个插件工具")

    app.agent = agent

    # 统计实际注册的工作流数量
    registered_workflow_count = len(workflow_providers) if workflow_providers else len(workflow_factories)
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
async def query(msgs, request, cancel_event=None) -> AsyncIterator[Tuple[dict, bool]]:
    """处理查询请求"""
    conversation_id = request.conversation_id
    _sanitize_runtime_logger_handlers(reason=f"query_start:{conversation_id}")
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

    stream_iter = None
    cancelled_by_client = False
    timeout_stage = "unknown"
    timeout_limit = None
    try:
        chunk_count = 0
        buffered_text_event = None
        buffered_text_delta = ""
        loop = asyncio.get_running_loop()
        last_text_flush_at = loop.time()
        last_chunk_at = loop.time()
        last_wait_diag_at = loop.time()
        overall_timeout = float(os.environ.get("WORKFLOW_EXECUTE_TIMEOUT", "300"))
        first_frame_timeout = float(os.environ.get("WORKFLOW_STREAM_FIRST_FRAME_TIMEOUT", str(overall_timeout)))
        frame_timeout = float(os.environ.get("WORKFLOW_STREAM_FRAME_TIMEOUT", str(overall_timeout)))
        deadline = loop.time() + overall_timeout
        logger.info(
            "流式超时配置 - conversation_id=%s overall=%.2fs first_frame=%.2fs frame=%.2fs",
            conversation_id,
            overall_timeout,
            first_frame_timeout,
            frame_timeout,
        )
        logger.info("开始创建流迭代器 - conversation_id=%s", conversation_id)
        create_iter_started_at = loop.time()
        stream_iter = await asyncio.to_thread(
            Runner.run_agent_streaming,
            agent=app.agent,
            inputs=inputs,
            session=conversation_id,
        )
        logger.info(
            "流迭代器创建完成 - conversation_id=%s elapsed=%.3fs",
            conversation_id,
            loop.time() - create_iter_started_at,
        )
        first_chunk_received = False

        async with asyncio.timeout_at(deadline):
            while True:
                # 即使底层还没产出 chunk，也要优先处理客户端断连，避免悬挂协程
                if cancel_event and cancel_event.is_set():
                    cancelled_by_client = True
                    logger.info(f"客户端已断开，停止处理 - conversation_id: {conversation_id}")
                    break

                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()

                next_timeout = min(
                    first_frame_timeout if not first_chunk_received else frame_timeout,
                    remaining,
                )
                timeout_stage = "first_frame" if not first_chunk_received else "next_frame"
                timeout_limit = next_timeout
                stage_started_at = loop.time()
                chunk = None
                reached_stream_end = False

                if (loop.time() - last_wait_diag_at) >= _STREAM_WAIT_DIAGNOSTIC_INTERVAL_SECONDS:
                    logger.info(
                        "等待流式输出中 - conversation_id=%s stage=%s chunks=%s waited_since_last_chunk=%.3fs remaining=%.3fs",
                        conversation_id,
                        timeout_stage,
                        chunk_count,
                        loop.time() - last_chunk_at,
                        remaining,
                    )
                    last_wait_diag_at = loop.time()

                while True:
                    if cancel_event and cancel_event.is_set():
                        cancelled_by_client = True
                        logger.info(f"客户端已断开（等待下一帧中），停止处理 - conversation_id: {conversation_id}")
                        break

                    elapsed_for_stage = loop.time() - stage_started_at
                    stage_remaining = next_timeout - elapsed_for_stage
                    overall_remaining = deadline - loop.time()
                    poll_timeout = min(_STREAM_NEXT_POLL_SECONDS, stage_remaining, overall_remaining)
                    if poll_timeout <= 0:
                        raise asyncio.TimeoutError()

                    block_watchdog = None
                    try:
                        if _STREAM_BLOCK_STACK_DUMP_SECONDS > 0:
                            block_watchdog = threading.Timer(
                                _STREAM_BLOCK_STACK_DUMP_SECONDS,
                                _log_main_thread_stack,
                                kwargs={
                                    "prefix": (
                                        f"[stream_block_watchdog] conversation_id={conversation_id} "
                                        f"stage={timeout_stage} poll_timeout={poll_timeout:.3f}s "
                                        f"chunk_count={chunk_count}"
                                    )
                                },
                            )
                            block_watchdog.daemon = True
                            block_watchdog.start()
                        try:
                            async with asyncio.timeout(poll_timeout):
                                chunk = await stream_iter.__anext__()
                        except TimeoutError:
                            # 细粒度轮询：允许尽快感知客户端断连，而不是一次性等待 12 秒
                            continue
                        except StopAsyncIteration:
                            reached_stream_end = True
                            break
                    finally:
                        if block_watchdog:
                            block_watchdog.cancel()

                if cancelled_by_client:
                    break
                if reached_stream_end:
                    break

                if chunk:
                    first_chunk_received = True
                    chunk_count += 1
                    last_chunk_at = loop.time()
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
                        last_text_flush_at = loop.time()
                    for event in events:
                        yield event, False

                if (
                    buffered_text_event is not None
                    and buffered_text_delta
                    and (loop.time() - last_text_flush_at) >= _AGUI_TEXT_DELTA_FLUSH_INTERVAL_SECONDS
                ):
                    events, buffered_text_event, buffered_text_delta = flush_buffered_agui_text_events(
                        buffered_text_event,
                        buffered_text_delta,
                    )
                    last_text_flush_at = loop.time()
                    for event in events:
                        yield event, False

        logger.info(f"Agent 执行完成 - conversation_id: {conversation_id}, chunks: {chunk_count}")

    except asyncio.TimeoutError:
        logger.error(
            "Agent 执行超时 - conversation_id=%s stage=%s timeout=%.3fs chunks=%s",
            conversation_id,
            timeout_stage,
            timeout_limit or -1.0,
            chunk_count if 'chunk_count' in locals() else -1,
        )
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
        err_text = str(e)
        if "created in a different Context" in err_text and "ContextVar" in err_text:
            logger.error(
                "[contextvar_context_mismatch] conversation_id=%s stage=%s chunks=%s error=%s",
                conversation_id,
                timeout_stage,
                chunk_count if 'chunk_count' in locals() else -1,
                err_text,
            )
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

    finally:
        if stream_iter is not None:
            try:
                logger.info("关闭流迭代器 - conversation_id=%s", conversation_id)
                await stream_iter.aclose()
            except Exception:
                # 忽略清理阶段异常，避免覆盖主流程错误
                logger.warning("关闭流迭代器失败 - conversation_id=%s", conversation_id, exc_info=True)

    if cancelled_by_client:
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
