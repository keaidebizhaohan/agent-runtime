# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

from openjiuwen_runtime.service.models.request import QueryRequest, ResetConversationRequest


def test_query_session_id_uses_agent_space_user_and_conversation(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ID", "agent-001")
    request = QueryRequest(
        conversation_id="conversation-001",
        user_id="user-001",
        space_id="space-001",
    )

    assert request.session_id == "agent-001:space-001:user-001:conversation-001"
    assert request.conversation_id == "conversation-001"


def test_query_session_id_uses_defaults_when_fields_are_omitted(monkeypatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_ID", raising=False)
    request = QueryRequest(conversation_id="conversation-001")

    assert request.session_id == "default-agent:default:anonymous:conversation-001"


def test_same_conversation_is_isolated_between_agents(monkeypatch) -> None:
    request = QueryRequest(
        conversation_id="conversation-001",
        user_id="user-001",
        space_id="space-001",
    )

    monkeypatch.setenv("DEPLOYMENT_ID", "agent-a")
    agent_a_session_id = request.session_id
    monkeypatch.setenv("DEPLOYMENT_ID", "agent-b")
    agent_b_session_id = request.session_id

    assert agent_a_session_id == "agent-a:space-001:user-001:conversation-001"
    assert agent_b_session_id == "agent-b:space-001:user-001:conversation-001"
    assert agent_a_session_id != agent_b_session_id


def test_reset_session_id_matches_query_session_id(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ID", "agent-001")
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


def test_reset_session_id_uses_defaults_when_fields_are_omitted(monkeypatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_ID", raising=False)
    request = ResetConversationRequest(conversation_id="conversation-001")

    assert request.session_id == "default-agent:default:anonymous:conversation-001"
