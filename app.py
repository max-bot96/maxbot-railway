import sys, io, json, os, re, html, secrets, time, hashlib, hmac
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests as http_requests
import subprocess
from flask import Flask, render_template, render_template_string, jsonify, request, session, redirect, url_for, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import logging
import traceback

load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

SECRET_KEY = os.getenv("HONEYPOT_SECRET", "maxbot-honeypot-secret-key-2026-change-me")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
TOKEN_EXPIRY = 300

from werkzeug.wrappers import Response as WerkzeugResponse

class SecureResponse(WerkzeugResponse):
    default_mimetype = 'text/html'
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers.pop('Server', None)

app.response_class = SecureResponse

class StripServerHeader:
    def __init__(self, wsgi_app):
        self.app = wsgi_app
    def __call__(self, environ, start_response):
        def custom_start_response(status, headers, exc_info=None):
            headers[:] = [(k, v) for k, v in headers if k.lower() != 'server']
            return start_response(status, headers, exc_info)
        return self.app(environ, custom_start_response)

app.wsgi_app = StripServerHeader(app.wsgi_app)

from werkzeug.serving import WSGIRequestHandler as _WRH

_original_send_header = _WRH.send_header

def _strip_server_header(self, keyword, value):
    if keyword.lower() == 'server':
        return
    return _original_send_header(self, keyword, value)

_WRH.send_header = _strip_server_header

SECRET_KEY_ENV = os.getenv("FLASK_SECRET_KEY", "")
app.secret_key = SECRET_KEY_ENV if SECRET_KEY_ENV else secrets.token_hex(64)

app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    MAX_FORM_MEMORY_SIZE=512 * 1024,
)

DATA_FILE = "bot_data.json"
OWNER_ID = "1379265753877975182"
CLIENT_ID = "1475142485012516944"
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
OAUTH_ENABLED = bool(CLIENT_SECRET)
TUNNEL_URL_FILE = "server_url2.txt"
VISITORS_FILE = "visitors.json"

