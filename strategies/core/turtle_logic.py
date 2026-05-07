"""
海龟策略核心信号计算（纯 pandas，无框架依赖）。

回测（Backtrader）和实盘（live_trading）共用此模块。
"""

import pandas as pd


def calc_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """计算 ATR（真实波幅均值）。"""
    high = df['high']
    low = df['low']
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_donchian(df: pd.DataFrame, entry_period: int, exit_period: int):
    """
    计算唐奇安通道（排除当前 bar，使用前一根收盘时的通道值）。

    Returns:
        (entry_high, exit_low): 入场高点，出场低点
    """
    entry_high = df['high'].iloc[-(entry_period + 1):-1].max()
    exit_low = df['low'].iloc[-(exit_period + 1):-1].min()
    return entry_high, exit_low


def turtle_signal(
    df: pd.DataFrame,
    entry_period: int,
    exit_period: int,
    atr_period: int,
    units_held: int,
    last_entry_price: float | None,
    max_units: int,
) -> dict:
    """
    根据当前 K 线数据计算海龟策略信号。

    Args:
        df:               OHLCV DataFrame，最新数据在最后
        entry_period:     入场唐奇安通道周期
        exit_period:      出场唐奇安通道周期
        atr_period:       ATR 周期
        units_held:       当前持仓单元数
        last_entry_price: 最后一次入场价格
        max_units:        最大加仓单元数

    Returns:
        dict，包含：
            action:      'BUY' | 'SELL' | 'HOLD'
            unit_fraction: 本次买入占最大仓位的比例（仅 BUY 时有意义）
            reason:      信号原因描述
            new_units:   更新后的 units_held
            new_entry_price: 更新后的 last_entry_price
    """
    close = df['close'].iloc[-1]
    atr = calc_atr(df, atr_period).iloc[-1]
    entry_high, exit_low = calc_donchian(df, entry_period, exit_period)

    # 出场：跌破退出通道
    if units_held > 0 and close < exit_low:
        return {
            'action': 'SELL',
            'unit_fraction': 1.0,
            'reason': f'价格 {close:.2f} 跌破 {exit_period} 根低点 {exit_low:.2f}',
            'new_units': 0,
            'new_entry_price': None,
        }

    # 止损：跌破入场价 - 2×ATR
    if units_held > 0 and last_entry_price is not None and close < last_entry_price - 2 * atr:
        return {
            'action': 'SELL',
            'unit_fraction': 1.0,
            'reason': f'触发止损：入场 {last_entry_price:.2f} - 2×ATR({atr:.2f})',
            'new_units': 0,
            'new_entry_price': None,
        }

    # 入场 / 加仓：突破入场通道
    if close > entry_high and units_held < max_units:
        can_add = last_entry_price is None or close >= last_entry_price + 0.5 * atr
        if can_add:
            new_units = units_held + 1
            return {
                'action': 'BUY',
                'unit_fraction': 1.0 / max_units,
                'reason': (
                    f'突破 {entry_period} 根高点 {entry_high:.2f}，'
                    f'当前仓位 {new_units}/{max_units}'
                ),
                'new_units': new_units,
                'new_entry_price': close,
            }

    return {
        'action': 'HOLD',
        'unit_fraction': 0.0,
        'reason': '',
        'new_units': units_held,
        'new_entry_price': last_entry_price,
    }
