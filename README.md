# Crypto Quant

基于 Binance API 的加密货币量化交易系统，包含策略回测框架和实盘交易引擎。

## 项目结构

```
crypto_quant/
├── strategies/                  # 回测策略（Backtrader）
│   ├── MovingAverageCrossStrategy.py
│   ├── TurtleStrategy.py
│   ├── BollingerBandsStrategy.py
│   ├── FundingRateArbitrage.py
│   └── MatingaleStrategy.py
├── live_trading/                # 实盘交易引擎
│   ├── main.py                  # 启动入口
│   ├── engine.py                # 交易引擎（核心编排）
│   ├── broker.py                # 订单执行 & 账户管理
│   ├── data_feed.py             # 实时 K 线数据源（WebSocket）
│   ├── risk_manager.py          # 风控管理
│   ├── notifier.py              # Telegram 通知
│   ├── config.py                # 配置加载
│   ├── logger.py                # 日志配置
│   └── strategies/              # 实盘策略
│       ├── base.py              # 策略基类
│       ├── ma_cross.py          # 双均线交叉
│       └── turtle.py            # 海龟策略
├── statistics/                  # 统计分析工具
├── data/                        # 本地 K 线缓存
├── config.yaml                  # 实盘配置文件
├── .env                         # API 密钥（不提交 git）
├── Dockerfile                   # 容器部署
└── requirements.txt
```

## 架构设计

### 实盘引擎架构

```
                        ┌─────────────────────────────────────┐
                        │           TradingEngine              │
                        │                                     │
  Binance REST ─────────┤  BinanceDataFeed                    │
  Binance WS  ─────────►│    └─ load_history()                │
                        │    └─ start() / _handle_message()   │
                        │         │ on_candle_close            │
                        │         ▼                           │
                        │  Strategy.on_candle(df)             │
                        │    └─ Signal(BUY/SELL/HOLD)         │
                        │         │                           │
                        │         ▼                           │
                        │  RiskManager.check()                │
                        │    └─ 回撤/日亏损检查               │
                        │         │ 通过                      │
                        │         ▼                           │
                        │  BinanceBroker                      │
                        │    └─ buy_market() / sell_all()     │
                        │    └─ newClientOrderId (broker tag) │
                        │         │                           │
                        │         ▼                           │
                        │  TelegramNotifier + CSV 日志        │
                        └─────────────────────────────────────┘
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `engine.py` | 编排所有模块，处理每根 K 线收盘事件 |
| `data_feed.py` | REST 加载历史数据 + WebSocket 实时推送，断线自动重连 |
| `broker.py` | 市价下单，自动处理数量精度，附加 broker ID 返佣标签 |
| `risk_manager.py` | 最大回撤保护 + 日亏损限制，日亏损次日自动解除 |
| `notifier.py` | Telegram 推送交易信号和风控告警 |
| `config.py` | YAML + 环境变量双层配置 |

### 数据流

```
历史 K 线 (REST)
      │
      ▼
  DataFrame (预热指标)
      │
      │◄── WebSocket 实时更新（每 tick 更新未收盘 K 线）
      │
  K 线收盘事件
      │
      ▼
  策略计算信号
      │
      ▼
  风控校验
      │
      ▼
  下单执行 ──► 日志 + Telegram
```

### 风控逻辑

- **最大回撤**：从历史峰值回撤超过阈值（默认 15%），永久暂停，需手动重启
- **日亏损限制**：当日亏损超过阈值（默认 5%），暂停至次日自动恢复
- **仓位控制**：每次最多使用 USDT 余额的 95%

## 已实现策略

### 双均线交叉（ma_cross）

短期均线上穿长期均线买入，下穿卖出。

| 周期 | Short | Long | 年化收益 | Sharpe | 最大回撤 |
|------|-------|------|---------|--------|---------|
| 1d   | 11    | 20   | 53.42%  | 1.15   | 9.25%   |

### 海龟策略（turtle）

唐奇安通道突破入场，ATR 动态止损，最多加仓 4 次。

| 周期 | Entry | Exit | ATR | 年化收益 | Sharpe | 最大回撤 |
|------|-------|------|-----|---------|--------|---------|
| 1h   | 10    | 30   | 15  | 42.82%  | 1.16   | 14.8%   |

### 布林带策略（回测）

利用移动平均线和标准差追踪价格波动区间。

### 资金费率套利（回测）

利用永续合约资金费率进行现货/合约对冲套利。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥

将 `.env copy` 重命名为 `.env` 并填入密钥：

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# 可选：Telegram 通知
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

> 注意：`.env` 文件已在 `.gitignore` 中，切勿提交到 git。

### 3. 修改配置

编辑 `config.yaml`：

```yaml
symbol: BTCUSDT
interval: 1h
testnet: true        # 改为 false 开启实盘
strategy: ma_cross   # 可选: ma_cross | turtle
```

### 4. 启动实盘引擎

```bash
# 测试网（默认）
python -m live_trading.main

# 指定策略和交易对
python -m live_trading.main --strategy turtle --symbol ETHUSDT --interval 4h

# 实盘（会要求二次确认）
python -m live_trading.main --live
```

### 5. 运行回测

```bash
python strategies/MovingAverageCrossStrategy.py
python strategies/TurtleStrategy.py
```

### 6. Docker 部署

```bash
docker build -t crypto-quant .
docker run -d --env-file .env crypto-quant
```

## 日志与记录

- 运行日志：`logs/trading_YYYY-MM-DD.log`
- 交易记录：`logs/trades.csv`（含时间、方向、数量、价格、原因、余额）

## 扩展新策略

1. 在 `live_trading/strategies/` 下新建文件，继承 `BaseStrategy`
2. 实现 `on_candle(df) -> Signal` 方法
3. 在 `live_trading/strategies/__init__.py` 的 `STRATEGIES` 字典中注册
4. 在 `config.yaml` 的 `strategy_params` 下添加参数

```python
from .base import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    @property
    def min_candles(self) -> int:
        return 50

    def on_candle(self, df) -> Signal:
        # 你的策略逻辑
        return Signal('BUY', 1.0, '信号原因')
```

## 免责声明

仅供技术学习交流，不构成投资建议。加密货币交易风险极高，请自行评估风险。

---

交流讨论：
- Issue / PR：[github.com/Ashley0324/crypto_quant](https://github.com/Ashley0324/crypto_quant)
- Email：ashleyjin0324@gmail.com
- Telegram 群：https://t.me/+PMkkHh0IfVU4ZTJl
- 微信公众号：泡芙写字的地方
