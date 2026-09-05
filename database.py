# database.py
import time
import secrets
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

client = MongoClient(Config.MONGO_URI)
db = client[Config.DB_NAME]

# Collections
users_col = db["web_users"]
products_col = db["web_products"]
orders_col = db["web_orders"]
gift_codes_col = db["web_gift_codes"]
coupons_col = db["web_coupons"]
settings_col = db["web_settings"]
counters_col = db["web_counters"]
admin_col = db["web_admin_auth"]

def get_next_sequence(name: str) -> int:
    seq = counters_col.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return seq["seq"]

def init_db():
    users_col.create_index("email", unique=True)
    users_col.create_index("referral_code", unique=True)
    products_col.create_index("id", unique=True)
    orders_col.create_index("order_id", unique=True)
    gift_codes_col.create_index("code", unique=True)
    coupons_col.create_index("code", unique=True)
    
    # Initialize default admin credentials in database if not present
    if admin_col.count_documents({}) == 0:
        admin_col.insert_one({
            "username": Config.DEFAULT_ADMIN_USERNAME.lower().strip(),
            "password": generate_password_hash(Config.DEFAULT_ADMIN_PASSWORD.strip()),
            "updated_at": time.time()
        })

# ==================== ADMIN CREDENTIALS ENGINE ====================

def verify_admin_login(username: str, password: str) -> bool:
    clean_uname = username.strip().lower()
    clean_pass = password.strip()
    
    admin_doc = admin_col.find_one({"username": clean_uname})
    if not admin_doc:
        # Fallback to default credentials if collection was reset
        if clean_uname == Config.DEFAULT_ADMIN_USERNAME.lower() and clean_pass == Config.DEFAULT_ADMIN_PASSWORD:
            admin_col.update_one(
                {"username": clean_uname},
                {"$set": {"username": clean_uname, "password": generate_password_hash(clean_pass), "updated_at": time.time()}},
                upsert=True
            )
            return True
        return False
        
    return check_password_hash(admin_doc["password"], clean_pass)

def update_admin_credentials(current_username: str, new_username: str, new_password: str) -> tuple:
    clean_u = new_username.strip().lower()
    clean_p = new_password.strip()
    
    if len(clean_u) < 3:
        return False, "Username must be at least 3 characters long."
    if len(clean_p) < 6:
        return False, "Password must be at least 6 characters long."
        
    admin_col.delete_many({})  # Ensure single active admin record
    admin_col.insert_one({
        "username": clean_u,
        "password": generate_password_hash(clean_p),
        "updated_at": time.time()
    })
    return True, "Admin credentials updated successfully!"

def get_current_admin_username() -> str:
    admin_doc = admin_col.find_one({})
    if admin_doc:
        return admin_doc.get("username", "admin")
    return Config.DEFAULT_ADMIN_USERNAME

# ==================== BUYER AUTHENTICATION (EMAIL & PASSWORD) ====================

def register_user(email: str, password: str, ref_code: str = None) -> tuple:
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email:
        return False, "Please provide a valid email address."
    
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."

    if users_col.find_one({"email": clean_email}):
        return False, "An account with this email already exists. Please log in."

    referrer_id = None
    if ref_code:
        ref_doc = users_col.find_one({"referral_code": ref_code.upper().strip()})
        if ref_doc:
            referrer_id = ref_doc["_id"]

    new_ref = "MXR" + secrets.token_hex(3).upper()
    hashed_pw = generate_password_hash(password)

    users_col.insert_one({
        "email": clean_email,
        "password": hashed_pw,
        "coins": 0,
        "referral_code": new_ref,
        "referred_by": referrer_id,
        "refer_count": 0,
        "refer_earnings": 0,
        "created_at": time.time()
    })

    if referrer_id:
        try:
            reward = int(get_setting("refer_coins_reward", "10"))
        except Exception:
            reward = 10
        users_col.update_one(
            {"_id": referrer_id},
            {"$inc": {"coins": reward, "refer_count": 1, "refer_earnings": reward}}
        )

    return True, "Account registered successfully! You can now log in."

def authenticate_user(email: str, password: str):
    clean_email = email.strip().lower()
    user = users_col.find_one({"email": clean_email})
    if user and check_password_hash(user.get("password", ""), password):
        return user
    return None

def get_user_by_email(email: str):
    return users_col.find_one({"email": email.strip().lower()})

def atomic_deduct_coins(email: str, coins: int) -> bool:
    if coins <= 0:
        return False
    res = users_col.update_one(
        {"email": email.strip().lower(), "coins": {"$gte": coins}},
        {"$inc": {"coins": -coins}}
    )
    return res.modified_count > 0

