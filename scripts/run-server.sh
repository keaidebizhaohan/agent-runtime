PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR=${PROJECT_DIR}/server
ENV_FILE=${SERVER_DIR}/.env


# ==============================================
# ✅ 跨平台路径解析：Windows + Linux 都正确
# ==============================================
function is_absolute_path {
    local path="$1"
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OS" == "Windows_NT" ]]; then
        # Windows 绝对路径 C:\xxx D:\xxx /c/xxx /d/xxx
        if [[ "$path" =~ ^[A-Za-z]:\\ || "$path" =~ ^/[A-Za-z]/ ]]; then
            return 0
        fi
    else
        # Linux/macOS 绝对路径 /xxx
        if [[ "$path" == /* ]]; then
            return 0
        fi
    fi
    return 1
}

cd ${PROJECT_DIR}
# git checkout develop
git submodule update --init --recursive
git submodule update --remote --recursive

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

if [[ "$OSTYPE" == "darwin"* ]]; then
    SED_I_FLAG="-i ''"
else
    SED_I_FLAG="-i"
fi

sed ${SED_I_FLAG} '/openjiuwen_studio/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed ${SED_I_FLAG} '/openjiuwen-runtime-service/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed ${SED_I_FLAG} '/openjiuwen-runtime-foundation/d' ${PROJECT_DIR}/management/pyproject.toml
sed ${SED_I_FLAG} '/openjiuwen-runtime-management/d' ${PROJECT_DIR}/server/pyproject.toml


# 自动解析 DIST_DIR：相对路径 = 基于 PROJECT_DIR；绝对路径 = 保持不变

if is_absolute_path "${DIST_DIR}"; then
    FINAL_DIST_DIR="${DIST_DIR}"
else
    FINAL_DIST_DIR="${PROJECT_DIR}/${DIST_DIR}"
fi

echo "✅ 最终构建输出目录（已解析绝对路径）: ${FINAL_DIST_DIR}"
rm -rf ${FINAL_DIST_DIR}
mkdir ${FINAL_DIST_DIR}

# complie dist/openjiuwen_studio-0.1.5-py3-none-any.whl
cd ${PROJECT_DIR}/agent-studio/backend
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${FINAL_DIST_DIR}

# complie dist/openjiuwen-0.1.9-py3-none-any.whl (core library)
if [ -d "${PROJECT_DIR}/../agent-core" ]; then
    cd ${PROJECT_DIR}/../agent-core
    rm -rf dist
    uv build --out-dir ${FINAL_DIST_DIR}
fi

# complie dist/lowcode_agent_runner-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/applications/lowcode_agent
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${FINAL_DIST_DIR}

# complie dist/openjiuwen_runtime_service-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/service
uv sync ${UV_EXTRA_ARGS}
rm -rf dist
uv build --out-dir ${FINAL_DIST_DIR}

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
