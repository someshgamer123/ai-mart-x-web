# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Fixed secret key (session cookie drop hone ki problem fix)
    SECRET_KEY = os.getenv("SECRET_KEY", "martx_super_secure_session_key_93370637292")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Standalone MongoDB Database (Aapke bot se bilkul alag)
    MONGO_URI = os.getenv(
        "MONGO_URI", 
        "mongodb+srv://mikunkumar242_db_user:Somesh93372585sg@cluster0.huo0uug.mongodb.net/?appName=Cluster0"
    )
    DB_NAME = os.getenv("DB_NAME", "mart_x_web_db")
    
    # Admin Panel Credentials (Sirf /admin/login se access hoga)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "someshkumarbiswaliamsomu@gmail.com").strip().lower()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "SoMuAdMiN@hsh6474764").strip()
    
    # Store Settings
    DEFAULT_COINS_PER_INR = os.getenv("DEFAULT_COINS_PER_INR", "10")
    DEFAULT_ADMIN_UPI = os.getenv("DEFAULT_ADMIN_UPI", "somuofc@ptyes")
    SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "SOMU_VERIFIED")
