# -*- coding: utf-8 -*-
"""
日志工具 - 支持结构化日志和分布式追踪
"""
import logging
import sys
from datetime import datetime
from functools import lru_cache

_old_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    record = _old_record_factory(*args, **kwargs)
    if not hasattr(record, "timestamp"):
        record.timestamp = datetime.utcnow().isoformat()
    if not hasattr(record, "level"):
        record.level = record.levelname
    return record


logging.setLogRecordFactory(_record_factory)


class CustomJsonFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""

    def __init__(self, fmt: str):
        super().__init__(
            fmt,
            defaults={
                "timestamp": "",
                "level": "",
                "service": "jusure-microservice",
            },
        )

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "timestamp"):
            record.timestamp = datetime.utcnow().isoformat()
        if not hasattr(record, "level"):
            record.level = record.levelname
        if not hasattr(record, "service"):
            record.service = "jusure-microservice"
        return super().format(record)

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict):
        log_record["timestamp"] = datetime.utcnow().isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["service"] = "jusure-microservice"

@lru_cache()
def get_logger(name: str, level: str = "INFO", json_format: bool = True) -> logging.Logger:
    """获取日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.propagate = False
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if json_format:
            formatter = CustomJsonFormatter(
                "%(timestamp)s %(level)s %(name)s %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

class TaskLogger:
    """任务日志记录器 - 支持任务进度追踪"""
    
    def __init__(self, task_id: str, logger: logging.Logger | None = None):
        self.task_id = task_id
        self.logger = logger or get_logger("task")
    
    def info(self, message: str, **kwargs):
        self._log("INFO", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log("ERROR", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log("WARNING", message, **kwargs)
    
    def progress(self, progress: float, message: str = ""):
        self._log("INFO", message, progress=progress, event="progress")
    
    def _log(self, level: str, message: str, **kwargs):
        extra = {"task_id": self.task_id, **kwargs}
        getattr(self.logger, level.lower())(message, extra=extra)

logger = get_logger("jusure")
