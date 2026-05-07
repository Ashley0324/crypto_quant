"""
本地 K 线数据缓存管理。

使用方式：
    from data.binance import get_klines

    df = get_klines('BTCUSDT', '1h')   # 自动增量更新本地缓存
    df = get_klines('BTCUSDT', '1d', lookback_days=600)

缓存文件保存在 data/cache/{symbol}_{interval}.csv。
每次调用时检查本地最新时间戳，只从 API 拉取缺失部分并追加，
避免重复下载全量数据。
"""

import os
import datetime
import logging
import pandas as pd
from binance.client import Client

logger = logging.getLogger('trading')

_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
_COLUMNS = ['open', 'high', 'low', 'close', 'volume']


def _cache_path(symbol: str, interval: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f'{symbol}_{interval}.csv')


def _parse_klines(klines: list) -> pd.DataFrame:
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore',
    ])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    return df[_COLUMNS].astype(float)


def _fetch_from_api(client: Client, symbol: str, interval: str,
                    start: datetime.datetime, end: datetime.datetime) -> pd.DataFrame:
    """从 Binance API 拉取指定时间范围的 K 线。"""
    klines = client.get_historical_klines(
        symbol,
        interval,
        start_str=start.strftime('%d %b %Y %H:%M:%S'),
        end_str=end.strftime('%d %b %Y %H:%M:%S'),
    )
    if not klines:
        return pd.DataFrame(columns=_COLUMNS)
    return _parse_klines(klines)


def get_klines(
    symbol: str = 'BTCUSDT',
    interval: str = '1h',
    lookback_days: int = 365,
    client: Client = None,
) -> pd.DataFrame:
    """
    获取 K 线数据，优先使用本地缓存，自动增量更新。

    Args:
        symbol:        交易对，如 'BTCUSDT'
        interval:      K 线周期，如 '1h' / '1d' / '4h'
        lookback_days: 首次下载时的历史天数（缓存存在时忽略此参数）
        client:        Binance Client 实例，不传则创建匿名客户端

    Returns:
        DataFrame，列为 [open, high, low, close, volume]，索引为 datetime
    """
    if client is None:
        client = Client()

    path = _cache_path(symbol.upper(), interval)
    now = datetime.datetime.utcnow()

    # ----------------------------------------------------------------
    # 读取本地缓存
    # ----------------------------------------------------------------
    if os.path.exists(path):
        cached = pd.read_csv(path, index_col='datetime', parse_dates=True)
        cached = cached[_COLUMNS].astype(float)

        latest_ts = cached.index.max()
        # 最新缓存时间到现在之间有缺口才去拉增量
        gap_seconds = (now - latest_ts.to_pydatetime().replace(tzinfo=None)).total_seconds()

        if gap_seconds < 60:
            # 缓存已是最新，直接返回
            logger.info(f'[缓存] {symbol} {interval}: 已是最新，共 {len(cached)} 根')
            return cached

        # 从最新时间戳之后拉增量（+1ms 避免重复）
        fetch_start = latest_ts.to_pydatetime().replace(tzinfo=None) + datetime.timedelta(milliseconds=1)
        logger.info(
            f'[缓存] {symbol} {interval}: 本地 {len(cached)} 根，'
            f'增量拉取 {fetch_start.strftime("%Y-%m-%d %H:%M")} 至今...'
        )
        new_data = _fetch_from_api(client, symbol, interval, fetch_start, now)

        if new_data.empty:
            logger.info(f'[缓存] {symbol} {interval}: 无新数据')
            return cached

        # 去重合并（以防时间戳重叠）
        combined = pd.concat([cached, new_data])
        combined = combined[~combined.index.duplicated(keep='last')]
        combined.sort_index(inplace=True)

        # 去掉最后一根未收盘的 K 线（当前正在运行的那根）
        combined = combined.iloc[:-1]

        combined.to_csv(path, index=True)
        logger.info(
            f'[缓存] {symbol} {interval}: 新增 {len(new_data)} 根，'
            f'共 {len(combined)} 根，已保存'
        )
        return combined

    # ----------------------------------------------------------------
    # 缓存不存在，全量下载
    # ----------------------------------------------------------------
    start = now - datetime.timedelta(days=lookback_days)
    logger.info(
        f'[缓存] {symbol} {interval}: 首次下载 {lookback_days} 天历史数据...'
    )
    df = _fetch_from_api(client, symbol, interval, start, now)

    if df.empty:
        logger.warning(f'[缓存] {symbol} {interval}: API 返回空数据')
        return df

    # 去掉最后一根未收盘的 K 线
    df = df.iloc[:-1]

    df.to_csv(path, index=True)
    logger.info(f'[缓存] {symbol} {interval}: 下载完成，共 {len(df)} 根，已保存至 {path}')
    return df
