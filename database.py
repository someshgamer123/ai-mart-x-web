import time
import secrets
import re
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

client = MongoClient(Config.MONGO_URI, authSource="admin")
db = client[Config.DB_NAME]

# Collections
users_col = db["web_users"]
products_col = db["web_products"]
orders_col = db["web_orders"]
deposits_col = db["web_deposits"]
gift_codes_col = db["web_gift_codes"]
coupons_col = db["web_coupons"]
settings_col = db["web_settings"]
counters_col = db["web_counters"]

def get_next_sequence(name: str) -> int:
    seq = counters_col.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return seq["seq"]

def init_db():
    users_col.create_index("username", unique=True)
    users_col.create_index("referral_code", unique=True)
    products_col.create_index("id", unique=True)
    orders_col.create_index("order_id", unique=True)
    deposits_col.create_index("deposit_id", unique=True)
    gift_codes_col.create_index("code", unique=True)
    coupons_col.create_index("code", unique=True)
    
    settings_col.update_one({"key": "coins_per_inr"}, {"$setOnInsert": {"key": "coins_per_inr", "value": Config.DEFAULT_COINS_PER_INR}}, upsert=True)
    settings_col.update_one({"key": "admin_upi"}, {"$setOnInsert": {"key": "admin_upi", "value": Config.DEFAULT_ADMIN_UPI}}, upsert=True)
    settings_col.update_one({"key": "payment_mode"}, {"$setOnInsert": {"key": "payment_mode", "value": "AUTO"}}, upsert=True)
    settings_col.update_one({"key": "refer_coins_reward"}, {"$setOnInsert": {"key": "refer_coins_reward", "value": "10"}}, upsert=True)

# User Authentication & Management
def register_user(username, password, phone, ref_code=None):
    clean_uname = username.strip().lower()
    if users_col.find_one({"username": clean_uname}):
        return False, "Username already exists."
    
    referrer_id = None
    if ref_code:
        ref_doc = users_col.find_one({"referral_code": ref_code.upper().strip()})
        if ref_doc:
            referrer_id = ref_doc["_id"]

    new_ref = "MXR" + secrets.token_hex(3).upper()
    hashed_pw = generate_password_hash(password)
    
    u_id = users_col.insert_one({
        "username": clean_uname,
        "password": hashed_pw,
        "phone": phone.strip(),
        "coins": 0,
        "referral_code": new_ref,
        "referred_by": referrer_id,
        "refer_completed": False,
        "refer_count": 0,
        "refer_earnings": 0,
        "role": "BUYER",
        "created_at": time.time()
    }).inserted_id

    # Give referral bonus if applicable
    if referrer_id:
        try:
            reward = int(get_setting("refer_coins_reward", "10"))
        except Exception:
            reward = 10
        users_col.update_one(
            {"_id": referrer_id},
            {"$inc": {"coins": reward, "refer_count": 1, "refer_earnings": reward}}
        )
        users_col.update_one({"_id": u_id}, {"$set": {"refer_completed": True}})

    return True, clean_uname

def authenticate_user(username, password):
    user = users_col.find_one({"username": username.strip().lower()})
    if user and check_password_hash(user["password"], password):
        return user
    return None

def get_user_by_username(username):
    return users_col.find_one({"username": username.strip().lower()})

def atomic_deduct_coins(username: str, coins: int) -> bool:
    if coins <= 0:
        return False
    res = users_col.update_one(
        {"username": username.strip().lower(), "coins": {"$gte": coins}},
        {"$inc": {"coins": -coins}}
    )
    return res.modified_count > 0

def add_user_coins(username: str, coins: int):
    if coins <= 0:
        return
    users_col.update_one({"username": username.strip().lower()}, {"$inc": {"coins": coins}})

# Products & Stock Management
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
        "name": name,
        "description": description,
        "price": price_coins,
        "stock_items": [],
        "is_active": 1,
        "created_at": time.time()
    })
    return p_id

def update_product_price(product_id: int, price: int):
    products_col.update_one({"id": product_id}, {"$set": {"price": price}})

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

# Orders
def create_order(username: str, product_id: int, product_name: str, qty: int, total_coins: int, delivered_items: list):
    order_id = f"ORD-{secrets.token_hex(4).upper()}"
    orders_col.insert_one({
        "order_id": order_id,
        "username": username.strip().lower(),
        "product_id": product_id,
        "product_name": product_name,
        "quantity": qty,
        "total_coins": total_coins,
        "delivered_items": delivered_items,
        "status": "COMPLETED",
        "created_at": time.time()
    })
    return order_id

def get_user_orders(username: str):
    return list(orders_col.find({"username": username.strip().lower()}).sort("created_at", -1))

# Deposits & UPI
def create_deposit(deposit_id: str, username: str, amount_inr: float, coins_to_add: int, deposit_type="ADD_FUNDS"):
    deposits_col.insert_one({
        "deposit_id": deposit_id,
        "username": username.strip().lower(),
        "amount_fiat": float(amount_inr),
        "coins_to_add": int(coins_to_add),
        "deposit_type": deposit_type,
        "status": "PENDING",
        "created_at": time.time(),
        "completed_at": None
    })

def complete_deposit(deposit_id: str):
    dep = deposits_col.find_one_and_update(
        {"deposit_id": deposit_id, "status": "PENDING"},
        {"$set": {"status": "COMPLETED", "completed_at": time.time()}},
        return_document=True
    )
    if not dep:
        return False, None, 0, None, None
    
    username = dep["username"]
    coins = dep["coins_to_add"]
    dep_type = dep.get("deposit_type", "ADD_FUNDS")
    gen_code = None

    if dep_type == "BUY_GIFT_CODE":
        raw = secrets.token_hex(6).upper()
        gen_code = f"MXGC-{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        gift_codes_col.insert_one({
            "code": gen_code,
            "coins": coins,
            "created_by": username,
            "is_redeemed": False,
            "created_at": time.time()
        })
    else:
        add_user_coins(username, coins)

    return True, username, coins, dep_type, gen_code

def get_user_deposits(username: str):
    return list(deposits_col.find({"username": username.strip().lower()}).sort("created_at", -1).limit(10))

# Gift Codes & Coupons
def redeem_gift_code(code: str, username: str):
    clean_code = code.upper().strip()
    item = gift_codes_col.find_one({"code": clean_code, "is_redeemed": False})
    if not item:
        return False, "Invalid or already redeemed Gift Code."
    
    gift_codes_col.update_one(
        {"code": clean_code},
        {"$set": {"is_redeemed": True, "redeemed_by": username.lower(), "redeemed_at": time.time()}}
    )
    add_user_coins(username, item["coins"])
    return True, f"Successfully redeemed +{item['coins']} Mart X Coins!"

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

def consume_coupon(code: str, username: str):
    coupons_col.update_one(
        {"code": code.upper().strip()},
        {"$set": {"is_redeemed": True, "redeemed_by": username.lower(), "redeemed_at": time.time()}}
    )

# Settings & System Stats
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
        "deposits": deposits_col.count_documents({"status": "COMPLETED"})
    }