"""端口管理器"""

import socket


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result != 0
    except Exception:
        return False


def allocate_port(start_port: int = 8090, max_port: int = 9090, host: str = "127.0.0.1") -> int:
    """分配可用端口"""
    for port in range(start_port, max_port):
        if is_port_available(port, host):
            return port
    raise RuntimeError(f"No available port in range {start_port}-{max_port}")
