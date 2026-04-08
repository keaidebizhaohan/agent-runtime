from __future__ import annotations

from typing import Callable, Iterable


def _normalize_workflow_id(workflow_id: str, workflow_version: str) -> str:
    """Keep workflow ids in raw form so version is appended exactly once later."""
    normalized_id = str(workflow_id or "").strip()
    normalized_version = str(workflow_version or "").strip()
    if not normalized_id or not normalized_version:
        return normalized_id

    suffix = f"_{normalized_version}"
    while normalized_id.endswith(suffix):
        normalized_id = normalized_id[: -len(suffix)]
    return normalized_id


def _attach_workflow_metadata(
    provider: Callable,
    *,
    workflow_id: str,
    workflow_version: str,
    workflow_name: str,
    workflow_description: str,
    input_params,
):
    """Attach the metadata expected by BaseAgent.add_workflows."""
    provider.id = _normalize_workflow_id(workflow_id, workflow_version)
    provider.version = workflow_version
    provider.name = workflow_name
    provider.description = workflow_description
    provider.input_params = input_params
    return provider


def normalize_workflow_providers_for_agent(
    workflow_providers: Iterable[tuple[object, Callable]],
) -> list[Callable]:
    """Convert runtime compiler output to the provider shape expected by BaseAgent.add_workflows.

    Runtime compiler already returns async workflow providers. Passing them through WorkflowFactory
    adds an extra callable layer, and ResourceMgr only awaits plain async functions. Returning the
    provider directly keeps registration concurrency-safe and retrievable.
    """
    normalized = []
    for workflow_card, workflow_provider in workflow_providers:
        normalized.append(
            _attach_workflow_metadata(
                workflow_provider,
                workflow_id=workflow_card.id,
                workflow_version=workflow_card.version,
                workflow_name=workflow_card.name,
                workflow_description=workflow_card.description or "",
                input_params=workflow_card.input_params,
            )
        )
    return normalized