def add_user_coins(email: str, coins: int):
    if coins <= 0:
        return
    users_col.update_one({"email": email.strip().lower()}, {"$inc": {"coins": coins}})

# ==================== PRODUCTS & STOCK MANAGEMENT ====================

def get_all_products(active_only=True):
    query = {"is_active": 1} if active_only else {}
    docs = list(products_col.find(query).sort("id", 1))
    for d in docs:
        d["stock"] = len(d.get("stock_items", []))
    return docs

def get_product(product_id: int):
    d = products_col.find_one({"id": product_id})
    if d:
        d["stock"] = len(d.get("stock_items", []))
    return d

def add_product(name: str, description: str, price_coins: int):
    p_id = get_next_sequence("product_id")
    products_col.insert_one({
        "id": p_id,
        "name": name.strip(),
        "description": description.strip(),
        "price": price_coins,
        "stock_items": [],
        "is_active": 1,
        "created_at": time.time()
    })
    return p_id

def delete_product(product_id: int):
    products_col.delete_one({"id": product_id})

def add_product_stock_items(product_id: int, raw_text: str):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    prod = products_col.find_one({"id": product_id})
    if not prod:
        return 0, 0
    existing = set(prod.get("stock_items", []))
    unique_items = [itm for itm in lines if itm not in existing]
    if unique_items:
        products_col.update_one({"id": product_id}, {"$push": {"stock_items": {"$each": unique_items}}})
    total = len(products_col.find_one({"id": product_id}).get("stock_items", []))
    return len(unique_items), total

def pop_product_stock_items(product_id: int, qty: int):
    prod = products_col.find_one({"id": product_id})
    if not prod:
        return []
    items = prod.get("stock_items", [])
    if len(items) < qty:
        return []
    delivered = items[:qty]
    remaining = items[qty:]
    products_col.update_one({"id": product_id}, {"$set": {"stock_items": remaining}})
    return delivered

# ==================== ORDERS ====================

def create_order(email: str, product_id: int, product_name: str, qty: int, total_coins: int, delivered_items: list):
    order_id = f"ORD-{secrets.token_hex(4).upper()}"
    orders_col.insert_one({
        "order_id": order_id,
        "email": email.strip().lower(),
        "product_id": product_id,
        "product_name": product_name,
        "quantity": qty,
        "total_coins": total_coins,
        "delivered_items": delivered_items,
        "status": "COMPLETED",
        "created_at": time.time()
    })
    return order_id

def get_user_orders(email: str):
    return list(orders_col.find({"email": email.strip().lower()}).sort("created_at", -1))

# ==================== GIFT CODES & COUPONS ====================

def redeem_gift_code(code: str, email: str):
    clean_code = code.upper().strip()
    item = gift_codes_col.find_one({"code": clean_code, "is_redeemed": False})
    if not item:
        return False, "Invalid or expired gift code."
    
    gift_codes_col.update_one(
        {"code": clean_code},
        {"$set": {"is_redeemed": True, "redeemed_by": email.lower(), "redeemed_at": time.time()}}
    )
    add_user_coins(email, item["coins"])
    return True, f"Successfully redeemed +{item['coins']} Mart X Coins to your wallet!"

def create_admin_gift_code(coins: int, created_by="admin"):
    raw = secrets.token_hex(6).upper()
    code = f"MXGC-{raw[:4]}-{raw[4:8]}-{raw[8:]}"
    gift_codes_col.insert_one({
        "code": code,
        "coins": coins,
        "created_by": created_by,
        "is_redeemed": False,
        "created_at": time.time()
    })
    return code

def create_coupon(code: str, discount_pct: int, created_by="admin"):
    clean_code = code.upper().strip()
    coupons_col.insert_one({
        "code": clean_code,
        "discount_percent": int(discount_pct),
        "created_by": created_by,
        "is_redeemed": False,
        "created_at": time.time()
    })

def validate_coupon(code: str):
    clean = code.upper().strip()
    c = coupons_col.find_one({"code": clean, "is_redeemed": False})
    if not c:
        return None
    return c["discount_percent"]

def consume_coupon(code: str, email: str):
    coupons_col.update_one(
        {"code": code.upper().strip()},
        {"$set": {"is_redeemed": True, "redeemed_by": email.lower(), "redeemed_at": time.time()}}
    )

def get_setting(key: str, default: str = ""):
    doc = settings_col.find_one({"key": key})
    return doc.get("value", default) if doc else default

def set_setting(key: str, value: str):
    settings_col.update_one({"key": key}, {"$set": {"value": str(value)}}, upsert=True)

def get_stats():
    return {
        "users": users_col.count_documents({}),
        "products": products_col.count_documents({}),
        "orders": orders_col.count_documents({}),
        "active_codes": gift_codes_col.count_documents({"is_redeemed": False})
    }
