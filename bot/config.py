"""Configuration, strategy constants and the demo-only guard.

Everything tunable by the operator comes from environment variables. Strategy
constants are fixed in code on purpose: the bot is a forward test of a specific
strategy, so they must not drift between runs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Demo-only guard
# ---------------------------------------------------------------------------
DEMO_BASE_URL = "https://demo-trading-openapi.blofin.com"


class LiveEndpointRefused(RuntimeError):
    """Raised when anything other than the BloFin demo endpoint is configured."""


def assert_demo_url(url: str | None) -> str:
    """Refuse to run unless `url` is exactly the BloFin demo REST endpoint."""
    if url is None or url.rstrip("/") != DEMO_BASE_URL:
        raise LiveEndpointRefused(
            f"Refusing to start: base URL {url!r} is not the BloFin demo URL {DEMO_BASE_URL}. "
            "This bot only ever trades on BloFin demo."
        )
    return DEMO_BASE_URL


# ---------------------------------------------------------------------------
# Strategy constants (implemented exactly as specified)
# ---------------------------------------------------------------------------
UNIVERSE = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "LINK", "SOL", "DOT", "AVAX"]
QUOTE = "USDT"
BAR = "4H"
BAR_MS = 4 * 60 * 60 * 1000

ATR_PERIOD = 14
VOL_Z_PERIOD = 50
VOL_Z_MIN = 2.0
VOL_RANK_WINDOW = 1000
VOL_RANK_MIN_BARS = 300
SWING_SIDE_DAYS = 5
LEVEL_LOOKBACK_DAYS = 365
BTC_SMA_DAYS = 200

BREAK_ATR = 0.2
STOP_ATR = 0.5
MIN_STOP_PCT = 0.003
MAX_STOP_PCT = 0.10
COOLDOWN_BARS = 6
TIME_EXIT_BARS = 60
LOSS_STREAK_HALVE = 3
MAX_LEVERAGE = 5

DAILY_LOSS_LIMIT = 0.05
MAX_DRAWDOWN_LIMIT = 0.10

# 4h history to load: 365d levels + 10 swing days + 200d SMA headroom + 90d replay.
HISTORY_BARS = 3400


@dataclass(frozen=True)
class ModeParams:
    name: str
    target_r: float
    risk_pct: float
    max_open_risk: float
    daily_block: float      # pre-trade block threshold for the daily-loss guard
    drawdown_block: float   # pre-trade block threshold for the max-drawdown guard
    btc_trend_filter: bool
    vol_rank_max: float | None


MODES = {
    "challenge": ModeParams("challenge", 3.0, 0.020, 0.04, 0.05, 0.10, False, None),
    "funded": ModeParams("funded", 5.0, 0.0075, 0.03, 0.045, 0.09, True, 0.90),
}


def _env_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Config:
    mode: ModeParams
    account_size: float
    bot_enabled: bool
    repo_root: Path
    state_dir: Path
    cache_dir: Path
    base_url: str = DEMO_BASE_URL
    api_key: str | None = field(default=None, repr=False)
    api_secret: str | None = field(default=None, repr=False)
    passphrase: str | None = field(default=None, repr=False)
    discord_webhook: str | None = field(default=None, repr=False)
    telegram_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = field(default=None, repr=False)

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def report_dir(self) -> Path:
        return self.state_dir / "reports"

    def stop_file_present(self) -> bool:
        return (self.repo_root / "STOP").exists() or (self.state_dir / "STOP").exists()

    @property
    def kill_switch(self) -> bool:
        return (not self.bot_enabled) or self.stop_file_present()


def load_config(env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    mode_name = env.get("MODE", "challenge").strip().lower()
    if mode_name not in MODES:
        raise ValueError(f"MODE must be one of {sorted(MODES)}, got {mode_name!r}")
    base_url = assert_demo_url(env.get("BLOFIN_BASE_URL", DEMO_BASE_URL))
    repo_root = Path(env.get("REPO_ROOT", Path(__file__).resolve().parent.parent))
    state_dir = Path(env.get("STATE_DIR", repo_root / "state"))
    cache_dir = Path(env.get("CACHE_DIR", repo_root / "data" / "cache"))
    enabled = _env_bool(env.get("BOT_ENABLED"), True)
    return Config(
        mode=MODES[mode_name],
        account_size=float(env.get("ACCOUNT_SIZE", "100000")),
        bot_enabled=enabled,
        repo_root=repo_root,
        state_dir=state_dir,
        cache_dir=cache_dir,
        base_url=base_url,
        api_key=env.get("BLOFIN_API_KEY") or None,
        api_secret=env.get("BLOFIN_API_SECRET") or None,
        passphrase=env.get("BLOFIN_PASSPHRASE") or None,
        discord_webhook=env.get("DISCORD_WEBHOOK_URL") or None,
        telegram_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
    )
