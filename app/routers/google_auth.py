import os
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from google.oauth2 import id_token
from google.auth.transport import requests
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware
from app.database import get_db_connection
from app.auth import create_access_token, decode_access_token
import json

# Load Google client credentials from environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") 
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET") 
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://api.symi.io/auth/google/callback")

# Set up OAuth
config = Config(environ=os.environ)
oauth = OAuth(config)

oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    client_kwargs={
        "scope": "openid email profile",
        "redirect_uri": REDIRECT_URI,
    }
)

router = APIRouter(tags=["Google Auth"])

@router.get("/google/login")
async def login_via_google(request: Request):
    """Initiate Google OAuth login flow"""
    # Store the next URL to redirect after auth (if provided)
    next_url = request.query_params.get("next", "/")
    request.session["next_url"] = next_url
    
    # Store if this is a signup flow (to ask for profession later)
    is_signup = request.query_params.get("signup", "false").lower() == "true"
    request.session["is_signup"] = is_signup
    
    # Initiate OAuth flow
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback", name="auth_callback")
async def auth_callback(request: Request):
    """Handle Google OAuth callback"""
    try:
        # Complete OAuth flow
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        
        if not user_info:
            # Verify Google ID token as fallback
            id_info = id_token.verify_oauth2_token(
                token["id_token"], 
                requests.Request(), 
                GOOGLE_CLIENT_ID
            )
            user_info = {
                "email": id_info.get("email"),
                "name": id_info.get("name"),
                "picture": id_info.get("picture")
            }
        
        if not user_info or not user_info.get("email"):
            raise HTTPException(status_code=400, detail="Could not get user info from Google")
        
        # Check if user exists in the database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, email, role, status FROM users WHERE email = %s", (user_info["email"],))
        user = cursor.fetchone()
        
        is_signup = request.session.get("is_signup", False)
        needs_profession = False
        
        if user:
            # User exists - check if they're active
            if user[3] == "suspended":
                cursor.close()
                conn.close()
                return RedirectResponse(url=f"/login?error=account_suspended")
            
            # Update or create the google_auth record
            cursor.execute(
                """INSERT INTO google_auth (user_id, google_id, name, picture_url) 
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id) 
                   DO UPDATE SET google_id = EXCLUDED.google_id, 
                                 name = EXCLUDED.name,
                                 picture_url = EXCLUDED.picture_url,
                                 updated_at = CURRENT_TIMESTAMP""",
                (user[0], user_info.get("sub", user_info.get("id")), 
                 user_info.get("name"), user_info.get("picture"))
            )
            conn.commit()
            
            # Create JWT token
            token = create_access_token({"sub": user[1], "user_id": user[0], "role": user[2]})
            
            # Check if user has a profession set
            cursor.execute("SELECT profession_id FROM user_profession WHERE user_id = %s", (user[0],))
            user_profession = cursor.fetchone()
            needs_profession = user_profession is None
            
        else:
            # New user - create an account
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role, status) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (user_info.get("name", "Google User"), user_info["email"], "GOOGLE_AUTH", "business_owner", "active")
            )
            user_id = cursor.fetchone()[0]
            
            # Store Google info
            cursor.execute(
                "INSERT INTO google_auth (user_id, google_id, name, picture_url) VALUES (%s, %s, %s, %s)",
                (user_id, user_info.get("sub", user_info.get("id")), 
                 user_info.get("name"), user_info.get("picture"))
            )
            conn.commit()
            
            # Create JWT token
            token = create_access_token({"sub": user_info["email"], "user_id": user_id, "role": "business_owner"})
            needs_profession = True
            
        cursor.close()
        conn.close()
        
        # Get the frontend URL to redirect to
        frontend_url = os.getenv("FRONTEND_URL", "https:/symi.io")
        next_url = request.session.get("next_url", "/")
        
        # Build the redirect URL with token
        if needs_profession:
            # Redirect to profession selection page
            redirect_url = f"{frontend_url}/select-profession?token={token}&first_login={is_signup or needs_profession}"
        else:
            # Redirect to dashboard or requested page
            redirect_url = f"{frontend_url}{next_url}?token={token}"
        
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        return RedirectResponse(url=f"/login?error={str(e)}")

@router.post("/google/link")
async def link_google_account(google_token: str, user_token: str):
    """Link Google account to existing user account"""
    try:
        # Verify the user's access token
        user_data = decode_access_token(user_token)
        if not user_data or "user_id" not in user_data:
            raise HTTPException(status_code=401, detail="Invalid user token")
        
        user_id = user_data["user_id"]
        
        # Verify the Google ID token
        try:
            idinfo = id_token.verify_oauth2_token(
                google_token, 
                requests.Request(), 
                GOOGLE_CLIENT_ID
            )
            
            # Extract user information
            email = idinfo.get('email')
            name = idinfo.get('name', 'Google User')
            google_id = idinfo.get('sub')
            picture = idinfo.get('picture')
            
            if not email or not google_id:
                raise HTTPException(status_code=400, detail="Invalid Google token")
            
            # Verify that the Google account's email matches the user's email
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get user's email
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            user_email = cursor.fetchone()
            
            if not user_email:
                cursor.close()
                conn.close()
                raise HTTPException(status_code=404, detail="User not found")
            
            # Check if this Google account is already linked to another user
            cursor.execute("SELECT user_id FROM google_auth WHERE google_id = %s", (google_id,))
            existing_link = cursor.fetchone()
            
            if existing_link and existing_link[0] != user_id:
                cursor.close()
                conn.close()
                raise HTTPException(status_code=409, detail="This Google account is already linked to another user")
            
            # If email verification is required, verify that emails match
            if user_email[0].lower() != email.lower():
                cursor.close()
                conn.close()
                raise HTTPException(status_code=400, detail="The Google account email does not match your account email")
            
            # Link Google account to user
            cursor.execute(
                """INSERT INTO google_auth (user_id, google_id, name, picture_url) 
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id) 
                   DO UPDATE SET google_id = EXCLUDED.google_id, 
                                name = EXCLUDED.name,
                                picture_url = EXCLUDED.picture_url,
                                updated_at = CURRENT_TIMESTAMP""",
                (user_id, google_id, name, picture)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return {"message": "Google account linked successfully"}
            
        except ValueError as e:
            # Invalid token
            raise HTTPException(status_code=400, detail=f"Invalid Google token: {str(e)}")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error linking account: {str(e)}")