def analyze_fingerprint(fp, client_ip, data):
    score = 0
    checks = []

    # === 1. HARDWARE BAN CHECK ===
    device_hash = fp.get("device_hash", "")
    hardware_bans = data.get("hardware_bans", [])
    if device_hash in hardware_bans:
        score += 10
        checks.append("🔴 الجهاز محظور سابقاً (Hardware Ban)")
    else:
        checks.append("✅ الجهاز غير محظور")

    # === 2. REPEAT OFFENDER ===
    user_id = fp.get("user_id", "")
    hacked = data.get("hacked_accounts", {})
    prev = hacked.get(str(user_id), [])
    if prev:
        score += min(len(prev) * 3, 9)
        checks.append(f"🔴 تم القبض عليه {len(prev)} مرة سابقاً")
    else:
        checks.append("✅ لم يتم القبض عليه من قبل")

    # === 3. HEADLESS / BOT DETECTION ===
    if fp.get("webdriver"):
        score += 8
        checks.append("🔴 navigator.webdriver = true (Puppeteer/Selenium)")
    else:
        checks.append("✅ navigator.webdriver = false")

    if not fp.get("chrome"):
        score += 5
        checks.append("🔴 window.chrome = false (Headless Browser)")
    else:
        checks.append("✅ window.chrome موجود")

    if fp.get("plugins_count", 0) == 0:
        score += 4
        checks.append("🔴 بدون plugins (Headless Browser)")
    else:
        checks.append(f"✅ {fp.get('plugins_count', 0)} plugins")

    if fp.get("cookies_enabled") == False:
        score += 3
        checks.append("🔴 الكوكيز معطّل")
    else:
        checks.append("✅ الكوكيز مفعّل")

    # === 4. CANVAS FINGERPRINT ===
    if not fp.get("canvas_hash"):
        score += 5
        checks.append("🔴 Canvas فاضي (لا يدعم الرسم)")
    elif not fp.get("canvas_hash2"):
        score += 2
        checks.append("⚠️ Canvas layer 2 فاضي")
    else:
        checks.append("✅ Canvas fingerprint موجود")

    # === 5. WEBGL / GPU ===
    if not fp.get("gpu_renderer"):
        score += 5
        checks.append("🔴 GPU فاضي (Headless / VPS)")
    else:
        gpu = fp.get("gpu_renderer", "")
        if "SwiftShader" in gpu or "llvmpipe" in gpu or "Software" in gpu:
            score += 4
            checks.append(f"🔴 GPU افتراضي: {gpu[:50]} (VM/Headless)")
        else:
            checks.append(f"✅ GPU: {gpu[:50]}")

    if not fp.get("webgl_extensions"):
        score += 2
        checks.append("🔴 WebGL extensions فاضية")
    else:
        ext_count = len(fp.get("webgl_extensions", "").split(","))
        checks.append(f"✅ {ext_count} WebGL extensions")

    # === 6. AUDIO FINGERPRINT ===
    if not fp.get("audio_sample_rate"):
        score += 4
        checks.append("🔴 Audio فاضي (Headless Browser)")
    elif fp.get("audio_sample_rate") == 44100 and not fp.get("audio_render_hash"):
        score += 1
        checks.append("⚠️ Audio 기본ي فقط")
    else:
        checks.append(f"✅ Audio: {fp.get('audio_sample_rate')} Hz")

    # === 7. FONTS ===
    fonts_count = fp.get("fonts_count", 0)
    if fonts_count == 0:
        score += 3
        checks.append("🔴 بدون خطوط مكتشفة (Headless)")
    elif fonts_count < 5:
        score += 1
        checks.append(f"⚠️ {fonts_count} خطوط فقط (منخفض)")
    else:
        checks.append(f"✅ {fonts_count} خطوط مكتشفة")

    # === 8. SCREEN vs WINDOW MISMATCH ===
    try:
        parts = fp.get("screen", "").split("x")
        sw = int(parts[0]) if len(parts) > 0 else 0
        sh = int(parts[1]) if len(parts) > 1 else 0
        ww, wh = [int(x) for x in fp.get("window_size", "0x0").split("x")]
        if ww > sw or wh > sh:
            score += 2
            checks.append("⚠️ حجم النافذة أكبر من الشاشة (VM/RDP)")
        elif sw == 0:
            score += 2
            checks.append("⚠️ الشاشة فاضية")
        else:
            checks.append(f"✅ الشاشة: {fp.get('screen')}")
    except:
        checks.append("⚠️ لا يمكن فحص الشاشة")

    # === 9. SCREEN AVAIL vs FULL ===
    try:
        avail = fp.get("screen_avail", "").split("x")
        full = fp.get("screen", "").split("x")
        if avail[0] != full[0] or avail[1] != full[1]:
            score += 2
            checks.append("⚠️ screen.avail ≠ screen (VM detection)")
        else:
            checks.append("✅ screen.avail = screen")
    except:
        pass

    # === 10. CPU / RAM REALISTIC ===
    cpu = fp.get("cpu_cores", 0)
    ram = fp.get("ram_size", 0)
    if cpu == 0 and ram == 0:
        score += 3
        checks.append("🔴 CPU و RAM فاضيين")
    elif cpu > 64 or ram > 128:
        score += 2
        checks.append(f"⚠️ specs غير واقعية: {cpu} cores, {ram} GB")
    elif cpu == 0 or ram == 0:
        score += 1
        checks.append(f"⚠️ specs جزئية: {cpu} cores, {ram} GB")
    else:
        checks.append(f"✅ CPU: {cpu} cores, RAM: {ram} GB")

    # === 11. MEDIA DEVICES ===
    cam = fp.get("media_cam", -1)
    mic = fp.get("media_mic", -1)
    if cam == 0 and mic == 0:
        score += 3
        checks.append("🔴 بدون كاميرا/ميكروفون (VPS/Cloud)")
    elif cam == -1:
        checks.append("⚠️ MediaDevices غير متوفر")
    else:
        checks.append(f"✅ {cam} كاميرات, {mic} ميكروفونات")

    # === 12. BATTERY API ===
    if fp.get("battery_api") == False and fp.get("battery_level") is None:
        if "mobile" in fp.get("platform", "").lower():
            score += 2
            checks.append("⚠️ Battery API غير متوفر على جوال")
        else:
            checks.append("✅ Battery API (desktop = null عادي)")

    # === 13. WEBRTC IP LEAK ===
    webrtc = fp.get("webrtc_ips", [])
    if webrtc and client_ip:
        if client_ip not in webrtc and len(webrtc) > 0:
            score += 2
            checks.append(f"⚠️ WebRTC يكشف IPs مختلفة: {', '.join(webrtc[:3])}")
        else:
            checks.append(f"✅ WebRTC IPs متوافقة")
    elif not webrtc:
        checks.append("✅ WebRTC معطّل/محظور")

    # === 14. TOUCH CONSISTENCY ===
    tp = fp.get("touch_points", 0)
    to = fp.get("touch_ontouch", False)
    if to and tp == 0:
        score += 1
        checks.append("⚠️ touch event موجود بدون touch points")
    elif not to and tp > 0:
        score += 1
        checks.append("⚠️ touch points موجود بدون touch event")
    else:
        checks.append(f"✅ Touch: {tp} points")

    # === 15. INCOGNITO MODE ===
    if fp.get("incognito"):
        score += 2
        checks.append("⚠️ وضع التصفح الخفي مفعّل")
    else:
        checks.append("✅ وضع التصفح العادي")

    # === 16. TIME ON PAGE ===
    top = fp.get("time_on_page", 0)
    if top < 2000:
        score += 4
        checks.append(f"🔴 أقل من ثانيتين على الصفحة ({top}ms) = بوت")
    elif top < 5000:
        score += 1
        checks.append(f"⚠️ أقل من 5 ثوانٍ ({top}ms)")
    else:
        checks.append(f"✅ {round(top/1000, 1)} ثانية على الصفحة")

    # === 17. TIMEZONE vs LANGUAGE ===
    tz = fp.get("timezone", "")
    lang = fp.get("lang", "")
    if tz and lang:
        tz_region = tz.split("/")[0] if "/" in tz else ""
        lang_code = lang.split("-")[0] if "-" in lang else lang
        arab_tz = any(x in tz for x in ["Asia/Riyadh","Asia/Dubai","Asia/Baghdad","Africa/Cairo","Asia/Amman"])
        arab_lang = lang_code in ["ar"]
        if arab_lang and not arab_tz:
            score += 1
            checks.append(f"⚠️ لغة عربية مع timezone غير عربي: {tz}")
        elif not arab_lang and arab_tz:
            score += 1
            checks.append(f"⚠️ timezone عربي مع لغة غير عربية: {lang}")
        else:
            checks.append(f"✅ Timezone/Language متوافق")

    # === 18. DATACENTER / HOSTING IP ===
    try:
        ip_info = http_requests.get(f"https://ipinfo.io/{client_ip}/json", timeout=3).json()
        org = ip_info.get("org", "")
        host_keywords = ["amazon", "aws", "google", "hetzner", "digitalocean", "linode",
                        "vultr", "ovh", "scaleway", "cloudflare", "microsoft", "azure",
                        "oracle", "alibaba", "kamatera", "contabo"]
        is_hosting = any(k in org.lower() for k in host_keywords)
        if is_hosting:
            score += 4
            checks.append(f"🔴 IP من Datacenter/Hosting: {org[:60]}")
        else:
            checks.append(f"✅ IP: {org[:60]}")
        fp["_ip_org"] = org
        fp["_ip_city"] = ip_info.get("city", "")
        fp["_ip_country"] = ip_info.get("country", "")
    except:
        checks.append("⚠️ لا يمكن فحص IP info")

    # === 19. IP CLUSTERING ===
    fingerprints = data.get("fingerprints", {})
    same_ip_users = []
    for key, val in fingerprints.items():
        if val.get("ip") == client_ip and key != f"{fp.get('guild_id','')}_{user_id}":
            same_ip_users.append(key)
    if same_ip_users:
        score += min(len(same_ip_users) * 2, 6)
        checks.append(f"🔴 نفس الـ IP مع {len(same_ip_users)} حسابات أخرى")
    else:
        checks.append("✅ IP فريد")

    # === 20. LANGUAGE COUNT ===
    if fp.get("languages_count", 0) == 0:
        score += 2
        checks.append("🔴 navigator.languages فاضي (Headless)")
    else:
        checks.append(f"✅ {fp.get('languages_count', 0)} لغات")

    # === VERDICT ===
    if score >= 19:
        verdict = "🔴 مؤكد هاكر / بوت"
        verdict_en = "confirmed_hacker"
        color = 0xE74C3C
        action = "🚫 حظر الجهاز + طرد"
    elif score >= 9:
        verdict = "⚠️ مشبوه جداً"
        verdict_en = "suspicious"
        color = 0xE67E22
        action = "👁️ راقب"
    elif score >= 5:
        verdict = "⚠️ مشبوه قليلاً"
        verdict_en = "slightly_suspicious"
        color = 0xF1C40F
        action = "📋 سجّل"
    else:
        verdict = "✅ يبدو عادي"
        verdict_en = "clean"
        color = 0x2ECC71
        action = "✅ لا إجراء"

    return {
        "score": score,
        "verdict": verdict,
        "verdict_en": verdict_en,
        "color": color,
        "action": action,
        "checks": checks
    }


