/* static/js/security.js - Anti-Inspect & DevTools Shield */

// 1. Disable Right Click Context Menu
document.addEventListener('contextmenu', function (e) {
    e.preventDefault();
}, false);

// 2. Disable Key Shortcuts (F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U, Ctrl+S)
document.addEventListener('keydown', function (e) {
    // F12
    if (e.keyCode === 123) {
        e.preventDefault();
        return false;
    }
    // Ctrl+Shift+I (Inspect), Ctrl+Shift+J (Console), Ctrl+Shift+C (Elements)
    if (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 74 || e.keyCode === 67)) {
        e.preventDefault();
        return false;
    }
    // Ctrl+U (View Source)
    if (e.ctrlKey && e.keyCode === 85) {
        e.preventDefault();
        return false;
    }
    // Ctrl+S (Save Page)
    if (e.ctrlKey && e.keyCode === 83) {
        e.preventDefault();
        return false;
    }
}, false);

// 3. DevTools Active Detection & Debugger Trap
(function() {
    let element = new Image();
    Object.defineProperty(element, 'id', {
        get: function() {
            window.location.reload();
        }
    });
    
    // Periodic debugger trigger to freeze any forced devtools
    setInterval(function() {
        const startTime = performance.now();
        (function() {}['constructor']('debugger')());
        const endTime = performance.now();
        if (endTime - startTime > 100) {
            document.body.innerHTML = "<div style='display:flex;justify-content:center;align-items:center;height:100vh;background:#05070f;color:#ff3366;font-family:sans-serif;font-size:24px;text-align:center;'>⛔ Security Violation: Developer Tools are Prohibited!</div>";
        }
    }, 1000);
})();