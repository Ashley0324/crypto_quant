import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class RiskConfig:
    max_position_pct: float = 0.95       # 最大仓位比例（占 USDT 余额的百分比）
    max_drawdown_pct: float = 0.15       # 最大回撤，超过则停止交易
    daily_loss_limit_pct: float = 0.05  # 日亏损限制，超过则停止交易


@dataclass
class BrokerConfig:
    spot_id: str = 'YD783Z4B'       # 现货 Broker ID（返佣）
    futures_id: str = 'ethkXc9Q'    # 合约 Broker ID（返佣）


@dataclass
class Config:
    symbol: str = 'BTCUSDT'
    interval: str = '1h'
    testnet: bool = True
    strategy: str = 'ma_cross'
    risk: RiskConfig = field(default_factory=RiskConfig)
    broker_config: BrokerConfig = field(default_factory=BrokerConfig)
    strategy_params: Dict[str, Any] = field(default_factory=dict)

    @property
    def api_key(self) -> str:
        # 同时兼容 BINANCE_API_KEY 和 API_KEY
        return os.getenv('BINANCE_API_KEY') or os.getenv('API_KEY', '')

    @property
    def api_secret(self) -> str:
        return os.getenv('BINANCE_API_SECRET') or os.getenv('API_SECRET', '')

    @property
    def telegram_token(self) -> Optional[str]:
        return os.getenv('TELEGRAM_TOKEN') or None

    @property
    def telegram_chat_id(self) -> Optional[str]:
        return os.getenv('TELEGRAM_CHAT_ID') or None


def load_config(path: str = 'config.yaml') -> Config:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[警告] 配置文件 '{path}' 未找到，使用默认参数。")
        return Config()

    risk_data = data.pop('risk', {})
    risk = RiskConfig(**risk_data)
    broker_data = data.pop('broker_config', {})
    broker_cfg = BrokerConfig(**broker_data) if broker_data else BrokerConfig()
    return Config(risk=risk, broker_config=broker_cfg, **data)
