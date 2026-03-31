PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR=${PROJECT_DIR}/server
ENV_FILE=${SERVER_DIR}/.env

cd ${PROJECT_DIR}
# git checkout develop
if [ ! -d "agent-studio" ]; then
    git submodule update --init --recursive
else
    echo "==> agent-studio already exist, skip pull."
fi

rm -rf ${PROJECT_DIR}/dist
mkdir ${PROJECT_DIR}/dist

if [ ! -f "${ENV_FILE}" ]; then
    echo "============================================================"
    echo "ERROR: Environment file not found!"
    echo "Please prepare ${ENV_FILE} first."
    echo "============================================================"
    exit 1
fi

echo "Loading environment variables from ${ENV_FILE}"
set -a                  # 开启：自动导出环境变量
source ${ENV_FILE}      # 读取环境变量
set +a                  # 关闭：恢复正常

sed -i '/openjiuwen_studio/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed -i '/openjiuwen-runtime-service/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed -i '/openjiuwen-runtime-foundation/d' ${PROJECT_DIR}/management/pyproject.toml
sed -i '/openjiuwen-runtime-management/d' ${PROJECT_DIR}/server/pyproject.toml

# complie dist/openjiuwen_studio-0.1.5-py3-none-any.whl
cd ${PROJECT_DIR}/agent-studio/backend
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/


# complie dist/lowcode_agent_runner-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/applications/lowcode_agent
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/


# complie dist/openjiuwen_runtime_service-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/service
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/

# Before run this, please prepare ${PROJECT_DIR}/server/.env
cd ${PROJECT_DIR}/server
uv sync ${UV_EXTRA_ARGS}

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OS" == "Windows_NT" ]]; then
    # Windows 系统 (Git Bash / WSL / Cygwin)
    source .venv/Scripts/activate
else
    # Linux / macOS 系统
    source .venv/bin/activate
fi
uv pip install -e ../management ${UV_EXTRA_ARGS}
uv pip install -e ../foundation ${UV_EXTRA_ARGS}

python -m openjiuwen_runtime.server.main 2>&1 | tee server.log