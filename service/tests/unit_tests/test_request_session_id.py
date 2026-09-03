# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from openjiuwen_runtime.service.models.request import QueryRequest, ResetConversationRequest


def test_query_session_id_uses_space_user_and_conversation() -> None:
    request = QueryRequest(
        conversation_id="conversation-001",
        user_id="user-001",
        space_id="space-001",
    )

    assert request.session_id == "space-001:user-001:conversation-001"
    assert request.conversation_id == "conversation-001"


def test_query_session_id_uses_defaults_when_tenant_fields_are_omitted() -> None:
    request = QueryRequest(conversation_id="conversation-001")

    assert request.session_id == "default:anonymous:conversation-001"


def test_reset_session_id_matches_query_session_id() -> None:
    query = QueryRequest(
        conversation_id="conversation-001",
        user_id="user-001",
        space_id="space-001",
    )
    reset = ResetConversationRequest(
        conversation_id="conversation-001",
        user_id="user-001",
        space_id="space-001",
    )

    assert reset.session_id == query.session_id


def test_reset_session_id_uses_defaults_when_tenant_fields_are_omitted() -> None:
    request = ResetConversationRequest(conversation_id="conversation-001")

    assert request.session_id == "default:anonymous:conversation-001"
