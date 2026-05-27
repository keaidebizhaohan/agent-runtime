# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

"""本地进程级部署：subprocess 拉起 jiuwenclaw AgentServer，供 Runtime Session 编排使用。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from openjiuwen_runtime.foundation.log import get_logger

from .runtime import IDeployController

logger = get_logger(__name__)


def _windows_system32_exe(filename: str) -> str:
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return str(Path(system_root) / "System32" / filename)


@dataclass(frozen=True)
class ProcessRunInfo:
    """进程拉起后的可访问点（与 DockerRunInfo / PodDeployInfo 对称）。"""

    process_id: int
    host: str
    port: int


class ProcessServiceHandler:
    """通过 subprocess 启动 AgentServer 进程。"""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        publish_port: Optional[int] = None,
        env_vars: Optional[Dict[str, str]] = None,
        ready_timeout: float = 120.0,
        ready_poll_interval: float = 0.5,
        python_executable: Optional[str] = None,
        module: str = "jiuwenclaw.app_agentserver",
        launcher_script: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = int(publish_port) if publish_port else 0
        self._env_vars = dict(env_vars or {})
        self._ready_timeout = float(ready_timeout)
        self._ready_poll_interval = float(ready_poll_interval)
        self._python = python_executable or sys.executable
        self._module = module
        self._launcher_script = launcher_script or os.getenv("AGENT_SERVER_LAUNCHER_SCRIPT") or None
        self._process: Optional[subprocess.Popen[Any]] = None
        self._process_id: Optional[int] = None

    @property
    def process_id(self) -> Optional[int]:
        return self._process_id

    async def deploy(self) -> ProcessRunInfo:
        if self._port <= 0:
            raise ValueError("publish_port must be set before ProcessServiceHandler.deploy()")

        env = os.environ.copy()
        env.update(self._env_vars)
        env.setdefault("AGENT_SERVER_HOST", self._host)

        if self._launcher_script:
            cmd = [self._python, self._launcher_script, "--port", str(self._port)]
        else:
            cmd = [
                self._python,
                "-m",
                self._module,
                "--port",
                str(self._port),
            ]

        creation_flags = 0
        preexec_fn = None
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            import os as _os

            preexec_fn = _os.setsid

        logger.info(
            "Process deploy 开始: module=%s host=%s port=%s",
            self._module,
            self._host,
            self._port,
        )
        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            preexec_fn=preexec_fn,
        )
        self._process_id = self._process.pid

        await self._wait_until_ready()
        info = ProcessRunInfo(process_id=self._process_id, host=self._host, port=self._port)
        logger.info("Process deploy 成功: %s", info)
        return info

    async def _wait_until_ready(self) -> None:
        import websockets

        deadline = asyncio.get_running_loop().time() + self._ready_timeout
        url = f"ws://{self._host}:{self._port}"
        last_error: Exception | None = None

        while asyncio.get_running_loop().time() < deadline:
            proc = self._process
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(
                    f"AgentServer process exited early with code {proc.returncode}"
                )
            try:
                async with websockets.connect(url, open_timeout=2.0):
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                await asyncio.sleep(self._ready_poll_interval)

        raise TimeoutError(
            f"AgentServer not ready within {self._ready_timeout}s url={url} last_error={last_error}"
        )

    async def delete(self) -> str:
        pid = self._process_id
        proc = self._process
        self._process = None
        self._process_id = None

        if proc is not None and proc.poll() is None:
            if sys.platform == "win32":
                taskkill = _windows_system32_exe("taskkill.exe")
                subprocess.run(
                    [taskkill, "/F", "/T", "/PID", str(proc.pid)],
                    shell=False,
                    capture_output=True,
                    text=True,
                )
            else:
                import os as _os
                import signal

                try:
                    _os.killpg(_os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        _os.killpg(_os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        proc.kill()

        label = str(pid or "unknown")
        logger.info("Process delete 完成: pid=%s", label)
        return label


class ProcessDeployController:
    def __init__(self, inner: ProcessServiceHandler) -> None:
        self._inner = inner

    @property
    def resource_id(self) -> str | None:
        pid = self._inner.process_id
        return str(pid) if pid is not None else None

    async def deploy(self) -> Any:
        return await self._inner.deploy()

    async def delete(self) -> str:
        return await self._inner.delete()
