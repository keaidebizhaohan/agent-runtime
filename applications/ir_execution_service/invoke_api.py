# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""`/execute_invoke` 的业务逻辑与返回体转换。

约定：
- HTTP status 恒为 200，业务状态由 ResponseModel.code 表示（LowcodeApiResponseCode）。
- 返回体恒为 openjiuwen_studio.schemas.ResponseModel（与 stream 事件体同形）。
"""

from __future__ import annotations

import asyncio
import json
import os
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from openjiuwen.core.context_engine.schema.config import ContextEngineConfig
from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig, ModelRequestConfig
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent.agents.react_agent import ReActAgent, ReActAgentConfig as NewReActAgentConfig
from openjiuwen.core.single_agent.legacy.config import LegacyReActAgentConfig
from openjiuwen.core.single_agent.schema.agent_card import AgentCard
from openjiuwen_studio.lowcode import AgentCompiler
from openjiuwen_studio.lowcode.config_adapter import ConfigAdapter
from openjiuwen_studio.lowcode.schemas import ModelOverride
from openjiuwen_studio.schemas import ResponseModel

from dsl_workflow_dependency_loader import WorkflowLlmApiKeyMissingError
from runtime_support.http_response_contract import LowcodeApiResponseCode, ResponseDataType
from runtime_support.ir_fetch import (
    detect_executable_kind,
    ensure_ir_local_path,
    lowcode_code_from_http_exception,
)
from runtime_support.runtime_bootstrap import ensure_runtime_ready
from runtime_support.runtime_env import get_bool_env

JSON_MEDIA_TYPE = "application/json; charset=utf-8"


def _json_response(model: ResponseModel) -> JSONResponse:
    # HTTP 永远 200：让上层网关/前端只看 body.code
    return JSONResponse(model.model_dump(), media_type=JSON_MEDIA_TYPE)


def _error_model(
    code: LowcodeApiResponseCode,
    *,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ResponseModel:
    msg = message if message is not None else code.default_message
    body: dict[str, Any] = {"message": msg}
    if payload:
        body.update(payload)
    return ResponseModel(
        code=int(code),
        message=msg,
        data={"type": ResponseDataType.ERROR.value, "payload": body},
    )


def _to_jsonable(obj: Any) -> Any:
    """将 core/studio 的对象转换为 JSON 可序列化结构（dict/list/primitive）。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _invoke_exception_to_model(exc: Exception) -> ResponseModel:
    """invoke 路径异常 → ResponseModel（data.type=error）。"""
    from openjiuwen.core.common.exception.errors import BaseError

    if isinstance(exc, WorkflowLlmApiKeyMissingError):
        c = LowcodeApiResponseCode.LLM_API_KEY_MISSING
        return _error_model(c, message=str(exc))
    if isinstance(exc, asyncio.TimeoutError):
        code = LowcodeApiResponseCode.EXECUTION_TIMEOUT
        return _error_model(code, message=code.format_message())
    if isinstance(exc, BaseError):
        detail_code = int(getattr(exc, "code", LowcodeApiResponseCode.INTERNAL_ERROR))
        msg = str(getattr(exc, "message", "") or exc)
        return _error_model(
            LowcodeApiResponseCode.EXECUTION_FAILED,
            message=msg,
            payload={"detail_code": detail_code},
        )
    if isinstance(exc, ValueError):
        msg = str(exc)
        return _error_model(LowcodeApiResponseCode.INVALID_PARAM, message=msg)
    msg = str(exc)
    return _error_model(LowcodeApiResponseCode.INTERNAL_ERROR, message=msg)


