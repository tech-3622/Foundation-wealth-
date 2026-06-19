from fastapi import FastAPI, Depends, HTTPException, Request, Form, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import json
import os
import random
import string
import shutil
from typing import Optional
import hmac
import struct
import base64
import io

from backend.database import get_db, init_db
from backend.models import (
    User, AppPassword, Portfolio, Trade, Algorithm, Backtest,
    Notification, Watchlist, AuditLog, Deposit, Withdrawal, TradeSide, TradeType,
    TradeStatus, AlgoStatus, UserRole, KYCStatus
)
from backend.auth import (
    hash_password, verify_password, create_access_token,
    decode_token, get_current_user
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.dirname(BASE_DIR)

SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "foundationalweath@gmail.com",
    "password": "zujw cdky widj idjm",
    "from_email": "foundationalweath@gmail.com",
}


def send_email(to: str, subject: str, body: str, code: str = "N/A"):
    import smtplib
    import threading
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import re

    username = SMTP_CONFIG["username"]
    from_addr = SMTP_CONFIG["from_email"]

    log_entry = {"to": to, "subject": subject, "code": code, "time": datetime.utcnow().isoformat()}
    log_path = os.path.join(BASE_DIR, "email_log.json")
    try:
        logs = json.loads(open(log_path).read()) if os.path.exists(log_path) else []
    except:
        logs = []
    logs.append(log_entry)
    with open(log_path, "w") as f:
        json.dump(logs[-50:], f)

    text_body = re.sub(r'<[^>]+>', '', body).strip()
    text_body = re.sub(r'\s+', ' ', text_body)

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Foundation Wealth <{from_addr}>"
            msg["To"] = to
            msg["Reply-To"] = from_addr
            msg["Message-ID"] = f"<{abs(hash(to + subject))}@foundationwealth.app>"
            msg["List-Unsubscribe"] = f"<mailto:{from_addr}?subject=unsubscribe>"
            msg["Precedence"] = "bulk"
            msg["X-Auto-Response-Suppress"] = "OOF, DR, RN, NRN, AutoReply"

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=10) as server:
                server.starttls()
                server.login(SMTP_CONFIG["username"], SMTP_CONFIG["password"])
                server.send_message(msg)
        except Exception as e:
            print(f"Email send failed: {e}")
    threading.Thread(target=_send, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Foundation Wealth", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def get_user_from_token(request: Request, db: Session):
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        return user
    except Exception:
        return None


def login_required(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        raise HTTPException(status_code=303, detail="Login required")
    return user


def admin_required(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user or user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=303, detail="Admin access required")
    return user


def log_audit(admin_id: int, action: str, details: str, ip: str, db: Session):
    log = AuditLog(admin_id=admin_id, action=action, details=details, ip_address=ip)
    db.add(log)
    db.commit()


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "user": None})


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request):
    email = request.query_params.get("email", "")
    return templates.TemplateResponse("verify.html", {"request": request, "user": None, "email": email})


@app.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request):
    name = request.query_params.get("name", "Trader")
    return templates.TemplateResponse("welcome.html", {"request": request, "user": None, "name": name})


def generate_verification_code():
    return str(random.randint(100000, 999999))


