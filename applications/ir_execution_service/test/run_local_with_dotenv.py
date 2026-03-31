#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地测试入口：加载本目录 .env，补齐 OBS 占位，IR 根目录固定为 test/，再启动服务。

用法（在 applications/ir_execution_service 下）：
  uv run python run_local_with_dotenv.py

可选环境变量：IR_EXEC_HOST（默认 0.0.0.0）、IR_EXEC_PORT（默认 8090）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent


def _ensure_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as e:
        print("缺少 python-dotenv，请在本目录执行: uv sync", file=sys.stderr)
        raise SystemExit(1) from e

    env_path = _APP_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path)
    else:
        print(f"警告: 未找到 {env_path}，仅使用当前进程已有环境变量", file=sys.stderr)

    test_ir_root = _APP_ROOT / "test"
    test_ir_root.mkdir(parents=True, exist_ok=True)
    os.environ["LOWCODE_IR_DOWNLOAD_DIR"] = str(test_ir_root.resolve())

    obs_placeholders = {
        "OBS_ACCESS_KEY_ID": "local-placeholder",
        "OBS_SECRET_ACCESS_KEY": "local-placeholder",
        "OBS_SERVER": "https://obs.local-placeholder.invalid",
        "OBS_REGION": "local",
        "LOWCODE_IR_OBS_BUCKET": "local-placeholder-bucket",
    }
    for key, val in obs_placeholders.items():
        if not (os.environ.get(key) or "").strip():
            os.environ[key] = val


def main() -> None:
    _ensure_env()

    if str(_APP_ROOT) not in sys.path:
        sys.path.insert(0, str(_APP_ROOT))

    import ir_execution_service_app as app_entry

    host = (os.environ.get("IR_EXEC_HOST") or "0.0.0.0").strip()
    port = int((os.environ.get("IR_EXEC_PORT") or "8090").strip())
    print(
        f"IR 本地目录: {os.environ.get('LOWCODE_IR_DOWNLOAD_DIR')}\n"
        f"请求 ir_path 需为该目录下的相对路径，例如 complicated_dsl.json 对应 test/complicated_dsl.json\n"
        f"监听: http://{host}:{port}",
        flush=True,
    )
    app_entry.runner.run(host=host, port=port)


if __name__ == "__main__":
    main()