def send_owner_dm_fingerprint(user_id, guild_id, device_hash, ip, analysis, fp, data):
    try:
        print(f"[FINGERPRINT DM] 📨 Starting DM send to owner for user {user_id}", flush=True)
        if not DISCORD_TOKEN:
            print(f"[FINGERPRINT DM] ❌ DISCORD_TOKEN is empty!", flush=True)
            return
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
        dm_url = "https://discord.com/api/v10/users/@me/channels"
        dm_resp = http_requests.post(dm_url, json={"recipient_id": OWNER_ID}, headers=headers, timeout=10)
        if dm_resp.status_code not in (200, 201):
            print(f"[FINGERPRINT DM] ❌ Cannot create DM channel: {dm_resp.status_code}", flush=True)
            return
        channel_id = dm_resp.json()["id"]

        # Get hacker info from main bot data
        hacked = data.get("hacked_accounts", {})
        prev = hacked.get(str(user_id), [])
        repeat_text = f"**{len(prev)} مرة سابقاً**" if prev else "أول مرة"

        # Get guild name
        guild_name = guild_id

        # Build checks text
        checks_text = "\n".join([f"  {c}" for c in analysis["checks"][:15]])
        if len(analysis["checks"]) > 15:
            checks_text += "\n  ...+" + str(len(analysis["checks"]) - 15) + " فحوصات أخرى"

        # Device info
        gpu = fp.get("gpu_renderer", "غير معروف")[:50] if fp.get("gpu_renderer") else "غير معروف"
        ram = fp.get("ram_size", "?")
        cpu = fp.get("cpu_cores", "?")
        screen = fp.get("screen", "غير معروف")
        platform = fp.get("platform", "غير معروف")
        fonts = fp.get("fonts_count", "?")
        audio = fp.get("audio_sample_rate", "?")
        media_cam = fp.get("media_cam", "?")
        media_mic = fp.get("media_mic", "?")
        ip_org = fp.get("_ip_org", "غير معروف")[:60]
        ip_city = fp.get("_ip_city", "?")
        ip_country = fp.get("_ip_country", "?")

        hw_text = (
            f"├─ 📱 النظام: {platform}\n"
            f"├─ 🖥️ الشاشة: {screen}\n"
            f"├─ 🎮 GPU: {gpu}\n"
            f"├─ 💾 RAM: {ram} GB\n"
            f"├─ 🔧 CPU: {cpu} cores\n"
            f"├─ 🎵 Audio: {audio} Hz\n"
            f"├─ 🔤 Fonts: {fonts} خطوط\n"
            f"├─ 📷 الكاميرات: {media_cam}\n"
            f"└─ 🎤 الميكروفونات: {media_mic}"
        )

        embed = {
            "title": f"🔍 تقرير التحقق من الهوية — {analysis['verdict']}",
            "description": (
                f"**👤 المستخدم:** <@{user_id}> (`{user_id}`)\n"
                f"**🌐 السيرفر:** `{guild_name}`\n"
                f"**🌐 IP:** `{ip}` — {ip_city}, {ip_country}\n"
                f"**🏢 مزود الخدمة:** {ip_org}\n"
                f"**🔑 Device Hash:** `{device_hash[:20]}`\n"
                f"**📅 سبق القبض:** {repeat_text}"
            ),
            "color": analysis["color"],
            "fields": [
                {"name": "🖥️ معلومات الجهاز", "value": hw_text, "inline": False},
                {"name": "🔬 نتائج الفحص", "value": checks_text[:1024], "inline": False},
                {"name": "📊 التقييم النهائي", "value": f"**النقاط: {analysis['score']}/30**\n{analysis['verdict']}\n\n**الإجراء:** {analysis['action']}", "inline": False}
            ],
            "footer": {"text": "🌐 MAX BOT — نظام الحماية السيبرانية"},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        msg_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        msg_resp = http_requests.post(msg_url, json={"embeds": [embed]}, headers=headers, timeout=10)
        if msg_resp.status_code in (200, 201):
            print(f"[FINGERPRINT DM] ✅ Owner DM sent (score={analysis['score']}, verdict={analysis['verdict_en']})", flush=True)
        else:
            print(f"[FINGERPRINT DM] ❌ Failed: {msg_resp.status_code} {msg_resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"[FINGERPRINT DM] ❌ Error: {e}\n{traceback.format_exc()}", flush=True)

def load_visitors():
    try:
        with open(VISITORS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"visitors": [], "total": 0}

def save_visitors(data):
    with open(VISITORS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def track_visitor(ip, username="", user_id="", page=""):
    data = load_visitors()
    visitor = {
        "ip": ip,
        "username": username,
        "user_id": user_id,
        "page": page,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    data["visitors"].insert(0, visitor)
    data["visitors"] = data["visitors"][:100]
    data["total"] = data.get("total", 0) + 1
    save_visitors(data)

IP_REGEX = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$'
)
XSS_PATTERNS = [
    re.compile(r'<\s*script', re.IGNORECASE),
    re.compile(r'javascript\s*:', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),
    re.compile(r'<\s*iframe', re.IGNORECASE),
    re.compile(r'<\s*object', re.IGNORECASE),
    re.compile(r'<\s*embed', re.IGNORECASE),
    re.compile(r'<\s*svg\s+onload', re.IGNORECASE),
    re.compile(r'data\s*:\s*text/html', re.IGNORECASE),
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'vbscript\s*:', re.IGNORECASE),
]
SQLI_PATTERNS = [
    re.compile(r"(\'\s*(OR|AND)\s*[\'\d])", re.IGNORECASE),
    re.compile(r"(UNION\s+(ALL\s+)?SELECT)", re.IGNORECASE),
    re.compile(r"(SELECT\s+.*FROM\s+)", re.IGNORECASE),
    re.compile(r"(INSERT\s+INTO\s+)", re.IGNORECASE),
    re.compile(r"(UPDATE\s+.*SET\s+)", re.IGNORECASE),
    re.compile(r"(DELETE\s+FROM\s+)", re.IGNORECASE),
    re.compile(r"(DROP\s+(TABLE|DATABASE))", re.IGNORECASE),
    re.compile(r"(--\s*$|/\*|\*/)", re.IGNORECASE),
    re.compile(r"(CHAR\s*\(|CONCAT\s*\(|0x[0-9a-fA-F]+)", re.IGNORECASE),
    re.compile(r"(BENCHMARK\s*\(|SLEEP\s*\(|LOAD_FILE\s*\()", re.IGNORECASE),
    re.compile(r"(INTO\s+(OUTFILE|DUMPFILE))", re.IGNORECASE),
]

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

_rate_limit_store = defaultdict(list)
_brute_force_store = defaultdict(lambda: {"count": 0, "locked_until": None})
_CAPTCHA_SECRET = os.getenv("CAPTCHA_SECRET", secrets.token_hex(32))

def get_base_url():
    env_url = os.getenv("SITE_URL", "").strip()
    if env_url:
        return env_url
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}"
    try:
        with open(TUNNEL_URL_FILE, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip().splitlines()
            url = raw[0].strip() if raw else ""
            if url:
                return url
    except Exception:
        pass
    return None

def get_real_ip():
    cf_ip = request.headers.get("CF-Connecting-IP", "")
    if cf_ip and IP_REGEX.match(cf_ip.split(",")[0].strip()):
        return cf_ip.split(",")[0].strip()
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        candidate = xff.split(",")[0].strip()
        if IP_REGEX.match(candidate):
            return candidate
    forwarded = request.headers.get("Forwarded", "")
    m = re.search(r'for="?([^";,\s]+)', forwarded, re.IGNORECASE)
    if m and IP_REGEX.match(m.group(1).strip('"')):
        return m.group(1).strip('"')
    remote = request.remote_addr or "127.0.0.1"
    if remote in ("127.0.0.1", "::1", "localhost"):
        return "127.0.0.1"
    if IP_REGEX.match(remote):
        return remote
    return "127.0.0.1"

def sanitize_input(value, max_length=500):
    if not isinstance(value, str):
        return ""
    value = value[:max_length]
    value = html.escape(value, quote=True)
    value = value.replace("'", "&#39;").replace('"', "&#34;")
    value = value.replace("\\", "&#92;")
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    return value.strip()

def detect_xss(value):
    if not isinstance(value, str):
        return False
    for pattern in XSS_PATTERNS:
        if pattern.search(value):
            return True
    return False

def detect_sqli(value):
    if not isinstance(value, str):
        return False
    cleaned = re.sub(r'[\s\t\n\r]+', ' ', value)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'--\s.*', '', cleaned)
    for pattern in SQLI_PATTERNS:
        if pattern.search(cleaned):
            return True
    return False

def validate_input(value, field_name="input"):
    if detect_xss(value):
        raise ValueError(f"XSS injection detected in {field_name}")
    if detect_sqli(value):
        raise ValueError(f"SQL injection detected in {field_name}")
    return sanitize_input(value)

def rate_limit(max_requests=30, window=60):
    ip = get_real_ip()
    now = time.time()
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    if len(_rate_limit_store[ip]) >= max_requests:
        return True
    _rate_limit_store[ip].append(now)
    return False

def check_brute_force(ip, max_attempts=5, lockout_minutes=15):
    info = _brute_force_store[ip]
    if info["locked_until"] and datetime.now() < info["locked_until"]:
        return True
    if info["locked_until"] and datetime.now() >= info["locked_until"]:
        info["count"] = 0
        info["locked_until"] = None
    return False

def register_brute_force(ip, max_attempts=5, lockout_minutes=15):
    info = _brute_force_store[ip]
    info["count"] += 1
    if info["count"] >= max_attempts:
        info["locked_until"] = datetime.now() + timedelta(minutes=lockout_minutes)
        return True
    return False

def reset_brute_force(ip):
    _brute_force_store[ip]["count"] = 0
    _brute_force_store[ip]["locked_until"] = None

def generate_captcha():
    a = secrets.randbelow(20) + 1
    b = secrets.randbelow(20) + 1
    ops = ['+', '-', '×']
    op = secrets.choice(ops)
    if op == '+':
        answer = a + b
        question = f"{a} + {b}"
    elif op == '-':
        if a < b:
            a, b = b, a
        answer = a - b
        question = f"{a} - {b}"
    else:
        answer = a * b
        question = f"{a} × {b}"
    token = hmac.new(
        _CAPTCHA_SECRET.encode(),
        str(answer).encode(),
        hashlib.sha256
    ).hexdigest()
    return question, str(answer), token

def verify_captcha(answer, token):
    expected = hmac.new(
        _CAPTCHA_SECRET.encode(),
        answer.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, token)

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def send_discord_dm(user_id, message):
    if not DISCORD_TOKEN:
        return False
    try:
        r = http_requests.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            json={"recipient_id": user_id},
            timeout=10
        )
        if r.status_code != 200:
            return False
        channel_id = r.json()["id"]
        r2 = http_requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            json={"content": message},
            timeout=10
        )
        return r2.status_code == 200
    except Exception:
        return False

