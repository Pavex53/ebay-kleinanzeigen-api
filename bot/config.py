from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    backend_url: str
    stripe_price_basic: str
    stripe_price_pro: str
    stripe_price_expert: str

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        return cls(
            telegram_bot_token=token,
            backend_url=os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/"),
            stripe_price_basic=os.getenv("STRIPE_PRICE_BASIC", ""),
            stripe_price_pro=os.getenv("STRIPE_PRICE_PRO", ""),
            stripe_price_expert=os.getenv("STRIPE_PRICE_EXPERT", ""),
        )
