"""
开源库集成测试 — 日志模块。
运行: pytest tests/test_logger.py -v
"""
import os
import sys

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ====================== Loguru 日志模块 ======================

class TestLogger:
    """测试 Loguru 日志模块"""

    def test_logger_import(self):
        """能正常导入 logger"""
        from werss.logger import logger
        assert logger is not None

    def test_logger_info(self):
        """info 级别日志不抛异常"""
        from werss.logger import logger
        logger.info("测试日志")
        logger.debug("调试日志")

    def test_log_dir_exists(self):
        """日志目录已创建"""
        from werss.logger import LOG_DIR
        assert os.path.exists(LOG_DIR)
        assert os.path.isdir(LOG_DIR)
