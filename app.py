# app.py
import os
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
        if "user_email" not in session:
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
    if "user_email" in session:
        user = database.get_user_by_email(session["user_email"])
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
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if action == "register":
            ref_code = request.form.get("ref_code", "").strip()
            success, msg = database.register_user(email, password, ref_code)
            if success:
                flash(msg, "success")
                return redirect(url_for("login"))
            else:
                flash(msg, "danger")
        else:
            user = database.authenticate_user(email, password)
            if user:
                session["user_email"] = user["email"]
                session.permanent = True
                flash("Login successful! Welcome to Ai Mart X.", "success")
                return redirect(url_for("index"))
            else:
                flash("Galat Gmail ya Password! Kripya dobara check karein.", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_email", None)
    flash("Aap logout ho chuke hain.", "info")
    return redirect(url_for("index"))

@app.route("/wallet")
@buyer_login_required
def wallet():
    user = database.get_user_by_email(session["user_email"])
    return render_template("wallet.html", user=user)

@app.route("/orders")
@buyer_login_required
def orders():
    user_orders = database.get_user_orders(session["user_email"])
    return render_template("orders.html", orders=user_orders)

@app.route("/refer")
@buyer_login_required
def refer():
    user = database.get_user_by_email(session["user_email"])
    reward = database.get_setting("refer_coins_reward", "10")
    return render_template("refer.html", user=user, reward=reward)

# ==================== CHECKOUT APIS ====================

@app.route("/api/checkout", methods=["POST"])
@buyer_login_required
def api_checkout():
    data = request.get_json() or {}
    product_id = int(data.get("product_id", 0))
    qty = int(data.get("quantity", 1))
    coupon_code = data.get("coupon_code", "").strip()

    prod = database.get_product(product_id)
    if not prod:
        return jsonify({"success": False, "message": "Product nahi mila."}), 404
    
    if prod["stock"] < qty or qty <= 0:
        return jsonify({"success": False, "message": f"Sirf {prod['stock']} items available hain."}), 400

    total_price = prod["price"] * qty
    discount_pct = 0
    if coupon_code:
        discount_pct = database.validate_coupon(coupon_code) or 0
        if discount_pct > 0:
            total_price = int(total_price * (1 - discount_pct / 100))

    user = database.get_user_by_email(session["user_email"])
    if user.get("coins", 0) < total_price:
        return jsonify({"success": False, "message": "Coins kam hain! Gift Code redeem karein ya friends ko invite karein."}), 400

    if not database.atomic_deduct_coins(session["user_email"], total_price):
        return jsonify({"success": False, "message": "Balance deduction failed."}), 400

    delivered_items = database.pop_product_stock_items(product_id, qty)
    order_id = database.create_order(session["user_email"], product_id, prod["name"], qty, total_price, delivered_items)

    if coupon_code and discount_pct > 0:
        database.consume_coupon(coupon_code, session["user_email"])

    return jsonify({
        "success": True,
        "order_id": order_id,
        "message": "Order complete & delivered!",
        "delivered_items": delivered_items
    })

@app.route("/api/redeem-gift-code", methods=["POST"])
@buyer_login_required
def api_redeem_gift_code():
    data = request.get_json() or {}
    code = data.get("code", "")
    success, msg = database.redeem_gift_code(code, session["user_email"])
    return jsonify({"success": success, "message": msg})

# ==================== 100% FIXED ADMIN LOGIN ====================
# Users page par iska koi link nahi hoga

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username", "").strip().lower()
        p = request.form.get("password", "").strip()

        if u == Config.ADMIN_USERNAME and p == Config.ADMIN_PASSWORD:
            session["is_admin"] = True
            session.permanent = True
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Galat Admin ID ya Password!", "danger")
            
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
    flash(f"Product '{name}' add ho gaya.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-product/<int:prod_id>", methods=["POST"])
@admin_required
def admin_del_product(prod_id):
    database.delete_product(prod_id)
    flash("Product delete ho gaya.", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/add-stock", methods=["POST"])
@admin_required
def admin_add_stock():
    p_id = int(request.form.get("product_id"))
    stock_text = request.form.get("stock_items", "")
    added, total = database.add_product_stock_items(p_id, stock_text)
    flash(f"Total {added} items add hue. Stock ab: {total}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/gen-gift-code", methods=["POST"])
@admin_required
def admin_gen_gift_code():
    coins = int(request.form.get("coins", 0))
    code = database.create_admin_gift_code(coins)
    flash(f"Gift Code: {code} (+{coins} Coins)", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/gen-coupon", methods=["POST"])
@admin_required
def admin_gen_coupon():
    code = request.form.get("code")
    pct = int(request.form.get("percent", 10))
    database.create_coupon(code, pct)
    flash(f"Coupon '{code}' ({pct}% OFF) create ho gaya.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    database.set_setting("coins_per_inr", request.form.get("rate"))
    database.set_setting("admin_upi", request.form.get("upi"))
    database.set_setting("refer_coins_reward", request.form.get("refer_reward"))
    flash("Settings update ho gayi.", "success")
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
