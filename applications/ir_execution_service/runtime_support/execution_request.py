#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from runtime_support.http_response_contract import LowcodeApiResponseCode
from runtime_support.ir_fetch import (
    detect_executable_kind,
    ensure_ir_local_path,
    lowcode_code_from_http_exception,
)


class ExecutionPrepareError(Exception):
    def __init__(self, code: LowcodeApiResponseCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class PreparedExecutionRequest:
    ir_local_json_path: Path
    executable_kind: str
    inputs_obj: Any
    space_id: str
    current_user: dict[str, Any]
    session_id: str
    timeout_seconds: float


def _load_ir_root(ir_local_json_path: Path) -> dict[str, Any]:
    try:
        ir_root = json.loads(ir_local_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        c = LowcodeApiResponseCode.IR_INVALID
        raise ExecutionPrepareError(c, f"{c.default_message}: {exc}") from exc
    if not isinstance(ir_root, dict):
        c = LowcodeApiResponseCode.IR_INVALID
        raise ExecutionPrepareError(c, "IR root must be a JSON object")
    return ir_root


def _detect_executable_kind(ir_root: dict[str, Any]) -> str:
    try:
        return detect_executable_kind(ir_root)
    except HTTPException as exc:
        code, message = lowcode_code_from_http_exception(exc)
        if exc.status_code == 400 and "neither workflow" in (message or "").lower():
            code = LowcodeApiResponseCode.IR_INVALID
        raise ExecutionPrepareError(code, message) from exc


def _decode_inputs(inputs_raw: str) -> dict[str, Any]:
    try:
        inputs_obj = json.loads(inputs_raw)
    except (TypeError, json.JSONDecodeError) as exc:
        c = LowcodeApiResponseCode.INVALID_INPUTS
        raise ExecutionPrepareError(c, f"{c.default_message}: {exc}") from exc
    if not isinstance(inputs_obj, dict):
        c = LowcodeApiResponseCode.INVALID_INPUTS
        raise ExecutionPrepareError(c, "inputs must decode to a JSON object")
    return inputs_obj


def _normalize_workflow_resume_inputs(inputs_obj: dict[str, Any]) -> Any:
    if set(inputs_obj.keys()) != {"__interactive_reply"}:
        return inputs_obj

    from openjiuwen.core.session import InteractiveInput

    reply = inputs_obj["__interactive_reply"]
    if isinstance(reply, dict) and (reply.get("id") is not None):
        interactive_input = InteractiveInput()
        interactive_input.update(str(reply.get("id")), reply.get("value"))
        return interactive_input
    return InteractiveInput(reply)


def _prepare_inputs_for_kind(inputs_obj: dict[str, Any], executable_kind: str, user_id: str) -> Any:
    if executable_kind == "workflow":
        return _normalize_workflow_resume_inputs(inputs_obj)
    if "user_id" in inputs_obj:
        return inputs_obj
    enriched = dict(inputs_obj)
    enriched["user_id"] = user_id
    return enriched


async def prepare_execution_request(body: Any) -> PreparedExecutionRequest:
    try:
        ir_local_json_path = await ensure_ir_local_path(getattr(body, "ir_path"))
    except HTTPException as exc:
        code, message = lowcode_code_from_http_exception(exc)
        raise ExecutionPrepareError(code, message) from exc

    ir_root = _load_ir_root(ir_local_json_path)
    executable_kind = _detect_executable_kind(ir_root)
    user_id = str(getattr(body, "user_id"))
    inputs_obj = _prepare_inputs_for_kind(_decode_inputs(getattr(body, "inputs")), executable_kind, user_id)
    space_id = os.environ.get("WORKFLOW_SPACE_ID", "default")

    return PreparedExecutionRequest(
        ir_local_json_path=ir_local_json_path,
        executable_kind=executable_kind,
        inputs_obj=inputs_obj,
        space_id=space_id,
        current_user={"user_id": user_id, "space_id": space_id},
        session_id=getattr(body, "conversation_id"),
        timeout_seconds=getattr(body, "timeout_ms") / 1000.0,
    )
