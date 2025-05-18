from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.models import create_tables
from app.routers import google_auth, pricing, profession_prompts, professions, reports, user_profession, users, chats, websocket, admin, payment
import os
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# create_tables()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

os.makedirs(os.path.join('app', 'static'), exist_ok=True)

app.include_router(users.router, prefix="/users")
app.include_router(chats.router, prefix="/chats")
app.include_router(websocket.router)
app.include_router(admin.router, prefix="/admin")  
app.include_router(payment.router, prefix="/payment")
app.include_router(pricing.router, prefix="/pricing")
app.include_router(professions.router, prefix="/professions")
app.include_router(user_profession.router, prefix="/user-profession")
app.include_router(profession_prompts.router, prefix="/profession-prompts")
app.include_router(reports.router, prefix="/reports")
app.include_router(google_auth.router, prefix="/auth")

@app.get("/")
def root():
    return {"message": "Chatbot API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8800, reload=False)