def _agent_invoke_result_to_model(result: Any) -> ResponseModel:
    """agent.invoke：Runner.run_agent(react_agent).invoke 返回 dict → ResponseModel。"""
    ok = LowcodeApiResponseCode.SUCCESS

    if isinstance(result, dict):
        result_type = str(result.get("result_type") or "").strip()

        # 1) 正常回答
        if result_type == "answer":
            payload = {"output": str(result.get("output", "") or "")}
            return ResponseModel(code=int(ok), message=ok.default_message, data={"type": "result", "payload": payload})

        # 2) 业务失败（如 max iterations）
        if result_type == "error":
            raw_msg = result.get("message")
            if raw_msg is None:
                raw_msg = result.get("output")
            msg = str(raw_msg or "")
            code = LowcodeApiResponseCode.EXECUTION_FAILED
            return ResponseModel(
                code=int(code),
                message=msg.strip() or code.default_message,
                data={"type": "error", "payload": {"message": msg}},
            )

        # 3/5) workflow 中断（含恢复后仍中断）
        if result_type == "interrupt":
            payload = {
                "workflow_execution_state": _to_jsonable(result.get("workflow_execution_state")),
                "component_ids": _to_jsonable(result.get("component_ids", [])),
            }
            return ResponseModel(code=int(ok), message=ok.default_message, data={"type": "interaction", "payload": payload})

        # 4) Rail 强制终止等：有 result_type 且非 answer/error/interrupt → force_finish，整包透传
        if result_type:
            return ResponseModel(
                code=int(ok),
                message=ok.default_message,
                data={
                    "type": ResponseDataType.FORCE_FINISH.value,
                    "payload": _to_jsonable(result),
                },
            )

        # 未携带 result_type：类型标为 unknown，整包透传
        return ResponseModel(
            code=int(ok),
            message=ok.default_message,
            data={"type": ResponseDataType.UNKNOWN.value, "payload": _to_jsonable(result)},
        )

    return ResponseModel(code=int(ok), message=ok.default_message, data={"type": "result", "payload": _to_jsonable(result)})


def _workflow_invoke_result_to_model(result: Any) -> ResponseModel:
    """workflow.invoke：按 README 转换（含 invoke 返回 list 的不支持分支）。"""
    from openjiuwen.core.common.constants.constant import INTERACTION
    from openjiuwen.core.session.stream import OutputSchema
    from openjiuwen.core.workflow import WorkflowExecutionState, WorkflowOutput

    ok = LowcodeApiResponseCode.SUCCESS

    # Runner.run_workflow 返回 WorkflowOutput（state + result），先解包再判定
    if isinstance(result, WorkflowOutput):
        state = getattr(result, "state", None)
        inner = getattr(result, "result", None)
        if state == WorkflowExecutionState.INPUT_REQUIRED:
            result = inner if inner is not None else []
        elif state == WorkflowExecutionState.COMPLETED:
            result = inner
        else:
            result = inner

    # 正常完成（非流式）：dict → payload={"data": result}
    if isinstance(result, dict):
        return ResponseModel(
            code=int(ok),
            message=ok.default_message,
            data={"type": "result", "payload": {"data": _to_jsonable(result)}},
        )

    # 交互中断或“误把流式当 invoke”：core 可能返回 list[OutputSchema(...), ...]
    if isinstance(result, list):
        # 交互中断：只取 type="__interaction__" 的那一条，其他丢弃
        for item in result:
            output_type = None
            payload_obj: Any = None
            if isinstance(item, OutputSchema):
                output_type = item.type
                payload_obj = item.payload
            elif isinstance(item, dict):
                output_type = item.get("type")
                payload_obj = item.get("payload")

            if output_type == INTERACTION:
                payload_json = _to_jsonable(payload_obj)
                interaction_id = payload_json.get("id") if isinstance(payload_json, dict) else None
                interaction_value = payload_json.get("value") if isinstance(payload_json, dict) else None
                return ResponseModel(
                    code=int(ok),
                    message=ok.default_message,
                    data={"type": "interaction", "payload": {"id": interaction_id, "value": interaction_value}},
                )

        # 正常完成但 end 节点为 stream 等开关导致 result=list：invoke 不支持，直接报错
        c = LowcodeApiResponseCode.INVOKE_NOT_SUPPORTED
        return ResponseModel(
            code=int(c),
            message=c.default_message,
            data={"type": "error", "payload": {"error_code": int(c), "error_message": c.default_message}},
        )

    # 兜底：保守透传为 result.data
    return ResponseModel(code=int(ok), message=ok.default_message, data={"type": "result", "payload": {"data": _to_jsonable(result)}})


