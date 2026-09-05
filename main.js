/* static/js/main.js - Interactivity */

function toggleDrawer() {
  const drawer = document.getElementById("menuDrawer");
  drawer.classList.toggle("open");
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert("Copied to clipboard: " + text);
  });
}

// Checkout Handler
async function openCheckout(productId, productName, price) {
  const qty = prompt(`Enter quantity for ${productName}:`, "1");
  if (!qty || isNaN(qty) || parseInt(qty) <= 0) return;

  const coupon = prompt("Have a discount coupon? Enter code (or leave empty):", "");

  const res = await fetch("/api/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: parseInt(productId),
      quantity: parseInt(qty),
      coupon_code: coupon ? coupon.trim() : ""
    })
  });

  const data = await res.json();
  if (data.success) {
    alert("🎉 " + data.message + "\nOrder ID: " + data.order_id);
    window.location.href = "/orders";
  } else {
    alert("❌ " + data.message);
  }
}