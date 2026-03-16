"""WHL包解析工具

从WHL包中自动解析包名
"""

import logging
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def parse_package_name(whl_path: str) -> Optional[str]:
    """
    从WHL包中解析包名

    优先级:
    1. 从 METADATA 文件读取 Name 字段（最准确）
    2. 从 top_level.txt 读取顶层模块名
    3. 从文件名解析（作为后备）

    Args:
        whl_path: WHL包文件路径

    Returns:
        包名，解析失败返回 None
    """
    whl_file = Path(whl_path)
    if not whl_file.exists():
        logger.error(f"WHL file not found: {whl_path}")
        return None

    try:
        with zipfile.ZipFile(whl_file, 'r') as whl:
            # 方法1: 从 METADATA 读取 Name 字段
            metadata_files = [f for f in whl.namelist() if f.endswith('.dist-info/METADATA')]
            if metadata_files:
                try:
                    metadata_content = whl.read(metadata_files[0]).decode('utf-8')
                    for line in metadata_content.split('\n'):
                        if line.startswith('Name:'):
                            package_name = line.split(':', 1)[1].strip()
                            logger.info(f"Package name from METADATA: {package_name}")
                            return package_name
                except Exception as e:
                    logger.warning(f"Failed to read METADATA: {e}")

            # 方法2: 从 top_level.txt 读取
            toplevel_files = [f for f in whl.namelist() if f.endswith('.dist-info/top_level.txt')]
            if toplevel_files:
                try:
                    toplevel_content = whl.read(toplevel_files[0]).decode('utf-8').strip()
                    package_name = toplevel_content.split('\n')[0].strip()
                    logger.info(f"Package name from top_level.txt: {package_name}")
                    return package_name
                except Exception as e:
                    logger.warning(f"Failed to read top_level.txt: {e}")

            # 方法3: 从文件名解析 (作为最后后备)
            filename = whl_file.stem  # 去掉 .whl 后缀
            # 格式: {package_name}-{version}-{python_tag}-{abi_tag}-{platform_tag}
            parts = filename.split('-')
            if len(parts) >= 2:
                package_name = parts[0]
                logger.info(f"Package name from filename: {package_name}")
                return package_name

            logger.error(f"Failed to parse package name from: {whl_path}")
            return None

    except zipfile.BadZipFile:
        logger.error(f"Invalid WHL file: {whl_path}")
        return None
    except Exception as e:
        logger.error(f"Error parsing WHL package: {e}")
        return None
