import os
from fastapi.responses import FileResponse
import stripe
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from dotenv import load_dotenv
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.database import get_db_connection
from app.auth import decode_access_token

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Stripe API Key
stripe.api_key = os.getenv("STRIPE_SECRET_KEY") 

router = APIRouter(tags=["Payment"])

# Request Model for Payment
class PaymentRequest(BaseModel):
    plan_id: int
    email: str

class PaymentStatusResponse(BaseModel):
    status: str
    expiry_date: str = None
    payment_date: str = None
    plan_id: int = None
    plan_name: str = None

# Create Stripe Checkout Session with pricing plan
@router.post("/create-checkout-session")
def create_checkout_session(payment: PaymentRequest, token: str):
    try:
        # Validate user token
        user = decode_access_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")
        
        user_id = user["user_id"]
        
        # Get pricing plan details
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, features
            FROM pricing_plans
            WHERE id = %s AND is_active = TRUE
        """, (payment.plan_id,))
        
        plan = cursor.fetchone()
        
        if not plan:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Pricing plan not found or inactive")
        
        plan_id = plan[0]
        plan_name = plan[1]
        plan_description = plan[2]
        plan_price = int(float(plan[3]) * 100)  # Convert to cents for Stripe
        plan_currency = plan[4].lower()
        plan_duration = plan[5]
        
        # Check if plan is a custom quote (price = 0)
        if plan_price == 0:
            cursor.close()
            conn.close()
            return {
                "message": "This is a custom quote plan. Please contact sales for pricing.",
                "plan_name": plan_name,
                "plan_id": plan_id,
                "requires_custom_quote": True
            }
        
        # Create metadata to track the user and plan
        metadata = {
            "user_id": str(user_id),
            "plan_id": str(plan_id),
            "plan_name": plan_name,
            "duration_days": str(plan_duration),
            "subscription_type": "premium"
        }
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": plan_currency,
                    "product_data": {
                        "name": plan_name,
                        "description": plan_description,
                    },
                    "unit_amount": plan_price,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=os.getenv("FRONTEND_URL", "https://api.symi.io") + "/payment/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=os.getenv("FRONTEND_URL", "https://api.symi.io") + "/payment/cancel",
            customer_email=payment.email,
            metadata=metadata,
        )
        

        cursor.execute("SELECT id FROM payment_status WHERE user_id = %s", (user_id,))
        existing_record = cursor.fetchone()
        
        if existing_record:
            # Update existing record
            cursor.execute("""
                UPDATE payment_status 
                SET payment_id = %s, payment_amount = %s, plan_id = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE user_id = %s
            """, (checkout_session.id, plan_price, plan_id, user_id))
        else:
            # Create new record
            cursor.execute("""
                INSERT INTO payment_status (user_id, status, payment_id, payment_amount, plan_id)
                VALUES (%s, 'free', %s, %s, %s)
            """, (user_id, checkout_session.id, plan_price, plan_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Created checkout session {checkout_session.id} for user {user_id}, plan {plan_id} ({plan_name})")
        
        return {
            "checkout_url": checkout_session.url, 
            "session_id": checkout_session.id,
            "plan_name": plan_name,
            "plan_id": plan_id
        }
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# Update payment status on success
def update_payment_status(session_id: str):
    try:
        # Retrieve session details from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.payment_status != "paid":
            logger.warning(f"Session {session_id} payment status is not 'paid': {session.payment_status}")
            return False
        
        # Get user_id and plan details from metadata
        user_id = session.metadata.get("user_id")
        plan_id = session.metadata.get("plan_id")
        duration_days = int(session.metadata.get("duration_days", 365))
        
        if not user_id or not plan_id:
            logger.error(f"No user_id or plan_id found in session {session_id} metadata")
            return False
        
        # Calculate expiry date based on plan duration
        expiry_date = datetime.now() + timedelta(days=duration_days)
        
        # Update payment status in database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE payment_status 
            SET status = 'premium', 
                payment_date = CURRENT_TIMESTAMP,
                expiry_date = %s,
                plan_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND payment_id = %s
            RETURNING id
        """, (expiry_date, plan_id, user_id, session_id))
        
        updated = cursor.fetchone()
        
        if not updated:
            # If no record was updated, create a new one
            cursor.execute("""
                INSERT INTO payment_status 
                (user_id, status, payment_id, payment_amount, payment_date, expiry_date, plan_id)
                VALUES (%s, 'premium', %s, %s, CURRENT_TIMESTAMP, %s, %s)
            """, (user_id, session_id, session.amount_total, expiry_date, plan_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Successfully updated payment status for user {user_id} to premium with plan {plan_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error updating payment status: {str(e)}")
        return False

# Success Page that updates payment status
@router.get("/success")
async def payment_success(session_id: str, background_tasks: BackgroundTasks):
    # Process payment update in background to avoid blocking
    background_tasks.add_task(update_payment_status, session_id)
    
    # Retrieve session to get plan details
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        # plan_name = session.metadata.get("plan_name", "Premium Plan")
        # plan_id = session.metadata.get("plan_id")
        
        # Return the HTML file with parameters in the URL
        return FileResponse(
            "app/static/success_page.html", 
            headers={"Content-Disposition": f"inline; filename=success.html"}
        )
    except Exception as e:
        # Return HTML file with minimal parameters
        return FileResponse(
            "app/static/success_page.html",
            headers={"Content-Disposition": f"inline; filename=success.html"}
        )

# Cancel Page
@router.get("/cancel")
def payment_cancel():
    return {"message": "Payment Cancelled"}

# Get payment status for current user
@router.get("/status", response_model=PaymentStatusResponse)
def get_payment_status(token: str):
    user = decode_access_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    user_id = user["user_id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT ps.status, ps.payment_date, ps.expiry_date, ps.plan_id, pp.name as plan_name 
            FROM payment_status ps
            LEFT JOIN pricing_plans pp ON ps.plan_id = pp.id
            WHERE ps.user_id = %s
        """, (user_id,))
        
        result = cursor.fetchone()
        
        if not result:
            return {"status": "free"}
        
        # Format dates
        payment_date = result[1].isoformat() if result[1] else None
        expiry_date = result[2].isoformat() if result[2] else None
        
        return {
            "status": result[0],
            "payment_date": payment_date,
            "expiry_date": expiry_date,
            "plan_id": result[3],
            "plan_name": result[4]
        }
    
    finally:
        cursor.close()
        conn.close()

# Webhook to Handle Stripe Events (e.g., Payment Success)
@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle payment success
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Get user ID from metadata
        user_id = session.metadata.get("user_id")
        plan_id = session.metadata.get("plan_id")
        
        if not user_id or not plan_id:
            logger.error("No user_id or plan_id found in session metadata")
            return {"message": "Error: No user ID or plan ID in metadata"}
        
        # Update payment status
        success = update_payment_status(session.id)
        
        if success:
            logger.info(f"Webhook: Payment successful for user {user_id}, plan {plan_id}")
            return {"message": f"Payment successfully processed for user {user_id}, plan {plan_id}"}
        else:
            logger.error(f"Webhook: Payment processing failed for user {user_id}, plan {plan_id}")
            return {"message": f"Error processing payment for user {user_id}, plan {plan_id}"}

    return {"message": "Webhook received"}