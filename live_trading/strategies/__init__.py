from .ma_cross import MACrossStrategy
from .turtle import TurtleStrategy

STRATEGIES = {
    'ma_cross': MACrossStrategy,
    'turtle': TurtleStrategy,
}


def get_strategy(name: str, params: dict):
    if name not in STRATEGIES:
        raise ValueError(
            f"未知策略 '{name}'。可用策略: {list(STRATEGIES.keys())}"
        )
    return STRATEGIES[name](params)
