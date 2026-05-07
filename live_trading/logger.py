import logging
import os
from datetime import datetime


def setup_logger(name: str = 'trading', log_dir: str = 'logs') -> logging.Logger:
    """配置并返回应用日志器，同时输出到控制台和日志文件。"""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件输出
    log_file = os.path.join(log_dir, f'trading_{datetime.now().strftime("%Y%m%d")}.log')
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
