"""日志工具模块"""
import logging
import traceback

def log_exception(logger: logging.Logger, msg: str = ""):
    """记录异常信息"""
    logger.error(f"{msg}\n{traceback.format_exc()}")