COMMANDS_FILE = "commands_data.json"

def load_commands():
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

COMMANDS = load_commands()

@app.after_request
def security_headers(response):
    path = request.path
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer()'
    public_paths = ['/', '/login', '/commands', '/support', '/terms', '/privacy', '/contact', '/sitemap.xml', '/robots.txt']
    if path in public_paths:
        response.headers['X-Robots-Tag'] = 'index, follow'
        response.headers['Cache-Control'] = 'public, max-age=300'
    else:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https://cdn.discordapp.com https://*.cloudflare.com https://whatismyipaddress.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    response.headers.pop('Server', None)
    response.headers.pop('X-Powered-By', None)
    return response

@app.before_request
def security_before_request():
    if request.path in ['/api/fingerprint']:
        return None
    ip = get_real_ip()
    if rate_limit(max_requests=60, window=60):
        return jsonify({"error": "rate limit exceeded"}), 429
    if check_brute_force(ip):
        return jsonify({"error": "temporarily locked"}), 429
    if request.method == "POST":
        content_type = request.content_type or ""
        if "application/json" in content_type:
            try:
                data = request.get_json(silent=True)
                if data and isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, str):
                            validate_input(val, key)
            except ValueError:
                return jsonify({"error": "security violation detected"}), 403
        elif "application/x-www-form-urlencoded" in content_type:
            for key in request.form:
                val = request.form[key]
                try:
                    validate_input(val, key)
                except ValueError:
                    return jsonify({"error": "security violation detected"}), 403
    if request.method == "GET":
        for key in request.args:
            val = request.args[key]
            try:
                validate_input(val, key)
            except ValueError:
                return jsonify({"error": "security violation detected"}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Internal System Transaction Blocked"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal System Transaction Blocked"}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "request too large"}), 413

@app.errorhandler(429)
def too_many(e):
    return jsonify({"error": "rate limit exceeded"}), 429

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": "MAX BOT"})

@app.route("/api/visitors")
def api_visitors():
    data = load_visitors()
    return jsonify(data)

@app.route('/sitemap.xml')
def sitemap():
    base = get_base_url() or "https://web-production-f6fb8.up.railway.app"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
    <url><loc>{base}/login</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
    <url><loc>{base}/commands</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
    <url><loc>{base}/support</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
    <url><loc>{base}/terms</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
    <url><loc>{base}/privacy</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
    <url><loc>{base}/contact</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
