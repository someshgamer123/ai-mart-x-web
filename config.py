import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "martx_super_secure_session_key_2026")
    MONGO_URI = mongodb+srv://mikunkumar242_db_user:<somesh63723348>@cluster0.huo0uug.mongodb.net/?appName=Cluster0
    
    # Admin Credentials
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "someshkumarbiswaliamsomu@gmail.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "SoMuAdMiN@hsh6474764")  # Change in production
    
    # Defaults
    DEFAULT_COINS_PER_INR = os.getenv("DEFAULT_COINS_PER_INR", "10")
    DEFAULT_ADMIN_UPI = os.getenv("DEFAULT_ADMIN_UPI", "somuofc@ptyes")
    SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "SOMU_VERIFIED")
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "not_linked")