def _normalize_runtime_config_for_react_agent(
    config: LegacyReActAgentConfig | NewReActAgentConfig,
    *,
    resolved_agent_dict: dict[str, Any] | None,
) -> NewReActAgentConfig:
    """兼容 legacy/new 两种 ReActAgentConfig，统一为 core 新版配置。"""
    if isinstance(config, NewReActAgentConfig):
        return config

    # legacy 结构：将常用字段映射到新版
    model_name = getattr(config, "model_name", "") or ""
    m = getattr(config, "model_config", None)
    info = getattr(m, "model_info", None) if m is not None else None
    mcc = ModelClientConfig(
        model_provider=str(getattr(m, "model_provider", "") or ""),
        api_key=str(getattr(info, "api_key", "") or ""),
        api_base=str(getattr(info, "api_base", "") or ""),
        verify_ssl=get_bool_env("LLM_SSL_VERIFY", True),
    )
    mrc = ModelRequestConfig(
        temperature=getattr(info, "temperature", None),
        max_tokens=getattr(info, "max_tokens", None),
        timeout=float(getattr(info, "timeout", 60) or 60),
    )
    ctx_cfg = ContextEngineConfig(
        max_context_message_num=200,
        default_window_round_num=config.constrain.reserved_max_chat_rounds,
    )
    return NewReActAgentConfig(
        mem_scope_id=config.memory_scope_id or "",
        model_name=str(model_name),
        model_provider=str(m.model_provider),
        api_key=str(getattr(info, "api_key", "") or ""),
        api_base=str(getattr(info, "api_base", "") or ""),
        prompt_template_name=config.prompt_template_name or "",
        prompt_template=list(config.prompt_template or []),
        max_iterations=config.constrain.max_iteration,
        model_client_config=mcc,
        model_config_obj=mrc,
        context_engine_config=ctx_cfg,
    )


async def build_react_agent(ir_path: Path, current_user: dict[str, Any]) -> ReActAgent:
    # 保持对外函数名不变，但实现迁移到公共模块，供 stream/invoke 共用
    from react_agent_builder import build_react_agent as _build  # noqa: E402

    export_data = json.loads(ir_path.read_text(encoding="utf-8"))
    model_overrides = _build_model_overrides_from_default_llm_env(export_data)
    return await _build(ir_path, current_user, model_overrides=model_overrides or None)


def _build_model_overrides_from_default_llm_env(export_data: dict[str, Any]) -> dict[str, ModelOverride]:
    """从环境变量生成模型覆盖配置（只补齐非空字段）。返回 Dict[model_id, ModelOverride]。"""
    default_llm = export_data.get("default_llm") if isinstance(export_data, dict) else None
    if not isinstance(default_llm, dict):
        default_llm = {}

    model_name = (os.environ.get("LLM_BASIC_MODEL") or "").strip()
    api_base = (os.environ.get("LLM_BASIC_BASE_URL") or "").strip()
    api_key = (os.environ.get("LLM_BASIC_API_KEY") or "").strip()
    api_type = (os.environ.get("LLM_BASIC_API_TYPE") or "").strip()
    ssl_verify = (os.environ.get("LLM_SSL_VERIFY") or "").strip()

    # 若环境没配则不覆盖（保持导出 IR 的 default_llm）
    if not any([model_name, api_base, api_key, api_type, ssl_verify]):
        return {}

    d = dict(default_llm)
    if model_name:
        d["model_name"] = model_name
    if api_base:
        d["api_base"] = api_base
    if api_key:
        d["api_key"] = api_key
    if api_type:
        d["api_type"] = api_type
    if ssl_verify:
        d["ssl_verify"] = ssl_verify.lower() in ("1", "true", "yes", "on")

    override = ModelOverride(model_id=d.get("model_id", "default"), **d)
    key = str(getattr(override, "model_id", "") or "").strip() or "default"
    return {key: override}


