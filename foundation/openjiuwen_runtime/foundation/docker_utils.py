# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

import asyncio
from pathlib import Path
from typing import Optional


async def build_docker_image(
        context_path: str,
        dockerfile: str = "Dockerfile",
        image_name: str = None,
        tag: str = "latest",
        build_args: Optional[dict] = None,
        docker_host: Optional[str] = None,
) -> tuple[bool, str]:
    """
    构建Docker镜像
    
    Args:
        context_path: 构建上下文路径
        dockerfile: Dockerfile路径，相对于context_path
        image_name: 镜像名称
        tag: 镜像标签
        build_args: 构建参数
        docker_host: Docker主机地址
        
    Returns:
        tuple[bool, str]: (是否成功, 输出信息)
    """
    context_path = Path(context_path).resolve()
    if not context_path.exists():
        return False, f"Context path not found: {context_path}"

    cmd = ["docker"]
    if docker_host:
        cmd.extend(["-H", docker_host])

    cmd.extend(["build", "-t", f"{image_name}:{tag}"])

    if dockerfile != "Dockerfile":
        cmd.extend(["-f", dockerfile])

    if build_args:
        for key, value in build_args.items():
            cmd.extend(["--build-arg", f"{key}={value}"])

    cmd.append(str(context_path))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        return True, stdout.decode().strip()
    return False, stderr.decode().strip()


async def push_docker_image(
        image_name: str,
        tag: str = "latest",
        registry: Optional[str] = None,
        docker_host: Optional[str] = None,
) -> tuple[bool, str]:
    """
    推送Docker镜像
    
    Args:
        image_name: 镜像名称
        tag: 镜像标签
        registry: 镜像仓库地址
        docker_host: Docker主机地址
        
    Returns:
        tuple[bool, str]: (是否成功, 输出信息)
    """
    cmd = ["docker"]
    if docker_host:
        cmd.extend(["-H", docker_host])

    full_image_name = image_name
    if registry:
        full_image_name = f"{registry}/{image_name}"

    cmd.extend(["push", f"{full_image_name}:{tag}"])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        return True, stdout.decode().strip()
    return False, stderr.decode().strip()


async def tag_docker_image(
        source_image: str,
        target_image: str,
        source_tag: str = "latest",
        target_tag: str = "latest",
        docker_host: Optional[str] = None,
) -> tuple[bool, str]:
    """
    标记Docker镜像
    
    Args:
        source_image: 源镜像名称
        target_image: 目标镜像名称
        source_tag: 源标签
        target_tag: 目标标签
        docker_host: Docker主机地址
        
    Returns:
        tuple[bool, str]: (是否成功, 输出信息)
    """
    cmd = ["docker"]
    if docker_host:
        cmd.extend(["-H", docker_host])

    cmd.extend([
        "tag",
        f"{source_image}:{source_tag}",
        f"{target_image}:{target_tag}",
    ])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        return True, stdout.decode().strip()
    return False, stderr.decode().strip()


async def remove_docker_image(
        image_name: str,
        tag: str = "latest",
        force: bool = False,
        docker_host: Optional[str] = None,
) -> tuple[bool, str]:
    """
    删除Docker镜像
    
    Args:
        image_name: 镜像名称
        tag: 镜像标签
        force: 是否强制删除
        docker_host: Docker主机地址
        
    Returns:
        tuple[bool, str]: (是否成功, 输出信息)
    """
    cmd = ["docker"]
    if docker_host:
        cmd.extend(["-H", docker_host])

    cmd.extend(["rmi"])
    if force:
        cmd.append("-f")
    cmd.append(f"{image_name}:{tag}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        return True, stdout.decode().strip()
    return False, stderr.decode().strip()


def generate_dockerfile(
        base_image: str = "python:3.10-slim",
        workdir: str = "/app",
        package_name: str = None,
        port: int = 8000,
        entrypoint: Optional[str] = None,
        extra_commands: Optional[list] = None,
) -> str:
    """
    生成Dockerfile内容
    
    Args:
        base_image: 基础镜像
        workdir: 工作目录
        package_name: 包名
        port: 暴露端口
        entrypoint: 入口命令
        extra_commands: 额外命令
        
    Returns:
        str: Dockerfile内容
    """
    lines = [
        f"FROM {base_image}",
        "",
        f"WORKDIR {workdir}",
        "",
    ]

    if package_name:
        lines.extend([
            f"COPY dist/{package_name}*.whl /tmp/",
            "RUN pip install /tmp/*.whl",
            "",
        ])

    if extra_commands:
        for cmd in extra_commands:
            lines.append(f"RUN {cmd}")
        lines.append("")

    lines.append(f"EXPOSE {port}")
    lines.append("")

    if entrypoint:
        lines.append(f'ENTRYPOINT {entrypoint}')
    elif package_name:
        lines.append(f'ENTRYPOINT ["python", "-m", "{package_name}"]')

    return "\n".join(lines)
