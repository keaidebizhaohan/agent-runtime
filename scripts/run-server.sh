PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

rm -rf ${PROJECT_DIR}/dist
mkdir ${PROJECT_DIR}/dist

sed -i '/openjiuwen_studio/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed -i '/openjiuwen-runtime-service/d' ${PROJECT_DIR}/applications/lowcode_agent/pyproject.toml
sed -i '/openjiuwen-runtime-foundation/d' ${PROJECT_DIR}/management/pyproject.toml
sed -i '/openjiuwen-runtime-management/d' ${PROJECT_DIR}/server/pyproject.toml

# complie dist/openjiuwen_studio-0.1.5-py3-none-any.whl
cd ${PROJECT_DIR}/agent-studio/backend
uv sync
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/


# complie dist/lowcode_agent_runner-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/applications/lowcode_agent
uv sync
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/


# complie dist/openjiuwen_runtime_service-0.1.0-py3-none-any.whl
cd ${PROJECT_DIR}/service
uv sync
rm -rf dist
uv build --out-dir ${PROJECT_DIR}/dist/

# Before run this, please prepare ${PROJECT_DIR}/server/.env
cd ${PROJECT_DIR}/server
uv sync
source .venv/Scripts/activate
uv pip install -e ../management
uv pip install -e ../foundation

uvicorn openjiuwen_runtime.server.main:app --host 0.0.0.0 --port 8186 2>&1 | tee server.log
