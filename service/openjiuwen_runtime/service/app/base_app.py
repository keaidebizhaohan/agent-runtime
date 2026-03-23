"""
BaseApp - AgentApp 和 PluginApp 的基类

提供通用功能:
- FastAPI 应用管理
- 生命周期管理 (@init, @shutdown 装饰器)
- 健康检查端点 (/health)
- 运行方法 (uvicorn 服务器)
"""
from typing import Callable, Optional
from fastapi import FastAPI
import uvicorn


class BaseApp:
    """
    openjiuwen 应用基类

    为 AgentApp 和 PluginApp 提供通用功能:
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
        """
        初始化钩子装饰器

        用法:
            @app.init
            async def init():
                # 初始化代码
                pass
        """
        self._init_hook = func
        return func

    def shutdown(self, func: Callable) -> Callable:
        """
        清理钩子装饰器

        用法:
            @app.shutdown
            async def shutdown():
                # 清理代码
                pass
        """
        self._shutdown_hook = func
        return func

    def _register_base_routes(self):
        """注册基础路由 (/health, 生命周期事件)"""

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
            """健康检查端点"""
            return {
                "status": "healthy",
                "app": self.app_name,
                "version": self.version,
            }

    def run(self, host: str = "0.0.0.0", port: int = 8090, **kwargs):
        """
        运行应用

        参数:
            host: 绑定主机 (默认: 0.0.0.0)
            port: 绑定端口 (默认: 8090)
            **kwargs: 传递给 uvicorn.run() 的额外参数
        """
        print(f"Starting {self.app_name} v{self.version} on http://{host}:{port}")
        uvicorn.run(self.app, host=host, port=port, **kwargs)
