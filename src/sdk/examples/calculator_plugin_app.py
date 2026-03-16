"""
Calculator Plugin App Example

This is a test example to verify PluginApp works correctly.
It provides calculator tools: add (addition) and multiply (multiplication).

Reference: OPENJIUWEN_RUNTIME_DESIGN_V2.md Section 3.3
"""

from src.core import PluginApp
from typing import Dict, Any


# Create the PluginApp
app = PluginApp(
    app_name="CalculatorTools",
    app_description="数学计算工具集，提供加法和乘法功能",
    version="0.1.0",
)


@app.restful.tool(
    name="add",
    description="计算两个数字的和"
)
async def add(a: float, b: float) -> Dict[str, Any]:
    """
    加法工具 - 计算两个数字的和

    Args:
        a: 第一个数字
        b: 第二个数字

    Returns:
        计算结果，包含操作数和和
    """
    result = a + b
    return {
        "operation": "addition",
        "operands": [a, b],
        "result": result,
    }


@app.restful.tool(
    name="multiply",
    description="计算两个数字的乘积"
)
async def multiply(a: float, b: float) -> Dict[str, Any]:
    """
    乘法工具 - 计算两个数字的乘积

    Args:
        a: 第一个数字
        b: 第二个数字

    Returns:
        计算结果，包含操作数和乘积
    """
    result = a * b
    return {
        "operation": "multiplication",
        "operands": [a, b],
        "result": result,
    }


@app.restful.tool(
    name="subtract",
    description="计算两个数字的差"
)
async def subtract(a: float, b: float) -> Dict[str, Any]:
    """
    减法工具 - 计算两个数字的差

    Args:
        a: 被减数
        b: 减数

    Returns:
        计算结果
    """
    result = a - b
    return {
        "operation": "subtraction",
        "operands": [a, b],
        "result": result,
    }


@app.restful.tool(
    name="divide",
    description="计算两个数字的商"
)
async def divide(a: float, b: float) -> Dict[str, Any]:
    """
    除法工具 - 计算两个数字的商

    Args:
        a: 被除数
        b: 除数

    Returns:
        计算结果
    """
    if b == 0:
        raise ValueError("除数不能为零")
    result = a / b
    return {
        "operation": "division",
        "operands": [a, b],
        "result": result,
    }


if __name__ == "__main__":
    # Run the app
    print("Starting CalculatorTools Plugin on http://127.0.0.1:8092")
    print()
    print("Available endpoints:")
    print("  GET  /health              - 健康检查")
    print("  GET  /tools               - 列出所有工具")
    print("  POST /tools/add           - 加法工具")
    print("  POST /tools/multiply      - 乘法工具")
    print("  POST /tools/subtract      - 减法工具")
    print("  POST /tools/divide        - 除法工具")
    print()
    print("Example usage:")
    print('  curl -X POST http://127.0.0.1:8092/tools/add -H "Content-Type: application/json" -d \'{"a": 5, "b": 3}\'')
    print('  curl -X POST http://127.0.0.1:8092/tools/multiply -H "Content-Type: application/json" -d \'{"a": 4, "b": 7}\'')
    print('  curl -X POST http://127.0.0.1:8092/tools/subtract -H "Content-Type: application/json" -d \'{"a": 10, "b": 3}\'')
    print('  curl -X POST http://127.0.0.1:8092/tools/divide -H "Content-Type: application/json" -d \'{"a": 20, "b": 4}\'')
    print()
    print("API documentation: http://127.0.0.1:8092/docs")
    print()
    app.run(host="127.0.0.1", port=8092)