</urlset>"""
    return xml, 200, {'Content-Type': 'application/xml'}

@app.route('/robots.txt')
def robots():
    base = get_base_url() or "https://web-production-f6fb8.up.railway.app"
    txt = f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /callback\nDisallow: /logout\nSitemap: {base}/sitemap.xml"
    return txt, 200, {
        'Content-Type': 'text/plain',
        'Cache-Control': 'public, max-age=3600'
    }

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = get_real_ip()
    track_visitor(ip, page="login")
    if check_brute_force(ip):
        total_commands = len(COMMANDS)
        return render_template("login.html",
            error="تم حظر عنوانك مؤقتاً بسبب محاولات كثيرة",
            oauth_enabled=OAUTH_ENABLED, redirect_uri="",
            total_commands=total_commands)

    if request.method == "POST":
        user_id_raw = request.form.get("user_id", "")
        captcha_answer = request.form.get("captcha_answer", "")
        captcha_token = request.form.get("captcha_token", "")
        total_commands = len(COMMANDS)
        if not verify_captcha(captcha_answer, captcha_token):
            register_brute_force(ip)
            captcha_q, _, captcha_token_new = generate_captcha()
            return render_template("login.html",
                error="الإجابة على السؤال الأمني خاطئة",
                oauth_enabled=OAUTH_ENABLED, redirect_uri="",
                captcha_question=captcha_q, captcha_token=captcha_token_new,
                show_captcha=True, total_commands=total_commands)
        try:
            user_id = validate_input(user_id_raw, "user_id")
        except ValueError:
            return render_template("login.html",
                error="الإدخال يحتوي على محتوى غير آمن",
                oauth_enabled=OAUTH_ENABLED, redirect_uri="",
                total_commands=total_commands)
        if user_id == OWNER_ID:
            reset_brute_force(ip)
            session.permanent = True
            session["owner"] = True
            session["user_id"] = user_id
            session["login_ip"] = ip
            session["login_time"] = datetime.now().isoformat()
            return redirect(url_for("dashboard"))
        else:
            register_brute_force(ip)
            captcha_q, _, captcha_token_new = generate_captcha()
            return render_template("login.html",
                error="رقم التعريف غير صحيح",
                oauth_enabled=OAUTH_ENABLED, redirect_uri="",
                captcha_question=captcha_q, captcha_token=captcha_token_new,
                show_captcha=True, total_commands=total_commands)

    captcha_q, _, captcha_token_val = generate_captcha()
    base = (get_base_url() or request.host_url.rstrip("/")).rstrip("/")
    redirect_uri = base + url_for("callback")
    total_commands = len(COMMANDS)
    return render_template("login.html",
        redirect_uri=redirect_uri,
        show_id_input=False,
        oauth_enabled=OAUTH_ENABLED,
        captcha_question=captcha_q,
        captcha_token=captcha_token_val,
        show_captcha=True,
        total_commands=total_commands)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("login"))

    ip = get_real_ip()

    base = (get_base_url() or request.host_url.rstrip("/")).rstrip("/")
    redirect_uri = base + url_for("callback")

    try:
        r = http_requests.post("https://discord.com/api/oauth2/token", data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "scope": "identify"
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        token_data = r.json()
        if "access_token" not in token_data:
            captcha_q, _, captcha_token_new = generate_captcha()
            total_commands = len(COMMANDS)
            return render_template("login.html",
                error="فشل تسجيل الدخول عبر Discord",
                oauth_enabled=OAUTH_ENABLED, redirect_uri=redirect_uri,
                captcha_question=captcha_q, captcha_token=captcha_token_new,
                show_captcha=True, total_commands=total_commands)

        r2 = http_requests.get("https://discord.com/api/users/@me", headers={
            "Authorization": f"Bearer {token_data['access_token']}"
        }, timeout=15)
        user_data = r2.json()
        user_id = user_data.get("id")

        if user_id == OWNER_ID:
            reset_brute_force(ip)
            session.permanent = True
            session["owner"] = True
            session["user_id"] = user_id
            session["username"] = user_data.get("username", "")
            avatar_hash = user_data.get("avatar")
            session["avatar"] = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else ""
            session["login_ip"] = ip
            session["login_time"] = datetime.now().isoformat()

            login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            login_time_en = datetime.now().strftime("%I:%M %p")
            ua = (request.headers.get("User-Agent", "") or "")[:200]
            site_url = get_base_url() or request.host_url.rstrip("/")
            
            browser = "مجهول"
            if "Chrome" in ua and "Edg" not in ua: browser = "Google Chrome"
            elif "Edg" in ua: browser = "Microsoft Edge"
            elif "Firefox" in ua: browser = "Mozilla Firefox"
            elif "Safari" in ua and "Chrome" not in ua: browser = "Safari"
            elif "Opera" in ua or "OPR" in ua: browser = "Opera"
            
            os_name = "مجهول"
            if "Windows NT 10" in ua: os_name = "Windows 10/11"
            elif "Windows NT 6.3" in ua: os_name = "Windows 8.1"
            elif "Windows NT 6.1" in ua: os_name = "Windows 7"
            elif "Linux" in ua and "Android" not in ua: os_name = "Linux"
            elif "Mac OS X" in ua: os_name = "macOS"
            elif "Android" in ua: os_name = "Android"
            elif "iPhone" in ua or "iPad" in ua: os_name = "iOS"
            
            device = "مجهول"
            if "Mobile" in ua or "Android" in ua: device = "📱 موبايل"
            elif "Tablet" in ua or "iPad" in ua: device = "📱 تابلت"
            else: device = "💻 كمبيوتر"
            
            msg = (
                f"```\n"
                f"╔══════════════════════════════════════╗\n"
                f"║     🔐 تنبيه أمني: تسجيل دخول       ║\n"
                f"╚══════════════════════════════════════╝\n"
                f"```\n\n"
                f"**👤 حساب المستخدم**\n"
                f"├─ الاسم: **{user_data.get('username', 'غير معروف')}**\n"
                f"├─ المعرّف: `{user_id}`\n"
                f"└─ الأفاتار: [عرض](https://cdn.discordapp.com/avatars/{user_id}/{user_data.get('avatar', '')}.png)\n\n"
                f"**🕐 تفاصيل الجلسة**\n"
                f"├─ التاريخ: `{login_time}`\n"
                f"└─ الوقت: `{login_time_en}`\n\n"
                f"**🌐 بيانات الشبكة**\n"
                f"├─ عنوان IP: `{ip}`\n"
                f"├─ الموقع: [Google Maps](https://www.google.com/maps?q={ip})\n"
                f"└─ مزود الخدمة: [OVH Cloud](https://ipinfo.io/{ip})\n\n"
                f"**📱 مواصفات الجهاز**\n"
                f"├─ النوع: {device}\n"
                f"├─ المتصفّح: {browser}\n"
                f"└─ نظام التشغيل: {os_name}\n\n"
                f"**🔗 رابط الموقع**\n"
                f"└─ [{site_url}]({site_url})\n\n"
                f"```\n"
                f"╔══════════════════════════════════════╗\n"
                f"║  ⚠️ إذا لم تكن أنت، غيّر كلمة      ║\n"
                f"║  المرور فوراً واتصل بالدعم الفني   ║\n"
                f"╚══════════════════════════════════════╝\n"
                f"```"
            )
            send_discord_dm(OWNER_ID, msg)

            return redirect(url_for("dashboard"))
        else:
            reset_brute_force(ip)
            session.permanent = True
            session["owner"] = False
            session["user_id"] = user_id
            session["username"] = user_data.get("username", "")
            avatar_hash = user_data.get("avatar")
            session["avatar"] = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else ""
            session["login_ip"] = ip
            session["login_time"] = datetime.now().isoformat()

            login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            login_time_en = datetime.now().strftime("%I:%M %p")
            ua = (request.headers.get("User-Agent", "") or "")[:200]
            site_url = get_base_url() or request.host_url.rstrip("/")

            browser = "مجهول"
            if "Chrome" in ua and "Edg" not in ua: browser = "Google Chrome"
            elif "Edg" in ua: browser = "Microsoft Edge"
            elif "Firefox" in ua: browser = "Mozilla Firefox"
            elif "Safari" in ua and "Chrome" not in ua: browser = "Safari"
            elif "Opera" in ua or "OPR" in ua: browser = "Opera"

            os_name = "مجهول"
            if "Windows NT 10" in ua: os_name = "Windows 10/11"
            elif "Windows NT 6.3" in ua: os_name = "Windows 8.1"
            elif "Windows NT 6.1" in ua: os_name = "Windows 7"
            elif "Linux" in ua and "Android" not in ua: os_name = "Linux"
            elif "Mac OS X" in ua: os_name = "macOS"
            elif "Android" in ua: os_name = "Android"
            elif "iPhone" in ua or "iPad" in ua: os_name = "iOS"

            device = "مجهول"
            if "Mobile" in ua or "Android" in ua: device = "📱 موبايل"
            elif "Tablet" in ua or "iPad" in ua: device = "📱 تابلت"
            else: device = "💻 كمبيوتر"

            msg = (
                f"```\n"
                f"╔══════════════════════════════════════╗\n"
                f"║     🔐 تنبيه: دخول مستخدم جديد     ║\n"
                f"╚══════════════════════════════════════╝\n"
                f"```\n\n"
                f"**👤 حساب المستخدم**\n"
                f"├─ الاسم: **{user_data.get('username', 'غير معروف')}**\n"
                f"├─ المعرّف: `{user_id}`\n"
                f"└─ الأفاتار: [عرض](https://cdn.discordapp.com/avatars/{user_id}/{user_data.get('avatar', '')}.png)\n\n"
                f"**🕐 تفاصيل الجلسة**\n"
                f"├─ التاريخ: `{login_time}`\n"
                f"└─ الوقت: `{login_time_en}`\n\n"
                f"**🌐 بيانات الشبكة**\n"
                f"├─ عنوان IP: `{ip}`\n"
                f"├─ الموقع: [Google Maps](https://www.google.com/maps?q={ip})\n"
                f"└─ مزود الخدمة: [OVH Cloud](https://ipinfo.io/{ip})\n\n"
                f"**📱 مواصفات الجهاز**\n"
                f"├─ النوع: {device}\n"
                f"├─ المتصفّح: {browser}\n"
                f"└─ نظام التشغيل: {os_name}\n\n"
                f"**🔗 رابط الموقع**\n"
                f"└─ [{site_url}]({site_url})\n\n"
                f"```"
            )
            send_discord_dm(OWNER_ID, msg)

            return redirect(url_for("dashboard"))
    except Exception:
        captcha_q, _, captcha_token_new = generate_captcha()
        total_commands = len(COMMANDS)
        return render_template("login.html",
            error="خطأ في الاتصال، حاول مجدداً",
            oauth_enabled=OAUTH_ENABLED, redirect_uri="",
            captcha_question=captcha_q, captcha_token=captcha_token_new,
            show_captcha=True, total_commands=total_commands)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    current_ip = get_real_ip()
    if session.get("login_ip") and session["login_ip"] != current_ip:
        session.clear()
        return redirect(url_for("login"))
    return render_template("dashboard.html",
        username=session.get("username", "المالك"),
        avatar=session.get("avatar", ""))

@app.route("/commands")
def commands_page():
    categories = {}
    for cmd in COMMANDS:
        cat = cmd.get("category", "غير محدد")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(cmd)
    total = sum(len(cmds) for cmds in categories.values())
    return render_template("commands.html", categories=categories, total=total)

@app.route("/api/stats")
def stats():
    STATS_FILE = "bot_stats.json"
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify({"guilds": 0, "total_members": 0, "commands_used": 0, "uptime": "0", "last_updated": ""})

@app.route("/api/economy")
def economy():
    data = load_data()
    economy_data = data.get("economy", {})
    top_users = []
    for guild_id, guild_data in economy_data.items():
        if isinstance(guild_data, dict):
            for uid, u in guild_data.get("users", {}).items():
                if isinstance(u, dict):
                    top_users.append({
                        "name": sanitize_input(u.get("name", "Unknown"), 30),
                        "cash": u.get("cash", 0),
                        "bank": u.get("bank", 0)
                    })
    top_users.sort(key=lambda x: x["cash"] + x["bank"], reverse=True)
    return jsonify(top_users[:10])

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

DISCORD_USER_ID = "1379265753877975182"
DISCORD_PROFILE_URL = f"https://discord.com/users/{DISCORD_USER_ID}"
SUPPORT_EMAIL = "MaxoptSupportTeam@gmail.com"

@app.route("/support")
def support():
    return render_template("support.html",
        discord_url=DISCORD_PROFILE_URL,
        bot_url=get_base_url() or "",
        support_email=SUPPORT_EMAIL)

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/api/contact", methods=["POST"])
def api_contact():
    ip = get_real_ip()
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"ok": False, "error": "بيانات غير صالحة"})
        name_raw = data.get("name", "")
        email_raw = data.get("email", "")
        message_raw = data.get("message", "")
        if not name_raw or not email_raw or not message_raw:
            return jsonify({"ok": False, "error": "جميع الحقول مطلوبة"})
        try:
            name = validate_input(name_raw, "name")
            email = validate_input(email_raw, "email")
            message = validate_input(message_raw, "message")
        except ValueError:
            return jsonify({"ok": False, "error": "البيانات تحتوي على محتوى غير آمن"})
        if len(name) < 2 or len(name) > 100:
            return jsonify({"ok": False, "error": "الاسم غير صالح"})
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({"ok": False, "error": "الإيميل غير صالح"})
        if len(message) < 10 or len(message) > 2000:
            return jsonify({"ok": False, "error": "الرسالة يجب أن تكون بين 10 و 2000 حرف"})
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dm = (
            f"📬 **رسالة جديدة من صفحة التواصل**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **الاسم:** {name}\n"
            f"📧 **الإيميل:** {email}\n"
            f"📝 **الرسالة:**\n{message}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 **IP:** {ip}\n"
            f"🕐 **الوقت:** {now}"
        )
        sent = send_discord_dm(DISCORD_USER_ID, dm)
        if sent:
            return jsonify({"ok": True, "message": "تم إرسال رسالتك بنجاح! سنرد عليك قريباً"})
        else:
            return jsonify({"ok": False, "error": "فشل الإرسال، تواصل معنا عبر Discord"})
    except Exception:
        return jsonify({"ok": False, "error": "خطأ داخلي"})

@app.route("/api/invite")
def invite_link():
    return jsonify({
        "invite_url": f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands",
        "bot_id": CLIENT_ID
    })

@app.route("/api/restart", methods=["POST"])
def api_restart():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ip = get_real_ip()
    if rate_limit(max_requests=3, window=300):
        return jsonify({"ok": False, "error": "تم تقييد هذا الطلب مؤقتاً"}), 429
    try:
        subprocess.run(['schtasks', '/end', '/tn', 'MaxBotRun'], capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run(['schtasks', '/delete', '/tn', 'MaxBotRun', '/f'], capture_output=True, timeout=5)
        time.sleep(1)
        subprocess.run([
            'schtasks', '/create',
            '/tn', 'MaxBotRun',
            '/tr', r'powershell.exe -WindowStyle Hidden -Command "& \'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe\' -u \'C:\Users\USER\Desktop\z1-pro\main.py\'"',
            '/sc', 'once', '/st', '00:00', '/f'
        ], capture_output=True, timeout=5)
        subprocess.run(['schtasks', '/run', '/tn', 'MaxBotRun'], capture_output=True, timeout=5)
        return jsonify({"ok": True, "message": "جاري إعادة تشغيل البوت..."})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/start", methods=["POST"])
def api_start():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ip = get_real_ip()
    if rate_limit(max_requests=3, window=300):
        return jsonify({"ok": False, "error": "تم تقييد هذا الطلب مؤقتاً"}), 429
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             'Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*main.py*" -and $_.CommandLine -like "*python*" }'],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            return jsonify({"ok": True, "message": "البوت شغّال بالفعل"})
        subprocess.run([
            'schtasks', '/create',
            '/tn', 'MaxBotRun',
            '/tr', r'powershell.exe -WindowStyle Hidden -Command "& \'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe\' -u \'C:\Users\USER\Desktop\z1-pro\main.py\'"',
            '/sc', 'once', '/st', '00:00', '/f'
        ], capture_output=True, timeout=5)
        subprocess.run(['schtasks', '/run', '/tn', 'MaxBotRun'], capture_output=True, timeout=5)
        return jsonify({"ok": True, "message": "جاري تشغيل البوت..."})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    ip = get_real_ip()
    if rate_limit(max_requests=3, window=300):
        return jsonify({"ok": False, "error": "تم تقييد هذا الطلب مؤقتاً"}), 429
    try:
        subprocess.run(['schtasks', '/end', '/tn', 'MaxBotRun'], capture_output=True, timeout=10)
        result = subprocess.run(
            ['powershell', '-Command',
             'Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*main.py*" -and $_.CommandLine -like "*python*" } | Select-Object -ExpandProperty ProcessId'],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split('\n')
        for pid in pids:
            pid = pid.strip()
            if pid and pid.isdigit():
                subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=5)
        return jsonify({"ok": True, "message": "تم إيقاف البوت"})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/sync", methods=["POST"])
def api_sync():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    try:
        with open("dashboard_cmd.txt", "w", encoding="utf-8") as f:
            f.write("sync")
        return jsonify({"ok": True, "message": "تم إرسال أمر المزامنة"})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/update-commands", methods=["POST"])
def api_update_commands():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    try:
        with open("dashboard_cmd.txt", "w", encoding="utf-8") as f:
            f.write("sync")
        global COMMANDS
        COMMANDS = load_commands()
        return jsonify({"ok": True, "message": "تم تحديث الأوامر", "total": len(COMMANDS)})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/backup", methods=["POST"])
def api_backup():
    if not session.get("owner"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    try:
        with open("dashboard_cmd.txt", "w", encoding="utf-8") as f:
            f.write("backup")
        return jsonify({"ok": True, "message": "تم إرسال أمر النسخ الاحتياطي"})
    except Exception:
        return jsonify({"ok": False, "error": "فشل التنفيذ"})

@app.route("/api/bot_status")
def api_bot_status():
    STATS_FILE = "bot_stats.json"
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return jsonify({"ok": True, "online": True, **json.load(f)})
        except Exception:
            pass
    return jsonify({"ok": True, "online": False, "message": "لا توجد إحصائيات"})

@app.route("/api/command-logs")
def api_command_logs():
    if not session.get("user_id"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    CMD_LOGS_FILE = "command_logs.json"
    if not os.path.exists(CMD_LOGS_FILE):
        return jsonify({"ok": True, "logs": [], "total": 0})
    try:
        with open(CMD_LOGS_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 50))))
        cmd_filter = sanitize_input(request.args.get("command", ""), 50).strip().lower()
        guild_filter = sanitize_input(request.args.get("guild", ""), 100).strip()
        user_filter = sanitize_input(request.args.get("user", ""), 100).strip()

        filtered = logs
        if cmd_filter:
            filtered = [l for l in filtered if cmd_filter in l.get("command", "").lower()]
        if guild_filter:
            filtered = [l for l in filtered if guild_filter in l.get("guild", "").lower()]
        if user_filter:
            filtered = [l for l in filtered if user_filter in l.get("user", "").lower()]

        filtered = list(reversed(filtered))
        total = len(filtered)
        start = (page - 1) * per_page
        end = start + per_page
        page_logs = filtered[start:end]

        top_commands = {}
        for l in logs:
            cmd = l.get("command", "?")
            top_commands[cmd] = top_commands.get(cmd, 0) + 1
        top_cmds = sorted(top_commands.items(), key=lambda x: x[1], reverse=True)[:10]

        top_users = {}
        for l in logs:
            user = l.get("user", "?")
            top_users[user] = top_users.get(user, 0) + 1
        top_usr = sorted(top_users.items(), key=lambda x: x[1], reverse=True)[:10]

        return jsonify({
            "ok": True,
            "logs": page_logs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "top_commands": [{"name": n, "count": c} for n, c in top_cmds],
            "top_users": [{"name": n, "count": c} for n, c in top_usr],
        })
    except Exception:
        return jsonify({"ok": False, "error": "فشل تحميل البيانات"})

# ═══════════════════════════════════════════════════════════════
# 🪤 نظام الحماية السيبرانية — Honeypot System
# ═══════════════════════════════════════════════════════════════

def _load_bot_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {"fingerprints": {}, "hardware_bans": [], "honeypot_invites": {}, "hacker_bait_channels": {}, "hacker_bait_kicked": [], "hacked_accounts": {}}

def _save_bot_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)

def generate_token(user_id, guild_id):
    payload = f"{user_id}:{guild_id}:{int(time.time())}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{sig}.{int(time.time())}"

def validate_token(token):
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False, "invalid format"
        sig, ts_str = parts
        ts = int(ts_str)
        now = int(time.time())
        if now - ts > TOKEN_EXPIRY:
            return False, "expired"
        data = _load_bot_data()
        used = data.get("used_tokens", [])
        if token in used:
            return False, "already used"
        for uid in data.get("fingerprints", {}).keys():
            for fp in data["fingerprints"][uid].get("tokens_used", []):
                if fp == token:
                    return False, "already used"
        return True, "valid"
    except:
        return False, "error"

@app.route('/verify', methods=['GET'])
def honeypot_verify():
    token = request.args.get('token', '')
    guild_id = request.args.get('guild_id', '')
    user_id = request.args.get('user_id', '')
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()

    isp_name = "Unknown ISP"
    latitude = "0"
    longitude = "0"
    city = "Unknown"
    try:
        ip_info = http_requests.get(f"https://ipinfo.io/{client_ip}/json", timeout=5).json()
        isp_name = ip_info.get("org", "Unknown ISP")
        loc = ip_info.get("loc", "0,0")
        parts = loc.split(",")
        latitude = parts[0] if len(parts) > 0 else "0"
        longitude = parts[1] if len(parts) > 1 else "0"
        city = ip_info.get("city", "Unknown")
    except Exception:
        pass

    invite_link = "#"
    try:
        data = _load_bot_data()
        invite_link = data.get("honeypot_invites", {}).get(token, "#")
    except Exception:
        pass

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "honeypot.html"), "r", encoding="utf-8") as f:
        html_content = f.read()
    html_content = html_content.replace("{{token}}", token)
    html_content = html_content.replace("{{guild_id}}", guild_id)
    html_content = html_content.replace("{{user_id}}", user_id)
    html_content = html_content.replace("{{client_ip}}", client_ip or '')
    html_content = html_content.replace("{{isp_name}}", isp_name)
    html_content = html_content.replace("{{latitude}}", latitude)
    html_content = html_content.replace("{{longitude}}", longitude)
    html_content = html_content.replace("{{city}}", city)
    html_content = html_content.replace("{{invite_link}}", invite_link)
    return html_content

EXPIRED_PAGE = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>انتهت الصلاحية</title>
<style>body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;font-size:16px}
.box{text-align:center;max-width:400px}.icon{font-size:64px;margin-bottom:16px}.title{font-size:20px;color:#E74C3C;margin-bottom:8px}.desc{color:#949ba4}</style></head>
<body><div class="box"><div class="icon">🔒</div><div class="title">رابط منتهي الصلاحية</div>
<div class="desc">هذا الرابط لم يعد صالحاً.<br>يرجى طلب رابط جديد من السيرفر.</div></div></body></html>"""

