import pandas as pd
import numpy as np
from .base import BaseStrategy, Signal


class TurtleStrategy(BaseStrategy):
    """
    海龟交易策略（与回测版本逻辑一致）。

    - 入场：价格突破过去 N 根 K 线的最高价
    - 出场：价格跌破过去 M 根 K 线的最低价
    - 止损：距入场价 2×ATR
    - 加仓：最多加仓至 max_units 个单位（每 0.5×ATR 加一次）

    回测最优参数（1h）: entry=10, exit=30, atr=15
      Sharpe=1.16, 最大回撤=14.8%, 年化收益=42.82%
    """

    def __init__(self, params: dict):
        super().__init__(params)
        self.entry_period = int(params.get('entry_period', 10))
        self.exit_period = int(params.get('exit_period', 30))
        self.atr_period = int(params.get('atr_period', 15))
        self.risk_per_trade = float(params.get('risk_per_trade', 0.01))
        self.max_units = int(params.get('max_units', 4))

        # 运行时状态
        self.units_held: int = 0
        self.last_entry_price: float | None = None

    @property
    def min_candles(self) -> int:
        return max(self.entry_period, self.exit_period, self.atr_period) + 2

    def _calc_atr(self, df: pd.DataFrame) -> pd.Series:
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(self.atr_period).mean()

    def on_candle(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal('HOLD', reason=f'数据不足 ({len(df)}/{self.min_candles})')

        close = df['close'].iloc[-1]
        atr = self._calc_atr(df).iloc[-1]

        # 使用前一根 K 线的唐奇安通道（排除当前 bar）
        entry_high = df['high'].iloc[-(self.entry_period + 1):-1].max()
        exit_low = df['low'].iloc[-(self.exit_period + 1):-1].min()

        # 出场：价格跌破退出通道
        if self.units_held > 0 and close < exit_low:
            self.units_held = 0
            self.last_entry_price = None
            return Signal(
                'SELL', 1.0,
                f'价格 {close:.2f} 跌破 {self.exit_period} 根低点 {exit_low:.2f}'
            )

        # 止损：价格跌破入场价 - 2×ATR
        if (self.units_held > 0
                and self.last_entry_price is not None
                and close < self.last_entry_price - 2 * atr):
            entry_price = self.last_entry_price  # 保存引用，置 None 前记录日志
            self.units_held = 0
            self.last_entry_price = None
            return Signal(
                'SELL', 1.0,
                f'触发止损：入场 {entry_price:.2f} - 2×ATR({atr:.2f})'
            )

        # 入场/加仓：价格突破入场通道
        if close > entry_high and self.units_held < self.max_units:
            can_add = (
                self.last_entry_price is None
                or close >= self.last_entry_price + 0.5 * atr
            )
            if can_add:
                self.units_held += 1
                self.last_entry_price = close
                unit_fraction = 1.0 / self.max_units
                return Signal(
                    'BUY', unit_fraction,
                    f'突破 {self.entry_period} 根高点 {entry_high:.2f}，'
                    f'当前仓位 {self.units_held}/{self.max_units}'
                )

        return Signal('HOLD')
