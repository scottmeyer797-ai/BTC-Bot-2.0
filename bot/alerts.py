"""Optional Discord / Telegram alerts. Never raises: alerts must not break a run."""
from __future__ import annotations

import logging

import requests

from .config import Config

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, cfg: Config, dry_run: bool = False):
        self.cfg = cfg
        self.prefix = f"[BloFin demo · {cfg.mode.name}{' · DRY RUN' if dry_run else ''}] "
        self.sent: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.discord_webhook or (self.cfg.telegram_token and self.cfg.telegram_chat_id))

    def send(self, text: str) -> None:
        msg = self.prefix + text
        self.sent.append(msg)
        log.info("ALERT %s", msg)
        if self.cfg.discord_webhook:
            try:
                r = requests.post(self.cfg.discord_webhook, json={"content": msg[:1900]}, timeout=10)
                if r.status_code >= 300:
                    log.warning("Discord webhook returned HTTP %s", r.status_code)
            except requests.RequestException as e:
                log.warning("Discord alert failed: %s", type(e).__name__)
        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            try:
                r = requests.post(f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                                  json={"chat_id": self.cfg.telegram_chat_id, "text": msg[:4000]}, timeout=10)
                if r.status_code >= 300:
                    log.warning("Telegram returned HTTP %s", r.status_code)
            except requests.RequestException as e:
                log.warning("Telegram alert failed: %s", type(e).__name__)