@app.post("/api/auth/register")
async def register(
    first_name: str = Form(...),
    last_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    country: str = Form(...),
    ssn: str = Form(None),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != confirm_password:
        return JSONResponse({"error": "Passwords do not match"}, status_code=400)

    if db.query(User).filter(User.email == email).first():
        return JSONResponse({"error": "Email already registered"}, status_code=400)
    if db.query(User).filter(User.username == username).first():
        return JSONResponse({"error": "Username already taken"}, status_code=400)

    code = generate_verification_code()
    expires = datetime.utcnow() + timedelta(minutes=15)

    user = User(
        first_name=first_name,
        last_name=last_name,
        username=username,
        email=email,
        phone=phone,
        country=country,
        ssn=ssn if country == "US" else None,
        hashed_password=hash_password(password),
        role=UserRole.USER.value,
        verified=False,
        verification_code=code,
        verification_code_expires=expires,
    )
    db.add(user)
    db.commit()

    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0a0a0f;font-family:Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;"><tr><td align="center" style="padding:40px 20px;">
<table width="480" cellpadding="0" cellspacing="0" style="background:#0a0a0f;border:1px solid #1a1a2e;border-radius:12px;">
<tr><td align="center" style="padding:40px 30px 20px;">
<table width="48" cellpadding="0" cellspacing="0" style="background:#2563eb;border-radius:10px;"><tr><td align="center" style="height:48px;font-size:18px;font-weight:bold;color:#fff;">FW</td></tr></table>
<h1 style="color:#fff;font-size:20px;font-weight:700;margin:20px 0 4px;">Welcome to Foundation Wealth</h1>
<p style="color:#888;font-size:14px;margin:0 0 24px;">Your verification code</p>
</td></tr>
<tr><td align="center" style="padding:0 30px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111118;border:1px solid #1a1a2e;border-radius:10px;"><tr><td align="center" style="padding:24px;">
<p style="color:#888;font-size:13px;margin:0 0 12px;">Enter this code to verify your email</p>
<p style="font-size:36px;font-weight:bold;letter-spacing:6px;color:#60a5fa;font-family:Courier,monospace;margin:0;">{code}</p>
<p style="color:#555;font-size:12px;margin:16px 0 0;">Expires in 15 minutes</p>
</td></tr></table>
</td></tr>
<tr><td align="center" style="padding:20px 30px 40px;">
<p style="color:#555;font-size:12px;margin:0;">If you didn't create an account, ignore this email.</p>
</td></tr></table>
</td></tr></table>
</body></html>"""
    send_email(email, "Verify your Foundation Wealth account", html_body, code=code)

    response = RedirectResponse(url=f"/verify?email={email}", status_code=303)
    return response


@app.post("/api/auth/verify")
async def verify_email(
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    if user.email_verified:
        return RedirectResponse(url="/dashboard", status_code=303)
    if user.verification_code != code:
        return JSONResponse({"error": "Invalid verification code"}, status_code=400)
    if user.verification_code_expires and datetime.utcnow() > user.verification_code_expires:
        return JSONResponse({"error": "Verification code expired. Request a new one."}, status_code=400)

    user.email_verified = True
    user.verification_code = None
    user.verification_code_expires = None
    db.commit()

    welcome_html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0a0a0f;font-family:Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;"><tr><td align="center" style="padding:40px 20px;">
<table width="480" cellpadding="0" cellspacing="0" style="background:#0a0a0f;border:1px solid #1a1a2e;border-radius:12px;">
<tr><td align="center" style="padding:40px 30px 20px;">
<table width="48" cellpadding="0" cellspacing="0" style="background:#2563eb;border-radius:10px;"><tr><td align="center" style="height:48px;font-size:18px;font-weight:bold;color:#fff;">FW</td></tr></table>
<h1 style="color:#fff;font-size:20px;font-weight:700;margin:20px 0 4px;">Welcome, {user.first_name or user.username}</h1>
<p style="color:#888;font-size:14px;margin:0 0 24px;">Your account has been verified</p>
</td></tr>
<tr><td align="center" style="padding:0 30px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111118;border:1px solid #1a1a2e;border-radius:10px;"><tr><td style="padding:24px;">
<p style="color:#ccc;font-size:14px;margin:0 0 16px;">You're now ready. Here's what you can do:</p>
<table cellpadding="0" cellspacing="0"><tr><td style="padding:4px 0;color:#888;font-size:13px;">Explore live markets with real-time data</td></tr>
<tr><td style="padding:4px 0;color:#888;font-size:13px;">Build and deploy trading algorithms</td></tr>
<tr><td style="padding:4px 0;color:#888;font-size:13px;">Track your portfolio performance</td></tr>
<tr><td style="padding:4px 0;color:#888;font-size:13px;">Bank-grade security always on</td></tr></table>
</td></tr></table>
</td></tr>
<tr><td align="center" style="padding:24px 30px 40px;">
<p style="color:#555;font-size:12px;margin:0;">Need help? Reply to this email.</p>
</td></tr></table>
</td></tr></table>
</body></html>"""
    send_email(user.email, "Welcome to Foundation Wealth!", welcome_html)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    response = RedirectResponse(url=f"/welcome?name={user.first_name or user.username}", status_code=303)
    response.set_cookie(key="token", value=token, httponly=True, max_age=86400 * 7)
    return response


@app.post("/api/auth/resend-code")
async def resend_code(
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    if user.email_verified:
        return JSONResponse({"error": "Email already verified"}, status_code=400)

    code = generate_verification_code()
    user.verification_code = code
    user.verification_code_expires = datetime.utcnow() + timedelta(minutes=15)
    db.commit()

    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0a0a0f;font-family:Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;"><tr><td align="center" style="padding:40px 20px;">
<table width="480" cellpadding="0" cellspacing="0" style="background:#0a0a0f;border:1px solid #1a1a2e;border-radius:12px;">
<tr><td align="center" style="padding:40px 30px 20px;">
<table width="48" cellpadding="0" cellspacing="0" style="background:#2563eb;border-radius:10px;"><tr><td align="center" style="height:48px;font-size:18px;font-weight:bold;color:#fff;">FW</td></tr></table>
<h1 style="color:#fff;font-size:20px;font-weight:700;margin:20px 0 4px;">New Verification Code</h1>
</td></tr>
<tr><td align="center" style="padding:0 30px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111118;border:1px solid #1a1a2e;border-radius:10px;"><tr><td align="center" style="padding:24px;">
<p style="font-size:36px;font-weight:bold;letter-spacing:6px;color:#60a5fa;font-family:Courier,monospace;margin:0;">{code}</p>
<p style="color:#555;font-size:12px;margin:16px 0 0;">Expires in 15 minutes</p>
</td></tr></table>
</td></tr>
<tr><td align="center" style="padding:24px 30px 40px;">
<p style="color:#555;font-size:12px;margin:0;">If you didn't request this, ignore this email.</p>
</td></tr></table>
</td></tr></table>
</body></html>"""
    send_email(email, "New verification code - Foundation Wealth", html_body, code=code)

    return JSONResponse({"status": "sent"})


@app.get("/api/dev/email-log")
async def dev_email_log():
    log_path = os.path.join(BASE_DIR, "email_log.json")
    if not os.path.exists(log_path):
        return {"emails": []}
    try:
        logs = json.loads(open(log_path).read())
        return {"emails": logs}
    except:
        return {"emails": []}


@app.get("/dev/verify-code")
async def dev_verify_code(email: str = ""):
    log_path = os.path.join(BASE_DIR, "email_log.json")
    if not os.path.exists(log_path):
        return HTMLResponse("<div style='padding:2rem;color:#888;'>No emails sent yet.</div>")
    try:
        logs = json.loads(open(log_path).read())
        for entry in reversed(logs):
            if entry["to"] == email or not email:
                code = entry.get("code", "N/A")
                return HTMLResponse(f"""
                <div style="padding:2rem;font-family:monospace;">
                    <p style="color:#60a5fa;font-size:2rem;font-weight:800;letter-spacing:4px;">{code}</p>
                    <p style="color:#888;font-size:0.85rem;margin-top:0.5rem;">Sent to {entry['to']} at {entry['time']}</p>
                    <p style="color:#555;font-size:0.75rem;margin-top:1rem;">Subject: {entry['subject']}</p>
                </div>
                """)
    except:
        pass
    return HTMLResponse("<div style='padding:2rem;color:#888;'>No code found.</div>")


@app.post("/api/auth/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return JSONResponse({"error": "Invalid email or password"}, status_code=400)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    if not user.email_verified:
        response = RedirectResponse(url=f"/verify?email={email}", status_code=303)
    elif user.role == "admin":
        response = RedirectResponse(url="/admin", status_code=303)
    else:
        response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="token", value=token, httponly=True, max_age=86400 * 7)
    return response


@app.post("/api/auth/app-password")
async def create_app_password(
    name: str = Form(...),
    db: Session = Depends(get_db),
    request: Request = None,
):
    user = login_required(request, db)
    raw_password = "".join(random.choices(string.ascii_letters + string.digits, k=24))
    app_pw = AppPassword(
        user_id=user.id,
        name=name,
        hashed_password=hash_password(raw_password),
    )
    db.add(app_pw)
    db.commit()
    return JSONResponse({"name": name, "password": raw_password})


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("token")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user.id).all()
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.created_at.desc()).limit(20).all()
    algorithms = db.query(Algorithm).filter(Algorithm.user_id == user.id).all()
    notifications = db.query(Notification).filter(Notification.user_id == user.id, Notification.read == False).count()
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()

    filled = [t for t in trades if t.status == "filled"]
    wins = len([t for t in filled if t.side == "sell" and t.filled_price and t.price and t.filled_price > t.price])
    win_rate = round((wins / len(filled) * 100) if filled else 0, 1)

    portfolio_value = (user.balance or 0) + sum(
        (p.avg_price * p.quantity) for p in portfolios if p.quantity > 0
    )

    all_prices = generate_market_prices()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "portfolios": portfolios,
        "trades": trades,
        "algorithms": algorithms,
        "notifications": notifications,
        "watchlists": watchlists,
        "win_rate": win_rate,
        "portfolio_value": portfolio_value,
        "symbol_logos": SYMBOL_LOGOS,
        "market_prices": all_prices,
        "all_symbols": MARKET_SYMBOLS,
    })


DEPOSIT_ADDRESSES = {
    "BTC": {"address": "1MoiNzm1W3cPPwU4zXnR595knr6DWkowzY", "network": "Bitcoin", "note": "Send only BTC on Bitcoin network"},
    "SOL": {"address": "H5vTgB3Q611T1sDjtg3snmxYcmqhpCRKLBYZGs3N782q", "network": "Solana", "note": "Send only SOL on Solana network"},
    "USDT": {"address": "TQznrvJETvuCPYhxzpxhFJ17RjYNYjZyu8", "network": "TRC20 (Tron)", "note": "Send only USDT on TRC20 network"},
    "ETH": {"address": "0x0ee56d3d93166ef98d6e8bf420a9348f48582429", "network": "ERC20 (Ethereum)", "note": "Send only ETH on ERC20 network"},
}


@app.get("/wallet", response_class=HTMLResponse)
async def wallet_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    deposits = db.query(Deposit).filter(Deposit.user_id == user.id).order_by(Deposit.created_at.desc()).all()
    return templates.TemplateResponse("wallet.html", {
        "request": request,
        "user": user,
        "deposits": deposits,
        "symbol_logos": SYMBOL_LOGOS,
        "deposit_addresses": DEPOSIT_ADDRESSES,
    })


ASSET_TYPES = {
    "stock": {"name": "Stocks",     "icon": "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",                          "color": "blue",      "badge": "badge-stock"},
    "crypto": {"name": "Crypto",    "icon": "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", "color": "amber",     "badge": "badge-crypto"},
    "forex": {"name": "Forex",      "icon": "M3 6l2.5 2.5L8 6l2.5 2.5L13 6l2.5 2.5L18 6l2.5 2.5L21 6M3 12l2.5 2.5L8 12l2.5 2.5L13 12l2.5 2.5L18 12l2.5 2.5L21 12M3 18l2.5 2.5L8 18l2.5 2.5L13 18l2.5 2.5L18 18l2.5 2.5L21 18", "color": "green",     "badge": "badge-forex"},
    "commodity": {"name": "Commodities", "icon": "M13 10V3L4 14h7v7l9-11h-7z",                          "color": "red",       "badge": "badge-commodity"},
    "etf": {"name": "ETFs",         "icon": "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z", "color": "purple",    "badge": "badge-etf"},
    "index": {"name": "Indices",    "icon": "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", "color": "indigo",    "badge": "badge-index"},
    "bond": {"name": "Bonds",       "icon": "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", "color": "yellow",    "badge": "badge-bond"},
    "reit": {"name": "REITs",       "icon": "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4", "color": "pink",      "badge": "badge-reit"},
}

MARKET_SYMBOLS = {
    "AAPL": {"type": "stock", "base": 218}, "TSLA": {"type": "stock", "base": 245},
    "NVDA": {"type": "stock", "base": 892}, "MSFT": {"type": "stock", "base": 425},
    "GOOGL": {"type": "stock", "base": 176}, "AMZN": {"type": "stock", "base": 198},
    "META": {"type": "stock", "base": 512}, "JPM": {"type": "stock", "base": 205},
    "V": {"type": "stock", "base": 278},
    "BTC": {"type": "crypto", "base": 67540}, "ETH": {"type": "crypto", "base": 3456},
    "SOL": {"type": "crypto", "base": 142}, "XRP": {"type": "crypto", "base": 0.62},
    "DOGE": {"type": "crypto", "base": 0.168}, "ADA": {"type": "crypto", "base": 0.52},
    "DOT": {"type": "crypto", "base": 7.85}, "LINK": {"type": "crypto", "base": 16.40},
    "EUR/USD": {"type": "forex", "base": 1.0845}, "GBP/USD": {"type": "forex", "base": 1.2678},
    "USD/JPY": {"type": "forex", "base": 151.2}, "AUD/USD": {"type": "forex", "base": 0.6590},
    "NZD/USD": {"type": "forex", "base": 0.6140}, "USD/CAD": {"type": "forex", "base": 1.3625},
    "XAU/USD": {"type": "commodity", "base": 2345}, "XAG/USD": {"type": "commodity", "base": 27.5},
    "CL": {"type": "commodity", "base": 78.3}, "NG": {"type": "commodity", "base": 2.64},
    "HG": {"type": "commodity", "base": 4.52},
    "SPY": {"type": "etf", "base": 548}, "QQQ": {"type": "etf", "base": 442},
    "VOO": {"type": "etf", "base": 498}, "IWM": {"type": "etf", "base": 208},
    "EEM": {"type": "etf", "base": 41.5}, "XLK": {"type": "etf", "base": 218},
    "SPX": {"type": "index", "base": 5432}, "IXIC": {"type": "index", "base": 18345},
    "DJI": {"type": "index", "base": 41230}, "RUT": {"type": "index", "base": 2180},
    "VIX": {"type": "index", "base": 14.2},
    "US10Y": {"type": "bond", "base": 4.32}, "AGG": {"type": "bond", "base": 97.5},
    "BND": {"type": "bond", "base": 72.8}, "TLT": {"type": "bond", "base": 92.4},
    "PLD": {"type": "reit", "base": 142.5}, "AMT": {"type": "reit", "base": 198.3},
    "O": {"type": "reit", "base": 58.4}, "SPG": {"type": "reit", "base": 156.2},
}

SYMBOL_LOGOS = {
    "AAPL": {"path": "M18.5 2.5C17.5 3.5 16.8 5 16.8 6.5c0 .2.2.5.3.5 1 .2 2.4-.5 3.2-1.5.8-1 1.2-2.3 1.2-3 0-.2-.2-.5-.3-.5-1.2-.2-2.2.5-2.7 1.5zM21 8.5c-1.5-1-2.2-2-2.7-3-.5-1-.7-2-.7-3 0-.3.2-.5.5-.5.3 0 .7.2 1.2.7 1 1 2.2 2.5 2.7 4.5.2.8.3 1.5.3 2 0 .3-.2.5-.5.5-.5 0-1-.2-1.5-.7zM12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm3.5 15.5c-.3.5-.7.7-1.2.7-.3 0-.7-.2-1-.5-.3-.3-.7-.5-1-.5s-.7.2-1 .5c-.3.3-.7.5-1 .5-.5 0-.8-.2-1-.5l-.5-.7c-.3-.5-.7-.8-1.2-.8-.5 0-1 .2-1.5.5v-.5c.5-.5 1-.8 1.5-.8.5 0 1 .3 1.3.8.3.5.7.7 1.2.7s.8-.2 1-.5c.3-.3.7-.5 1-.5s.7.2 1 .5c.3.3.7.5 1 .5.5 0 .8-.3 1-.7l.2-.3c.3.2.5.3.7.3.5 0 1-.3 1.5-.8v.5c-.5.5-1 .8-1.5.8-.3 0-.5-.2-.7-.5z", "color": "#555"},
    "TSLA": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5.5 7.5h-3l-1-5h-3l-1 5h-3l-1 5h3l1 5h3l-1-5h3z", "color": "#e82127"},
    "NVDA": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c.55 0 1 .45 1 1v8c0 .55-.45 1-1 1s-1-.45-1-1V6c0-.55.45-1 1-1zm-4 4c.55 0 1 .45 1 1v4c0 .55-.45 1-1 1s-1-.45-1-1v-4c0-.55.45-1 1-1zm8 0c.55 0 1 .45 1 1v4c0 .55-.45 1-1 1s-1-.45-1-1v-4c0-.55.45-1 1-1z", "color": "#76b900"},
    "MSFT": {"path": "M2 2h9v9H2V2zm11 0h9v9h-9V2zM2 13h9v9H2v-9zm11 0h9v9h-9v-9z", "color": "#00a4ef"},
    "GOOGL": {"path": "M12.5 11.5V8h-1v3.5H8v1h3.5V16h1v-3.5H16v-1h-3.5z", "color": "#4285f4"},
    "AMZN": {"path": "M12 2l10 20H2L12 2zm0 4L5 18h14L12 6z", "color": "#ff9900"},
    "META": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 7h-2.5l-1.5 3-1.5-3H9l-1 5h2l.5-2.5L12 14l1.5-3.5L14 14h2l-1-5z", "color": "#1877f2"},
    "JPM": {"path": "M6 6h4v12H6V6zm8 0h4v12h-4V6z", "color": "#003087"},
    "V": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm3.5 6.5c-.3 0-.5.2-.5.5v5c0 .8-.7 1.5-1.5 1.5s-1.5-.7-1.5-1.5V9c0-.3-.2-.5-.5-.5s-.5.2-.5.5v5c0 1.4 1.1 2.5 2.5 2.5s2.5-1.1 2.5-2.5V9c0-.3-.2-.5-.5-.5z", "color": "#1a1f71"},
    "BTC": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.5 11c0 1.5-1 2.5-2.5 2.8V17h-1.5v-1.2h-1V17H10v-1.2c-1.5-.3-2.5-1.3-2.5-2.8h1.5c0 .8.7 1.5 1.5 1.5h3c.8 0 1.5-.7 1.5-1.5s-.7-1.5-1.5-1.5h-2c-1.7 0-3-1.3-3-3s1.3-3 3-3V7h1.5v1.2h1V7H14v1.2c1.5.3 2.5 1.3 2.5 2.8H15c0-.8-.7-1.5-1.5-1.5h-3c-.8 0-1.5.7-1.5 1.5s.7 1.5 1.5 1.5h2c1.7 0 3 1.3 3 3z", "color": "#f7931a"},
    "ETH": {"path": "M12 2l8 12-8 4-8-4 8-12zm0 3.5L7 12l5 2 5-2-5-6.5z", "color": "#627eea"},
    "SOL": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm4 7c0 2.2-1.8 4-4 4s-4-1.8-4-4 1.8-4 4-4 4 1.8 4 4z", "color": "#9945ff"},
    "XRP": {"path": "M12 2L6 8l6 6 6-6-6-6zm0 8L8 6l4-4 4 4-4 4zm0 4l-6 6 6 6 6-6-6-6zm0 8l-4-4 4-4 4 4-4 4z", "color": "#00aae4"},
    "DOGE": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm3 14h-2c-2.2 0-4-1.8-4-4s1.8-4 4-4h2v2h-2c-1.1 0-2 .9-2 2s.9 2 2 2h2v2z", "color": "#c2a633"},
    "ADA": {"path": "M12 2L2 20h20L12 2zm0 4l7 13H5l7-13zm0 2l-4 8h8l-4-8z", "color": "#0033ad"},
    "DOT": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm0 9.5c-1.93 0-3.5-1.57-3.5-3.5s1.57-3.5 3.5-3.5 3.5 1.57 3.5 3.5-1.57 3.5-3.5 3.5z", "color": "#e6007a"},
    "LINK": {"path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3l3 5-3 5-3-5 3-5zm0 10l-3-5 3-5 3 5-3 5z", "color": "#375bd2"},
    "EUR/USD": {"path": "M7 4h10l-2 16H9L7 4zm2 0h2l1 16h-2l-1-16zm4 0h2l-1 16h-2l1-16z", "color": "#1e88e5"},
    "GBP/USD": {"path": "M7 4h10l-2 16H9L7 4zm3 4h4l-1 8h-2l-1-8z", "color": "#1e88e5"},
    "USD/JPY": {"path": "M7 4h10v3H7V4zm0 6h10v3H7v-3zm0 6h10v3H7v-3z", "color": "#1e88e5"},
    "AUD/USD": {"path": "M7 4h10l-2 8H9L7 4zm5 8l2 8H10l2-8z", "color": "#1e88e5"},
    "NZD/USD": {"path": "M7 4h10v3H7V4zm0 6h10v3H7v-3z", "color": "#1e88e5"},
    "USD/CAD": {"path": "M7 4h10l-3 16h-4L7 4zm4 0h2l-2 14h-2l2-14z", "color": "#1e88e5"},
    "XAU/USD": {"path": "M8 4h8l4 16H4L8 4zm1 2l-3 14h12l-3-14H9zm1 2h4l2 10h-8l2-10z", "color": "#f59e0b"},
    "XAG/USD": {"path": "M12 2l10 20H2L12 2zm0 4L5 18h14L12 6z", "color": "#9ca3af"},
    "CL": {"path": "M8 4h8v5l4 6v5H4v-5l4-6V4zm2 0v5l-4 6v3h12v-3l-4-6V4h-4z", "color": "#ef4444"},
    "NG": {"path": "M10 4h4v6l-4 4V4zm2 10l4-4v10h-4V14z", "color": "#f97316"},
    "HG": {"path": "M8 4h8v4l2 2v10H6V10l2-2V4zm2 2v3.5L8.5 11v7h7v-7L14 9.5V6h-4z", "color": "#d97706"},
    "SPY": {"path": "M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z", "color": "#6366f1"},
    "QQQ": {"path": "M4 4h16v3H4V4zm0 5h10v3H4V9zm13 0h3v3h-3V9zM4 14h16v3H4v-3z", "color": "#6366f1"},
    "VOO": {"path": "M4 4h16v2H4V4zm0 4h16v2H4V8zm0 4h16v2H4v-2zm0 4h16v2H4v-2z", "color": "#6366f1"},
    "IWM": {"path": "M4 4h16v3H4V4zm0 6h16v3H4v-3zm0 6h16v3H4v-3z", "color": "#6366f1"},
    "EEM": {"path": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5", "color": "#6366f1"},
    "XLK": {"path": "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z", "color": "#6366f1"},
    "SPX": {"path": "M4 18l4-8 4 4 4-8 4 12-4-4-4 8-4-4-4 8z", "color": "#8b5cf6"},
    "IXIC": {"path": "M4 18l3-6 4 3 4-9 5 12-4-5-4 9-4-3-4 6z", "color": "#8b5cf6"},
    "DJI": {"path": "M4 18l3-4 4 2 4-8 5 10-4-4-4 8-4-2-4 4z", "color": "#8b5cf6"},
    "RUT": {"path": "M4 18l4-6 4 3 4-9 4 12-4-4-4 9-4-3-4 6z", "color": "#8b5cf6"},
    "VIX": {"path": "M4 18l3-8 4 4 5-10 4 14-4-6-5 10-4-4-3 8z", "color": "#8b5cf6"},
    "US10Y": {"path": "M8 4v16h8V4H8zm2 2h4v12h-4V6z", "color": "#eab308"},
    "AGG": {"path": "M6 4h12v2H6V4zm0 4h12v2H6V8zm0 4h12v2H6v-2zm0 4h12v2H6v-2z", "color": "#eab308"},
    "BND": {"path": "M6 4h12v2H6V4zm0 4h12v2H6V8zm0 4h12v2H6v-2zm0 4h12v2H6v-2z", "color": "#eab308"},
    "TLT": {"path": "M10 4h4v16h-4V4zM6 8h4v12H6V8zm8 0h4v12h-4V8z", "color": "#eab308"},
    "PLD": {"path": "M6 4h12v3H6V4zm2 5h8v12H8V9zm2 2v8h4v-8h-4z", "color": "#ec4899"},
    "AMT": {"path": "M5 4h14v3H5V4zm3 5h8v12H8V9zm2 2v8h4v-8h-4zm-6 0h4v8H4v-8z", "color": "#ec4899"},
    "O": {"path": "M8 4h8v16H8V4zm2 2v12h4V6h-4z", "color": "#ec4899"},
    "SPG": {"path": "M6 4h12v3H6V4zm2 5h8v12H8V9zm2 2v8h4v-8h-4z", "color": "#ec4899"},
}

def get_symbol_logo(symbol):
    return SYMBOL_LOGOS.get(symbol, {"path": "", "color": "#666"})


def generate_market_prices(symbols_dict=None):
    src = symbols_dict or MARKET_SYMBOLS
    prices = {}
    for s, info in src.items():
        base = info["base"]
        vol = base * 0.02
        price = round(base + random.uniform(-vol, vol), 2)
        chg = round(random.uniform(-vol * 0.5, vol * 0.5), 2)
        chg_pct = round((chg / base) * 100, 2)
        prices[s] = {"price": price, "change": chg, "change_pct": chg_pct, "type": info["type"]}
    return prices

def generate_candles(symbol: str, base_price: float, count: int, volatility: float = 0.02):
    data = []
    price = base_price
    for _ in range(count):
        o = round(price, 2)
        h = round(o * (1 + random.uniform(0, volatility)), 2)
        l = round(o * (1 - random.uniform(0, volatility)), 2)
        c = round(random.uniform(l, h), 2)
        v = random.randint(10000, 500000)
        data.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c
    return data


@app.get("/invest", response_class=HTMLResponse)
async def invest_overview(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    all_prices = generate_market_prices()
    all_types_data = {}
    for k, v in ASSET_TYPES.items():
        syms = {s: info for s, info in MARKET_SYMBOLS.items() if info["type"] == k}
        prices = {s: p for s, p in all_prices.items() if p["type"] == k}
        movers = sorted(prices.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        all_types_data[k] = {
            "name": v["name"], "color": v["color"], "icon": v["icon"],
            "badge": v["badge"], "count": len(syms),
            "top_gainer": movers[0] if movers else None,
            "top_loser": movers[-1] if movers else None,
        }
    all_movers = sorted(all_prices.items(), key=lambda x: x[1]["change_pct"], reverse=True)
    gainers = all_movers[:6]
    losers = list(reversed(all_movers[-6:])) if len(all_movers) >= 6 else list(reversed(all_movers))
    advancers = sum(1 for p in all_prices.values() if p["change_pct"] >= 0)
    decliners = sum(1 for p in all_prices.values() if p["change_pct"] < 0)
    total_volume = sum(abs(int(p["price"] * 50000)) for p in all_prices.values())
    return templates.TemplateResponse("invest_overview.html", {
        "request": request, "user": user,
        "all_types": all_types_data,
        "gainers": gainers, "losers": losers,
        "advancers": advancers, "decliners": decliners,
        "total_volume": total_volume,
        "total_symbols": len(MARKET_SYMBOLS),
        "symbol_logos": SYMBOL_LOGOS,
    })


@app.get("/invest/{asset_type}", response_class=HTMLResponse)
async def invest_type_page(asset_type: str, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if asset_type not in ASSET_TYPES:
        return HTMLResponse("Asset type not found", status_code=404)
    type_info = ASSET_TYPES[asset_type]
    symbols = {s: info for s, info in MARKET_SYMBOLS.items() if info["type"] == asset_type}
    prices = generate_market_prices(symbols)
    all_types = {k: v["name"] for k, v in ASSET_TYPES.items()}
    user_positions = {}
    if user:
        for p in db.query(Portfolio).filter(Portfolio.user_id == user.id).all():
            user_positions[p.symbol] = {"qty": p.quantity, "avg_price": p.avg_price}
    return templates.TemplateResponse("invest_list.html", {
        "request": request, "user": user,
        "asset_type": asset_type, "type_info": type_info,
        "symbols": symbols, "prices": prices, "all_types": all_types,
        "user_positions": user_positions,
        "symbol_logos": SYMBOL_LOGOS,
    })

@app.get("/invest/{asset_type}/{symbol}", response_class=HTMLResponse)
async def invest_symbol_page(asset_type: str, symbol: str, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    symbol_upper = symbol.upper()
    if asset_type not in ASSET_TYPES or symbol_upper not in MARKET_SYMBOLS or MARKET_SYMBOLS[symbol_upper]["type"] != asset_type:
        return HTMLResponse("Symbol not found", status_code=404)
    type_info = ASSET_TYPES[asset_type]
    all_prices = generate_market_prices()
    price_data = all_prices.get(symbol_upper, {"price": 0, "change": 0, "change_pct": 0, "type": asset_type})
    related = {s: p for s, p in all_prices.items() if p["type"] == asset_type and s != symbol_upper}
    base_price = MARKET_SYMBOLS[symbol_upper]["base"]
    candle_data = {
        "1d": generate_candles(symbol_upper, base_price, 24, 0.008),
        "1w": generate_candles(symbol_upper, base_price, 7, 0.015),
        "1m": generate_candles(symbol_upper, base_price, 30, 0.025),
        "3m": generate_candles(symbol_upper, base_price, 12, 0.04),
        "1y": generate_candles(symbol_upper, base_price, 12, 0.06),
    }
    sparkline_data = [round(base_price * (1 + random.uniform(-0.03, 0.03)), 2) for _ in range(20)]
    position = None
    if user:
        pos = db.query(Portfolio).filter(Portfolio.user_id == user.id, Portfolio.symbol == symbol_upper).first()
        if pos and pos.quantity > 0:
            current_val = pos.quantity * price_data["price"]
            cost_basis = pos.quantity * pos.avg_price
            position = {
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_value": round(current_val, 2),
                "cost_basis": round(cost_basis, 2),
                "unrealized_pl": round(current_val - cost_basis, 2),
                "unrealized_pl_pct": round(((price_data["price"] - pos.avg_price) / pos.avg_price) * 100, 2),
            }
    return templates.TemplateResponse("invest_detail.html", {
        "request": request, "user": user,
        "asset_type": asset_type, "type_info": type_info,
        "symbol": symbol_upper, "price_data": price_data,
        "related": dict(list(related.items())[:6]),
        "sparkline_data": sparkline_data,
        "candle_data": candle_data,
        "position": position,
        "symbol_logos": SYMBOL_LOGOS,
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    user = admin_required(request, db)
    users = db.query(User).all()
    trades = db.query(Trade).order_by(Trade.created_at.desc()).limit(100).all()
    algorithms = db.query(Algorithm).all()
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()
    portfolios = db.query(Portfolio).all()

    total_balance = db.query(func.coalesce(func.sum(User.balance), 0)).scalar()
    total_trade_volume = db.query(func.coalesce(func.sum(Trade.total), 0)).filter(Trade.status == "filled").scalar()
    total_filled_trades = db.query(Trade).filter(Trade.status == "filled").count()
    verified_count = db.query(User).filter(User.verified == True).count()
    active_algos = db.query(Algorithm).filter(Algorithm.status == "active").count()
    total_portfolio_value = db.query(func.coalesce(func.sum(Portfolio.quantity * Portfolio.avg_price), 0)).scalar()

    recent_users = db.query(User).order_by(User.created_at.desc()).limit(10).all()

    users_last_7 = db.query(func.date(User.created_at), func.count(User.id)).filter(
        User.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    ).group_by(func.date(User.created_at)).order_by(func.date(User.created_at)).all()

    growth_dates = [(datetime.now(timezone.utc) - timedelta(days=i)).strftime("%a") for i in range(6, -1, -1)]
    growth_counts = {}
    for row in users_last_7:
        d = row[0]
        c = row[1]
        if hasattr(d, 'strftime'):
            growth_counts[d.strftime("%a")] = c
        else:
            growth_counts[str(d)[:3]] = c
    growth_data = {"labels": growth_dates, "counts": [growth_counts.get(d, 0) for d in growth_dates]}

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
        "trades": trades,
        "algorithms": algorithms,
        "logs": logs,
        "portfolios": portfolios,
        "total_balance": total_balance,
        "total_trade_volume": total_trade_volume,
        "total_filled_trades": total_filled_trades,
        "verified_count": verified_count,
        "active_algos": active_algos,
        "total_portfolio_value": total_portfolio_value,
        "recent_users": recent_users,
        "growth_data": growth_data,
        "kyc_pending_count": db.query(User).filter(User.kyc_status == KYCStatus.PENDING.value).count(),
    })


@app.get("/api/user/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "balance": user.balance,
        "kyc_status": user.kyc_status,
        "verified": user.verified,
    }


@app.get("/api/portfolio")
async def get_portfolio(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user.id).all()
    return [
        {"symbol": p.symbol, "quantity": p.quantity, "avg_price": p.avg_price}
        for p in portfolios
    ]


@app.get("/api/trades")
async def get_trades(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "type": t.type,
            "quantity": t.quantity,
            "price": t.price,
            "filled_price": t.filled_price,
            "status": t.status,
            "total": t.total,
            "created_at": t.created_at.isoformat(),
        }
        for t in trades
    ]


@app.post("/api/trades")
async def create_trade(
    request: Request,
    symbol: str = Form(...),
    side: str = Form(...),
    trade_type: str = Form(...),
    quantity: float = Form(...),
    price: Optional[str] = Form(None),
    do_redirect: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)

    def err_redirect(code: str):
        if do_redirect:
            ref = str(request.headers.get("referer", "/invest"))
            return RedirectResponse(url=ref + ("&" if "?" in ref else "?") + "trade=" + code, status_code=303)
        return None

    if user.role != UserRole.ADMIN.value and user.kyc_status != KYCStatus.VERIFIED.value:
        r = err_redirect("kyc")
        if r: return r
        return JSONResponse({"error": "KYC verification required to trade"}, status_code=403)

    qty = abs(quantity)
    if qty <= 0:
        r = err_redirect("error")
        if r: return r
        return JSONResponse({"error": "Quantity must be positive"}, status_code=400)

    sym = symbol.upper()
    if sym not in MARKET_SYMBOLS:
        r = err_redirect("error")
        if r: return r
        return JSONResponse({"error": "Unknown symbol"}, status_code=400)

    prices = generate_market_prices()
    if sym not in prices:
        r = err_redirect("error")
        if r: return r
        return JSONResponse({"error": "Market price not available"}, status_code=503)
    current_price = prices[sym]["price"]
    fill_price = current_price
    if price is not None:
        try:
            p = float(price)
            if p > 0:
                fill_price = p
        except (ValueError, TypeError):
            pass
    total = round(fill_price * qty, 2)

    if side == "buy":
        if user.balance < total:
            r = err_redirect("insufficient_balance")
            if r: return r
            return JSONResponse({"error": f"Insufficient balance. Need ${total:,.2f}, have ${user.balance:,.2f}"}, status_code=400)

        user.balance = round(user.balance - total, 2)

        portfolio = db.query(Portfolio).filter(Portfolio.user_id == user.id, Portfolio.symbol == sym).first()
        if portfolio:
            new_qty = portfolio.quantity + qty
            portfolio.avg_price = round(((portfolio.avg_price * portfolio.quantity) + (fill_price * qty)) / new_qty, 2)
            portfolio.quantity = new_qty
        else:
            portfolio = Portfolio(user_id=user.id, symbol=sym, quantity=qty, avg_price=fill_price)
            db.add(portfolio)

        trade = Trade(
            user_id=user.id, symbol=sym, side="buy", type=trade_type,
            quantity=qty, price=fill_price, filled_price=fill_price,
            filled_quantity=qty, status=TradeStatus.FILLED.value, total=total,
        )
        db.add(trade)

    elif side == "sell":
        portfolio = db.query(Portfolio).filter(Portfolio.user_id == user.id, Portfolio.symbol == sym).first()
        if not portfolio or portfolio.quantity < qty:
            have = portfolio.quantity if portfolio else 0
            r = err_redirect("insufficient_holdings")
            if r: return r
            return JSONResponse({"error": f"Insufficient holdings. You have {have} {sym}, tried to sell {qty}"}, status_code=400)

        proceeds = round(fill_price * qty, 2)
        user.balance = round(user.balance + proceeds, 2)

        new_qty = portfolio.quantity - qty
        if new_qty <= 0:
            db.delete(portfolio)
        else:
            portfolio.quantity = new_qty

        trade = Trade(
            user_id=user.id, symbol=sym, side="sell", type=trade_type,
            quantity=qty, price=fill_price, filled_price=fill_price,
            filled_quantity=qty, status=TradeStatus.FILLED.value, total=proceeds,
        )
        db.add(trade)

    else:
        r = err_redirect("error")
        if r: return r
        return JSONResponse({"error": "Invalid side"}, status_code=400)

    notification = Notification(user_id=user.id, type="trade", title="Trade Executed", message="Trade executed")
    db.add(notification)
    db.commit()

    if do_redirect:
        ref = str(request.headers.get("referer", "/invest"))
        return RedirectResponse(url=ref + ("&" if "?" in ref else "?") + "trade=success", status_code=303)

    return JSONResponse({
        "success": True,
        "message": "Trade executed",
        "balance": user.balance,
        "trade_id": trade.id,
    })


@app.get("/api/algorithms")
async def get_algorithms(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    algos = db.query(Algorithm).filter(Algorithm.user_id == user.id).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "language": a.language,
            "status": a.status,
            "last_run": a.last_run.isoformat() if a.last_run else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in algos
    ]


@app.post("/api/algorithms")
async def create_algorithm(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    code: str = Form(""),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    algo = Algorithm(
        user_id=user.id,
        name=name,
        description=description,
        code=code,
        status=AlgoStatus.DRAFT.value,
        config={},
    )
    db.add(algo)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/algorithms/{algo_id}/deploy")
async def deploy_algorithm(
    algo_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    algo = db.query(Algorithm).filter(Algorithm.id == algo_id, Algorithm.user_id == user.id).first()
    if not algo:
        raise HTTPException(status_code=404, detail="Algorithm not found")

    algo.status = AlgoStatus.ACTIVE.value
    algo.last_run = datetime.now(timezone.utc)
    db.commit()

    notification = Notification(
        user_id=user.id,
        type="algo",
        title="Algorithm Deployed",
        message=f"Algorithm '{algo.name}' is now live",
    )
    db.add(notification)
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/algorithms/{algo_id}/pause")
async def pause_algorithm(
    algo_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    algo = db.query(Algorithm).filter(Algorithm.id == algo_id, Algorithm.user_id == user.id).first()
    if not algo:
        raise HTTPException(status_code=404, detail="Algorithm not found")

    algo.status = AlgoStatus.PAUSED.value
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/algorithms/{algo_id}/backtest")
async def backtest_algorithm(
    algo_id: int,
    request: Request,
    symbol: str = Form(...),
    initial_capital: float = Form(10000.0),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    algo = db.query(Algorithm).filter(Algorithm.id == algo_id, Algorithm.user_id == user.id).first()
    if not algo:
        raise HTTPException(status_code=404, detail="Algorithm not found")

    result = {
        "total_return": round(random.uniform(-15, 40), 2),
        "sharpe_ratio": round(random.uniform(0.5, 2.5), 2),
        "max_drawdown": round(random.uniform(-25, -5), 2),
        "total_trades": random.randint(10, 200),
        "win_rate": round(random.uniform(40, 75), 1),
    }

    backtest = Backtest(
        algo_id=algo.id,
        symbol=symbol,
        start_date=datetime.now(timezone.utc) - timedelta(days=365),
        end_date=datetime.now(timezone.utc),
        initial_capital=initial_capital,
        result=result,
        status="completed",
    )
    db.add(backtest)
    db.commit()

    return JSONResponse(result)


@app.post("/api/admin/users/{user_id}/action")
async def admin_user_action(
    user_id: int,
    request: Request,
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = admin_required(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if action == "verify":
        target.verified = True
        target.email_verified = True
        target.kyc_status = KYCStatus.VERIFIED.value
    elif action == "ban":
        target.verified = False
        target.email_verified = False
    elif action == "make_admin":
        target.role = UserRole.ADMIN.value
    elif action == "make_user":
        target.role = UserRole.USER.value

    db.commit()

    client_ip = request.client.host if request.client else "unknown"
    log_audit(admin.id, f"User {action}", f"User {target.email} -> {action}", client_ip, db)

    return RedirectResponse(url="/admin", status_code=303)


@app.get("/api/admin/users/{user_id}")
async def admin_user_detail(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = admin_required(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    user_trades = db.query(Trade).filter(Trade.user_id == user_id).order_by(Trade.created_at.desc()).limit(20).all()
    user_portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()
    user_algos = db.query(Algorithm).filter(Algorithm.user_id == user_id).all()

    filled_volume = db.query(func.coalesce(func.sum(Trade.total), 0)).filter(
        Trade.user_id == user_id, Trade.status == "filled"
    ).scalar()

    return {
        "id": target.id,
        "email": target.email,
        "username": target.username,
        "first_name": target.first_name,
        "last_name": target.last_name,
        "phone": target.phone,
        "country": target.country,
        "ssn": target.ssn,
        "role": target.role,
        "verified": target.verified,
        "email_verified": target.email_verified,
        "kyc_status": target.kyc_status,
        "date_of_birth": target.date_of_birth,
        "address": target.address,
        "city": target.city,
        "state": target.state,
        "zip_code": target.zip_code,
        "occupation": target.occupation,
        "id_type": target.id_type,
        "id_front_path": target.id_front_path,
        "id_back_path": target.id_back_path,
        "kyc_submitted_at": target.kyc_submitted_at.isoformat() if target.kyc_submitted_at else None,
        "kyc_rejection_reason": target.kyc_rejection_reason,
        "balance": target.balance,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "filled_volume": filled_volume,
        "trades_count": len(user_trades),
        "portfolio_count": len(user_portfolios),
        "algo_count": len(user_algos),
        "trades": [
            {"id": t.id, "symbol": t.symbol, "side": t.side, "quantity": t.quantity,
             "price": t.price, "filled_price": t.filled_price, "status": t.status,
             "total": t.total, "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in user_trades
        ],
        "portfolio": [
            {"symbol": p.symbol, "quantity": p.quantity, "avg_price": p.avg_price}
            for p in user_portfolios
        ],
        "algorithms": [
            {"id": a.id, "name": a.name, "language": a.language, "status": a.status,
             "created_at": a.created_at.isoformat() if a.created_at else None}
            for a in user_algos
        ],
    }


@app.get("/api/admin/logs")
async def admin_logs(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "details": log.details,
            "ip": log.ip_address,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@app.get("/api/market/prices")
async def market_prices():
    return generate_market_prices()


@app.get("/api/market/candles/{symbol}")
async def market_candles(symbol: str, range: str = Query("1m")):
    sym = symbol.upper()
    if sym not in MARKET_SYMBOLS:
        raise HTTPException(status_code=404, detail="Symbol not found")
    base = MARKET_SYMBOLS[sym]["base"]
    range_map = {"1d": 24, "1w": 7, "1m": 30, "3m": 12, "1y": 12}
    vol_map = {"1d": 0.008, "1w": 0.015, "1m": 0.025, "3m": 0.04, "1y": 0.06}
    count = range_map.get(range, 30)
    vol = vol_map.get(range, 0.025)
    return generate_candles(sym, base, count, vol)


@app.get("/api/market/top-movers")
async def market_top_movers():
    prices = generate_market_prices()
    sorted_prices = sorted(prices.items(), key=lambda x: x[1]["change_pct"], reverse=True)
    return {
        "gainers": [{"symbol": s, **p} for s, p in sorted_prices[:6]],
        "losers": [{"symbol": s, **p} for s, p in list(reversed(sorted_prices[-6:]))],
    }


@app.get("/api/notifications")
async def get_notifications(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    notifs = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(20).all()
    return [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "read": n.read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifs
    ]


@app.post("/api/notifications/read")
async def read_notifications(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read == False).update({"read": True})
    db.commit()
    return {"status": "ok"}


UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/api/user/deposit")
async def request_deposit(
    request: Request,
    method: str = Form(...),
    amount: float = Form(...),
    currency: str = Form(None),
    tx_hash: str = Form(None),
    card_type: str = Form(None),
    card_code: str = Form(None),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if user.role != UserRole.ADMIN.value and user.kyc_status != KYCStatus.VERIFIED.value:
        return JSONResponse({"error": "KYC verification required to deposit"}, status_code=403)

    if amount < 11:
        return JSONResponse({"error": "Minimum deposit is $11"}, status_code=400)

    if method == "crypto":
        if not currency or not tx_hash:
            return JSONResponse({"error": "Currency and transaction hash required"}, status_code=400)
        details = {"currency": currency, "tx_hash": tx_hash}
    elif method == "gift_card":
        if not card_type or not card_code:
            return JSONResponse({"error": "Card type and code required"}, status_code=400)
        details = {"card_type": card_type, "code": card_code}
    else:
        return JSONResponse({"error": "Invalid deposit method"}, status_code=400)

    receipt_path = None
    if receipt and receipt.filename:
        ext = receipt.filename.rsplit(".", 1)[-1] if "." in receipt.filename else "jpg"
        filename = f"deposit_{user.id}_{datetime.now(timezone.utc).timestamp()}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        content = await receipt.read()
        with open(filepath, "wb") as f:
            f.write(content)
        receipt_path = f"/static/uploads/{filename}"

    deposit = Deposit(
        user_id=user.id,
        amount=amount,
        method=method,
        method_details=details,
        receipt_path=receipt_path,
        status="pending",
    )
    db.add(deposit)
    db.commit()

    return JSONResponse({"id": deposit.id, "status": "pending", "message": "Deposit request submitted for review"})


@app.get("/api/user/deposits")
async def user_deposits(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    deposits = db.query(Deposit).filter(Deposit.user_id == user.id).order_by(Deposit.created_at.desc()).limit(20).all()
    return [
        {
            "id": d.id,
            "amount": d.amount,
            "method": d.method,
            "details": d.method_details,
            "status": d.status,
            "admin_note": d.admin_note,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "reviewed_at": d.reviewed_at.isoformat() if d.reviewed_at else None,
        }
        for d in deposits
    ]


@app.get("/withdraw", response_class=HTMLResponse)
async def withdraw_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    withdrawals = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).order_by(Withdrawal.created_at.desc()).all()
    has_direct_deposit = db.query(Deposit).filter(
        Deposit.user_id == user.id,
        Deposit.status == "approved",
        Deposit.direct_deposit == True,
        Deposit.amount >= 11,
    ).first() is not None
    return templates.TemplateResponse("withdraw.html", {
        "request": request,
        "user": user,
        "withdrawals": withdrawals,
        "withdrawals_data": {"has_direct_deposit": has_direct_deposit},
    })


@app.post("/api/user/withdraw")
async def request_withdrawal(
    request: Request,
    amount: float = Form(...),
    currency: str = Form(...),
    wallet_address: str = Form(...),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if user.kyc_status != KYCStatus.VERIFIED.value:
        return JSONResponse({"error": "KYC verification required to withdraw"}, status_code=403)
    has_direct = db.query(Deposit).filter(
        Deposit.user_id == user.id,
        Deposit.status == "approved",
        Deposit.direct_deposit == True,
        Deposit.amount >= 11,
    ).first() is not None
    if not has_direct:
        return JSONResponse({"error": "You must make a direct deposit of $11 or more before withdrawing"}, status_code=403)
    if amount <= 0:
        return JSONResponse({"error": "Invalid amount"}, status_code=400)
    if amount > (user.balance or 0):
        return JSONResponse({"error": "Insufficient balance"}, status_code=400)
    if not wallet_address:
        return JSONResponse({"error": "Wallet address is required"}, status_code=400)

    receipt_path = None
    if receipt and receipt.filename:
        ext = receipt.filename.rsplit(".", 1)[-1] if "." in receipt.filename else "jpg"
        filename = f"withdraw_{user.id}_{datetime.now(timezone.utc).timestamp()}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        content = await receipt.read()
        with open(filepath, "wb") as f:
            f.write(content)
        receipt_path = f"/static/uploads/{filename}"

    withdrawal = Withdrawal(
        user_id=user.id,
        amount=amount,
        currency=currency,
        wallet_address=wallet_address,
        network=currency,
        receipt_path=receipt_path,
        status="pending",
    )
    db.add(withdrawal)
    db.commit()

    notif = Notification(
        user_id=user.id, type="withdrawal",
        title="Withdrawal Request Submitted",
        message=f"Your withdrawal request for ${amount:,.2f} ({currency}) has been submitted for review.",
    )
    db.add(notif)
    db.commit()

    return JSONResponse({"id": withdrawal.id, "status": "pending", "message": "Withdrawal request submitted for review"})


@app.get("/api/user/withdrawals")
async def user_withdrawals(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    withdrawals = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).order_by(Withdrawal.created_at.desc()).limit(20).all()
    return [
        {
            "id": w.id,
            "amount": w.amount,
            "currency": w.currency,
            "wallet_address": w.wallet_address,
            "status": w.status,
            "admin_note": w.admin_note,
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "reviewed_at": w.reviewed_at.isoformat() if w.reviewed_at else None,
        }
        for w in withdrawals
    ]


@app.get("/api/admin/withdrawals/pending")
async def admin_pending_withdrawals(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    withdrawals = db.query(Withdrawal).filter(Withdrawal.status == "pending").order_by(Withdrawal.created_at.desc()).all()
    return [
        {
            "id": w.id,
            "user_id": w.user_id,
            "username": w.user.username if w.user else "—",
            "email": w.user.email if w.user else "—",
            "amount": w.amount,
            "currency": w.currency,
            "wallet_address": w.wallet_address,
            "receipt_path": w.receipt_path,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in withdrawals
    ]


@app.get("/api/admin/withdrawals")
async def admin_all_withdrawals(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    withdrawals = db.query(Withdrawal).order_by(Withdrawal.created_at.desc()).all()
    return [
        {
            "id": w.id,
            "user_id": w.user_id,
            "username": w.user.username if w.user else "—",
            "email": w.user.email if w.user else "—",
            "amount": w.amount,
            "currency": w.currency,
            "wallet_address": w.wallet_address,
            "status": w.status,
            "receipt_path": w.receipt_path,
            "admin_note": w.admin_note,
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "reviewed_at": w.reviewed_at.isoformat() if w.reviewed_at else None,
        }
        for w in withdrawals
    ]


@app.post("/api/admin/withdrawals/{withdrawal_id}/review")
async def admin_review_withdrawal(
    withdrawal_id: int,
    request: Request,
    action: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db),
):
    admin = admin_required(request, db)
    withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    if action == "approve":
        withdrawal.status = "approved"
        withdrawal.reviewed_at = datetime.now(timezone.utc)
        withdrawal.admin_id = admin.id
        withdrawal.admin_note = note
        user = withdrawal.user
        user.balance = max(0.0, (user.balance or 0.0) - withdrawal.amount)
        notif = Notification(
            user_id=user.id, type="withdrawal",
            title="Withdrawal Approved",
            message=f"Your withdrawal of ${withdrawal.amount:,.2f} ({withdrawal.currency}) has been approved and sent to your wallet.",
        )
        db.add(notif)
    elif action == "reject":
        withdrawal.status = "rejected"
        withdrawal.reviewed_at = datetime.now(timezone.utc)
        withdrawal.admin_id = admin.id
        withdrawal.admin_note = note or "Withdrawal request was rejected"
        notif = Notification(
            user_id=withdrawal.user_id, type="withdrawal",
            title="Withdrawal Rejected",
            message=f"Your withdrawal of ${withdrawal.amount:,.2f} was rejected. Reason: {withdrawal.admin_note}",
        )
        db.add(notif)
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")

    db.commit()
    log_audit(admin.id, f"withdrawal_{action}", f"Withdrawal #{withdrawal.id} - ${withdrawal.amount} {withdrawal.currency}", request.client.host if request.client else "unknown", db)
    return JSONResponse({"status": "ok", "message": f"Withdrawal {action}d successfully"})


@app.get("/api/admin/deposits/pending")
async def admin_pending_deposits(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    deposits = db.query(Deposit).filter(Deposit.status == "pending").order_by(Deposit.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "user_id": d.user_id,
            "username": d.user.username if d.user else "—",
            "email": d.user.email if d.user else "—",
            "amount": d.amount,
            "method": d.method,
            "details": d.method_details,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in deposits
    ]


@app.post("/api/admin/deposits/{deposit_id}/review")
async def admin_review_deposit(
    deposit_id: int,
    request: Request,
    action: str = Form(...),
    note: str = Form(None),
    db: Session = Depends(get_db),
):
    admin = admin_required(request, db)
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if action == "approve":
        deposit.status = "approved"
        deposit.reviewed_at = datetime.now(timezone.utc)
        deposit.admin_id = admin.id
        deposit.admin_note = note
        if deposit.amount >= 11:
            deposit.direct_deposit = True
        user = deposit.user
        user.balance = (user.balance or 0.0) + deposit.amount
        notif = Notification(
            user_id=user.id, type="deposit",
            title="Deposit Approved",
            message=f"Your ${deposit.amount:,.2f} deposit has been approved and added to your balance.",
        )
        db.add(notif)
    elif action == "reject":
        deposit.status = "rejected"
        deposit.reviewed_at = datetime.now(timezone.utc)
        deposit.admin_id = admin.id
        deposit.admin_note = note or "Deposit request was rejected"
        notif = Notification(
            user_id=deposit.user_id, type="deposit",
            title="Deposit Rejected",
            message=f"Your ${deposit.amount:,.2f} deposit was rejected. Reason: {deposit.admin_note}",
        )
        db.add(notif)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    db.commit()

    client_ip = request.client.host if request.client else "unknown"
    log_audit(admin.id, f"Deposit {action}", f"Deposit #{deposit_id} ${deposit.amount} -> {action}", client_ip, db)

    return JSONResponse({"status": "ok", "deposit_status": deposit.status})


KYC_DIR = os.path.join(BASE_DIR, "static", "kyc_docs")


@app.get("/api/user/kyc")
async def get_kyc_status(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    return {
        "status": user.kyc_status,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "phone": user.phone or "",
        "country": user.country or "",
        "date_of_birth": user.date_of_birth or "",
        "address": user.address or "",
        "city": user.city or "",
        "state": user.state or "",
        "zip_code": user.zip_code or "",
        "occupation": user.occupation or "",
        "id_type": user.id_type or "",
        "has_id_front": bool(user.id_front_path),
        "has_id_back": bool(user.id_back_path),
        "submitted_at": user.kyc_submitted_at.isoformat() if user.kyc_submitted_at else None,
        "rejection_reason": user.kyc_rejection_reason,
        "reviewed_at": user.kyc_reviewed_at.isoformat() if user.kyc_reviewed_at else None,
    }


@app.post("/api/user/kyc")
async def submit_kyc(
    request: Request,
    date_of_birth: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    zip_code: str = Form(...),
    occupation: str = Form(...),
    id_type: str = Form(...),
    id_front: UploadFile = File(...),
    id_back: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)

    user_dir = os.path.join(KYC_DIR, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    front_ext = os.path.splitext(id_front.filename or "front.jpg")[1] or ".jpg"
    back_ext = os.path.splitext(id_back.filename or "back.jpg")[1] or ".jpg"
    front_path = os.path.join(user_dir, f"front{front_ext}")
    back_path = os.path.join(user_dir, f"back{back_ext}")

    with open(front_path, "wb") as f:
        shutil.copyfileobj(id_front.file, f)
    with open(back_path, "wb") as f:
        shutil.copyfileobj(id_back.file, f)

    user.date_of_birth = date_of_birth
    user.address = address
    user.city = city
    user.state = state
    user.zip_code = zip_code
    user.occupation = occupation
    user.id_type = id_type
    user.id_front_path = f"/static/kyc_docs/{user.id}/front{front_ext}"
    user.id_back_path = f"/static/kyc_docs/{user.id}/back{back_ext}"
    user.kyc_status = KYCStatus.PENDING.value
    user.kyc_submitted_at = datetime.now(timezone.utc)
    user.kyc_rejection_reason = None
    db.commit()

    return JSONResponse({"status": "pending", "message": "KYC application submitted for review"})


@app.get("/api/admin/kyc/pending")
async def admin_kyc_pending(request: Request, db: Session = Depends(get_db)):
    admin_required(request, db)
    pending = db.query(User).filter(User.kyc_status == KYCStatus.PENDING.value).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "country": u.country,
            "submitted_at": u.kyc_submitted_at.isoformat() if u.kyc_submitted_at else None,
            "id_front_path": u.id_front_path,
            "id_back_path": u.id_back_path,
        }
        for u in pending
    ]


@app.post("/api/admin/kyc/{user_id}/review")
async def admin_kyc_review(
    user_id: int,
    request: Request,
    action: str = Form(...),
    reason: str = Form(None),
    db: Session = Depends(get_db),
):
    admin = admin_required(request, db)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if action == "approve":
        target.kyc_status = KYCStatus.VERIFIED.value
        target.verified = True
    elif action == "reject":
        target.kyc_status = KYCStatus.REJECTED.value
        target.kyc_rejection_reason = reason or "Documents did not meet requirements"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    target.kyc_reviewed_at = datetime.now(timezone.utc)
    db.commit()

    client_ip = request.client.host if request.client else "unknown"
    log_audit(admin.id, f"KYC {action}", f"User {target.email} KYC -> {action}", client_ip, db)

    notif = Notification(
        user_id=target.id, type="kyc",
        title="KYC Update" if action == "approve" else "KYC Rejected",
        message=f"Your KYC has been {action}d. You can now trade and deposit." if action == "approve" else f"Your KYC was rejected: {target.kyc_rejection_reason}",
    )
    db.add(notif)
    db.commit()

    return JSONResponse({"status": "ok", "kyc_status": target.kyc_status})


@app.get("/api/user/kyc/images")
async def get_kyc_images(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    return {
        "id_front": user.id_front_path,
        "id_back": user.id_back_path,
    }


@app.get("/api/chart/portfolio")
async def chart_portfolio(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.created_at.asc()).all()
    data = []
    running = 10000.0
    for t in trades:
        if t.status == "filled":
            if t.side == "buy":
                running -= (t.filled_price or t.price or 0) * t.quantity
            else:
                running += (t.filled_price or t.price or 0) * t.quantity
        data.append({"date": t.created_at.isoformat()[:10], "value": round(running + (user.balance or 0), 2)})
    if not data:
        base = user.balance or 10000.0
        data = [{"date": "Day 1", "value": base}, {"date": "Day 7", "value": base}]
    return data


@app.get("/api/chart/allocation")
async def chart_allocation(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user.id).all()
    return [
        {"symbol": p.symbol, "value": round(p.avg_price * p.quantity, 2)}
        for p in portfolios if p.quantity > 0
    ]


@app.get("/api/chart/sparkline/{symbol}")
async def chart_sparkline(symbol: str, request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    trades = db.query(Trade).filter(Trade.user_id == user.id, Trade.symbol == symbol.upper()).order_by(Trade.created_at.asc()).limit(20).all()
    data = []
    running = 0
    for t in trades:
        if t.status == "filled":
            running += (t.filled_price or t.price or 0) * t.quantity
        data.append(round(running, 2) if running else 0)
    if not data:
        data = [round(random.uniform(50, 500), 2) for _ in range(10)]
    return data


# ---------------------------------------------------------------------------
# TOTP helpers (built-in, no pyotp dependency)
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(10)).decode('utf-8')

def get_totp_token(secret: str, for_time: int | None = None) -> str:
    key = base64.b32decode(secret, casefold=True)
    counter = struct.pack('>Q', int((for_time if for_time is not None else datetime.now(timezone.utc).timestamp()) / 30))
    h = hmac.new(key, counter, 'sha1').digest()
    o = h[-1] & 0x0f
    truncated = struct.unpack('>I', h[o:o+4])[0] & 0x7fffffff
    return str(truncated % 1000000).zfill(6)

def verify_totp(secret: str, token: str) -> bool:
    now = int(datetime.now(timezone.utc).timestamp())
    for offset in [-1, 0, 1]:
        t = now + offset * 30
        if get_totp_token(secret, t) == token:
            return True
    return False

def totp_provisioning_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/Foundation%20Wealth:{email}?secret={secret}&issuer=Foundation%20Wealth&algorithm=SHA1&digits=6&period=30"

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = login_required(request, db)
    except HTTPException:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = login_required(request, db)
    except HTTPException:
        return RedirectResponse(url="/login")
    pairs = []
    if user.two_factor_enabled and user.two_factor_secret:
        pairs = db.query(AppPassword).filter(AppPassword.user_id == user.id).all()
    return templates.TemplateResponse("settings.html", {"request": request, "user": user, "app_passwords": pairs})

@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = login_required(request, db)
    except HTTPException:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("portfolio.html", {"request": request, "user": user, "symbol_logos": SYMBOL_LOGOS})

# ---------------------------------------------------------------------------
# API: Profile
# ---------------------------------------------------------------------------
@app.get("/api/user/profile")
async def get_profile(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    photo_url = None
    if user.profile_photo_path:
        photo_url = f"/static/profile_photos/{user.id}/{os.path.basename(user.profile_photo_path)}"
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "phone": ("" if user.phone == user.email else user.phone) or "",
        "country": user.country or "",
        "photo_url": photo_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "total_trades": db.query(Trade).filter(Trade.user_id == user.id, Trade.status == "filled").count(),
        "kyc_status": user.kyc_status,
    }

@app.put("/api/user/profile")
async def update_profile(
    request: Request,
    first_name: str = Form(None),
    last_name: str = Form(None),
    username: str = Form(None),
    phone: str = Form(None),
    country: str = Form(None),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if first_name is not None: user.first_name = first_name
    if last_name is not None: user.last_name = last_name
    if phone is not None: user.phone = phone
    if country is not None: user.country = country
    if username is not None:
        existing = db.query(User).filter(User.username == username, User.id != user.id).first()
        if existing:
            return JSONResponse({"error": "Username already taken"}, status_code=400)
        user.username = username
    db.commit()
    return {"success": True, "message": "Profile updated"}

@app.post("/api/user/profile/photo")
async def upload_profile_photo(
    request: Request,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if photo.content_type not in allowed:
        return JSONResponse({"error": "Only JPG, PNG, GIF, WebP allowed"}, status_code=400)
    data = await photo.read()
    if len(data) > 2 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 2MB)"}, status_code=400)
    upload_dir = os.path.join(BASE_DIR, "static", "profile_photos", str(user.id))
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(photo.filename or "photo.png")[1] or ".png"
    fname = f"photo{ext}"
    fpath = os.path.join(upload_dir, fname)
    with open(fpath, "wb") as f:
        f.write(data)
    user.profile_photo_path = fpath
    db.commit()
    return {"success": True, "photo_url": f"/static/profile_photos/{user.id}/{fname}"}

@app.post("/api/user/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if not verify_password(current_password, user.hashed_password):
        return JSONResponse({"error": "Current password is incorrect"}, status_code=400)
    if new_password != confirm_password:
        return JSONResponse({"error": "Passwords do not match"}, status_code=400)
    if len(new_password) < 6:
        return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)
    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"success": True, "message": "Password changed"}

# ---------------------------------------------------------------------------
# API: Settings
# ---------------------------------------------------------------------------
@app.get("/api/user/settings")
async def get_settings(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    prefs = {}
    if user.notification_prefs:
        try:
            prefs = json.loads(user.notification_prefs)
        except Exception:
            prefs = {}
    return {
        "two_factor_enabled": user.two_factor_enabled,
        "notifications": prefs,
    }

@app.put("/api/user/settings")
async def update_settings(
    request: Request,
    trade_confirmations: str = Form(None),
    price_alerts: str = Form(None),
    kyc_updates: str = Form(None),
    marketing: str = Form(None),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    prefs = {}
    if user.notification_prefs:
        try:
            prefs = json.loads(user.notification_prefs)
        except Exception:
            prefs = {}
    if trade_confirmations is not None: prefs["trade_confirmations"] = trade_confirmations == "1"
    if price_alerts is not None: prefs["price_alerts"] = price_alerts == "1"
    if kyc_updates is not None: prefs["kyc_updates"] = kyc_updates == "1"
    if marketing is not None: prefs["marketing"] = marketing == "1"
    user.notification_prefs = json.dumps(prefs)
    db.commit()
    return {"success": True, "message": "Settings saved"}

# ---------------------------------------------------------------------------
# API: 2FA
# ---------------------------------------------------------------------------
@app.post("/api/auth/2fa/setup")
async def setup_2fa(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    secret = generate_totp_secret()
    user.two_factor_secret = secret
    db.commit()
    uri = totp_provisioning_uri(secret, user.email)
    return {"secret": secret, "uri": uri}

@app.post("/api/auth/2fa/verify")
async def verify_2fa(
    request: Request,
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if not user.two_factor_secret:
        return JSONResponse({"error": "2FA not set up yet"}, status_code=400)
    if verify_totp(user.two_factor_secret, token):
        user.two_factor_enabled = True
        db.commit()
        return {"success": True, "message": "2FA enabled"}
    return JSONResponse({"error": "Invalid token"}, status_code=400)

@app.post("/api/auth/2fa/disable")
async def disable_2fa(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if not verify_password(password, user.hashed_password):
        return JSONResponse({"error": "Password is incorrect"}, status_code=400)
    user.two_factor_enabled = False
    user.two_factor_secret = None
    db.commit()
    return {"success": True, "message": "2FA disabled"}

# ---------------------------------------------------------------------------
# API: Watchlist
# ---------------------------------------------------------------------------
@app.get("/api/watchlist")
async def get_watchlist(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    wl = db.query(Watchlist).filter(Watchlist.user_id == user.id).first()
    symbols = []
    if wl and wl.symbols:
        symbols = [s.strip() for s in wl.symbols.split(",") if s.strip()]
    return {"symbols": symbols}

@app.post("/api/watchlist")
async def add_to_watchlist(
    request: Request,
    symbol: str = Form(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    sym = symbol.upper()
    wl = db.query(Watchlist).filter(Watchlist.user_id == user.id).first()
    if not wl:
        wl = Watchlist(user_id=user.id, symbols="")
        db.add(wl)
    existing = [s.strip() for s in wl.symbols.split(",") if s.strip()] if wl.symbols else []
    if sym in existing:
        return {"success": True, "message": "Already in watchlist"}
    existing.append(sym)
    wl.symbols = ",".join(existing)
    db.commit()
    return {"success": True, "symbols": existing}

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    sym = symbol.upper()
    wl = db.query(Watchlist).filter(Watchlist.user_id == user.id).first()
    if not wl or not wl.symbols:
        return {"symbols": []}
    existing = [s.strip() for s in wl.symbols.split(",") if s.strip()]
    existing = [s for s in existing if s != sym]
    wl.symbols = ",".join(existing)
    db.commit()
    return {"success": True, "symbols": existing}

# ---------------------------------------------------------------------------
# API: Portfolio stats
# ---------------------------------------------------------------------------
@app.get("/api/portfolio/stats")
async def portfolio_stats(request: Request, db: Session = Depends(get_db)):
    user = login_required(request, db)
    portfolio = db.query(Portfolio).filter(Portfolio.user_id == user.id).all()
    prices = generate_market_prices()
    total_value = user.balance
    total_cost = 0
    total_pnl = 0
    positions_count = len(portfolio)
    wins = 0
    losses = 0
    position_details = []
    for p in portfolio:
        cur_price = prices.get(p.symbol, {}).get("price", 0)
        val = cur_price * p.quantity
        cost = p.avg_price * p.quantity
        pnl = val - cost
        pnl_pct = ((pnl / cost) * 100) if cost > 0 else 0
        total_value += val
        total_cost += cost
        total_pnl += pnl
        position_details.append({
            "symbol": p.symbol,
            "quantity": p.quantity,
            "avg_price": p.avg_price,
            "current_price": cur_price,
            "value": round(val, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        if pnl > 0: wins += 1
        elif pnl < 0: losses += 1

    all_trades = db.query(Trade).filter(Trade.user_id == user.id, Trade.status == "filled").count()
    win_rate = round((wins / positions_count * 100) if positions_count > 0 else 0, 1)

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "positions_count": positions_count,
        "total_trades": all_trades,
        "win_rate": win_rate,
        "positions": position_details,
    }

# ---------------------------------------------------------------------------
# API: Delete account
# ---------------------------------------------------------------------------
@app.post("/api/user/delete")
async def delete_account(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = login_required(request, db)
    if not verify_password(password, user.hashed_password):
        return JSONResponse({"error": "Password is incorrect"}, status_code=400)
    user_id = user.id
    # Clean up uploaded files
    for d in ["kyc_docs", "profile_photos"]:
        p = os.path.join(BASE_DIR, "static", d, str(user_id))
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
    db.query(Notification).filter(Notification.user_id == user_id).delete()
    db.query(AppPassword).filter(AppPassword.user_id == user_id).delete()
    db.query(Algorithm).filter(Algorithm.user_id == user_id).delete()
    db.query(Trade).filter(Trade.user_id == user_id).delete()
    db.query(Portfolio).filter(Portfolio.user_id == user_id).delete()
    db.query(Watchlist).filter(Watchlist.user_id == user_id).delete()
    db.query(Deposit).filter(Deposit.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    resp = JSONResponse({"success": True, "message": "Account deleted"})
    resp.delete_cookie("token")
    return resp


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "foundation-wealth"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000)
