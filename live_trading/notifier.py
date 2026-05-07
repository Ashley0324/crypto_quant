import logging
from typing import Optional
import requests

logger = logging.getLogger('trading')


class TelegramNotifier:
    """
    可选的 Telegram 通知模块。

    在 .env 中设置 TELEGRAM_TOKEN 和 TELEGRAM_CHAT_ID 后自动启用。
    获取 token：https://t.me/BotFather
    获取 chat_id：https://t.me/userinfobot
    """

    def __init__(self, token: Optional[str], chat_id: Optional[str]):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if self.enabled:
            logger.info("Telegram 通知已启用")

    def send(self, text: str):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(
                url,
                json={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'Markdown'},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Telegram 发送失败: {e}")

    def notify_start(self, symbol: str, interval: str, strategy: str, testnet: bool):
        mode = "测试网" if testnet else "实盘"
        self.send(
            f"*交易引擎启动*\n"
            f"模式: `{mode}`\n"
            f"交易对: `{symbol}`\n"
            f"周期: `{interval}`\n"
            f"策略: `{strategy}`"
        )

    def notify_order(self, action: str, symbol: str, qty: float,
                     price: float, reason: str):
        tag = "买入" if action == 'BUY' else "卖出"
        mark = "+" if action == 'BUY' else "-"
        self.send(
            f"*{mark} {tag} {symbol}*\n"
            f"数量: `{qty:.6f}`\n"
            f"价格: `{price:.2f} USDT`\n"
            f"原因: {reason}"
        )

    def notify_halt(self, reason: str):
        self.send(f"*风控触发，交易已暂停*\n原因: {reason}")
