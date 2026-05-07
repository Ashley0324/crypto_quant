import logging
import math
import threading
import time
from typing import Optional, Dict
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger('trading')

# Binance broker tag 格式: x-{brokerID}{timestamp后6位}
# 现货和合约分别使用不同的 broker ID
_SPOT_BROKER_ID = 'YD783Z4B'
_FUTURES_BROKER_ID = 'ethkXc9Q'

# 限价单追踪默认参数
_LIMIT_POLL_INTERVAL = 5    # 轮询间隔（秒）
_LIMIT_TIMEOUT = 300        # 超时未成交则撤单（秒）


def _make_client_order_id(broker_id: str) -> str:
    """生成带 broker tag 的 clientOrderId，格式: x-{brokerID}{时间戳后6位}"""
    suffix = str(int(time.time() * 1000))[-6:]
    return f'x-{broker_id}{suffix}'


class BinanceBroker:
    """
    币安订单执行与账户管理。

    支持现货市价/限价买入、全仓卖出，自动处理数量和价格精度。
    限价单在后台线程追踪成交状态，超时自动撤单。
    下单时自动附加 broker ID 以获取返佣。
    """

    def __init__(self, client: Client, symbol: str,
                 spot_broker_id: str = _SPOT_BROKER_ID,
                 futures_broker_id: str = _FUTURES_BROKER_ID,
                 limit_timeout: int = _LIMIT_TIMEOUT,
                 limit_poll_interval: int = _LIMIT_POLL_INTERVAL):
        self.client = client
        self.symbol = symbol.upper()
        self._info: Optional[dict] = None
        self.spot_broker_id = spot_broker_id
        self.futures_broker_id = futures_broker_id
        self.limit_timeout = limit_timeout
        self.limit_poll_interval = limit_poll_interval

        # 当前挂单追踪（同时只允许一笔限价单）
        self._pending_order_id: Optional[str] = None
        self._pending_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 市场信息
    # ------------------------------------------------------------------

    def _symbol_info(self) -> dict:
        if self._info is None:
            self._info = self.client.get_symbol_info(self.symbol)
        return self._info

    def _lot_size(self) -> tuple[float, float]:
        """返回 (min_qty, step_size)。"""
        for f in self._symbol_info()['filters']:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['minQty']), float(f['stepSize'])
        return 1e-6, 1e-6

    def _tick_size(self) -> float:
        """返回价格最小变动单位（tickSize）。"""
        for f in self._symbol_info()['filters']:
            if f['filterType'] == 'PRICE_FILTER':
                return float(f['tickSize'])
        return 0.01

    def _round_qty(self, qty: float) -> float:
        """将数量取整到合法步长。"""
        _, step = self._lot_size()
        precision = max(0, int(round(-math.log10(step))))
        return round(math.floor(qty / step) * step, precision)

    def _round_price(self, price: float) -> float:
        """将价格取整到合法 tickSize。"""
        tick = self._tick_size()
        precision = max(0, int(round(-math.log10(tick))))
        return round(round(price / tick) * tick, precision)

    def base_asset(self) -> str:
        return self._symbol_info()['baseAsset']

    # ------------------------------------------------------------------
    # 账户查询
    # ------------------------------------------------------------------

    def get_balance(self, asset: str = 'USDT') -> float:
        account = self.client.get_account()
        for b in account['balances']:
            if b['asset'] == asset:
                return float(b['free'])
        return 0.0

    def get_position(self) -> float:
        """返回当前基础资产持仓（如 BTC）。"""
        return self.get_balance(self.base_asset())

    def has_position(self) -> bool:
        min_qty, _ = self._lot_size()
        return self.get_position() >= min_qty

    def get_price(self) -> float:
        return float(self.client.get_symbol_ticker(symbol=self.symbol)['price'])

    def has_pending_limit_order(self) -> bool:
        """是否有正在追踪的限价单。"""
        with self._pending_lock:
            return self._pending_order_id is not None

    # ------------------------------------------------------------------
    # 市价单
    # ------------------------------------------------------------------

    def buy_market(self, usdt_amount: float) -> Optional[Dict]:
        """用指定 USDT 金额市价买入。"""
        price = self.get_price()
        qty = self._round_qty(usdt_amount / price)
        min_qty, _ = self._lot_size()

        if qty < min_qty:
            logger.warning(
                f"计算数量 {qty} 低于最小交易量 {min_qty}，跳过下单"
            )
            return None

        logger.info(
            f"[市价买入] {qty} {self.base_asset()} @ ~{price:.2f} USDT "
            f"(约 {qty * price:.2f} USDT)"
        )
        client_order_id = _make_client_order_id(self.spot_broker_id)
        try:
            order = self.client.order_market_buy(
                symbol=self.symbol,
                quantity=qty,
                newClientOrderId=client_order_id,
            )
            logger.info(
                f"买单成交: orderId={order['orderId']}, "
                f"qty={order.get('executedQty')}, "
                f"clientOrderId={order.get('clientOrderId')}"
            )
            return order
        except BinanceAPIException as e:
            logger.error(f"买单失败: {e}")
            return None

    def sell_all(self) -> Optional[Dict]:
        """卖出全部基础资产持仓（市价）。"""
        qty = self._round_qty(self.get_position())
        min_qty, _ = self._lot_size()

        if qty < min_qty:
            logger.warning(f"持仓 {qty} 低于最小交易量 {min_qty}，跳过卖出")
            return None

        logger.info(f"[市价卖出] {qty} {self.base_asset()}")
        client_order_id = _make_client_order_id(self.spot_broker_id)
        try:
            order = self.client.order_market_sell(
                symbol=self.symbol,
                quantity=qty,
                newClientOrderId=client_order_id,
            )
            logger.info(
                f"卖单成交: orderId={order['orderId']}, "
                f"qty={order.get('executedQty')}, "
                f"clientOrderId={order.get('clientOrderId')}"
            )
            return order
        except BinanceAPIException as e:
            logger.error(f"卖单失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 限价单
    # ------------------------------------------------------------------

    def buy_limit(self, usdt_amount: float, price: float,
                  on_filled=None, on_cancelled=None) -> Optional[Dict]:
        """
        挂限价买单，后台追踪成交状态。

        Args:
            usdt_amount: 买入金额（USDT）
            price:       限价价格
            on_filled:   成交回调 fn(order: dict)，在后台线程中调用
            on_cancelled: 撤单回调 fn(order_id: str)，在后台线程中调用

        Returns:
            下单响应 dict，或 None（下单失败）
        """
        with self._pending_lock:
            if self._pending_order_id is not None:
                logger.warning(
                    f"已有挂单 {self._pending_order_id}，跳过新限价买单"
                )
                return None

        limit_price = self._round_price(price)
        qty = self._round_qty(usdt_amount / limit_price)
        min_qty, _ = self._lot_size()

        if qty < min_qty:
            logger.warning(f"计算数量 {qty} 低于最小交易量 {min_qty}，跳过下单")
            return None

        logger.info(
            f"[限价买入] {qty} {self.base_asset()} @ {limit_price:.4f} USDT "
            f"(约 {qty * limit_price:.2f} USDT)"
        )
        client_order_id = _make_client_order_id(self.spot_broker_id)
        try:
            order = self.client.order_limit_buy(
                symbol=self.symbol,
                quantity=qty,
                price=str(limit_price),
                newClientOrderId=client_order_id,
            )
            order_id = str(order['orderId'])
            logger.info(f"限价买单已提交: orderId={order_id}, price={limit_price}")
            with self._pending_lock:
                self._pending_order_id = order_id
            self._track_order(order_id, on_filled, on_cancelled)
            return order
        except BinanceAPIException as e:
            logger.error(f"限价买单失败: {e}")
            return None

    def sell_limit_all(self, price: float,
                       on_filled=None, on_cancelled=None) -> Optional[Dict]:
        """
        将全部持仓挂限价卖单，后台追踪成交状态。

        Args:
            price:        限价价格
            on_filled:    成交回调 fn(order: dict)
            on_cancelled: 撤单回调 fn(order_id: str)

        Returns:
            下单响应 dict，或 None（下单失败）
        """
        with self._pending_lock:
            if self._pending_order_id is not None:
                logger.warning(
                    f"已有挂单 {self._pending_order_id}，跳过新限价卖单"
                )
                return None

        qty = self._round_qty(self.get_position())
        min_qty, _ = self._lot_size()

        if qty < min_qty:
            logger.warning(f"持仓 {qty} 低于最小交易量 {min_qty}，跳过卖出")
            return None

        limit_price = self._round_price(price)
        logger.info(f"[限价卖出] {qty} {self.base_asset()} @ {limit_price:.4f} USDT")
        client_order_id = _make_client_order_id(self.spot_broker_id)
        try:
            order = self.client.order_limit_sell(
                symbol=self.symbol,
                quantity=qty,
                price=str(limit_price),
                newClientOrderId=client_order_id,
            )
            order_id = str(order['orderId'])
            logger.info(f"限价卖单已提交: orderId={order_id}, price={limit_price}")
            with self._pending_lock:
                self._pending_order_id = order_id
            self._track_order(order_id, on_filled, on_cancelled)
            return order
        except BinanceAPIException as e:
            logger.error(f"限价卖单失败: {e}")
            return None

    def cancel_pending_order(self) -> bool:
        """撤销当前挂单（如有）。返回是否成功撤单。"""
        with self._pending_lock:
            order_id = self._pending_order_id
        if not order_id:
            return False
        return self._cancel_order(order_id)

    # ------------------------------------------------------------------
    # 限价单后台追踪
    # ------------------------------------------------------------------

    def _track_order(self, order_id: str, on_filled=None, on_cancelled=None):
        """在后台线程中轮询订单状态，超时自动撤单。"""
        t = threading.Thread(
            target=self._poll_order,
            args=(order_id, on_filled, on_cancelled),
            daemon=True,
            name=f'order-tracker-{order_id}',
        )
        t.start()

    def _poll_order(self, order_id: str, on_filled=None, on_cancelled=None):
        """轮询订单状态直到成交、撤单或超时。"""
        deadline = time.time() + self.limit_timeout
        logger.info(
            f"开始追踪限价单 {order_id}，超时 {self.limit_timeout}s"
        )

        while time.time() < deadline:
            time.sleep(self.limit_poll_interval)
            try:
                order = self.client.get_order(
                    symbol=self.symbol, orderId=int(order_id)
                )
            except BinanceAPIException as e:
                logger.error(f"查询订单 {order_id} 失败: {e}")
                continue

            status = order.get('status')
            logger.debug(f"订单 {order_id} 状态: {status}")

            if status == 'FILLED':
                logger.info(
                    f"限价单 {order_id} 已完全成交: "
                    f"qty={order.get('executedQty')}, "
                    f"price={order.get('price')}"
                )
                with self._pending_lock:
                    self._pending_order_id = None
                if on_filled:
                    on_filled(order)
                return

            if status in ('CANCELED', 'REJECTED', 'EXPIRED'):
                logger.warning(f"限价单 {order_id} 状态变为 {status}")
                with self._pending_lock:
                    self._pending_order_id = None
                if on_cancelled:
                    on_cancelled(order_id)
                return

            if status == 'PARTIALLY_FILLED':
                filled = float(order.get('executedQty', 0))
                orig = float(order.get('origQty', 0))
                logger.info(f"限价单 {order_id} 部分成交: {filled}/{orig}")

        # 超时，撤单
        logger.warning(
            f"限价单 {order_id} 超时 {self.limit_timeout}s 未完全成交，撤单"
        )
        cancelled = self._cancel_order(order_id)
        if cancelled and on_cancelled:
            on_cancelled(order_id)

    def _cancel_order(self, order_id: str) -> bool:
        """撤销指定订单。"""
        try:
            self.client.cancel_order(
                symbol=self.symbol, orderId=int(order_id)
            )
            logger.info(f"订单 {order_id} 已撤销")
            with self._pending_lock:
                if self._pending_order_id == order_id:
                    self._pending_order_id = None
            return True
        except BinanceAPIException as e:
            # 订单已成交时撤单会报错，属于正常情况
            logger.warning(f"撤单 {order_id} 失败（可能已成交）: {e}")
            with self._pending_lock:
                if self._pending_order_id == order_id:
                    self._pending_order_id = None
            return False