async def handle_execute_invoke(body: Any) -> JSONResponse:
    """FastAPI 路由层入口：POST /execute_invoke."""
    try:
        await ensure_runtime_ready()
    except Exception as e:
        logging.getLogger(__name__).exception("service unavailable during startup: %s", e)
        return _json_response(_error_model(LowcodeApiResponseCode.SERVICE_UNAVAILABLE, message=str(e)))

    try:
        ir_local_json_path = await ensure_ir_local_path(getattr(body, "ir_path"))
    except HTTPException as he:
        lc, msg = lowcode_code_from_http_exception(he)
        return _json_response(_error_model(lc, message=msg))

    try:
        ir_root = json.loads(ir_local_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        c = LowcodeApiResponseCode.IR_INVALID
        return _json_response(_error_model(c, message=f"{c.default_message}: {exc}"))

    try:
        executable_kind = detect_executable_kind(ir_root)
    except HTTPException as he:
        lc, msg = lowcode_code_from_http_exception(he)
        if he.status_code == 400 and "neither workflow" in (msg or "").lower():
            lc = LowcodeApiResponseCode.IR_INVALID
        return _json_response(_error_model(lc, message=msg))

    try:
        inputs_obj = json.loads(getattr(body, "inputs"))
    except json.JSONDecodeError as exc:
        c = LowcodeApiResponseCode.INVALID_INPUTS
        return _json_response(_error_model(c, message=f"{c.default_message}: {exc}"))
    if not isinstance(inputs_obj, dict):
        c = LowcodeApiResponseCode.INVALID_INPUTS
        return _json_response(_error_model(c, message="inputs must decode to a JSON object"))

    # 续跑输入（workflow）：HTTP 约定字段 "__interactive_reply" → core InteractiveInput
    # 支持两种形态：
    # 1) {"__interactive_reply": "<text>"} -> InteractiveInput(raw_inputs="<text>")
    # 2) {"__interactive_reply": {"id": "<node_id>", "value": <any>}} -> InteractiveInput().update(id, value)
    if executable_kind == "workflow" and set(inputs_obj.keys()) == {"__interactive_reply"}:
        from openjiuwen.core.session import InteractiveInput

        reply = inputs_obj["__interactive_reply"]
        if isinstance(reply, dict) and (reply.get("id") is not None):
            ii = InteractiveInput()
            ii.update(str(reply.get("id")), reply.get("value"))
            inputs_obj = ii
        else:
            inputs_obj = InteractiveInput(reply)

    space_id = os.environ.get("WORKFLOW_SPACE_ID", "default")
    current_user = {"user_id": getattr(body, "user_id"), "space_id": space_id}

    # Agent 路径可自动补 user_id，workflow 路径必须严格按 DSL schema
    if executable_kind == "agent" and "user_id" not in inputs_obj:
        inputs_obj = dict(inputs_obj)
        inputs_obj["user_id"] = getattr(body, "user_id")

    timeout_seconds = getattr(body, "timeout_ms") / 1000.0
    session_id = getattr(body, "conversation_id")

    if executable_kind == "workflow":
        from workflow_ir_builder import build_core_workflow_from_ir_file

        try:
            workflow = await build_core_workflow_from_ir_file(
                str(ir_local_json_path.resolve()), space_id=space_id, current_user=current_user
            )
        except WorkflowLlmApiKeyMissingError as e:
            c = LowcodeApiResponseCode.LLM_API_KEY_MISSING
            return _json_response(_error_model(c, message=str(e)))
        except Exception as e:
            return _json_response(_error_model(LowcodeApiResponseCode.IR_LOAD_FAILED, message=str(e)))

        try:
            wf_output = await asyncio.wait_for(
                Runner.run_workflow(workflow=workflow, inputs=inputs_obj, session=session_id),
                timeout=timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.getLogger(__name__).exception("workflow invoke failed: %s", e)
            return _json_response(_invoke_exception_to_model(e))

        return _json_response(_workflow_invoke_result_to_model(wf_output))

    try:
        react_agent = await build_react_agent(ir_local_json_path.resolve(), current_user)
    except Exception as e:
        return _json_response(_error_model(LowcodeApiResponseCode.IR_LOAD_FAILED, message=str(e)))

    try:
        agent_output = await asyncio.wait_for(
            Runner.run_agent(agent=react_agent, inputs=inputs_obj, session=session_id),
            timeout=timeout_seconds,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.getLogger(__name__).exception("agent invoke failed: %s", e)
        return _json_response(_invoke_exception_to_model(e))

    return _json_response(_agent_invoke_result_to_model(agent_output))

