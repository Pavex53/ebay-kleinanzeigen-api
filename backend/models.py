"""
Database models for Kleinanzeigen SaaS backend.
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class SubscriptionStatus(str, Enum):
    """Stripe subscription statuses."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    CANCELED = "canceled"
    TRIALING = "trialing"


class PlanTier(str, Enum):
    """Subscription plan tiers."""
    BASIC = "basic"
    PRO = "pro"
    EXPERT = "expert"


class User(Base):
    """User table - stores all registered users."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=True)  # Optional, falls du Login willst
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    searches = relationship("Search", back_populates="user", cascade="all, delete-orphan")
    telegram_accounts = relationship("TelegramAccount", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_user_id={self.telegram_user_id})>"


class Subscription(Base):
    """Subscription table - stores Stripe subscription info per user."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_customer_id = Column(String, nullable=False, index=True)
    stripe_subscription_id = Column(String, nullable=True, unique=True, index=True)
    plan_tier = Column(SQLEnum(PlanTier), nullable=False, default=PlanTier.BASIC)
    status = Column(SQLEnum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.ACTIVE)
    current_period_end = Column(DateTime, nullable=False)
    interval_minutes = Column(Integer, nullable=False, default=30)  # 30, 10, or 1
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="subscriptions")

    def is_active(self) -> bool:
        """Check if subscription is currently active."""
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.current_period_end > datetime.utcnow()
        )

    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, tier={self.plan_tier}, status={self.status})>"


class Search(Base):
    """Search table - stores user's search configurations."""
    __tablename__ = "searches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)  # User-defined name for the search
    query = Column(String, nullable=False)  # Search keyword(s)
    location = Column(String, nullable=True)  # City/Location
    radius = Column(Integer, nullable=True, default=0)  # Radius in km
    price_from = Column(Float, nullable=True)  # Minimum price
    price_to = Column(Float, nullable=True)  # Maximum price
    category = Column(String, nullable=True)  # Category ID or name
    shipping_only = Column(Boolean, default=False, nullable=False)  # Only shipping offers
    condition = Column(String, nullable=True)  # e.g., "new", "like_new", "good", "ok"
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_polled_at = Column(DateTime, nullable=True)  # Last time this search was executed

    # Relationships
    user = relationship("User", back_populates="searches")
    results = relationship("SearchResult", back_populates="search", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Search(id={self.id}, user_id={self.user_id}, query={self.query})>"


class SearchResult(Base):
    """SearchResult table - stores found listings to detect new ones."""
    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_id = Column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    inserat_id = Column(String, nullable=False, index=True)  # Kleinanzeigen listing ID
    title = Column(String, nullable=False)
    price = Column(Float, nullable=True)
    url = Column(String, nullable=False)
    location = Column(String, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_new = Column(Boolean, default=True, nullable=False, index=True)  # True if not yet notified
    notified_at = Column(DateTime, nullable=True)  # When user was notified

    # Relationships
    search = relationship("Search", back_populates="results")

    def __repr__(self):
        return f"<SearchResult(id={self.id}, search_id={self.search_id}, inserat_id={self.inserat_id})>"


class TelegramAccount(Base):
    """TelegramAccount table - links Telegram users to their accounts."""
    __tablename__ = "telegram_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    telegram_user_id = Column(String, nullable=False, unique=True, index=True)
    telegram_username = Column(String, nullable=True)  # @username
    is_enabled = Column(Boolean, default=True, nullable=False)  # User can disable notifications
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="telegram_accounts")

    def __repr__(self):
        return f"<TelegramAccount(id={self.id}, user_id={self.user_id}, telegram_user_id={self.telegram_user_id})>"
