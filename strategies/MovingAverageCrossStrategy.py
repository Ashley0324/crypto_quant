from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from data.binance import get_klines

# backtrader 数据接口
class PandasData(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', -1),
    )

# 定义移动平均线策略
class MovingAverageCrossStrategy(bt.Strategy):
    params = (
        ('short_period', 10),
        ('long_period', 30),
    )

    def __init__(self):
        self.sma_short = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.short_period)
        self.sma_long = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.long_period)
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None  # 当前挂单
        self.buy_price = None

    def next(self):
        if self.order:
            return  # 如果有挂单在等待，就不下新单

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()
        elif self.crossover < 0:
            self.order = self.sell()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return  # 订单提交中，忽略

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                # print(f'🟢 买入: {order.executed.price:.2f} @ {bt.num2date(order.executed.dt)}')
            elif order.issell():
                pnl = order.executed.price - self.buy_price
                pnl_pct = (pnl / self.buy_price) * 100
                # print(f'🔴 卖出: {order.executed.price:.2f} @ {bt.num2date(order.executed.dt)}')
                # print(f'💰 本次盈亏: {pnl:.2f} USDT ({pnl_pct:.2f}%)')

        self.order = None  # 重置订单引用

    def notify_trade(self, trade):
        if trade.isclosed:
            return
            # print(f'✅ 交易完成: 毛利: {trade.pnl:.2f} USDT, 净利: {trade.pnlcomm:.2f} USDT')

# 设置Backtrader
def run_backtest_and_plot(interval, short_period, long_period, plot=False):
    if short_period >= long_period:
        return None  # 这句很重要，避免无效数据加入结果

    df = get_klines(interval=interval)
    data = PandasData(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0008)
    cerebro.adddata(data)
    cerebro.addstrategy(
        MovingAverageCrossStrategy,
        short_period=short_period,
        long_period=long_period
    )

    # 调用分析器，进行结果分析
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    results = cerebro.run()
    strat = results[0]

    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0)
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()

    rtot = returns.get('rtot', 0)
    annual = returns.get('rnorm')
    average = returns.get('ravg')
    maxdd = drawdown['max']['drawdown'] if 'max' in drawdown else 0

    # 输出结果
    print(f"[{interval}] short={short_period}, long={long_period} | Sharpe: {sharpe:.2f}, Return: {rtot*100:.2f}%, MaxDD: {maxdd:.2f}%,anunual return:{annual*100:.2f}%,average return:{average*100:.2f}%")

    # 绘制图表
    if plot:
        cerebro.plot(
            style='candlestick',
            barup='green',
            bardown='red',
            grid=True,
            volume=True,
            figsize=(18, 9),
            dpi=120
        )

    return {
        'interval': interval,
        'short': short_period,
        'long': long_period,
        'sharpe': sharpe,
        'return': rtot,
        'maxdd': maxdd,
        'annual':annual,
        'average':average,
    }

def main():
    best_result = None
    best_return = -float('inf')  # 初始为负无穷
    all_results = []

    intervals = ['1d', '12h']
    short_range = range(5, 21, 3)
    long_range = range(20, 61, 5)

    print("🔍 正在进行参数优化...\n")

    for interval in intervals:
        for short_p in short_range:
            for long_p in long_range:
                result = run_backtest_and_plot(interval, short_p, long_p, plot=False)
                if result:
                    all_results.append(result)
                    if result['return'] > best_return:
                        best_return = result['return']
                        best_result = result

    print("\n🏆 最佳参数组合:")
    print(f"周期: {best_result['interval']}, short={best_result['short']}, long={best_result['long']}")
    print(f"🔹 Sharpe Ratio:  {best_result['sharpe']:.2f}")
    print(f"🔹 Max Drawdown:  {best_result['maxdd']:.2f}%")
    print(f"🔹 Total Return: {best_result['return']*100:.2f}%")
    print(f"🔹 Annual Return: {best_result['annual']*100:.2f}%")
    print(f"🔹 Average Return: {best_result['average']*100:.2f}%")

    print("\n📈 使用最佳参数重新运行并绘图...")
    run_backtest_and_plot(
        interval=best_result['interval'],
        short_period=best_result['short'],
        long_period=best_result['long'],
        plot=True
    )


if __name__ == '__main__':
    main()