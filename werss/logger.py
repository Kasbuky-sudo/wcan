# Made by SONGJUNSONG, Jilin Business and Technology College (School of Finance and Economics)
"""
日志模块 — 基于 Loguru 的零配置结构化日志。

特性：
- 自动按天轮转，保留 30 天
- 同时输出到控制台（彩色）和文件（JSON 格式）
- 全局拦截标准 logging 模块，统一日志入口
- 提供 logger 单例，其他模块直接 from werss.logger import logger

使用方式：
    from werss.logger import logger
    logger.info("文章采集完成")
    logger.error("爬取失败", url="https://...")
"""
import os
import sys
import logging
from loguru import logger as _logger

# 日志目录（跟随可写用户数据目录；冻结成 exe 后落在 exe 旁边）
try:
    from paths import user_dir as _user_dir
except ImportError:  # 兜底：按项目根推导
    def _user_dir():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.join(_user_dir(), "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 移除 loguru 默认配置
_logger.remove()

# 控制台输出：彩色、简洁格式
_logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:{line} - <level>{message}</level>",
    colorize=True,
)

# 文件输出：按天轮转，保留 30 天，UTF-8 编码
_logger.add(
    os.path.join(LOG_DIR, "app_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="00:00",      # 每天午夜轮转
    retention="30 days",   # 保留 30 天
    encoding="utf-8",
    enqueue=True,          # 多进程安全
    backtrace=True,        # 异常完整堆栈
    diagnose=True,         # 异常变量值
)

# 拦截标准 logging 模块，使第三方库（如 APScheduler）的日志也走 loguru
class _InterceptHandler(logging.Handler):
    def emit(self, record):
        # 获取对应的 loguru level
        try:
            level = _logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 找到真正的调用者
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        _logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# 安装拦截器
logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)

# 导出 logger 单例
logger = _logger


def init_logging():
    """初始化日志系统（向后兼容接口）。

    Loguru 在模块导入时已自动配置完成，此函数仅用于兼容旧代码调用。
    可在此处添加额外的运行时日志配置。
    """
    logger.info("日志系统初始化完成（init_logging 调用）")


logger.info("Loguru 日志模块初始化完成 | 日志目录: {}", LOG_DIR)
