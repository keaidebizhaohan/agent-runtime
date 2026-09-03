# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from openjiuwen_runtime.server.middleware.tenant import (
    deployment_belongs_to_tenant,
    normalize_tenant_context,
    resolve_proxy_tenant,
)


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers or [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "scheme": "http",
    })


def test_normalize_tenant_context_uses_defaults() -> None:
    assert normalize_tenant_context(None, None) == ("anonymous", "default")
    assert normalize_tenant_context("", "  ") == ("anonymous", "default")


def test_deployment_tenant_must_match_user_and_space() -> None:
    deployment = SimpleNamespace(user_id="user-a", space_id="space-a")

    assert deployment_belongs_to_tenant(deployment, "user-a", "space-a")
    assert not deployment_belongs_to_tenant(deployment, "user-b", "space-a")
    assert not deployment_belongs_to_tenant(deployment, "user-a", "space-b")


def test_legacy_empty_deployment_belongs_to_default_tenant() -> None:
    deployment = SimpleNamespace(user_id=None, space_id=None)

    assert deployment_belongs_to_tenant(deployment, "anonymous", "default")


def test_proxy_tenant_uses_body_and_injects_normalized_values() -> None:
    user_id, space_id, body = resolve_proxy_tenant(
        _request(),
        "query",
        {"conversation_id": "conversation-1", "user_id": "user-a", "space_id": "space-a"},
    )

    assert (user_id, space_id) == ("user-a", "space-a")
    assert body["user_id"] == "user-a"
    assert body["space_id"] == "space-a"


def test_proxy_tenant_uses_defaults_and_injects_them() -> None:
    user_id, space_id, body = resolve_proxy_tenant(
        _request(),
        "query",
        {"conversation_id": "conversation-1"},
    )

    assert (user_id, space_id) == ("anonymous", "default")
    assert body["user_id"] == "anonymous"
    assert body["space_id"] == "default"


def test_proxy_rejects_conflicting_header_and_body_tenant() -> None:
    request = _request([(b"x-user-id", b"user-a"), (b"x-space-id", b"space-a")])

    with pytest.raises(HTTPException) as exc_info:
        resolve_proxy_tenant(
            request,
            "query",
            {"user_id": "user-b", "space_id": "space-a"},
        )

    assert exc_info.value.status_code == 400
