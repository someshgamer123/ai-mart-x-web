import os
import secrets
import urllib.parse
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from config import Config
import database

app = Flask(__name__)
app.config.from_object(Config)

database.init_db()

# Security Headers & Anti-Clickjacking Middleware
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval';"
    return response

# Auth Decorators
def buyer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_global_vars():
    user = None
    if "user" in session:
        user = database.get_user_by_username(session["user"])
    coins_rate = database.get_setting("coins_per_inr", Config.DEFAULT_COINS_PER_INR)
    support = Config.SUPPORT_HANDLE
    return dict(current_user=user, coins_per_inr=coins_rate, support_handle=support)

# ==================== BUYER ROUTES ====================

@app.route("/")
def index():
    products = database.get_all_products(active_only=True)
    return render_template("index.html", products=products)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if action == "register":
            phone = request.form.get("phone", "").strip()
            ref_code = request.form.get("ref_code", "").strip()
            success, msg = database.register_user(username, password, phone, ref_code)
            if success:
                session["user"] = username.lower()
                flash("Registration successful! Welcome to Ai Mart X.", "success")
                return redirect(url_for("index"))
            else:
                flash(msg, "danger")
        else:
            user = database.authenticate_user(username, password)
            if user:
                session["user"] = user["username"]
                flash("Logged in successfully.", "success")
                return redirect(url_for("index"))
            else:
                flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have logged out.", "info")
    return redirect(url_for("index"))

@app.route("/wallet")
@buyer_login_required
def wallet():
    user = database.get_user_by_username(session["user"])
    deposits = database.get_user_deposits(session["user"])
    admin_upi = database.get_setting("admin_upi", Config.DEFAULT_ADMIN_UPI)
    pay_mode = database.get_setting("payment_mode", "AUTO")
    return render_template("wallet.html", user=user, deposits=deposits, admin_upi=admin_upi, pay_mode=pay_mode)

@app.route("/orders")
@buyer_login_required
def orders():
    user_orders = database.get_user_orders(session["user"])
    return render_template("orders.html", orders=user_orders)

@app.route("/refer")
@buyer_login_required
def refer():
    user = database.get_user_by_username(session["user"])
    reward = database.get_setting("refer_coins_reward", "10")
    return render_template("refer.html", user=user, reward=reward)

# ==================== TRANSACTION & PURCHASE APIS ====================

@app.route("/api/checkout", methods=["POST"])
@buyer_login_required
def api_checkout():
    data = request.get_json() or {}
    product_id = int(data.get("product_id", 0))
    qty = int(data.get("quantity", 1))
    coupon_code = data.get("coupon_code", "").strip()

    prod = database.get_product(product_id)
    if not prod:
        return jsonify({"success": False, "message": "Product not found."}), 404
    
    if prod["stock"] < qty or qty <= 0:
        return jsonify({"success": False, "message": f"Only {prod['stock']} items available in stock."}), 400

    total_price = prod["price"] * qty
    discount_pct = 0
    if coupon_code:
        discount_pct = database.validate_coupon(coupon_code) or 0
        if discount_pct > 0:
            total_price = int(total_price * (1 - discount_pct / 100))

    user = database.get_user_by_username(session["user"])
    if user["coins"] < total_price:
        return jsonify({"success": False, "message": "Insufficient Mart X Coins in wallet. Please add funds."}), 400

    # Atomic deduction to prevent race condition
    if not database.atomic_deduct_coins(session["user"], total_price):
        return jsonify({"success": False, "message": "Transaction failed. Balance mismatch."}), 400

    delivered_items = database.pop_product_stock_items(product_id, qty)
    order_id = database.create_order(session["user"], product_id, prod["name"], qty, total_price, delivered_items)

    if coupon_code and discount_pct > 0:
        database.consume_coupon(coupon_code, session["user"])

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order completed successfully!",
        "delivered_items": delivered_items
    })