@app.route('/api/fingerprint', methods=['POST'])
def receive_fingerprint():
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return jsonify({"ok": True, "banned": False})
        token = payload.get('token', '')
        guild_id = payload.get('guild_id', '')
        user_id = payload.get('user_id', '')
        if not token or not guild_id or not user_id:
            return jsonify({"ok": True, "banned": False})
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if client_ip and ',' in client_ip:
            client_ip = client_ip.split(',')[0].strip()
        fingerprint = {
            "ip": client_ip,
            "ua": payload.get('ua', ''),
            "platform": payload.get('platform', ''),
            "screen": payload.get('screen', ''),
            "screen_avail": payload.get('screen_avail', ''),
            "window_size": payload.get('window_size', ''),
            "lang": payload.get('lang', ''),
            "languages": payload.get('languages', ''),
            "languages_count": payload.get('languages_count', 0),
            "timezone": payload.get('timezone', ''),
            "tz_offset": payload.get('tz_offset', 0),
            "cpu_cores": payload.get('cpu_cores', 0),
            "ram_size": payload.get('ram_size', 0),
            "gpu_vendor": payload.get('gpu_vendor', ''),
            "gpu_renderer": payload.get('gpu_renderer', ''),
            "canvas_hash": payload.get('canvas_hash', ''),
            "canvas_hash2": payload.get('canvas_hash2', ''),
            "audio_sample_rate": payload.get('audio_sample_rate', 0),
            "audio_render_hash": payload.get('audio_render_hash', ''),
            "audio_state": payload.get('audio_state', ''),
            "font_hash": payload.get('font_hash', ''),
            "fonts": payload.get('fonts', ''),
            "fonts_count": payload.get('fonts_count', 0),
            "local_ip": payload.get('local_ip', ''),
            "battery_level": payload.get('battery_level', None),
            "battery_charging": payload.get('battery_charging', None),
            "battery_api": payload.get('battery_api', None),
            "battery_charging_time": payload.get('battery_charging_time', None),
            "battery_discharging_time": payload.get('battery_discharging_time', None),
            "mouse_avg_dx": payload.get('mouse_avg_dx', 0),
            "mouse_avg_dy": payload.get('mouse_avg_dy', 0),
            "touch_avg_force": payload.get('touch_avg_force', 0),
            "touch_samples": payload.get('touch_samples', 0),
            "touch_ontouch": payload.get('touch_ontouch', False),
            "touch_points": payload.get('touch_points', 0),
            "pointer_events": payload.get('pointer_events', False),
            "mouse_events": payload.get('mouse_events', False),
            "memory_timing": payload.get('memory_timing', 0),
            "cpu_timing": payload.get('cpu_timing', 0),
            "media_devices": payload.get('media_devices', 0),
            "media_count": payload.get('media_count', 0),
            "media_cam": payload.get('media_cam', 0),
            "media_mic": payload.get('media_mic', 0),
            "media_speaker": payload.get('media_speaker', 0),
            "no_js": payload.get('no_js', False),
            "webdriver": payload.get('webdriver', False),
            "chrome": payload.get('chrome', False),
            "plugins_count": payload.get('plugins_count', 0),
            "cookies_enabled": payload.get('cookies_enabled', False),
            "dnt": payload.get('dnt', ''),
            "connection": payload.get('connection', {}),
            "product": payload.get('product', ''),
            "vendor": payload.get('vendor', ''),
            "webrtc_ips": payload.get('webrtc_ips', []),
            "speech_count": payload.get('speech_count', 0),
            "speech_voices": payload.get('speech_voices', []),
            "incognito": payload.get('incognito', False),
            "time_on_page": payload.get('time_on_page', 0),
            "page_load_ms": payload.get('page_load_ms', 0),
            "has_focus": payload.get('has_focus', True),
            "css_features": payload.get('css_features', ''),
            "js_timing": payload.get('js_timing', 0),
            "js_engine": payload.get('js_engine', ''),
            "webgl_version": payload.get('webgl_version', ''),
            "webgl_extensions": payload.get('webgl_extensions', ''),
            "webgl_max_tex": payload.get('webgl_max_tex', 0),
            "webgl_fs_prec": payload.get('webgl_fs_prec', 0),
            "webgl_vs_prec": payload.get('webgl_vs_prec', 0),
            "nav_dns": payload.get('nav_dns', 0),
            "nav_tcp": payload.get('nav_tcp', 0),
            "nav_tls": payload.get('nav_tls', 0),
            "nav_ttfb": payload.get('nav_ttfb', 0),
            "nav_total": payload.get('nav_total', 0),
            "collected_at": payload.get('collected_at', datetime.utcnow().isoformat()),
        }
        device_raw = "|".join([
            str(fingerprint.get('canvas_hash', '')),
            str(fingerprint.get('gpu_renderer', '')),
            str(fingerprint.get('ram_size', '')),
            str(fingerprint.get('cpu_cores', '')),
            str(fingerprint.get('audio_sample_rate', '')),
            str(fingerprint.get('fonts', '')[:200]),
            str(fingerprint.get('screen', '')),
            str(fingerprint.get('webgl_extensions', '')[:200]),
            str(fingerprint.get('canvas_hash2', '')),
            str(fingerprint.get('audio_render_hash', '')),
        ])
        device_hash = hashlib.sha256(device_raw.encode()).hexdigest()[:32]
        fingerprint['device_hash'] = device_hash
        data = _load_bot_data()
        if 'fingerprints' not in data:
            data['fingerprints'] = {}
        if 'hardware_bans' not in data:
            data['hardware_bans'] = []
        if 'hacked_accounts' not in data:
            data['hacked_accounts'] = {}
        is_banned = device_hash in data['hardware_bans']
        fp_key = f"{guild_id}_{user_id}"
        data['fingerprints'][fp_key] = fingerprint
        _save_bot_data(data)
        print(f"[FINGERPRINT] ✅ Received from {client_ip} | device={device_hash[:16]} | guild={guild_id} user={user_id}", flush=True)

        # Run analysis
        analysis = analyze_fingerprint(fingerprint, client_ip, data)

        # Send report to owner
        send_owner_dm_fingerprint(user_id, guild_id, device_hash, client_ip, analysis, fingerprint, data)

        # Auto-ban confirmed hackers
        if analysis["verdict_en"] == "confirmed_hacker" and device_hash not in data.get("hardware_bans", []):
            data2 = _load_bot_data()
            data2.setdefault("hardware_bans", []).append(device_hash)
            _save_bot_data(data2)
            print(f"[FINGERPRINT] 🚫 Auto-banned device {device_hash[:16]} (score={analysis['score']})", flush=True)

        return jsonify({"ok": True, "banned": is_banned, "device_hash": device_hash, "score": analysis["score"], "verdict": analysis["verdict_en"]})
    except Exception as e:
        print(f"[FINGERPRINT ERROR] {e}", flush=True)
        return jsonify({"ok": True, "banned": False})

