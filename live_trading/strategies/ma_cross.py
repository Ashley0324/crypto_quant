import pandas as pd
from .base import BaseStrategy, Signal


class MACrossStrategy(BaseStrategy):
    """
    双均线交叉策略（与回测版本逻辑一致）。

    - 短期均线上穿长期均线 → 买入
    - 短期均线下穿长期均线 → 卖出

    回测最优参数（1d）: short=11, long=20
      Sharpe=1.15, 最大回撤=9.25%, 年化收益=53.42%
    """

    def __init__(self, params: dict):
        super().__init__(params)
        self.short_period = int(params.get('short_period', 11))
        self.long_period = int(params.get('long_period', 20))

    @property
    def min_candles(self) -> int:
        return self.long_period + 2

    def on_candle(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.min_candles:
            return Signal('HOLD', reason=f'数据不足 ({len(df)}/{self.min_candles})')

        close = df['close']
        short_ma = close.rolling(self.short_period).mean()
        long_ma = close.rolling(self.long_period).mean()

        prev_short = short_ma.iloc[-2]
        prev_long = long_ma.iloc[-2]
        curr_short = short_ma.iloc[-1]
        curr_long = long_ma.iloc[-1]

        if prev_short <= prev_long and curr_short > curr_long:
            return Signal(
                'BUY', 1.0,
                f'短MA({self.short_period})上穿长MA({self.long_period}) '
                f'[{curr_short:.2f} > {curr_long:.2f}]'
            )

        if prev_short >= prev_long and curr_short < curr_long:
            return Signal(
                'SELL', 1.0,
                f'短MA({self.short_period})下穿长MA({self.long_period}) '
                f'[{curr_short:.2f} < {curr_long:.2f}]'
            )

        return Signal('HOLD')
