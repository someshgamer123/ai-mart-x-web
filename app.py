# app.py
import os
import secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from config import Config
import database

app = Flask(__name__)
app.config.from_object(Config)

database.init_db()

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

def buyer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
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
    return dict(current_user=user, coins_per_inr=coins_rate, support_handle=Config.SUPPORT_HANDLE)

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
            telegram_id = request.form.get("telegram_id", "").strip()
            ref_code = request.form.get("ref_code", "").strip()
            success, msg = database.register_web_user(username, password, phone, telegram_id, ref_code)
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
                flash("Welcome back!", "success")
                return redirect(url_for("index"))
            else:
                flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

@app.route("/wallet")
@buyer_login_required
def wallet():
    user = database.get_user_by_username(session["user"])
    return render_template("wallet.html", user=user)

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

# ==================== CHECKOUT API ====================

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
        return jsonify({"success": False, "message": f"Only {prod['stock']} available in stock."}), 400

    total_price = prod["price"] * qty
    discount_pct = 0
    if coupon_code:
        discount_pct = database.validate_coupon(coupon_code) or 0
        if discount_pct > 0:
            total_price = int(total_price * (1 - discount_pct / 100))

    user = database.get_user_by_username(session["user"])
    if user.get("coins", 0) < total_price:
        return jsonify({"success": False, "message": "Insufficient Mart X Coins. Redeem a Gift Code or refer friends!"}), 400

    if not database.atomic_deduct_coins(session["user"], total_price):
        return jsonify({"success": False, "message": "Balance deduction failed."}), 400

    delivered_items = database.pop_product_stock_items(product_id, qty)
    order_id = database.create_order(user.get("user_id"), session["user"], product_id, prod["name"], qty, total_price, delivered_items)

    if coupon_code and discount_pct > 0:
        database.consume_coupon(coupon_code, user.get("user_id"))

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order delivered instantly!",
        "delivered_items": delivered_items
    })

@app.route("/api/redeem-gift-code", methods=["POST"])
@buyer_login_required
def api_redeem_gift_code():
    data = request.get_json() or {}
    code = data.get("code", "")
    user = database.get_user_by_username(session["user"])
    success, msg = database.redeem_gift_code(code, user.get("user_id"), session["user"])
    return jsonify({"success": success, "message": msg})

# ==================== STRICTLY SEPARATE ADMIN ROUTES ====================
# Users page has NO link to this URL. Admin can access only via /admin/login

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == Config.ADMIN_USERNAME and p == Config.ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid Admin Credentials.", "danger")
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
    rate = database.get_setting("coins_per_inr", Config.DEFAULT_COINS_PER_INR)
    upi = database.get_setting("admin_upi", Config.DEFAULT_ADMIN_UPI)
    refer_reward = database.get_setting("refer_coins_reward", "10")
    return render_template("admin.html", stats=stats, products=products, rate=rate, upi=upi, refer_reward=refer_reward)

@app.route("/admin/add-product", methods=["POST"])
@admin_required
def admin_add_product():
    name = request.form.get("name")
    desc = request.form.get("description")
    price = int(request.form.get("price", 0))
    database.add_product(name, desc, price)
    flash(f"Product '{name}' added to catalog.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-product/<int:prod_id>", methods=["POST"])
@admin_required
def admin_del_product(prod_id):
    database.delete_product(prod_id)
    flash("Product deleted.", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/add-stock", methods=["POST"])
@admin_required
def admin_add_stock():
    p_id = int(request.form.get("product_id"))
    stock_text = request.form.get("stock_items", "")
    added, total = database.add_product_stock_items(p_id, stock_text)
    flash(f"Added {added} items. Total stock is now {total}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/gen-gift-code", methods=["POST"])
@admin_required
def admin_gen_gift_code():
    coins = int(request.form.get("coins", 0))
    code = database.create_admin_gift_code(coins)
    flash(f"Generated Gift Code: {code} (+{coins} Coins)", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/gen-coupon", methods=["POST"])
@admin_required
def admin_gen_coupon():
    code = request.form.get("code")
    pct = int(request.form.get("percent", 10))
    database.create_coupon(code, pct)
    flash(f"Coupon '{code}' ({pct}% OFF) activated.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    database.set_setting("coins_per_inr", request.form.get("rate"))
    database.set_setting("admin_upi", request.form.get("upi"))
    database.set_setting("refer_coins_reward", request.form.get("refer_reward"))
    flash("Settings updated successfully.", "success")
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
