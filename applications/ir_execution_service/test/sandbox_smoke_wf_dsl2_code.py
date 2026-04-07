"""用 wf_dsl2.json 中 code_br6Gu 的同一段代码探测 CODE_SANDBOX_URL（与 RemoteCodeRunner 请求体一致）。"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import requests

DEFAULT_PY_CODE = """
class Args:
    def __init__(self, params):
        self.params = params

class Outputs(dict):
    pass
"""

USER_CODE = """def main(args: Args):
  import time
  time.sleep(3)
  return {'result': args.params['input']}"""


def _read_sandbox_url() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("CODE_SANDBOX_URL=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return (os.environ.get("CODE_SANDBOX_URL") or "").strip()


def main() -> None:
    url = _read_sandbox_url()
    if not url:
        raise SystemExit("未找到 CODE_SANDBOX_URL（.env 或环境变量）")

    dedented = textwrap.dedent(textwrap.dedent(DEFAULT_PY_CODE + "\n" + USER_CODE))
    payload = {
        "language": "python",
        "code": dedented,
        "inputs": {"input": "sandbox_smoke_test"},
        "timeout": 30,
    }
    print("POST", url)
    r = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=45,
    )
    print("HTTP", r.status_code)
    print("raw body:", r.text[:3000])
    r.raise_for_status()
    data = r.json()
    out = data.get("output")
    print("output:", out)
    if isinstance(out, dict):
        print("output.error:", out.get("error"))
        print("output.return:", out.get("return"))


if __name__ == "__main__":
    main()
