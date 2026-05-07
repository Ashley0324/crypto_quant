import logging
import os
import signal
import time
import pandas as pd
from datetime import datetime
from binance.client import Client

from .config import Config
from .data_feed import BinanceDataFeed
from .broker import BinanceBroker
from .risk_manager import RiskManager
from .notifier import TelegramNotifier
from .strategies import get_strategy

logger = logging.getLogger('trading')

TRADE_LOG = 'logs/trades.csv'


class TradingEngine:
    """
    实盘交易引擎。

    编排数据源、策略、风控、经纪商、通知等所有模块。
    """

    def __init__(self, config: Config):
        self.config = config

        logger.info(
            f"连接币安 {'[测试网]' if config.testnet else '[实盘]'}..."
        )
        self.client = Client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            testnet=config.testnet,
        )

        # 实例化各模块
        strategy_params = config.strategy_params.get(config.strategy, {})
        self.strategy = get_strategy(config.strategy, strategy_params)

        self.feed = BinanceDataFeed(
            client=self.client,
            symbol=config.symbol,
            interval=config.interval,
            lookback=300,
        )
        self.broker = BinanceBroker(
            client=self.client,
            symbol=config.symbol,
            spot_broker_id=config.broker_config.spot_id,
            futures_broker_id=config.broker_config.futures_id,
        )
        self.risk = RiskManager(
            max_position_pct=config.risk.max_position_pct,
            max_drawdown_pct=config.risk.max_drawdown_pct,
            daily_loss_limit_pct=config.risk.daily_loss_limit_pct,
        )
        self.notifier = TelegramNotifier(
            token=config.telegram_token,
            chat_id=config.telegram_chat_id,
        )

        os.makedirs('logs', exist_ok=True)
        self._init_trade_log()

    # ------------------------------------------------------------------
    # 交易日志
    # ------------------------------------------------------------------

    def _init_trade_log(self):
        if not os.path.exists(TRADE_LOG):
            pd.DataFrame(columns=[
                'time', 'action', 'symbol', 'qty', 'price',
                'value_usdt', 'reason', 'usdt_balance',
            ]).to_csv(TRADE_LOG, index=False)

    def _log_trade(self, action: str, qty: float, price: float,
                   reason: str, balance: float):
        row = {
            'time': datetime.now().isoformat(timespec='seconds'),
            'action': action,
            'symbol': self.config.symbol,
            'qty': qty,
            'price': price,
            'value_usdt': round(qty * price, 4),
            'reason': reason,
            'usdt_balance': round(balance, 4),
        }
        pd.DataFrame([row]).to_csv(TRADE_LOG, mode='a', header=False, index=False)

    # ------------------------------------------------------------------
    # 核心逻辑
    # ------------------------------------------------------------------

    def _total_value(self) -> float:
        usdt = self.broker.get_balance('USDT')
        position = self.broker.get_position()
        price = self.broker.get_price()
        return usdt + position * price

    def _on_candle(self, df: pd.DataFrame):
        """每根 K 线收盘后由数据源调用。"""
        try:
            self._process(df)
        except Exception as e:
            logger.error(f"处理 K 线时出错: {e}", exc_info=True)

    def _process(self, df: pd.DataFrame):
        price = df['close'].iloc[-1]
        total = self._total_value()
        usdt = self.broker.get_balance('USDT')
        has_pos = self.broker.has_position()

        logger.info(
            f"账户 | 总值: {total:.2f} USDT | "
            f"可用: {usdt:.2f} USDT | "
            f"持仓: {'是' if has_pos else '否'} | "
            f"现价: {price:.2f}"
        )

        self.risk.update(total)
        if not self.risk.check(total):
            self.notifier.notify_halt(self.risk.state.halt_reason)
            return

        # 有挂单未成交时跳过本轮信号，避免重复下单
        if self.broker.has_pending_limit_order():
            logger.info("有限价单正在追踪中，跳过本轮信号")
            return

        signal = self.strategy.on_candle(df)
        logger.info(f"信号: {signal}")

        if signal.action == 'BUY' and not has_pos and usdt > 10:
            amount = self.risk.order_amount(usdt, signal.size_pct)
            if signal.order_type == 'LIMIT' and signal.limit_price:
                order = self.broker.buy_limit(
                    usdt_amount=amount,
                    price=signal.limit_price,
                    on_filled=lambda o: self._on_limit_filled('BUY', o, signal.reason),
                    on_cancelled=lambda oid: self._on_limit_cancelled('BUY', oid),
                )
                if order:
                    logger.info(f"限价买单已提交，等待成交...")
            else:
                order = self.broker.buy_market(amount)
                if order:
                    qty = float(order.get('executedQty', 0))
                    self._log_trade('BUY', qty, price, signal.reason,
                                    self.broker.get_balance('USDT'))
                    self.notifier.notify_order('BUY', self.config.symbol,
                                               qty, price, signal.reason)

        elif signal.action == 'SELL' and has_pos:
            if signal.order_type == 'LIMIT' and signal.limit_price:
                order = self.broker.sell_limit_all(
                    price=signal.limit_price,
                    on_filled=lambda o: self._on_limit_filled('SELL', o, signal.reason),
                    on_cancelled=lambda oid: self._on_limit_cancelled('SELL', oid),
                )
                if order:
                    logger.info(f"限价卖单已提交，等待成交...")
            else:
                order = self.broker.sell_all()
                if order:
                    qty = float(order.get('executedQty', 0))
                    self._log_trade('SELL', qty, price, signal.reason,
                                    self.broker.get_balance('USDT'))
                    self.notifier.notify_order('SELL', self.config.symbol,
                                               qty, price, signal.reason)

    def _on_limit_filled(self, action: str, order: dict, reason: str):
        """限价单成交回调（在后台线程中执行）。"""
        qty = float(order.get('executedQty', 0))
        price = float(order.get('price', 0))
        balance = self.broker.get_balance('USDT')
        self._log_trade(action, qty, price, reason, balance)
        self.notifier.notify_order(action, self.config.symbol, qty, price, reason)
        logger.info(f"限价{action}单成交记录完成")

    def _on_limit_cancelled(self, action: str, order_id: str):
        """限价单撤单回调（在后台线程中执行）。"""
        logger.warning(f"限价{action}单 {order_id} 已撤销（超时或手动）")
        self.notifier.send(f"*限价单已撤销*\n方向: {action}\n订单ID: `{order_id}`")

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def run(self):
        logger.info(
            f"启动交易引擎 | 策略: {self.config.strategy} | "
            f"交易对: {self.config.symbol} | 周期: {self.config.interval}"
        )

        self.feed.load_history()
        self.feed.start(
            on_candle_close=self._on_candle,
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            testnet=self.config.testnet,
        )

        self.notifier.notify_start(
            self.config.symbol, self.config.interval,
            self.config.strategy, self.config.testnet,
        )

        # 注册系统信号，支持 Docker/systemd 优雅停止
        self._running = True
        def _handle_signal(signum, frame):
            logger.info(f"收到信号 {signum}，准备停止...")
            self._running = False
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        logger.info("引擎运行中，按 Ctrl+C 停止...")
        try:
            while self._running:
                time.sleep(1)
        finally:
            # 停止前撤销未成交的限价单，避免引擎停止后挂单继续在交易所挂着
            if self.broker.has_pending_limit_order():
                logger.info("引擎停止，撤销未成交限价单...")
                self.broker.cancel_pending_order()
            self.feed.stop()
            logger.info("引擎已停止")
