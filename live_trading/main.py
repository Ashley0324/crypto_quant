#!/usr/bin/env python3
"""
加密货币实盘交易入口

用法:
    python -m live_trading.main                          # 使用 config.yaml 默认配置
    python -m live_trading.main --strategy turtle        # 指定策略
    python -m live_trading.main --symbol ETHUSDT         # 指定交易对
    python -m live_trading.main --interval 4h            # 指定 K 线周期
    python -m live_trading.main --live                   # 切换到实盘（默认测试网）
"""

import argparse
import logging
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_trading.logger import setup_logger
from live_trading.config import load_config
from live_trading.engine import TradingEngine


def main():
    parser = argparse.ArgumentParser(
        description='Crypto Quant 实盘交易系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--strategy', help='策略名称 (ma_cross / turtle)')
    parser.add_argument('--symbol', help='交易对，如 BTCUSDT')
    parser.add_argument('--interval', help='K 线周期，如 1h / 4h / 1d')
    parser.add_argument('--live', action='store_true',
                        help='实盘模式（默认为测试网）')
    args = parser.parse_args()

    setup_logger()
    logger = logging.getLogger('trading')

    config = load_config(args.config)

    # CLI 参数覆盖配置文件
    if args.strategy:
        config.strategy = args.strategy
    if args.symbol:
        config.symbol = args.symbol
    if args.interval:
        config.interval = args.interval
    if args.live:
        config.testnet = False

    # 校验 API 凭证
    if not config.api_key or not config.api_secret:
        logger.error(
            "未找到 API_KEY / API_SECRET。\n"
            "请将 '.env copy' 重命名为 '.env' 并填入你的 API 密钥。"
        )
        sys.exit(1)

    # 实盘二次确认
    if not config.testnet:
        logger.warning("=" * 55)
        logger.warning("警告: 实盘模式，将使用真实资金交易！")
        logger.warning("=" * 55)
        confirm = input("输入 'yes' 确认继续: ").strip().lower()
        if confirm != 'yes':
            logger.info("已取消")
            sys.exit(0)

    TradingEngine(config).run()


if __name__ == '__main__':
    main()
