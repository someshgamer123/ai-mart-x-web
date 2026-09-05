# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "martx_super_secure_session_key_93370637292")
    
    # Same MongoDB Atlas Cluster used by Bot
    MONGO_URI = os.getenv(
        "MONGO_URI", 
        "mongodb+srv://mikunkumar242_db_user:Somesh93372585sg@cluster0.huo0uug.mongodb.net/?appName=Cluster0"
    )
    DB_NAME = os.getenv("DB_NAME", "mart_x_web_db")  # Exactly matches bot's database!
    
    # Admin Credentials (Private Access only via /admin/login)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "someshkumarbiswaliamsomu@gmail.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "SoMuAdMiN@hsh6474764")
    ADMIN_ID = os.getenv("ADMIN_ID", "7118261474")  # Your Telegram User ID
    
    # Telegram Bot Sync
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8864299070:AAEyJOZNmkuaotInCt3j012aKYJZDoxmot0")  # Bot Token for sending live notifications
    SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "SOMU_VERIFIED")
    
    # Economics Defaults
    DEFAULT_COINS_PER_INR = os.getenv("DEFAULT_COINS_PER_INR", "10")
    DEFAULT_ADMIN_UPI = os.getenv("DEFAULT_ADMIN_UPI", "somuofc@ptyes")
