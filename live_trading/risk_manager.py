import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger('trading')

# 触发原因前缀，用于区分是否可自动恢复
_DAILY_HALT_PREFIX = '日亏损'


@dataclass
class RiskState:
    peak_value: float = 0.0
    daily_start_value: float = 0.0
    daily_start_date: date = field(default_factory=date.today)
    trading_halted: bool = False
    halt_reason: str = ''


class RiskManager:
    """
    风控管理器。

    功能：
    - 仓位规模计算（按余额百分比）
    - 最大回撤保护（从历史峰值计算）
    - 日亏损限制（每日自动重置）
    """

    def __init__(
        self,
        max_position_pct: float = 0.95,
        max_drawdown_pct: float = 0.15,
        daily_loss_limit_pct: float = 0.05,
    ):
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.state = RiskState()

    def update(self, total_value: float):
        """更新峰值和日内起始资产；次日自动重置日亏损暂停。"""
        today = date.today()
        if self.state.daily_start_date != today:
            self.state.daily_start_value = total_value
            self.state.daily_start_date = today
            # 日亏损触发的暂停在新的一天自动解除
            if (self.state.trading_halted
                    and self.state.halt_reason.startswith(_DAILY_HALT_PREFIX)):
                logger.info("新的一天，日亏损限制已重置，恢复交易")
                self.state.trading_halted = False
                self.state.halt_reason = ''

        if self.state.daily_start_value == 0:
            self.state.daily_start_value = total_value

        if total_value > self.state.peak_value:
            self.state.peak_value = total_value

    def check(self, total_value: float) -> bool:
        """
        检查是否触发风控。
        返回 True 表示可以继续交易，False 表示需要暂停。
        """
        if self.state.trading_halted:
            logger.warning(f"交易已暂停: {self.state.halt_reason}")
            return False

        # 最大回撤检查
        if self.state.peak_value > 0:
            drawdown = (self.state.peak_value - total_value) / self.state.peak_value
            if drawdown >= self.max_drawdown_pct:
                self._halt(
                    f"最大回撤 {drawdown:.1%} 超限 {self.max_drawdown_pct:.1%}"
                )
                return False

        # 日亏损检查
        if self.state.daily_start_value > 0:
            daily_loss = (
                (self.state.daily_start_value - total_value)
                / self.state.daily_start_value
            )
            if daily_loss >= self.daily_loss_limit_pct:
                self._halt(
                    f"{_DAILY_HALT_PREFIX} {daily_loss:.1%} 超限 {self.daily_loss_limit_pct:.1%}"
                )
                return False

        return True

    def _halt(self, reason: str):
        self.state.trading_halted = True
        self.state.halt_reason = reason
        logger.error(f"风控触发 — {reason}")

    def order_amount(self, balance: float, size_pct: float = 1.0) -> float:
        """计算本次下单金额（USDT）。"""
        return balance * self.max_position_pct * size_pct
