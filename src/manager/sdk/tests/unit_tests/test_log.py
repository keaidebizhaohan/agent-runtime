from pathlib import Path
from unittest import TestCase

from openjiuwen_runtime.management.sdk.foundation.log import get_logger, setup_logging


class TestLog(TestCase):
    def test_max_bytes(self):
        setup_logging(str(Path(__file__).parent.parent / "resources" / "config" / "max_bytes_logging.yaml"))
        logger = get_logger(__name__)
        for i in range(100):
            logger.debug('debug message')
            logger.info('info message')
            logger.error('error message')
