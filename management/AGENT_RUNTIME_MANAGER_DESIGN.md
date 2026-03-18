# Agent Runtime Manager 设计文档

**版本**: v2.0
**更新时间**: 2026-01-29
**状态**: 设计草案

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 核心架构](#2-核心架构)
- [3. 数据模型](#3-数据模型)
- [4. API 设计](#4-api-设计)
- [5. CLI 设计](#5-cli-设计)
- [6. 使用示例](#6-使用示例)
- [7. 详细设计](#7-详细设计)
- [8. 虚拟环境管理](#8-虚拟环境管理)
- [附录](#附录)

---

## 1. 项目概述

### 1.1 定位

**Agent Runtime Manager** 是 openjiuwen-runtime-sdk 的部署管理系统，提供：

- **Server 模式**: RESTful API 供 AgentStudio 调用，实现 Agent/Plugin 的云端部署管理
- **CLI 模式**: 命令行工具实现本地 Agent/Plugin 的部署管理
- **SDK 层**: 统一的部署管理功能实现，供 Server 和 CLI 共用

### 1.2 核心功能

| 功能模块 | Server | CLI | 说明 |
|---------|--------|-----|------|
| 部署 Agent | ✅ | ✅ | Server: JSON配置（低码）→ AgentConverter转Python<br>CLI: Python文件（高码）→ Manager SDK打包WHL |
| 部署 Plugin | ❌ | ✅ | Python文件（高码）→ Manager SDK打包WHL + 虚拟环境 + python -m 运行 |
| 查询列表 | ✅ | ✅ | 获取已部署的 Agent/Plugin 列表 |
| 查询详情 | ✅ | ✅ | 获取单个 Agent/Plugin 的详细信息 |
| 删除部署 | ✅ | ✅ | 停止并删除部署（含虚拟环境清理） |

### 1.3 核心设计原则

1. **虚拟环境隔离**：每个部署使用独立的虚拟环境，完全隔离依赖
2. **WHL包部署**：使用标准 Python wheel 包格式，通过 `python -m package_name` 运行
3. **统一打包逻辑**：Manager SDK 提供 Python 文件到 WHL 包的统一打包功能
4. **文件上传方式**：调用者直接上传文件，Server 负责存储到 OSS 和数据库

---

## 2. 核心架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Agent Runtime Manager                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────┐    ┌────────────────────────────┐  │
│  │       Server Layer         │    │        CLI Layer           │  │
│  │    (FastAPI REST API)      │    │   (Click Commands)         │  │
│  │                            │    │                            │  │
│  │  ┌──────────┐              │    │  $ agent-runtime agent    │  │
│  │  │/agents   │              │    │    deploy agent.py      │  │
│  │  └──────────┘              │    │  $ agent-runtime plugin   │  │
│  │                            │    │    deploy plugin.py     │  │
│  │  POST /agents/deploy       │    │                            │  │
│  │  GET  /agents              │    │                            │  │
│  │  DELETE /agents/{id}       │    │                            │  │
│  └────────────┬───────────────┘    └────────────┬───────────────┘  │
│               │                                 │                   │
│               └────────────┬────────────────────┘                   │
│                            ↓                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Manager SDK                              │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │         DeploymentManager                           │   │   │
│  │  │  - package_python_to_whl(py_file) → WHL路径        │   │   │
│  │  │  - deploy_agent(py_file, ...)                      │   │   │
│  │  │  - deploy_plugin(py_file, ...)                     │   │   │
│  │  │  - list_deployments()                              │   │   │
│  │  │  - get_deployment(id)                              │   │   │
│  │  │  - delete_deployment(id)                           │   │   │
│  │  └──────────────────────────┬────────────────────────────┘   │   │
│  └─────────────────────────────┼─────────────────────────────────┘   │
│                                ↓                                     │
│           ┌─────────────────────────────────────────────────────┐    │
│           │           runtime-manager Deployers                 │    │
│           │                                                     │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ LocalSubprocessDeployer                      │   │    │
│           │  │   1. create_venv(deployment_id)             │   │    │
│           │  │   2. install_whl(venv_path, whl_path)       │   │    │
│           │  │   3. subprocess.Popen([venv_python, -m,     │   │    │
│           │  │                      package_name,          │   │    │
│           │  │                      --host, --port])        │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ LocalThreadDeployer                         │   │    │
│           │  │   threading.Thread(target=run_agent)        │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ KubernetesDeployer                           │   │    │
│           │  │   k8s pod: python -m package_name            │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ DockerDeployer                              │   │    │
│           │  │   docker run: python -m package_name        │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           └─────────────────────────────────────────────────────┘    │
│                                  │ execute / load                    │
│                                  ↓                                   │
│           ┌─────────────────────────────────────────────────────┐    │
│           │         Virtual Environments (Per Deployment)        │    │
│           │         (每个部署独立的虚拟环境)                       │    │
│           │                                                     │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ venvs/agent_20250128_abc123/                │   │    │
│           │  │   ├── bin/python (or Scripts/python.exe)    │   │    │
│           │  │   ├── lib/site-packages/                    │   │    │
│           │  │   │   ├── my_agent_package/                 │   │    │
│           │  │   │   │   └── __main__.py                   │   │    │
│           │  │   │   └── dependencies...                   │   │    │
│           │  │   └── pyvenv.cfg                            │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           │                                                     │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ venvs/plugin_20250128_def456/               │   │    │
│           │  │   ├── bin/python (or Scripts/python.exe)    │   │    │
│           │  │   ├── lib/site-packages/                    │   │    │
│           │  │   │   ├── my_plugin_package/                │   │    │
│           │  │   │   │   └── __main__.py                   │   │    │
│           │  │   │   └── dependencies...                   │   │    │
│           │  │   └── pyvenv.cfg                            │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           └─────────────────────────────────────────────────────┘    │
│                                  │ imports                            │
│                                  ↓                                   │
│           ┌─────────────────────────────────────────────────────┐    │
│           │        openjiuwen-runtime-sdk (WHL包依赖)            │    │
│           │                                                     │    │
│           │  ┌─────────────────────────────────────────────┐   │    │
│           │  │ AgentApp, PluginApp, BaseApp                │   │    │
│           │  │ (打包在WHL中，部署时安装到虚拟环境)             │   │    │
│           │  └─────────────────────────────────────────────┘   │    │
│           └─────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              External Services                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │   │
│  │  │  OSS Storage │  │  Database    │  │ WHL Packages │      │   │
│  │  │  (可选存储)  │  │  (部署记录)  │  │  (用户提供)  │      │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Server工作时序 (Agent低码部署)**:
```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   Agent     │       │   Server    │       │  Manager    │       │  Deployer   │
│  Studio     │       │  (FastAPI)  │       │    SDK      │       │  + VenvMgr  │
└──────┬──────┘       └──────┬──────┘       └──────┬──────┘       └──────┬──────┘
       │                    │                      │                     │
       │  POST /agents/deploy (multipart/form-data)                    │
       │  file: <binary JSON config>               │                    │
       │  package_name: "my_agent"                 │                    │
       ├──────────────────> │                      │                    │
       │                    │                      │                    │
       │                    │  AgentConverter: JSON → Python         │                    │
       │                    │  保存Python文件到本地                      │                    │
       │                    │                      │                    │
       │                    │  deploy_agent(       │                    │
       │                    │    python_file_path  │                    │
       │                    │    package_name      │                    │
       │                    │  )                   │                    │
       │                    │─────────────────────>│                    │
       │                    │                      │                    │
       │                    │                      │  package_python_to_whl()
       │                    │                      │  [内部打包WHL]        │
       │                    │                      │                    │
       │                    │                      │  create_venv(      │
       │                    │                      │    deployment_id   │
       │                    │                      │  )                 │
       │                    │                      │───────────────────>│
       │                    │                      │                    │
       │                    │                      │  install_whl(      │
       │                    │                      │    venv_path,      │
       │                    │                      │    whl_path        │
       │                    │                      │  )                 │
       │                    │                      │<───────────────────┘
       │                    │                      │                    │
       │                    │                      │  subprocess.Popen( │
       │                    │                      │    [venv_python,    │
       │                    │                      │     "-m",          │
       │                    │                      │     package_name,  │
       │                    │                      │     "--host",      │
       │                    │                      │     "--port"]      │
       │                    │                      │  )                 │
       │                    │                      │───────────────────>│
       │                    │                      │                    │
       │                    │                      │         Agent运行    │
       │                    │<─────────────────────┘                    │
       │                    │  {status: success,   │                    │
       │                    │   data}              │                    │
       │<───────────────────┘                      │                    │
```

**CLI工作时序 (Agent/Plugin高码部署)**:
```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│    用户      │       │     CLI     │       │  Manager    │       │  Deployer   │
└──────┬──────┘       └──────┬──────┘       └──────┬──────┘       └──────┬──────┘
       │                    │                      │                     │
       │  $ agent-runtime agent deploy agent.py  │                    │
       ├──────────────────> │                      │                    │
       │                    │                      │                    │
       │                    │  deploy_agent(       │                    │
       │                    │    python_file_path  │                    │
       │                    │  )                   │                    │
       │                    │─────────────────────>│                    │
       │                    │                      │                    │
       │                    │                      │  package_python_to_whl()
       │                    │                      │  [内部打包WHL]        │
       │                    │                      │                    │
       │                    │                      │  [后续流程同Server]  │
       │                    │                      │───────────────────>│
       │                    │<─────────────────────┘                    │
       │  {status: success, data}                 │                    │
       │<───────────────────┘                      │                    │
```

**部署流程详解**:

**Agent 部署流程（Server API，低码方式）**:
1. **AgentStudio 上传 JSON 配置** → 通过 multipart/form-data 上传 JSON 配置文件
2. **Server AgentConverter** → 将 JSON 配置转换为 Python 文件
3. **Manager SDK.deploy_agent()** → 接收 Python 文件路径
4. **Manager SDK.package_python_to_whl()** → 内部打包 Python 文件为 WHL 包
5. **Manager SDK 调用 Deployer**:
   - **VirtualEnvironmentManager.create_venv()** → 创建独立虚拟环境
   - **VirtualEnvironmentManager.install_whl()** → 在虚拟环境中安装 WHL 包
   - **LocalSubprocessDeployer.deploy()** → 使用虚拟环境Python执行 `python -m package_name`
6. **Agent 独立运行** → 完全隔离的依赖环境

**Agent/Plugin 部署流程（CLI，高码方式）**:
1. **用户提供 Python 文件** → 直接提供本地 Python 文件路径
2. **CLI 调用 Manager SDK** → 传入 Python 文件路径
3. **Manager SDK.package_python_to_whl()** → 内部打包 Python 文件为 WHL 包
4. **Manager SDK 调用 Deployer** → 同 Server 流程步骤 5-6

**Plugin 部署流程（CLI，仅支持 Python 文件）**:
1. **用户提供 Python 文件** → 直接提供本地 Python 文件路径
2. **CLI 调用 Manager SDK** → 传入 Python 文件路径
3. **Manager SDK.package_python_to_whl()** → 内部打包 Python 文件为 WHL 包
4. **Manager SDK 调用 Deployer** → 同 Agent 流程步骤 5-6

**关键设计点**:
- **依赖隔离**: 每个部署有独立的虚拟环境，避免依赖冲突
- **标准化分发**: 使用 Python 标准 WHL 包格式
- **模块运行**: 通过 `python -m package_name` 方式运行，符合 Python 最佳实践
- **统一打包逻辑**: Manager SDK 提供 `package_python_to_whl()` 统一处理 Python 文件到 WHL 的转换
- **文件存储**: Server 负责将文件上传到 OSS，便于后续访问和管理
- **数据持久化**: 部署信息包含 OSS URL，保存到数据库中
- **Agent vs Plugin**: Agent 支持 Server 低码部署，Plugin 仅支持 CLI Python 文件部署

### 2.3 进程/线程模型

#### 2.3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           共享数据库                                 │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  部署记录 (deployment_id, pid/thread_id, port, status, ...)│   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
     │ Manager SDK       │ Manager SDK               │ Manager SDK
     │                   │                           │
┌─────────────────┐ ┌─────────────────┐     ┌─────────────────┐
│   Server 主进程   │ │   CLI 主进程      │     │  守护进程 (Daemon)│
│  ┌───────────┐   │ │  ┌───────────┐   │     │  ┌───────────┐   │
│  │ FastAPI   │   │ │  │ Click CLI │   │     │  │ Thread    │   │
│  │ Server    │   │ │  │           │   │     │  │ Manager   │   │
│  └───────────┘   │ │  └───────────┘   │     │  └───────────┘   │
│  ┌───────────┐   │ │  ┌───────────┐   │     │  ┌───────────┐   │
│  │ Manager   │   │ │  │ Manager   │   │     │  │ Manager   │   │
│  │ SDK       │   │ │  │ SDK       │   │     │  │ SDK       │   │
│  └───────────┘   │ │  └───────────┘   │     │  └───────────┘   │
└─────────────────┘ └─────────────────┘     │           │       │
     ↓                    ↓                    │           │       │
     │ subprocess.Popen()│                    │           │       │
     └────────────────────┴────────────────────┘           │       │
                         │                                │       │
                         ↓                                │       │
              ┌─────────────────────┐                      │       │
              │   独立工作进程        │                      │       │
              │  ┌──────────┐       │                      │       │
              │  │Agent1.py │       │                      │       │
              │  │(PID:101) │       │                      │       │
              │  └──────────┘       │                      │       │
              │  ┌──────────┐       │                      │       │
              │  │Plugin1.py│       │                      │       │
              │  │(PID:102) │       │                      │       │
              │  └──────────┘       │                      │       │
              └─────────────────────┘                      │       │
                                                         │       │
                                                         │       │
                                                         ↓       │
                                              ┌─────────────────────┐
                                              │  Daemon 工作线程池   │
                                              │  ┌──────────┐       │
                                              │  │工作线程1  │       │
                                              │  │Agent2.py │       │
                                              │  └──────────┘       │
                                              │  ┌──────────┐       │
                                              │  │工作线程2  │       │
                                              │  │Plugin2.py│       │
                                              │  └──────────┘       │
                                              │  ┌──────────┐       │
                                              │  │工作线程N  │       │
                                              │  │PluginN.py│       │
                                              │  └──────────┘       │
                                              └─────────────────────┘

特点:
- 工作进程：完全独立，CLI/Server/Daemon 都可通过 PID 管理
- 工作线程：集中运行在 Daemon 进程中，统一管理
- Daemon 进程：独立守护进程，专门负责线程部署的生命周期管理
- 数据库：共享所有部署状态，供所有管理器查询
```

#### 2.3.2 Daemon 进程设计

**职责**:
- 创建和管理所有工作线程（LocalThreadDeployer）
- 监控工作线程状态，更新数据库
- 接收来自 CLI/Server 的管理指令
- 独立于 Server/CLI 运行，崩溃不影响工作进程

**启动方式**:
```bash
# 方式1: systemd 服务（推荐生产环境）
sudo systemctl start agent-runtime-daemon

# 方式2: 手动启动（开发测试）
agent-runtime-daemon start

# 方式3: Docker 容器
docker run -d agent-runtime-daemon
```

**通信机制**:
- CLI/Server 通过数据库与 Daemon 通信
- Daemon 定期轮询数据库获取新部署请求
- 状态更新通过数据库共享

#### 2.3.3 部署器选择策略

| 部署器 | 部署类型 | 适用场景 | 优点 | 缺点 |
|--------|---------|----------|------|------|
| LocalSubprocessDeployer | 独立进程 | 生产环境、重要服务 | 故障隔离、资源独立、崩溃不影响主进程 | 资源开销大 |
| LocalThreadDeployer | 线程 | 开发测试、轻量服务 | 资源占用少、启动快 | 崩溃可能影响主进程 |
| KubernetesDeployer | Pod | 云端部署 | 容器化、易扩展 | 需要 K8s 集群 |
| DockerDeployer | 容器 | 本地容器化部署 | 环境一致、易迁移 | 需要 Docker |

#### 2.3.4 关键设计原则

**管理器互通**:
- 工作进程：完全独立，所有管理器（CLI/Server/Daemon）都可通过 PID 管理
- 工作线程：运行在 Daemon 中，通过 Daemon 统一管理
- 数据库作为状态共享中心

**Daemon 守护进程**:
- 专门负责工作线程的创建和生命周期管理
- 独立运行，不依赖 Server 或 CLI
- 崩溃不影响工作进程，可独立重启

**混合部署**:
- 工作进程：由 CLI/Server 直接创建，完全隔离
- 工作线程：由 Daemon 统一管理，资源共享
- 根据应用重要性选择部署方式

**进程隔离**:
- LocalSubprocessDeployer: 每个部署运行在独立进程，互不影响
- 适合生产环境，故障隔离好

**资源效率**:
- LocalThreadDeployer: 多个部署运行在 Daemon 进程的不同线程
- 适合开发测试，资源占用少

**状态管理**:
- 数据库维护部署元数据（PID/Thread ID、端口、状态）
- Daemon 定期检查工作线程状态并更新数据库
- DELETE 操作通知 Daemon 终止工作线程

### 2.4 状态流转设计

#### 2.4.1 状态定义

| 状态 | 说明 | 触发条件 |
|------|------|----------|
| PENDING | 部署中 | 已创建部署记录，正在启动应用 |
| RUNNING | 运行中 | 应用已成功启动并正常运行 |
| STOPPED | 已停止 | 应用已停止（自然结束或异常终止） |
| FAILED | 失败 | 部署或启动失败 |

#### 2.4.2 状态流转图

```
                    部署请求
                       ↓
                    PENDING
                       ↓
                 启动成功？
                   ╱   ╲
                 是      否
                 ↓        ↓
              RUNNING  FAILED
                 ↓        ↓
            正常运行？  (记录失败原因)
              ╱   ╲
            是      否
            ↓        ↓
         RUNNING  STOPPED
  
```

#### 2.4.3 当前设计决策（最小化集 MVP）

**核心原则**: 当前版本**不提供**独立的 STOP/START 接口，仅提供 DELETE 接口

| 接口 | 功能 | 状态变化 |
|------|------|----------|
| POST `/api/v1/agents/deploy` | 部署 | → PENDING → RUNNING |
| DELETE `/api/v1/agents/{id}` | 删除 | RUNNING → STOPPED → 删除记录 |
| GET `/api/v1/agents` | 查询 | 不改变状态 |
| GET `/api/v1/agents/{id}` | 查询 | 不改变状态 |

**设计理由**:
1. **简化管理**: 部署失败或运行结束直接删除，无需保留历史记录
2. **快速迭代**: MVP 阶段聚焦核心部署功能，降低复杂度
3. **实际场景**: 大多数情况下，用户部署失败或运行结束会重新部署，不需要保留记录

#### 2.4.4 状态监控机制（按需检查）

**设计原则**: 懒加载/按需检查，不使用定期监控线程

**触发场景**: 查询接口（`GET /agents/{id}`、`GET /agents`、CLI 命令）调用时实时检查部署状态并更新数据库

**状态检查**:
- LocalSubprocessDeployer: 检查进程状态
- LocalThreadDeployer: 检查线程存活状态
- KubernetesDeployer: 查询 Pod 状态
- DockerDeployer: 查询容器状态

#### 2.4.5 DELETE 接口行为

**功能**: 停止应用 + 删除记录

**流程**: 调用 Deployer.stop() → 停止应用 → 删除数据库记录 → 清理临时文件

**状态变化**: `RUNNING` → `STOPPED` → `记录删除`

#### 2.4.6 未来扩展方向

**计划功能**（未来版本）:

| 功能 | 接口 | 状态变化 | 说明 |
|------|------|----------|------|
| 停止 | POST `/api/v1/agents/{id}/stop` | RUNNING → STOPPED | 停止应用，保留记录 |
| 启动 | POST `/api/v1/agents/{id}/start` | STOPPED → RUNNING | 从已停止状态重新启动 |
| 重启 | POST `/api/v1/agents/{id}/restart` | RUNNING → RUNNING | 重启应用 |

**扩展时的考虑**:
1. **状态验证**: START 接口只能从 STOPPED 状态调用
2. **资源管理**: 停止时保留记录，删除时才清理资源

#### 2.4.7 状态转换规则

| 当前状态 | 允许转换 | 接口 |
|----------|----------|------|
| 无 → PENDING | ✅ | POST `/api/v1/agents/deploy` |
| PENDING → RUNNING | ✅ | 自动（Deployer） |
| PENDING → FAILED | ✅ | 自动（Deployer） |
| RUNNING → STOPPED | ✅ | 自动（监控） |
| RUNNING → FAILED | ✅ | 自动（监控） |
| RUNNING → 已删除 | ✅ | DELETE `/api/v1/agents/{id}` |
| STOPPED → RUNNING | ❌ | 未来版本支持 |
| 已删除 → STOPPED | ❌ | 不可逆 |

#### 2.4.8 状态一致性保证

**并发控制**:
- 使用数据库事务保证状态更新原子性
- 防止重复部署（同一部署 ID）
- DELETE 操作加锁，防止并发删除

**错误恢复**:
- Deployer 异常时自动标记为 FAILED
- 监控线程定期检查状态一致性
- 提供 `/health` 接口用于健康检查

---

### 2.3 目录结构

```
agent-runtime/
├── src/
│   └── manager/                     # runtime-manager 组件
│       ├── cli/                     # CLI 子组件（只处理本地文件）
│       │   ├── pyproject.toml
│       │   └── src/
│       │       ├── __init__.py
│       │       └── main.py          # CLI 入口（基于 Click/Typer）
│       │
│       ├── server/                  # Server 子组件（负责 OSS 下载）
│       │   ├── pyproject.toml
│       │   └── src/
│       │       ├── __init__.py
│       │       ├── main.py          # FastAPI 应用
│       │       ├── config.py        # 配置管理
│       │       ├── oss/             # OSS 客户端（下载文件）
│       │       │   ├── __init__.py
│       │       │   ├── client.py    # OSS 客户端接口和实现
│       │       │   └── config.py    # OSS 配置
│       │       ├── converter/       # 配置文件转换器（low_code → Python）
│       │       │   ├── __init__.py
│       │       │   ├── agent_converter.py  # Agent 配置转换器
│       │       └── models/
│       │           ├── __init__.py
│       │           ├── request.py   # 请求模型（包含 OSS URL）
│       │           └── response.py  # 响应模型
│       │
│       └── sdk/                     # Manager SDK（只处理本地文件）
│           ├── pyproject.toml
│           └── src/
│               ├── __init__.py
│               ├── manager.py       # DeploymentManager 核心类
│               ├── deployer/        # 部署器实现
│               │   ├── __init__.py
│               │   ├── base.py      # BaseDeployer 抽象类
│               │   ├── local_subprocess.py  # LocalSubprocessDeployer
│               │   ├── local_thread.py      # LocalThreadDeployer
│               │   ├── kubernetes.py        # KubernetesDeployer
│               │   └── docker.py            # DockerDeployer
│               ├── database/        # 数据库抽象和模型
│               │   ├── __init__.py
│               │   ├── base.py      # DatabaseBackend 抽象类
│               │   ├── mysql.py     # MySQL 实现
│               │   ├── models.py    # ORM 模型
│               │   └── redis.py     # Redis 实现（可选）
│               ├── models/          # 数据模型
│               │   ├── __init__.py
│               │   ├── deployment.py # Deployment 模型
│               │   ├── enums.py      # 枚举定义
│               │   └── config.py     # 配置模型
│               └── utils/           # 工具函数
│                   ├── __init__.py
│                   ├── id_generator.py # ID 生成器
│                   └── port_manager.py # 端口管理
│
└── README.md
```

**目录说明:**

| 目录 | 说明 |
|------|------|
| `src/manager/cli/` | 命令行工具，只处理本地文件，不依赖 OSS |
| `src/manager/server/` | RESTful API 服务，接收 JSON 配置，转换后调用 Manager SDK |
| `src/manager/server/src/converter/` | Agent 配置文件转换器（low_code JSON → Python） |
| `src/manager/sdk/` | Manager SDK 核心库，只处理本地文件路径，管理部署生命周期 |

**关键设计原则:**

1. **Manager SDK 独立性**: 不依赖 runtime-sdk，提供统一的 Python 文件到 WHL 打包功能
2. **Server 职责**: 接收 JSON 配置 → AgentConverter 转 Python → 调用 Manager SDK
3. **CLI 职责**: 接收本地 Python 文件 → 调用 Manager SDK
4. **Deployer 在 SDK 中**: 所有部署器实现都在 Manager SDK 内部
5. **模块化**: deployer/, database/, models/, utils/ 清晰分离

---

## 3. 数据模型

### 3.1 Deployment 记录模型

```python
# agent-runtime/src/manager/sdk/src/models/deployment.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Deployment(BaseModel):
    """部署记录模型 (v2.1 - 支持租户隔离)"""

    deployment_id: str                    # 部署唯一 ID
    type: str                              # 部署类型: agent | plugin
    name: str                               # 部署名称（= 包名，用于 python -m 运行）
    status: str                            # 状态: pending | running | stopped | failed

    # 租户隔离字段 (v2.1 新增)
    user_id: str                           # 用户 ID
    space_id: str                          # 空间 ID（用户下可以有多个空间）

    # 部署信息
    url: Optional[str]                     # 服务访问 URL
    deployer_type: str                     # 部署器类型
    port: int                               # 服务端口
    pid: Optional[int]                      # 进程/线程 ID（如果适用）

    # v2.0 新增字段
    venv_path: Optional[str] = None        # 虚拟环境路径
    package_name: Optional[str] = None     # Python 包名
    whl_path: Optional[str] = None         # WHL 包路径

    # 时间戳
    created_at: str                        # 创建时间
    updated_at: str                        # 更新时间
    error_message: Optional[str] = None    # 错误信息
```

### 3.2 租户模型

```python
# agent-runtime/src/manager/sdk/src/models/tenant.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Space(BaseModel):
    """空间模型 - 用户下的逻辑隔离单位"""

    space_id: str                          # 空间唯一 ID
    user_id: str                           # 所属用户 ID
    name: str                              # 空间名称
    description: Optional[str] = None      # 空间描述

    # 配置
    max_deployments: int = 10              # 最大部署数量
    max_memory_mb: int = 4096              # 最大内存限制 (MB)

    # 时间戳
    created_at: str
    updated_at: str
```

**租户隔离说明**：
- **user_id**: 用户标识，从认证 token 中提取
- **space_id**: 空间标识，一个用户可以有多个空间（如：开发环境、测试环境、生产环境）
- **Server API**: 所有查询操作自动过滤 `user_id` 和 `space_id`，用户只能访问自己空间下的部署
- **CLI**: 管理员模式，无租户限制，可查看/删除所有用户的部署

### 3.2 请求/响应模型

```python
# agent-runtime/src/manager/server/src/models/request.py

from pydantic import BaseModel
from typing import Optional
from fastapi import UploadFile

class DeployAgentRequest(BaseModel):
    """部署 Agent 请求表单数据"""
    name: str                               # 部署名称（= 包名，用于打包和运行）
    deployer_type: str = "local_subprocess"    # 部署器类型
    port: Optional[int] = None             # 服务端口（可选，自动分配）

# Plugin 通过 CLI 部署，不需要 Server API 请求模型


# agent-runtime/src/manager/server/src/models/response.py

from pydantic import BaseModel
from typing import List, Optional

class ApiResponse(BaseModel):
    """统一响应格式"""
    status: str                            # success | error
    data: Optional[dict] = None            # 响应数据
    message: Optional[str] = None          # 错误信息

class DeploymentListResponse(BaseModel):
    """部署列表响应"""
    status: str
    data: List[dict]
```

---

## 4. API 设计

### 4.0 租户隔离机制

**认证方式**

所有 API 请求需要通过 HTTP Header 传递租户上下文：

```http
X-User-ID: user_123456
X-Space-ID: space_abc123
```

或者通过 JWT Token（推荐）：

```http
Authorization: Bearer <JWT_TOKEN>
```

JWT Token Payload 示例：

```json
{
  "user_id": "user_123456",
  "space_id": "space_abc123",
  "exp": 1735689600
}
```

**隔离规则**

| 操作 | Server API 行为 | CLI 行为（管理员） |
|------|-----------------|------------------|
| 部署 Agent | `user_id` + `space_id` 自动注入 | 无限制，可指定任意租户 |
| 查询列表 | 只返回当前 `user_id` + `space_id` 下的部署 | 返回所有用户的部署 |
| 获取详情 | 只能访问当前 `user_id` + `space_id` 下的部署 | 可访问所有部署 |
| 删除部署 | 只能删除当前 `user_id` + `space_id` 下的部署 | 可删除所有部署 |

**设计说明**：
- **Server API**: 面向普通用户，强制租户隔离，确保数据安全
- **CLI**: 面向系统管理员，无租户限制，用于运维和故障排查

**错误处理**

当用户尝试访问其他租户的部署时：

```json
{
  "detail": "Deployment {deployment_id} not found or access denied"
}
```

HTTP 状态码：`404 Not Found` （不暴露资源存在性）

### 4.1 Agent API

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/agents/deploy` | 部署 Agent（JSON 配置，低码方式） |
| GET | `/api/v1/agents` | 查询 Agent 列表 |
| GET | `/api/v1/agents/{deployment_id}` | 获取 Agent 详情 |
| DELETE | `/api/v1/agents/{deployment_id}` | 删除 Agent 部署 |

#### 4.1.1 部署 Agent

**请求**

```http
POST /api/v1/agents/deploy
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file` | File | ✅ | - | JSON 配置文件（低码配置） |
| `name` | string | ✅ | - | 部署名称（=包名，用于打包和运行） |
| `deployer_type` | string | ❌ | `local_subprocess` | 部署器类型 |
| `port` | integer | ❌ | `8090` | 服务端口 |

**请求示例**

```bash
curl -X POST "http://localhost:8001/api/v1/agents/deploy" \
  -F "file=@agent_config.json" \
  -F "name=my_agent" \
  -F "port=8090"
```

**成功响应** (HTTP 201)

```json
{
  "deployment_id": "agent_1772182334862_a27827d6",
  "type": "agent",
  "name": "my_agent",
  "status": "running",
  "url": "http://127.0.0.1:8090",
  "port": 8090
}
```

**错误响应** (HTTP 500)

```json
{
  "detail": "Deployment failed: Port 8090 already in use"
}
```

#### 4.1.2 查询 Agent 列表

**请求**

```http
GET /api/v1/agents
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `status` | string | ❌ | - | 过滤状态: `pending`, `running`, `stopped`, `failed` |

**请求示例**

```bash
# 查询所有 Agent
curl "http://localhost:8001/api/v1/agents"

# 只查询运行中的 Agent
curl "http://localhost:8001/api/v1/agents?status=running"
```

**成功响应** (HTTP 200)

```json
{
  "deployments": [
    {
      "deployment_id": "agent_1772182334862_a27827d6",
      "name": "my_agent",
      "status": "running",
      "url": "http://127.0.0.1:8090",
      "port": 8090
    },
    {
      "deployment_id": "agent_1772181938214_21255bb4",
      "name": "test_agent",
      "status": "stopped",
      "url": "http://127.0.0.1:8091",
      "port": 8091
    }
  ]
}
```

#### 4.1.3 获取 Agent 详情

**请求**

```http
GET /api/v1/agents/{deployment_id}
```

| 路径参数 | 类型 | 说明 |
|----------|------|------|
| `deployment_id` | string | 部署 ID |

**请求示例**

```bash
curl "http://localhost:8001/api/v1/agents/agent_1772182334862_a27827d6"
```

**成功响应** (HTTP 200)

```json
{
  "deployment_id": "agent_1772182334862_a27827d6",
  "name": "my_agent",
  "status": "running",
  "url": "http://127.0.0.1:8090",
  "port": 8090,
  "type": "agent",
  "created_at": "2026-02-27T17:52:15.123456",
  "updated_at": "2026-02-27T17:52:18.234567"
}
```

**错误响应** (HTTP 404)

```json
{
  "detail": "Deployment agent_1772182334862_a27827d6 not found"
}
```

#### 4.1.4 删除 Agent

**请求**

```http
DELETE /api/v1/agents/{deployment_id}
```

| 路径参数 | 类型 | 说明 |
|----------|------|------|
| `deployment_id` | string | 部署 ID |

**请求示例**

```bash
curl -X DELETE "http://localhost:8001/api/v1/agents/agent_1772182334862_a27827d6"
```

**成功响应** (HTTP 200)

```json
{
  "message": "Deployment agent_1772182334862_a27827d6 deleted"
}
```

**错误响应** (HTTP 404)

```json
{
  "detail": "Deployment agent_1772182334862_a27827d6 not found"
}
```

### 4.2 状态码说明

| HTTP 状态码 | 说明 |
|------------|------|
| `200 OK` | 请求成功 |
| `201 Created` | 部署成功创建 |
| `404 Not Found` | 部署不存在 |
| `500 Internal Server Error` | 服务器内部错误 |

### 4.3 健康检查

**请求**

```http
GET /health
```

**请求示例**

```bash
curl "http://localhost:8001/health"
```

**成功响应** (HTTP 200)

```json
{
  "status": "healthy"
}
```

### 4.4 部署状态说明

| 状态 | 说明 |
|------|------|
| `pending` | 部署中，正在创建虚拟环境和安装依赖 |
| `running` | 运行中，Agent 进程正常运行 |
| `stopped` | 已停止，Agent 进程已终止 |
| `failed` | 部署失败，虚拟环境已清理 |

### 4.5 错误响应格式

所有错误响应都遵循统一格式：

```json
{
  "detail": "错误描述信息"
}
```

**常见错误场景**

| 场景 | HTTP 状态码 | 错误信息示例 |
|------|------------|--------------|
| 部署不存在 | 404 | `Deployment {deployment_id} not found` |
| 端口已被占用 | 500 | `Deployment failed: Port {port} already in use` |
| 虚拟环境创建失败 | 500 | `Deployment failed: Failed to create virtual environment` |
| WHL 安装失败 | 500 | `Deployment failed: Failed to install WHL package` |

---

## 5. CLI 设计

### 5.1 命令结构

```bash
agent-runtime-manager [OPTIONS] COMMAND [ARGS]...

选项:
  --help                  显示帮助

命令:
  agent       Agent 管理
  plugin      Plugin 管理
```

**管理员模式**：
- CLI 默认以管理员身份运行，**不受租户隔离限制**
- 可查看/删除**所有用户**的部署
- 用于系统运维、故障排查和跨租户管理
- 与 Server API 的租户隔离机制不同，CLI 拥有完整权限

### 5.2 Agent 命令

```bash
# 部署 Agent（使用Python文件，SDK内部打包WHL）
agent-runtime-manager agent deploy PYTHON_FILE --name NAME [--port PORT]

# 查询 Agent 列表
agent-runtime-manager agent list [--status STATUS]

# 获取 Agent 详情
agent-runtime-manager agent get DEPLOYMENT_ID

# 删除 Agent
agent-runtime-manager agent delete DEPLOYMENT_ID
```

**部署选项说明**:
- `PYTHON_FILE`: Python文件路径（如 `./my_agent.py` 或 `./my_agent/__main__.py`）
- `--name`: 部署名称（= 包名，必需，用于打包和 python -m 运行）
- `--port`: 服务端口，默认自动分配（从8090开始）
- **SDK内部处理**: Manager SDK 自动将 Python 文件打包为 WHL 并部署

### 5.3 Plugin 命令

```bash
# 部署 Plugin（使用Python文件，SDK内部打包WHL）
agent-runtime-manager plugin deploy PYTHON_FILE --name NAME [--port PORT]

# 查询 Plugin 列表
agent-runtime-manager plugin list [--status STATUS]

# 获取 Plugin 详情
agent-runtime-manager plugin get DEPLOYMENT_ID

# 删除 Plugin
agent-runtime-manager plugin delete DEPLOYMENT_ID
```

**部署选项说明**:
- `--port`: 服务端口，默认自动分配（从8091开始）
- **SDK内部处理**: Manager SDK 自动将 Python 文件打包为 WHL 并部署

---

## 6. 使用示例

### 6.1 Server 使用示例

```bash
# 启动 Server
uvicorn agent_runtime_manager.server.main:app --host 0.0.0.0 --port 8000

# 部署 Agent（上传 JSON 配置文件）
curl -X POST http://localhost:8000/api/v1/agents/deploy \
  -F "file=@./agent_config.json" \
  -F "name=my_agent" \
  -F "port=8090"

# 查询 Agent 列表
curl http://localhost:8000/api/v1/agents

# 获取 Agent 详情
curl http://localhost:8000/api/v1/agents/{deployment_id}

# 删除 Agent
curl -X DELETE http://localhost:8000/api/v1/agents/{deployment_id}

# 注意：Plugin 部署和查询仅支持 CLI 方式
```

### 6.2 CLI 使用示例

```bash
# 部署 Agent（使用Python文件，SDK内部打包WHL）
agent-runtime-manager agent deploy ./my_agent.py --name my_agent --port 8090

# 部署 Plugin（使用Python文件，SDK内部打包WHL）
agent-runtime-manager plugin deploy ./my_plugin.py --name my_plugin --port 8091

# 查询 Agent 列表
agent-runtime-manager agent list

# 查询运行中的 Agent
agent-runtime-manager agent list --status running

# 获取详情
agent-runtime-manager agent get <deployment_id>

# 删除部署
agent-runtime-manager agent delete <deployment_id>
```

## 7. 详细设计

### 7.1 Manager SDK (`src/manager/sdk/`)

Manager SDK 是核心库，只处理本地文件，负责部署生命周期管理。

#### 7.1.1 DeploymentManager

```python
# agent-runtime/src/manager/sdk/src/manager.py

from typing import List, Optional, Dict, Any
from enum import Enum

class DeploymentType(str, Enum):
    """部署类型"""
    AGENT = "agent"
    PLUGIN = "plugin"

class DeploymentStatus(str, Enum):
    """部署状态"""
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"

class DeploymentManager:
    """
    部署管理器

    负责管理 Agent/Plugin 的部署生命周期。

    工作流程:
    1. 接收本地 Python 文件路径（CLI 直接提供或 Server AgentConverter 生成）
    2. 内部调用 package_python_to_whl() 打包为 WHL
    3. 使用 Deployer 启动应用运行 WHL 包
    4. 保存部署记录到数据库
    5. 管理部署生命周期（停止、查询、删除）

    注意:
    - Manager SDK 与 runtime-sdk 完全无关
    - Manager SDK 处理本地 Python 文件，内部自动打包为 WHL
    - CLI 直接传入 Python 文件，Server 通过 AgentConverter 生成 Python 文件
    """

    def __init__(
        self,
        database_backend: "DatabaseBackend",
        default_deployer_type: str = "local_subprocess",
    ):
        """初始化部署管理器"""
        pass

    def package_python_to_whl(
        self,
        python_file_path: str,
        name: str,
        temp_dir: Optional[str] = None
    ) -> str:
        """
        将 Python 文件打包为 WHL 包

        Args:
            python_file_path: Python 文件路径（.py 文件或包含 __main__.py 的目录）
            name: 包名（用于打包 WHL 和 python -m 运行）
            temp_dir: 临时目录（可选，默认使用系统临时目录）

        Returns:
            生成的 WHL 包路径

        工作流程:
        1. 检测 Python 文件类型（单文件或目录）
        2. 创建临时打包目录结构
        3. 生成 setup.py/pyproject.toml 配置
        4. 调用 `python -m build` 打包 WHL
        5. 返回 WHL 包路径
        """
        pass

    async def deploy_agent(
        self,
        python_file_path: str,
        name: str,
        deployer_type: str = None,
        port: Optional[int] = None,
        **deployer_kwargs
    ) -> Dict[str, Any]:
        """
        部署 Agent

        Args:
            python_file_path: 本地 Python 文件路径（CLI 直接提供或 Server AgentConverter 生成）
            name: 部署名称（= 包名，用于打包和 python -m 运行）
            deployer_type: 部署器类型
            port: 服务端口
            **deployer_kwargs: 其他部署参数

        Returns:
            部署信息
        """
        # 内部流程:
        # 1. whl_path = self.package_python_to_whl(python_file_path, name)
        # 2. 调用 Deployer 部署（使用 name 作为包名）
        pass

    async def deploy_plugin(
        self,
        python_file_path: str,
        name: str,
        deployer_type: str = None,
        port: Optional[int] = None,
        **deployer_kwargs
    ) -> Dict[str, Any]:
        """
        部署 Plugin

        Args:
            python_file_path: 本地 Python 文件路径
            name: 部署名称（= 包名，用于打包和 python -m 运行）
            deployer_type: 部署器类型
            port: 服务端口
            **deployer_kwargs: 其他部署参数

        Returns:
            部署信息
        """
        # 内部流程与 deploy_agent 相同
        pass

    async def list_deployments(
        self,
        deployment_type: Optional[DeploymentType] = None,
        status: Optional[DeploymentStatus] = None,
    ) -> List[Dict[str, Any]]:
        """查询部署列表"""
        pass

    async def get_deployment(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """获取部署详情"""
        pass

    async def delete_deployment(self, deployment_id: str) -> bool:
        """删除部署"""
        pass
```

#### 7.1.2 Deployer 设计与实现

**设计原则**: Deployer 负责以不同方式启动 Python 应用运行 AgentApp/PluginApp 文件。

**支持的部署器类型**:
1. **LocalSubprocessDeployer** - 使用 subprocess.Popen 启动独立 Python 进程
2. **LocalThreadDeployer** - 使用 threading.Thread 在当前进程中启动线程
3. **KubernetesDeployer** - 在 K8s 集群中创建 Pod 运行 Python 容器
4. **DockerDeployer** - 使用 Docker 容器运行 Python 应用

##### 7.1.2.1 Deployer 基类 (runtime-manager)

```python
# agent-runtime/src/manager/sdk/src/deployer/base.py

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from enum import Enum


class DeploymentStatus(str, Enum):
    """部署状态"""
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class Deployer(ABC):
    """
    Deployer 抽象基类

    负责以不同方式（进程/线程/容器）启动 Python 应用运行 AgentApp/PluginApp。

    注意：Deployer 不直接处理用户提供的 Python 文件，WHL 包的生成和解析由 Manager SDK 内部处理。
    """

    @abstractmethod
    async def deploy(
        self,
        whl_path: str,  # WHL 包路径（由 Manager SDK 内部生成）
        name: str,  # 部署名称=包名（由 Manager SDK 从 Python 文件或用户输入传入）
        deployment_id: str,
        port: int,
        host: str = "127.0.0.1",
        **kwargs
    ) -> Dict[str, Any]:
        """
        部署应用

        Args:
            whl_path: WHL 包路径（由 Manager SDK 内部打包生成）
            name: 部署名称=包名（用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务主机
            **kwargs: 其他部署参数

        Returns:
            部署信息字典，包含:
            - deployment_id: 部署 ID
            - url: 服务访问地址
            - status: 部署状态
            - pid: 进程/线程/容器 ID (如果适用)
        """
        pass

    @abstractmethod
    async def stop(self, deployment_id: str) -> bool:
        """
        停止部署

        Args:
            deployment_id: 部署唯一标识

        Returns:
            是否成功停止
        """
        pass

    @abstractmethod
    async def get_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """
        获取部署状态

        Args:
            deployment_id: 部署唯一标识

        Returns:
            当前部署状态，如果部署不存在则返回 None
        """
        pass
```

##### 7.1.2.2 LocalSubprocessDeployer 实现

```python
# agent-runtime/src/manager/sdk/src/deployer/local_subprocess.py

import subprocess
from typing import Dict, Any
from .base import Deployer, DeploymentStatus


class LocalSubprocessDeployer(Deployer):
    """
    本地进程部署器

    使用 subprocess.Popen 启动独立 Python 进程。
    """

    def __init__(self, python_executable: str = "python3"):
        """初始化部署器"""
        pass

    async def deploy(
        self,
        whl_path: str,
        package_name: str,
        deployment_id: str,
        port: int,
        host: str = "127.0.0.1",
        **kwargs
    ) -> Dict[str, Any]:
        """
        启动 Python 子进程部署应用

        Args:
            whl_path: WHL 包路径
            package_name: Python 包名（自动解析，用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务主机
            **kwargs: 其他部署参数

        Returns:
            部署信息字典
        """
        pass

    async def stop(self, deployment_id: str) -> bool:
        """停止子进程"""
        pass

    async def get_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """获取部署状态"""
        pass
```

##### 7.1.2.3 LocalThreadDeployer 实现

```python
# agent-runtime/src/manager/sdk/src/deployer/local_thread.py

import threading
from typing import Dict, Any, Optional
from .base import Deployer, DeploymentStatus


class LocalThreadDeployer(Deployer):
    """
    本地线程部署器

    使用 threading.Thread 在当前进程中启动 Python 线程。
    """

    def __init__(self, python_executable: str = "python3"):
        """初始化部署器"""
        self.python_executable = python_executable
        self.threads: Dict[str, threading.Thread] = {}
        pass

    async def deploy(
        self,
        whl_path: str,
        package_name: str,
        deployment_id: str,
        port: int,
        host: str = "127.0.0.1",
        **kwargs
    ) -> Dict[str, Any]:
        """
        启动 Python 线程部署应用

        Args:
            whl_path: WHL 包路径
            package_name: Python 包名（自动解析，用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务地址
            **kwargs: 其他参数

        Returns:
            部署结果字典
        """
        pass

    async def stop(self, deployment_id: str) -> bool:
        """停止线程"""
        pass

    async def get_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """获取部署状态"""
        pass
```

##### 7.1.2.4 KubernetesDeployer 实现

```python
# agent-runtime/src/manager/sdk/src/deployer/kubernetes.py

from typing import Dict, Any, Optional
from .base import Deployer, DeploymentStatus


class KubernetesDeployer(Deployer):
    """
    Kubernetes 部署器

    在 K8s 集群中创建 Pod 运行 Python 容器。
    """

    def __init__(
        self,
        kubeconfig_path: Optional[str] = None,
        namespace: str = "default",
        image: str = "python:3.10-slim",
    ):
        """初始化部署器"""
        self.namespace = namespace
        self.image = image
        pass

    async def deploy(
        self,
        whl_path: str,
        package_name: str,
        deployment_id: str,
        port: int,
        host: str = "0.0.0.0",
        **kwargs
    ) -> Dict[str, Any]:
        """
        在 K8s 中创建 Pod 部署应用

        Args:
            whl_path: WHL 包路径
            package_name: Python 包名（自动解析，用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务地址
            **kwargs: 其他参数（如资源限制、环境变量等）

        Returns:
            部署结果字典，包含 pod_name, pod_status 等
        """
        pass

    async def stop(self, deployment_id: str) -> bool:
        """删除 K8s Pod"""
        pass

    async def get_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """获取 Pod 状态"""
        pass
```

##### 7.1.2.5 DockerDeployer 实现

```python
# agent-runtime/src/manager/sdk/src/deployer/docker.py

from typing import Dict, Any, Optional
from .base import Deployer, DeploymentStatus


class DockerDeployer(Deployer):
    """
    Docker 部署器

    使用 Docker 容器运行 Python 应用。
    """

    def __init__(
        self,
        image: str = "python:3.10-slim",
        docker_host: Optional[str] = None,
    ):
        """初始化部署器"""
        self.image = image
        self.docker_host = docker_host
        pass

    async def deploy(
        self,
        whl_path: str,
        package_name: str,
        deployment_id: str,
        port: int,
        host: str = "0.0.0.0",
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用 Docker 容器部署应用

        Args:
            whl_path: WHL 包路径
            package_name: Python 包名（自动解析，用于 python -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务地址
            **kwargs: 其他参数（如环境变量、挂载卷等）

        Returns:
            部署结果字典，包含 container_id, container_status 等
        """
        pass

    async def stop(self, deployment_id: str) -> bool:
        """停止并删除容器"""
        pass

    async def get_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """获取容器状态"""
        pass
```

#### 7.1.3 Database Backend

```python
# agent-runtime/src/manager/sdk/src/database.py

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

class DatabaseBackend(ABC):
    """数据库后端抽象"""

    @abstractmethod
    async def create_deployment(self, deployment: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    async def get_deployment(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def list_deployments(
        self,
        deployment_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def update_deployment_status(self, deployment_id: str, status: str) -> bool:
        pass

    @abstractmethod
    async def delete_deployment(self, deployment_id: str) -> bool:
        pass


class MySQLDatabase(DatabaseBackend):
    """MySQL 数据库 (生产环境推荐)"""

    def __init__(self, host: str = "localhost", port: int = 3306,
                 database: str = "agent_runtime", user: str = "root",
                 password: str = ""):
        """初始化 MySQL 数据库连接"""
        pass

    async def create_deployment(self, deployment: Dict[str, Any]) -> str:
        """创建部署记录"""
        pass

    async def get_deployment(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """获取单个部署记录"""
        pass

    async def list_deployments(
        self,
        deployment_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询部署列表"""
        pass

    async def update_deployment_status(self, deployment_id: str, status: str) -> bool:
        """更新部署状态"""
        pass

    async def delete_deployment(self, deployment_id: str) -> bool:
        """删除部署记录"""
        pass
```

#### 7.1.4 Storage Backend

```python
# agent-runtime/src/manager/sdk/src/storage.py

from abc import ABC, abstractmethod
from typing import Optional

class StorageBackend(ABC):
    """本地文件存储后端抽象 (用于临时文件缓存)"""

    @abstractmethod
    async def save_temp_file(self, content: bytes, filename: str) -> str:
        """保存临时文件，返回本地路径"""
        pass

    @abstractmethod
    async def delete_temp_file(self, local_path: str) -> bool:
        """删除临时文件"""
        pass


class LocalStorageBackend(StorageBackend):
    """本地文件系统存储 (用于临时文件缓存)"""

    def __init__(self, temp_dir: str = "./temp"):
        """初始化存储后端"""
        pass

    async def save_temp_file(self, content: bytes, filename: str) -> str:
        """保存临时文件"""
        pass

    async def delete_temp_file(self, local_path: str) -> bool:
        """删除临时文件"""
        pass
```

**说明**:
- Storage Backend 仅用于本地临时文件管理
- Server 从 OSS 下载文件后使用 Storage Backend 缓存
- 不再提供 OSS 上传/下载功能（OSS 是外部独立服务）

---

### 7.2 Server (`src/manager/server/`)

Server 组件负责接收 JSON 配置文件，通过 AgentConverter 转换为 Python 文件后调用 Manager SDK。

#### 7.2.1 OSS Client

```python
# agent-runtime/src/manager/server/src/oss/client.py

from abc import ABC, abstractmethod
from typing import Optional
import os

class OSSClient(ABC):
    """
    OSS 客户端抽象

    负责将上传的文件存储到 OSS，并返回可访问的 URL。
    """

    @abstractmethod
    async def upload_file(self, local_file_path: str, object_key: str) -> str:
        """
        上传文件到 OSS

        Args:
            local_file_path: 本地文件路径
            object_key: OSS 对象键（如 deployments/xxx/agent.whl）

        Returns:
            OSS 文件 URL（可供后续访问）
        """
        pass

    @abstractmethod
    async def delete_file(self, object_key: str) -> bool:
        """
        从 OSS 删除文件

        Args:
            object_key: OSS 对象键

        Returns:
            是否删除成功
        """
        pass


class DefaultOSSClient(OSSClient):
    """
    默认 OSS 客户端实现

    支持标准 OSS 协议（如阿里云 OSS、腾讯云 COS 等）。
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
    ):
        """初始化 OSS 客户端"""
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket

    async def upload_file(self, local_file_path: str, object_key: str) -> str:
        """
        上传文件到 OSS

        Args:
            local_file_path: 本地文件路径
            object_key: OSS 对象键

        Returns:
            OSS 文件 URL
        """
        # 实现文件上传逻辑
        pass

    async def delete_file(self, object_key: str) -> bool:
        """
        从 OSS 删除文件

        Args:
            object_key: OSS 对象键

        Returns:
            是否删除成功
        """
        # 实现文件删除逻辑
        pass
```

**说明**:
- OSS Client 负责将用户上传的文件存储到 OSS
- 文件上传后返回 OSS URL，并保存到数据库中供后续访问
- 删除部署时，可以选择从 OSS 删除对应的文件
- 实际实现需要根据具体 OSS 服务提供商的 API 调整

#### 7.2.2 Agent Converter（配置文件转换器）

```python
# agent-runtime/src/manager/server/src/converter/agent_converter.py

from typing import Dict, Any
import json
import tempfile
import shutil


class AgentConverter:
    """
    Agent 配置文件转换器

    负责将 low_code 类型的 JSON 配置文件转换为 Python 文件。
    WHL 打包由 Manager SDK 统一处理。
    """

    async def convert_to_python(
        self,
        config_json: Dict[str, Any],
        name: str,
        output_dir: str
    ) -> str:
        """
        将 Agent 配置转换为 Python 文件

        Args:
            config_json: Agent 配置（JSON 格式）
            name: 包名（用于生成 Python 文件目录和后续打包）
            output_dir: 输出目录

        Returns:
            生成的 Python 文件路径（__main__.py）

        配置格式示例:
        {
            "app_name": "MyAgent",
            "app_description": "My AI agent",
            "framework": "agentscope",
            "init": {...},
            "query": {...},
            "shutdown": {...}
        }
        """
        app_name = config_json.get("app_name", "Agent")
        app_description = config_json.get("app_description", "")
        framework = config_json.get("framework", "agentscope")
        init_config = config_json.get("init", {})
        query_config = config_json.get("query", {})
        shutdown_config = config_json.get("shutdown", {})

        # 1. 生成 Python 代码
        python_code = self._generate_python_code(
            app_name, app_description, framework,
            init_config, query_config, shutdown_config
        )

        # 2. 创建包子目录并保存 Python 文件
        pkg_dir = Path(output_dir) / name
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # 写入 __main__.py
        (pkg_dir / "__main__.py").write_text(python_code, encoding='utf-8')
        (pkg_dir / "__init__.py").write_text("", encoding='utf-8')

        # 3. 返回 Python 文件路径（__main__.py 或包目录）
        python_file_path = str(pkg_dir / "__main__.py")

        return python_file_path

    def _generate_python_code(
        self,
        app_name: str,
        app_description: str,
        framework: str,
        init_config: Dict[str, Any],
        query_config: Dict[str, Any],
        shutdown_config: Dict[str, Any]
    ) -> str:
        """生成 Python 代码"""
        # 根据配置生成 Python 代码模板
        pass
```

**说明**:
- Agent Converter 仅处理 low_code 类型的 Agent 配置 
- Plugin 不支持 low_code，无需转换
- 转换器生成 Python 文件（包含 __main__.py 的包目录）
- WHL 打包由 Manager SDK 的 `package_python_to_whl()` 统一处理

#### 7.2.3 FastAPI

```python
# agent-runtime/src/manager/server/src/config.py

from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import os


# 加载 .env 配置文件（固定位置：manager 根目录）
_manager_root = Path(__file__).parent.parent.parent
_env_file = _manager_root / ".env"
load_dotenv(_env_file)


class Settings:
    """配置类（单例模式）"""

    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "agent_runtime")
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    OSS_ENDPOINT: str = os.getenv("OSS_ENDPOINT", "")
    OSS_BUCKET: str = os.getenv("OSS_BUCKET", "")
    OSS_ACCESS_KEY: str = os.getenv("OSS_ACCESS_KEY", "")
    OSS_SECRET_KEY: str = os.getenv("OSS_SECRET_KEY", "")


settings = Settings()
```

```python
# agent-runtime/src/manager/server/src/main.py

from fastapi import FastAPI, HTTPException, UploadFile
from typing import Optional

from agent_runtime_manager import DeploymentManager, DeploymentType
from agent_runtime_manager.oss import DefaultOSSClient
from agent_runtime_manager.database import MySQLDatabase
from .converter.agent_converter import AgentConverter
from .config import settings

app = FastAPI(
    title="Agent Runtime Manager API",
    description="Agent/Plugin 部署管理服务",
    version="1.0.0",
)

# 外部 OSS 服务客户端（Server 负责下载文件）
oss_client = DefaultOSSClient(
    endpoint=settings.OSS_ENDPOINT,
    access_key=settings.OSS_ACCESS_KEY,
    secret_key=settings.OSS_SECRET_KEY,
)
database = MySQLDatabase(
    host=settings.MYSQL_HOST,
    port=settings.MYSQL_PORT,
    database=settings.MYSQL_DATABASE,
    user=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD,
)
# Manager SDK 只处理本地文件
manager = DeploymentManager(
    database_backend=database,
)
# Agent 配置转换器
agent_converter = AgentConverter()


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ==================== Agent API ====================

@app.post("/api/v1/agents/deploy")
async def deploy_agent(
    file: UploadFile,
    name: str,
    deployer_type: str = "local_subprocess",
    port: int = 8090,
):
    """
    部署 Agent（JSON 配置，低码方式）

    工作流程:
    1. Server 接收上传的 JSON 配置文件
    2. Server 将文件保存到本地临时目录
    3. AgentConverter 将 JSON 转换为 Python 文件
    4. Server 调用 Manager SDK 传入 Python 文件路径和 name
    5. Manager SDK 内部将 Python 文件打包为 WHL 并部署
    """
    try:
        # 1. 保存上传的文件到本地临时目录
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            json_file_path = tmp_file.name

        # 2. 上传 JSON 配置到 OSS
        object_key = f"deployments/agent_configs/{file.filename}"
        oss_url = await oss_client.upload_file(json_file_path, object_key)

        # 3. 读取 JSON 配置并转换为 Python 文件
        with open(json_file_path, 'r', encoding='utf-8') as f:
            config_json = json.load(f)

        # AgentConverter: JSON → Python 文件
        python_file_path = await agent_converter.convert_to_python(
            config_json=config_json,
            name=name,
            output_dir=os.path.dirname(json_file_path)
        )

        # 4. Server 调用 Manager SDK（传入 Python 文件路径和 name）
        result = await manager.deploy_agent(
            python_file_path=python_file_path,
            name=name,
            deployer_type=deployer_type,
            port=port,
        )
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/agents")
async def list_agents(status: Optional[str] = None):
    """查询 Agent 列表"""
    deployments = await manager.list_deployments(
        deployment_type=DeploymentType.AGENT,
        status=status,
    )
    return {"status": "success", "data": deployments}


@app.get("/api/v1/agents/{deployment_id}")
async def get_agent(deployment_id: str):
    """获取 Agent 详情"""
    deployment = await manager.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"status": "success", "data": deployment}


@app.delete("/api/v1/agents/{deployment_id}")
async def delete_agent(deployment_id: str):
    """删除 Agent 部署"""
    success = await manager.delete_deployment(deployment_id)
    if not success:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"status": "success"}


# ==================== CLI Implementation ====================
# Plugin 部署和查询仅通过 CLI 方式支持

### 7.3 CLI (`src/manager/cli/`)

CLI 组件只处理本地文件，不涉及 OSS 下载。

```python
# agent-runtime/src/manager/cli/src/main.py

import click
import json
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

from agent_runtime_manager import DeploymentManager, DeploymentType, DeploymentStatus
from agent_runtime_manager.database import MySQLDatabase


# 加载 .env 配置文件（固定位置：manager 根目录）
_manager_root = Path(__file__).parent.parent.parent
_env_file = _manager_root / ".env"
load_dotenv(_env_file)


@click.group()
@click.pass_context
def cli(ctx):
    """Agent Runtime Manager CLI"""
    ctx.ensure_object(dict)

    # 从环境变量读取配置（由 load_dotenv 加载）
    database = MySQLDatabase(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE", "agent_runtime"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
    )
    # Manager SDK 只处理本地文件
    ctx.obj["manager"] = DeploymentManager(
        database_backend=database,
    )


# ==================== Agent 命令 ====================

@cli.group()
def agent():
    """Agent 管理"""
    pass


@agent.command()
@click.argument("python_file_path", type=click.Path(exists=True))  # 本地 Python 文件路径
@click.option("--name", help="部署名称（= 包名，必需）", required=True)
@click.option("--deployer-type", default="local_subprocess",
              type=click.Choice(["local_subprocess", "local_thread", "kubernetes", "docker"]),
              help="部署器类型")
@click.option("--port", default=8090, help="服务端口")
@click.pass_context
def deploy(ctx, python_file_path, name, deployer_type, port):
    """部署 Agent（使用本地 Python 文件，SDK 内部打包 WHL）"""
    manager = ctx.obj["manager"]

    async def _deploy():
        result = await manager.deploy_agent(
            python_file_path=python_file_path,
            name=name,
            deployer_type=deployer_type,
            port=port,
        )
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_deploy())


@agent.command()
@click.option("--status", type=click.Choice(["pending", "running", "stopped", "failed"]), help="过滤状态")
@click.pass_context
def list(ctx, status):
    """查询 Agent 列表"""
    manager = ctx.obj["manager"]

    async def _list():
        deployments = await manager.list_deployments(
            deployment_type=DeploymentType.AGENT,
            status=DeploymentStatus(status) if status else None,
        )
        click.echo(json.dumps(deployments, indent=2, ensure_ascii=False))

    asyncio.run(_list())


@agent.command()
@click.argument("deployment_id")
@click.pass_context
def get(ctx, deployment_id):
    """获取 Agent 详情"""
    manager = ctx.obj["manager"]

    async def _get():
        deployment = await manager.get_deployment(deployment_id)
        if deployment:
            click.echo(json.dumps(deployment, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Deployment {deployment_id} not found", err=True)

    asyncio.run(_get())


@agent.command()
@click.argument("deployment_id")
@click.pass_context
def delete(ctx, deployment_id):
    """删除 Agent"""
    manager = ctx.obj["manager"]

    async def _delete():
        success = await manager.delete_deployment(deployment_id)
        if success:
            click.echo(f"Deployment {deployment_id} deleted")
        else:
            click.echo(f"Deployment {deployment_id} not found", err=True)

    asyncio.run(_delete())


# ==================== Plugin 命令 ====================

@cli.group()
def plugin():
    """Plugin 管理"""
    pass


@plugin.command()
@click.argument("python_file_path", type=click.Path(exists=True))  # 本地 Python 文件路径
@click.option("--name", help="部署名称（= 包名，必需）", required=True)
@click.option("--deployer-type", default="local_subprocess",
              type=click.Choice(["local_subprocess", "local_thread", "kubernetes", "docker"]),
              help="部署器类型")
@click.option("--port", default=8091, help="服务端口")
@click.pass_context
def deploy(ctx, python_file_path, name, deployer_type, port):
    """部署 Plugin（使用本地 Python 文件，SDK 内部打包 WHL）"""
    manager = ctx.obj["manager"]

    async def _deploy():
        result = await manager.deploy_plugin(
            python_file_path=python_file_path,
            name=name,
            deployer_type=deployer_type,
            port=port,
        )
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_deploy())


@plugin.command()
@click.option("--status", type=click.Choice(["pending", "running", "stopped", "failed"]), help="过滤状态")
@click.pass_context
def list(ctx, status):
    """查询 Plugin 列表"""
    manager = ctx.obj["manager"]

    async def _list():
        deployments = await manager.list_deployments(
            deployment_type=DeploymentType.PLUGIN,
            status=DeploymentStatus(status) if status else None,
        )
        click.echo(json.dumps(deployments, indent=2, ensure_ascii=False))

    asyncio.run(_list())


@plugin.command()
@click.argument("deployment_id")
@click.pass_context
def get(ctx, deployment_id):
    """获取 Plugin 详情"""
    manager = ctx.obj["manager"]

    async def _get():
        deployment = await manager.get_deployment(deployment_id)
        if deployment:
            click.echo(json.dumps(deployment, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Deployment {deployment_id} not found", err=True)

    asyncio.run(_get())


@plugin.command()
@click.argument("deployment_id")
@click.pass_context
def delete(ctx, deployment_id):
    """删除 Plugin"""
    manager = ctx.obj["manager"]

    async def _delete():
        success = await manager.delete_deployment(deployment_id)
        if success:
            click.echo(f"Deployment {deployment_id} deleted")
        else:
            click.echo(f"Deployment {deployment_id} not found", err=True)

    asyncio.run(_delete())


if __name__ == "__main__":
    cli(obj={})
```

### 7.4 环境配置文件

**配置文件位置**: `agent-runtime/src/manager/.env`

CLI 和 Server 启动时自动从该位置读取配置，使用 `python-dotenv` 库加载。

```bash
# MySQL 数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=agent_runtime
MYSQL_USER=root
MYSQL_PASSWORD=

# 外部 OSS 服务配置（用于上传和存储文件）
OSS_ENDPOINT=
OSS_ACCESS_KEY=
OSS_SECRET_KEY=
OSS_BUCKET=

# 虚拟环境配置
V_ENVS_ROOT=./venvs
```

**依赖项**:

### Manager SDK (`src/manager/sdk/`)
```txt
# 数据库
sqlalchemy>=2.0.0
pymysql>=1.0.0

# 数据验证
pydantic>=2.0.0
```

### Server (`src/manager/server/`)
```txt
# Web 框架
fastapi>=0.100.0
uvicorn[standard]>=0.23.0

# OSS 客户端（文件上传）
oss2>=2.18.0  # 阿里云 OSS SDK，或其他 OSS SDK

# 配置管理
python-dotenv>=1.0.0

# 数据库（继承 SDK）
sqlalchemy>=2.0.0
pymysql>=1.0.0
```

### CLI (`src/manager/cli/`)
```txt
# 命令行框架
click>=8.0.0

# 配置管理
python-dotenv>=1.0.0

# 数据库（继承 SDK）
sqlalchemy>=2.0.0
pymysql>=1.0.0
```

### 可选依赖（根据部署器类型）
```txt
# Kubernetes 部署器
kubernetes>=28.0.0

# Docker 部署器
docker>=6.0.0
```

---

## 8. 虚拟环境管理

### 8.1 设计目标

**核心特性**：为每个部署创建独立的虚拟环境，实现完全的依赖隔离。

**解决的问题**：
1. **依赖冲突**：多个Agent使用不同版本的相同依赖时互不影响
2. **环境隔离**：每个Agent运行在干净的独立环境中
3. **清理便利**：删除部署时自动清理对应的虚拟环境

### 8.2 虚拟环境目录结构

```
agent-runtime/src/manager/
├── venvs/                           # 虚拟环境根目录
│   ├── agent_20250128_abc123/       # Agent部署虚拟环境
│   │   ├── bin/                     # Linux/Mac
│   │   │   ├── python               # 虚拟环境Python解释器
│   │   │   ├── pip                  # 虚拟环境pip
│   │   │   └── activate             # 激活脚本
│   │   │   └── ...                  # 其他可执行文件
│   │   ├── lib/                     # Linux/Mac
│   │   │   └── python3.X/
│   │   │       └── site-packages/   # 安装的包
│   │   │           ├── my_agent_package/
│   │   │           │   └── __main__.py
│   │   │           ├── openjiuwen_runtime_sdk/
│   │   │           └── ...          # 其他依赖
│   │   └── pyvenv.cfg               # 虚拟环境配置
│   │
│   ├── plugin_20250128_def456/      # Plugin部署虚拟环境
│   │   ├── Scripts/                 # Windows
│   │   │   ├── python.exe           # 虚拟环境Python解释器
│   │   │   ├── pip.exe              # 虚拟环境pip
│   │   │   └── activate.bat         # 激活脚本
│   │   │   └── ...                  # 其他可执行文件
│   │   ├── Lib/                     # Windows
│   │   │   └── site-packages/       # 安装的包
│   │   │       ├── my_plugin_package/
│   │   │       │   └── __main__.py
│   │   │       └── ...              # 其他依赖
│   │   └── pyvenv.cfg               # 虚拟环境配置
│   │
│   └── ...                          # 其他部署的虚拟环境
│
├── .env                             # 环境配置
├── cli/                             # CLI组件
├── server/                          # Server组件
└── sdk/                             # SDK组件
    └── src/
        └── utils/
            └── venv_manager.py      # 虚拟环境管理器
```

### 8.3 VirtualEnvironmentManager 设计

```python
# agent-runtime/src/manager/sdk/src/utils/venv_manager.py

import subprocess
import shutil
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class VirtualEnvironmentManager:
    """
    虚拟环境管理器

    负责为每个部署创建、管理和清理独立的虚拟环境。
    """

    def __init__(self, venvs_root: str = "./venvs"):
        """
        初始化虚拟环境管理器

        Args:
            venvs_root: 虚拟环境根目录路径
        """
        self.venvs_root = Path(venvs_root)
        self.venvs_root.mkdir(parents=True, exist_ok=True)

    def create_venv(self, deployment_id: str) -> Path:
        """
        为部署创建独立的虚拟环境

        Args:
            deployment_id: 部署ID，用作虚拟环境目录名

        Returns:
            虚拟环境路径

        Raises:
            RuntimeError: 虚拟环境创建失败
        """
        venv_path = self.venvs_root / deployment_id

        if venv_path.exists():
            logger.info(f"Virtual environment already exists: {venv_path}")
            return venv_path

        logger.info(f"Creating virtual environment: {venv_path}")

        try:
            # 使用python -m venv创建虚拟环境
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Virtual environment created successfully: {venv_path}")
            return venv_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create virtual environment: {e.stderr}")
            raise RuntimeError(f"Failed to create venv: {e}")

    def get_python_executable(self, deployment_id: str) -> Path:
        """
        获取虚拟环境中的Python可执行文件路径

        Args:
            deployment_id: 部署ID

        Returns:
            Python可执行文件路径
        """
        venv_path = self.venvs_root / deployment_id

        if sys.platform == "win32":
            # Windows: Scripts/python.exe
            python_path = venv_path / "Scripts" / "python.exe"
        else:
            # Linux/Mac: bin/python
            python_path = venv_path / "bin" / "python"

        if not python_path.exists():
            raise RuntimeError(f"Python executable not found: {python_path}")

        return python_path

    def install_whl(self, deployment_id: str, whl_path: str) -> bool:
        """
        在虚拟环境中安装WHL包

        Args:
            deployment_id: 部署ID
            whl_path: WHL包文件路径

        Returns:
            是否安装成功

        Raises:
            RuntimeError: 安装失败
        """
        python_executable = self.get_python_executable(deployment_id)

        logger.info(f"Installing WHL package: {whl_path} into {deployment_id}")

        try:
            # 使用虚拟环境的pip安装WHL包
            result = subprocess.run(
                [
                    str(python_executable), "-m", "pip", "install",
                    "--no-deps",  # 不安装依赖，依赖应该已经在WHL中声明
                    whl_path
                ],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"WHL package installed successfully: {whl_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install WHL: {e.stderr}")
            raise RuntimeError(f"Failed to install WHL package: {e}")

    def delete_venv(self, deployment_id: str) -> bool:
        """
        删除部署的虚拟环境

        Args:
            deployment_id: 部署ID

        Returns:
            是否删除成功
        """
        venv_path = self.venvs_root / deployment_id

        if not venv_path.exists():
            logger.warning(f"Virtual environment not found: {venv_path}")
            return False

        logger.info(f"Deleting virtual environment: {venv_path}")

        try:
            shutil.rmtree(venv_path)
            logger.info(f"Virtual environment deleted: {venv_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete virtual environment: {e}")
            return False

    def venv_exists(self, deployment_id: str) -> bool:
        """
        检查虚拟环境是否存在

        Args:
            deployment_id: 部署ID

        Returns:
            虚拟环境是否存在
        """
        venv_path = self.venvs_root / deployment_id
        return venv_path.exists()
```

### 8.4 LocalSubprocessDeployer 实现

```python
# agent-runtime/src/manager/sdk/src/deployer/local_subprocess.py

import asyncio
import logging
import subprocess
import sys
from typing import Dict, Any
from pathlib import Path

from .base import Deployer
from ..models.enums import DeploymentStatus
from ..utils.venv_manager import VirtualEnvironmentManager

logger = logging.getLogger(__name__)


class LocalSubprocessDeployer(Deployer):
    """
    本地进程部署器

    特性:
    - 为每个部署创建独立的虚拟环境
    - 支持WHL包部署
    - 使用 python -m package_name 方式运行
    """

    def __init__(self, venvs_root: str = "./venvs"):
        """
        初始化部署器

        Args:
            venvs_root: 虚拟环境根目录
        """
        self.venv_manager = VirtualEnvironmentManager(venvs_root)

    async def deploy(
        self,
        whl_path: str,
        package_name: str,
        deployment_id: str,
        port: int,
        host: str = "127.0.0.1",
        **kwargs
    ) -> Dict[str, Any]:
        """
        部署应用

        流程:
        1. 创建独立虚拟环境
        2. 在虚拟环境中安装WHL包
        3. 使用 python -m package_name 启动应用

        Args:
            whl_path: WHL包文件路径
            package_name: Python包名（用于 -m 运行）
            deployment_id: 部署唯一标识
            port: 服务端口
            host: 服务主机
            **kwargs: 其他部署参数

        Returns:
            部署信息字典，包含:
            - deployment_id: 部署 ID
            - url: 服务访问地址
            - status: 部署状态
            - pid: 进程 ID
            - venv_path: 虚拟环境路径
        """
        logger.info(f"Deploying {deployment_id} from {whl_path} on {host}:{port}")

        try:
            # 1. 创建虚拟环境
            venv_path = self.venv_manager.create_venv(deployment_id)
            logger.info(f"Virtual environment created: {venv_path}")

            # 2. 安装WHL包
            self.venv_manager.install_whl(deployment_id, whl_path)
            logger.info(f"WHL package installed: {whl_path}")

            # 3. 获取虚拟环境Python解释器
            python_executable = self.venv_manager.get_python_executable(deployment_id)

            # 4. 构建启动命令: python -m package_name --host --port
            cmd = [
                str(python_executable),
                "-m",
                package_name,
                "--host", host,
                "--port", str(port)
            ]
            logger.debug(f"Command: {' '.join(cmd)}")

            # 5. 启动进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            # 6. 等待进程启动并检查状态
            await asyncio.sleep(2)

            if process.poll() is not None:
                # 进程已经退出，读取错误信息
                stderr = process.stderr.read()
                stdout = process.stdout.read()
                error_msg = stderr or stdout or "Unknown error"
                logger.error(f"Process exited for {deployment_id}: {error_msg}")

                # 清理虚拟环境
                self.venv_manager.delete_venv(deployment_id)
                raise RuntimeError(f"Process exited: {error_msg}")

            logger.info(f"Deployment {deployment_id} succeeded, PID: {process.pid}")
            return {
                "deployment_id": deployment_id,
                "url": f"http://{host}:{port}",
                "status": DeploymentStatus.RUNNING,
                "pid": process.pid,
                "venv_path": str(venv_path),
            }
        except Exception as e:
            logger.error(f"Deployment {deployment_id} failed: {e}")
            # 清理虚拟环境
            self.venv_manager.delete_venv(deployment_id)
            raise RuntimeError(f"Failed to deploy: {e}")

    async def stop(self, deployment: dict) -> bool:
        """
        停止部署并清理虚拟环境

        Args:
            deployment: 部署信息字典，包含 deployment_id 和 pid
        """
        deployment_id = deployment.get("deployment_id")
        pid = deployment.get("pid")
        logger.info(f"Stopping deployment {deployment_id}, PID: {pid}")

        # 1. 终止进程
        success = False
        if pid:
            success = self._kill_by_pid(pid)
            if success:
                logger.info(f"Deployment {deployment_id} process stopped")
            else:
                logger.warning(f"Failed to kill process {pid}")

        # 2. 清理虚拟环境
        venv_deleted = self.venv_manager.delete_venv(deployment_id)
        if venv_deleted:
            logger.info(f"Virtual environment deleted: {deployment_id}")

        return success

    # ... (其他方法保持不变)
```

### 8.5 数据模型更新

**部署记录模型添加虚拟环境字段**:

```python
class Deployment(BaseModel):
    """部署记录模型"""

    deployment_id: str                    # 部署唯一 ID
    type: str                              # 部署类型: agent | plugin
    name: str                               # 部署名称（= 包名，用于 python -m 运行）
    status: str                            # 状态: pending | running | stopped | failed

    # 部署信息
    url: Optional[str]                     # 服务访问 URL
    deployer_type: str                     # 部署器类型
    port: int                               # 服务端口
    pid: Optional[int]                      # 进程/线程 ID

    # 虚拟环境相关字段
    venv_path: Optional[str]               # 虚拟环境路径
    package_name: Optional[str]            # Python包名（用于python -m运行）
    whl_path: Optional[str]                # WHL包路径（部署时使用）

    # 时间戳
    created_at: str                        # 创建时间
    updated_at: str                        # 更新时间
```

### 8.6 配置项

**环境配置**:

```bash
# agent-runtime/src/manager/.env

# MySQL 数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=agent_runtime
MYSQL_USER=root
MYSQL_PASSWORD=

# 外部 OSS 服务配置（用于下载WHL包）
OSS_ENDPOINT=
OSS_ACCESS_KEY=
OSS_SECRET_KEY=

# 虚拟环境配置
V_ENVS_ROOT=./venvs                    # 虚拟环境根目录
```

### 8.8 清理策略

**自动清理**：
- 删除部署时自动清理对应的虚拟环境（默认行为）
- 部署失败时也会自动清理已创建的虚拟环境

### 8.9 错误处理

**虚拟环境创建失败**：
```python
try:
    venv_path = venv_manager.create_venv(deployment_id)
except RuntimeError as e:
    # 部署状态设置为 FAILED
    # 错误信息: "Failed to create virtual environment: {details}"
    await db.update_deployment_status(
        deployment_id,
        DeploymentStatus.FAILED,
        error_message=str(e)
    )
```

**WHL安装失败**：
```python
try:
    venv_manager.install_whl(deployment_id, whl_path)
except RuntimeError as e:
    # 清理已创建的虚拟环境
    venv_manager.delete_venv(deployment_id)
    # 部署状态设置为 FAILED
    await db.update_deployment_status(
        deployment_id,
        DeploymentStatus.FAILED,
        error_message=f"Failed to install WHL: {e}"
    )
```

---

## 附录

### A. 配置项

所有配置项通过 `.env` 文件进行配置，CLI 和 Server 使用相同的配置文件格式。

| 配置项 | 说明 | 默认值 | 使用方 |
|--------|------|--------|--------|
| MYSQL_HOST | MySQL 主机地址 | localhost | CLI, Server |
| MYSQL_PORT | MySQL 端口 | 3306 | CLI, Server |
| MYSQL_DATABASE | MySQL 数据库名 | agent_runtime | CLI, Server |
| MYSQL_USER | MySQL 用户名 | root | CLI, Server |
| MYSQL_PASSWORD | MySQL 密码 | - | CLI, Server |
| OSS_ENDPOINT | 外部 OSS 服务端点 | - | CLI, Server |
| OSS_ACCESS_KEY | OSS 访问密钥 | - | CLI, Server |
| OSS_SECRET_KEY | OSS 密钥 | - | CLI, Server |
| V_ENVS_ROOT | 虚拟环境根目录 | ./venvs | CLI, Server |

### B. 状态流转

详见 [2.4 状态流转设计](#24-状态流转设计)

### C. 错误码

| 错误码 | 描述 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 部署不存在 |
| 500 | 服务器内部错误 |
| 501 | 虚拟环境创建失败 |
| 502 | WHL包安装失败 |

### D. WHL包规范

**说明**: Manager SDK 内部通过 `package_python_to_whl()` 方法自动将用户提供的 Python 文件打包为 WHL 包。以下是生成的 WHL 包规范供参考。

**WHL包命名规范**:
```
{package_name}-{version}-{python_tag}-{abi_tag}-{platform_tag}.whl

示例:
my_agent-1.0.0-py3-none-any.whl
weather_plugin-2.1.0-py3-none-any.whl
```

**WHL包结构要求**:
```
my_agent-1.0.0-py3-none-any.whl
├── my_agent/
│   └── __main__.py           # 必须：包入口文件
│       ├── from openjiuwen_runtime_sdk import AgentApp
│       ├── app = AgentApp(...)
│       └── if __name__ == "__main__":
│           └── app.run()
├── my_agent-1.0.0.dist-info/
│   ├── METADATA               # 必须：包元数据
│   ├── WHEEL                  # 必须：WHL格式信息
│   ├── RECORD                 # 必须：文件清单
│   └── top_level.txt          # 必须：顶级包名
└── ... (其他依赖)
```

**`__main__.py` 要求**:
- 必须包含可执行的入口代码
- 支持 `--host` 和 `--port` 命令行参数
- 导入并使用 openjiuwen_runtime_sdk 中的 AgentApp 或 PluginApp
- **必须实现长期运行的服务**（如HTTP服务器），不能执行完就退出
