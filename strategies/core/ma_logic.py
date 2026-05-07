"""
双均线交叉策略核心信号计算（纯 pandas，无框架依赖）。

回测（Backtrader）和实盘（live_trading）共用此模块。
"""

import pandas as pd


def calc_ma(close: pd.Series, short_period: int, long_period: int):
    """
    计算短期和长期简单移动平均线。

    Returns:
        (short_ma, long_ma): 两条均线的 Series
    """
    short_ma = close.rolling(short_period).mean()
    long_ma = close.rolling(long_period).mean()
    return short_ma, long_ma


def ma_cross_signal(
    df: pd.DataFrame,
    short_period: int,
    long_period: int,
) -> dict:
    """
    根据当前 K 线数据计算双均线交叉信号。

    Args:
        df:            OHLCV DataFrame，最新数据在最后
        short_period:  短期均线周期
        long_period:   长期均线周期

    Returns:
        dict，包含：
            action: 'BUY' | 'SELL' | 'HOLD'
            reason: 信号原因描述
    """
    close = df['close']
    short_ma, long_ma = calc_ma(close, short_period, long_period)

    prev_short = short_ma.iloc[-2]
    prev_long = long_ma.iloc[-2]
    curr_short = short_ma.iloc[-1]
    curr_long = long_ma.iloc[-1]

    if prev_short <= prev_long and curr_short > curr_long:
        return {
            'action': 'BUY',
            'reason': (
                f'短MA({short_period})上穿长MA({long_period}) '
                f'[{curr_short:.2f} > {curr_long:.2f}]'
            ),
        }

    if prev_short >= prev_long and curr_short < curr_long:
        return {
            'action': 'SELL',
            'reason': (
                f'短MA({short_period})下穿长MA({long_period}) '
                f'[{curr_short:.2f} < {curr_long:.2f}]'
            ),
        }

    return {'action': 'HOLD', 'reason': ''}
