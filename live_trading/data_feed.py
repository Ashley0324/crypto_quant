import logging
import threading
import pandas as pd
from typing import Callable, Optional
from binance.client import Client
from binance import ThreadedWebsocketManager

logger = logging.getLogger('trading')

# python-binance 周期映射
INTERVAL_MAP = {
    '1m': Client.KLINE_INTERVAL_1MINUTE,
    '3m': Client.KLINE_INTERVAL_3MINUTE,
    '5m': Client.KLINE_INTERVAL_5MINUTE,
    '15m': Client.KLINE_INTERVAL_15MINUTE,
    '30m': Client.KLINE_INTERVAL_30MINUTE,
    '1h': Client.KLINE_INTERVAL_1HOUR,
    '2h': Client.KLINE_INTERVAL_2HOUR,
    '4h': Client.KLINE_INTERVAL_4HOUR,
    '6h': Client.KLINE_INTERVAL_6HOUR,
    '12h': Client.KLINE_INTERVAL_12HOUR,
    '1d': Client.KLINE_INTERVAL_1DAY,
}

# DataFrame 最多保留的 K 线数量，防止内存无限增长
_MAX_CANDLES = 1000


class BinanceDataFeed:
    """
    币安实时 K 线数据源。

    流程：
    1. 从 REST API 加载历史数据，预热指标
    2. 通过 WebSocket 接收实时 K 线更新
    3. 每根 K 线收盘后回调 on_candle_close
    """

    def __init__(self, client: Client, symbol: str, interval: str, lookback: int = 300):
        self.client = client
        self.symbol = symbol.upper()
        self.interval = interval
        self.lookback = lookback
        self.df = pd.DataFrame()
        self._twm: Optional[ThreadedWebsocketManager] = None
        self._callback: Optional[Callable] = None
        self._api_key: str = ''
        self._api_secret: str = ''
        self._testnet: bool = False
        self._lock = threading.Lock()

    def load_history(self):
        """加载历史 K 线数据，预热策略指标。"""
        logger.info(
            f"加载历史数据: {self.symbol} {self.interval} "
            f"({self.lookback} 根 K 线)..."
        )
        klines = self.client.get_klines(
            symbol=self.symbol,
            interval=INTERVAL_MAP.get(self.interval, self.interval),
            limit=self.lookback,
        )
        self.df = self._parse_klines(klines)
        logger.info(f"历史数据加载完成，共 {len(self.df)} 根 K 线")

    @staticmethod
    def _parse_klines(klines: list) -> pd.DataFrame:
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore',
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df[['open', 'high', 'low', 'close', 'volume']]

    def start(self, on_candle_close: Callable, api_key: str, api_secret: str,
              testnet: bool = False):
        """启动 WebSocket 实时数据流。"""
        self._callback = on_candle_close
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._start_websocket()

    def _start_websocket(self):
        """创建并启动 WebSocket 连接。"""
        self._twm = ThreadedWebsocketManager(
            api_key=self._api_key,
            api_secret=self._api_secret,
            testnet=self._testnet,
        )
        self._twm.start()
        self._twm.start_kline_socket(
            callback=self._handle_message,
            symbol=self.symbol,
            interval=INTERVAL_MAP.get(self.interval, self.interval),
        )
        logger.info(f"WebSocket 已启动: {self.symbol} {self.interval}")

    def stop(self):
        if self._twm:
            self._twm.stop()
            logger.info("WebSocket 已停止")

    def _handle_message(self, msg: dict):
        if msg.get('e') == 'error':
            logger.error(f"WebSocket 错误: {msg.get('m')} — 尝试重连...")
            self._reconnect()
            return

        if msg.get('e') != 'kline':
            return

        k = msg['k']
        ts = pd.Timestamp(k['t'], unit='ms')
        row = {
            'open': float(k['o']),
            'high': float(k['h']),
            'low': float(k['l']),
            'close': float(k['c']),
            'volume': float(k['v']),
        }

        with self._lock:
            # 更新当前未收盘 K 线
            self.df.loc[ts] = row

            # 防止 DataFrame 无限增长，保留最近 _MAX_CANDLES 根
            if len(self.df) > _MAX_CANDLES:
                self.df = self.df.iloc[-_MAX_CANDLES:]

        if k['x']:  # K 线已收盘
            logger.info(
                f"K 线收盘 [{ts}] "
                f"O:{row['open']:.2f} H:{row['high']:.2f} "
                f"L:{row['low']:.2f} C:{row['close']:.2f}"
            )
            if self._callback:
                with self._lock:
                    df_snapshot = self.df.copy()
                self._callback(df_snapshot)

    def _reconnect(self):
        """WebSocket 断线后重新连接并补充历史数据。"""
        logger.warning("WebSocket 断线，正在重连...")
        try:
            if self._twm:
                self._twm.stop()
        except Exception:
            pass
        try:
            self.load_history()
            self._start_websocket()
            logger.info("WebSocket 重连成功")
        except Exception as e:
            logger.error(f"WebSocket 重连失败: {e}")
