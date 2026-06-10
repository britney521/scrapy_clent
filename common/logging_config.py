from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Set

from .project_settings import LOG_DIR, LOG_LEVEL


_CONFIGURED: Set[str] = set()


def get_logger(app_name: str = 'app'):
    """返回已配置的日志器。

    优先使用 loguru；未安装时回退到标准 logging，避免开发环境未装依赖时直接崩溃。
    """
    try:
        from loguru import logger
    except ModuleNotFoundError:
        return _stdlib_logger(app_name)

    if app_name not in _CONFIGURED:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.remove()
        logger.add(
            sys.stderr,
            level=LOG_LEVEL,
            format='<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | <cyan>{thread.name}</cyan> | <level>{message}</level>',
            enqueue=True,
            backtrace=True,
            diagnose=False,
        )
        logger.add(
            log_dir / f'{app_name}.log',
            level=LOG_LEVEL,
            rotation='10 MB',
            retention='14 days',
            encoding='utf-8',
            enqueue=True,
            backtrace=True,
            diagnose=False,
            format='{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {thread.name} | {message}',
        )
        _CONFIGURED.add(app_name)
    return logger


def log_debug(title: str, payload: Any = None, app_name: str = 'client') -> None:
    # 服务端不打印 debug 日志；只保留客户端调试日志写入 logs/client.log。
    if app_name == 'server':
        return
    logger = get_logger(app_name)
    if payload is None:
        logger.debug(title)
        return
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        body = str(payload)
    logger.debug(f'{title}\n{body}')


def _stdlib_logger(app_name: str):
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(app_name)
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))
    formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_dir / f'{app_name}.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger
