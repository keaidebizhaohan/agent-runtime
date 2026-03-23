#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
AG-UI converter for openJiuwen agent streaming chunks.

将底层 streaming chunk（TraceSchema / OutputSchema）转换为 AG-UI SSE 事件对象
（每条对应一行 ``data: <json>``）。

由 agent-runtime 低码部署与 agent-studio AgentRunner 共用逻辑；
ReActAgent 的 ``llm_output`` 使用 ``payload.content``，``answer`` 使用 ``payload.output``。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgUiStreamState:
    """AG-UI SSE 事件组装状态（每个 run / conversation 一份）"""

    thread_id: str
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex}")
    started: bool = False
    text_message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex}")
    text_started: bool = False
    text_acc: str = ""
    finished: bool = False


def _get_or_create_agui_state(trace_context: Any, thread_id: str) -> AgUiStreamState:
    if not thread_id:
        thread_id = f"thread_{uuid.uuid4().hex}"

    state = getattr(trace_context, "_agui_state", None)
    if isinstance(state, AgUiStreamState) and state.thread_id == thread_id:
        return state
    state = AgUiStreamState(thread_id=thread_id)
    if getattr(trace_context, "trace_id", None):
        state.run_id = str(getattr(trace_context, "trace_id"))
    setattr(trace_context, "_agui_state", state)
    return state


def convert_chunk_to_agui_events(chunk: Any, trace_context: Any, conversation_id: str) -> List[Dict[str, Any]]:
    """
    将底层 streaming chunk 转为 AG-UI SSE 事件（data 行 JSON 对象）。

    返回值为事件对象列表（上层包装为 SSE 的 ``data: <json>``）。
    """
    from openjiuwen.core.session.stream.base import TraceSchema, OutputSchema

    state = _get_or_create_agui_state(trace_context, conversation_id)
    events: List[Dict[str, Any]] = []

    if not state.started:
        raw_input = getattr(trace_context, "agent_input", None) or {}
        if not isinstance(raw_input, dict):
            raw_input = {}
        events.append(
            {
                "type": "RUN_STARTED",
                "threadId": state.thread_id,
                "runId": state.run_id,
                "input": {
                    "threadId": state.thread_id,
                    "runId": state.run_id,
                    "messages": raw_input.get("messages", []),
                    "tools": raw_input.get("tools", []),
                    "context": raw_input.get("context", []),
                },
            }
        )
        state.started = True

    def _ensure_text_started() -> None:
        if not state.text_started:
            events.append(
                {"type": "TEXT_MESSAGE_START", "messageId": state.text_message_id, "role": "assistant"}
            )
            state.text_started = True

    def _emit_text_delta(delta: str) -> None:
        if not delta:
            return
        _ensure_text_started()
        state.text_acc += delta
        events.append(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": state.text_message_id, "delta": delta}
        )

    def _finish_if_possible(final_content: Optional[str] = None) -> None:
        if state.finished:
            return
        if final_content is not None and isinstance(final_content, str) and final_content.strip():
            if not state.text_acc.strip():
                state.text_acc = final_content
        if not state.text_acc.strip():
            return
        _ensure_text_started()
        events.append(
            {
                "type": "TEXT_MESSAGE_END",
                "messageId": state.text_message_id,
                "content": state.text_acc,
            }
        )
        events.append(
            {"type": "RUN_FINISHED", "threadId": state.thread_id, "runId": state.run_id, "result": None}
        )
        state.finished = True

    if isinstance(chunk, OutputSchema):
        payload = getattr(chunk, "payload", None) or {}
        if isinstance(payload, dict):
            if chunk.type in {"llm_output", "workflow_final", "end node stream"}:
                delta = (
                    payload.get("content")
                    or payload.get("output")
                    or payload.get("response")
                    or ""
                )
                if isinstance(delta, dict):
                    delta = json.dumps(delta, ensure_ascii=False, default=str)
                _emit_text_delta(str(delta))
            elif chunk.type == "llm_reasoning":
                rc = payload.get("content") or ""
                if isinstance(rc, str) and rc:
                    _emit_text_delta(rc)
            elif chunk.type == "answer":
                _finish_if_possible(payload.get("output"))
            elif chunk.type == "__interaction__":
                events.append(
                    {
                        "type": "CUSTOM",
                        "name": "REQUIRES_ACTION",
                        "value": {"threadId": state.thread_id, "runId": state.run_id},
                    }
                )

    if isinstance(chunk, TraceSchema) and getattr(chunk, "type", None) == "tracer_agent":
        payload = getattr(chunk, "payload", None) or {}
        final_content: Optional[str] = None
        if isinstance(payload, dict):
            outputs = payload.get("outputs")
            if isinstance(outputs, dict):
                outs = outputs.get("outputs")
                if isinstance(outs, list) and outs:
                    first = outs[0]
                    if isinstance(first, dict) and isinstance(first.get("content"), str):
                        final_content = first.get("content")
        if final_content:
            _finish_if_possible(final_content)
        else:
            end_time = payload.get("end_time") if isinstance(payload, dict) else None
            if end_time:
                _finish_if_possible(None)

    return events


def finalize_agui_stream(trace_context: Any, conversation_id: str) -> List[Dict[str, Any]]:
    """
    流式迭代结束后调用：若尚未 ``RUN_FINISHED``（例如上游未发 ``answer``），补发结束事件。
    """
    state = getattr(trace_context, "_agui_state", None)
    if not isinstance(state, AgUiStreamState) or state.finished:
        return []
    events: List[Dict[str, Any]] = []
    if state.text_acc.strip():
        if not state.text_started:
            events.append(
                {"type": "TEXT_MESSAGE_START", "messageId": state.text_message_id, "role": "assistant"}
            )
            state.text_started = True
        events.append(
            {
                "type": "TEXT_MESSAGE_END",
                "messageId": state.text_message_id,
                "content": state.text_acc,
            }
        )
    events.append(
        {"type": "RUN_FINISHED", "threadId": state.thread_id, "runId": state.run_id, "result": None}
    )
    state.finished = True
    return events


def agui_assistant_text_as_answer_events(
    trace_context: Any,
    conversation_id: str,
    assistant_text: str,
) -> List[Dict[str, Any]]:
    """
    将一段固定 assistant 文案转为 AG-UI 事件（RUN_STARTED + 文本 + RUN_FINISHED）。
    用于校验失败、异常提示等无底层 chunk 的场景。
    """
    from openjiuwen.core.session.stream.base import OutputSchema

    chunk = OutputSchema(
        type="answer",
        index=0,
        payload={"output": assistant_text, "result_type": "answer"},
    )
    out = convert_chunk_to_agui_events(chunk, trace_context, conversation_id)
    out.extend(finalize_agui_stream(trace_context, conversation_id))
    return out
