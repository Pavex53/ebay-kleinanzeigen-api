"""
Stripe service for handling payments, subscriptions, and webhooks.
"""

import os
from datetime import datetime, timezone

import stripe
from sqlalchemy.orm import Session

from backend.models import Subscription, PlanTier, SubscriptionStatus
from backend.utils.auth import PLAN_INTERVALS


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not configured")

stripe.api_key = STRIPE_SECRET_KEY


PRICE_TO_PLAN = {
    os.getenv("STRIPE_PRICE_BASIC", ""): (PlanTier.BASIC, 30),
    os.getenv("STRIPE_PRICE_PRO", ""): (PlanTier.PRO, 10),
    os.getenv("STRIPE_PRICE_EXPERT", ""): (PlanTier.EXPERT, 1),
}

def create_checkout_session(user_id: int, price_id: str, base_url: str) -> str:
    """
    Create a Stripe Checkout Session for a subscription.

    Returns the checkout URL to send to the user.
    """

    if not price_id or not price_id.startswith("price_"):
        raise ValueError(f"Invalid Stripe price ID: {price_id!r}")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        mode="subscription",
        success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/cancel",
        client_reference_id=str(user_id),
        metadata={
            "user_id": str(user_id),
        },
        subscription_data={
            "metadata": {
                "user_id": str(user_id),
            },
        },
    )

    return session.url

def handle_webhook_event(
    event_type: str,
    event_data: dict,
    db: Session,
) -> dict:
    """
    Handle Stripe webhook events and update the database.
    """

    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.created": _handle_subscription_created,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.payment_succeeded": _handle_payment_succeeded,
        "invoice.payment_failed": _handle_payment_failed,
    }

    handler = handlers.get(event_type)

    if handler is None:
        return {
            "status": "ignored",
            "message": f"Event type {event_type} not handled",
        }

    return handler(event_data, db)


def _handle_checkout_completed(event_data: dict, db: Session) -> dict:
    session = event_data
    client_reference_id = session.get("client_reference_id")

    if not client_reference_id:
        return {
            "status": "ignored",
            "message": "Checkout session has no client_reference_id",
        }

    user_id = int(client_reference_id)

    print(
        f"Checkout completed for user {user_id}, "
        f"session: {session.get('id')}"
    )

    return {
        "status": "success",
        "message": f"Checkout completed for user {user_id}",
        "user_id": user_id,
    }


def _handle_subscription_created(
    event_data: dict,
    db: Session,
) -> dict:
    sub = event_data

    customer_id = sub["customer"]
    subscription_id = sub["id"]

    price_id = sub["items"]["data"][0]["price"]["id"]
    plan_tier, interval_minutes = PRICE_TO_PLAN.get(
        price_id,
        (PlanTier.BASIC, 30),
    )

    user_id = _get_user_id_from_subscription(sub)

    if user_id is None:
        return {
            "status": "ignored",
            "message": (
                "Could not determine user_id for subscription "
                f"{subscription_id}"
            ),
        }

    existing = (
        db.query(Subscription)
        .filter(
            Subscription.stripe_subscription_id == subscription_id
        )
        .first()
    )

    if existing is not None:
        return {
            "status": "ignored",
            "message": (
                f"Subscription {subscription_id} already exists"
            ),
        }

    subscription = Subscription(
        user_id=user_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        plan_tier=plan_tier,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=_get_current_period_end(sub),
        interval_minutes=interval_minutes,
    )

    try:
        db.add(subscription)
        db.commit()
    except Exception:
        db.rollback()
        raise

    print(
        f"Subscription created for user {user_id}: "
        f"{plan_tier.value} plan"
    )

    return {
        "status": "success",
        "message": f"Subscription created for user {user_id}",
        "user_id": user_id,
        "plan_tier": plan_tier.value,
    }


def _handle_subscription_updated(
    event_data: dict,
    db: Session,
) -> dict:
    sub = event_data
    subscription_id = sub["id"]

    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.stripe_subscription_id == subscription_id
        )
        .first()
    )

    if subscription is None:
        return {
            "status": "not_found",
            "message": "Subscription not found in database",
        }

    status_value = sub.get("status")

    try:
        subscription.status = SubscriptionStatus(status_value)
    except ValueError:
        return {
            "status": "ignored",
            "message": f"Unknown Stripe subscription status: {status_value}",
        }

    subscription.current_period_end = _get_current_period_end(sub)

    price_id = sub["items"]["data"][0]["price"]["id"]

    if price_id in PRICE_TO_PLAN:
        plan_tier, interval_minutes = PRICE_TO_PLAN[price_id]
        subscription.plan_tier = plan_tier
        subscription.interval_minutes = interval_minutes

    db.commit()

    return {
        "status": "success",
        "message": f"Subscription updated for user {subscription.user_id}",
        "user_id": subscription.user_id,
        "subscription_status": subscription.status.value,
    }


def _handle_subscription_deleted(
    event_data: dict,
    db: Session,
) -> dict:
    sub = event_data
    subscription_id = sub["id"]

    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.stripe_subscription_id == subscription_id
        )
        .first()
    )

    if subscription is None:
        return {
            "status": "not_found",
            "message": "Subscription not found in database",
        }

    subscription.status = SubscriptionStatus.CANCELED
    subscription.current_period_end = _timestamp_to_datetime(
        sub.get("current_period_end")
    )

    db.commit()

    return {
        "status": "success",
        "message": (
            f"Subscription canceled for user {subscription.user_id}"
        ),
        "user_id": subscription.user_id,
    }


def _handle_payment_succeeded(
    event_data: dict,
    db: Session,
) -> dict:
    invoice = event_data
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return {
            "status": "ignored",
            "message": "Invoice has no subscription",
        }

    print(
        f"Payment succeeded for subscription {subscription_id}"
    )

    return {
        "status": "success",
        "message": "Payment logged",
    }


def _handle_payment_failed(
    event_data: dict,
    db: Session,
) -> dict:
    invoice = event_data["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return {
            "status": "ignored",
            "message": "Invoice has no subscription",
        }

    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.stripe_subscription_id == subscription_id
        )
        .first()
    )

    if subscription is not None:
        subscription.status = SubscriptionStatus.PAST_DUE
        db.commit()

    return {
        "status": "success",
        "message": "Payment failure processed",
    }


def _get_user_id_from_subscription(sub: dict) -> int | None:
    metadata = sub.get("metadata") or {}
    user_id = metadata.get("user_id")

    if user_id:
        return int(user_id)

    customer_id = sub.get("customer")

    if not customer_id:
        return None

    customers = stripe.Customer.retrieve(customer_id)
    customer_metadata = customers.get("metadata") or {}
    user_id = customer_metadata.get("user_id")

    return int(user_id) if user_id else None


def _timestamp_to_datetime(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(
        tzinfo=None
    )

def _get_current_period_end(sub: dict) -> datetime:
    timestamp = sub.get("current_period_end")

    if timestamp:
        return _timestamp_to_datetime(timestamp)

    items = (sub.get("items") or {}).get("data") or []

    if items:
        item_period_end = items[0].get("current_period_end")

        if item_period_end:
            return _timestamp_to_datetime(item_period_end)

    raise ValueError(
        "Stripe subscription has no current_period_end"
    )
