#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Lowcode Agent Runner - 命令行入口

支持通过以下方式运行:
    python -m openjiuwen_runtime.examples.lowcode_agent --file config.json --port 8091
    lowcode-agent-runner --file config.json --port 8091
"""

from pathlib import Path
import argparse
import sys

# 导入应用（延迟导入以避免初始化问题）
def _load_app():
    from .lowcode_agent_runner import app, FILE_PATH
    return app, FILE_PATH


def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(
        description="Lowcode Agent Runner - 从导出的 JSON 配置加载并运行 Agent"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="导出的 Agent JSON 配置文件路径 (必需)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="监听地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8090,
        help="监听端口 (默认: 8090)"
    )

    args = parser.parse_args()

    # 设置导出文件路径
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(f"[ERROR] 配置文件不存在: {file_path}")
        sys.exit(1)

    # 延迟加载应用
    app, FILE_PATH = _load_app()

    # 更新全局变量
    import openjiuwen_runtime.examples.lowcode_agent.lowcode_agent_runner as runner_module
    runner_module.FILE_PATH = str(file_path)

    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()