@app.route('/api/honeypot_status', methods=['GET'])
def honeypot_status():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    data = _load_bot_data()
    fps = data.get('fingerprints', {})
    bans = data.get('hardware_bans', [])
    recent = sorted(fps.items(), key=lambda x: x[1].get('collected_at', ''), reverse=True)[:50]
    return jsonify({
        "ok": True,
        "total_fingerprints": len(fps),
        "total_bans": len(bans),
        "recent": [{"key": k, "ip": v.get("ip"), "device_hash": v.get("device_hash"), "gpu": v.get("gpu_renderer"), "no_js": v.get("no_js", False), "collected_at": v.get("collected_at")} for k, v in recent]
    })

def cleanup_old_fingerprints():
    try:
        data = _load_bot_data()
        fps = data.get('fingerprints', {})
        if not fps:
            return
        now = datetime.utcnow()
        cutoff = (now - timedelta(days=90)).isoformat()
        cleaned = {k: v for k, v in fps.items() if v.get('collected_at', '') >= cutoff}
        removed = len(fps) - len(cleaned)
        if removed > 0:
            data['fingerprints'] = cleaned
            _save_bot_data(data)
            print(f"[HONEYPOT CLEANUP] Removed {removed} old fingerprints", flush=True)
    except Exception as e:
        print(f"[HONEYPOT CLEANUP ERROR] {e}", flush=True)

if __name__ == "__main__":
    port = 5001
    print(f"\n{'='*50}")
    print(f"  MAX BOT Dashboard")
    print(f"  Local: http://127.0.0.1:{port}")
    print(f"  Security: HARDENED")
    print(f"{'='*50}\n")
    app.run(debug=False, port=port, host='0.0.0.0', threaded=True)
