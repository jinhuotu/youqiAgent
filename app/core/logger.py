"""全局日志配置模块。

使用 loguru 实现统一日志管理：
- 格式：时间 | 日志级别 | 模块名 | user_id | 日志内容
- 同时输出控制台 + 文件，按天切割，保留 30 天
- 敏感信息自动脱敏
"""

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.security import mask_sensitive_text


# 移除 loguru 默认 handler，由本模块统一配置
logger.remove()


def _patch_record(record: dict[str, Any]) -> None:
    """为每条日志补充默认 extra 字段，并脱敏消息内容。"""
    record["extra"].setdefault("user_id", "-")
    record["extra"].setdefault("module_name", record["name"] or "-")
    # 对日志消息做敏感信息脱敏
    record["message"] = mask_sensitive_text(str(record["message"]))


def setup_logger(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """初始化全局日志。

    Args:
        log_level: 日志级别，如 INFO / DEBUG / WARNING / ERROR
        log_dir: 日志文件目录
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[module_name]}</cyan> | "
        "user_id={extra[user_id]} | "
        "<level>{message}</level>"
    )

    # 控制台输出
    logger.add(
        sys.stdout,
        format=log_format,
        level=log_level,
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    # 文件输出：按天切割，保留 30 天
    logger.add(
        f"{log_dir}/app_{{time:YYYY-MM-DD}}.log",
        format=log_format,
        level=log_level,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    logger.configure(patcher=_patch_record)
    logger.bind(module_name="logger").info(f"日志系统初始化完成，级别={log_level}")


def get_logger(module_name: str = "app"):
    """获取绑定模块名的 logger。

    Args:
        module_name: 模块标识，写入日志的模块名字段

    Returns:
        绑定了 module_name 的 loguru logger
    """
    return logger.bind(module_name=module_name)
