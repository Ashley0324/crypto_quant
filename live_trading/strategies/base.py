from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    action: str                        # 'BUY' | 'SELL' | 'HOLD'
    size_pct: float = 1.0              # 占允许仓位的比例（0.0 ~ 1.0）
    reason: str = ''
    order_type: str = 'MARKET'         # 'MARKET' | 'LIMIT'
    limit_price: Optional[float] = None  # 限价单价格，order_type='LIMIT' 时必填

    def __str__(self):
        price_str = f' @ {self.limit_price:.4f}' if self.limit_price else ''
        return f"{self.action} [{self.order_type}{price_str}] ({self.size_pct:.0%}) | {self.reason}"


class BaseStrategy(ABC):
    """所有实盘策略的基类。"""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def on_candle(self, df: pd.DataFrame) -> Signal:
        """
        每根 K 线收盘时调用。

        Args:
            df: 包含 [open, high, low, close, volume] 列的 DataFrame，
                以时间戳为索引，最新数据在最后。

        Returns:
            Signal 信号对象
        """
        ...

    @property
    def min_candles(self) -> int:
        """产生信号所需的最少 K 线数量。"""
        return 50
