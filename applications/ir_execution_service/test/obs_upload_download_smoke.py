#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本地冒烟：
1) openjiuwen 的 AioBotoClient：upload_file + download_file
2) runtime_support.ir_fetch.ensure_ir_local_path：用刚上传的 object key 走一遍缓存下载逻辑

以下常量请与本机 applications/ir_execution_service/.env 中 OBS 段保持一致（勿将含密钥的修改提交到公共仓库）。

用法：
  cd applications/ir_execution_service
  uv run python test/obs_upload_download_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path

# --- 从 .env 手工同步的配置（与 LOWCODE_IR_OBS_BUCKET、OBS_* 一致）---
OBS_ACCESS_KEY_ID = "Jx96ZXEJ7GFIRezFaZyCqym9oTEyJUoK"
OBS_SECRET_ACCESS_KEY = "7Fesmvbt8CCBsBOHRPfkunOmrRfo2Dpm"
OBS_SERVER = "7.219.144.25"
OBS_REGION: str | None = None  # .env 里为空则保持 None
LOWCODE_IR_OBS_BUCKET = "poissontest-bj"
# ensure_ir_local_path 使用的缓存根（仅本脚本测试目录下，避免污染项目 .lowcode_ir_cache）
LOWCODE_IR_DOWNLOAD_DIR_REL = ".obs_ir_cache_smoke"
# -------------------------------------------------------------------


def _apply_obs_env_to_process() -> None:
    """供 ensure_ir_local_path 内无参 AioBotoClient() 读取。"""
    os.environ["OBS_ACCESS_KEY_ID"] = OBS_ACCESS_KEY_ID
    os.environ["OBS_SECRET_ACCESS_KEY"] = OBS_SECRET_ACCESS_KEY
    os.environ["OBS_SERVER"] = OBS_SERVER
    if OBS_REGION:
        os.environ["OBS_REGION"] = OBS_REGION
    else:
        os.environ.pop("OBS_REGION", None)
    os.environ["LOWCODE_IR_OBS_BUCKET"] = LOWCODE_IR_OBS_BUCKET


async def _main() -> None:
    from openjiuwen.core.foundation.store.object.aioboto_storage_client import AioBotoClient

    client = AioBotoClient(
        server=OBS_SERVER,
        access_key_id=OBS_ACCESS_KEY_ID,
        secret_access_key=OBS_SECRET_ACCESS_KEY,
        region_name=OBS_REGION,
    )

    test_dir = Path(__file__).resolve().parent
    test_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    object_key = f"ir_execution_service_smoke/{token}.txt"
    upload_path = test_dir / f".obs_upload_{token}.txt"
    download_path = test_dir / f".obs_download_{token}.txt"
    payload = f"obs-smoke-test token={token}\n".encode("utf-8")
    upload_path.write_bytes(payload)

    ok_up = await client.upload_file(
        bucket_name=LOWCODE_IR_OBS_BUCKET,
        object_name=object_key,
        file_path=upload_path,
    )
    if not ok_up:
        print("upload_file 返回 False", file=sys.stderr)
        raise SystemExit(10)

    if download_path.exists():
        download_path.unlink(missing_ok=True)

    ok_down = await client.download_file(
        bucket_name=LOWCODE_IR_OBS_BUCKET,
        object_name=object_key,
        file_path=download_path,
    )
    if not ok_down:
        print("download_file 返回 False", file=sys.stderr)
        raise SystemExit(11)

    if download_path.read_bytes() != payload:
        print("下载内容与上传不一致", file=sys.stderr)
        raise SystemExit(12)

    print("AioBotoClient upload_file + download_file OK")
    print(f"- bucket: {LOWCODE_IR_OBS_BUCKET}")
    print(f"- object_key: {object_key}")

    # --- ensure_ir_local_path：依赖进程环境变量 + 无参 AioBotoClient ---
    _apply_obs_env_to_process()
    cache_root = (test_dir / LOWCODE_IR_DOWNLOAD_DIR_REL).resolve()
    os.environ["LOWCODE_IR_DOWNLOAD_DIR"] = str(cache_root)
    # 避免并发测试时缓存淘汰干扰（0=不限制，与 ir_fetch 约定一致）
    os.environ["LOWCODE_IR_CACHE_MAX_FILES"] = "0"

    cached_expected = cache_root.joinpath(*object_key.replace("\\", "/").split("/"))
    if cached_expected.exists():
        cached_expected.unlink()
    cached_expected.parent.mkdir(parents=True, exist_ok=True)

    service_root = test_dir.parent
    if str(service_root) not in sys.path:
        sys.path.insert(0, str(service_root))

    from fastapi import HTTPException

    from runtime_support.ir_fetch import ensure_ir_local_path

    try:
        local_path = await ensure_ir_local_path(object_key)
    except HTTPException as e:
        print(f"ensure_ir_local_path 失败: {e.status_code} {e.detail}", file=sys.stderr)
        raise SystemExit(16) from e
    if local_path.resolve() != cached_expected.resolve():
        print(f"ensure_ir_local_path 返回路径与预期不一致: {local_path} != {cached_expected}", file=sys.stderr)
        raise SystemExit(13)
    if not local_path.is_file():
        print(f"ensure_ir_local_path 未生成文件: {local_path}", file=sys.stderr)
        raise SystemExit(14)
    if local_path.read_bytes() != payload:
        print("ensure_ir_local_path 落盘内容与上传不一致", file=sys.stderr)
        raise SystemExit(15)

    print("ensure_ir_local_path OK")
    print(f"- local_path: {local_path}")


if __name__ == "__main__":
    asyncio.run(_main())
