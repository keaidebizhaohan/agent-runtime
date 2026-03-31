"""从 Studio 导出 IR 构建 ReActAgent（stream / invoke 共用）。

包含：AgentCompiler 编译、运行时配置归一化、按导出 JSON 开关挂载 MemoryRail 与 system 占位符。
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from openjiuwen.core.common.schema.param import Param
from openjiuwen.core.memory.config.config import AgentMemoryConfig
from openjiuwen.core.single_agent.agents.react_agent import ReActAgent
from openjiuwen_studio.lowcode.compiler import AgentCompiler

from runtime_support.runtime_env import get_env, resolve_memory_scope_id


def _agent_memory_config_from_export_memory(memory: Any) -> AgentMemoryConfig:
    """从导出 JSON 的 agent.memory 构建 AgentMemoryConfig；缺省为 false 或空列表。"""
    if not isinstance(memory, dict):
        memory = {}

    raw_vars = memory.get("variable_config")
    if not isinstance(raw_vars, list):
        raw_vars = []

    mem_variables: list[Any] = []
    for var in raw_vars:
        if not isinstance(var, dict):
            continue
        if not var.get("enabled", False):
            continue
        name = str(var.get("name") or "").strip()
        if not name:
            continue
        desc = str(var.get("description") or "")
        mem_variables.append(Param.string(name, description=desc, required=False))

    return AgentMemoryConfig(
        mem_variables=mem_variables,
        # 注意：AgentMemoryConfig 在 core 里默认都是 True；这里必须以导出 IR 为准，
        # 且缺省按 False 处理，避免“开关没开也加载/写入记忆”。
        enable_long_term_mem=bool(memory.get("longterm_memory_config", False)),
        enable_user_profile=bool(memory.get("user_profile_config", False)),
        enable_semantic_memory=bool(memory.get("semantic_memory_config", False)),
        enable_episodic_memory=bool(memory.get("episodic_memory_config", False)),
        enable_summary_memory=bool(memory.get("summary_memory_config", False)),
    )


def _memory_switch_enabled() -> bool:
    """全局记忆开关：默认开启；设置 IR_ENABLE_AGENT_MEMORY=false 可关闭所有记忆加载/写入。"""
    v = (os.environ.get("IR_ENABLE_AGENT_MEMORY") or "true").strip().lower()
    return v not in {"0", "false", "no", "off"}


def _is_agent_memory_cfg_enabled(cfg: AgentMemoryConfig) -> bool:
    """只要任一记忆能力开启，就认为需要挂载 MemoryRail。"""
    if not isinstance(cfg, AgentMemoryConfig):
        return False
    return bool(
        cfg.mem_variables
        or cfg.enable_long_term_mem
        or cfg.enable_user_profile
        or cfg.enable_semantic_memory
        or cfg.enable_episodic_memory
        or cfg.enable_summary_memory
    )


def _ensure_memory_placeholders_in_system_prompt(agent: Any, agent_memory_cfg: AgentMemoryConfig) -> None:
    """
    仅当导出 JSON 的开关开启时，才注入对应占位符。
    MemoryRail 使用 PromptTemplate（占位符前后缀为 {{ 与 }}）渲染 system message 中的记忆变量。
    """
    enable_vars = bool(getattr(agent_memory_cfg, "mem_variables", None))
    enable_long_term = bool(getattr(agent_memory_cfg, "enable_long_term_mem", False))
    if not (enable_vars or enable_long_term):
        return

    cfg = getattr(agent, "_config", None)
    prompt_template = getattr(cfg, "prompt_template", None)
    if not isinstance(prompt_template, list) or not prompt_template:
        return

    def _has_placeholder(key: str) -> bool:
        token = "{{" + key + "}}"
        for m in prompt_template:
            if not isinstance(m, dict):
                continue
            if m.get("role") != "system":
                continue
            c = m.get("content")
            if isinstance(c, str) and token in c:
                return True
        return False

    ok_long_term = (not enable_long_term) or _has_placeholder("sys_long_term_memory")
    ok_vars = (not enable_vars) or _has_placeholder("sys_memory_variables")
    if ok_long_term and ok_vars:
        return

    lines = ["【系统记忆注入（由服务端自动追加）】"]
    lines.append("你可能会获得以下记忆信息（均为 JSON 字符串），用于辅助回答：")
    if enable_long_term:
        lines.append("- 长期记忆（列表，可能为空）：{{sys_long_term_memory}}")
    if enable_vars:
        lines.append("- 用户记忆变量（字典，可能为空）：{{sys_memory_variables}}")
    lines.append("规则：若相关字段为空，不要编造用户信息。")

    prompt_template.append({"role": "system", "content": "\n".join(lines)})


async def _register_memory_rail_from_export(agent: Any, export_agent: dict[str, Any]) -> None:
    """根据导出 IR 的 memory 配置挂载 MemoryRail（如未开启则跳过）。"""
    if not _memory_switch_enabled():
        return

    memory = export_agent.get("memory") if isinstance(export_agent, dict) else None
    if not isinstance(memory, dict) or not memory:
        return

    agent_memory_cfg = _agent_memory_config_from_export_memory(memory)
    if not _is_agent_memory_cfg_enabled(agent_memory_cfg):
        return

    scope_id = resolve_memory_scope_id(
        raw_memory_scope_id=str(getattr(agent, "_config", None).mem_scope_id or ""),
        default_memory_scope_id=get_env("DEFAULT_MEMORY_SCOPE_ID", ""),
    )

    from openjiuwen.core.application.llm_agent.rails.memory_rail import MemoryRail

    await agent.register_rail(MemoryRail(scope_id, agent_memory_cfg))
    _ensure_memory_placeholders_in_system_prompt(agent, agent_memory_cfg)


async def build_react_agent(ir_path: Path, current_user: dict[str, Any], *, model_overrides: dict[str, Any] | None = None) -> ReActAgent:
    """
    统一的 Agent 构建入口，供 stream/invoke 共用。
    注意：记忆 rail 是否挂载完全由导出 JSON 的开关 + IR_ENABLE_AGENT_MEMORY 决定。
    """
    export_data = json.loads(ir_path.read_text(encoding="utf-8"))
    export_agent = export_data.get("agent") if isinstance(export_data.get("agent"), dict) else {}
    compiler = AgentCompiler()

    # model_overrides 由调用侧准备（环境变量、请求覆盖等）
    if model_overrides is None:
        model_overrides = {}

    resolved_agent: dict[str, Any] | None = None
    if hasattr(compiler, "compile_for_runtime"):
        compile_result = await compiler.compile_for_runtime(
            config=export_data,
            model_overrides=model_overrides or None,
            current_user=current_user,
        )
    else:
        compiled = await compiler.compile_with_overrides_config(
            config=export_data, model_overrides=model_overrides, current_user=current_user
        )
        agent_config_dict = compiled["agent_config"]
        resolved_agent = agent_config_dict
        from openjiuwen_studio.lowcode.config_adapter import ConfigAdapter

        adapt_rt = getattr(ConfigAdapter, "adapt_to_runtime_config", None)
        runtime_config = adapt_rt(agent_config_dict) if adapt_rt is not None else ConfigAdapter.adapt(agent_config_dict)
        from openjiuwen.core.single_agent.schema.agent_card import AgentCard

        compile_result = {
            "agent_card": AgentCard(
                id=agent_config_dict.get("agent_id", ""),
                name=agent_config_dict.get("agent_name", "Agent"),
                description=agent_config_dict.get("description", ""),
                version=agent_config_dict.get("agent_version", "draft"),
            ),
            "runtime_config": runtime_config,
        }

    # 运行时配置归一化逻辑仍复用 invoke_api（避免重复与 drift）
    from invoke_api import _normalize_runtime_config_for_react_agent  # noqa: E402

    agent = ReActAgent(card=compile_result["agent_card"])
    agent.configure(
        _normalize_runtime_config_for_react_agent(
            compile_result["runtime_config"],
            resolved_agent_dict=resolved_agent,
        )
    )
    await _register_memory_rail_from_export(agent, export_agent)
    return agent
