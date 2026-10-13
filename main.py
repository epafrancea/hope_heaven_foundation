from fastapi import FastAPI, HTTPException, Form, Request, Response, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import bcrypt
import sqlite3
import os
import random
import io
import csv
import shutil
from datetime import datetime
import pytz
import httpx

app = FastAPI(title="Hope Haven Foundation", version="15.9")

# Weka API Key yako ya Gemini hapa moja kwa moja
GEMINI_API_KEY = "AQ.Ab8RN6IngAjJrV9MG0qvu9vTiyk2iKQO0SleQXAWHEl3MrbqqA"

def hash_password(password: str) -> str:
    pwd_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password[:72].encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)

if not os.path.exists("static"):
    os.makedirs("static")
if not os.path.exists("static/events"):
    os.makedirs("static/events")

app.mount("/static", StaticFiles(directory="static"), name="static")

EAT_TIMEZONE = pytz.timezone("Africa/Dar_es_Salaam")

def get_current_time_eat():
    return datetime.now(EAT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    conn = sqlite3.connect("charity_app.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_name TEXT,
            amount REAL,
            payment_method TEXT,
            transaction_id TEXT UNIQUE,
            is_anonymous BOOLEAN,
            timestamp DATETIME
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS community_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            message TEXT,
            timestamp DATETIME
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            location TEXT,
            event_date TEXT,
            event_type TEXT,
            image_names TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_raised REAL,
            total_expenses REAL,
            net_balance REAL,
            summary TEXT,
            timestamp DATETIME
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_date TEXT,
            visitor_name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            contact TEXT,
            otp TEXT,
            role TEXT DEFAULT 'user',
            language TEXT DEFAULT 'sw'
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'sw'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    admin_user = cursor.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    if not admin_user:
        hashed_admin_pwd = hash_password("password123")
        cursor.execute("INSERT INTO users (username, password, contact, role, language) VALUES ('admin', ?, 'admin@hopehaven.org', 'admin', 'sw')", (hashed_admin_pwd,))
    
    conn.commit()
    conn.close()

init_db()

def require_admin(request: Request):
    role = request.cookies.get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have administrator permissions."
        )

class ChatPayload(BaseModel):
    user_name: str
    message: str

class DonationPayload(BaseModel):
    donor_name: str
    amount: float
    payment_method: str
    transaction_id: str
    is_anonymous: bool = False

class AzamPayStkPayload(BaseModel):
    donor_name: str
    amount: float
    phone_number: str
    provider: str
    is_anonymous: bool = False

class HopeAIPayload(BaseModel):
    message: str
    user_name: str

@app.post("/api/hope-ai")
async def chat_with_hope(data: HopeAIPayload):
    if not GEMINI_API_KEY or GEMINI_API_KEY == "Weka_Hapa_API_Key_Yako_Yote":
        return {"reply": "Habari! Tafadhali weka Gemini API Key halisi ndani ya main.py."}

    prompt = f"""
    Wewe ni Hope, AI Assistant rafiki wa taasisi ya 'Hope Haven Foundation' Dar es Salaam.
    Jibu kwa heshima, fupi (mistari 2-3), kwa lugha aliyotumia mtumiaji ({data.user_name}).
    Ujumbe: "{data.message}"
    """

    try:
        async with httpx.AsyncClient() as client:
            # Tunatumia header ya x-goog-api-key badala ya kuweka key kwenye URL (kuzuia makosa ya AQ keys)
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
                headers={"x-goog-api-key": GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=20.0
            )
            res_data = response.json()
            
            if "candidates" in res_data and len(res_data["candidates"]) > 0:
                reply_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                return {"reply": reply_text}
            else:
                error_msg = res_data.get("error", {}).get("message", "Hitilafu haijulikani kutoka Google AI.")
                return {"reply": f"Hitilafu ya AI: {error_msg}"}
                
    except Exception as e:
        return {"reply": f"Hitilafu ya mtandao: {str(e)}"}
@app.post("/api/chat")
def post_message(data: ChatPayload):
    conn = get_db()
    current_time = get_current_time_eat()
    conn.execute("INSERT INTO community_chats (user_name, message, timestamp) VALUES (?, ?, ?)", (data.user_name, data.message, current_time))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/webhook/donation")
def receive_donation(data: DonationPayload):
    conn = get_db()
    current_time = get_current_time_eat()
    try:
        conn.execute(
            """INSERT INTO donations (donor_name, amount, payment_method, transaction_id, is_anonymous, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.donor_name, data.amount, data.payment_method, data.transaction_id, data.is_anonymous, current_time)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Transaction ID already used!")
    finally:
        conn.close()
    return {"status": "success", "message": "Donation recorded successfully!"}

@app.post("/api/payment/azampay-stk")
def request_azampay_stk(data: AzamPayStkPayload):
    payload = {
        "accountNumber": "HopeHavenFoundation",
        "amount": str(data.amount),
        "currency": "TZS",
        "externalId": f"TXN_{int(datetime.now().timestamp())}",
        "provider": data.provider,
        "mobileNumber": data.phone_number,
        "additionalProperties": {}
    }
    
    try:
        conn = get_db()
        current_time = get_current_time_eat()
        txn_id = payload["externalId"]
        
        conn.execute(
            """INSERT INTO donations (donor_name, amount, payment_method, transaction_id, is_anonymous, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.donor_name, data.amount, f"AzamPay ({data.provider})", txn_id, data.is_anonymous, current_time)
        )
        conn.commit()
        conn.close()
        
        return {
            "status": "success", 
            "message": f"Ombi la TZS {data.amount} limetumwa kwenda namba {data.phone_number} kupitia AzamPay",
            "transaction_id": txn_id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Hitilafu ya malipo: {str(e)}")

@app.post("/api/admin/add-event")
async def add_event(
    request: Request, 
    title: str = Form(...), 
    description: str = Form(...), 
    location: str = Form(...), 
    event_date: str = Form(...), 
    event_type: str = Form(...), 
    images: list[UploadFile] = File([])
):
    require_admin(request)
    saved_filenames = []
    for img in images:
        if img.filename:
            unique_filename = f"{int(datetime.now().timestamp())}_{img.filename}"
            file_path = os.path.join("static/events", unique_filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(img.file, buffer)
            saved_filenames.append(unique_filename)
            
    image_names_str = ",".join(saved_filenames)
    conn = get_db()
    conn.execute("INSERT INTO events (title, description, location, event_date, event_type, image_names) VALUES (?, ?, ?, ?, ?, ?)", 
                 (title, description, location, event_date, event_type, image_names_str))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/?page=admin&success=event", status_code=303)

@app.post("/api/admin/add-finance")
def add_finance(request: Request, total_raised: float = Form(...), total_expenses: float = Form(...), summary: str = Form(...)):
    require_admin(request)
    net_balance = total_raised - total_expenses
    conn = get_db()
    current_time = get_current_time_eat()
    conn.execute("INSERT INTO financial_reports (total_raised, total_expenses, net_balance, summary, timestamp) VALUES (?, ?, ?, ?, ?)", 
                 (total_raised, total_expenses, net_balance, summary, current_time))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/admin/clear-data")
def clear_system_data(request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("DELETE FROM donations")
    conn.execute("DELETE FROM community_chats")
    conn.execute("DELETE FROM financial_reports")
    conn.execute("DELETE FROM visitors")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/?page=admin&success=cleared", status_code=303)

@app.get("/api/admin/export/donations")
def export_donations(request: Request):
    require_admin(request)
    conn = get_db()
    donations = conn.execute("SELECT id, donor_name, amount, payment_method, transaction_id, is_anonymous, timestamp FROM donations").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Donor Name", "Amount (TZS)", "Payment Method", "Transaction ID", "Is Anonymous", "Timestamp"])
    for d in donations:
        writer.writerow([d["id"], d["donor_name"], d["amount"], d["payment_method"], d["transaction_id"], d["is_anonymous"], d["timestamp"]])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=donations_report.csv"}
    )

@app.get("/api/admin/export/users")
def export_users(request: Request):
    require_admin(request)
    conn = get_db()
    users = conn.execute("SELECT id, username, contact, role, language FROM users").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Username", "Contact / Email", "Role", "Language"])
    for u in users:
        writer.writerow([u["id"], u["username"], u["contact"], u["role"], u["language"]])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=system_users.csv"}
    )

@app.post("/api/auth/register")
def register_user(username: str = Form(...), password: str = Form(...), contact: str = Form(...)):
    conn = get_db()
    hashed_pwd = hash_password(password)
    try:
        conn.execute("INSERT INTO users (username, password, contact, role, language) VALUES (?, ?, ?, 'user', 'sw')", (username, hashed_pwd, contact))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return RedirectResponse(url="/auth?mode=register&error=exists", status_code=303)
    conn.close()
    return RedirectResponse(url="/auth?mode=login&success=registered", status_code=303)

@app.post("/api/auth/login")
def login_user(username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user and verify_password(password, user["password"]):
        resp = RedirectResponse(url="/?page=home", status_code=303)
        resp.set_cookie(key="username", value=username, httponly=True, samesite="lax")
        resp.set_cookie(key="role", value=user["role"], httponly=True, samesite="lax")
        return resp
    else:
        return RedirectResponse(url="/auth?mode=login&error=invalid", status_code=303)

@app.get("/logout")
def logout_user():
    resp = RedirectResponse(url="/auth", status_code=303)
    resp.delete_cookie(key="username")
    resp.delete_cookie(key="role")
    return resp

@app.post("/api/auth/request-otp")
def request_otp(username: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return RedirectResponse(url="/auth?mode=forgot&error=notfound", status_code=303)
    
    otp_code = str(random.randint(1000, 9999))
    conn.execute("UPDATE users SET otp = ? WHERE username = ?", (otp_code, username))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/auth?mode=reset&username={username}&otp_display={otp_code}", status_code=303)

@app.post("/api/auth/reset-password")
def reset_password(username: str = Form(...), otp: str = Form(...), new_password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ? AND otp = ?", (username, otp)).fetchone()
    if not user:
        conn.close()
        return RedirectResponse(url=f"/auth?mode=reset&username={username}&error=invalidotp", status_code=303)
    
    hashed_pwd = hash_password(new_password)
    conn.execute("UPDATE users SET password = ?, otp = NULL WHERE username = ?", (hashed_pwd, username))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/auth?mode=login&success=reset", status_code=303)


@app.get("/auth", response_class=HTMLResponse)
def auth_page(mode: str = "login", error: str = None, success: str = None, username: str = "", otp_display: str = ""):
    logo_exists = os.path.exists("static/brand/logo.jpg")
    logo_html = f'<img src="/static/brand/logo.jpg" alt="Hope Haven Logo" style="width: 80px; height: 80px; display: block; margin: 0 auto 12px auto; border-radius: 50%; object-fit: cover; border: 2px solid #60a5fa; box-shadow: 0 4px 10px rgba(0,0,0,0.3);">' if logo_exists else '<h1 style="text-align:center; margin:0; color:#60a5fa;">💙</h1>'

    alert_msg = ""
    if error == "exists":
        alert_msg = "<p style='color: #f87171; text-align:center; font-weight:bold;'>Username already exists!</p>"
    elif error == "invalid":
        alert_msg = "<p style='color: #f87171; text-align:center; font-weight:bold;'>Invalid username or password!</p>"
    elif error == "notfound":
        alert_msg = "<p style='color: #f87171; text-align:center; font-weight:bold;'>Username not found!</p>"
    elif error == "invalidotp":
        alert_msg = "<p style='color: #f87171; text-align:center; font-weight:bold;'>Invalid OTP code!</p>"
    elif success == "registered":
        alert_msg = "<p style='color: #4ade80; text-align:center; font-weight:bold;'>Registration successful! Please log in.</p>"
    elif success == "reset":
        alert_msg = "<p style='color: #4ade80; text-align:center; font-weight:bold;'>Password reset successful! Please log in.</p>"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Hope Haven Foundation</title>
        <link rel="icon" type="image/jpeg" href="/static/brand/logo.jpg">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 15px;
                background-color: #0f172a;
                color: #f8fafc;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                box-sizing: border-box;
            }}
            .auth-card {{
                background: rgba(30, 41, 59, 0.96);
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 35px 40px;
                border-radius: 16px;
                width: 100%;
                max-width: 400px;
                box-shadow: 0 15px 35px rgba(0,0,0,0.7);
                box-sizing: border-box;
            }}
            h2 {{ color: #60a5fa; text-align: center; margin-bottom: 20px; font-size: 22px; font-weight: 700; }}
            .form-group {{ margin-bottom: 18px; }}
            .form-group label {{ display: block; margin-bottom: 6px; font-weight: bold; font-size: 13px; color: #cbd5e1; }}
            .form-group input {{
                width: 100%;
                padding: 12px;
                background: #0f172a;
                border: 1px solid #475569;
                color: white;
                border-radius: 8px;
                box-sizing: border-box;
                font-size: 14px;
            }}
            .btn {{
                background-color: #2563eb;
                color: white;
                border: none;
                width: 100%;
                padding: 12px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
                font-size: 15px;
                transition: background 0.3s;
            }}
            .btn:hover {{ background-color: #1d4ed8; }}
            .auth-links {{
                text-align: center;
                margin-top: 20px;
                font-size: 13px;
            }}
            .auth-links a {{
                color: #60a5fa;
                text-decoration: none;
                font-weight: 600;
            }}
            .auth-links a:hover {{ text-decoration: underline; }}
            .otp-box {{
                background: rgba(15, 23, 42, 0.8);
                border: 1px dashed #60a5fa;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="auth-card">
            {logo_html}
            <h2>Hope Haven Foundation</h2>
            {alert_msg}
    """

    if mode == "login":
        html += """
            <form action="/api/auth/login" method="POST">
                <div class="form-group">
                    <label>Username:</label>
                    <input type="text" name="username" required>
                </div>
                <div class="form-group">
                    <label>Password:</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit" class="btn">Log In</button>
            </form>
            <div class="auth-links">
                <p>Don't have an account? <a href="/auth?mode=register">Create Account</a></p>
                <p><a href="/auth?mode=forgot">Forgot Password?</a></p>
            </div>
        """
    elif mode == "register":
        html += """
            <form action="/api/auth/register" method="POST">
                <div class="form-group">
                    <label>Username:</label>
                    <input type="text" name="username" required>
                </div>
                <div class="form-group">
                    <label>Email or Phone Number:</label>
                    <input type="text" name="contact" placeholder="e.g. user@email.com or +255..." required>
                </div>
                <div class="form-group">
                    <label>Password:</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit" class="btn" style="background-color: #059669;">Register</button>
            </form>
            <div class="auth-links">
                <p>Already have an account? <a href="/auth?mode=login">Log In</a></p>
            </div>
        """
    elif mode == "forgot":
        html += """
            <form action="/api/auth/request-otp" method="POST">
                <div class="form-group">
                    <label>Enter your Username:</label>
                    <input type="text" name="username" required>
                </div>
                <button type="submit" class="btn">Send OTP</button>
            </form>
            <div class="auth-links">
                <p><a href="/auth?mode=login">Back to Log In</a></p>
            </div>
        """
    elif mode == "reset":
        html += f"""
            <div class="otp-box">
                <p style="margin:0; font-size:12px; color:#93c5fd;">SIMULATED OTP CODE:</p>
                <h3 style="margin:5px 0 0 0; color:#4ade80; font-size:24px;">{otp_display}</h3>
            </div>
            <form action="/api/auth/reset-password" method="POST">
                <input type="hidden" name="username" value="{username}">
                <div class="form-group">
                    <label>Enter 4-Digit OTP:</label>
                    <input type="text" name="otp" maxlength="4" required>
                </div>
                <div class="form-group">
                    <label>New Password:</label>
                    <input type="password" name="new_password" required>
                </div>
                <button type="submit" class="btn" style="background-color: #d97706;">Reset Password</button>
            </form>
            <div class="auth-links">
                <p><a href="/auth?mode=login">Back to Log In</a></p>
            </div>
        """

    html += """
        </div>
    </body>
    </html>
    """
    return html


@app.get("/", response_class=HTMLResponse)
def serve_frontend(request: Request, page: str = "home", lang: str = None, success: str = None):
    username = request.cookies.get("username")
    role = request.cookies.get("role") or "user"
    if not username:
        return RedirectResponse(url="/auth", status_code=303)

    conn = get_db()
    
    user_row = conn.execute("SELECT language FROM users WHERE username = ?", (username,)).fetchone()
    current_lang = user_row["language"] if user_row and user_row["language"] in ["sw", "en"] else "sw"

    if lang and lang in ["sw", "en"]:
        conn.execute("UPDATE users SET language = ? WHERE username = ?", (lang, username))
        conn.commit()
        current_lang = lang

    today_str = datetime.now(EAT_TIMEZONE).strftime("%Y-%m-%d")
    visited_today = conn.execute("SELECT * FROM visitors WHERE visit_date = ? AND visitor_name = ?", (today_str, username)).fetchone()
    
    if not visited_today:
        conn.execute("INSERT INTO visitors (visit_date, visitor_name) VALUES (?, ?)", (today_str, username))
        conn.commit()

    today_visitors_count = conn.execute("SELECT COUNT(DISTINCT visitor_name) as total FROM visitors WHERE visit_date = ?", (today_str,)).fetchone()["total"]

    donations = conn.execute("SELECT * FROM donations ORDER BY id DESC").fetchall()
    chats = conn.execute("SELECT * FROM community_chats ORDER BY id DESC").fetchall()
    next_events = conn.execute("SELECT * FROM events WHERE event_type = 'next' ORDER BY id DESC").fetchall()
    past_events = conn.execute("SELECT * FROM events WHERE event_type = 'past' ORDER BY id DESC").fetchall()
    finances = conn.execute("SELECT * FROM financial_reports ORDER BY id DESC").fetchall()
    all_users = conn.execute("SELECT id, username, contact, role, language FROM users ORDER BY id DESC").fetchall() if role == "admin" else []
    
    total_raised = sum([d["amount"] for d in donations]) if donations else 0
    conn.close()

    bg_dir = "static/backgrounds"
    if os.path.exists(bg_dir):
        bg_files = [f for f in os.listdir(bg_dir) if f.lower().endswith(('.jfif', '.jpg', '.jpeg', '.png'))]
    else:
        bg_files = []

    if bg_files:
        bg_images_list = [f"/static/backgrounds/{f}" for f in bg_files]
    else:
        bg_images_list = [
            "https://images.unsplash.com/photo-1488521787991-ed7bbaae773c?q=80&w=1600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1532629345422-7515f3d16bb9?q=80&w=1600&auto=format&fit=crop"
        ]

    selected_bg = bg_images_list[0]
    logo_exists = os.path.exists("static/brand/logo.jpg")

    t = {
        "sw": {
            "title": "Hope Haven Foundation",
            "tagline": "Hope Starts Here | Taasisi ya Kutoa Msaada",
            "home": "🏠 Ukurasa wa Kwanza",
            "dashboard": "📊 Dashboard & Michango",
            "events": "🚗 Matukio (Events)",
            "chat": "💬 Jamii na Chat",
            "finance": "💰 Ripoti za Fedha & Uwazi",
            "admin": "⚙️ Paneli ya Utawala",
            "settings": "🛠️ Mipangilio (Settings)",
            "logout": "🚪 Toka kwenye Akaunti (Logout)",
            "donors": "Wachangiaji",
            "visitors": "Wageni Leo",
            "save": "Hifadhi Mabadiliko",
            "home_history_title": "Historia Yetu (Our Background)",
            "home_history_desc": "Hope Haven Foundation ilianzishwa kwa lengo kuu la kusaidia jamii zenye mahitaji maalum, kutoa elimu, huduma za afya, na kuinua maisha ya makundi maalum ya kijamii hapa Tanzania na kanda ya Afrika.",
            "home_vision_title": "Dira Yetu (Vision)",
            "home_vision_desc": "Kuona jamii ambayo kila mtu anaishi kwa matumaini, usawa, na kupata fursa sawa za kimaendeleo.",
            "home_mission_title": "Dhumuni Letu (Mission)",
            "home_mission_desc": "Kufika vijijini na mijini kutoa rasilimali, misaada ya kibinadamu, na kuwajengea uwezo wananchi ili wajitegemee kiuchumi na kijamii.",
            "donate_title": "💳 Lipa Moja kwa Moja kupitia Simu (AzamPay STK Push)",
            "donor_name": "Jina la Mchangiaji:",
            "amount": "Kiasi cha Fedha (TZS):",
            "phone_number": "Namba ya Simu (mfano: 0712345678):",
            "payment_provider": "Mtandao wa Simu:",
            "payment_method": "Njia ya Malipo:",
            "anonymous": "Changia kwa Siri (Anonymous)",
            "submit_donation": "Tuma Ombi la Malipo Kwenye Simu",
            "donors_list": "Orodha ya Wachangiaji",
            "next_events": "🚗 Matukio Yajayo (Next Events)",
            "past_events": "📸 Matukio Yaliyopita (Past Events)",
            "chat_title": "💬 Maoni na Mazungumzo ya Jamii",
            "chat_name": "Jina Lako:",
            "chat_msg": "Ujumbe:",
            "send_msg": "Tuma Ujumbe",
            "finance_title": "💰 Ripoti za Fedha & Uwazi (Financial Transparency)",
            "finance_desc": "Hapa unaona takwimu za mapato, matumizi, na salio au nakisi kwa uwazi kabisa.",
            "admin_title": "⚙️ Paneli ya Utawala (Admin Only)",
            "add_event_title": "1. Ongeza Tukio Jipya & Picha Nyingi",
            "event_title_label": "Kichwa cha Tukio:",
            "location_label": "Eneo (Location):",
            "date_label": "Tarehe:",
            "event_type_label": "Aina ya Tukio:",
            "desc_label": "Maelezo:",
            "save_event": "Hifadhi Tukio",
            "add_finance_title": "2. Weka Ripoti ya Fedha",
            "total_raised_label": "Jumla ya Mapato (TZS):",
            "total_exp_label": "Jumla ya Matumizi (TZS):",
            "summary_label": "Muhtasari (Short Summary):",
            "save_finance": "Hifadhi Ripoti ya Fedha",
            "settings_title": "🛠️ Mipangilio ya Mfumo (Settings)",
            "select_lang": "Chagua Lugha (Language):"
        },
        "en": {
            "title": "Hope Haven Foundation",
            "tagline": "Hope Starts Here | Charity Platform",
            "home": "🏠 Home",
            "dashboard": "📊 Dashboard & Donations",
            "events": "🚗 Events",
            "chat": "💬 Community Chat",
            "finance": "💰 Financial Transparency",
            "admin": "⚙️ Admin Panel",
            "settings": "🛠️ Settings",
            "logout": "🚪 Log Out",
            "donors": "Total Donors",
            "visitors": "Visitors Today",
            "save": "Save Changes",
            "home_history_title": "Our Background",
            "home_history_desc": "Hope Haven Foundation was established with the core mission of supporting underprivileged communities, providing education, healthcare services, and uplifting vulnerable groups across Tanzania and the African region.",
            "home_vision_title": "Our Vision",
            "home_vision_desc": "To see a society where everyone lives with hope, equality, and access to equal developmental opportunities.",
            "home_mission_title": "Our Mission",
            "home_mission_desc": "Reaching rural and urban areas to provide resources, humanitarian aid, and empower citizens towards self-reliance socially and economically.",
            "donate_title": "💳 Mobile Money Direct Payment (AzamPay STK Push)",
            "donor_name": "Donor Name:",
            "amount": "Amount (TZS):",
            "phone_number": "Phone Number (e.g. 0712345678):",
            "payment_provider": "Mobile Provider:",
            "payment_method": "Payment Method:",
            "anonymous": "Donate Anonymously",
            "submit_donation": "Send Payment Request to Phone",
            "donors_list": "List of Donors",
            "next_events": "🚗 Upcoming Events",
            "past_events": "📸 Past Events",
            "chat_title": "💬 Community Discussion & Feedback",
            "chat_name": "Your Name:",
            "chat_msg": "Message:",
            "send_msg": "Send Message",
            "finance_title": "💰 Financial Transparency Reports",
            "finance_desc": "Here you can transparently view income, expenses, and net balance or deficit statistics.",
            "admin_title": "⚙️ Administration Panel (Admin Only)",
            "add_event_title": "1. Add New Event & Multiple Images",
            "event_title_label": "Event Title:",
            "location_label": "Location:",
            "date_label": "Date:",
            "event_type_label": "Event Type:",
            "desc_label": "Description:",
            "save_event": "Save Event",
            "add_finance_title": "2. Add Financial Report",
            "total_raised_label": "Total Raised (TZS):",
            "total_exp_label": "Total Expenses (TZS):",
            "summary_label": "Short Summary:",
            "save_finance": "Save Financial Report",
            "settings_title": "🛠️ System Settings",
            "select_lang": "Select Language:"
        }
    }[current_lang]

    sidebar_logo = f'<img src="/static/brand/logo.jpg" alt="Logo" style="width: 55px; height: 55px; border-radius: 50%; object-fit: cover; margin-bottom: 10px; border: 2px solid #60a5fa;">' if logo_exists else '💙'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="{current_lang}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{t['title']}</title>
        <link rel="icon" type="image/jpeg" href="/static/brand/logo.jpg">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #0f172a;
                color: #f8fafc;
                display: flex;
                height: 100vh;
                overflow: hidden;
            }}
            .bg-layer {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-size: cover;
                background-position: center;
                transition: opacity 1.5s ease-in-out;
                z-index: -999;
            }}
            #bg1 {{
                opacity: 1;
                background-image: linear-gradient(rgba(15, 23, 42, 0.65), rgba(15, 23, 42, 0.65)), url('{selected_bg}');
            }}
            #bg2 {{
                opacity: 0;
                background-image: linear-gradient(rgba(15, 23, 42, 0.65), rgba(15, 23, 42, 0.65)), url('{selected_bg}');
            }}
            .sidebar {{
                width: 280px;
                height: 100vh;
                background: rgba(15, 23, 42, 0.95);
                border-right: 1px solid rgba(255, 255, 255, 0.1);
                display: flex;
                flex-direction: column;
                padding: 20px;
                box-shadow: 4px 0 10px rgba(0,0,0,0.3);
                align-items: center;
                box-sizing: border-box;
                flex-shrink: 0;
                z-index: 100;
            }}
            .sidebar h2 {{
                color: #60a5fa;
                font-size: 18px;
                text-align: center;
                margin-bottom: 25px;
                margin-top: 5px;
            }}
            .sidebar a {{
                color: #cbd5e1;
                text-decoration: none;
                padding: 12px 15px;
                border-radius: 8px;
                margin-bottom: 6px;
                font-weight: 600;
                font-size: 14px;
                width: 100%;
                box-sizing: border-box;
                transition: background 0.3s, color 0.3s;
            }}
            .sidebar a:hover, .sidebar a.active {{
                background-color: #2563eb;
                color: white;
            }}
            .user-tag {{
                background: rgba(30, 41, 59, 0.8);
                padding: 10px;
                border-radius: 6px;
                text-align: center;
                margin-bottom: 20px;
                font-size: 13px;
                color: #93c5fd;
                border: 1px solid rgba(255,255,255,0.05);
                width: 100%;
                box-sizing: border-box;
            }}
            .main-content {{
                flex: 1;
                height: 100vh;
                padding: 40px;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                box-sizing: border-box;
            }}
            .content-body {{
                flex: 1;
            }}
            .card-container {{
                display: flex;
                gap: 20px;
                margin-bottom: 30px;
            }}
            .metric-card {{
                background: rgba(30, 41, 59, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 20px;
                border-radius: 10px;
                flex: 1;
                text-align: center;
                box-shadow: 0 4px 6px rgba(0,0,0,0.2);
            }}
            .metric-card h3 {{ margin: 0; color: #93c5fd; font-size: 14px; }}
            .metric-card p {{ font-size: 26px; font-weight: bold; margin: 10px 0 0 0; color: white; }}
            .content-box {{
                background: rgba(30, 41, 59, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.2);
                margin-bottom: 20px;
            }}
            h2 {{ color: #60a5fa; border-bottom: 2px solid rgba(255,255,255,0.1); padding-bottom: 8px; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}
            th, td {{
                border: 1px solid rgba(255,255,255,0.1);
                padding: 12px;
                text-align: left;
            }}
            th {{ background-color: #1e3a8a; color: white; }}
            tr:nth-child(even) {{ background: rgba(255,255,255,0.02); }}
            .form-group {{ margin-bottom: 15px; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            .form-group select, .form-group input, .form-group textarea {{
                width: 100%;
                padding: 10px;
                background: #0f172a;
                border: 1px solid #475569;
                color: white;
                border-radius: 6px;
            }}
            .btn {{
                background-color: #2563eb;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: bold;
                text-decoration: none;
                display: inline-block;
            }}
            .btn:hover {{ background-color: #1d4ed8; }}
            
            .slider-container {{
                position: relative;
                max-width: 100%;
                height: 520px;
                margin: 15px 0;
                overflow: hidden;
                border-radius: 12px;
                background: rgba(15, 23, 42, 0.6);
                box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5);
            }}
            .slide {{
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                opacity: 0;
                transition: opacity 0.6s ease-in-out;
                display: flex;
                justify-content: center;
                align-items: center;
            }}
            .slide.active {{
                opacity: 1;
            }}
            .slide img {{
                max-width: 100%;
                max-height: 100%;
                width: auto;
                height: auto;
                object-fit: contain;
                border-radius: 8px;
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.6);
            }}
            .slider-btn {{
                position: absolute;
                top: 50%;
                transform: translateY(-50%);
                background: rgba(0, 0, 0, 0.6);
                color: white;
                border: none;
                padding: 12px 16px;
                cursor: pointer;
                font-size: 18px;
                border-radius: 50%;
                z-index: 10;
                transition: background 0.3s;
            }}
            .slider-btn:hover {{
                background: rgba(37, 99, 235, 0.9);
            }}
            .prev-btn {{ left: 15px; }}
            .next-btn {{ right: 15px; }}

            /* FOOTER STYLES */
            footer {{
                background: rgba(15, 23, 42, 0.95);
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                text-align: center;
                padding: 20px;
                margin-top: 40px;
                border-radius: 10px;
                color: #94a3b8;
                font-size: 14px;
                flex-shrink: 0;
            }}
            footer p {{ margin: 5px 0; }}
            .social-links {{
                margin-top: 10px;
            }}
            .social-links a {{
                color: #60a5fa;
                text-decoration: none;
                margin: 0 10px;
                font-weight: 600;
            }}
            .social-links a:hover {{
                text-decoration: underline;
            }}

            /* HOPE AI FLOATING WIDGET STYLES */
            .ai-widget-btn {{
                position: fixed;
                bottom: 25px;
                right: 25px;
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, #2563eb, #3b82f6);
                color: white;
                border: 2px solid #60a5fa;
                box-shadow: 0 8px 20px rgba(0,0,0,0.5);
                font-size: 28px;
                cursor: pointer;
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: transform 0.3s;
            }}
            .ai-widget-btn:hover {{
                transform: scale(1.1);
            }}

            .ai-chat-box {{
                position: fixed;
                bottom: 95px;
                right: 25px;
                width: 350px;
                max-width: 90vw;
                height: 450px;
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 16px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.7);
                display: none;
                flex-direction: column;
                z-index: 9999;
                overflow: hidden;
            }}

            .ai-chat-header {{
                background: #0f172a;
                padding: 14px;
                border-bottom: 1px solid #334155;
                display: flex;
                justify-content: space-between;
                align-items: center;
                color: #60a5fa;
                font-weight: bold;
            }}

            .ai-chat-messages {{
                flex: 1;
                padding: 15px;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 10px;
                font-size: 13px;
            }}

            .msg-ai {{
                background: #334155;
                color: white;
                padding: 10px 12px;
                border-radius: 12px 12px 12px 0;
                max-width: 80%;
                align-self: flex-start;
            }}

            .msg-user {{
                background: #2563eb;
                color: white;
                padding: 10px 12px;
                border-radius: 12px 12px 0 12px;
                max-width: 80%;
                align-self: flex-end;
            }}

            .ai-chat-input {{
                padding: 10px;
                background: #0f172a;
                border-top: 1px solid #334155;
                display: flex;
                gap: 8px;
            }}

            .ai-chat-input input {{
                flex: 1;
                padding: 8px 12px;
                border-radius: 6px;
                border: 1px solid #475569;
                background: #1e293b;
                color: white;
                font-size: 13px;
            }}

            .mobile-nav-bar {{
                display: none;
            }}

            @media (max-width: 768px) {{
                body {{
                    flex-direction: column !important;
                    height: auto !important;
                    overflow-y: auto !important;
                }}

                .mobile-nav-bar {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    background: rgba(15, 23, 42, 0.95);
                    padding: 12px 20px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                    width: 100%;
                    box-sizing: border-box;
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                }}

                .menu-toggle-btn {{
                    background: #2563eb;
                    color: white;
                    border: none;
                    padding: 8px 14px;
                    border-radius: 6px;
                    font-weight: bold;
                    cursor: pointer;
                    font-size: 14px;
                }}

                .sidebar {{
                    display: none;
                    width: 100% !important;
                    height: auto !important;
                    position: absolute;
                    top: 55px;
                    left: 0;
                    z-index: 999;
                    background: rgba(15, 23, 42, 0.98) !important;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.7);
                    border-right: none;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                }}

                .sidebar.show {{
                    display: flex !important;
                }}

                .main-content {{
                    height: auto !important;
                    padding: 15px !important;
                    overflow-y: visible !important;
                }}

                .card-container {{
                    flex-direction: column !important;
                }}

                .slider-container {{
                    height: 250px !important;
                }}

                table {{
                    display: block !important;
                    overflow-x: auto !important;
                    white-space: nowrap !important;
                }}
            }}
        </style>
    </head>
    <body>

        <div id="bg1" class="bg-layer"></div>
        <div id="bg2" class="bg-layer"></div>

        <div class="mobile-nav-bar">
            <span style="color: #60a5fa; font-weight: bold; font-size: 16px;">💙 Hope Haven</span>
            <button onclick="toggleMenu()" class="menu-toggle-btn">☰ Menu</button>
        </div>

        <div class="sidebar" id="appSidebar">
            {sidebar_logo}
            <h2>Hope Haven Foundation</h2>
            <div class="user-tag">👤 <b>{username}</b> ({role})</div>
            <a href="/?page=home" class="{'active' if page == 'home' else ''}">{t['home']}</a>
            <a href="/?page=dashboard" class="{'active' if page == 'dashboard' else ''}">{t['dashboard']}</a>
            <a href="/?page=events" class="{'active' if page == 'events' else ''}">{t['events']}</a>
            <a href="/?page=chat" class="{'active' if page == 'chat' else ''}">{t['chat']}</a>
            <a href="/?page=finance" class="{'active' if page == 'finance' else ''}">{t['finance']}</a>
            {f'<a href="/?page=admin" class="{"active" if page == "admin" else ""}">{"⚙️ Paneli ya Utawala" if current_lang=="sw" else "⚙️ Admin Panel"}</a>' if role == 'admin' else ''}
            <a href="/?page=settings" class="{'active' if page == 'settings' else ''}">{t['settings']}</a>
            <a href="/logout" style="color: #f87171; margin-top: 20px;">{t['logout']}</a>
        </div>

        <div class="main-content">
            <div class="content-body">
    """

    if page == "home":
        html_content += f"""
            <div class="content-box">
                <h1>{t['title']}</h1>
                <p style="color: #94a3b8; font-size: 18px; margin-bottom: 20px;">{t['tagline']}</p>
                <hr style="border-color: rgba(255,255,255,0.1); margin: 20px 0;">
                <h3>{t['home_history_title']}</h3>
                <p>{t['home_history_desc']}</p>
                <h3>{t['home_vision_title']}</h3>
                <p>{t['home_vision_desc']}</p>
                <h3>{t['home_mission_title']}</h3>
                <p>{t['home_mission_desc']}</p>
            </div>
        """

    elif page == "dashboard":
        html_content += f"""
            <div class="card-container">
                <div class="metric-card">
                    <h3>Jumla ya Michango</h3>
                    <p>TZS {total_raised:,.2f}</p>
                </div>
                <div class="metric-card">
                    <h3>{t['donors']}</h3>
                    <p>{len(donations)}</p>
                </div>
                <div class="metric-card">
                    <h3>{t['visitors']}</h3>
                    <p>{today_visitors_count}</p>
                </div>
            </div>

            <div class="content-box">
                <h2>{t['donate_title']}</h2>
                <form onsubmit="submitAzamPayStk(event)">
                    <div class="form-group">
                        <label>{t['donor_name']}</label>
                        <input type="text" id="donor_name" value="{username}" required>
                    </div>
                    <div class="form-group">
                        <label>{t['amount']}</label>
                        <input type="number" id="amount" step="100" required>
                    </div>
                    <div class="form-group">
                        <label>{t['phone_number']}</label>
                        <input type="text" id="phone_number" placeholder="07xxxxxxxx" required>
                    </div>
                    <div class="form-group">
                        <label>{t['payment_provider']}</label>
                        <select id="payment_provider">
                            <option value="Mpesa">Vodacom M-Pesa</option>
                            <option value="Tigo">Tigo Pesa</option>
                            <option value="Airtel">Airtel Money</option>
                            <option value="Halopesa">Halopesa</option>
                            <option value="Azampesa">Azampesa</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label><input type="checkbox" id="is_anonymous"> {t['anonymous']}</label>
                    </div>
                    <button type="submit" class="btn" style="background-color: #059669;">{t['submit_donation']}</button>
                </form>
            </div>

            <div class="content-box">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                    <h2>{t['donors_list']}</h2>
                    <a href="/api/admin/export/donations" class="btn" style="background-color: #059669; font-size: 13px; padding: 8px 14px;">📥 Download Excel (CSV)</a>
                </div>
                <table>
                    <tr>
                        <th>{t['donor_name']}</th>
                        <th>{t['amount']}</th>
                        <th>{t['payment_method']}</th>
                        <th>Timestamp (EAT)</th>
                    </tr>
        """
        if donations:
            for d in donations:
                name = "Anonymous" if d["is_anonymous"] else d["donor_name"]
                html_content += f"<tr><td>{name}</td><td>{d['amount']:,.2f}</td><td>{d['payment_method']}</td><td>{d['timestamp']}</td></tr>"
        else:
            html_content += "<tr><td colspan='4'>No donations recorded yet.</td></tr>"
        html_content += f"""
                </table>
            </div>
            <script>
            async function submitAzamPayStk(e) {{
                e.preventDefault();
                let data = {{
                    donor_name: document.getElementById('donor_name').value,
                    amount: parseFloat(document.getElementById('amount').value),
                    phone_number: document.getElementById('phone_number').value,
                    provider: document.getElementById('payment_provider').value,
                    is_anonymous: document.getElementById('is_anonymous').checked
                }};
                
                alert('Inatuma ombi la malipo kupitia AzamPay Sandbox...');
                
                let res = await fetch('/api/payment/azampay-stk', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(data)
                }});
                
                if(res.ok) {{
                    let result = await res.json();
                    alert('Imefaulu! ' + result.message);
                    window.location.reload();
                }} else {{
                    let err = await res.json();
                    alert('Imeshindwa: ' + (err.detail || 'Hitilafu imetokea'));
                }}
            }}
            </script>
        """

    elif page == "events":
        html_content += f"""
            <div class="content-box">
                <h2>{t['next_events']}</h2>
        """
        if next_events:
            for idx, ev in enumerate(next_events):
                img_list = ev['image_names'].split(',') if ev['image_names'] else []
                slider_html = ""
                if img_list and img_list[0] != "":
                    slider_slides = ""
                    for s_idx, img_file in enumerate(img_list):
                        active_cls = "active" if s_idx == 0 else ""
                        slider_slides += f'<div class="slide {active_cls}"><img src="/static/events/{img_file}" alt="Event Image"></div>'
                    
                    slider_html = f"""
                    <div class="slider-container" id="slider-next-{idx}">
                        {slider_slides}
                        <button class="slider-btn prev-btn" onclick="moveSlide('slider-next-{idx}', -1)">&#10094;</button>
                        <button class="slider-btn next-btn" onclick="moveSlide('slider-next-{idx}', 1)">&#10095;</button>
                    </div>
                    """
                
                html_content += f"""
                <div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:8px; margin-bottom:15px;'>
                    <h3>{ev['title']}</h3>
                    <p><b>Location:</b> {ev['location']} | <b>Date:</b> {ev['event_date']}</p>
                    {slider_html}
                    <p>{ev['description']}</p>
                </div>
                """
        else:
            html_content += "<p>No upcoming events at the moment.</p>"

        html_content += f"""
                <h2 style="margin-top: 30px;">{t['past_events']}</h2>
        """
        if past_events:
            for idx, ev in enumerate(past_events):
                img_list = ev['image_names'].split(',') if ev['image_names'] else []
                slider_html = ""
                if img_list and img_list[0] != "":
                    slider_slides = ""
                    for s_idx, img_file in enumerate(img_list):
                        active_cls = "active" if s_idx == 0 else ""
                        slider_slides += f'<div class="slide {active_cls}"><img src="/static/events/{img_file}" alt="Event Image"></div>'
                    
                    slider_html = f"""
                    <div class="slider-container" id="slider-past-{idx}">
                        {slider_slides}
                        <button class="slider-btn prev-btn" onclick="moveSlide('slider-past-{idx}', -1)">&#10094;</button>
                        <button class="slider-btn next-btn" onclick="moveSlide('slider-past-{idx}', 1)">&#10095;</button>
                    </div>
                    """

                html_content += f"""
                <div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:8px; margin-bottom:15px;'>
                    <h3>{ev['title']}</h3>
                    <p><b>Date:</b> {ev['event_date']}</p>
                    {slider_html}
                    <p>{ev['description']}</p>
                </div>
                """
        else:
            html_content += "<p>No past events recorded yet.</p>"
        html_content += "</div>"

        html_content += """
        <script>
        function moveSlide(sliderId, direction) {
            const container = document.getElementById(sliderId);
            const slides = container.querySelectorAll('.slide');
            let currentIndex = Array.from(slides).findIndex(slide => slide.classList.contains('active'));
            
            slides[currentIndex].classList.remove('active');
            currentIndex = (currentIndex + direction + slides.length) % slides.length;
            slides[currentIndex].classList.add('active');
        }
        </script>
        """

    elif page == "chat":
        html_content += f"""
            <div class="content-box">
                <h2>{t['chat_title']}</h2>
                <form onsubmit="postChat(event)">
                    <div class="form-group">
                        <label>{t['chat_name']}</label>
                        <input type="text" id="chat_name" value="{username}" required readonly>
                    </div>
                    <div class="form-group">
                        <label>{t['chat_msg']}</label>
                        <textarea id="chat_msg" rows="3" required></textarea>
                    </div>
                    <button type="submit" class="btn">{t['send_msg']}</button>
                </form>
                <hr style="border-color: rgba(255,255,255,0.1); margin: 20px 0;">
        """
        for c in chats:
            html_content += f"<p><b>{c['user_name']}</b> <i>({c['timestamp']})</i><br>{c['message']}</p><hr style='border-color: rgba(255,255,255,0.05);'>"
        html_content += "</div>"
        html_content += """
        <script>
        async function postChat(e) {
            e.preventDefault();
            let name = document.getElementById('chat_name').value;
            let msg = document.getElementById('chat_msg').value;
            await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user_name: name, message: msg})
            });
            window.location.reload();
        }
        </script>
        """

    elif page == "finance":
        html_content += f"""
            <div class="content-box">
                <h2>{t['finance_title']}</h2>
                <p style="color: #94a3b8;">{t['finance_desc']}</p>
                <table>
                    <tr>
                        <th>Timestamp</th>
                        <th>Total Raised (TZS)</th>
                        <th>Total Expenses (TZS)</th>
                        <th>Net Balance (TZS)</th>
                        <th>Summary</th>
                    </tr>
        """
        if finances:
            for f in finances:
                status_color = "#4ade80" if f['net_balance'] >= 0 else "#f87171"
                html_content += f"<tr><td>{f['timestamp']}</td><td>{f['total_raised']:,.2f}</td><td>{f['total_expenses']:,.2f}</td><td style='color: {status_color}; font-weight:bold;'>{f['net_balance']:,.2f}</td><td>{f['summary']}</td></tr>"
        else:
            html_content += "<tr><td colspan='5'>No financial reports published yet.</td></tr>"
        html_content += "</table></div>"

    elif page == "admin" and role == "admin":
        success_banner = '<div style="background: rgba(74, 222, 128, 0.2); border: 1px solid #4ade80; color: #4ade80; padding: 10px; border-radius: 6px; margin-bottom: 15px; font-weight: bold;">Tukio limehifadhiwa na picha zimepakiwa kwa mafanikio!</div>' if success == "event" else ''
        cleared_banner = '<div style="background: rgba(74, 222, 128, 0.2); border: 1px solid #4ade80; color: #4ade80; padding: 10px; border-radius: 6px; margin-bottom: 15px; font-weight: bold;">Data zote za mfumo zimefutwa kikamilifu!</div>' if success == "cleared" else ''
        
        html_content += f"""
            <div class="content-box">
                <h2>{t['admin_title']}</h2>
                {success_banner}
                {cleared_banner}
                
                <h3>3. Orodha ya Watumiaji wa Mfumo (System Users)</h3>
                <div style="margin-bottom: 15px;">
                    <a href="/api/admin/export/users" class="btn" style="background-color: #059669; font-size: 13px; padding: 8px 14px;">📥 Download Users (Excel / CSV)</a>
                </div>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Contact / Email</th>
                        <th>Role</th>
                        <th>Language</th>
                    </tr>
        """
        if all_users:
            for u in all_users:
                html_content += f"<tr><td>{u['id']}</td><td>{u['username']}</td><td>{u['contact']}</td><td>{u['role']}</td><td>{u['language']}</td></tr>"
        else:
            html_content += "<tr><td colspan='5'>No users found.</td></tr>"
        
        html_content += f"""
                </table>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 30px 0;">

                <h3>{t['add_event_title']}</h3>
                <form action="/api/admin/add-event" method="POST" enctype="multipart/form-data">
                    <div class="form-group"><label>{t['event_title_label']}</label><input type="text" name="title" required></div>
                    <div class="form-group"><label>{t['location_label']}</label><input type="text" name="location" required></div>
                    <div class="form-group"><label>{t['date_label']}</label><input type="text" name="event_date" required></div>
                    <div class="form-group">
                        <label>{t['event_type_label']}</label>
                        <select name="event_type">
                            <option value="next">Upcoming Event</option>
                            <option value="past">Past Event</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Pakia Picha Nyingi (Multiple Images):</label>
                        <input type="file" name="images" multiple accept="image/*" style="padding: 6px;">
                        <small style="color: #93c5fd; display: block; margin-top: 4px;">Unaweza kuchagua picha zaidi ya moja kwa wakati mmoja.</small>
                    </div>
                    <div class="form-group"><label>{t['desc_label']}</label><textarea name="description" rows="3" required></textarea></div>
                    <button type="submit" class="btn">{t['save_event']}</button>
                </form>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 30px 0;">

                <h3>{t['add_finance_title']}</h3>
                <form action="/api/admin/add-finance" method="POST" onsubmit="alert('Financial report saved successfully!');">
                    <div class="form-group"><label>{t['total_raised_label']}</label><input type="number" step="0.01" name="total_raised" required></div>
                    <div class="form-group"><label>{t['total_exp_label']}</label><input type="number" step="0.01" name="total_expenses" required></div>
                    <div class="form-group"><label>{t['summary_label']}</label><textarea name="summary" rows="2" required></textarea></div>
                    <button type="submit" class="btn">{t['save_finance']}</button>
                </form>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 30px 0;">

                <h3 style="color: #f87171;">4. Eneo Hatari: Safisha Data Zote (Reset Dashboard)</h3>
                <p style="color: #94a3b8; font-size: 13px;">Kitendo hiki kitafuta michango yote, mazungumzo ya jamii, na ripoti za fedha ili dashboard ianze upya kuanzia sifuri.</p>
                <form action="/api/admin/clear-data" method="POST" onsubmit="return confirm('Je, una uhakika unataka kufuta data zote za mfumo?');">
                    <button type="submit" class="btn" style="background-color: #dc2626;">🗑️ Futa Data Zote (Clear System Data)</button>
                </form>
            </div>
        """

    elif page == "settings":
        html_content += f"""
            <div class="content-box">
                <h2>{t['settings_title']}</h2>
                <form action="/" method="GET">
                    <input type="hidden" name="page" value="settings">
                    <div class="form-group">
                        <label>{t['select_lang']}</label>
                        <select name="lang">
                            <option value="sw" {'selected' if current_lang == 'sw' else ''}>Kiswahili</option>
                            <option value="en" {'selected' if current_lang == 'en' else ''}>English</option>
                        </select>
                    </div>
                    <button type="submit" class="btn">{t['save']}</button>
                </form>
            </div>
        """

    html_content += f"""
            </div>
            <footer>
                <p><b>📍 Headquarters:</b> Dar es Salaam, Tanzania | 📞 <b>Leadership Line:</b> +255 710 6817</p>
                <div class="social-links">
                    <a href="https://chat.whatsapp.com/KMoUHndYyie9tVoiwYpFL6" target="_blank">🌐 WhatsApp Group</a> | 
                    <a href="https://facebook.com/hopehavenfoundation" target="_blank">📘 Facebook</a> | 
                    <a href="https://instagram.com/hope.haven.foundation" target="_blank">📷 hope.haven.foundation</a> | 
                    <a href="https://x.com/hopehaven" target="_blank">🐦 Twitter / X</a> | 
                    <a href="mailto:info@hopehaven.org">✉️ Email</a>
                </div>
                <p style="margin-top: 10px; font-size: 12px;">© {datetime.now(EAT_TIMEZONE).year} Hope Haven Foundation. All rights reserved.</p>
            </footer>
        </div>

        <!-- HOPE AI FLOATING WIDGET -->
        <button class="ai-widget-btn" onclick="toggleAIChat()" title="Ongea na Hope AI">🤖</button>

        <div class="ai-chat-box" id="aiChatBox">
            <div class="ai-chat-header">
                <span>🤖 Hope AI Assistant</span>
                <span style="cursor: pointer;" onclick="toggleAIChat()">✖</span>
            </div>
            <div class="ai-chat-messages" id="aiMessages">
                <div class="msg-ai">Habari <b>{username}</b>! Mimi ni <b>Hope AI</b>, msaidizi wako. Una swali lolote kuhusu Hope Haven Foundation au huduma zetu?</div>
            </div>
            <div class="ai-chat-input">
                <input type="text" id="aiInput" placeholder="Andika ujumbe wako..." onkeypress="handleAIPress(event)">
                <button class="btn" style="padding: 6px 12px; font-size: 12px;" onclick="sendAIMessage()">Tuma</button>
            </div>
        </div>
        
        <script>
        function toggleMenu() {{
            const sidebar = document.getElementById('appSidebar');
            sidebar.classList.toggle('show');
        }}

        function toggleAIChat() {{
            const box = document.getElementById('aiChatBox');
            box.style.display = (box.style.display === 'flex') ? 'none' : 'flex';
        }}

        function handleAIPress(e) {{
            if (e.key === 'Enter') {{
                sendAIMessage();
            }}
        }}

        async function sendAIMessage() {{
            const input = document.getElementById('aiInput');
            const msg = input.value.trim();
            if (!msg) return;

            const msgsBox = document.getElementById('aiMessages');

            const userDiv = document.createElement('div');
            userDiv.className = 'msg-user';
            userDiv.innerText = msg;
            msgsBox.appendChild(userDiv);
            input.value = '';
            msgsBox.scrollTop = msgsBox.scrollHeight;

            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'msg-ai';
            loadingDiv.innerText = "Hope anafikiri...";
            msgsBox.appendChild(loadingDiv);
            msgsBox.scrollTop = msgsBox.scrollHeight;

            try {{
                const res = await fetch('/api/hope-ai', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ message: msg, user_name: '{username}' }})
                }});
                const data = await res.json();
                loadingDiv.innerText = data.reply;
            }} catch(err) {{
                loadingDiv.innerText = "Samahani, imefeli kuwasiliana na Hope AI.";
            }}
            msgsBox.scrollTop = msgsBox.scrollHeight;
        }}

        const bgImages = {bg_images_list};
        let currentBgIndex = 0;
        let activeBg = 1;

        function changeBackground() {{
            if (bgImages.length > 1) {{
                currentBgIndex = (currentBgIndex + 1) % bgImages.length;
                let nextImageUrl = "linear-gradient(rgba(15, 23, 42, 0.65), rgba(15, 23, 42, 0.65)), url('" + bgImages[currentBgIndex] + "')";
                
                let bg1 = document.getElementById('bg1');
                let bg2 = document.getElementById('bg2');

                if (activeBg === 1) {{
                    bg2.style.backgroundImage = nextImageUrl;
                    bg2.style.opacity = 1;
                    bg1.style.opacity = 0;
                    activeBg = 2;
                }} else {{
                    bg1.style.backgroundImage = nextImageUrl;
                    bg1.style.opacity = 1;
                    bg2.style.opacity = 0;
                    activeBg = 1;
                }}
            }}
        }}

        setInterval(changeBackground, 35000);
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
