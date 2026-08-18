"""Sample dataset used by POST /seed for an instant, working demo."""

SAMPLE_FEEDBACK = [
    {"channel": "app_review", "text": "Payment failed three times while trying to purchase. Very frustrating.", "customer_id": "C-101"},
    {"channel": "support_ticket", "text": "Unable to complete payment. Transaction keeps timing out at checkout.", "customer_id": "C-102"},
    {"channel": "survey", "text": "Checkout experience is frustrating, my card gets declined for no reason.", "customer_id": "C-103"},
    {"channel": "app_review", "text": "Tried to pay for my order 4 times, payment gateway keeps failing.", "customer_id": "C-104"},
    {"channel": "email", "text": "Charged twice for the same order after a failed payment attempt.", "customer_id": "C-105"},

    {"channel": "app_review", "text": "Can't log in anymore, it says invalid password even though I reset it.", "customer_id": "C-201"},
    {"channel": "support_ticket", "text": "OTP for login never arrives on my phone, tried 5 times.", "customer_id": "C-202"},
    {"channel": "survey", "text": "Sign in is broken, I keep getting locked out of my account.", "customer_id": "C-203"},

    {"channel": "app_review", "text": "My order was delivered a week late with no updates from the courier.", "customer_id": "C-301"},
    {"channel": "support_ticket", "text": "Delivery delayed again, shipment stuck at the warehouse for days.", "customer_id": "C-302"},
    {"channel": "survey", "text": "Shipping is always late, courier never shows up on the promised day.", "customer_id": "C-303"},
    {"channel": "email", "text": "Still haven't received my order, it's been delayed for over a week.", "customer_id": "C-304"},

    {"channel": "app_review", "text": "The app keeps crashing every time I open the product page.", "customer_id": "C-401"},
    {"channel": "support_ticket", "text": "App force closes constantly on Android, very buggy after the update.", "customer_id": "C-402"},

    {"channel": "survey", "text": "Support never responds, I've been waiting 3 days for a reply on my ticket.", "customer_id": "C-501"},
    {"channel": "support_ticket", "text": "On hold for over an hour, no agent ever picked up my call.", "customer_id": "C-502"},

    {"channel": "survey", "text": "The app is beautiful, just wanted to say thanks for the great experience!", "customer_id": "C-601"},
]

SAMPLE_OPERATIONAL_METRICS = [
    {"name": "payment_api_latency_ms", "baseline": 250, "current": 2400, "unit": "ms"},
    {"name": "gateway_timeout_rate", "baseline": 0.012, "current": 0.087, "unit": "rate"},
    {"name": "payment_success_rate", "baseline": 0.98, "current": 0.913, "unit": "rate"},

    {"name": "auth_latency_ms", "baseline": 180, "current": 410, "unit": "ms"},
    {"name": "otp_delivery_failure_rate", "baseline": 0.02, "current": 0.15, "unit": "rate"},
    {"name": "login_success_rate", "baseline": 0.97, "current": 0.89, "unit": "rate"},

    {"name": "warehouse_dispatch_hours", "baseline": 6, "current": 30, "unit": "hours"},
    {"name": "courier_sla_breach_rate", "baseline": 0.05, "current": 0.22, "unit": "rate"},
    {"name": "on_time_delivery_rate", "baseline": 0.94, "current": 0.78, "unit": "rate"},

    {"name": "crash_rate", "baseline": 0.004, "current": 0.031, "unit": "rate"},
    {"name": "crash_free_sessions_rate", "baseline": 0.996, "current": 0.969, "unit": "rate"},

    {"name": "avg_response_time_hours", "baseline": 2, "current": 9, "unit": "hours"},
    {"name": "ticket_backlog_count", "baseline": 40, "current": 210, "unit": "count"},
]
