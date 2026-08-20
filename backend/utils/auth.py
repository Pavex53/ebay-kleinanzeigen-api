"""
Authentication and authorization utilities for Kleinanzeigen SaaS.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import User, Subscription, PlanTier


# Plan tier to interval mapping (in minutes)
PLAN_INTERVALS = {
    PlanTier.BASIC: 30,
    PlanTier.PRO: 10,
    PlanTier.EXPERT: 1,
}


def get_active_subscription(db: Session, user_id: int) -> Subscription | None:
    """
    Get the active subscription for a user.
    
    Returns None if no active subscription exists.
    """
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.current_period_end > datetime.utcnow()
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return subscription


def is_subscriber_active(db: Session, user_id: int) -> bool:
    """
    Check if a user has an active subscription.
    
    Returns True if user can access premium features.
    """
    subscription = get_active_subscription(db, user_id)
    return subscription is not None


def get_poll_interval(db: Session, user_id: int) -> int | None:
    """
    Get the polling interval (in minutes) for a user's subscription.
    
    Returns None if user has no active subscription.
    Returns interval_minutes from subscription (30, 10, or 1).
    """
    subscription = get_active_subscription(db, user_id)
    if subscription is None:
        return None
    return subscription.interval_minutes


def get_plan_tier(db: Session, user_id: int) -> PlanTier | None:
    """
    Get the plan tier for a user's subscription.
    
    Returns None if user has no active subscription.
    """
    subscription = get_active_subscription(db, user_id)
    if subscription is None:
        return None
    return subscription.plan_tier


def check_subscription_access(db: Session, user_id: int) -> dict:
    """
    Check subscription status and return access info.
    
    Returns dict with:
    - has_access: bool
    - plan_tier: str | None
    - interval_minutes: int | None
    - current_period_end: datetime | None
    """
    subscription = get_active_subscription(db, user_id)
    
    if subscription is None:
        return {
            "has_access": False,
            "plan_tier": None,
            "interval_minutes": None,
            "current_period_end": None,
        }
    
    return {
        "has_access": True,
        "plan_tier": subscription.plan_tier.value,
        "interval_minutes": subscription.interval_minutes,
        "current_period_end": subscription.current_period_end,
    }
