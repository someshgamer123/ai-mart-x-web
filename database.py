# database.py
import time
import secrets
import requests
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

client = MongoClient(Config.MONGO_URI)
db = client[Config.DB_NAME]

# Shared Collections (Bot & Web use the SAME collections!)
users_col = db["users"]
products_col = db["products"]
orders_col = db["orders"]
deposits_col = db["deposits"]
gift_codes_col = db["gift_codes"]
coupons_col = db["coupons"]
settings_col = db["settings"]
counters_col = db["counters"]

def get_next_sequence(name: str) -> int:
    seq = counters_col.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return seq["seq"]

def init_db():
    users_col.create_index("username", sparse=True)
    users_col.create_index("user_id", unique=True, sparse=True)
    products_col.create_index("id", unique=True)
    orders_col.create_index("order_id", unique=True)
    gift_codes_col.create_index("code", unique=True)
    coupons_col.create_index("code", unique=True)

# Notify via Telegram Bot API
def send_telegram_alert(chat_id, text):
    if not Config.BOT_TOKEN or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=5)
    except Exception:
        pass

# User Operations (Web & Bot Combined)
def register_web_user(username, password, phone, telegram_id=None, ref_code=None):
    clean_uname = username.strip().lower()
    if users_col.find_one({"username": clean_uname}):
        return False, "Username already taken."
    
    numeric_id = int(telegram_id) if (telegram_id and str(telegram_id).isdigit()) else get_next_sequence("user_id") + 100000
    
    referrer_id = None
    if ref_code:
        ref_doc = users_col.find_one({"referral_code": ref_code.upper().strip()})
        if ref_doc:
            referrer_id = ref_doc.get("user_id")

    new_ref = "MXR" + secrets.token_hex(3).upper()
    hashed_pw = generate_password_hash(password)
    
    users_col.insert_one({
        "user_id": numeric_id,
        "username": clean_uname,
        "first_name": username.strip(),
        "password": hashed_pw,
        "phone_number": phone.strip(),
        "coins": 0,
        "state": "IDLE",
        "referral_code": new_ref,
        "referred_by": referrer_id,
        "refer_completed": False,
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
            {"user_id": referrer_id},
            {"$inc": {"coins": reward, "refer_count": 1, "refer_earnings": reward}}
        )
        users_col.update_one({"user_id": numeric_id}, {"$set": {"refer_completed": True}})

    return True, clean_uname

def authenticate_user(username, password):
    clean_uname = username.strip().lower()
    user = users_col.find_one({"username": clean_uname})
    if user and user.get("password") and check_password_hash(user["password"], password):
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

# Products & Stock
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
def create_order(user_id, username: str, product_id: int, product_name: str, qty: int, total_coins: int, delivered_items: list):
    order_id = f"ORD-{secrets.token_hex(4).upper()}"
    orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "username": username.strip().lower(),
        "product_id": product_id,
        "product_name": product_name,
        "quantity": qty,
        "total_coins": total_coins,
        "delivered_items": delivered_items,
        "status": "APPROVED",
        "created_at": time.time()
    })
    
    # Notify user on Telegram if bot is linked
    if user_id:
        items_text = "\n".join([f"<code>{itm}</code>" for itm in delivered_items])
        bot_msg = (
            f"🎉 <b>New Web Order Delivered!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>Order ID:</b> <code>{order_id}</code>\n"
            f"📦 <b>Item:</b> {product_name} (Qty: {qty})\n"
            f"🪙 <b>Coins:</b> {total_coins} Mart X Coins\n\n"
            f"🔑 <b>Your Delivered Items:</b>\n{items_text}\n\n"
            f"<i>Order saved in your account!</i>"
        )
        send_telegram_alert(user_id, bot_msg)
        
    return order_id

def get_user_orders(username: str):
    return list(orders_col.find({"username": username.strip().lower()}).sort("created_at", -1))

# Gift Codes & Coupons
def redeem_gift_code(code: str, user_id, username: str):
    clean_code = code.upper().strip()
    item = gift_codes_col.find_one({"code": clean_code, "is_redeemed": False})
    if not item:
        return False, "Invalid or already redeemed Gift Code."
    
    coins_val = item.get("coins", 0)
    gift_codes_col.update_one(
        {"code": clean_code},
        {"$set": {"is_redeemed": True, "redeemed_by": user_id or username.lower(), "redeemed_at": time.time()}}
    )
    add_user_coins(username, coins_val)
    return True, f"Successfully redeemed +{coins_val} Mart X Coins!"

def create_admin_gift_code(coins: int, created_by="admin"):
    raw = secrets.token_hex(6).upper()
    code = f"MXGC-{raw[:4]}-{raw[4:8]}-{raw[8:]}"
    gift_codes_col.insert_one({
        "code": code,
        "type": "COINS",
        "coins": coins,
        "product_id": 0,
        "product_name": "Wallet Coins",
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
        "product_id": 0,
        "product_name": "Store-Wide",
        "created_by": created_by,
        "is_redeemed": False,
        "created_at": time.time()
    })

def validate_coupon(code: str):
    clean = code.upper().strip()
    c = coupons_col.find_one({"code": clean, "is_redeemed": False})
    if not c:
        return None
    return c.get("discount_percent", 0)

def consume_coupon(code: str, user_id):
    coupons_col.update_one(
        {"code": code.upper().strip()},
        {"$set": {"is_redeemed": True, "redeemed_by": user_id, "redeemed_at": time.time()}}
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
