@echo off
REM Agent Runtime Server 一键部署脚本

echo ========================================
echo   Agent Runtime Server 部署脚本
echo ========================================
echo.

REM 检查 uv
echo [1/5] 检查环境...
uv --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ uv 未安装，请先安装 uv: pip install uv
    exit /b 1
)
for /f "tokens=*" %%v in ('uv --version') do set UV_VERSION=%%v
echo   ✓ uv %UV_VERSION%

REM 切换到脚本目录
cd /d "%~dp0"
echo   工作目录: %CD%

REM 创建虚拟环境
echo.
echo [2/5] 创建虚拟环境...
if not exist ".venv" (
    uv venv
    echo   ✓ 虚拟环境创建成功
) else (
    echo   ✓ 虚拟环境已存在
)

REM 同步依赖
echo.
echo [3/5] 同步依赖...
uv sync >nul 2>&1
if %errorlevel% neq 0 (
    echo   ! 无 pyproject.toml，跳过 uv sync
) else (
    echo   ✓ 依赖同步成功
)

REM 安装 management
echo.
echo [4/5] 安装 management SDK...
uv pip install -e ..\management >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ management SDK 安装失败
    exit /b 1
)
echo   ✓ management SDK 安装成功

REM 安装 foundation
echo.
echo [5/5] 安装 foundation SDK...
uv pip install -e ..\foundation >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ foundation SDK 安装失败
    exit /b 1
)
echo   ✓ foundation SDK 安装成功

REM 启动服务器
echo.
echo 启动服务器...
echo.
echo ========================================
echo   API: http://localhost:8000
echo   文档: http://localhost:8000/docs
echo ========================================
echo.

uv run -m openjiuwen_runtime.server.main
