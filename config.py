# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Fixed session key to ensure sessions stay persistent across requests
    SECRET_KEY = os.getenv("SECRET_KEY", "martx_super_secure_session_key_93370637292")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Standalone MongoDB Database (Completely separate from Telegram bot)
    MONGO_URI = os.getenv(
        "MONGO_URI", 
        "mongodb+srv://mikunkumar242_db_user:Somesh93372585sg@cluster0.huo0uug.mongodb.net/?appName=Cluster0"
    )
    DB_NAME = os.getenv("DB_NAME", "mart_x_web_db")
    
    # Default Admin Credentials
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "MartXAdmin#2026"
    
    # Store Economics
    DEFAULT_COINS_PER_INR = "10"
    DEFAULT_ADMIN_UPI = "merchant@upi"
    SUPPORT_HANDLE = "SOMU_VERIFIED"
