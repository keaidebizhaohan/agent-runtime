# openjiuwen-runtime-sdk 设计文档 v2.0

**版本**: v2.0
**更新时间**: 2025-01-08
**状态**: 设计草案

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 核心架构](#2-核心架构)
- [3. 详细设计](#3-详细设计)
- [4. 使用示例](#4-使用示例)

---

## 1. 项目概述

### 1.1 定位

**openjiuwen-runtime-sdk** 是 agent-studio Agent 和 Plugin 的**生产级部署运行时**，提供：

- **Agent 部署能力**: 将开发好的 Agent 部署为生产服务
- **Plugin 部署能力**: 将一组工具部署为 RESTful 服务
- **执行能力**: 运行 agent-studio 的 ReAct Agent 和 Workflow Agent
- **会话管理**: 支持多用户、多会话的并发执行
- **扩展能力**: 沙箱工具、RESTful 工具服务集成

---

## 2. 核心架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    openjiuwen-runtime-sdk                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              BaseApp (基类)                           │    │
│  │  - FastAPI 应用管理                                   │    │
│  │  - 生命周期管理 (@init, @shutdown)                   │    │
│  │  - 健康检查 (/health)                                │    │
│  │  - 运行方法 (run)                                     │    │
│  └─────────────────┬───────────────────────────────────┘    │
│                    │                                         │
│      ┌─────────────┴─────────────┐                         │
│      ↓                           ↓                          │
│  ┌──────────────────┐    ┌──────────────────┐             │
│  │   AgentApp       │    │   PluginApp      │             │
│  │  - Agent 实例    │    │  - 工具注册表    │             │
│  │  - @query        │    │  - @tool         │             │
│  │  - /query 路由   │    │  - /tools/* 路由  │             │
│  └──────────────────┘    └──────────────────┘             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              AppGroup (应用容器)                      │    │
│  │  - 多应用共享单端口                                   │    │
│  │  - 路径前缀区分 (/customer, /assistant)             │    │
│  │  - 聚合生命周期管理                                   │    │
│  │  - 聚合健康检查                                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                          ↓                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Services Layer (可选)                   │    │
│  │  ┌──────────┬──────────┬──────────────────────────┐  │    │
│  │  │  Sandbox │  Tools   │    Observability         │  │    │
│  │  │ Service  │ Service  │       Service            │  │    │
│  │  └──────────┴──────────┴──────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
agent-runtime/
├── src/
│   ├── sdk/                         # openjiuwen-runtime-sdk 组件
│   │   ├── pyproject.toml
│   │   └── src/
│   │       ├── core/                # AgentApp, PluginApp, BaseApp, AppGroup
│   │       │   ├── __init__.py
│   │       │   ├── base_app.py           # 核心: BaseApp 基类
│   │       │   ├── agent_app.py          # AgentApp 类
│   │       │   ├── plugin_app.py         # PluginApp 类
│   │       │   ├── app_group.py          # AppGroup 多应用容器
│   │       │   ├── restful.py            # @restful.tool() 装饰器
│   │       │   ├── loader.py             # Agent 加载器
│   │       │   └── stream_handler.py     # 流式输出处理
│   │       ├── services/ (可选)
│   │       │   ├── __init__.py
│   │       │   ├── sandbox/              # 沙箱服务 (复用 agentscope-runtime)
│   │       │   │   ├── __init__.py
│   │       │   │   └── sandbox_service.py
│   │       │   ├── tools/                # RESTful 工具服务
│   │       │   │   ├── __init__.py
│   │       │   │   ├── http_client.py    # HTTP 工具客户端
│   │       │   │   └── tool_registry.py  # 工具注册表
│   │       │   └── observability/        # 观测性服务
│   │       │       ├── __init__.py
│   │       │       └── tracing.py
│   │       └── models/                   # 数据模型
│   │           ├── __init__.py
│   │           ├── agent.py
│   │           ├── message.py
│   │           ├── request.py
│   │           └── tool.py               # 工具相关模型
│   │
│   └── manager/                     # runtime-manager 组件
│       ├── cli/                     # CLI 子组件
│       │   ├── pyproject.toml
│       │   └── src/
│       │       ├── __init__.py
│       │       └── main.py             # CLI 入口
│       ├── server/                  # Server 子组件
│       │   ├── pyproject.toml
│       │   └── src/
│       │       ├── __init__.py
│       │       ├── main.py             # FastAPI 应用
│       │       ├── config.py           # 配置管理
│       │       └── models/
│       │           ├── __init__.py
│       │           ├── request.py       # 请求模型
│       │           └── response.py      # 响应模型
│       └── sdk/                     # Manager SDK 子组件
│           ├── pyproject.toml
│           └── src/
│               ├── __init__.py
│               ├── manager.py          # DeploymentManager 核心类
│               ├── storage.py          # OSS/本地存储抽象
│               ├── database.py         # 数据库抽象
│               ├── mysql_models.py     # MySQL ORM 模型
│               ├── config.py           # 配置项定义
│               ├── models/
│               │   ├── __init__.py
│               │   ├── deployment.py    # 部署记录模型
│               │   └── enums.py        # 枚举定义
│               ├── deployers/          # 部署器实现 (subprocess/进程管理)
│               │   ├── __init__.py
│               │   ├── base.py               # Deployer 基类
│               │   ├── local_subprocess.py   # 本地进程部署器
│               │   ├── kubernetes.py         # K8s 部署器 (待实现)
│               │   └── docker.py             # Docker 部署器 (待实现)
│               └── utils/
│                   ├── __init__.py
│                   └── id_generator.py   # ID 生成器
│
└── README.md
```

**目录说明:**
- `src/sdk/` - openjiuwen-runtime-sdk，提供 AgentApp/PluginApp 基类
- `src/manager/` - runtime-manager，提供部署管理服务和部署器实现
  - `cli/` - 命令行工具组件
  - `server/` - RESTful API 服务组件
  - `sdk/` - Manager SDK (被 CLI 和 Server 共用)

**包结构说明:**
- 每个组件都有自己的 `src/` 目录，Python 模块直接位于各自的 `src/` 下
- 例如：`agent-runtime/src/sdk/src/core/`
- 部署器实现在 `manager/sdk/src/deployers/` 中，使用 subprocess 启动 Python 进程

---

## 3. 详细设计

### 3.1 BaseApp 基类设计

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/base_app.py

from typing import Callable, Optional
from fastapi import FastAPI


class BaseApp:
    """
    openjiuwen 应用基类

    提供 AgentApp 和 PluginApp 的公共功能:
    - FastAPI 应用管理
    - 生命周期管理 (@init, @shutdown)
    - 健康检查 (/health)
    - 运行方法 (run)
    """

    def __init__(
        self,
        app_name: str,
        app_description: str = "",
        version: str = "1.0.0",
    ):
        self.app_name = app_name
        self.app_description = app_description
        self.version = version

        # FastAPI 应用
        self.app = FastAPI(
            title=self.app_name,
            description=self.app_description,
            version=self.version,
        )

        # 生命周期钩子
        self._init_hook: Optional[Callable] = None
        self._shutdown_hook: Optional[Callable] = None

        # 注册基础路由
        self._register_base_routes()

    def init(self, func: Callable) -> Callable:
        """初始化钩子装饰器"""
        self._init_hook = func
        return func

    def shutdown(self, func: Callable) -> Callable:
        """清理钩子装饰器"""
        self._shutdown_hook = func
        return func

    def _register_base_routes(self):
        """注册基础路由"""
        @self.app.on_event("startup")
        async def startup():
            # 执行用户初始化钩子
            if self._init_hook:
                await self._init_hook()

        @self.app.on_event("shutdown")
        async def shutdown():
            # 执行用户清理钩子
            if self._shutdown_hook:
                await self._shutdown_hook()

        @self.app.get("/health")
        async def health():
            """健康检查"""
            return {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
            }

    def run(self, host: str = "0.0.0.0", port: int = 8090, **kwargs):
        """运行应用"""
        import uvicorn
        uvicorn.run(self.app, host=host, port=port, **kwargs)
```

### 3.2 AgentApp 核心设计

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/agent_app.py

from typing import Callable, Optional
from .base_app import BaseApp


class AgentApp(BaseApp):
    """
    openjiuwen Agent 应用类

    提供简洁的 API 用于部署 agent-studio Agent 到生产环境。

    设计理念:
    - 每个 AgentApp 只保存一个 Agent 实例
    - 一个 Agent 实例服务所有 conversation
    - Agent 内部通过 conversation_id 自动隔离 session

    TODO: 引入 agent 实例池或 provider 模式
    - 当前单实例模式在高并发场景下可能成为瓶颈
    - 后续引入 agent 实例池: 预创建多个 agent 实例，按需分配
    - 或引入 provider 模式: 动态创建/获取 agent 实例
    - 目标: 解决并行处理问题，提升并发能力

    用法:
        app = AgentApp("MyAgent", agent_config_path="agent_export.json")

        @app.init
        async def init():
            app.agent = await load_agent_from_config(app.agent_config_path)

        @app.query
        async def query(msgs, request):
            async for msg, last in app.agent.stream(
                messages=msgs,
                conversation_id=request.conversation_id,
            ):
                yield msg, last

        app.run(port=8090)
    """

    def __init__(
        self,
        app_name: str,
        app_description: str = "",
        version: str = "1.0.0",
        agent_config_path: str = None,
    ):
        super().__init__(app_name, app_description, version)

        # 查询钩子
        self._query_hook: Optional[Callable] = None

        # Agent 配置路径
        self.agent_config_path = agent_config_path

        # TODO: 引入 agent 实例池或 provider 模式
        # 当前单实例模式，后续改为实例池或动态创建以支持高并发
        self.agent = None

        # 可选服务
        self.sandbox_service = None

        # 注册 Agent 特定路由
        self._register_agent_routes()

    def query(self, func: Callable) -> Callable:
        """查询钩子装饰器"""
        self._query_hook = func
        return func

    def _register_agent_routes(self):
        """注册 Agent 特定路由"""
        from fastapi import Request

        @self.app.post("/query")
        async def query_endpoint(request: Request):
            """查询端点"""
            from fastapi.responses import StreamingResponse
            import json

            # 解析请求
            body = await request.body()
            data = json.loads(body)
            messages = data.get("messages", [])
            conversation_id = data.get("conversation_id")

            if not conversation_id:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail="conversation_id is required",
                )

            # 构造请求对象
            from openjiuwen_runtime.models.request import QueryRequest
            query_request = QueryRequest(
                messages=messages,
                conversation_id=conversation_id,
                user_id=data.get("user_id", "anonymous"),
            )

            # 执行查询钩子
            async def generate():
                if self._query_hook:
                    async for msg, last in self._query_hook(messages, query_request):
                        yield f"data: {msg.model_dump_json()}\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
            )

        @self.app.post("/reset_conversation")
        async def reset_conversation_endpoint(request: Request):
            """重置对话端点"""
            body = await request.body()
            data = json.loads(body)
            conversation_id = data.get("conversation_id")

            if not conversation_id:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail="conversation_id is required",
                )

            # 调用 Agent 内部的 session 清理方法
            if self.agent and hasattr(self.agent, 'clear_session'):
                await self.agent.clear_session(conversation_id)

            return {"status": "ok", "message": f"Conversation {conversation_id} reset"}

        # 更新健康检查，添加 agent_loaded 状态
        original_health = self.app.routes[-1]  # 获取 BaseApp 注册的 /health 端点

        @self.app.get("/health")
        async def health_with_agent():
            """健康检查（包含 Agent 状态）"""
            return {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
                "agent_loaded": self.agent is not None,
            }
```

### 3.3 PluginApp 核心设计

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/plugin_app.py

from typing import Callable, Dict, Any, Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .base_app import BaseApp


class PluginApp(BaseApp):
    """
    openjiuwen Plugin 应用类

    提供简洁的 API 用于部署同类工具集为 RESTful 服务。

    设计理念:
    - 一个 PluginApp 包含同一类别的多个工具
    - 工具应具有主题相关性（如：天气工具、搜索工具、数学工具）
    - 使用 @restful.tool() 装饰器注册工具
    - 自动为每个工具生成 RESTful 端点
    - 支持工具元数据定义

    用法 - 天气工具 Plugin:
        app = PluginApp(
            app_name="WeatherTools",
            app_description="天气查询工具集"
        )

        @app.restful.tool(name="current_weather", description="查询实时天气")
        async def current_weather(city: str) -> Dict[str, Any]:
            return {"city": city, "temperature": 25, "condition": "晴"}

        @app.restful.tool(name="weather_forecast", description="查询天气预报")
        async def weather_forecast(city: str, days: int = 3) -> Dict[str, Any]:
            return {"city": city, "forecast": [...]}

        app.run(port=8091)

    用法 - 搜索工具 Plugin:
        app = PluginApp(
            app_name="SearchTools",
            app_description="搜索和查询工具集"
        )

        @app.restful.tool(name="web_search", description="网络搜索")
        async def web_search(query: str) -> Dict[str, Any]:
            return {"results": [...]}

        @app.restful.tool(name="image_search", description="图片搜索")
        async def image_search(query: str) -> Dict[str, Any]:
            return {"images": [...]}
    """

    def __init__(
        self,
        app_name: str,
        app_description: str = "",
        version: str = "1.0.0",
    ):
        super().__init__(app_name, app_description, version)

        # 工具注册表
        self._tools: Dict[str, Dict[str, Any]] = {}

        # 创建工具装饰器（绑定到当前 app）
        from .restful import RestfulToolDecorator
        self.restful = RestfulToolDecorator(self)

        # 注册 Plugin 特定路由
        self._register_plugin_routes()

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str = "",
        parameters: Dict[str, Any] = None,
    ):
        """
        注册工具

        Args:
            name: 工具名称
            func: 工具函数
            description: 工具描述
            parameters: 参数定义（可选）
        """
        self._tools[name] = {
            "name": name,
            "func": func,
            "description": description,
            "parameters": parameters or {},
        }

        # 为工具创建路由
        self._create_tool_route(name, func)

    def _create_tool_route(self, name: str, func: Callable):
        """为工具创建 RESTful 路由"""

        @self.app.post(f"/tools/{name}")
        async def tool_endpoint(request: Request):
            """工具执行端点"""
            try:
                import json

                # 解析请求
                body = await request.body()
                data = json.loads(body) if body else {}

                # 执行工具函数
                result = await func(**data) if asyncio.iscoroutinefunction(func) else func(**data)

                return {
                    "status": "success",
                    "tool": name,
                    "result": result,
                }
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Tool execution failed: {str(e)}",
                )

    def _register_plugin_routes(self):
        """注册 Plugin 特定路由"""

        @self.app.get("/tools")
        async def list_tools():
            """列出所有工具"""
            tools_info = []
            for name, tool in self._tools.items():
                tools_info.append({
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                    "endpoint": f"/tools/{name}",
                })
            return {
                "status": "success",
                "tools": tools_info,
            }

        # 更新健康检查，添加工具数量
        @self.app.get("/health")
        async def health_with_tools():
            """健康检查（包含工具状态）"""
            return {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
                "tools_count": len(self._tools),
            }
```

### 3.4 @restful.tool() 装饰器

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/restful.py

import asyncio
import inspect
from typing import Dict, Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin_app import PluginApp


class RestfulToolDecorator:
    """
    @restful.tool() 装饰器实现

    用于将 Python 函数注册为 RESTful 工具。

    支持的功能:
    - 自动提取函数签名生成参数定义
    - 支持同步和异步函数
    - 支持工具元数据定义
    """

    def __init__(self, plugin_app: "PluginApp"):
        """
        初始化装饰器

        Args:
            plugin_app: PluginApp 实例（必需）
        """
        self.plugin_app = plugin_app

    def tool(
        self,
        name: str = None,
        description: str = "",
    ):
        """
        工具装饰器

        Args:
            name: 工具名称（默认使用函数名）
            description: 工具描述
        """

        def decorator(func: Callable) -> Callable:
            # 提取函数签名
            sig = inspect.signature(func)
            parameters = {}
            for param_name, param in sig.parameters.items():
                param_info = {"type": str(param.annotation if param.annotation != inspect.Parameter.empty else "any")}
                if param.default != inspect.Parameter.empty:
                    param_info["default"] = param.default
                parameters[param_name] = param_info

            # 确定工具名称
            tool_name = name or func.__name__

            # 直接注册到 PluginApp
            self.plugin_app.register_tool(
                name=tool_name,
                func=func,
                description=description,
                parameters=parameters,
            )

            return func

        return decorator
```

### 3.5 Agent 加载器

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/loader.py

from typing import Union, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from openjiuwen.Agent import Agent


async def load_agent_from_config(
    config_path: Union[str, Path],
    current_user: dict = None,
) -> "Agent":
    """
    从配置文件加载并创建 Agent 实例

    此函数通过调用 openjiuwen studio 提供的 Agent 编译接口来加载 Agent。

    Args:
        config_path: Agent 配置文件路径（JSON 格式）
        current_user: 当前用户信息

    Returns:
        编译后的 Agent 实例

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件格式错误或 agent_type 不支持

    Note:
        依赖 openjiuwen studio 提供的 Agent 编译接口。
        支持的 agent_type:
        - "react": ReAct Agent
        - "workflow": Workflow Agent

    Example:
        >>> agent = await load_agent_from_config(
        ...     "agent_export.json",
        ...     current_user={"user_id": "system"}
        ... )
    """
    import json
    from openjiuwen.studio import AgentCompiler  # 由 openjiuwen studio 提供

    # 1. 读取 JSON 配置文件
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Agent config not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        agent_config = json.load(f)

    # 2. 调用 openjiuwen studio 的 Agent 编译接口
    compiler = AgentCompiler()
    agent = await compiler.compile(
        config=agent_config,
        current_user=current_user or {"user_id": "system"},
    )

    return agent
```

### 3.6 请求模型

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/models/request.py

from pydantic import BaseModel
from typing import List, Dict, Any


class QueryRequest(BaseModel):
    """查询请求模型"""

    messages: List[Dict[str, Any]]  # 当前消息（非完整历史）
    conversation_id: str              # 对话 ID（必需）
    user_id: str                      # 用户 ID
    space_id: str = "default"         # 工作空间 ID
    stream: bool = True                # 是否流式输出
```

### 3.7 AppGroup 多应用容器

```python
# agent-runtime/src/sdk/src/openjiuwen_runtime/core/app_group.py

from typing import Dict
from fastapi import FastAPI
import uvicorn

from .base_app import BaseApp
from .agent_app import AgentApp
from .plugin_app import PluginApp


class AppGroup:
    """
    多应用容器，允许多个 AgentApp/PluginApp 共享一个 FastAPI 服务。

    设计理念:
    - 单一 FastAPI 服务托管多个应用
    - 通过路径前缀区分应用 (如 /customer/query)
    - 聚合生命周期钩子执行
    - 聚合健康检查

    用法:
        group = AppGroup("MyAgentGroup")

        customer_app = AgentApp("CustomerAgent")
        @customer_app.query
        async def query(msgs, request): ...

        assistant_app = AgentApp("AssistantAgent")
        @assistant_app.query
        async def query(msgs, request): ...

        group.mount("/customer", customer_app)
        group.mount("/assistant", assistant_app)
        group.run(port=8090)
    """

    def __init__(
        self,
        group_name: str,
        description: str = "",
        version: str = "1.0.0",
    ):
        self.group_name = group_name
        self.description = description
        self.version = version

        # 主 FastAPI 应用
        self.app = FastAPI(
            title=group_name,
            description=description,
            version=version,
        )

        # 已挂载的应用注册表: prefix -> BaseApp
        self._mounted_apps: Dict[str, BaseApp] = {}

    def mount(self, prefix: str, app: BaseApp) -> "AppGroup":
        """
        挂载应用到指定路径前缀。

        Args:
            prefix: URL 路径前缀 (如 "/customer", "/assistant")
            app: BaseApp 实例 (AgentApp 或 PluginApp)

        Returns:
            Self，支持链式调用
        """
        # 规范化前缀
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        prefix = prefix.rstrip("/")

        # 检查重复前缀
        if prefix in self._mounted_apps:
            raise ValueError(f"前缀 '{prefix}' 已被挂载")

        self._mounted_apps[prefix] = app
        self.app.mount(prefix, app.app)

        return self

    def _register_lifecycle_events(self):
        """注册聚合的启动和关闭事件"""

        @self.app.on_event("startup")
        async def startup():
            """按顺序执行所有挂载应用的 init 钩子"""
            for prefix, app in self._mounted_apps.items():
                if app._init_hook:
                    await app._init_hook()

        @self.app.on_event("shutdown")
        async def shutdown():
            """按逆序执行所有挂载应用的 shutdown 钩子"""
            for prefix, app in reversed(list(self._mounted_apps.items())):
                if app._shutdown_hook:
                    await app._shutdown_hook()

    def _register_routes(self):
        """注册 AppGroup 特定路由"""

        @self.app.get("/health")
        async def health():
            """聚合健康检查"""
            apps_status = {}
            overall_healthy = True

            for prefix, app in self._mounted_apps.items():
                app_info = {
                    "name": app.app_name,
                    "version": app.version,
                    "mount_path": prefix,
                }

                if isinstance(app, AgentApp):
                    app_info["type"] = "agent"
                    app_info["agent_loaded"] = app.agent is not None
                    if app.agent is None:
                        overall_healthy = False
                elif isinstance(app, PluginApp):
                    app_info["type"] = "plugin"
                    app_info["tools_count"] = len(app._tools)
                else:
                    app_info["type"] = "base"

                apps_status[prefix] = app_info

            return {
                "status": "healthy" if overall_healthy else "degraded",
                "group": self.group_name,
                "version": self.version,
                "apps_count": len(self._mounted_apps),
                "apps": apps_status,
            }

        @self.app.get("/")
        async def root():
            """根端点，列出所有挂载的应用"""
            return {
                "group": self.group_name,
                "version": self.version,
                "mounted_apps": [
                    {"prefix": prefix, "name": app.app_name}
                    for prefix, app in self._mounted_apps.items()
                ],
            }

    def run(self, host: str = "0.0.0.0", port: int = 8090, **kwargs):
        """运行所有挂载应用"""
        self._register_routes()
        self._register_lifecycle_events()
        uvicorn.run(self.app, host=host, port=port, **kwargs)
```

**端点结构:**

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | 组信息，列出所有挂载应用 |
| `/health` | GET | 聚合健康检查 |
| `/docs` | GET | OpenAPI 文档 |
| `/{prefix}/health` | GET | 单应用健康检查 |
| `/{prefix}/query` | POST | AgentApp 查询端点 (SSE) |
| `/{prefix}/reset_conversation` | POST | AgentApp 重置对话 |
| `/{prefix}/tools` | GET | PluginApp 工具列表 |
| `/{prefix}/tools/{name}` | POST | PluginApp 执行工具 |

---

## 4. 使用示例

### 4.1 AgentApp 示例

```python
# examples/simple_agent.py

from openjiuwen_runtime import AgentApp
from openjiuwen_runtime.core.loader import load_agent_from_config

app = AgentApp(
    app_name="SimpleAgent",
    agent_config_path="configs/customer_service.json",
)

@app.init
async def init():
    """创建 Agent 实例"""
    app.agent = await load_agent_from_config(
        config_path=app.agent_config_path,
        current_user={"user_id": "system"},
    )

@app.query
async def query(msgs, request):
    """处理查询"""
    async for msg, last in app.agent.stream(
        messages=msgs,
        conversation_id=request.conversation_id,
    ):
        yield msg, last

@app.shutdown
async def shutdown():
    """清理资源"""
    if app.agent and hasattr(app.agent, 'cleanup'):
        await app.agent.cleanup()

if __name__ == "__main__":
    app.run(port=8090)
```

### 4.2 PluginApp 示例

```python
# examples/weather_plugin.py

from openjiuwen_runtime import PluginApp
import httpx

app = PluginApp(
    app_name="WeatherTools",
    app_description="天气查询工具集",
    version="1.0.0",
)

@app.init
async def init():
    """初始化 HTTP 客户端"""
    app.http_client = httpx.AsyncClient(timeout=30.0)

@app.shutdown
async def shutdown():
    """清理资源"""
    if hasattr(app, 'http_client'):
        await app.http_client.aclose()

@app.restful.tool(name="current_weather", description="查询实时天气")
async def current_weather(city: str, unit: str = "celsius") -> dict:
    """
    获取指定城市的实时天气

    Args:
        city: 城市名称
        unit: 温度单位 (celsius/fahrenheit)

    Returns:
        实时天气信息
    """
    response = await app.http_client.get(
        f"https://api.weather.example.com/current",
        params={"city": city, "unit": unit},
    )
    return response.json()

@app.restful.tool(name="weather_forecast", description="查询天气预报")
async def weather_forecast(city: str, days: int = 3) -> dict:
    """
    获取指定城市的天气预报

    Args:
        city: 城市名称
        days: 预报天数

    Returns:
        天气预报信息
    """
    response = await app.http_client.get(
        f"https://api.weather.example.com/forecast",
        params={"city": city, "days": days},
    )
    return response.json()

@app.restful.tool(name="weather_alerts", description="查询天气预警")
async def weather_alerts(city: str) -> dict:
    """
    获取指定城市的天气预警信息

    Args:
        city: 城市名称

    Returns:
        天气预警列表
    """
    response = await app.http_client.get(
        f"https://api.weather.example.com/alerts",
        params={"city": city},
    )
    return response.json()

if __name__ == "__main__":
    app.run(port=8091)
```

### 4.3 向 Agent 发送请求

假设 Agent 已经通过 4.1 部署在 `http://localhost:8090`，下面演示如何向其发送请求。

#### 使用 curl 测试

**1. 健康检查**
```bash
curl http://localhost:8090/health
```
响应：
```json
{
  "status": "healthy",
  "app": "CustomerService",
  "version": "1.0.0",
  "agent_loaded": true
}
```

**2. 发送查询请求**
```bash
curl -X POST http://localhost:8090/query \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "你好，我想查询订单状态"}
    ],
    "conversation_id": "conv_001",
    "user_id": "user_123"
  }'
```

**3. 查看流式响应**
```bash
# 方式 1: 直接输出 SSE 流
curl -N -X POST http://localhost:8090/query \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你好"}],
    "conversation_id": "conv_002",
    "user_id": "user_123"
  }'

# 方式 2: 格式化输出（使用 jq）
curl -N -X POST http://localhost:8090/query \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "帮我查一下北京天气"}],
    "conversation_id": "conv_003",
    "user_id": "user_123"
  }' | while read -r line; do
    if [[ $line == data:* ]]; then
      echo "${line#data: }" | jq .
    fi
  done
```

**4. 重置对话**
```bash
curl -X POST http://localhost:8090/reset_conversation \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_001"
  }'
```
响应：
```json
{
  "status": "ok",
  "message": "Conversation conv_001 reset"
}
```

#### 使用 Python 测试

```python
import asyncio
import json
import httpx

async def query_agent():
    agent_url = "http://localhost:8090"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 健康检查
        health = await client.get(f"{agent_url}/health")
        print(f"Health: {health.json()}")

        # 发送查询
        request_data = {
            "messages": [
                {"role": "user", "content": "帮我查询订单 12345 的状态"}
            ],
            "conversation_id": "conv_python_001",
            "user_id": "user_123",
        }

        # 接收流式响应
        async with client.stream(
            "POST",
            f"{agent_url}/query",
            json=request_data,
        ) as response:
            print(f"\nAgent Response:")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    try:
                        message = json.loads(data)
                        if message.get("type") == "text":
                            print(f"🤖 {message.get('content', '')}")
                        elif message.get("type") == "tool_call":
                            print(f"🔧 调用工具: {message.get('tool_name', '')}")
                    except json.JSONDecodeError:
                        pass

if __name__ == "__main__":
    asyncio.run(query_agent())
```

#### API 端点总结

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/query` | POST | 发送查询（返回 SSE 流） |
| `/reset_conversation` | POST | 重置指定对话的上下文 |

### 4.4 AppGroup 示例 - 多 Agent 共享端口

```python
# examples/multi_agent_group.py

from openjiuwen_runtime import AgentApp, AppGroup


# 创建客服 Agent
customer_app = AgentApp(
    app_name="CustomerService",
    app_description="客服 Agent",
    version="1.0.0",
)

@customer_app.init
async def init_customer():
    print("客服 Agent 初始化完成")

@customer_app.query
async def query_customer(msgs, request):
    # 客服逻辑
    yield {"type": "text", "content": f"客服回复: {msgs[-1]['content']}"}, True


# 创建助手 Agent
assistant_app = AgentApp(
    app_name="PersonalAssistant",
    app_description="个人助手 Agent",
    version="1.0.0",
)

@assistant_app.init
async def init_assistant():
    print("助手 Agent 初始化完成")

@assistant_app.query
async def query_assistant(msgs, request):
    # 助手逻辑
    yield {"type": "text", "content": f"助手回复: {msgs[-1]['content']}"}, True


# 创建应用组并挂载
group = AppGroup(
    group_name="MultiAgentService",
    description="多 Agent 服务组",
    version="1.0.0",
)

group.mount("/customer", customer_app)
group.mount("/assistant", assistant_app)


if __name__ == "__main__":
    # 支持 --host 和 --port 命令行参数
    group.run(port=8090)
```

**测试 AppGroup:**

```bash
# 查看组信息
curl http://localhost:8090/

# 组健康检查
curl http://localhost:8090/health

# 查询客服 Agent
curl -X POST http://localhost:8090/customer/query \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}], "conversation_id": "test1"}'

# 查询助手 Agent
curl -X POST http://localhost:8090/assistant/query \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}], "conversation_id": "test2"}'
```

**响应示例 - 组健康检查:**

```json
{
  "status": "healthy",
  "group": "MultiAgentService",
  "version": "1.0.0",
  "apps_count": 2,
  "apps": {
    "/customer": {
      "name": "CustomerService",
      "version": "1.0.0",
      "mount_path": "/customer",
      "type": "agent",
      "agent_loaded": true
    },
    "/assistant": {
      "name": "PersonalAssistant",
      "version": "1.0.0",
      "mount_path": "/assistant",
      "type": "agent",
      "agent_loaded": true
    }
  }
}
```

