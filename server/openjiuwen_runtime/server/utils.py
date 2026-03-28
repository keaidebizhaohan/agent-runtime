#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""日志脱敏工具函数"""


def mask_userdata(userdata: str | None, max_bytes: int = 10) -> str:
    """
    对userdata进行脱敏处理，只保留前N字节，其余隐藏

    Args:
        userdata: 用户数据字符串
        max_bytes: 保留的最大字节数，默认10字节

    Returns:
        脱敏后的字符串
    """
    if userdata is None:
        return "None"

    if not isinstance(userdata, str):
        userdata = str(userdata)

    # 编码为字节获取准确长度
    userdata_bytes = userdata.encode('utf-8')

    if len(userdata_bytes) <= max_bytes:
        return userdata

    # 只保留前max_bytes字节
    masked_bytes = userdata_bytes[:max_bytes]
    try:
        masked_str = masked_bytes.decode('utf-8', errors='ignore')
    except UnicodeDecodeError:
        # 如果解码失败，直接返回截断前的原始字符串前几个字符
        masked_str = userdata[:max_bytes]

    return f"{masked_str}***"