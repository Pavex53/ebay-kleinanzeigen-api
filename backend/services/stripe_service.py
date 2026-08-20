"""
Stripe service for handling payments, subscriptions, and webhooks.
"""
import stripe
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import Subscription, PlanTier, SubscriptionStatus
from backend.utils.auth import PLAN_INTERVALS


# Stripe API key (set via environment variable)
stripe.api_key = None  # Will be set in main.py from env


# Price ID to plan tier mapping (update with your actual Stripe price IDs)
PRICE_TO_PLAN = {
    "price_basic_id": (PlanTier.BASIC, 30),
    "price_pro_id": (PlanTier.PRO, 10),
    "price_expert_id": (PlanTier.EXPERT, 1),
}


def create_checkout_session(user_id: int, price_id: str, base_url: str) -> str:
    """
    Create a Stripe Checkout Session for a subscription.
    
    Returns the checkout URL to send to the user.
    """
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
    )
    return session.url


def handle_webhook_event(event_type: str, event_data: dict, db: Session) -> dict:
    """
    Handle Stripe webhook events and update database.
    
    Returns dict with status and info.
    """
    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(event_data, db)
    
    elif event_type == "customer.subscription.created":
        return _handle_subscription_created(event_data, db)
    
    elif event_type == "customer.subscription.updated":
        return _handle_subscription_updated(event_data, db)
    
    elif event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(event_data, db)
    
    elif event_type == "invoice.payment_succeeded":
        return _handle_payment_succeeded(event_data, db)
    
    elif event_type == "invoice.payment_failed":
        return _handle_payment_failed(event_data, db)
    
    else:
        return {"status": "ignored", "message": f"Event type {event_type} not handled"}


def _handle_checkout_completed(event_data: dict, db: Session) -> dict:
    """Handle checkout.session.completed event."""
    session = event_data["object"]
    user_id = int(session["client_reference_id"])
    
    # Log the checkout completion (subscription will be created in customer.subscription.created)
    print(f"Checkout completed for user {user_id}, session: {session['id']}")
    
    return {
        "status": "success",
        "message": f"Checkout completed for user {user_id}",
        "user_id": user_id,
    }


def _handle_subscription_created(event_data: dict, db: Session) -> dict:
    """Handle customer.subscription.created event."""
    sub = event_data["object"]
    customer_id = sub["customer"]
    subscription_id = sub["id"]
    
    # Get the checkout session to retrieve user_id
    session = stripe.checkout.Session.retrieve(sub.get("checkout_session"))
    user_id = int(session["client_reference_id"])
    
    # Get plan tier from price ID
    price_id = sub["items"]["data"][0]["price"]["id"]
    plan_tier, interval_minutes = PRICE_TO_PLAN.get(price_id, (PlanTier.BASIC, 30))
    
    # Create subscription record
    subscription = Subscription(
        user_id=user_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        plan_tier=plan_tier,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=datetime.fromtimestamp(sub["current_period_end"]),
        interval_minutes=interval_minutes,
    )
    
    db.add(subscription)
    db.commit()
    
    print(f"Subscription created for user {user_id}: {plan_tier.value} plan")
    
    return {
        "status": "success",
        "message": f"Subscription created for user {user_id}",
        "user_id": user_id,
        "plan_tier": plan_tier.value,
    }


def _handle_subscription_updated(event_data: dict, db: Session) -> dict:
    """Handle customer.subscription.updated event."""
    sub = event_data["object"]
    subscription_id = sub["id"]
    
    # Find existing subscription
    subscription = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_id
    ).first()
    
    if subscription is None:
        # Subscription not found, might be from different system
        return {"status": "not_found", "message": "Subscription not found in DB"}
    
    # Update subscription
    subscription.status = SubscriptionStatus(sub["status"])
    subscription.current_period_end = datetime.fromtimestamp(sub["current_period_end"])
    
    # Update plan tier if changed
    price_id = sub["items"]["data"][0]["price"]["id"]
    if price_id in PRICE_TO_PLAN:
        plan_tier, interval_minutes = PRICE_TO_PLAN[price_id]
        subscription.plan_tier = plan_tier
        subscription.interval_minutes = interval_minutes
    
    db.commit()
    
    print(f"Subscription updated for user {subscription.user_id}: {subscription.status.value}")
    
    return {
        "status": "success",
        "message": f"Subscription updated for user {subscription.user_id}",
        "user_id": subscription.user_id,
        "status": subscription.status.value,
    }


def _handle_subscription_deleted(event_data: dict, db: Session) -> dict:
    """Handle customer.subscription.deleted event."""
    sub = event_data["object"]
    subscription_id = sub["id"]
    
    # Find existing subscription
    subscription = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_id
    ).first()
    
    if subscription is None:
        return {"status": "not_found", "message": "Subscription not found in DB"}
    
    # Mark as canceled
    subscription.status = SubscriptionStatus.CANCELED
    subscription.current_period_end = datetime.fromtimestamp(sub["current_period_end"])
    
    db.commit()
    
    print(f"Subscription canceled for user {subscription.user_id}")
    
    return {
        "status": "success",
        "message": f"Subscription canceled for user {subscription.user_id}",
        "user_id": subscription.user_id,
    }


def _handle_payment_succeeded(event_data: dict, db: Session) -> dict:
    """Handle invoice.payment_succeeded event."""
    invoice = event_data["object"]
    subscription_id = invoice.get("subscription")
    
    if not subscription_id:
        return {"status": "ignored", "message": "No subscription in invoice"}
    
    # Optional: Log successful payment
    print(f"Payment succeeded for subscription {subscription_id}")
    
    return {"status": "success", "message": "Payment logged"}


def _handle_payment_failed(event_data: dict, db: Session) -> dict:
    """Handle invoice.payment_failed event."""
    invoice = event_data["object"]
    subscription_id = invoice.get("subscription")
    
    if not subscription_id:
        return {"status": "ignored", "message": "No subscription in invoice"}
    
    # Find subscription and mark as past_due
    subscription = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_id
    ).first()
    
    if subscription:
        subscription.status = SubscriptionStatus.PAST_DUE
        db.commit()
        print(f"Payment failed for user {subscription.user_id}")
    
    return {"status": "success", "message": "Payment failure logged"}
