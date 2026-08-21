"""
FastAPI main application for Kleinanzeigen SaaS backend.
"""
import os
import stripe
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend import database
from backend.database import Database, get_db
from backend.models import User
from backend.services import stripe_service
from backend.utils.auth import is_subscriber_active, check_subscription_access


# Environment variables
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:pass@localhost:5432/kleinanzeigen_saas",
)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

database.db = Database(DATABASE_URL)
database.db.create_tables()

# Price IDs (replace with your actual Stripe price IDs)
PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "price_basic_id")
PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "price_pro_id")
PRICE_EXPERT = os.getenv("STRIPE_PRICE_EXPERT", "price_expert_id")


# Initialize database
db = Database(DATABASE_URL)
db.create_tables()  # Create tables on startup

# Initialize Stripe
stripe.api_key = STRIPE_SECRET_KEY
stripe_service.stripe.api_key = STRIPE_SECRET_KEY


# FastAPI app
app = FastAPI(
    title="Kleinanzeigen SaaS API",
    description="Backend API for Kleinanzeigen Telegram Alert Service",
    version="0.1.0"
)

# CORS middleware (allow frontend to call API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency
def get_database() -> Session:
    """Get database session."""
    return next(db.get_session())


# Pydantic schemas
class CheckoutRequest(BaseModel):
    user_id: int
    plan: str  # "basic", "pro", or "expert"


class WebhookResponse(BaseModel):
    status: str
    message: str


# Endpoints
@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Kleinanzeigen SaaS API is running"}


@app.get("/health")
def health_check():
    """Health check for monitoring."""
    return {"status": "healthy"}


@app.post("/checkout/create")
def create_checkout_session(
    request: CheckoutRequest,
    db: Session = Depends(get_database)
):
    """
    Create a Stripe Checkout Session for a subscription.
    
    Returns checkout URL to redirect user to.
    """
    # Map plan to price ID
    plan_to_price = {
        "basic": PRICE_BASIC,
        "pro": PRICE_PRO,
        "expert": PRICE_EXPERT,
    }
    
    if request.plan not in plan_to_price:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {request.plan}")
    
    price_id = plan_to_price[request.plan]
    
    # Verify user exists
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create checkout session
    checkout_url = stripe_service.create_checkout_session(
        user_id=request.user_id,
        price_id=price_id,
        base_url=BASE_URL
    )
    
    return {"checkout_url": checkout_url}


@app.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe-Signature header",
        )

    if not webhook_secret:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_WEBHOOK_SECRET is not configured",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=webhook_secret,
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe webhook payload",
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe webhook signature",
        )

    result = stripe_service.handle_webhook_event(
        event_type=event["type"],
        event_data=event["data"]["object"],
        db=db,
    )

    return {
        "received": True,
        "event_type": event["type"],
        "result": result,
    }

@app.get("/users/{user_id}/subscription")
def get_user_subscription(user_id: int, db: Session = Depends(get_database)):
    """
    Get subscription status for a user.
    """
    access_info = check_subscription_access(db, user_id)
    
    if not access_info["has_access"]:
        return {
            "has_active_subscription": False,
            "message": "No active subscription found"
        }
    
    return {
        "has_active_subscription": True,
        "plan_tier": access_info["plan_tier"],
        "interval_minutes": access_info["interval_minutes"],
        "current_period_end": access_info["current_period_end"].isoformat(),
    }


@app.get("/users/{user_id}/access")
def check_user_access(user_id: int, db: Session = Depends(get_database)):
    """
    Check if a user has active subscription access.
    
    Returns 200 if user has access, 403 otherwise.
    """
    if not is_subscriber_active(db, user_id):
        raise HTTPException(
            status_code=403,
            detail="No active subscription. Please subscribe at /checkout/create"
        )
    
    return {"has_access": True}


# Run with: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
