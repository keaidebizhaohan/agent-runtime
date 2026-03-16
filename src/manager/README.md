# Agent Runtime Manager

**openjiuwen-runtime** 的部署管理系统，提供 Agent 和 Plugin 的部署、查询和管理功能。

## 核心特性

### 虚拟环境隔离
- 每个部署使用独立的虚拟环境，避免依赖冲突
- 删除部署时自动清理虚拟环境
- 支持跨平台（Windows/Linux/Mac）

### WHL 包部署
- 标准化的 Python 包分发格式
- 自动解析包名，无需手动指定
- 自动安装 WHL 包依赖到独立虚拟环境

### 灵活的管理方式
- **CLI 模式**: 命令行工具，适合本地开发测试
- **SDK 模式**: Python SDK，适合集成到其他系统
- **Server 模式**: REST API（预留，供 AgentStudio 调用）

## 快速开始

### 1. 安装 CLI

```bash
# 进入 CLI 目录
cd cli

# 创建虚拟环境并安装依赖
uv venv
uv sync

# 安装 CLI（editable 模式）
uv pip install -e ./
```

### 2. 准备 WHL 包

```bash
# 构建示例 Agent WHL 包
cd examples/my_agent
py -m build --outdir ../../dist
```

### 3. 部署 Agent

```bash
# 部署（包名自动从 WHL 解析）
agent-runtime-manager agent deploy "E:/code/agent-runtime/src/manager/examples/dist/my_agent-1.0.0-py3-none-any.whl"

# 查看部署列表
agent-runtime-manager agent list

# 查看部署详情
agent-runtime-manager agent get <deployment_id>

# 删除部署
agent-runtime-manager agent delete <deployment_id>
```

## CLI 使用

### Agent 命令

```bash
# 部署 Agent（自动解析包名）
agent-runtime-manager agent deploy <whl_path> [--port PORT]

# 查询列表
agent-runtime-manager agent list [--status STATUS]

# 获取详情
agent-runtime-manager agent get <deployment_id>

# 删除部署
agent-runtime-manager agent delete <deployment_id>
```

### Plugin 命令

```bash
# 部署 Plugin
agent-runtime-manager plugin deploy <whl_path> [--port PORT]

# 查询列表
agent-runtime-manager plugin list [--status STATUS]

# 获取详情
agent-runtime-manager plugin get <deployment_id>

# 删除部署
agent-runtime-manager plugin delete <deployment_id>
```

## SDK 使用

```python
from openjiuwen_runtime.management.sdk import DeploymentManager

manager = DeploymentManager()

# 部署 Agent（包名自动解析）
result = await manager.deploy_agent(
    whl_path="./my_agent-1.0.0-py3-none-any.whl",
    port=8090
)

# 查询列表
deployments = await manager.list_deployments(
    deployment_type=DeploymentType.AGENT,
    status=DeploymentStatus.RUNNING
)

# 获取详情
deployment = await manager.get_deployment(deployment_id)

# 删除部署
await manager.delete_deployment(deployment_id)
```

## WHL 包规范

### 命名规范

```
{package_name}-{version}-{python_tag}-{abi_tag}-{platform_tag}.whl

示例:
my_agent-1.0.0-py3-none-any.whl
weather_plugin-2.1.0-py3-none-any.whl
```

### 目录结构

```
my_agent/
├── my_agent/              # ✅ 包子目录（必须）
│   ├── __init__.py
│   └── __main__.py        # ✅ 主入口文件（必须）
└── setup.py              # ✅ 打包配置（必须）
```

### __main__.py 要求

```python
import argparse

def main():
    # 1. 必须解析 --host 和 --port 参数
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    # 2. 必须实现长期运行的服务
    # 例如：FastAPI、Flask 等 HTTP 服务器
    run_server(host=args.host, port=args.port)

if __name__ == "__main__":
    main()
```

### setup.py 示例

```python
from setuptools import setup, find_packages

setup(
    name="my_agent",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
    ],
    python_requires=">=3.8",
)
```

## 虚拟环境管理

### 目录结构

```
venvs/
├── agent_20250129_abc123/     # Agent 部署虚拟环境
│   ├── Scripts/python.exe     # Windows
│   ├── Lib/site-packages/     # 已安装的包
│   └── pyvenv.cfg
└── plugin_20250129_def456/    # Plugin 部署虚拟环境
    ├── bin/python             # Linux/Mac
    └── ...
```

### 自动清理

- 部署成功后，虚拟环境会保留直到部署被删除
- 部署失败时，虚拟环境会自动清理
- 删除部署时，虚拟环境会自动清理

## 配置选项

### 环境变量 (.env)

```bash
# MySQL 数据库
DB_HOST=124.71.229.79
DB_PORT=33306
DB_USER=root
DB_PASSWORD=root
DB_NAME=jiuwen_runtime

# 虚拟环境
V_ENVS_ROOT=./venvs    # 虚拟环境根目录（默认: ./venvs）
```

## 项目架构

```
Agent Runtime Manager
├── sdk/                    # Manager SDK（核心共享组件）
│   ├── manager.py          # DeploymentManager - 部署管理核心
│   ├── deployer/           # LocalSubprocessDeployer - WHL 包部署器
│   ├── database/           # MySQLDatabase - 数据持久化
│   ├── models/             # Deployment/DeploymentDB - 数据模型
│   └── utils/              # 工具类
│       ├── venv_manager.py      # 虚拟环境管理
│       ├── whl_parser.py        # WHL 包名解析
│       ├── port_manager.py      # 端口分配
│       └── id_generator.py      # ID 生成
├── cli/                    # CLI 命令行工具
│   └── src/main.py         # Click 命令（agent/plugin deploy/list/get/delete）
└── server/                 # REST API Server（预留）
```

## 开发指南

### 构建示例包

```bash
cd examples/my_agent
py -m build --outdir ../../dist
```

### 运行测试

```bash
cd cli
agent-runtime-manager agent deploy "../examples/dist/my_agent-1.0.0-py3-none-any.whl"
```

## 常见问题

### 1. Editable 安装问题

**症状**: 修改代码后仍然使用旧版本

**解决**:
```bash
cd cli
rm -rf .venv/Lib/site-packages/openjiuwen_runtime
uv pip install -e ../sdk
```

### 2. WHL 包结构错误

**症状**: `No module named xxx`

**解决**: 确保 WHL 包内有正确的包子目录结构

```bash
# 验证 WHL 包内容
python -m zipfile -l my_agent-1.0.0-py3-none-any.whl
```

### 3. 进程立即退出

**症状**: 部署后进程很快退出

**解决**: `__main__.py` 必须实现长期运行的服务（如 HTTP 服务器）

## 依赖项

### SDK 依赖
- `sqlalchemy>=2.0.0` - ORM 框架
- `pymysql>=1.0.0` - MySQL 驱动
- `pydantic>=2.0.0` - 数据验证
- `cryptography>=42.0.0` - 加密工具

### CLI 依赖
- `click>=8.0.0` - CLI 框架
- `python-dotenv>=1.0.0` - 环境变量
- `fastapi>=0.100.0` - Web 框架（Server 预留）
