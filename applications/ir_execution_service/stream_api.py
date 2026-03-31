# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""`/execute_stream` 的 SSE 逻辑与 chunk→ResponseModel 映射。

约定：
- FastAPI 路由返回 EventSourceResponse；
- 每个 SSE event 的 data 部分都是 `ResponseModel` 的 JSON 字符串；
- code 统一使用 LowcodeApiResponseCode，data.type 使用 ResponseDataType。
"""

from __future__ import annotations

import asyncio
import json
import os
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from dsl_workflow_dependency_loader import WorkflowLlmApiKeyMissingError
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from openjiuwen.core.runner import Runner
from openjiuwen_studio.schemas import ResponseModel

from runtime_support.http_response_contract import LowcodeApiResponseCode, ResponseDataType
from runtime_support.ir_fetch import (
    detect_executable_kind,
    ensure_ir_local_path,
    lowcode_code_from_http_exception,
)
from runtime_support.runtime_bootstrap import ensure_runtime_ready

# agent 构建与 JSON 序列化为公共能力
from react_agent_builder import build_react_agent  # noqa: E402
from invoke_api import _to_jsonable  # noqa: E402


@asynccontextmanager
async def _optional_async_timeout(seconds: float):
    """Python 3.11+ 的 asyncio.timeout 统一包一层，方便测试/兼容。"""
    timeout_cm = getattr(asyncio, "timeout", None)
    if timeout_cm is not None:
        async with timeout_cm(seconds):
            yield
    else:
        yield


def _sse_include_trace() -> bool:
    return (os.environ.get("LOWCODE_SSE_INCLUDE_TRACE") or "").strip().lower() in ("1", "true", "yes", "on")


def _stream_error_event(
    code: LowcodeApiResponseCode,
    *,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    msg = message if message is not None else code.default_message
    body: dict[str, Any] = {"message": msg}
    if payload:
        body.update(payload)
    return ResponseModel(
        code=int(code),
        message=msg,
        data={"type": ResponseDataType.ERROR.value, "payload": body},
    ).model_dump_json()


def _stream_frame_message(code: LowcodeApiResponseCode, payload: Any) -> str:
    """业务错误帧优先用 payload.message（若存在），否则用枚举默认文案。"""
    if code != LowcodeApiResponseCode.SUCCESS:
        if isinstance(payload, dict):
            m = payload.get("message")
            if m is not None and str(m).strip():
                return str(m)
        return code.default_message
    return code.default_message


def _workflow_chunk_to_type_payload_code(chunk: Any) -> tuple[str | None, Any, LowcodeApiResponseCode]:
    """Workflow.stream：chunk → (data.type, payload, code)；None 表示本帧丢弃。"""
    from openjiuwen.core.common.constants.constant import END_NODE_STREAM, INTERACTION
    from openjiuwen.core.session.stream import CustomSchema, OutputSchema, TraceSchema
    from openjiuwen.core.session.tracer.handler import TracerHandlerName

    include_trace = _sse_include_trace()
    ok = LowcodeApiResponseCode.SUCCESS

    if isinstance(chunk, TraceSchema):
        # TraceSchema 由 core 生成，payload 已是 JSON 友好结构；这里再 _to_jsonable 一次保证安全
        if chunk.type == TracerHandlerName.TRACER_WORKFLOW.value:
            if not include_trace:
                return None, None, ok
            return ResponseDataType.TRACE.value, _to_jsonable(chunk.payload), ok
        if include_trace:
            return ResponseDataType.TRACE.value, _to_jsonable(chunk.payload), ok
        return None, None, ok

    if isinstance(chunk, OutputSchema):
        output_type = chunk.type
        if output_type == "output":
            return ResponseDataType.NODE_OUTPUT.value, _to_jsonable(chunk.payload), ok
        if output_type == END_NODE_STREAM:
            return ResponseDataType.STREAM.value, _to_jsonable(chunk.payload), ok
        if output_type == INTERACTION:
            # 注意：workflow.stream 的 __interaction__ 对外暴露为 input_required（区别于 agent 的 interaction）
            return ResponseDataType.INPUT_REQUIRED.value, _to_jsonable(chunk.payload), ok
        if output_type == "workflow_final":
            return ResponseDataType.RESULT.value, _to_jsonable(chunk.payload), ok
        return ResponseDataType.STREAM.value, _to_jsonable(chunk.payload), ok

    if isinstance(chunk, CustomSchema):
        return ResponseDataType.STREAM.value, _to_jsonable(chunk.model_dump()), ok
    if isinstance(chunk, dict):
        return ResponseDataType.STREAM.value, _to_jsonable(chunk), ok
    return ResponseDataType.STREAM.value, _to_jsonable(chunk), ok


def _agent_output_payload_dict(chunk: Any) -> dict[str, Any]:
    from openjiuwen.core.session.stream import OutputSchema

    if not isinstance(chunk, OutputSchema):
        return {}
    payload = chunk.payload
    if isinstance(payload, dict):
        return payload
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        d = model_dump()
        return d if isinstance(d, dict) else {}
    return {}


def _agent_chunk_to_type_payload_code(chunk: Any) -> tuple[str | None, Any, LowcodeApiResponseCode]:
    """Agent.stream：chunk → (data.type, payload, code)。"""
    from openjiuwen.core.common.constants.constant import INTERACTION
    from openjiuwen.core.session.stream import CustomSchema, OutputSchema, TraceSchema
    from openjiuwen.core.session.tracer.handler import TracerHandlerName

    include_trace = _sse_include_trace()
    ok = LowcodeApiResponseCode.SUCCESS
    fail = LowcodeApiResponseCode.EXECUTION_FAILED

    if isinstance(chunk, TraceSchema):
        if chunk.type in (TracerHandlerName.TRACE_AGENT.value, TracerHandlerName.TRACER_WORKFLOW.value):
            if not include_trace:
                return None, None, ok
            return ResponseDataType.TRACE.value, _to_jsonable(chunk.payload), ok
        if include_trace:
            return ResponseDataType.TRACE.value, _to_jsonable(chunk.payload), ok
        return None, None, ok

    if isinstance(chunk, OutputSchema):
        output_type = chunk.type
        payload_dict = _agent_output_payload_dict(chunk)

        if output_type == INTERACTION:
            # agent.stream 的 __interaction__ → interaction（payload 透传）
            return ResponseDataType.INTERACTION.value, _to_jsonable(chunk.payload), ok

        if output_type == "llm_reasoning":
            content = payload_dict.get("output") or payload_dict.get("content") or ""
            return ResponseDataType.STREAM.value, {"content": content, "stream_type": "llm_reasoning"}, ok

        if output_type == "llm_output":
            content = payload_dict.get("output") or payload_dict.get("content") or ""
            return ResponseDataType.STREAM.value, {"content": content, "stream_type": "llm_output"}, ok

        if output_type == "answer":
            result_type = str(payload_dict.get("result_type") or "").strip()
            if result_type == "error":
                msg = payload_dict.get("message") or payload_dict.get("output") or ""
                return ResponseDataType.ERROR.value, {"message": str(msg)}, fail
            if result_type == "interrupt":
                return (
                    ResponseDataType.INTERACTION.value,
                    {
                        "workflow_execution_state": _to_jsonable(payload_dict.get("workflow_execution_state")),
                        "component_ids": _to_jsonable(payload_dict.get("component_ids", [])),
                    },
                    ok,
                )
            if not result_type:
                return ResponseDataType.UNKNOWN.value, _to_jsonable(chunk.model_dump()), ok
            if result_type == "answer":
                out = payload_dict.get("output", "")
                return ResponseDataType.RESULT.value, {"output": out if isinstance(out, str) else str(out)}, ok
            return ResponseDataType.FORCE_FINISH.value, _to_jsonable(chunk.model_dump()), ok

        if output_type == "final" and payload_dict.get("error"):
            return ResponseDataType.ERROR.value, {"message": str(payload_dict.get("message", ""))}, fail

        return ResponseDataType.STREAM.value, _to_jsonable(chunk.model_dump()), ok

    if isinstance(chunk, CustomSchema):
        return ResponseDataType.STREAM.value, _to_jsonable(chunk.model_dump()), ok
    if isinstance(chunk, dict):
        return ResponseDataType.STREAM.value, _to_jsonable(chunk), ok
    return ResponseDataType.STREAM.value, _to_jsonable(chunk), ok


async def _workflow_stream_event_source(chunk_stream: AsyncIterator[Any], timeout_seconds: float) -> AsyncIterator[str]:
    """将 workflow streaming iterator 转为 ResponseModel JSON 流。"""
    from openjiuwen.core.common.exception.errors import BaseError

    try:
        async with _optional_async_timeout(timeout_seconds):
            async for chunk in chunk_stream:
                data_type, payload, frame_code = _workflow_chunk_to_type_payload_code(chunk)
                if data_type is None:
                    continue
                yield ResponseModel(
                    code=int(frame_code),
                    message=_stream_frame_message(frame_code, payload),
                    data={"type": data_type, "payload": payload},
                ).model_dump_json()
    except asyncio.TimeoutError:
        logging.getLogger(__name__).error("workflow stream execution timeout after %.3fs", timeout_seconds, exc_info=True)
        c = LowcodeApiResponseCode.EXECUTION_TIMEOUT
        yield _stream_error_event(c, message=c.format_message())
    except BaseError as e:
        logging.getLogger(__name__).exception("workflow stream execution failed: %s", e)
        detail_code = int(getattr(e, "code", LowcodeApiResponseCode.INTERNAL_ERROR))
        msg = str(getattr(e, "message", "") or e)
        yield _stream_error_event(LowcodeApiResponseCode.EXECUTION_FAILED, message=msg, payload={"detail_code": detail_code})
    except asyncio.CancelledError:
        c = LowcodeApiResponseCode.EXECUTION_CANCELLED
        yield _stream_error_event(c)
        raise
    except WorkflowLlmApiKeyMissingError as e:
        logging.getLogger(__name__).exception("workflow stream missing LLM API key: %s", e)
        c = LowcodeApiResponseCode.LLM_API_KEY_MISSING
        yield _stream_error_event(c, message=str(e))
    except Exception as e:
        logging.getLogger(__name__).exception("workflow stream internal error: %s", e)
        c = LowcodeApiResponseCode.INTERNAL_ERROR
        yield _stream_error_event(c, message=str(e))


async def _agent_stream_event_source(chunk_stream: AsyncIterator[Any], timeout_seconds: float) -> AsyncIterator[str]:
    """将 agent streaming iterator 转为 ResponseModel JSON 流。"""
    from openjiuwen.core.common.exception.errors import BaseError

    try:
        async with _optional_async_timeout(timeout_seconds):
            async for chunk in chunk_stream:
                data_type, payload, frame_code = _agent_chunk_to_type_payload_code(chunk)
                if data_type is None:
                    continue
                yield ResponseModel(
                    code=int(frame_code),
                    message=_stream_frame_message(frame_code, payload),
                    data={"type": data_type, "payload": payload},
                ).model_dump_json()
    except asyncio.TimeoutError:
        logging.getLogger(__name__).error("agent stream execution timeout after %.3fs", timeout_seconds, exc_info=True)
        c = LowcodeApiResponseCode.EXECUTION_TIMEOUT
        yield _stream_error_event(c, message=c.format_message())
    except BaseError as e:
        logging.getLogger(__name__).exception("agent stream execution failed: %s", e)
        detail_code = int(getattr(e, "code", LowcodeApiResponseCode.INTERNAL_ERROR))
        msg = str(getattr(e, "message", "") or e)
        yield _stream_error_event(LowcodeApiResponseCode.EXECUTION_FAILED, message=msg, payload={"detail_code": detail_code})
    except asyncio.CancelledError:
        c = LowcodeApiResponseCode.EXECUTION_CANCELLED
        yield _stream_error_event(c)
        raise
    except WorkflowLlmApiKeyMissingError as e:
        logging.getLogger(__name__).exception("agent stream missing LLM API key: %s", e)
        c = LowcodeApiResponseCode.LLM_API_KEY_MISSING
        yield _stream_error_event(c, message=str(e))
    except Exception as e:
        logging.getLogger(__name__).exception("agent stream internal error: %s", e)
        c = LowcodeApiResponseCode.INTERNAL_ERROR
        yield _stream_error_event(c, message=str(e))


async def validation_error_stream_events(exc: RequestValidationError) -> AsyncIterator[str]:
    """SSE 路由的请求体校验失败也要走 ResponseModel 事件体。"""
    yield _stream_error_event(
        LowcodeApiResponseCode.INVALID_REQUEST,
        message=LowcodeApiResponseCode.INVALID_REQUEST.default_message,
        payload={"errors": exc.errors()},
    )


async def execute_stream_event_source(body: Any) -> AsyncIterator[str]:
    """FastAPI 路由层入口：POST /execute_stream."""
    try:
        await ensure_runtime_ready()
    except Exception as e:
        yield _stream_error_event(LowcodeApiResponseCode.SERVICE_UNAVAILABLE, message=str(e))
        return

    try:
        ir_local_json_path = await ensure_ir_local_path(getattr(body, "ir_path"))
    except HTTPException as he:
        lc, msg = lowcode_code_from_http_exception(he)
        yield _stream_error_event(lc, message=msg)
        return

    try:
        ir_root = json.loads(ir_local_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        c = LowcodeApiResponseCode.IR_INVALID
        yield _stream_error_event(c, message=f"{c.default_message}: {exc}")
        return

    try:
        executable_kind = detect_executable_kind(ir_root)
    except HTTPException as he:
        lc, msg = lowcode_code_from_http_exception(he)
        if he.status_code == 400 and "neither workflow" in (msg or "").lower():
            lc = LowcodeApiResponseCode.IR_INVALID
        yield _stream_error_event(lc, message=msg)
        return

    try:
        inputs_obj = json.loads(getattr(body, "inputs"))
    except json.JSONDecodeError as exc:
        c = LowcodeApiResponseCode.INVALID_INPUTS
        yield _stream_error_event(c, message=f"{c.default_message}: {exc}")
        return
    if not isinstance(inputs_obj, dict):
        c = LowcodeApiResponseCode.INVALID_INPUTS
        yield _stream_error_event(c, message="inputs must decode to a JSON object")
        return

    if executable_kind == "workflow" and set(inputs_obj.keys()) == {"__interactive_reply"}:
        # 续跑输入：支持两种形态
        # 1) {"__interactive_reply": "<text>"} -> InteractiveInput(raw_inputs="<text>")（兼容老约定）
        # 2) {"__interactive_reply": {"id": "<node_id>", "value": <any>}} -> InteractiveInput().update(id, value)
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
    if executable_kind == "agent" and "user_id" not in inputs_obj:
        inputs_obj = dict(inputs_obj)
        inputs_obj["user_id"] = getattr(body, "user_id")

    timeout_seconds = getattr(body, "timeout_ms") / 1000.0
    session_id = getattr(body, "conversation_id")

    if executable_kind == "workflow":
        try:
            from workflow_ir_builder import build_core_workflow_from_ir_file

            workflow = await build_core_workflow_from_ir_file(
                str(ir_local_json_path.resolve()), space_id=space_id, current_user=current_user
            )
        except WorkflowLlmApiKeyMissingError as e:
            yield _stream_error_event(LowcodeApiResponseCode.LLM_API_KEY_MISSING, message=str(e))
            return
        except Exception as e:
            yield _stream_error_event(LowcodeApiResponseCode.IR_LOAD_FAILED, message=str(e))
            return

        chunk_iterator = Runner.run_workflow_streaming(workflow=workflow, inputs=inputs_obj, session=session_id)
        async for line in _workflow_stream_event_source(chunk_iterator, timeout_seconds):
            yield line
        return

    try:
        react_agent = await build_react_agent(ir_local_json_path.resolve(), current_user)
    except Exception as e:
        yield _stream_error_event(LowcodeApiResponseCode.IR_LOAD_FAILED, message=str(e))
        return

    chunk_iterator = Runner.run_agent_streaming(agent=react_agent, inputs=inputs_obj, session=session_id)
    async for line in _agent_stream_event_source(chunk_iterator, timeout_seconds):
        yield line

