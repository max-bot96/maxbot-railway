import os
import re
import json
import time
import hashlib
import hmac
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEFAULT_LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
YOUR_USER_ID = int(os.getenv("YOUR_USER_ID", "0"))
OWNER_ID = YOUR_USER_ID
EXEMPT_ROLE_IDS = [int(x) for x in os.getenv("EXEMPT_ROLE_IDS", "").split(",") if x.strip()]
AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "0"))
TICKET_ROLE_ID = int(os.getenv("TICKET_ROLE_ID", "0"))
TICKET_MANAGER_ROLE_ID = int(os.getenv("TICKET_MANAGER_ROLE_ID", "0"))
HIGH_ROLE_ID = int(os.getenv("HIGH_ROLE_ID", "0"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
SECRET_KEY = os.getenv("SECRET_KEY", "maxbot-secret-key-change-me")
DATA_FILE = "bot_data.json"

LINK_REGEX = re.compile(r'(https?://[^\s]+|discord\.gg/[^\s]+|discord\.com/invite/[^\s]+)')

# ── Data Management �─
_data_cache = {}
_data_dirty = False
_github_sha = None

def load_data():
    global _data_cache
    if _data_cache:
        return _data_cache
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _data_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _data_cache = {}
    return _data_cache

def save_data(data=None):
    global _data_cache, _data_dirty
    if data is not None:
        _data_cache = data
    _data_dirty = False
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(_data_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[DATA] Save error: {e}", flush=True)

def mark_data_dirty():
    global _data_dirty
    _data_dirty = True

def get_from_data(key, default=None):
    data = load_data()
    return data.get(key, default)

def set_to_data(key, value):
    data = load_data()
    data[key] = value
    mark_data_dirty()

# ── GitHub Sync ──
def load_from_github():
    global _github_sha
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            content = resp.json().get("content", "")
            sha = resp.json().get("sha", "")
            decoded = base64.b64decode(content).decode("utf-8")
            data = json.loads(decoded)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            _github_sha = sha
            print(f"[GITHUB] ✅ Loaded bot_data.json ({len(decoded)} bytes)", flush=True)
            return True
        elif resp.status_code == 404:
            print("[GITHUB] ⚠️ bot_data.json not found", flush=True)
        else:
            print(f"[GITHUB] ❌ Failed: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[GITHUB] ❌ Error: {e}", flush=True)
    return False

def save_to_github():
    global _github_sha
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        payload = {"message": "Auto-save bot data", "content": base64.b64encode(content.encode()).decode()}
        if _github_sha:
            payload["sha"] = _github_sha
        resp = requests.put(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            _github_sha = resp.json().get("sha", _github_sha)
            print("[GITHUB] ✅ Saved to GitHub", flush=True)
            return True
        else:
            print(f"[GITHUB] ❌ Save failed: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[GITHUB] ❌ Save error: {e}", flush=True)
    return False

# ── URL Helpers ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TUNNEL_URL_FILE = os.path.join(BASE_DIR, "server_url2.txt")

def get_base_url():
    env_url = os.getenv("SITE_URL", "").strip()
    if env_url:
        return env_url
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        return f"https://{railway_domain}"
    try:
        with open(TUNNEL_URL_FILE, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip().splitlines()
            url = raw[0].strip() if raw else ""
            if url:
                return url
    except Exception:
        pass
    return None

# ── Security ──
def generate_honeypot_token(user_id, guild_id):
    payload = f"{user_id}:{guild_id}:{int(time.time())}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{sig}.{int(time.time())}"

def verify_honeypot_token(token, user_id, guild_id, max_age=300):
    try:
        sig, ts_str = token.split(".", 1)
        ts = int(ts_str)
        if time.time() - ts > max_age:
            return False
        payload = f"{user_id}:{guild_id}:{ts}"
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

# ── Badge Helpers ──
def get_badges_text(user):
    if not hasattr(user, 'public_flags') or not user.public_flags:
        return "No Badges"
    badges = []
    for flag in user.public_flags:
        name = flag.name.replace("_", " ").title() if hasattr(flag, 'name') else str(flag)
        badges.append(name)
    return ", ".join(badges) if badges else "No Badges"

# ── Time Helpers ──
def format_duration(seconds):
    if seconds >= 86400:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days} يوم، {hours} ساعة"
    elif seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} ساعة، {minutes} دقيقة"
    else:
        minutes = seconds // 60
        return f"{minutes} دقيقة"

def format_boost_duration(days):
    if days >= 365:
        years = days // 365
        months = (days % 365) // 30
        return f"**{years}** سنة و **{months}** شهر"
    elif days >= 30:
        months = days // 30
        remaining_days = days % 30
        return f"**{months}** شهر و **{remaining_days}** يوم"
    else:
        return f"**{days}** يوم"
