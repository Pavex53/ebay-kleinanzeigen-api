import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import stripe
from fastapi import FastAPI, HTTPException, Depends, status, APIRouter, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")
STRIPE_PRICE_EXPERT = os.getenv("STRIPE_PRICE_EXPERT")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENV = os.getenv("ENV", "prod")
BASE_URL = os.getenv("BASE_URL", "")


# Initialize Stripe
stripe.api_key = STRIPE_SECRET_KEY


# FastAPI app
app = FastAPI(
    title="Kleinanzeigen SaaS API",
    description="Backend API for Kleinanzeigen Telegram Alert Service",
    version="0.1.0"
)

# Pydantic models
class CheckoutRequest(BaseModel):
    user_id: int
    price_id: str
    email: str

class WebhookRequest(BaseModel):
    user_id: int



@app.get("/success", response_class=HTMLResponse)
def checkout_success(session_id: str = Query(...)) -> str:
    session = stripe.checkout.Session.retrieve(session_id)
    customer = stripe.Customer.retrieve(session.customer) if session.customer else None
    name = customer.name if customer else "Kunde"

    return f"""
    <!doctype html>
    <html lang="de">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Zahlung erfolgreich</title>
        <style>
          body {{
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #0f172a;
            color: #f8fafc;
            font-family: Arial, sans-serif;
          }}
          main {{
            width: min(560px, calc(100% - 48px));
            padding: 36px;
            border-radius: 18px;
            background: #1e293b;
            text-align: center;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
          }}
          h1 {{
            margin: 0 0 16px;
            font-size: 28px;
          }}
          p {{
            color: #cbd5e1;
            line-height: 1.6;
          }}
          .check {{
            font-size: 54px;
            margin-bottom: 12px;
          }}
        </style>
      </head>
      <body>
        <main>
          <div class="check">✅</div>
          <h1>Vielen Dank für deinen Einkauf, {name}!</h1>
          <p>Dein Abo wurde erfolgreich verarbeitet.</p>
          <p>Du kannst dieses Fenster jetzt schließen und zum Telegram-Bot zurückkehren.</p>
        </main>
      </body>
    </html>
    """

@app.get("/cancel", response_class=HTMLResponse)
def checkout_cancel() -> str:
    return """
    <!doctype html>
    <html lang="de">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Zahlung abgebrochen</title>
        <style>
          body {{
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #0f172a;
            color: #f8fafc;
            font-family: Arial, sans-serif;
          }}
          main {{
            width: min(560px, calc(100% - 48px));
            padding: 36px;
            border-radius: 18px;
            background: #1e293b;
            text-align: center;
          }}
          h1 {{
            margin: 0 0 16px;
          }}
          p {{
            color: #cbd5e1;
            line-height: 1.6;
          }}
        </style>
      </head>
      <body>
        <main>
          <h1>Zahlung abgebrochen</h1>
          <p>Es wurde keine Zahlung abgeschlossen.</p>
          <p>Du kannst dieses Fenster schließen und zum Telegram-Bot zurückkehren.</p>
        </main>
      </body>
    </html>
    """

@app.post("/checkout/create")
async def create_checkout(request: CheckoutRequest):
    try:
        # Determine success_url based on ENV
        if ENV == "local":
            success_url = f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{BASE_URL}/cancel"
        else:
            # Live: Stripe default page (no custom domain needed)
            success_url = None
            cancel_url = None

        session = stripe.checkout.Session.create(
            line_items=[
                {
                    "price": request.price_id,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=request.email,
            metadata={
                "user_id": str(request.user_id),
            },
        )

        return {"url": session.url}
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhooks/stripe")
async def stripe_webhook(request: WebhookRequest):
    # This is a simplified webhook handler
    # In production, you should verify the Stripe signature
    try:
        # Process the webhook event
        # Update user subscription status in database
        logger.info(f"Webhook received for user_id: {request.user_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "Kleinanzeigen SaaS API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
