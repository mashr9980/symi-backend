from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict
from app.database import get_db_connection
from app.routers.admin import is_admin
from app.auth import decode_access_token
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pricing"])

# Schema for pricing plan
class PricingPlanBase(BaseModel):
    name: str
    description: str
    price: float
    currency: str = "USD"
    duration_days: int = 365
    features: List[str]
    is_active: bool = True
    display_order: int = 0

class PricingPlanCreate(PricingPlanBase):
    pass

class PricingPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    duration_days: Optional[int] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None

class PricingPlanResponse(PricingPlanBase):
    id: int
    
# Function to create pricing_plans table if it doesn't exist
def create_pricing_table():
    """Create pricing_plans table if it doesn't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # try:
    #     cursor.execute("""
    #         CREATE TABLE IF NOT EXISTS pricing_plans (
    #             id SERIAL PRIMARY KEY,
    #             name VARCHAR(100) NOT NULL,
    #             description TEXT NOT NULL,
    #             price NUMERIC(10, 2) NOT NULL,
    #             currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    #             duration_days INTEGER NOT NULL DEFAULT 365,
    #             features JSONB NOT NULL DEFAULT '[]',
    #             is_active BOOLEAN NOT NULL DEFAULT TRUE,
    #             display_order INTEGER NOT NULL DEFAULT 0,
    #             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #             updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #         )
    #     """)
    #     conn.commit()
        
    # except Exception as e:
    #     logger.error(f"Error creating pricing_plans table: {str(e)}")
    #     conn.rollback()
        
    # finally:
    #     cursor.close()
    #     conn.close()

