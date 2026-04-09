"""
AgentApp - Agent 应用类

提供部署 agent-studio Agent 的功能:
- Agent 实例管理
- @query 装饰器用于处理查询
- /query 和 /reset_conversation 端点
"""

import json
import asyncio
import logging
import inspect
import contextvars
import time
import uuid
from typing import Callable, Optional
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .base_app import BaseApp
from .middleware import Middleware, MiddlewareContext
from ..models.request import QueryRequest, ResetConversationRequest

logger = logging.getLogger(__name__)


class AgentApp(BaseApp):
    """
    openjiuwen Agent 应用类

    提供简单的 API 用于将 agent-studio Agent 部署到生产环境。

    设计原则:
    - 每个 AgentApp 持有一个 Agent 实例
    - 一个 Agent 服务所有对话
    - Agent 内部通过 conversation_id 隔离会话

    用法:
        app = AgentApp("MyAgent")

        @app.init
        async def init():
            app.agent = await load_agent_from_config(...)

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
        self._agent_detail_hook: Optional[Callable] = None

        # 中间件列表
        self._middlewares: list = []

        # Agent 配置路径
        self.agent_config_path = agent_config_path

        # Agent 实例 (由用户初始化)
        self.agent = None

        # 可选服务
        self.sandbox_service = None

        # 并发流状态（用于排障）
        self._active_query_streams = 0
        self._active_query_lock = asyncio.Lock()

        # 注册 Agent 特定路由
        self._register_agent_routes()

    def query(self, func: Callable) -> Callable:
        """
        查询钩子装饰器

        用法:
            @app.query
            async def query(msgs, request):
                # 处理查询
                async for msg, last in agent.stream(...):
                    yield msg, last
        """
        self._query_hook = func
        return func

    def agent_detail(self, func: Callable) -> Callable:
        """
        Agent 详情钩子装饰器

        用法:
            @app.agent_detail
            async def agent_detail():
                return {"agent_name": "demo"}
        """
        self._agent_detail_hook = func
        return func

    def add_middleware(self, middleware: Middleware) -> 'AgentApp':
        """
        添加中间件实例

        参数:
            middleware: 中间件实例

        返回:
            self，支持链式调用
        """
        self._middlewares.append(middleware)
        return self

    def middleware(self, middleware_class):
        """
        中间件装饰器

        用法:
            @app.middleware(MyMiddleware)
            class MyMiddleware(Middleware):
                pass

        参数:
            middleware_class: 中间件类

        返回:
            中间件实例
        """
        instance = middleware_class()
        self._middlewares.append(instance)
        return instance

    def _register_agent_routes(self):
        """注册 Agent 特定路由"""

        @self.app.post("/query")
        async def query_endpoint(query_request: QueryRequest, request: Request):
            """
            查询端点 - 发送消息给 Agent 并获取流式响应

            参数:
                query_request: 包含 messages 和 conversation_id 的查询请求

            返回:
                Agent 响应的服务器发送事件 (SSE) 流
            """
            # 从请求中提取消息
            messages = query_request.messages

            # 执行查询钩子
            async def generate():
                if self._query_hook:
                    request_id = uuid.uuid4().hex[:8]
                    started_at = time.perf_counter()

                    async with self._active_query_lock:
                        self._active_query_streams += 1
                        active_streams = self._active_query_streams
                    logger.info(
                        "[query_start] request_id=%s conversation_id=%s active_streams=%s",
                        request_id,
                        query_request.conversation_id,
                        active_streams,
                    )

                    # 创建中间件上下文
                    context = MiddlewareContext()
                    processed_messages = messages

                    # 调用所有中间件的 before_query 方法
                    for mw in self._middlewares:
                        try:
                            processed_messages = await mw.before_query(
                                processed_messages, query_request, context
                            )
                        except Exception:
                            pass

                    try:
                        chunk_count = 0
                        cancel_event = asyncio.Event()
                        gen = self._query_hook(processed_messages, query_request, cancel_event)
                        disconnect_watcher_task = None

                        async def watch_disconnect():
                            # 独立轮询客户端断连，避免生成器阻塞时无法及时设置 cancel_event
                            while not cancel_event.is_set():
                                try:
                                    if await request.is_disconnected():
                                        logger.info(
                                            "[disconnect_watcher] request_id=%s conversation_id=%s client disconnected",
                                            request_id,
                                            query_request.conversation_id,
                                        )
                                        cancel_event.set()
                                        return
                                except Exception:
                                    # 断连检查失败时不影响主流程
                                    pass
                                await asyncio.sleep(0.2)

                        disconnect_watcher_task = asyncio.create_task(watch_disconnect())

                        try:
                            async for msg, last in gen:
                                if await request.is_disconnected():
                                    logger.info(
                                        "[generate] request_id=%s conversation_id=%s client disconnected at chunk=%s",
                                        request_id,
                                        query_request.conversation_id,
                                        chunk_count,
                                    )
                                    cancel_event.set()
                                    break
                                chunk_count += 1
                                processed_msg = msg
                                for mw in self._middlewares:
                                    try:
                                        processed_msg = await mw.before_response(
                                            processed_messages, query_request, processed_msg, context
                                        )
                                    except Exception:
                                        pass

                                if chunk_count <= 3:
                                    logger.info(
                                        "[generate] request_id=%s conversation_id=%s yielding chunk=%s type=%s",
                                        request_id,
                                        query_request.conversation_id,
                                        chunk_count,
                                        type(processed_msg).__name__,
                                    )
                                yield f"data: {json.dumps(processed_msg)}\n\n"
                        finally:
                            cancel_event.set()
                            if disconnect_watcher_task:
                                disconnect_watcher_task.cancel()
                                try:
                                    await disconnect_watcher_task
                                except asyncio.CancelledError:
                                    pass

                        logger.info(
                            "[generate_finish] request_id=%s conversation_id=%s total_chunks=%s elapsed=%.3fs",
                            request_id,
                            query_request.conversation_id,
                            chunk_count,
                            time.perf_counter() - started_at,
                        )

                        # 调用 after_query 中间件
                        for mw in self._middlewares:
                            try:
                                await mw.after_query(processed_messages, query_request, context)
                            except Exception:
                                pass

                        logger.info(
                            "Query completed - request_id=%s conversation_id=%s total_messages=%s elapsed=%.3fs",
                            request_id,
                            query_request.conversation_id,
                            chunk_count,
                            time.perf_counter() - started_at,
                        )

                    except Exception as e:
                        logger.error(
                            "Query execution failed - request_id=%s conversation_id=%s error=%s",
                            request_id,
                            query_request.conversation_id,
                            e,
                            exc_info=True,
                        )
                        # 调用错误中间件
                        for mw in self._middlewares:
                            try:
                                await mw.on_error(processed_messages, query_request, e, context)
                            except Exception:
                                pass

                        # 发送错误事件
                        error_event = {
                            "type": "error",
                            "error": str(e),
                        }
                        error_data = f"data: {json.dumps(error_event, ensure_ascii=False, default=str)}\n\n"
                        yield error_data

                    except asyncio.CancelledError:
                        logger.warning(
                            "Query stream cancelled - request_id=%s conversation_id=%s",
                            request_id,
                            query_request.conversation_id,
                        )
                        raise
                    finally:
                        async with self._active_query_lock:
                            self._active_query_streams = max(0, self._active_query_streams - 1)
                            active_streams = self._active_query_streams
                        logger.info(
                            "[query_end] request_id=%s conversation_id=%s active_streams=%s elapsed=%.3fs",
                            request_id,
                            query_request.conversation_id,
                            active_streams,
                            time.perf_counter() - started_at,
                        )

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @self.app.post("/reset_conversation")
        async def reset_conversation_endpoint(request: ResetConversationRequest):
            """
            重置对话端点 - 清除对话上下文

            参数:
                request: 包含 conversation_id 的重置请求

            返回:
                状态消息
            """
            # 调用 Agent 的会话清理方法
            if self.agent and hasattr(self.agent, 'clear_session'):
                await self.agent.clear_session(request.conversation_id)

            return {"status": "ok", "message": f"Conversation {request.conversation_id} reset"}

        @self.app.get("/agent_detail")
        async def agent_detail_endpoint():
            """
            Agent 详情端点 - 返回当前 Agent 的 IR 详情信息

            返回:
                Agent 详情字典
            """
            if not self._agent_detail_hook:
                raise HTTPException(status_code=501, detail="agent_detail hook not implemented")

            try:
                detail = self._agent_detail_hook()
                if inspect.isawaitable(detail):
                    detail = await detail
                if detail is None:
                    detail = {}
                return detail
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Agent detail execution failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        # 更新健康检查，包含 agent_loaded 状态
        # 获取原始 /health 路由
        for route in self.app.routes:
            if hasattr(route, 'path') and route.path == "/health":
                # 存储原始端点
                original_endpoint = route.app
                break
        else:
            original_endpoint = None

        # 定义增强的健康检查
        @self.app.get("/health")
        async def health_with_agent():
            """健康检查（包含 Agent 状态）"""
            started_at = time.perf_counter()
            health_data = {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
                "agent_loaded": self.agent is not None,
                "active_query_streams": self._active_query_streams,
            }
            logger.info(
                "[health] status=%s agent_loaded=%s active_streams=%s elapsed=%.3fs",
                health_data["status"],
                health_data["agent_loaded"],
                health_data["active_query_streams"],
                time.perf_counter() - started_at,
            )

            return health_data