@app.route("/api/create-deposit", methods=["POST"])
@buyer_login_required
def api_create_deposit():
    data = request.get_json() or {}
    coins_req = int(data.get("coins", 0))
    dep_type = data.get("deposit_type", "ADD_FUNDS")

    if coins_req <= 0:
        return jsonify({"success": False, "message": "Invalid coins amount."}), 400

    rate = float(database.get_setting("coins_per_inr", Config.DEFAULT_COINS_PER_INR))
    amount_inr = round(coins_req / rate, 2)
    dep_id = f"DEP-{secrets.token_hex(4).upper()}"

    database.create_deposit(dep_id, session["user"], amount_inr, coins_req, deposit_type=dep_type)

    admin_upi = database.get_setting("admin_upi", Config.DEFAULT_ADMIN_UPI)
    upi_intent = f"upi://pay?pa={admin_upi}&pn=AiMartX&am={amount_inr}&cu=INR&tn={dep_id}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(upi_intent)}"

    return jsonify({
        "success": True,
        "deposit_id": dep_id,
        "amount_inr": amount_inr,
        "coins": coins_req,
        "admin_upi": admin_upi,
        "qr_url": qr_url
    })

@app.route("/api/check-deposit-status/<deposit_id>")
@buyer_login_required
def check_deposit_status(deposit_id):
    dep = database.deposits_col.find_one({"deposit_id": deposit_id})
    if not dep:
        return jsonify({"status": "NOT_FOUND"})
    return jsonify({"status": dep["status"]})

@app.route("/api/redeem-gift-code", methods=["POST"])
@buyer_login_required
def api_redeem_gift_code():
    data = request.get_json() or {}
    code = data.get("code", "")
    success, msg = database.redeem_gift_code(code, session["user"])
    return jsonify({"success": success, "message": msg})

# ==================== SECURE PAYMENT AUTO-VERIFY WEBHOOK ====================

@app.route("/webhook/payment", methods=["POST"])
def payment_webhook():
    """
    Secure Webhook receiver for payment gateways (e.g., BharatPe, Cashfree, UPI gateway).
    Supports token verification.
    """
    auth_header = request.headers.get("X-Webhook-Secret") or request.args.get("secret")
    if auth_header != Config.WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    payload = request.get_json() or {}
    status = payload.get("status") or payload.get("transactionStatus") or ""
    order_ref = payload.get("orderId") or payload.get("merchantTransactionId") or payload.get("transactionId") or ""
    amount = float(payload.get("amount") or payload.get("txnAmount") or 0.0)

    if status.upper() in ["SUCCESS", "PAID", "COMPLETED"] and order_ref:
        success, username, coins, dep_type, gen_code = database.complete_deposit(order_ref)
        if success:
            return jsonify({"status": "SUCCESS", "message": f"Deposited {coins} to {username}"}), 200

    return jsonify({"status": "IGNORED"}), 200

# ==================== ADMIN PANEL ROUTES ====================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == Config.ADMIN_USERNAME and p == Config.ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Admin authenticated successfully.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = database.get_stats()
    products = database.get_all_products(active_only=False)
    pending_deposits = list(database.deposits_col.find({"status": "PENDING"}))
    rate = database.get_setting("coins_per_inr", Config.DEFAULT_COINS_PER_INR)
    admin_upi = database.get_setting("admin_upi", Config.DEFAULT_ADMIN_UPI)
    pay_mode = database.get_setting("payment_mode", "AUTO")
    return render_template("admin.html", stats=stats, products=products, deposits=pending_deposits, rate=rate, admin_upi=admin_upi, pay_mode=pay_mode)

@app.route("/admin/add-product", methods=["POST"])
@admin_required
def admin_add_product():
    name = request.form.get("name")
    desc = request.form.get("description")
    price = int(request.form.get("price", 0))
    database.add_product(name, desc, price)
    flash(f"Product '{name}' added successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/add-stock", methods=["POST"])
@admin_required
def admin_add_stock():
    p_id = int(request.form.get("product_id"))
    stock_text = request.form.get("stock_items", "")
    added, total = database.add_product_stock_items(p_id, stock_text)
    flash(f"Added {added} items. Total stock is now {total}.", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/approve-deposit/<dep_id>")
@admin_required
def admin_approve_deposit(dep_id):
    success, u, c, t, g = database.complete_deposit(dep_id)
    if success:
        flash(f"Deposit {dep_id} approved for {u}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    database.set_setting("coins_per_inr", request.form.get("rate"))
    database.set_setting("admin_upi", request.form.get("upi"))
    database.set_setting("payment_mode", request.form.get("pay_mode"))
    flash("Settings updated successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/gen-gift-code", methods=["POST"])
@admin_required
def admin_gen_gift_code():
    coins = int(request.form.get("coins", 0))
    code = database.create_admin_gift_code(coins)
    flash(f"Generated Gift Code: {code} ({coins} Coins)", "success")
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)