# Admin - Create a new pricing plan
@router.post("/admin/plans", response_model=PricingPlanResponse)
def create_pricing_plan(plan: PricingPlanCreate, token: str = Depends(is_admin)):
    """Admin creates a new pricing plan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Convert features list to JSON string for PostgreSQL JSONB type
        features_json = json.dumps(plan.features)
        
        # Insert new pricing plan
        cursor.execute("""
            INSERT INTO pricing_plans 
            (name, description, price, currency, duration_days, features, is_active, display_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, description, price, currency, duration_days, features, is_active, display_order
        """, (
            plan.name, 
            plan.description, 
            plan.price, 
            plan.currency, 
            plan.duration_days, 
            features_json,  # Pass as JSON string
            plan.is_active,
            plan.display_order
        ))
        
        result = cursor.fetchone()
        conn.commit()
        
        # Create response object
        response = {
            "id": result[0],
            "name": result[1],
            "description": result[2],
            "price": float(result[3]),
            "currency": result[4],
            "duration_days": result[5],
            "features": result[6],  # PostgreSQL returns JSONB as parsed Python list
            "is_active": result[7],
            "display_order": result[8]
        }
        
        return response
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating pricing plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    finally:
        cursor.close()
        conn.close()

# Admin - Get all pricing plans
@router.get("/admin/plans", response_model=List[PricingPlanResponse])
def get_all_pricing_plans():
    """Admin gets all pricing plans"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, 
                   features, is_active, display_order
            FROM pricing_plans
            ORDER BY display_order, name
        """)
        
        plans = cursor.fetchall()
        
        result = []
        for plan in plans:
            result.append({
                "id": plan[0],
                "name": plan[1],
                "description": plan[2],
                "price": float(plan[3]),
                "currency": plan[4],
                "duration_days": plan[5],
                "features": plan[6],
                "is_active": plan[7],
                "display_order": plan[8]
            })
        
        return result
        
    finally:
        cursor.close()
        conn.close()

# Admin - Get a specific pricing plan
@router.get("/admin/plans/{plan_id}", response_model=PricingPlanResponse)
def get_pricing_plan(plan_id: int, token: str = Depends(is_admin)):
    """Admin gets a specific pricing plan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, 
                   features, is_active, display_order
            FROM pricing_plans
            WHERE id = %s
        """, (plan_id,))
        
        plan = cursor.fetchone()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Pricing plan not found")
        
        return {
            "id": plan[0],
            "name": plan[1],
            "description": plan[2],
            "price": float(plan[3]),
            "currency": plan[4],
            "duration_days": plan[5],
            "features": plan[6],
            "is_active": plan[7],
            "display_order": plan[8]
        }
        
    finally:
        cursor.close()
        conn.close()

# Admin - Update a pricing plan
@router.put("/admin/plans/{plan_id}", response_model=PricingPlanResponse)
def update_pricing_plan(plan_id: int, plan: PricingPlanUpdate, token: str = Depends(is_admin)):
    """Admin updates a pricing plan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if plan exists
        cursor.execute("SELECT id FROM pricing_plans WHERE id = %s", (plan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Pricing plan not found")
        
        # Build update query dynamically based on provided fields
        update_fields = []
        update_values = []
        
        if plan.name is not None:
            update_fields.append("name = %s")
            update_values.append(plan.name)
        
        if plan.description is not None:
            update_fields.append("description = %s")
            update_values.append(plan.description)
        
        if plan.price is not None:
            update_fields.append("price = %s")
            update_values.append(plan.price)
        
        if plan.currency is not None:
            update_fields.append("currency = %s")
            update_values.append(plan.currency)
        
        if plan.duration_days is not None:
            update_fields.append("duration_days = %s")
            update_values.append(plan.duration_days)
        
        if plan.features is not None:
            update_fields.append("features = %s")
            update_values.append(json.dumps(plan.features))  # Convert to JSON string
        
        if plan.is_active is not None:
            update_fields.append("is_active = %s")
            update_values.append(plan.is_active)
            
        if plan.display_order is not None:
            update_fields.append("display_order = %s")
            update_values.append(plan.display_order)
        
        # Add updated_at timestamp
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        # Only update if there are fields to update
        if update_fields:
            query = f"""
                UPDATE pricing_plans
                SET {', '.join(update_fields)}
                WHERE id = %s
                RETURNING id, name, description, price, currency, duration_days, 
                          features, is_active, display_order
            """
            cursor.execute(query, update_values + [plan_id])
            
            updated_plan = cursor.fetchone()
            conn.commit()
            
            return {
                "id": updated_plan[0],
                "name": updated_plan[1],
                "description": updated_plan[2],
                "price": float(updated_plan[3]),
                "currency": updated_plan[4],
                "duration_days": updated_plan[5],
                "features": updated_plan[6],
                "is_active": updated_plan[7],
                "display_order": updated_plan[8]
            }
        
        # If no updates were provided, return the current plan
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, 
                   features, is_active, display_order
            FROM pricing_plans
            WHERE id = %s
        """, (plan_id,))
        
        plan = cursor.fetchone()
        
        return {
            "id": plan[0],
            "name": plan[1],
            "description": plan[2],
            "price": float(plan[3]),
            "currency": plan[4],
            "duration_days": plan[5],
            "features": plan[6],
            "is_active": plan[7],
            "display_order": plan[8]
        }
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating pricing plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    finally:
        cursor.close()
        conn.close()

# Admin - Delete a pricing plan
@router.delete("/admin/plans/{plan_id}")
def delete_pricing_plan(plan_id: int, token: str = Depends(is_admin)):
    """Admin deletes a pricing plan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if plan exists
        cursor.execute("SELECT id FROM pricing_plans WHERE id = %s", (plan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Pricing plan not found")
        
        # Delete the plan
        cursor.execute("DELETE FROM pricing_plans WHERE id = %s", (plan_id,))
        conn.commit()
        
        return {"message": f"Pricing plan {plan_id} deleted successfully"}
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting pricing plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    finally:
        cursor.close()
        conn.close()

# Public - Get active pricing plans (for frontend)
@router.get("/plans", response_model=List[PricingPlanResponse])
def get_active_pricing_plans():
    """Get all active pricing plans for frontend display"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, 
                   features, is_active, display_order
            FROM pricing_plans
            WHERE is_active = TRUE
            ORDER BY display_order, price
        """)
        
        plans = cursor.fetchall()
        
        result = []
        for plan in plans:
            result.append({
                "id": plan[0],
                "name": plan[1],
                "description": plan[2],
                "price": float(plan[3]),
                "currency": plan[4],
                "duration_days": plan[5],
                "features": plan[6],
                "is_active": plan[7],
                "display_order": plan[8]
            })
        
        return result
        
    finally:
        cursor.close()
        conn.close()

# Get a specific pricing plan (public)
@router.get("/plans/{plan_id}", response_model=PricingPlanResponse)
def get_public_pricing_plan(plan_id: int):
    """Get details for a specific pricing plan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, description, price, currency, duration_days, 
                   features, is_active, display_order
            FROM pricing_plans
            WHERE id = %s AND is_active = TRUE
        """, (plan_id,))
        
        plan = cursor.fetchone()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Pricing plan not found or inactive")
        
        return {
            "id": plan[0],
            "name": plan[1],
            "description": plan[2],
            "price": float(plan[3]),
            "currency": plan[4],
            "duration_days": plan[5],
            "features": plan[6],
            "is_active": plan[7],
            "display_order": plan[8]
        }
        
    finally:
        cursor.close()
        conn.close()