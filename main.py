import os
import io
import sys
import re
import json
import time
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
import random
import math
import asyncio
import cloudscraper
import discord
from discord.ext import commands, tasks
from discord.ui import View
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from log_service import LogColors, LogEmbed, MessageCache, send_log, cleanup_rate_limits
from protection_engine import (SpamDetector, RaidDetector, AntiNuke, PunishmentManager,
                                WhitelistManager, PROTECTION_NAMES, PUNISHMENT_CONFIG)
from message_archive import archive_message
from guild_backup import init_db as init_backup_db, save_backup, list_backups, get_backup, backup_stats, delete_backup
from ticket_characters import TICKET_CATEGORIES, get_category, generate_ai_response
from quiz import QUIZ_QUESTIONS, get_level, get_badge, save_quiz_score, get_leaderboard, load_quiz_scores
import requests
import string

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEFAULT_LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))
YOUR_USER_ID = int(os.getenv("YOUR_USER_ID"))
OWNER_ID = YOUR_USER_ID
EXEMPT_ROLE_IDS = [int(x) for x in os.getenv("EXEMPT_ROLE_IDS", "").split(",") if x.strip()]
AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "0"))
TICKET_ROLE_ID = int(os.getenv("TICKET_ROLE_ID", "0"))
TICKET_MANAGER_ROLE_ID = int(os.getenv("TICKET_MANAGER_ROLE_ID", "0"))
HIGH_ROLE_ID = int(os.getenv("HIGH_ROLE_ID", "0"))
UNLOCK_PROTECTION_ROLE_ID = 1508286557524857042
TICKET_LOG_CHANNEL_ID = 1508798210368606208
DATA_FILE = "bot_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
LINK_REGEX = re.compile(r'(https?://[^\s]+|discord\.gg/[^\s]+|discord\.com/invite/[^\s]+)')

TICKET_ROLE_ACCESS = {}

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

def generate_honeypot_token(user_id, guild_id):
    payload = f"{user_id}:{guild_id}:{int(time.time())}"
    import hashlib as _hl, hmac as _hm
    sig = _hm.new(SECRET_KEY.encode(), payload.encode(), _hl.sha256).hexdigest()[:32]
    return f"{sig}.{int(time.time())}"

def load_from_github():
    global _github_sha
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    try:
        import requests as _req
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        resp = _req.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            import base64
            content = resp.json().get("content", "")
            sha = resp.json().get("sha", "")
            decoded = base64.b64decode(content).decode("utf-8")
            data = json.loads(decoded)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            _github_sha = sha
            print(f"[GITHUB] ✅ Loaded bot_data.json from GitHub ({len(decoded)} bytes)", flush=True)
            return True
        elif resp.status_code == 404:
            print(f"[GITHUB] ⚠️ bot_data.json not found in repo — will create on first save", flush=True)
            return False
        else:
            print(f"[GITHUB] ❌ Failed to load: {resp.status_code} {resp.text[:200]}", flush=True)
            return False
    except Exception as e:
        print(f"[GITHUB] ❌ Load error: {e}", flush=True)
        return False

_github_sha = ""

def save_to_github():
    global _github_sha
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        import requests as _req
        import base64
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        payload = {"message": f"Auto-save bot_data.json ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')})", "content": encoded}
        if _github_sha:
            payload["sha"] = _github_sha
        resp = _req.put(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            _github_sha = resp.json().get("content", {}).get("sha", _github_sha)
            print(f"[GITHUB] ✅ Saved bot_data.json to GitHub", flush=True)
        else:
            print(f"[GITHUB] ❌ Save failed: {resp.status_code} {resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"[GITHUB] ❌ Save error: {e}", flush=True)

SECRET_KEY = os.getenv("HONEYPOT_SECRET", "maxbot-honeypot-secret-key-2026-change-me")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=["!", "$"], intents=intents, help_command=None, case_insensitive=True)
RESTART_COUNT = 0

_cmd_logs_buffer = []
_cmd_logs_flush_interval = 60
_last_cmd_logs_flush = time.time()

async def _flush_cmd_logs():
    """Periodically flush command logs buffer to disk"""
    global _cmd_logs_buffer, _last_cmd_logs_flush
    while not bot.is_closed():
        await asyncio.sleep(_cmd_logs_flush_interval)
        if _cmd_logs_buffer:
            await _do_flush_cmd_logs()

async def _do_flush_cmd_logs():
    global _cmd_logs_buffer, _last_cmd_logs_flush
    if not _cmd_logs_buffer:
        return
    _last_cmd_logs_flush = time.time()
    try:
        cmd_logs_file = "command_logs.json"
        logs = []
        if os.path.exists(cmd_logs_file):
            with open(cmd_logs_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.extend(_cmd_logs_buffer)
        if len(logs) > 10000:
            logs = logs[-10000:]
        _cmd_logs_buffer = []
        with open(cmd_logs_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False)
    except Exception:
        pass

@bot.before_invoke
async def track_commands(ctx):
    global command_count, command_hourly
    command_count += 1
    h = datetime.now().strftime("%Y-%m-%d %H:00")
    command_hourly[h] = command_hourly.get(h, 0) + 1

    try:
        cmd_log = {
            "command": ctx.command.name if ctx.command else "unknown",
            "user": str(ctx.author),
            "user_id": str(ctx.author.id),
            "guild": ctx.guild.name if ctx.guild else "DM",
            "guild_id": str(ctx.guild.id) if ctx.guild else "0",
            "channel": ctx.channel.name if hasattr(ctx.channel, "name") else "DM",
            "timestamp": datetime.now().isoformat(),
            "prefix": ctx.prefix or "!",
        }
        _cmd_logs_buffer.append(cmd_log)
        if len(_cmd_logs_buffer) >= 50:
            asyncio.create_task(_do_flush_cmd_logs())
    except Exception:
        pass

_processed_messages = set()
command_count = 0
command_hourly = {}
start_time = None

ticket_counter = 1
ticket_image = ""
ticket_characters_map = {}
link_blocker_enabled = {}
log_channels = {}
logged_link_messages = set()
voice_event_cache = {}
voice_audit_usage = {}
activity_tracking_enabled = {}
hacker_bait_channels = {}
hacker_bait_kicked = set()
bait_dm_cooldown = {}
HACKER_ROLE_ID = 1517202253281231028
ticket_log_channels_loaded = {}
recent_activity_logs = {}
protections = {}
role_exempt_users = {}
mod_room_channel_id = None
spam_cache = {}
bad_words_list = []
secret_users = []
message_cache = MessageCache()
spam_detector = SpamDetector()
raid_detector = RaidDetector()
anti_nuke = AntiNuke()
punishment_manager = PunishmentManager()
whitelist_manager = WhitelistManager()
competitions = {}
pending_punishments = {}
_pending_role_changes = set()

BAD_WORDS_DEFAULT = ["كس", "شرموط", "منيوك", "خرة", "عاهة", "قحبة", "عرص"]

def load_data():
    global link_blocker_enabled, log_channels, protections, bad_words_list, secret_users, mod_room_channel_id
    global welcome_config, xp_data, economy_data, suggestion_config, afk_users, afk_voice_channels, reaction_role_config, level_rewards, shop_items, custom_commands, competitions, pending_punishments
    global ticket_image, music_control_config, activity_tracking_enabled, hacker_bait_channels, ticket_log_channels_loaded, ticket_categories_data, _quiz_scores_cache, TICKET_ROLE_ACCESS, username_hunter_data
    global custom_blacklist, dynamic_blacklist, target_list, proxies_list, hardware_bans, fingerprints, used_tokens
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            link_blocker_enabled = {int(k): v for k, v in data.get("link_blocker", {}).items()}
            log_channels = {int(k): v for k, v in data.get("log_channels", {}).items()}
            protections = {int(k): v for k, v in data.get("protections", {}).items()}
            role_exempt_users = {int(k): [int(x) for x in v] for k, v in data.get("role_exempt_users", {}).items()}
            bad_words_list = data.get("bad_words", BAD_WORDS_DEFAULT)
            secret_users = data.get("secret_users", [])
            mod_room_channel_id = data.get("mod_room_channel_id")
            welcome_config = {int(k): v for k, v in data.get("welcome", {}).items()}
            xp_data = {int(k): {int(u): v for u, v in users.items()} for k, users in data.get("xp", {}).items()}
            economy_data = {int(k): {int(u): v for u, v in users.items()} for k, users in data.get("economy", {}).items()}
            suggestion_config = {int(k): v for k, v in data.get("suggestions", {}).items()}
            afk_users = {int(k): v for k, v in data.get("afk", {}).items()}
            afk_voice_channels = {int(k): v for k, v in data.get("afk_voice", {}).items()}
            reaction_role_config = {int(k): v for k, v in data.get("reaction_roles", {}).items()}
            level_rewards = {int(k): {int(l): r for l, r in rewards.items()} for k, rewards in data.get("level_rewards", {}).items()}
            shop_items = data.get("shop", SHOP_DEFAULT)
            custom_commands = {int(k): v for k, v in data.get("custom_commands", {}).items()}
            if "whitelist" in data:
                whitelist_manager.set_all(data["whitelist"])
            if "punishment_warnings" in data:
                punishment_manager.set_warnings_data(data["punishment_warnings"])
            if "anti_nuke_enabled" in data:
                anti_nuke.set_enabled_data(data["anti_nuke_enabled"])
            competitions = {int(k): v for k, v in data.get("competitions", {}).items()}
            pending_punishments = {int(k): v for k, v in data.get("pending_punishments", {}).items()}
            ticket_image = data.get("ticket_image", "")
            music_control_config = {int(k): v for k, v in data.get("music_control", {}).items()}
            music_filters.update({int(k): v for k, v in data.get("music_filters", {}).items()})
            music_autoplay.update({int(k): v for k, v in data.get("music_autoplay", {}).items()})
            activity_tracking_enabled = {int(k): v for k, v in data.get("activity_tracking", {}).items()}
            hacker_bait_channels = {int(k): v for k, v in data.get("hacker_bait_channels", {}).items()}
            hacker_bait_kicked = set(data.get("hacker_bait_kicked", []))
            ticket_log_channels_loaded = {int(k): v for k, v in data.get("ticket_log_channels", {}).items()}
            ticket_categories_data = data.get("ticket_categories", {})
            _quiz_scores_cache = data.get("quiz_scores", {})
            load_quiz_scores(_quiz_scores_cache)
            TICKET_ROLE_ACCESS = data.get("ticket_role_access", {})
            saved_hunter = data.get("username_hunter", {})
            for k, v in username_hunter_data.items():
                if k not in saved_hunter:
                    saved_hunter[k] = v
                elif isinstance(v, dict) and isinstance(saved_hunter[k], dict):
                    for sk, sv in v.items():
                        if sk not in saved_hunter[k]:
                            saved_hunter[k][sk] = sv
                        elif isinstance(sv, dict) and isinstance(saved_hunter[k][sk], dict):
                            for ssk, ssv in sv.items():
                                saved_hunter[k][sk].setdefault(ssk, ssv)
            username_hunter_data = saved_hunter
            custom_blacklist = data.get("custom_blacklist", [])
            dynamic_blacklist = data.get("dynamic_blacklist", [])
            target_list = data.get("target_list", [])
            proxies_list = data.get("proxies_list", [])
            hardware_bans = data.get("hardware_bans", [])
            fingerprints = data.get("fingerprints", {})
            used_tokens = data.get("used_tokens", [])
    except (FileNotFoundError, json.JSONDecodeError):
        link_blocker_enabled = {}
        log_channels = {}
        protections = {}
        bad_words_list = BAD_WORDS_DEFAULT
        secret_users = []
        mod_room_channel_id = None
        welcome_config = {}
        xp_data = {}
        economy_data = {}
        suggestion_config = {}
        afk_users = {}
        afk_voice_channels = {}
        reaction_role_config = {}
        level_rewards = {}
        shop_items = dict(SHOP_DEFAULT)
        custom_commands = {}
        activity_tracking_enabled = {}
        hacker_bait_channels = {}
        ticket_log_channels_loaded = {}
        ticket_categories_data = {}
        _quiz_scores_cache = {}
        custom_blacklist = []
        dynamic_blacklist = []
        target_list = []
        proxies_list = []
        hardware_bans = []
        fingerprints = {}
        used_tokens = []

_data_dirty = False
_last_save_time = 0
_SAVE_INTERVAL = 30

def mark_data_dirty():
    global _data_dirty
    _data_dirty = True

def save_data(force=False):
    global _data_dirty, _last_save_time
    _data_dirty = True
    now = time.time()
    if not force and (now - _last_save_time) < _SAVE_INTERVAL:
        return
    _do_save_data()

def _do_save_data():
    global _data_dirty, _last_save_time
    _last_save_time = time.time()
    _data_dirty = False
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "link_blocker": {str(k): v for k, v in link_blocker_enabled.items()},
            "log_channels": {str(k): v for k, v in log_channels.items()},
            "protections": {str(k): v for k, v in protections.items()},
            "role_exempt_users": {str(k): v for k, v in role_exempt_users.items()},
            "bad_words": bad_words_list,
            "secret_users": secret_users,
            "mod_room_channel_id": mod_room_channel_id,
            "welcome": {str(k): v for k, v in welcome_config.items()},
            "xp": {str(k): {str(u): v for u, v in users.items()} for k, users in xp_data.items()},
            "economy": {str(k): {str(u): v for u, v in users.items()} for k, users in economy_data.items()},
            "suggestions": {str(k): v for k, v in suggestion_config.items()},
            "afk": {str(k): v for k, v in afk_users.items()},
            "afk_voice": {str(k): v for k, v in afk_voice_channels.items()},
            "reaction_roles": {str(k): v for k, v in reaction_role_config.items()},
            "level_rewards": {str(k): {str(l): r for l, r in rewards.items()} for k, rewards in level_rewards.items()},
            "shop": shop_items,
            "custom_commands": {str(k): v for k, v in custom_commands.items()},
            "whitelist": whitelist_manager.get_all(),
            "punishment_warnings": punishment_manager.get_warnings_data(),
            "anti_nuke_enabled": anti_nuke.get_enabled_data(),
            "competitions": {str(k): v for k, v in competitions.items()},
            "pending_punishments": {str(k): v for k, v in pending_punishments.items()},
            "ticket_image": ticket_image,
            "music_control": {str(k): v for k, v in music_control_config.items()},
            "music_filters": {str(k): v for k, v in music_filters.items()},
            "music_autoplay": {str(k): v for k, v in music_autoplay.items()},
            "activity_tracking": {str(k): v for k, v in activity_tracking_enabled.items()},
            "hacker_bait_channels": {str(k): v for k, v in hacker_bait_channels.items()},
            "hacker_bait_kicked": list(hacker_bait_kicked),
            "username_hunter": username_hunter_data,
            "ticket_log_channels": {str(k): v for k, v in ticket_log_channels_loaded.items()},
            "ticket_categories": ticket_categories_data,
            "ticket_role_access": {str(k): v for k, v in TICKET_ROLE_ACCESS.items()},
            "quiz_scores": _quiz_scores_cache,
            "custom_blacklist": custom_blacklist,
            "dynamic_blacklist": dynamic_blacklist,
            "target_list": target_list,
            "proxies_list": proxies_list,
            "hardware_bans": hardware_bans,
            "fingerprints": fingerprints,
            "used_tokens": used_tokens
        }, f, ensure_ascii=False)
    save_to_github()

def is_exempt(member):
    if member.id == YOUR_USER_ID:
        return True
    if hasattr(member, 'guild') and member.guild:
        if member.guild.owner_id == member.id:
            return True
        return any(r.id in EXEMPT_ROLE_IDS for r in member.roles)
    return False

def get_prot(guild_id, key, channel_id=None):
    if not protections.get(guild_id, {}).get(key, True):
        return False
    if channel_id and whitelist_manager.is_whitelisted(guild_id, channel_id, key):
        return False
    return True

async def get_log_ch(guild_id, log_type="main"):
    config = log_channels.get(guild_id, {})
    if isinstance(config, dict):
        ch_id = config.get(log_type) or config.get("main") or DEFAULT_LOG_CHANNEL_ID
    else:
        ch_id = DEFAULT_LOG_CHANNEL_ID
    if ch_id:
        ch = bot.get_channel(int(ch_id))
        if ch:
            return ch
    return None

async def get_admin(guild, action_type, target_id):
    try:
        async for entry in guild.audit_logs(limit=5, action=action_type):
            if entry.target and entry.target.id == target_id:
                return entry.user
    except discord.Forbidden:
        print(f"[PERMISSIONS ERROR] Turn on 'View Audit Log' for the bot in server: {guild.name}")
    except Exception as e:
        print(f"Unexpected error fetching audit logs: {e}")
    return None

async def safe_send(ch, embed, view=None):
    if not ch:
        return
    try:
        if view:
            await ch.send(embed=embed, view=view)
        else:
            await ch.send(embed=embed)
    except discord.Forbidden:
        print(f"[ACCESS ERROR] Grant the bot 'View Channel', 'Send Messages', and 'Embed Links' in #{ch.name}")
    except Exception as e:
        print(f"Unexpected error sending message: {e}")

async def find_voice_move_admin(guild, before_id, after_id, event_time):
    for _ in range(8):
        try:
            async for entry in guild.audit_logs(limit=20, action=discord.AuditLogAction.member_move):
                delta = (entry.created_at - event_time).total_seconds()
                if delta < -10 or delta > 20:
                    continue

                count = int(getattr(getattr(entry, "extra", None), "count", 1) or 1)
                used_count = voice_audit_usage.get(entry.id, 0)
                if used_count >= count:
                    continue

                moved_to = getattr(getattr(entry, "extra", None), "channel", None)
                moved_to_id = getattr(moved_to, "id", None)
                if moved_to_id in (before_id, after_id):
                    voice_audit_usage[entry.id] = used_count + 1
                    return entry.user
        except discord.Forbidden:
            return "غير معروف (يفتقد البوت لصلاحية View Audit Log)"
        except Exception as e:
            print(f"Unexpected error checking voice move audit logs: {e}")

        await asyncio.sleep(0.75)

    return None

@bot.event
async def on_ready():
    global start_time, RESTART_COUNT
    RESTART_COUNT += 1
    start_time = datetime.now()
    print(f'--- [ MAX BOT Online ] ---', flush=True)
    print(f'Connected as: {bot.user.name}', flush=True)
    print(f'Restart #{RESTART_COUNT}', flush=True)
    load_from_github()
    load_data()
    print(f'[BAIT] hacker_bait_channels loaded: {hacker_bait_channels}', flush=True)
    print(f'[BAIT] YOUR_USER_ID = {YOUR_USER_ID}', flush=True)
    bot.add_view(TicketView())
    bot.add_view(TicketActions())
    bot.add_view(CompetitionView())
    bot.add_view(PunishmentReviewView())
    bot.add_view(UsernameHunterView())
    try:
        bot.add_view(HackerInvestigateView(
            hacker_id=0, hacker_name="", message_content="", guild_id=0,
            invite_link="", account_age=0, joined_ts=0, created_ts=0,
            severity_label="", url_analyses=[], roles_text="", is_booster=False, is_bot_acc=False
        ))
    except Exception as e:
        print(f"[STARTUP] HackerInvestigateView add_view: {e}", flush=True)
    bot.loop.create_task(update_stats())
    bot.loop.create_task(check_dashboard_commands())
    bot.loop.create_task(daily_report())
    bot.loop.create_task(_periodic_save())
    bot.loop.create_task(_flush_cmd_logs())
    bot.loop.create_task(_ensure_ollama())
    print("Ready - starting heavy init in background", flush=True)
    bot.loop.create_task(_after_ready())


async def _periodic_save():
    """Periodically save data to disk if dirty"""
    while not bot.is_closed():
        await asyncio.sleep(_SAVE_INTERVAL)
        if _data_dirty:
            _do_save_data()
            print("[AUTO-SAVE] Saved bot_data.json")
    # Final save on close
    if _data_dirty:
        _do_save_data()
        print("[FINAL-SAVE] Saved bot_data.json on shutdown")

async def _ensure_ollama():
    import subprocess, shutil
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        for p in [r"C:\Users\USER\AppData\Local\Programs\Ollama\ollama.exe", r"C:\Program Files\Ollama\ollama.exe"]:
            if os.path.exists(p):
                ollama_path = p
                break
    if not ollama_path:
        print("[OLLAMA] Not found - AI responses will use fallback", flush=True)
        return
    try:
        proc = subprocess.Popen([ollama_path, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"[OLLAMA] Server started (PID {proc.pid})", flush=True)
        await asyncio.sleep(3)
        import httpx
        with httpx.Client(timeout=5) as c:
            r = c.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"[OLLAMA] Available models: {models}", flush=True)
    except Exception as e:
        print(f"[OLLAMA] Startup error: {e}", flush=True)

async def _after_ready():
    global TICKET_LOG_CHANNEL_ID, TICKET_ROLE_ACCESS
    try:
        from message_archive import setup as archive_setup
        await archive_setup(bot)
    except Exception as e:
        print(f"[ARCHIVE SETUP ERROR] {e}", flush=True)
    init_backup_db()

    # TICKET_ROLE_ACCESS already loaded in load_data()
    print(f"[TICKET] Loaded ticket_role_access for {len(TICKET_ROLE_ACCESS)} guilds", flush=True)

    for guild in bot.guilds:
        saved_tkt_log_id = ticket_log_channels_loaded.get(guild.id)
        if saved_tkt_log_id:
            ch = guild.get_channel(saved_tkt_log_id)
            if ch:
                TICKET_LOG_CHANNEL_ID = saved_tkt_log_id
                print(f"[TICKET LOG] Loaded LOG-تكت: {ch.name} ({ch.id}) for {guild.name}", flush=True)

    for guild in bot.guilds:
        vc_id = afk_voice_channels.get(guild.id)
        if vc_id:
            ch = guild.get_channel(vc_id)
            if ch and isinstance(ch, discord.VoiceChannel):
                try:
                    if not (guild.me.voice and guild.me.voice.channel):
                        await ch.connect()
                except:
                    pass
    for g in bot.guilds:
        try:
            await bot.tree.sync(guild=g)
        except:
            pass
    try:
        export_commands_to_json()
    except Exception as e:
        print(f"[EXPORT COMMANDS ERROR] {e}", flush=True)
    renamed_total = 0
    topics_updated = 0
    for guild in bot.guilds:
        config = log_channels.get(guild.id)
        if not config:
            continue
        for key, new_name in LOG_CHANNEL_NAMES.items():
            ch_id = config.get(key)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    if ch.name != new_name:
                        try:
                            await ch.edit(name=new_name)
                            renamed_total += 1
                            await asyncio.sleep(0.3)
                        except:
                            pass
                    new_topic = LOG_CHANNEL_TOPICS.get(key)
                    if new_topic and ch.topic != new_topic:
                        try:
                            await ch.edit(topic=new_topic)
                            topics_updated += 1
                            await asyncio.sleep(0.3)
                        except:
                            pass
    if renamed_total:
        print(f"[AUTO-RENAME] Renamed {renamed_total} log channels to new format")
    if topics_updated:
        print(f"[AUTO-TOPIC] Updated {topics_updated} log channel topics")

    # Start username hunter task if it was active
    if username_hunter_data.get("active") and username_hunter_data.get("channel_id"):
        try:
            username_hunter_task.start()
            print(f"[HUNTER] Username hunter task started (channel: {username_hunter_data['channel_id']})", flush=True)
        except Exception as e:
            print(f"[HUNTER] Could not start task: {e}", flush=True)

async def send_error_to_owner(error_name, error_msg, ctx_str="", guild_str="", user_str=""):
    try:
        owner = bot.get_user(YOUR_USER_ID)
        if not owner:
            owner = await bot.fetch_user(YOUR_USER_ID)
        dm = await owner.create_dm()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        embed = discord.Embed(
            title="❌ خطأ في البوت!",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        fields = [
            ("📋 الخطأ", f"`{error_name}`", False),
            ("💬 التفاصيل", f"```{str(error_msg)[:900]}```", False),
        ]
        if ctx_str:
            fields.append(("📍 السياق", ctx_str, False))
        if guild_str:
            fields.append(("🌐 السيرفر", guild_str, False))
        if user_str:
            fields.append(("👤 المستخدم", user_str, False))
        fields.append(("⏰ الوقت", now, False))
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
        embed.set_footer(text="MAX BOT — Error Report")
        await dm.send(embed=embed)
    except Exception as e:
        print(f"[ERROR DM] Failed to send error DM: {e}", flush=True)

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    try:
        print(f"TREE ERROR: {type(error).__name__}: {error}")
        msg = f"❌ {error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        ctx_str = f"الأمر: /{interaction.command.name if interaction.command else 'غير معروف'}"
        guild_str = f"{interaction.guild.name} ({interaction.guild.id})" if interaction.guild else "DM"
        user_str = f"{interaction.user} ({interaction.user.id})"
        await send_error_to_owner(type(error).__name__, error, ctx_str, guild_str, user_str)
    except Exception as e:
        print(f"TREE ERROR HANDLER FAILED: {e}")

@bot.event
async def on_error(event_name, *args, **kwargs):
    import traceback as tb_mod
    err = tb_mod.format_exc()
    try:
        ctx_str = f"Event: {event_name}"
        guild_str = ""
        user_str = ""
        if args:
            first = args[0]
            if hasattr(first, 'guild'):
                guild_str = f"{first.guild.name} ({first.guild.id})" if first.guild else "DM"
            if hasattr(first, 'author'):
                user_str = f"{first.author} ({first.author.id})"
            elif hasattr(first, 'user'):
                user_str = f"{first.user} ({first.user.id})"
        await send_error_to_owner(f"Event: {event_name}", err, ctx_str, guild_str, user_str)
    except Exception as e:
        print(f"[ERROR DM] Failed in on_error: {e}", flush=True)

@bot.event
async def on_command_error(ctx, error):
    try:
        print(f"CMD ERROR: {type(error).__name__}: {error}")

        if isinstance(error, commands.CommandNotFound):
            _dash_url = "https://web-production-f6fb8.up.railway.app"
            try:
                with open(os.path.join(BASE_DIR, "server_url2.txt"), "r", encoding="utf-8-sig") as _f:
                    _dash_url = _f.read().strip().splitlines()[0]
            except Exception:
                pass
            embed = discord.Embed(
                title="❌ الأمر غير موجود",
                description="هذا الأمر غير موجود في البوت!",
                color=0xE74C3C
            )
            embed.add_field(
                name="📞 للتواصل مع الدعم الفني",
                value=(
                    f"📧 الإيميل: `MaxoptSupportTeam@gmail.com`\n"
                    f"🌐 الموقع: {_dash_url}\n"
                    f"💬 Telegram: https://t.me/maxpot_0\n"
                    f"📢 قروب التحديثات: https://t.me/maxpot_0"
                ),
                inline=False
            )
            embed.set_footer(text="MAX BOT • الدعم الفني")
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
            elif ctx.message:
                await ctx.send(embed=embed)
            return

        if isinstance(error, commands.MissingRequiredArgument):
            _dash_url = "https://web-production-f6fb8.up.railway.app"
            try:
                with open(os.path.join(BASE_DIR, "server_url2.txt"), "r", encoding="utf-8-sig") as _f:
                    _dash_url = _f.read().strip().splitlines()[0]
            except Exception:
                pass
            param_name = error.param.name if error.param else "غير معروف"
            embed = discord.Embed(
                title="❌ ناقص بيانات",
                description=f"الأمر **`{ctx.command.name}`** يحتاج بيانات ناقصة!\n**المطلوب:** `{param_name}`",
                color=0xE74C3C
            )
            usage = ctx.command.usage or ""
            if ctx.command.help:
                embed.add_field(name="💡 طريقة الاستخدام", value=f"`{ctx.prefix}{ctx.command.name} {ctx.command.help}`", inline=False)
            elif usage:
                embed.add_field(name="💡 طريقة الاستخدام", value=f"`{ctx.prefix}{ctx.command.name} {usage}`", inline=False)
            else:
                sig = str(ctx.command.signature) if ctx.command.signature else ""
                if sig:
                    embed.add_field(name="💡 طريقة الاستخدام", value=f"`{ctx.prefix}{ctx.command.name} {sig}`", inline=False)
            embed.add_field(
                name="📞 للتواصل مع الدعم الفني",
                value=(
                    f"📧 الإيميل: `MaxoptSupportTeam@gmail.com`\n"
                    f"🌐 الموقع: {_dash_url}\n"
                    f"💬 Telegram: https://t.me/maxpot_0"
                ),
                inline=False
            )
            embed.set_footer(text="MAX BOT • الدعم الفني")
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
            elif ctx.message:
                await ctx.send(embed=embed)
            return

        if isinstance(error, commands.BadArgument):
            _dash_url = "https://web-production-f6fb8.up.railway.app"
            try:
                with open(os.path.join(BASE_DIR, "server_url2.txt"), "r", encoding="utf-8-sig") as _f:
                    _dash_url = _f.read().strip().splitlines()[0]
            except Exception:
                pass
            embed = discord.Embed(
                title="❌ بيانات غير صحيحة",
                description=f"الأمر **`{ctx.command.name}`** تلقى بيانات غير صحيحة!",
                color=0xE74C3C
            )
            embed.add_field(
                name="📞 للتواصل مع الدعم الفني",
                value=(
                    f"📧 الإيميل: `MaxoptSupportTeam@gmail.com`\n"
                    f"🌐 الموقع: {_dash_url}\n"
                    f"💬 Telegram: https://t.me/maxpot_0"
                ),
                inline=False
            )
            embed.set_footer(text="MAX BOT • الدعم الفني")
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
            elif ctx.message:
                await ctx.send(embed=embed)
            return

        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title="❌ صلاحية مفقودة",
                description=f"أنت لا تملك الصلاحية المطلوبة: **{missing}**",
                color=0xE74C3C
            )
            embed.set_footer(text="MAX BOT • الحماية")
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
            elif ctx.message:
                await ctx.send(embed=embed)
            return

        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title="❌ البوت ينقصه صلاحية",
                description=f"البوت يحتاج الصلاحية: **{missing}**\nتواصل مع الإدارة.",
                color=0xE74C3C
            )
            embed.set_footer(text="MAX BOT • الحماية")
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
            elif ctx.message:
                await ctx.send(embed=embed)
            return

        msg = f"❌ {error}"
        if ctx.interaction:
            if ctx.interaction.response.is_done():
                await ctx.interaction.followup.send(msg, ephemeral=True)
            else:
                await ctx.interaction.response.send_message(msg, ephemeral=True)
        elif ctx.message:
            await ctx.send(msg)
        cmd_name = ctx.command.name if ctx.command else "غير معروف"
        ctx_str = f"الأمر: {ctx.prefix}{cmd_name}"
        guild_str = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "DM"
        user_str = f"{ctx.author} ({ctx.author.id})"
        await send_error_to_owner(type(error).__name__, error, ctx_str, guild_str, user_str)
    except Exception as e:
        print(f"ERROR HANDLER FAILED: {e}")

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    guild_id = before.guild.id if before.guild else None
    if not guild_id:
        return

    cached = message_cache.get(guild_id, before.id)
    old_content = cached["content"] if cached else (before.content or "فارغ")

    b_content = old_content if cached else (before.content or "فارغ")
    a_content = after.content or "فارغ"

    embed = LogEmbed.base("📝 تعديل رسالة", LogColors.EDIT, guild=before.guild)
    LogEmbed.user_field(embed, before.author, "المرسل")
    LogEmbed.channel_field(embed, "القناة", before.channel)
    msg_age = discord.utils.utcnow() - before.created_at
    m_days = msg_age.days
    m_hours, m_rem = divmod(msg_age.seconds, 3600)
    m_min, _ = divmod(m_rem, 60)
    if m_days > 0:
        age_str = f"{m_days} يوم، {m_hours} ساعة"
    elif m_hours > 0:
        age_str = f"{m_hours} ساعة، {m_min} دقيقة"
    else:
        age_str = f"{m_min} دقيقة"
    embed.add_field(name="⏱️ عمر الرسالة", value=age_str, inline=True)
    if before.edited_at:
        edit_age = discord.utils.utcnow() - before.edited_at
        e_min, e_sec = divmod(edit_age.seconds, 60)
        embed.add_field(name="🔄 عدد التعديلات", value=f"عُدّت قبل {e_min} دقيقة", inline=True)
    LogEmbed.diff_field(embed, "التغيير", b_content[:500], a_content[:500])
    if cached:
        LogEmbed.evidence_field(embed, message_data=cached)
    else:
        embed.add_field(name="الرابط", value=f"[قفز للرسالة]({after.jump_url})", inline=False)
    await send_log(guild_id, "log_messages", embed)

async def send_punishment_review(guild, user, prot_type, score, detail=""):
    """ترسل رسالة مراجعة عقاب لروم الحماية وتخزن العقاب المعلق"""
    action_info = punishment_manager.get_punishment_action(prot_type, score)
    if not action_info:
        return
    config = PUNISHMENT_CONFIG.get(prot_type, PUNISHMENT_CONFIG["spam"])
    prot_name = config.get("name", prot_type)

    embed = LogEmbed.base("🛡️ مراجعة عقاب", LogColors.PROTECT, guild=guild)
    LogEmbed.user_field(embed, user, "المخالف", thumb=True)
    embed.add_field(name="المخالفة", value=prot_name, inline=True)
    embed.add_field(name="العقاب المقترح", value=action_info["label"], inline=True)
    if detail:
        embed.add_field(name="التفاصيل", value=detail, inline=False)

    config = log_channels.get(guild.id, {})
    mapped_type = LOG_CHANNEL_MAP.get("protection_security", "log_admin")
    ch_id = config.get(mapped_type) or config.get("protection_security") or config.get("main") or DEFAULT_LOG_CHANNEL_ID
    ch = bot.get_channel(int(ch_id)) if ch_id else None
    if not ch:
        return
    msg = await ch.send(embed=embed, view=PunishmentReviewView())
    pending_punishments[msg.id] = {
        "guild_id": guild.id,
        "user_id": user.id,
        "user_name": str(user),
        "prot_type": prot_type,
        "prot_name": prot_name,
        "action": action_info["action"],
        "duration": action_info.get("duration", 0),
        "label": action_info["label"],
        "score": score,
    }
    save_data()

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")
    if custom_id.startswith("hunter_simplify_"):
        username = custom_id.replace("hunter_simplify_", "")
        embed = discord.Embed(
            title=f"🔍 تبسيط `{username}`",
            description=f"**اليوزر الأصلي:** `{username}`\n\n🔄 جاري البحث عن بدائل مبسطة...",
            color=0x5865F2
        )
        simplified = []
        if "." in username:
            simplified.append(username.replace(".", ""))
        if "_" in username:
            simplified.append(username.replace("_", ""))
        if len(username) >= 4:
            simplified.append(username[:3])
            simplified.append(username[-3:])
        if simplified:
            embed.add_field(name="💡 بدائل مقترحة", value="\n".join(f"`{s}`" for s in simplified[:5]), inline=False)
        embed.set_footer(text="MAX BOT • صيد اليوزرات")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    elif custom_id.startswith("hunter_verify_"):
        username = custom_id.replace("hunter_verify_", "")
        embed = discord.Embed(
            title=f"✅ التحقق من `{username}`",
            description=f"🔄 جاري إعادة التحقق من توفر `{username}`...\n\n⚠️ قد يستغرق هذا بضع ثوانٍ",
            color=0x2ECC71
        )
        embed.set_footer(text="MAX BOT • صيد اليوزرات")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        try:
            available = check_availability(username, "discord")
            if available:
                result_embed = discord.Embed(
                    title=f"✅ `{username}` متاح!",
                    description=f"**اليوزر:** `{username}`\n**الحالة:** ✅ لا يزال متاحاً للحجز",
                    color=0x2ECC71
                )
            else:
                result_embed = discord.Embed(
                    title=f"❌ `{username}` غير متاح",
                    description=f"**اليوزر:** `{username}`\n**الحالة:** ❌ غير متاح (تم حجزه)",
                    color=0xE74C3C
                )
            result_embed.set_footer(text="MAX BOT • صيد اليوزرات")
            await interaction.followup.send(embed=result_embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في التحقق: {e}", ephemeral=True)

def analyze_url(text):
    urls = re.findall(r'https?://[^\s<>"]+', text)
    if not urls:
        return []
    results = []
    for url in urls:
        url_lower = url.lower()
        if any(k in url_lower for k in ["canary", "webhook", "grabber", "logger", "ipinfo", "iplogger", "whatismyip"]):
            verdict = "🔴 IP Logger / Token Grabber"
        elif any(k in url_lower for k in ["nitro", "free-nitro", "gift", "airdrop", "claim", "steam", "cs2", "csgo"]):
            verdict = "🟠 Phishing (سرقة حسابات)"
        elif any(k in url_lower for k in [".exe", ".apk", ".bat", ".cmd", ".ps1", "download", "install", "malware"]):
            verdict = "🔴 Malware / برمجية خبيثة"
        elif any(k in url_lower for k in ["discord", "gg/", "discord.gg", "discord.com", "discordapp"]):
            verdict = "🟡 رابط ديسكورد مشبوه"
        elif any(k in url_lower for k in ["tiktok", "instagram", "youtube", "twitter"]):
            verdict = "🟡 رابط منصة مشبوه"
        else:
            verdict = "🟡 رابط خارجي مشبوه"
        results.append({"url": url, "verdict": verdict})
    return results

def get_severity(account_age, url_analyses):
    has_phishing = any("Phishing" in u["verdict"] for u in url_analyses)
    has_malware = any("Malware" in u["verdict"] or "IP Logger" in u["verdict"] for u in url_analyses)
    if has_malware or (has_phishing and account_age < 30):
        return 0xE74C3C, "🔴 حساب وهمي / خبيث"
    elif has_phishing or account_age < 7:
        return 0xE67E22, "🟠 حساب مشبوه جداً"
    elif account_age < 30:
        return 0xF1C40F, "🟡 حساب جديد مشبوه"
    else:
        return 0x2ECC71, "🟢 حساب قد يكون مخترق"

def get_hacked_accounts_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d.get("hacked_accounts", {})
    except:
        pass
    return {}

def save_hacked_account(user_id, guild_id, hacker_name, link, severity_label):
    try:
        d = {}
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        hacked = d.setdefault("hacked_accounts", {})
        key = str(user_id)
        entries = hacked.setdefault(key, [])
        entries.append({
            "guild_id": guild_id,
            "name": hacker_name,
            "link": link,
            "severity": severity_label,
            "timestamp": int(discord.utils.utcnow().timestamp()),
        })
        if len(entries) > 10:
            hacked[key] = entries[-10:]
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        print(f"[BAIT] save_hacked_account error: {e}", flush=True)

def get_attack_methods(text):
    methods = []
    text_lower = text.lower()
    if any(k in text_lower for k in ["free", "nitro", "boost"]):
        methods.append("Discord Nitro Scam")
    if any(k in text_lower for k in ["steam", "cs2", "csgo", "skins"]):
        methods.append("Steam Scam")
    if any(k in text_lower for k in ["airdrop", "crypto", "wallet"]):
        methods.append("Crypto Airdrop Scam")
    if re.search(r'https?://', text):
        methods.append("رابط خارجي")
    if text.count("http") > 1:
        methods.append("سبام (روابط متعددة)")
    if not methods:
        methods.append("رابط غير مصنف")
    return methods

class HackerInvestigateView(discord.ui.View):
    def __init__(self, hacker_id, hacker_name, message_content, guild_id, invite_link, account_age, joined_ts, created_ts, severity_label, url_analyses, roles_text, is_booster, is_bot_acc):
        super().__init__(timeout=None)
        self.hacker_id = hacker_id
        self.hacker_name = hacker_name
        self.message_content = message_content
        self.guild_id = guild_id
        self.invite_link = invite_link
        self.account_age = account_age
        self.joined_ts = joined_ts
        self.created_ts = created_ts
        self.severity_label = severity_label
        self.url_analyses = url_analyses
        self.roles_text = roles_text
        self.is_booster = is_booster
        self.is_bot_acc = is_bot_acc

    @discord.ui.button(label="🔍 تحقق", style=discord.ButtonStyle.danger, emoji="🔍", custom_id="bait_investigate")
    async def investigate(self, interaction, button):
        await interaction.response.defer()
        try:
            results = []
            score = 0
            max_score = 10

            member = None
            guild = bot.get_guild(self.guild_id)
            if guild:
                member = guild.get_member(self.hacker_id)

            analysis_1 = ""
            if self.account_age < 7:
                analysis_1 = "🔴 حساب جديد جداً (أقل من أسبوع) — احتمال وهمي كبير"
                score += 2
            elif self.account_age < 30:
                analysis_1 = "🟠 حساب جديد (أقل من شهر) — مشبوه"
                score += 1
            elif self.account_age < 180:
                analysis_1 = "🟡 حساب متوسط — قد يكون عادي"
            else:
                analysis_1 = "🟢 حساب قديم (أكثر من 6 شهور) — لا يشبه الوهمي"
            results.append(f"📋 **فحص 1: عمر الحساب** ({self.account_age} يوم)\n  {analysis_1}")

            analysis_2 = ""
            if self.joined_ts:
                days_since_join = (discord.utils.utcnow().timestamp() - self.joined_ts) / 86400
                if days_since_join < 1:
                    analysis_2 = "🔴 انضم اليوم — مشبوه جداً"
                    score += 1
                elif days_since_join < 7:
                    analysis_2 = "🟠 انضم خلال أسبوع — ممكن حديث"
                else:
                    analysis_2 = "🟢 انضم منذ فترة — طبيعي"
            else:
                analysis_2 = "⚪ لا يمكن تحديد تاريخ الانضمام"
            results.append(f"📋 **فحص 2: تاريخ الانضمام**\n  {analysis_2}")

            analysis_3 = ""
            if self.url_analyses:
                for u in self.url_analyses:
                    v = u["verdict"]
                    if "IP Logger" in v or "Grabber" in v:
                        analysis_3 += f"  🔴 `{u['url'][:50]}` — {v}\n"
                        score += 2
                    elif "Phishing" in v:
                        analysis_3 += f"  🟠 `{u['url'][:50]}` — {v}\n"
                        score += 1
                    elif "Malware" in v:
                        analysis_3 += f"  🔴 `{u['url'][:50]}` — {v}\n"
                        score += 2
                    else:
                        analysis_3 += f"  🟡 `{u['url'][:50]}` — {v}\n"
            else:
                analysis_3 = "  🟢 لا توجد روابط مشبوهة في المحتوى"
            results.append(f"📋 **فحص 3: تحليل الرابط**\n{analysis_3}")

            analysis_4 = ""
            if member:
                roles = [r.name for r in member.roles if r != guild.default_role]
                if any(r.permissions.administrator or r.permissions.manage_guild for r in member.roles if r != guild.default_role):
                    analysis_4 = "🔴 يملك صلاحيات إدارية! خطر"
                    score += 2
                elif any(r.permissions.ban_members or r.permissions.kick_members for r in member.roles if r != guild.default_role):
                    analysis_4 = "🟠 يملك صلاحيات طرد/حظر — مشبوه"
                    score += 1
                elif roles:
                    analysis_4 = f"🟢 رتب عادية: {', '.join(roles[:5])}"
                else:
                    analysis_4 = "🟢 بدون رتب إضافية"
            else:
                analysis_4 = "🔴 تمطرد بالفعل — لا يمكن فحص الرتب الحالية"
            results.append(f"📋 **فحص 4: الرتب والصلاحيات**\n  {analysis_4}")

            analysis_5 = ""
            if member:
                perms = [p[0] for p in member.guild_permissions if p[1]]
                dangerous = [p for p in perms if p in ["administrator", "manage_guild", "ban_members", "kick_members", "manage_channels", "manage_roles", "manage_webhooks"]]
                if dangerous:
                    analysis_5 = f"🔴 صلاحيات خطرة: {', '.join(dangerous)}"
                    score += 2
                else:
                    analysis_5 = "🟢 لا يملك صلاحيات إدارية"
            else:
                analysis_5 = "⚪ غير قابل للفحص (تمطرد)"
            results.append(f"📋 **فحص 5: الصلاحيات**\n  {analysis_5}")

            analysis_6 = ""
            prev = get_hacked_accounts_data().get(str(self.hacker_id), [])
            if len(prev) > 0:
                analysis_6 = f"🔴 تم القبض عليه **{len(prev)} مرة من قبل!**\n"
                for e in prev[-3:]:
                    analysis_6 += f"  • <t:{e.get('timestamp', 0)}:R> — {e.get('link', '?')[:40]}\n"
                score += min(len(prev), 3)
            else:
                analysis_6 = "🟢 لم يُقبض عليه من قبل"
            results.append(f"📋 **فحص 6: الحسابات المكررة**\n  {analysis_6}")

            analysis_7 = "🔴 حساب بوت — لا يُسمح بالبوتات بدون توثيق" if self.is_bot_acc else "🟢 حساب عادي (ليس بوت)"
            if self.is_bot_acc:
                score += 1
            results.append(f"📋 **فحص 7: نوع الحساب**\n  {analysis_7}")

            analysis_8 = ""
            fingerprint_data = {}
            is_banned = False
            device_hash = ""
            try:
                _d3 = {}
                if os.path.exists(DATA_FILE):
                    with open(DATA_FILE, "r", encoding="utf-8") as _f3:
                        _d3 = json.load(_f3)
                fp_key = f"{self.guild_id}_{self.hacker_id}"
                fingerprint_data = _d3.get("fingerprints", {}).get(fp_key, {})
                device_hash = fingerprint_data.get("device_hash", "")
                hardware_bans = _d3.get("hardware_bans", [])
                is_banned = device_hash in hardware_bans if device_hash else False
            except:
                pass
            if is_banned:
                analysis_8 = f"🔴 الجهاز محظور بالفعل! Device Hash: `{device_hash[:16]}`"
                score += 3
            elif fingerprint_data:
                analysis_8 = f"🟢 الجهاز غير محظور\n  Device Hash: `{device_hash[:16]}`"
            else:
                analysis_8 = "⏳ لم يزر صفحة التحقق — لا توجد بيانات بصمة"
            results.append(f"📋 **فحص 8: Hardware Ban**\n  {analysis_8}")

            analysis_9 = ""
            if fingerprint_data and device_hash:
                _d4 = {}
                try:
                    if os.path.exists(DATA_FILE):
                        with open(DATA_FILE, "r", encoding="utf-8") as _f4:
                            _d4 = json.load(_f4)
                    all_fps = _d4.get("fingerprints", {})
                    matching = [k for k, v in all_fps.items() if v.get("device_hash") == device_hash and k != f"{self.guild_id}_{self.hacker_id}"]
                    if matching:
                        analysis_9 = f"🔴 نفس البصمة تُستخدم في **{len(matching)} حساب آخر!**"
                        score += 2
                    else:
                        analysis_9 = "🟢 بصمة فريدة — لا توجد حسابات مشتركة"
                except:
                    analysis_9 = "⚪ خطأ في الفحص"
            else:
                analysis_9 = "⏳ لا توجد بيانات كافية"
            results.append(f"📋 **فحص 9: Device Hash**\n  {analysis_9}")

            analysis_10 = ""
            if self.is_booster:
                analysis_10 = "🟢 يboost السيرفر — حساب فعلي"
            elif self.account_age > 365 and not is_banned:
                analysis_10 = "🟢 حساب قديم + غير محظور — قد يكون مخترق (حساب حقيقي)"
            elif self.account_age < 7 and ("phishing" in self.severity_label.lower() or score >= 5):
                analysis_10 = "🔴 حساب وهمي + phishing — صيد حسابات"
            elif score >= 5:
                analysis_10 = "🔴 تقييم عالي الخطورة — اجراءات وهمية"
            else:
                analysis_10 = "🟡 مشبوه — يحتاج مراقبة"
            results.append(f"📋 **فحص 10: التقييم النهائي**\n  {analysis_10}")

            final_color = 0xE74C3C if score >= 6 else 0xE67E22 if score >= 4 else 0xF1C40F if score >= 2 else 0x2ECC71

            embed = discord.Embed(
                title=f"🔍 تحليل شامل — {self.hacker_name}",
                description=f"**📊 نتيجة الفحص:** {score}/{max_score} (كلما زاد، زادت الخطورة)\n\n" + "\n\n".join(results),
                color=final_color,
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="MAX BOT • تحليل الهاكرز 🔎")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في التحليل: {e}", ephemeral=True)

    @discord.ui.button(label="📩 دعوة", style=discord.ButtonStyle.success, emoji="📩", custom_id="bait_invite")
    async def invite_back(self, interaction, button):
        await interaction.response.defer()
        try:
            user = await bot.fetch_user(self.hacker_id)
            link = self.invite_link
            if not link:
                guild = bot.get_guild(self.guild_id)
                if guild:
                    ch = guild.system_channel or guild.text_channels[0]
                    inv = await ch.create_invite(max_age=86400, max_uses=1, reason="Bait invite back")
                    link = inv.url
            if link:
                await user.send(f"📩 **تم إرسال لك دعوة للعودة للسيرفر:**\n{link}\n\n**⚠️ يرجى عدم نشر روابط مشبوهة مجدداً.**")
                await interaction.followup.send(f"✅ تم إرسال الدعوة لـ `{self.hacker_name}`", ephemeral=True)
            else:
                await interaction.followup.send("❌ فشل إنشاء الرابط", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ خاص الهاكر مغلق — لا يمكن إرسال الدعوة", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)

    @discord.ui.button(label="🗑️ مسح", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="bait_clear")
    async def delete_msg(self, interaction, button):
        try:
            await interaction.message.delete()
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)

    @discord.ui.button(label="👤 معلومات الشخص", style=discord.ButtonStyle.primary, emoji="👤", custom_id="bait_fullinfo")
    async def full_info(self, interaction, button):
        await interaction.response.defer()
        try:
            user = await bot.fetch_user(self.hacker_id)
            guild = bot.get_guild(self.guild_id)
            member = guild.get_member(self.hacker_id) if guild else None

            embed = discord.Embed(
                title=f"👤 معلومات كاملة — {user}",
                color=0x3498DB,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            created_ts = int(user.created_at.timestamp())
            embed.add_field(
                name="📋 معلومات الحساب",
                value=(
                    f"├─ المعرف: `{user.id}`\n"
                    f"├─ الاسم: `{user}`\n"
                    f"├─ الاسم الأصلي: `{user.name}`\n"
                    f"├─ تاريخ الإنشاء: <t:{created_ts}:F> (<t:{created_ts}:R>)\n"
                    f"├─ عمر الحساب: **{self.account_age}** يوم\n"
                    f"├─ بوت؟ {'نعم 🤖' if user.bot else 'لا'}\n"
                    f"└─ بوست؟ {'نعم 💎' if member and member.premium_since else 'لا'}"
                ),
                inline=False
            )

            if member:
                nickname = member.nick or "لا يوجد"
                top_role = member.top_role.name if member.top_role != guild.default_role else "لا يوجد"
                roles_list = [r.name for r in member.roles if r != guild.default_role]
                roles_count = len(roles_list)
                roles_text = " • ".join(roles_list[:20])
                if roles_count > 20:
                    roles_text += f" +{roles_count - 20} أخرى"

                status_map = {
                    discord.Status.online: "🟢 متصل",
                    discord.Status.idle: "🌙 خامل",
                    discord.Status.dnd: "🔴 لا تزعج",
                    discord.Status.offline: "⚫ غير متصل",
                }
                status = status_map.get(member.status, "⚫ غير معروف")

                devices = []
                if member.mobile:
                    devices.append("📱 جوال")
                if member.desktop:
                    devices.append("🖥️ كمبيوتر")
                if member.web_client:
                    devices.append("🌐 متصفح")
                devices_str = " • ".join(devices) if devices else "غير معروف"

                custom_status = "لا يوجد"
                for act in member.activities:
                    if act.type == discord.ActivityType.custom and act.state:
                        custom_status = act.state
                        break

                permissions = [p[0] for p in member.guild_permissions if p[1]]
                perms_str = " • ".join(permissions[:15])
                if len(permissions) > 15:
                    perms_str += f" +{len(permissions) - 15} أخرى"

                badges = []
                try:
                    flags = user.public_flags
                    if flags.verified_bot_developer:
                        badges.append("🔧 مطور موثوق")
                    if flags.discord_certified_moderator:
                        badges.append("🛡️ مoderator موثوق")
                    if flags.active_developer:
                        badges.append("👨‍💻 مطور نشط")
                    if flags.early_supporter:
                        badges.append("⭐ داعم مبكر")
                    if flags.staff:
                        badges.append("👔 طاقم ديسكورد")
                    if flags.partner:
                        badges.append("🤝 شريك ديسكورد")
                    if flags.hypesquad_events:
                        badges.append("🎉 HypeSquad")
                    if flags.bughunter_1:
                        badges.append("🐛 صياد باغز")
                    if flags.bughunter_2:
                        badges.append("🐛 صياد باغز ذهبي")
                    if flags.early_verified_bot_developer:
                        badges.append("🔧 مطور بوت موثوق مبكر")
                except:
                    pass
                if user.avatar and user.avatar.is_animated():
                    badges.append("🎞️ أفاتار متحرك")
                badges_str = " • ".join(badges) if badges else "لا يوجد"

                if self.joined_ts:
                    embed.add_field(
                        name="🏰 معلومات السيرفر",
                        value=(
                            f"├─ الاسم بالسيرفر: **{nickname}**\n"
                            f"├─ أعلى رتبة: **{top_role}**\n"
                            f"├─ الرتب ({roles_count}): {roles_text}\n"
                            f"├─ الحالة: {status}\n"
                            f"├─ الأجهزة: {devices_str}\n"
                            f"├─ الحالة الشخصية: {custom_status}\n"
                            f"├─ انضم للسيرفر: <t:{self.joined_ts}:F> (<t:{self.joined_ts}:R>)\n"
                            f"└─ بوستر؟ {'نعم 💎' if member.premium_since else 'لا'}"
                        ),
                        inline=False
                    )

                embed.add_field(name="🏅 الشارات", value=badges_str, inline=False)
                embed.add_field(name="🔑 الصلاحيات", value=perms_str[:1024], inline=False)

                if member.roles:
                    roles_hierarchy = sorted(member.roles, key=lambda r: r.position, reverse=True)
                    hierarchy_text = "\n".join([f"{'🔴' if r.hoist else '⚪'} {r.name} (pos {r.position})" for r in roles_hierarchy[:15]])
                    embed.add_field(name="📊 ترتيب الرتب", value=hierarchy_text, inline=False)
            else:
                embed.add_field(name="⚠️ ملاحظة", value="العضو لم يعد في السيرفر (تم الطرد)", inline=False)
                if self.roles_text:
                    embed.add_field(name="🎭 الرتب السابقة", value=self.roles_text, inline=False)

            if self.invite_link:
                embed.add_field(name="🔗 رابط الدعوة", value=self.invite_link, inline=True)

            embed.set_footer(text=f"🌐 MAX BOT — معلومات الهاكر")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في جلب المعلومات: {e}", ephemeral=True)

    @discord.ui.button(label="📋 تأكد من اختبار", style=discord.ButtonStyle.success, emoji="📋", custom_id="bait_test_status")
    async def test_status(self, interaction, button):
        await interaction.response.defer()
        try:
            fp_key = f"{self.guild_id}_{self.hacker_id}"
            data = {}
            try:
                if os.path.exists(DATA_FILE):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except:
                pass

            fingerprints = data.get("fingerprints", {})
            fp = fingerprints.get(fp_key, {})
            hardware_bans = data.get("hardware_bans", [])
            hacked_accounts = data.get("hacked_accounts", {})
            prev = hacked_accounts.get(str(self.hacker_id), [])

            embed = discord.Embed(
                title="📋 تأكيد اختبار الهاكرز",
                color=0x2ECC71 if fp else 0xE74C3C,
                timestamp=discord.utils.utcnow()
            )

            if fp:
                is_banned = fp.get("device_hash", "") in hardware_bans
                collected_at = fp.get("collected_at", "غير معروف")[:19]
                ip = fp.get("ip", "غير معروف")
                gpu = fp.get("gpu_renderer", "غير معروف")[:50]
                platform = fp.get("platform", "?")
                screen = fp.get("screen", "?")
                device_hash = fp.get("device_hash", "غير معروف")[:20]

                score = 0
                if is_banned:
                    score += 10
                if fp.get("no_js"):
                    score += 8
                if fp.get("webdriver"):
                    score += 8
                if fp.get("incognito"):
                    score += 3
                media_count = (fp.get("media_cam", 0) or 0) + (fp.get("media_mic", 0) or 0)
                if media_count == 0:
                    score += 4
                if fp.get("touch_support") and fp.get("max_touch_points", 0) == 0:
                    score += 2
                if prev:
                    score += min(len(prev) * 3, 9)

                if score >= 19:
                    verdict = "🔴 هاكر مؤكد"
                elif score >= 9:
                    verdict = "🟠 مشبوه جداً"
                elif score >= 5:
                    verdict = "🟡 مشبوه"
                else:
                    verdict = "🟢 نظيف"

                embed.add_field(
                    name="✅ اختبر — تم جمع البصمة",
                    value=(
                        f"├─ ⏰ **الوقت:** {collected_at}\n"
                        f"├─ 🌐 **IP:** `{ip}`\n"
                        f"├─ 📱 **النظام:** {platform}\n"
                        f"├─ 🖥️ **الشاشة:** {screen}\n"
                        f"├─ 🎮 **GPU:** {gpu}\n"
                        f"├─ 🔑 **Device Hash:** `{device_hash}`\n"
                        f"├─ 📷 **كاميرات:** {fp.get('media_cam', '?')} | 🎤 **ميكروفونات:** {fp.get('media_mic', '?')}\n"
                        f"├─ 🔤 **خطوط:** {fp.get('fonts_count', '?')}\n"
                        f"├─ 🚫 **Hardware Ban:** {'نعم 🔴' if is_banned else 'لا 🟢'}\n"
                        f"└─ 📊 **التقييم:** {verdict} ({score}/30)"
                    ),
                    inline=False
                )
                if prev:
                    embed.add_field(
                        name=f"⚠️ سبق القبض ({len(prev)} مرة)",
                        value="\n".join([f"• <t:{e['timestamp']}:R>" for e in prev[-3:]]),
                        inline=False
                    )
                embed.set_footer(text="🌐 MAX BOT — تأكيد الاختبار ✅")
            else:
                embed.add_field(
                    name="❌ لم يختبر بعد",
                    value=(
                        f"**الهاكر:** {self.hacker_name} (`{self.hacker_id}`)\n\n"
                        f"├─ 🔗 تم إرسال رابط التحقق له\n"
                        f"├─ ❌ لم يضغط على الرابط بعد\n"
                        f"├─ 📊 عمر الحساب: **{self.account_age}** يوم\n"
                        f"├─ 🔗 الروابط المشبوهة: {len(self.url_analyses)}\n"
                        f"└─ 📊 التقييم: {self.severity_label}\n\n"
                        f"**💡 نصيحة:** أرسل له الدعوة مرة ثانية قد يضغط على الرابط"
                    ),
                    inline=False
                )
                if self.invite_link:
                    embed.add_field(name="🔗 رابط الدعوة", value=self.invite_link, inline=True)
                embed.set_footer(text="🌐 MAX BOT — لم يختبر ❌")

            user_obj = await bot.fetch_user(self.hacker_id)
            embed.set_thumbnail(url=user_obj.display_avatar.url)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في التحقق من الاختبار: {e}", ephemeral=True)

    @discord.ui.button(label="🔬 تحقق من الاختبار", style=discord.ButtonStyle.danger, emoji="🔬", custom_id="bait_honeypot")
    async def honeypot_check(self, interaction, button):
        await interaction.response.defer()
        try:
            fp_key = f"{self.guild_id}_{self.hacker_id}"
            data = {}
            try:
                if os.path.exists(DATA_FILE):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except:
                pass

            fingerprints = data.get("fingerprints", {})
            fp = fingerprints.get(fp_key, {})
            hardware_bans = data.get("hardware_bans", [])
            hacked_accounts = data.get("hacked_accounts", {})
            prev = hacked_accounts.get(str(self.hacker_id), [])

            embed = discord.Embed(
                title="🔬 تقرير اختبار الهاكرز — Honeypot",
                color=0xE74C3C if fp else 0x95A5A6,
                timestamp=discord.utils.utcnow()
            )

            if not fp:
                embed.add_field(
                    name="⚠️ لا توجد بيانات fingerprint",
                    value=(
                        f"**السبب:** الهاكر لم يضغط على رابط التحقق في صفحة الـ honeypot\n\n"
                        f"**📊 معلومات الصيد:**\n"
                        f"├─ التقييم: {self.severity_label}\n"
                        f"├─ عمر الحساب: {self.account_age} يوم\n"
                        f"├─ الروابط المشبوهة: {len(self.url_analyses)}\n"
                        f"├─ الطرق المستخدمة: {', '.join(self.url_analyses[:3]) if self.url_analyses else 'غير معروف'}\n"
                        f"└─ بوت؟ {'نعم' if self.is_bot_acc else 'لا'}"
                    ),
                    inline=False
                )
            else:
                is_banned = fp.get("device_hash", "") in hardware_bans
                ban_status = "🔴 **محظور (Hardware Ban)**" if is_banned else "🟢 غير محظور"

                embed.add_field(
                    name="📊 الحالة العامة",
                    value=(
                        f"├─ Hardware Ban: {ban_status}\n"
                        f"├─ Device Hash: `{fp.get('device_hash', 'غير معروف')[:24]}`\n"
                        f"├─ IP: `{fp.get('ip', 'غير معروف')}`\n"
                        f"├─ تم الجمع: {fp.get('collected_at', 'غير معروف')[:19]}\n"
                        f"└─ مكرر؟ **{len(prev)}** مرة سابقاً"
                    ),
                    inline=False
                )

                hw_text = (
                    f"├─ 📱 النظام: {fp.get('platform', '?')}\n"
                    f"├─ 🖥️ الشاشة: {fp.get('screen', '?')}\n"
                    f"├─ 🎮 GPU: {fp.get('gpu_renderer', 'غير معروف')[:60]}\n"
                    f"├─ 💾 RAM: {fp.get('ram_size', '?')} GB\n"
                    f"├─ 🔧 CPU: {fp.get('cpu_cores', '?')} cores\n"
                    f"├─ 🎵 Audio: {fp.get('audio_sample_rate', '?')} Hz\n"
                    f"├─ 🔋 البطارية: {fp.get('battery_level', '?')}%\n"
                    f"├─ 📷 الكاميرات: {fp.get('media_cam', '?')}\n"
                    f"├─ 🎤 الميكروفونات: {fp.get('media_mic', '?')}\n"
                    f"├─ 🔤 الخطوط: {fp.get('fonts_count', '?')} خط\n"
                    f"├─ 🌐 WebGL: {fp.get('webgl_version', '?')}\n"
                    f"├─ 🕐 JS Timing: {fp.get('js_timing', '?')} ms\n"
                    f"├─ 🌐 WebRTC IP: {fp.get('webrtc_ip', 'غير متاح')}\n"
                    f"├─ 🗣️ Speech Voices: {fp.get('speech_voices', '?')}\n"
                    f"└─ 🐢 JS Engine: {fp.get('js_engine', '?')}"
                )
                embed.add_field(name="🖥️ معلومات الجهاز المتقدمة", value=hw_text, inline=False)

                checks_text = ""
                if fp.get("no_js"):
                    checks_text += "🔴 لا يوجد JavaScript (headless browser)\n"
                else:
                    checks_text += "✅ JavaScript متاح\n"

                if fp.get("webdriver"):
                    checks_text += "🔴 navigator.webdriver = true (Selenium/Puppeteer)\n"
                else:
                    checks_text += "✅ navigator.webdriver = false\n"

                if fp.get("incognito"):
                    checks_text += "🔴 وضع Incognito مكتشف\n"
                else:
                    checks_text += "✅ وضع Incognito غير مكتشف\n"

                if fp.get("languages", 0) == 0:
                    checks_text += "🔴 لا توجد لغات مسجلة\n"
                elif fp.get("languages", 0) > 5:
                    checks_text += "⚠️ لغات كثيرة جداً (قد يكون proxy)\n"
                else:
                    checks_text += f"✅ {fp.get('languages', 0)} لغة\n"

                touch = fp.get("touch_support", False)
                max_touch = fp.get("max_touch_points", 0)
                has_screen = fp.get("screen_width", 0) > 0
                if touch and max_touch == 0:
                    checks_text += "🔴 Touch مدعوم لكن 0 نقاط (مميزات وهمية)\n"
                elif not touch and has_screen:
                    checks_text += "✅ بدون Touch (normal desktop)\n"

                if fp.get("battery_level", -1) == 0 and fp.get("charging") is False:
                    checks_text += "⚠️ البطارية فاضية وغير مشحونة (قد يكون headless)\n"

                media_count = (fp.get("media_cam", 0) or 0) + (fp.get("media_mic", 0) or 0)
                if media_count == 0:
                    checks_text += "🔴 لا توجد أجهزة media (headless)\n"

                if checks_text:
                    embed.add_field(name="🔬 نتائج الفحص التقني", value=checks_text[:1024], inline=False)

                if prev:
                    dates = [f"• <t:{e['timestamp']}:R>" for e in prev[-5:]]
                    embed.add_field(
                        name=f"⚠️ سجل القبض ({len(prev)} مرات)",
                        value="\n".join(dates),
                        inline=False
                    )

                score = 0
                if is_banned:
                    score += 10
                if fp.get("no_js"):
                    score += 8
                if fp.get("webdriver"):
                    score += 8
                if fp.get("incognito"):
                    score += 3
                if media_count == 0:
                    score += 4
                if touch and max_touch == 0:
                    score += 2
                if prev:
                    score += min(len(prev) * 3, 9)

                if score >= 19:
                    verdict = "🔴 هاكر مؤكد — تم الحظر تلقائياً"
                elif score >= 9:
                    verdict = "🟠 مشبوه جداً"
                elif score >= 5:
                    verdict = "🟡 مشبوه"
                else:
                    verdict = "🟢 نظيف"

                embed.add_field(name="📊 التقييم النهائي", value=f"**النقاط: {score}/30**\n{verdict}", inline=False)

                user_obj = await bot.fetch_user(self.hacker_id)
                embed.set_thumbnail(url=user_obj.display_avatar.url)

            embed.set_footer(text=f"🌐 MAX BOT — نظام الحماية السيبرانية")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في فحص الـ honeypot: {e}", ephemeral=True)

@bot.event
async def on_message(message):
    if message.author.bot and not message.webhook_id:
        return

    if message.id in _processed_messages:
        return
    _processed_messages.add(message.id)
    if len(_processed_messages) > 1000:
        _processed_messages.clear()

    guild_id = message.guild.id if message.guild else None

    if guild_id and message.guild:
        bait_ch = hacker_bait_channels.get(guild_id)
        if bait_ch and message.channel.id == bait_ch:
            print(f"[BAIT] {message.author} ({message.author.id}) wrote in bait channel {message.channel.id}", flush=True)
            member_obj = message.guild.get_member(message.author.id)
            has_kick_perm = False
            if member_obj:
                has_kick_perm = any(r.permissions.kick_members for r in member_obj.roles)
            if not (message.author.id == YOUR_USER_ID or message.author.id == message.guild.owner_id or has_kick_perm):
                print(f"[BAIT] Processing {message.author}...", flush=True)

                msg_content = message.content or ""
                content_preview = msg_content[:500] if msg_content else "(مرفق)"
                msg_len_chars = len(msg_content)
                msg_len_words = len(msg_content.split())
                msg_len_lines = msg_content.count("\n") + 1

                try:
                    await message.delete()
                except Exception as e:
                    print(f"[BAIT DELETE ERROR] {e}", flush=True)

                invite_link = ""
                try:
                    invite = await message.channel.create_invite(max_age=3600, max_uses=1, reason="Bait kick invite")
                    invite_link = invite.url
                except Exception as e:
                    print(f"[BAIT INVITE ERROR] {e}", flush=True)

                account_age = (discord.utils.utcnow() - message.author.created_at).days
                joined_at = member_obj.joined_at if member_obj else None
                days_in_server = (discord.utils.utcnow() - joined_at).days if joined_at else "غير معروف"
                is_bot = message.author.bot
                is_boosting = member_obj.premium_since is not None if member_obj else False

                created_ts = int(message.author.created_at.timestamp())
                joined_ts = int(joined_at.timestamp()) if joined_at else 0

                dm_embed = discord.Embed(
                    title="⚠️ تم طردك من السيرفر",
                    description=(
                        f"**❌ تم طردك من {message.guild.name}**\n\n"
                        f"**📋 السبب:** نشر روابط مشبوهة\n"
                        f"**👤 الحساب:** `{message.author.id}`"
                    ),
                    color=0xE74C3C,
                    timestamp=discord.utils.utcnow()
                )
                dm_embed.set_footer(text=f"🌐 {message.guild.name} • MAX BOT", icon_url=message.guild.icon.url if message.guild.icon else None)

                site_url = get_base_url()
                if site_url:
                    hp_token = generate_honeypot_token(message.author.id, guild_id)
                    verify_url = f"{site_url}/verify?token={hp_token}&guild_id={guild_id}&user_id={message.author.id}"
                    dm_embed.add_field(
                        name="🔐 تأكيد الهوية",
                        value=(
                            f"**⚠️ أنت مشبوه عليه في السيرفر**\n\n"
                            f"لإثبات أنك **لست هاكر**، اضغط الزر أدناه:\n\n"
                            f"🔗 **[اضغط هنا للتحقق]({verify_url})**\n\n"
                            f"⏰ **الرابط ينتهي خلال 5 دقائق**"
                        ),
                        inline=False
                    )
                    try:
                        _d = {}
                        if os.path.exists(DATA_FILE):
                            with open(DATA_FILE, "r", encoding="utf-8") as _f:
                                _d = json.load(_f)
                        _d.setdefault("honeypot_invites", {})[hp_token] = invite_link or ""
                        with open(DATA_FILE, "w", encoding="utf-8") as _f:
                            json.dump(_d, _f, ensure_ascii=False)
                    except Exception as e:
                        print(f"[BAIT] honeypot save error: {e}", flush=True)
                if invite_link:
                    dm_embed.add_field(
                        name="📌 رابط العودة",
                        value=f"**[اضغط للعودة للسيرفر]({invite_link})**",
                        inline=False
                    )

                dm_sent = False
                try:
                    await message.author.send(embed=dm_embed)
                    dm_sent = True
                    print(f"[BAIT] ✅ DM sent to {message.author}", flush=True)
                except discord.Forbidden:
                    print(f"[BAIT] ❌ DMs مغلقة للمستخدم {message.author} ({message.author.id})", flush=True)
                except Exception as e:
                    print(f"[BAIT] ❌ DM ERROR: {e}", flush=True)

                if not dm_sent:
                    try:
                        fallback = discord.Embed(
                            title="⚠️ تم طردك",
                            description=f"**{message.author.mention}** — تم طردك لنشر روابط مشبوهة\n📞 تواصل مع الإدارة",
                            color=0xE74C3C
                        )
                        fallback.set_footer(text=f"🌐 {message.guild.name} • MAX BOT")
                        await message.channel.send(embed=fallback)
                        print(f"[BAIT] ✅ Fallback sent in channel for {message.author}", flush=True)
                    except Exception as e2:
                        print(f"[BAIT] ❌ FALLBACK ERROR: {e2}", flush=True)

                roles_text = "بدون"
                roles_list = []
                nickname = "لا يوجد"
                top_role = "لا يوجد"
                roles_count = 0
                permissions = []
                if member_obj:
                    roles_list = [r.name for r in member_obj.roles if r != message.guild.default_role]
                    nickname = member_obj.nick or "لا يوجد"
                    top_role = member_obj.top_role.name if member_obj.top_role != message.guild.default_role else "لا يوجد"
                    roles_count = len(roles_list)
                    permissions = [p[0] for p in member_obj.guild_permissions if p[1]]
                all_roles = ", ".join(roles_list) if roles_list else "لا يوجد"
                perms_str = ", ".join(permissions[:10]) if permissions else "لا يوجد صلاحيات"

                badges = []
                try:
                    sys_flags = message.author.public_flags
                    if sys_flags.verified_bot_developer:
                        badges.append("🔧 مطور موثوق")
                    if sys_flags.discord_certified_moderator:
                        badges.append("🛡️ مoderator موثوق")
                    if sys_flags.active_developer:
                        badges.append("👨‍💻 مطور نشط")
                    if sys_flags.early_supporter:
                        badges.append("⭐ داعم مبكر")
                    if sys_flags.staff:
                        badges.append("👔 طاقم ديسكورد")
                    if sys_flags.partner:
                        badges.append("🤝 شريك ديسكورد")
                    if sys_flags.hypesquad_events:
                        badges.append("🎉 HypeSquad")
                    if sys_flags.bughunter_1:
                        badges.append("🐛 صياد باغز")
                    if sys_flags.bughunter_2:
                        badges.append("🐛 صياد باغز ذهبي")
                    if sys_flags.early_verified_bot_developer:
                        badges.append("🔧 مطور بوت موثوق مبكر")
                    if sys_flags.verified_bot:
                        badges.append("✅ بوت موثوق")
                except:
                    pass
                if message.author.avatar and message.author.avatar.is_animated():
                    badges.append("🎞️ أفاتار متحرك")
                if message.author.bot:
                    badges.append("🤖 بوت")
                if not badges:
                    badges.append("لا يوجد")
                badges_str = " • ".join(badges)

                client_status = "غير معروف"
                try:
                    if member_obj:
                        if member_obj.status == discord.Status.online:
                            client_status = "🟢 متصل"
                        elif member_obj.status == discord.Status.idle:
                            client_status = "🌙 خامل"
                        elif member_obj.status == discord.Status.dnd:
                            client_status = "🔴 لا تزعج"
                        elif member_obj.status == discord.Status.offline:
                            client_status = "⚫ غير متصل"
                except:
                    pass

                device_status = []
                try:
                    if member_obj:
                        if member_obj.mobile:
                            device_status.append("📱 جوال")
                        if member_obj.desktop:
                            device_status.append("🖥️ كمبيوتر")
                        if member_obj.web_client:
                            device_status.append("🌐 متصفح")
                except:
                    pass
                devices_str = " • ".join(device_status) if device_status else "غير معروف"

                custom_status = "لا يوجد"
                try:
                    if member_obj:
                        for act in member_obj.activities:
                            if act.type == discord.ActivityType.custom:
                                if act.state:
                                    custom_status = act.state
                                break
                except:
                    pass

                booster_duration = "غير معروف"
                if member_obj and member_obj.premium_since:
                    boost_days = (discord.utils.utcnow() - member_obj.premium_since).days
                    if boost_days >= 365:
                        booster_duration = f"**{boost_days // 365}** سنة و **{(boost_days % 365) // 30}** شهر"
                    elif boost_days >= 30:
                        booster_duration = f"**{boost_days // 30}** شهر و **{boost_days % 30}** يوم"
                    else:
                        booster_duration = f"**{boost_days}** يوم"

                created_date = f"<t:{int(message.author.created_at.timestamp())}:F>"
                joined_date = f"<t:{int(joined_at.timestamp())}:F>" if joined_at else "غير معروف"

                account_type = "غير معروف"
                if message.author.bot:
                    account_type = "🤖 بوت"
                elif account_age < 7:
                    account_type = "⚠️ حساب جديد جداً (أقل من أسبوع)"
                elif account_age < 30:
                    account_type = "⚠️ حساب جديد (أقل من شهر)"
                elif account_age < 365:
                    account_type = "✅ حساب عادي"
                else:
                    account_type = "✅ حساب قديم"

                age_vs_server = "غير معروف"
                if days_in_server != "غير معروف":
                    ratio = account_age - days_in_server
                    if ratio > 30:
                        age_vs_server = "📊 الحساب أقدم من السيرفر"
                    elif ratio < 0:
                        age_vs_server = "⚠️ الحساب أحدث من السيرفر!"
                    else:
                        age_vs_server = "📊 الحساب تم إنشاؤه قريب من تاريخ السيرفر"

                reason = "حساب مهكر / نشر روابط مشبوهة"

                log_embed = discord.Embed(
                    title="🪤 صيد هاكرز — تم القبض والطرد",
                    color=0xE74C3C,
                    timestamp=datetime.now(timezone.utc)
                )
                log_embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
                log_embed.set_thumbnail(url=message.author.display_avatar.url)

                account_info = (
                    f"├─ المعرف: `{message.author.id}`\n"
                    f"├─ الاسم الأصلي: `{message.author}`\n"
                    f"├─ الاسم بالسيرفر: **{nickname}**\n"
                    f"├─ نوع الحساب: {account_type}\n"
                    f"├─ عمر الحساب: **{account_age}** يوم\n"
                    f"├─ تاريخ الإنشاء: {created_date}\n"
                    f"├─ تاريخ الانضمام: {joined_date}\n"
                    f"├─ مدة بالسيرفر: **{days_in_server}** يوم\n"
                    f"└─ {age_vs_server}"
                )
                log_embed.add_field(name="👤 معلومات العضو", value=account_info, inline=False)

                status_info = (
                    f"├─ حالة الحساب: {client_status}\n"
                    f"├─ المنصات: {devices_str}\n"
                    f"├─ الحالة الشخصية: {custom_status}\n"
                    f"├─ بوت؟ {'نعم 🤖' if is_bot else 'لا'}\n"
                    f"└─ ميستر؟ {'نعم 💎 (' + booster_duration + ')' if is_boosting else 'لا'}"
                )
                log_embed.add_field(name="📊 حالة الحساب", value=status_info, inline=False)

                if badges_str and badges_str != "لا يوجد":
                    log_embed.add_field(name="🏅 الشارات", value=badges_str, inline=False)

                if roles_list:
                    roles_text = " • ".join(roles_list[:15])
                    if roles_count > 15:
                        roles_text += f" +{roles_count - 15} أخرى"
                    log_embed.add_field(name=f"🎭 الرتب ({roles_count})", value=roles_text, inline=False)

                if permissions:
                    log_embed.add_field(name="🔑 الصلاحيات", value=perms_str[:1000], inline=False)

                message_info = (
                    f"├─ الروم: {message.channel.mention}\n"
                    f"├─ محتوى الرسالة:\n```\n{content_preview}\n```\n"
                    f"├─ الطول: **{msg_len_chars}** حرف • **{msg_len_words}** كلمة • **{msg_len_lines}** سطر"
                )
                if message.attachments:
                    att_lines = "\n".join([f"│   📎 [{a.filename}]({a.url})" for a in message.attachments[:3]])
                    message_info += f"\n├─ المرفقات:\n{att_lines}"
                message_info += f"\n└─ [قفز للرسالة]({message.jump_url})"
                log_embed.add_field(name="💬 الرسالة المخترقة", value=message_info, inline=False)

                log_embed.add_field(name="📍 القناة", value=message.channel.mention, inline=True)
                log_embed.add_field(name="🔗 رابط الدعوة", value=invite_link or "غير متاح", inline=True)
                log_embed.add_field(name="📊 عدد الأعضاء", value=f"**{message.guild.member_count}** عضو", inline=True)
                log_embed.add_field(name="📌 السبب", value=f"```\n{reason}\n```", inline=False)
                log_embed.add_field(name="🕐 التوقيت", value=f"<t:{int(discord.utils.utcnow().timestamp())}:F>", inline=True)
                log_embed.set_footer(text=f"🌐 {message.guild.name} • صيد الهاكرز 🔎", icon_url=message.guild.icon.url if message.guild.icon else None)
                try:
                    print(f"[BAIT] Attempting send_log(log_hacking) for {message.author}...", flush=True)
                    await send_log(message.guild.id, "log_hacking", log_embed)
                    print(f"[BAIT] ✅ Log sent to log_hacker", flush=True)
                except Exception as e:
                    print(f"[BAIT LOG ERROR] {e}", flush=True)

                await asyncio.sleep(5)

                kick_success = False
                bot_permissions = message.guild.me.guild_permissions
                print(f"[BAIT] Bot permissions: kick={bot_permissions.kick_members}, manage_roles={bot_permissions.manage_roles}", flush=True)

                target_member = member_obj or message.guild.get_member(message.author.id)
                if not target_member:
                    try:
                        target_member = await message.guild.fetch_member(message.author.id)
                    except:
                        pass
                if target_member:
                    if not bot_permissions.kick_members:
                        print(f"[BAIT] ❌ Bot missing kick_members permission!", flush=True)
                    elif message.guild.me.top_role.position <= target_member.top_role.position:
                        print(f"[BAIT] ❌ Target role ({target_member.top_role.name} pos {target_member.top_role.position}) >= Bot role ({message.guild.me.top_role.name} pos {message.guild.me.top_role.position})", flush=True)
                    else:
                        try:
                            await message.guild.kick(target_member, reason=reason)
                            kick_success = True
                            hacker_bait_kicked.add(message.author.id)
                            mark_data_dirty()
                            print(f"[BAIT] ✅ Successfully kicked {message.author} ({message.author.id})", flush=True)
                        except discord.Forbidden:
                            print(f"[BAIT] ❌ KICK Forbidden (discord.py) — trying HTTP API...", flush=True)
                            try:
                                import aiohttp
                                async with aiohttp.ClientSession() as session:
                                    headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
                                    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{message.author.id}"
                                    async with session.delete(url, headers=headers) as resp:
                                        if resp.status == 204:
                                            kick_success = True
                                            hacker_bait_kicked.add(message.author.id)
                                            mark_data_dirty()
                                            print(f"[BAIT] ✅ HTTP API kick SUCCESS for {message.author}", flush=True)
                                        else:
                                            body = await resp.text()
                                            print(f"[BAIT] ❌ HTTP API kick FAILED: {resp.status} {body}", flush=True)
                            except Exception as e2:
                                print(f"[BAIT] ❌ HTTP API kick ERROR: {e2}", flush=True)
                        except discord.NotFound:
                            print(f"[BAIT] ❌ KICK NotFound — member already left", flush=True)
                        except Exception as e:
                            print(f"[BAIT] ❌ KICK ERROR: {type(e).__name__}: {e}", flush=True)
                            try:
                                import aiohttp
                                async with aiohttp.ClientSession() as session:
                                    headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
                                    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{message.author.id}"
                                    async with session.delete(url, headers=headers) as resp:
                                        if resp.status == 204:
                                            kick_success = True
                                            hacker_bait_kicked.add(message.author.id)
                                            mark_data_dirty()
                                            print(f"[BAIT] ✅ HTTP API kick SUCCESS for {message.author}", flush=True)
                                        else:
                                            body = await resp.text()
                                            print(f"[BAIT] ❌ HTTP API kick FAILED: {resp.status} {body}", flush=True)
                            except Exception as e3:
                                print(f"[BAIT] ❌ HTTP API kick ERROR: {e3}", flush=True)
                else:
                    print(f"[BAIT] ❌ Member not found in guild: {message.author.id}", flush=True)

                url_analyses = analyze_url(msg_content)
                severity_color, severity_label = get_severity(account_age, url_analyses)
                extracted_urls = "\n".join([f"• `{u['url'][:80]}` — {u['verdict']}" for u in url_analyses]) if url_analyses else "لا توجد روابط"
                methods = get_attack_methods(msg_content)
                methods_text = "\n".join([f"• {m}" for m in methods])
                prev_catches = get_hacked_accounts_data().get(str(message.author.id), [])
                is_repeat = len(prev_catches) > 0

                save_hacked_account(message.author.id, guild_id, str(message.author), content_preview, severity_label)

                if is_repeat:
                    severity_color = 0xFF0000
                    severity_label = "🔴 مكرر! " + severity_label

                owner_embed = discord.Embed(
                    title="🪤 صيد هاكرز — تم القبض!",
                    description=(
                        f"**👤 الهاكر:** {message.author} (`{message.author.id}`)\n"
                        f"**🎭 الاسم بالسيرفر:** {nickname}\n"
                        f"**📅 عمر الحساب:** {account_age} يوم\n"
                        f"**📅 انضم للسيرفر:** <t:{joined_ts}:R>\n"
                        f"**🎭 الرتب:** {roles_text or 'بدون'}\n"
                        f"**📊 عدد الأعضاء:** {message.guild.member_count}"
                    ),
                    color=severity_color,
                    timestamp=discord.utils.utcnow()
                )
                owner_embed.add_field(name="💬 الرسالة المرسلة", value=f"```\n{content_preview[:500]}\n```", inline=False)
                owner_embed.add_field(name="🔗 الروابط المكتشفة", value=extracted_urls[:1024], inline=False)
                owner_embed.add_field(name="🛠️ الطرق المستخدمة", value=methods_text, inline=False)
                owner_embed.add_field(name="📊 التقييم", value=severity_label, inline=False)
                if is_repeat:
                    repeat_dates = [f"<t:{e['timestamp']}:R>" for e in prev_catches[-3:]]
                    owner_embed.add_field(name="⚠️ مكرر!", value=f"**سبق القبض عليه {len(prev_catches)} مرة:**\n" + "\n".join(repeat_dates), inline=False)
                if invite_link:
                    owner_embed.add_field(name="🔗 رابط الدعوة", value=invite_link, inline=True)

                fingerprint_data = {}
                try:
                    _d2 = {}
                    if os.path.exists(DATA_FILE):
                        with open(DATA_FILE, "r", encoding="utf-8") as _f2:
                            _d2 = json.load(_f2)
                    fp_key = f"{guild_id}_{message.author.id}"
                    fingerprint_data = _d2.get("fingerprints", {}).get(fp_key, {})
                except:
                    pass
                if fingerprint_data:
                    fp_text = (
                        f"├─ 🌐 IP: `{fingerprint_data.get('ip', 'غير معروف')}`\n"
                        f"├─ 📱 النظام: {fingerprint_data.get('platform', 'غير معروف')}\n"
                        f"├─ 🖥️ الشاشة: {fingerprint_data.get('screen', 'غير معروف')}\n"
                        f"├─ 🎮 GPU: {fingerprint_data.get('gpu_renderer', 'غير معروف')[:60]}\n"
                        f"├─ 💾 RAM: {fingerprint_data.get('ram_size', '?')} GB\n"
                        f"├─ 🔧 CPU: {fingerprint_data.get('cpu_cores', '?')} cores\n"
                        f"├─ 🎵 Audio: {fingerprint_data.get('audio_sample_rate', '?')} Hz\n"
                        f"├─ 🔋 البطارية: {fingerprint_data.get('battery_level', '?')}%\n"
                        f"├─ 🔑 Device Hash: `{fingerprint_data.get('device_hash', 'غير معروف')[:16]}`\n"
                        f"└─ 🕐 تم الجمع: {fingerprint_data.get('collected_at', 'غير معروف')[:19]}"
                    )
                    owner_embed.add_field(name="🔍 معلومات الشبكة والجهاز", value=fp_text, inline=False)
                    is_banned = fingerprint_data.get('device_hash', '') in _d2.get('hardware_bans', [])
                    if is_banned:
                        owner_embed.add_field(name="🚫 Hardware Ban", value="🔴 هذا الجهاز محظور بالفعل!", inline=False)

                owner_embed.set_thumbnail(url=message.author.display_avatar.url)
                owner_embed.set_footer(text=f"🌐 {message.guild.name} • صيد الهاكرز 🔎")
                owner_view = HackerInvestigateView(
                    hacker_id=message.author.id,
                    hacker_name=str(message.author),
                    message_content=msg_content,
                    guild_id=guild_id,
                    invite_link=invite_link,
                    account_age=account_age,
                    joined_ts=joined_ts,
                    created_ts=created_ts,
                    severity_label=severity_label,
                    url_analyses=url_analyses,
                    roles_text=roles_text,
                    is_booster=is_boosting,
                    is_bot_acc=is_bot
                )

                now_ts = int(discord.utils.utcnow().timestamp())
                last_dm = bait_dm_cooldown.get(message.author.id, 0)
                if now_ts - last_dm < 60:
                    print(f"[BAIT] ⏳ Rate limited: {message.author} ({now_ts - last_dm}s since last DM)", flush=True)
                else:
                    bait_dm_cooldown[message.author.id] = now_ts
                    owner_user = None
                    try:
                        owner_user = bot.get_user(YOUR_USER_ID)
                        if not owner_user:
                            owner_user = await bot.fetch_user(YOUR_USER_ID)
                        print(f"[BAIT] Owner found: {owner_user} ({owner_user.id})", flush=True)
                    except Exception as e:
                        print(f"[BAIT] ❌ Cannot fetch owner {YOUR_USER_ID}: {e}", flush=True)
                    if owner_user:
                        dm_sent_ok = False
                        try:
                            await owner_user.send(embed=owner_embed, view=owner_view)
                            dm_sent_ok = True
                            print(f"[BAIT] ✅ Owner DM sent (embed+view) for {message.author}", flush=True)
                        except discord.Forbidden:
                            print(f"[BAIT] ❌ Owner DM Forbidden — owner DMs closed or bot blocked", flush=True)
                        except Exception as e:
                            print(f"[BAIT] ❌ Owner DM error: {type(e).__name__}: {e}", flush=True)
                            try:
                                await owner_user.send(embed=owner_embed)
                                dm_sent_ok = True
                                print(f"[BAIT] ✅ Owner embed-only DM sent (view failed)", flush=True)
                            except Exception as e2:
                                print(f"[BAIT] ❌ Owner embed fallback error: {type(e2).__name__}: {e2}", flush=True)
                        if not dm_sent_ok:
                            print(f"[BAIT] ⚠️ Sending to log_hacking as fallback", flush=True)
                            try:
                                await send_log(guild_id, "log_hacking", owner_embed)
                            except:
                                pass
                    else:
                        print(f"[BAIT] ❌ Owner user not found, sending to log_hacking", flush=True)
                        try:
                            await send_log(guild_id, "log_hacking", owner_embed)
                        except:
                            pass

                async def voice_alert_task():
                    try:
                        for vs in bot.voice_clients:
                            if vs.channel and vs.channel.members:
                                owner_member = message.guild.get_member(YOUR_USER_ID)
                                if owner_member and owner_member in vs.channel.members:
                                    alert_embed = discord.Embed(
                                        title="🪤 صيد هاكرز!",
                                        description=f"**تم القبض على {message.author}**\n{severity_label}\n{invite_link or ''}",
                                        color=severity_color
                                    )
                                    await message.channel.send(content=f"🪤 <@{YOUR_USER_ID}>", embed=alert_embed)
                                    return
                        owner_member = message.guild.get_member(YOUR_USER_ID)
                        if owner_member and owner_member.voice and owner_member.voice.channel:
                            ch = owner_member.voice.channel
                            if not message.guild.voice_client:
                                vc = await ch.connect(self_deaf=True)
                                await asyncio.sleep(1)
                                if vc.is_connected():
                                    await vc.disconnect()
                    except Exception as e:
                        print(f"[BAIT] Voice alert skipped: {e}", flush=True)
                asyncio.create_task(voice_alert_task())

                return

    if guild_id and message.guild:
        content = message.content.strip()
        if content.lower() in ("$log", "$لوق"):
            cmd = bot.get_command("program_log")
            if cmd:
                ctx = await bot.get_context(message)
                ctx.command = cmd
                await ctx.invoke(cmd)
                return
        elif content.lower().startswith(("$log ", "$لوق ")):
            args = content.split(None, 1)[1].strip().lower()
            cmd = bot.get_command("program_on" if args in ("on", "تفعيل") else "program_off" if args in ("off", "تعطيل") else None)
            if cmd:
                ctx = await bot.get_context(message)
                ctx.command = cmd
                await ctx.invoke(cmd)
                return

    if not guild_id:
        await bot.process_commands(message)
        return

    try:
        message_cache.add(message)
    except Exception as e:
        print(f"[MSG_CACHE ERROR] {e}", flush=True)

    if is_exempt(message.author):
        await bot.process_commands(message)
        return

    ch_id = message.channel.id

    # ── نظام AFK ──
    try:
        if message.author.id in afk_users:
            afk_users.pop(message.author.id, None)
            await message.channel.send(f"👋 **{message.author.mention}** أهلاً رجعت! تم إلغاء الـAFK.", delete_after=5)
            save_data()
        for mention in message.mentions:
            if mention.id in afk_users:
                reason = afk_users[mention.id]
                await message.channel.send(f"💤 **{mention.display_name}** AFK: {reason}", delete_after=5)
    except Exception as e:
        print(f"[AFK ERROR] {e}", flush=True)

    if ch_id in ticket_characters_map and not message.author.bot:
        try:
            character_id = ticket_characters_map[ch_id]
            cat = get_category(character_id)
            if cat:
                persona = cat.get("persona", {})
                persona_name = persona.get("name", cat.get("name", "Support"))
                persona_title = persona.get("title", "")
                persona_icon = persona.get("icon", "🤖")
                persona_color = cat.get("color", 0x3498DB)

                async with message.channel.typing():
                    await asyncio.sleep(1)
                    response = generate_ai_response(character_id, message.content)
                    embed = discord.Embed(
                        description=response,
                        color=persona_color,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_author(
                        name=f"{persona_icon} {persona_name} • {persona_title}",
                        icon_url=message.guild.me.display_avatar.url
                    )
                    embed.set_footer(text=f"═══════════════════════════\nMAX BOT • {persona_name}\n═══════════════════════════")
                    await message.channel.send(embed=embed)
        except Exception as e:
            print(f"[TICKET AI ERROR] {e}", flush=True)


    # ── حماية السبام ──
    try:
        if get_prot(guild_id, "spam", ch_id):
            score = spam_detector.check(message.author.id)
            if score >= 1:
                try:
                    await message.delete()
                except:
                    pass
                await send_punishment_review(message.guild, message.author, "spam", score, detail=f"القناة: {message.channel.mention}\nLevel {score}")
                await bot.process_commands(message)
                return

        # ── حماية الفلود ──
        if get_prot(guild_id, "flood", ch_id):
            last_msg = spam_cache.get(f"last_{message.author.id}")
            if last_msg and last_msg["content"] == message.content and time.time() - last_msg["time"] < 3:
                try:
                    await message.delete()
                except:
                    pass
                await send_punishment_review(message.guild, message.author, "flood", 1, detail=f"القناة: {message.channel.mention}")
                await bot.process_commands(message)
                return
            spam_cache[f"last_{message.author.id}"] = {"content": message.content, "time": time.time()}

        # ── حماية المنشن الجماعي ──
        if get_prot(guild_id, "mention", ch_id):
            if len(message.mentions) >= 4:
                try:
                    await message.delete()
                except:
                    pass
                await send_punishment_review(message.guild, message.author, "mention", 1, detail=f"القناة: {message.channel.mention}\nعدد المنشن: {len(message.mentions)}")
                await bot.process_commands(message)
                return

        # ── حماية الكلمات السيئة ──
        if get_prot(guild_id, "badwords", ch_id):
            for word in bad_words_list:
                if word in message.content.lower():
                    try:
                        await message.delete()
                    except:
                        pass
                    await send_punishment_review(message.guild, message.author, "badwords", 1, detail=f"القناة: {message.channel.mention}\nالكلمة: ||{word}||")
                    await bot.process_commands(message)
                    return

        # ── حماية روابط الدعوة ──
        if get_prot(guild_id, "invite", ch_id):
            invite_regex = re.compile(r'(discord\.gg/[^\s]+|discord\.com/invite/[^\s]+)')
            if invite_regex.search(message.content):
                try:
                    await message.delete()
                except:
                    pass
                await send_punishment_review(message.guild, message.author, "invite", 1, detail=f"القناة: {message.channel.mention}\nالرابط: {message.content[:200]}")
                await bot.process_commands(message)
                return
    except Exception as e:
        print(f"[PROT ERROR] {e}", flush=True)

    # ── منع الروابط / linkblocker ──
    try:
        if link_blocker_enabled.get(guild_id, False):
            if LINK_REGEX.search(message.content):
                embed = LogEmbed.base("🔗 رابط محذوف", LogColors.PROTECT, guild=message.guild)
                LogEmbed.user_field(embed, message.author, "المرسل", thumb=True)
                LogEmbed.channel_field(embed, "القناة", message.channel)
                LogEmbed.evidence_field(embed, message=message)
                await send_log(guild_id, "protection_security", embed)
    except Exception as e:
        print(f"[LINK BLOCKER ERROR] {e}", flush=True)

    # ── نظام XP ──
    try:
        if len(message.content) > 3:
            xp_cooldown = spam_cache.get(f"xp_{message.author.id}")
            now = time.time()
            if not xp_cooldown or now - xp_cooldown > 30:
                spam_cache[f"xp_{message.author.id}"] = now
                guild_xp = xp_data.setdefault(guild_id, {})
                user_xp = guild_xp.setdefault(message.author.id, {"xp": 0, "level": 1})
                user_xp["xp"] += random.randint(5, 15)
                xp_needed = user_xp["level"] * 50
                if user_xp["xp"] >= xp_needed:
                    user_xp["xp"] -= xp_needed
                    user_xp["level"] += 1
                    lvl = user_xp["level"]
                    rewards = level_rewards.get(guild_id, {})
                    if lvl in rewards:
                        role = message.guild.get_role(rewards[lvl])
                        if role:
                            try:
                                await message.author.add_roles(role, reason="مكافأة مستوى")
                            except:
                                pass
                    embed = LogEmbed.base("⬆️ مستوى جديد!", LogColors.CREATE, guild=message.guild)
                    LogEmbed.user_field(embed, message.author, "العضو", thumb=True)
                    embed.add_field(name="المستوى", value=str(lvl))
                    await send_log(guild_id, "log_all", embed)
                save_data()
    except Exception as e:
        print(f"[XP ERROR] {e}", flush=True)

    try:
        embed = LogEmbed.base("💬 رسالة جديدة", LogColors.CREATE, guild=message.guild)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="👤 العضو", value=f"`{message.author.id}` {message.author.mention}", inline=True)
        embed.add_field(name="📍 الروم", value=f"{message.channel.mention}", inline=True)
        if message.content:
            content = message.content[:1000]
            embed.add_field(name="📝 الرسالة", value=content, inline=False)
        if message.attachments:
            atts = "\n".join([f"📎 [{a.filename}]({a.url})" for a in message.attachments[:3]])
            embed.add_field(name="📎 المرفقات", value=atts, inline=False)
        embed.add_field(name="🔗 الروابط", value=f"[قفز للرسالة]({message.jump_url})", inline=False)
        await send_log(guild_id, "log_new_message", embed, bot=bot)
    except Exception as e:
        pass

    await bot.process_commands(message)

@bot.event
async def on_member_update(before, after):
    guild_id = after.guild.id

    # Debug: role change detection
    if before.roles != after.roles:
        new_r = [r.name for r in after.roles if r not in before.roles]
        rem_r = [r.name for r in before.roles if r not in after.roles]
        print(f"[DEBUG] on_member_update: {after.name} +{new_r} -{rem_r}")

    # ── كشف تغيير الـ Timeout ──
    if before.timed_out_until != after.timed_out_until:
        embed = LogEmbed.base("⏱️ تغيير الـ Timeout", LogColors.TIMEOUT, guild=after.guild)
        LogEmbed.user_field(embed, after, "العضو", thumb=True)
        if after.timed_out_until:
            embed.add_field(name="المدة", value=f"حتى {after.timed_out_until.strftime('%Y-%m-%d %H:%M UTC')}")
        else:
            embed.add_field(name="الحالة", value="✅ تم إلغاء الـ Timeout")
        admin = await get_admin(after.guild, discord.AuditLogAction.member_update, after.id)
        LogEmbed.audit_field(embed, admin)
        await send_log(guild_id, "ban_kick_timeout", embed, admin=admin)

    # ── تغيير الرتب ──
    if before.roles != after.roles:
        admin = await get_admin(after.guild, discord.AuditLogAction.member_role_update, after.id)
        new_roles = [role for role in after.roles if role not in before.roles]
        removed_roles = [role for role in before.roles if role not in after.roles]
        high_role_obj = after.guild.get_role(HIGH_ROLE_ID)
        unlock_role = after.guild.get_role(UNLOCK_PROTECTION_ROLE_ID)
        async def is_authorized_for(role):
            if not admin:
                return False
            if admin.id == bot.user.id:
                return True
            if admin.id == YOUR_USER_ID:
                return True
            exempt = role_exempt_users.get(after.guild.id, [])
            if admin.id in exempt:
                return True
            if role.id == UNLOCK_PROTECTION_ROLE_ID:
                return admin.id == YOUR_USER_ID
            if not unlock_role:
                return False
            try:
                member_admin = admin if isinstance(admin, discord.Member) else (after.guild.get_member(admin.id) or await after.guild.fetch_member(admin.id))
                return unlock_role in member_admin.roles
            except:
                return False

        def is_protected(role):
            p = protections.get(after.guild.id, {})
            return p.get("role", True)

        print(f"[DEBUG] admin={admin} (id={admin.id if admin else 'N/A'}) high_role_obj={'exists' if high_role_obj else 'NONE'} unlock_role={'exists' if unlock_role else 'NONE'}")

        # ── حماية إضافة الرتب ──
        for role in new_roles:
            # ── تتبع تغييرات الرتب من البوت نفسه ──
            key = (after.guild.id, after.id, role.id)
            if key in _pending_role_changes:
                _pending_role_changes.discard(key)
                continue
            protected = is_protected(role)
            print(f"[DEBUG] new_role: {role.name}(pos={role.position}) protected={protected}")
            if not protected:
                continue
            embed = LogEmbed.base("🛡️ إعطاء رتبة", LogColors.PROTECT, guild=after.guild)
            LogEmbed.user_field(embed, after, "العضو", thumb=True)
            embed.add_field(name="الرتبة", value=role.mention)
            LogEmbed.audit_field(embed, admin)
            authorized = await is_authorized_for(role)
            print(f"[DEBUG] new_role: {role.name}(id={role.id}) authorized={authorized}")
            if authorized:
                embed.add_field(name="الحالة", value=f"✅ مصرح به — {admin.mention if admin else 'النظام'}")
                print(f"[DEBUG] AUTHORIZED: {role.name} given to {after.name}")
            else:
                try:
                    await after.remove_roles(role, reason="حماية: غير مصرح بإعطاء الرتبة")
                    embed.add_field(name="الإجراء", value="🛡️ تم سحب الرتبة تلقائياً")
                    print(f"[DEBUG] REMOVED: {role.name} from {after.name}")
                except Exception as e:
                    embed.add_field(name="الإجراء", value=f"❌ فشل سحب الرتبة: {e}")
                    print(f"[DEBUG] FAILED: remove {role.name} from {after.name}: {e}")
            await send_log(guild_id, "protection_security", embed, admin=admin)

        # ── حماية سحب الرتب ──
        for role in removed_roles:
            if not is_protected(role):
                print(f"[DEBUG] SKIP removed_role: {role.name} (not protected)")
                continue
            authorized = await is_authorized_for(role)
            print(f"[DEBUG] removed_role: {role.name}(id={role.id}) authorized={authorized}")
            embed = LogEmbed.base("🛡️ سحب رتبة", LogColors.PROTECT, guild=after.guild)
            LogEmbed.user_field(embed, after, "العضو", thumb=True)
            embed.add_field(name="الرتبة", value=role.mention)
            LogEmbed.audit_field(embed, admin)
            if authorized:
                embed.add_field(name="الحالة", value=f"✅ مصرح به — {admin.mention if admin else 'النظام'}")
            else:
                try:
                    await after.add_roles(role, reason="حماية: غير مصرح بسحب الرتبة")
                    embed.add_field(name="الإجراء", value="🛡️ تم إعادة الرتبة تلقائياً")
                except Exception as e:
                    embed.add_field(name="الإجراء", value=f"❌ فشل إعادة الرتبة: {e}")
            await send_log(guild_id, "protection_security", embed, admin=admin)

        # ── سجل عام لجميع إضافات/سحب الرتب ──
        added_mentions = [r.mention for r in new_roles]
        removed_mentions = [r.mention for r in removed_roles]
        if added_mentions or removed_mentions:
            embed = LogEmbed.base("🎭 تحديث رتب", LogColors.ROLE, guild=after.guild)
            LogEmbed.user_field(embed, after, "العضو", thumb=True)
            if added_mentions:
                embed.add_field(name="✅ أضيفت", value=", ".join(added_mentions), inline=False)
            if removed_mentions:
                embed.add_field(name="❌ سحبت", value=", ".join(removed_mentions), inline=False)
            LogEmbed.audit_field(embed, admin)
            await send_log(guild_id, "log_role", embed, admin=admin)

    # ── تغيير اللقب ──
    if before.nick != after.nick:
        admin = await get_admin(after.guild, discord.AuditLogAction.member_update, after.id)
        embed = LogEmbed.base("🏷️ تغيير اسم مستعار", LogColors.WARN, guild=after.guild)
        LogEmbed.user_field(embed, after, "العضو", thumb=True)
        LogEmbed.diff_field(embed, "التغيير", before.nick or after.name, after.nick or after.name)
        LogEmbed.audit_field(embed, admin)
        await send_log(guild_id, "log_nickname", embed, admin=admin)

@bot.event
async def on_member_ban(guild, user):
    embed = LogEmbed.base("🔨 حظر نهائي", LogColors.PROTECT, guild=guild)
    LogEmbed.user_field(embed, user, "المحظور", thumb=True)
    account_age = (discord.utils.utcnow() - user.created_at).days
    embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم {'⚠️ حساب جديد!' if account_age < 7 else '✅'}", inline=True)
    try:
        entry = None
        async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if e.target and e.target.id == user.id:
                entry = e
                break
        admin = entry.user if entry else None
        LogEmbed.audit_field(embed, admin)
        reason = getattr(entry, "reason", None) if entry else None
        LogEmbed.details_field(embed, reason=reason, action="حظر نهائي من السيرفر")
    except discord.Forbidden:
        LogEmbed.audit_field(embed, None)
    await send_log(guild.id, "ban_kick_timeout", embed, admin=admin)

@bot.event
async def on_member_unban(guild, user):
    embed = LogEmbed.base("✅ إلغاء الحظر", LogColors.CREATE, guild=guild)
    LogEmbed.user_field(embed, user, "المستخدم", thumb=True)
    try:
        entry = None
        async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
            if e.target and e.target.id == user.id:
                entry = e
                break
        admin = entry.user if entry else None
        LogEmbed.audit_field(embed, admin)
        reason = getattr(entry, "reason", None) if entry else None
        if reason:
            LogEmbed.reason_field(embed, reason)
    except discord.Forbidden:
        LogEmbed.audit_field(embed, None)
    await send_log(guild.id, "ban_kick_timeout", embed, admin=admin)

@bot.event
async def on_member_remove(member):
    if not hasattr(member, 'id') or not hasattr(member, 'roles'):
        return
    roles = [r.mention for r in member.roles if not r.is_default()]
    roles_text = " | ".join(roles) if roles else "لا يوجد"
    if len(roles_text) > 1024:
        roles_text = roles_text[:1021] + "..."

    embed_leave = LogEmbed.base("🚪 خروج عضو", LogColors.LEAVE, guild=member.guild)
    LogEmbed.user_field(embed_leave, "العضو", member, thumb=True)
    embed_leave.add_field(name="🎭 الرتب", value=roles_text, inline=False)
    if member.joined_at:
        time_in_server = discord.utils.utcnow() - member.joined_at
        days = time_in_server.days
        hours, remainder = divmod(time_in_server.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days} يوم، {hours} ساعة، {minutes} دقيقة"
        elif hours > 0:
            duration_str = f"{hours} ساعة، {minutes} دقيقة"
        else:
            duration_str = f"{minutes} دقيقة"
        embed_leave.add_field(name="⏱️ مدة الإقامة", value=duration_str, inline=True)
    is_booster = any(r.id == member.guild.premium_subscriber_role.id for r in member.roles if member.guild.premium_subscriber_role) if member.guild.premium_subscriber_role else False
    if is_booster:
        embed_leave.add_field(name="💎 Nitro Booster", value="✅ كان Booster", inline=True)
    await send_log(member.guild.id, "log_leave", embed_leave)

    # VIP leave -> log_admin_leave
    if member.get_role(HIGH_ROLE_ID):
        embed_vip = LogEmbed.base("⭐ مغادرة VIP", LogColors.WARN, guild=member.guild)
        LogEmbed.user_field(embed_vip, "العضو", member, thumb=True)
        embed_vip.add_field(name="🎭 الرتب", value=roles_text, inline=False)
        await send_log(member.guild.id, "log_admin_leave", embed_vip)

    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target and hasattr(entry.target, 'id') and entry.target.id == member.id:
                embed = LogEmbed.base("👢 طرد عضو", LogColors.TIMEOUT, guild=member.guild)
                LogEmbed.user_field(embed, member, "المطرود", thumb=True)
                embed.add_field(name="🎭 الرتب", value=roles_text, inline=False)
                if hasattr(entry.user, 'id'):
                    LogEmbed.audit_field(embed, entry.user)
                LogEmbed.reason_field(embed, entry.reason)
                await send_log(member.guild.id, "ban_kick_timeout", embed, admin=entry.user if hasattr(entry.user, 'id') else None)
                break
    except discord.Forbidden:
        print(f"[PERMISSIONS ERROR] Cannot check kick audit log in {member.guild.name}")
    except Exception as e:
        print(f"[ERROR] on_member_remove audit check: {e}")

class CharacterSelectView(View):
    def __init__(self, user_id, guild_id, ticket_num):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.guild_id = guild_id
        self.ticket_num = ticket_num
        self.selected = False
        for cat_id, cat_data in TICKET_CATEGORIES.items():
            btn = discord.ui.Button(
                label=f"{cat_data['emoji']} {cat_data['name']}",
                style=discord.ButtonStyle.blurple,
                custom_id=f"cat_{cat_id}",
                row=0
            )
            btn.callback = self._make_callback(cat_id)
            self.add_item(btn)

    def _make_callback(self, cat_id):
        async def callback(interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ هذا الزر مخصص لصاحب التذكرة!", ephemeral=True)
                return
            self.selected = True
            ticket_characters_map[interaction.channel.id] = cat_id
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            cat = get_category(cat_id)

            persona = cat.get("persona", {})
            persona_name = persona.get("name", cat.get("name", "Support"))
            persona_title = persona.get("title", "")
            persona_icon = persona.get("icon", "🤖")
            persona_greeting = persona.get("greeting", cat.get("greeting", "مرحباً! كيف أقدر أساعدك؟"))

            embed = discord.Embed(
                title=f"{persona_icon} {persona_name}",
                description=persona_greeting,
                color=cat['color'],
                timestamp=datetime.now(timezone.utc)
            )
            if cat.get('image'):
                embed.set_image(url=cat['image'])
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text=f"═══════════════════════════\nMAX BOT • {persona_name} • {persona_title}\n═══════════════════════════")

            await interaction.followup.send(content="@here @everyone")
            await interaction.followup.send(embed=embed)

            # Reveal channel to roles that have access to this category
            cat_name_map = {"question": "سؤال", "problem": "مشكلة", "complaint": "شكوى", "programming": "برمجة", "help": "مساعدة"}
            readable_cat = cat_name_map.get(cat_id, cat_id)
            guild = interaction.guild
            guild_key = str(guild.id)
            access = TICKET_ROLE_ACCESS.get(guild_key, {})
            ch = interaction.channel
            for role_id_str, allowed_cats in access.items():
                if readable_cat in allowed_cats:
                    role = guild.get_role(int(role_id_str))
                    if role:
                        try:
                            await ch.set_permissions(role, view_channel=True, send_messages=True)
                        except:
                            pass

            # Also allow admin role and ticket manager role
            admin_role = guild.get_role(ADMIN_ROLE_ID)
            if admin_role:
                try:
                    await ch.set_permissions(admin_role, view_channel=True, send_messages=True)
                except:
                    pass
            tkt_mgr_role = guild.get_role(TICKET_MANAGER_ROLE_ID)
            if tkt_mgr_role:
                try:
                    await ch.set_permissions(tkt_mgr_role, view_channel=True, send_messages=True)
                except:
                    pass

            try:
                cat_log_ch = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
                if cat_log_ch:
                    cat_log_embed = discord.Embed(
                        title=f"{persona_icon} تم اختيار التصنيف — {persona_name}",
                        description=(
                            f"═══════════════════════════\n"
                            f"🎫 𝗧𝗜𝗖𝗞𝗘𝗧 𝗖𝗔𝗧𝗘𝗚𝗢𝗥𝗬\n"
                            f"═══════════════════════════\n\n"
                            f"├─ العضو: {interaction.user.mention}\n"
                            f"├─ التصنيف: {cat['emoji']} **{cat['name']}**\n"
                            f"├─ الشخصية: {persona_icon} **{persona_name}**\n"
                            f"├─ القناة: {interaction.channel.mention}\n"
                            f"└─ الوقت: <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n\n"
                            f"═══════════════════════════"
                        ),
                        color=cat['color'],
                        timestamp=datetime.now(timezone.utc)
                    )
                    cat_log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    cat_log_embed.set_footer(text="═══════════════════════════\nMAX BOT • لوق التذاكر\n═══════════════════════════")
                    await cat_log_ch.send(embed=cat_log_embed)
            except:
                pass
        return callback

class TicketClosedView(View):
    def __init__(self, channel_id, guild_id, closed_by_id, transcript_text, ticket_name):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.closed_by_id = closed_by_id
        self.transcript_text = transcript_text
        self.ticket_name = ticket_name

    @discord.ui.button(label="📄 Transcript", style=discord.ButtonStyle.blurple, custom_id="transcript_btn_v2")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        file_data = io.BytesIO(self.transcript_text.encode('utf-8-sig'))
        transcript_file = discord.File(file_data, filename=f"transcript-{self.ticket_name}.txt")
        await interaction.response.send_message(file=transcript_file, ephemeral=True)

    @discord.ui.button(label="🔓 Open", style=discord.ButtonStyle.green, custom_id="reopen_btn_v2")
    async def reopen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ للمسؤولين فقط!", ephemeral=True)
            return
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ القناة غير موجودة! ربما تم حذفها.", ephemeral=True)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        ADMIN_ROLE_ID = 1508798210368606208
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        try:
            await channel.edit(overwrites=overwrites, sync_permissions=True)
        except:
            pass
        await channel.send(f"🔓 تم فتح التذكرة بواسطة {interaction.user.mention}")

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.red, custom_id="delete_ticket_btn_v2")
    async def delete_ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ للمسؤولين فقط!", ephemeral=True)
            return
        await interaction.response.send_message("⏳ جاري حذف التذكرة...")
        await asyncio.sleep(2)
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            try:
                await channel.delete(reason=f"Deleted by {interaction.user}")
            except:
                pass
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

async def close_ticket_logic(channel, closed_by):
    category_id = ticket_characters_map.pop(channel.id, None)
    cat_data = TICKET_CATEGORIES.get(category_id, {}) if category_id else {}
    cat_name = cat_data.get("name", "غير محدد")
    persona = cat_data.get("persona", {})
    persona_name = persona.get("name", "Support")
    persona_icon = persona.get("icon", "🤖")

    log_lines = []
    async for message in channel.history(limit=5000, oldest_first=True):
        time_str = message.created_at.strftime('%H:%M:%S')
        if message.author.bot:
            log_lines.append(f"[{time_str}] 🤖 {message.author.display_name}: {message.content[:200]}")
        else:
            log_lines.append(f"[{time_str}] 👤 {message.author}: {message.content[:200]}")

    user_msgs = sum(1 for m in log_lines if "👤" in m)
    bot_msgs = sum(1 for m in log_lines if "🤖" in m)
    if len(log_lines) >= 2:
        first_time = log_lines[0].split("]")[0].replace("[", "")
        last_time = log_lines[-1].split("]")[0].replace("[", "")
        try:
            fmt = '%H:%M:%S'
            t1 = datetime.strptime(first_time, fmt)
            t2 = datetime.strptime(last_time, fmt)
            duration = (t2 - t1).total_seconds() / 60
            duration_str = f"{duration:.0f} دقيقة"
        except:
            duration_str = "غير معروف"
    else:
        duration_str = "غير معروف"

    transcript_text = f"═══════════════════════════════════════════\n"
    transcript_text += f"🎫 𝗧𝗜𝗖𝗞𝗘𝗧 𝗧𝗥𝗔𝗡𝗦𝗖𝗥𝗜𝗣𝗧: {channel.name}\n"
    transcript_text += f"═══════════════════════════════════════════\n"
    transcript_text += f"👤 أغلق بواسطة: {closed_by}\n"
    transcript_text += f"🤖 التصنيف: {cat_name}\n"
    transcript_text += f"🎯 الشخصية: {persona_icon} {persona_name}\n"
    transcript_text += f"🕐 التاريخ: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n"
    transcript_text += f"═══════════════════════════════════════════\n\n"
    transcript_text += "\n".join(log_lines)

    closed_by_top_role = closed_by.top_role.mention if closed_by.top_role != closed_by.guild.default_role else "لا يوجد"

    closed_embed = discord.Embed(
        title=f"🔒 𝗧𝗜𝗖𝗞𝗘𝗧 𝗖𝗟𝗢𝗦𝗘𝗗 — {persona_icon} {persona_name}",
        description=(
            f"═══════════════════════════\n"
            f"🔒 **Ticket Closed by:** {closed_by.mention}\n"
            f"👑 **رتبته:** {closed_by_top_role}\n"
            f"═══════════════════════════\n\n"
            f"├─ القناة: **{channel.name}**\n"
            f"├─ التصنيف: **{cat_name}**\n"
            f"├─ شخصية الدعم: {persona_icon} **{persona_name}**\n"
            f"├─ عدد الرسائل: **{len(log_lines)}** ({user_msgs} عضو + {bot_msgs} دعم)\n"
            f"├─ مدة المحادثة: **{duration_str}**\n"
            f"├─ الوقت: <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n"
            f"└─ الحالة: **مغلقة — في انتظار الإجراء**\n\n"
            f"═══════════════════════════\n"
            f"### 🎛️ Support Team Ticket Controls\n"
            f"═══════════════════════════\n"
            f"**📄 Transcript** — تحميل سجل المحادثة\n"
            f"**🔓 Open** — فتح التذكرة مرة أخرى\n"
            f"**🗑️ Delete** — حذف التذكرة نهائياً\n"
            f"═══════════════════════════"
        ),
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc)
    )
    closed_embed.set_thumbnail(url=closed_by.display_avatar.url)
    closed_embed.set_footer(text=f"═══════════════════════════\nMAX BOT • {persona_name} — لوق التذاكر\n═══════════════════════════")

    # Send close message + buttons in ticket channel
    close_msg = discord.Embed(
        title="🔒 تم إغلاق التذكرة",
        description=(
            f"**تم الإغلاق بواسطة:** {closed_by.mention}\n"
            f"**رتبته:** {closed_by_top_role}\n"
            f"**الشخصية:** {persona_icon} {persona_name}\n\n"
            f"### 🎛️ Support Team Ticket Controls\n"
            f"**📄 Transcript** — تحميل السجل\n"
            f"**🔓 Open** — فتح التذكرة\n"
            f"**🗑️ Delete** — حذف التذكرة"
        ),
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc)
    )
    try:
        view = TicketClosedView(channel.id, channel.guild.id, closed_by.id, transcript_text, channel.name)
        await channel.send(embed=close_msg, view=view)
    except:
        pass

    # Kick the ticket opener from the channel
    guild = channel.guild
    for member in list(channel.overwrites.keys()):
        if isinstance(member, discord.Member) and member != guild.me and not member.bot and member != closed_by:
            try:
                await channel.set_permissions(member, view_channel=False, send_messages=False, attach_files=False)
            except:
                pass

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False)}
    bot_member = guild.me
    overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    try:
        await channel.edit(overwrites=overwrites)
    except:
        pass

    # Send LOG to ticket log channel
    log_ch = guild.get_channel(TICKET_LOG_CHANNEL_ID)
    print(f"[TICKET CLOSE] log_ch={log_ch} (ID={TICKET_LOG_CHANNEL_ID}), guild={guild.name}")
    if log_ch:
        try:
            await log_ch.send(embed=closed_embed)
            print(f"[TICKET CLOSE] LOG sent to #{log_ch.name}")
        except Exception as e:
            print(f"[TICKET CLOSE] ERROR sending log: {e}")
    else:
        print(f"[TICKET CLOSE] LOG channel NOT FOUND for guild {guild.name} (ID={TICKET_LOG_CHANNEL_ID})")

class CloseConfirmView(View):
    def __init__(self, channel, closed_by):
        super().__init__(timeout=60)
        self.channel = channel
        self.closed_by = closed_by

    @discord.ui.button(label="✅ نعم، أغلق", style=discord.ButtonStyle.red, custom_id="confirm_close")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.closed_by.id:
            await interaction.response.send_message("❌ هذا الزر مخصص لمن يريد الإغلاق!", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("⏳ جاري حفظ السجل وقفل التذكرة...")
        await close_ticket_logic(self.channel, self.closed_by)

    @discord.ui.button(label="❌ لا، ألغِ", style=discord.ButtonStyle.gray, custom_id="cancel_close")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.closed_by.id:
            await interaction.response.send_message("❌ هذا الزر مخصص لمن يريد الإغلاق!", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="✅ تم إلغاء الإغلاق.", view=None)

class StaffReminderView(View):
    def __init__(self, channel_id, staff_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.staff_id = staff_id

    @discord.ui.button(label="📝 ذكّرني لاحقاً", style=discord.ButtonStyle.secondary, custom_id="staff_reminder_btn")
    async def staff_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.staff_id:
            await interaction.response.send_message("❌ هذا الزر لك فقط!", ephemeral=True)
            return
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ القناة غير موجودة!", ephemeral=True)
            return
        embed = discord.Embed(
            title="⏰ تذكير — تذكرة مفتوحة",
            description=(
                f"**القناة:** {channel.mention}\n"
                f"**أنت مسؤول عن هذه التذكرة**\n\n"
                f"يرجى مراجعتها والرد على العضو."
            ),
            color=0xF39C12
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • تذكير\n═══════════════════════════")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class MemberReminderView(View):
    def __init__(self, channel_id, member_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.member_id = member_id

    @discord.ui.button(label="📝 تذكير بالرد", style=discord.ButtonStyle.secondary, custom_id="member_reminder_btn")
    async def member_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member_id:
            await interaction.response.send_message("❌ هذا الزر لك فقط!", ephemeral=True)
            return
        embed = discord.Embed(
            title="⏰ تذكير",
            description=(
                f"**يمكنك كتابة رسالتك الآن!**\n\n"
                f"اكتب مشكلتك أو سؤالك وسنرد عليك في أقرب وقت."
            ),
            color=0xF39C12
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • تذكير\n═══════════════════════════")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TicketActions(View):
    def __init__(self, ticket_num=0, character_id=None):
        super().__init__(timeout=None)
        self.ticket_num = ticket_num
        self.character_id = character_id

    @discord.ui.button(label="استلام 🙋‍♂️", style=discord.ButtonStyle.blurple, custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if admin_role in interaction.user.roles or interaction.user.guild_permissions.administrator:
            button.disabled = True
            button.label = "تم الاستلام ✅"
            button.style = discord.ButtonStyle.gray
            await interaction.response.edit_message(view=self)
            top_role = interaction.user.top_role.mention if interaction.user.top_role != interaction.guild.default_role else "لا يوجد"
            await interaction.followup.send(f"✅ تمت استلام التذكرة بواسطة المسؤول: {interaction.user.mention}\n👑 أعلى رتبة: {top_role}")

            # Send reminder embed to staff in the ticket channel
            char_id = ticket_characters_map.get(interaction.channel.id)
            persona = TICKET_CATEGORIES.get(char_id, {}).get("persona", {}) if char_id else {}
            persona_name = persona.get("name", "Support")
            persona_icon = persona.get("icon", "🤖")

            reminder_embed = discord.Embed(
                title=f"📋 تذكير بالتذكرة — {persona_icon} {persona_name}",
                description=(
                    f"**تم الاستلام بواسطة:** {interaction.user.mention}\n"
                    f"**أعلى رتبة:** {top_role}\n\n"
                    f"**الوقت:** <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n\n"
                    f"⚠️ يرجى مراجعة التذكرة والرد على العضو في أقرب وقت."
                ),
                color=0xF39C12,
                timestamp=datetime.now(timezone.utc)
            )
            reminder_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            reminder_embed.set_footer(text=f"═══════════════════════════\nMAX BOT • تذكير التذاكر\n═══════════════════════════")

            # Add reminder button for the staff
            reminder_view = StaffReminderView(interaction.channel.id, interaction.user.id)
            await interaction.followup.send(embed=reminder_embed, view=reminder_view)

            try:
                claim_log_ch = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
                if claim_log_ch:
                    char_id = ticket_characters_map.get(interaction.channel.id)
                    persona = TICKET_CATEGORIES.get(char_id, {}).get("persona", {}) if char_id else {}
                    persona_name = persona.get("name", "غير محدد")
                    persona_icon = persona.get("icon", "🤖")
                    claim_embed = discord.Embed(
                        title=f"🙋‍♂️ تم استلام التذكرة — {persona_icon} {persona_name}",
                        description=(
                            f"═══════════════════════════\n"
                            f"🎫 𝗧𝗜𝗖𝗞𝗘𝗧 𝗖𝗟𝗔𝗜𝗠𝗘𝗗\n"
                            f"═══════════════════════════\n\n"
                            f"├─ القناة: {interaction.channel.mention}\n"
                            f"├─ المسؤول: {interaction.user.mention}\n"
                            f"├─ أعلى رتبة: {top_role}\n"
                            f"├─ شخصية الدعم: {persona_icon} **{persona_name}**\n"
                            f"└─ الوقت: <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n\n"
                            f"═══════════════════════════"
                        ),
                        color=0x3498DB,
                        timestamp=datetime.now(timezone.utc)
                    )
                    claim_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    claim_embed.set_footer(text=f"═══════════════════════════\nMAX BOT • {persona_name} — لوق التذاكر\n═══════════════════════════")
                    await claim_log_ch.send(embed=claim_embed)
            except:
                pass
        else:
            await interaction.response.send_message("❌ هذا الزر مخصص للمسؤولين فقط!", ephemeral=True)

    @discord.ui.button(label="إغلاق 🔒", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠️ تأكيد الإغلاق",
            description=(
                "```\n"
                "╔══════════════════════════════════╗\n"
                "║  ⚠️ 𝗖𝗢𝗡𝗙𝗜𝗥𝗠 𝗖𝗟𝗢𝗦𝗘              ║\n"
                "╚══════════════════════════════════╝\n"
                "```\n"
                f"**هل أنت متأكد من إغلاق التذكرة؟**\n\n"
                "• سيتم حفظ سجل المحادثة\n"
                "• سيتم حذف القناة نهائياً\n\n"
                "### اختر:"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • تأكيد الإغلاق\n═══════════════════════════")
        await interaction.response.send_message(embed=embed, view=CloseConfirmView(interaction.channel, interaction.user), ephemeral=False)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💻 𝐓𝐈𝐂𝐊𝐄𝐓", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        global ticket_counter
        guild = interaction.guild
        user = interaction.user

        if not hasattr(bot, '_ticket_cooldowns'):
            bot._ticket_cooldowns = {}
        cd_key = f"{guild.id}_{user.id}"
        now_ts = datetime.now(timezone.utc).timestamp()
        if cd_key in bot._ticket_cooldowns:
            elapsed = now_ts - bot._ticket_cooldowns[cd_key]
            if elapsed < 60:
                remain = int(60 - elapsed)
                await interaction.response.send_message(f"❌ انتظر **{remain}** ثانية قبل فتح تذكرة جديدة!", ephemeral=True)
                return

        for ch in guild.text_channels:
            if ch.name.startswith("ticket") and ch.category and ch.category.name == "🎫 التذاكر":
                async for m in ch.history(limit=5):
                    if m.author.id == user.id:
                        await interaction.response.send_message(f"❌ لديك تذكرة مفتوحة بالفعل: {ch.mention}", ephemeral=True)
                        return

        bot._ticket_cooldowns[cd_key] = now_ts

        cat_id = ticket_categories_data.get(str(guild.id), 0)
        category = guild.get_channel(cat_id) if cat_id else None
        if not category:
            for ch in guild.categories:
                if ch.name == "🎫 التذاكر":
                    category = ch
                    cat_id = ch.id
                    ticket_categories_data[str(guild.id)] = cat_id
                    break
        if not category:
            category = await guild.create_category("🎫 التذاكر")
            cat_id = category.id
            ticket_categories_data[str(guild.id)] = cat_id

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)
        }
        # Owner can always see tickets
        owner_member = guild.get_member(YOUR_USER_ID)
        if owner_member:
            overwrites[owner_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

        channel_name = f"ticket 📩-{ticket_counter}"
        channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)

        if TICKET_ROLE_ID:
            ticket_role = guild.get_role(TICKET_ROLE_ID)
            if ticket_role:
                await channel.set_permissions(ticket_role, view_channel=True, send_messages=True, attach_files=True)

        ticket_counter += 1

        await interaction.response.send_message(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)

        cat_embed = discord.Embed(
            title="🎫 𝐓𝐈𝐂𝐊𝐄𝐓 — اختر التصنيف",
            description="اختر التصنيف المناسب لمشكلتك:",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        cat_embed.set_footer(text="═══════════════════════════\nMAX BOT • نظام التذاكر الذكي\n═══════════════════════════")
        await channel.send(embed=cat_embed, view=CharacterSelectView(user.id, guild.id, ticket_counter - 1))

        info_embed = discord.Embed(
            title="📋 𝐓𝐈𝐂𝐊𝐄𝐓 𝐈𝐍𝐅𝐎",
            description=(
                f"**صاحب التذكرة:** {user.mention}\n"
                f"**رقم التذكرة:** #{ticket_counter - 1}\n"
                f"**الوقت:** <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n\n"
                "اكتب مشكلتك أو استفسارك هنا..."
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        info_embed.set_thumbnail(url=user.display_avatar.url)
        info_embed.set_footer(text="═══════════════════════════\nMAX BOT • نظام التذاكر الذكي\n═══════════════════════════")
        await channel.send(embed=info_embed, view=TicketActions(ticket_num=ticket_counter - 1))

        # Member reminder button
        member_reminder_embed = discord.Embed(
            title="📝 محتاج مساعدة؟",
            description=(
                f"**اكتب رسالتك هنا** وسنرد عليك في أقرب وقت!\n\n"
                f"💡 يمكنك الضغط على الزر أدناه لتذكيرنا بالرد عليك."
            ),
            color=0xF39C12
        )
        member_reminder_embed.set_footer(text="═══════════════════════════\nMAX BOT • تذكير\n═══════════════════════════")
        await channel.send(embed=member_reminder_embed, view=MemberReminderView(channel.id, user.id))

        try:
            log_ch = guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_ch:
                log_embed = discord.Embed(
                    title="🎫 تم فتح تذكرة جديدة",
                    description=(
                        f"═══════════════════════════\n"
                        f"🎫 𝗡𝗘𝗪 𝗧𝗜𝗖𝗞𝗘𝗧\n"
                        f"═══════════════════════════\n\n"
                        f"├─ العضو: {user.mention}\n"
                        f"├─ رقم التذكرة: #{ticket_counter - 1}\n"
                        f"├─ القناة: {channel.mention}\n"
                        f"└─ الوقت: <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n\n"
                        f"═══════════════════════════"
                    ),
                    color=0x2ECC71,
                    timestamp=datetime.now(timezone.utc)
                )
                log_embed.set_thumbnail(url=user.display_avatar.url)
                log_embed.set_footer(text="═══════════════════════════\nMAX BOT • لوق التذاكر\n═══════════════════════════")
                await log_ch.send(embed=log_embed)
        except:
            pass

@bot.command(name="setticket")
@commands.has_permissions(administrator=True)
async def setticket_prefix(ctx):
    global ticket_image
    guild = ctx.guild
    saved_cat_id = ticket_categories_data.get(str(guild.id), 0)

    category = guild.get_channel(saved_cat_id) if saved_cat_id else None
    if not category:
        for ch in guild.categories:
            if ch.name == "🎫 التذاكر":
                category = ch
                saved_cat_id = ch.id
                ticket_categories_data[str(guild.id)] = saved_cat_id
                break
    if not category:
        category = await guild.create_category("🎫 التذاكر")
        ticket_categories_data[str(guild.id)] = category.id
    embed = discord.Embed(
        title=" ",
        description=(
            "```\n"
            "╔══════════════════════════════════╗\n"
            "║     🎫 𝐓𝐈𝐂𝐊𝐄𝐓 𝐒YSTEM           ║\n"
            "╚══════════════════════════════════╝\n"
            "```\n"
            "### 🎯 **اختر التصنيف**\n\n"
            "```\n"
            "┌─────────────────────────────────┐\n"
            "│                                 │\n"
            "│  ❓  سؤال                       │\n"
            "│     لديك سؤال؟ نحن هنا!        │\n"
            "│                                 │\n"
            "│  🔧  مشكلة                      │\n"
            "│     واجهتك مشكلة؟ حلها معنا!   │\n"
            "│                                 │\n"
            "│  📢  شكوى                       │\n"
            "│     ملاحظاتك تهمنا!             │\n"
            "│                                 │\n"
            "│  💻  طلب برمجة                  │\n"
            "│     تريد ميزة جديدة؟           │\n"
            "│                                 │\n"
            "│  🤝  مساعدة                     │\n"
            "│     نحن هنا لمساعدتك!          │\n"
            "│                                 │\n"
            "└─────────────────────────────────┘\n"
            "```\n"
            "### ✨ **اضغط الزر لفتح تذكرة**\n\n"
            "```\n"
            "╔══════════════════════════════════╗\n"
            "║   MAX BOT • نظام التذاكر الذكي   ║\n"
            "╚══════════════════════════════════╝\n"
            "```"
        ),
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc)
    )
    if ticket_image:
        embed.set_image(url=ticket_image)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • نظام التذاكر الذكي\n═══════════════════════════")
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    # Create LOG-تكت channel if needed (same as slash command)
    global TICKET_LOG_CHANNEL_ID
    log_tkt_id = ticket_log_channels_loaded.get(guild.id, 0)
    log_tkt_ch = guild.get_channel(log_tkt_id) if log_tkt_id else None

    if not log_tkt_ch:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        admin_role = guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        tkt_mgr_role = guild.get_role(TICKET_MANAGER_ROLE_ID)
        if tkt_mgr_role:
            overwrites[tkt_mgr_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        log_tkt_ch = await guild.create_text_channel("📋 LOG-تكت", overwrites=overwrites, category=category)
        ticket_log_channels_loaded[guild.id] = log_tkt_ch.id
        await log_tkt_ch.send(embed=discord.Embed(
            title="📋 LOG-تكت — تم الإنشاء",
            description=f"قناة لوق التذاكر جاهزة.\nجميع عمليات فتح/إغلاق التذاكر ستظهر هنا.",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        ))

    TICKET_LOG_CHANNEL_ID = log_tkt_ch.id

    await ctx.send(embed=embed, view=TicketView())

@bot.tree.command(name="setticket", description="إنشاء لوحة التذاكر")
@discord.app_commands.default_permissions(administrator=True)
async def setticket(interaction: discord.Interaction):
    global ticket_image, TICKET_LOG_CHANNEL_ID
    guild = interaction.guild
    cat_id = ticket_categories_data.get(str(guild.id), 0)
    if not cat_id:
        cat_id = TICKET_CATEGORY_ID

    category = guild.get_channel(cat_id)
    if not category:
        category = await guild.create_category("🎫 التذاكر")
        ticket_categories_data[str(guild.id)] = category.id

    log_tkt_id = ticket_log_channels_loaded.get(guild.id, 0)
    log_tkt_ch = guild.get_channel(log_tkt_id) if log_tkt_id else None

    if not log_tkt_ch:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        admin_role = guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        tkt_mgr_role = guild.get_role(TICKET_MANAGER_ROLE_ID)
        if tkt_mgr_role:
            overwrites[tkt_mgr_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        log_tkt_ch = await guild.create_text_channel("📋 LOG-تكت", overwrites=overwrites, category=category)
        ticket_log_channels_loaded[guild.id] = log_tkt_ch.id
        await log_tkt_ch.send(embed=discord.Embed(
            title="📋 LOG-تكت — تم الإنشاء",
            description=f"قناة لوق التذاكر جاهزة.\nجميع عمليات فتح/إغلاق التذاكر ستظهر هنا.",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        ))

    TICKET_LOG_CHANNEL_ID = log_tkt_ch.id

    embed = discord.Embed(
        title=" ",
        description=(
            "```\n"
            "╔══════════════════════════════════╗\n"
            "║     🎫 𝐓𝐈𝐂𝐊𝐄𝐓 𝐒YSTEM           ║\n"
            "╚══════════════════════════════════╝\n"
            "```\n"
            "### 🎯 **اختر التصنيف**\n\n"
            "```\n"
            "┌─────────────────────────────────┐\n"
            "│                                 │\n"
            "│  ❓  سؤال                       │\n"
            "│     لديك سؤال؟ نحن هنا!        │\n"
            "│                                 │\n"
            "│  🔧  مشكلة                      │\n"
            "│     واجهتك مشكلة؟ حلها معنا!   │\n"
            "│                                 │\n"
            "│  📢  شكوى                       │\n"
            "│     ملاحظاتك تهمنا!             │\n"
            "│                                 │\n"
            "│  💻  طلب برمجة                  │\n"
            "│     تريد ميزة جديدة؟           │\n"
            "│                                 │\n"
            "│  🤝  مساعدة                     │\n"
            "│     نحن هنا لمساعدتك!          │\n"
            "│                                 │\n"
            "└─────────────────────────────────┘\n"
            "```\n"
            "### ✨ **اضغط الزر لفتح تذكرة**\n\n"
            "```\n"
            "╔══════════════════════════════════╗\n"
            "║   MAX BOT • نظام التذاكر الذكي   ║\n"
            "╚══════════════════════════════════╝\n"
            "```"
        ),
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc)
    )
    if ticket_image:
        embed.set_image(url=ticket_image)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • نظام التذاكر الذكي\n═══════════════════════════")
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed, view=TicketView())

@bot.tree.command(name="setticketimage", description="تغيير صورة لوحة التذاكر")
@discord.app_commands.default_permissions(administrator=True)
async def setticketimage(interaction: discord.Interaction, url: str):
    global ticket_image
    ticket_image = url
    save_data()
    embed = discord.Embed(title="✅ تم تعيين الصورة", color=0x2ECC71)
    embed.set_image(url=url)
    await interaction.response.send_message(embed=embed)

@bot.command(name="صورة_تكت")
@commands.has_permissions(administrator=True)
async def set_ticket_image_prefix(ctx, url: str = None):
    """!صورة_تكت <رابط أو صورة> - تعيين صورة لوحة التذاكر"""
    global ticket_image
    if url is None and ctx.message.attachments:
        url = ctx.message.attachments[0].url
    elif url is None:
        await ctx.send("❌ أرسل رابط الصورة أو الصورة مباشرة!")
        return
    ticket_image = url
    save_data()
    embed = discord.Embed(title="✅ تم تعيين صورة لوحة التذاكر", color=0x2ECC71)
    embed.set_image(url=url)
    await ctx.send(embed=embed)

@bot.command(name="صورة_تصنيف")
@commands.has_permissions(administrator=True)
async def set_category_image(ctx, category: str, url: str = None):
    """!صورة_تصنيف <التصنيف> <رابط أو صورة> - تعيين صورة لتصنيف"""
    category_map = {
        "سؤال": "question",
        "مشكلة": "problem",
        "شكوى": "complaint",
        "برمجة": "programming",
        "مساعدة": "help"
    }
    cat_id = category_map.get(category)
    if not cat_id:
        await ctx.send("❌ تصنيف غير صحيح! الاستخدام: `!صورة_تصنيف سؤال/مشكلة/شكوى/برمجة/مساعدة`")
        return

    if url is None and ctx.message.attachments:
        url = ctx.message.attachments[0].url
    elif url is None:
        await ctx.send("❌ أرسل رابط الصورة أو الصورة مباشرة!\n**مثال:**\n`!صورة_تصنيف سؤال` + أرفق الصورة\nأو\n`!صورة_تصنيف سؤال https://رابط.com/image.png`")
        return

    TICKET_CATEGORIES[cat_id]["image"] = url
    print(f"[TICKET IMAGE] Set image for {cat_id}: {url}")
    embed = discord.Embed(title="✅ تم تعيين الصورة", color=0x2ECC71)
    embed.add_field(name="التصنيف", value=f"{TICKET_CATEGORIES[cat_id]['emoji']} {TICKET_CATEGORIES[cat_id]['name']}", inline=True)
    embed.add_field(name="الصورة", value=url, inline=True)
    embed.set_image(url=url)
    await ctx.send(embed=embed)

@bot.command(name="حذف_صورة_تصنيف")
@commands.has_permissions(administrator=True)
async def remove_category_image(ctx, category: str):
    """!حذف_صورة_تصنيف <التصنيف> - حذف صورة تصنيف"""
    category_map = {
        "سؤال": "question",
        "مشكلة": "problem",
        "شكوى": "complaint",
        "برمجة": "programming",
        "مساعدة": "help"
    }
    cat_id = category_map.get(category)
    if not cat_id:
        await ctx.send("❌ تصنيف غير صحيح!")
        return
    TICKET_CATEGORIES[cat_id]["image"] = None
    await ctx.send(f"✅ تم حذف صورة تصنيف: {TICKET_CATEGORIES[cat_id]['emoji']} {TICKET_CATEGORIES[cat_id]['name']}")

@bot.command(name="صلاحيات_تكت")
@commands.has_permissions(administrator=True)
async def ticket_role_access_cmd(ctx, role: discord.Role = None, *, categories: str = None):
    """!صلاحيات_تكت @رتبة سؤال,مشكلة,شكوى,برمجة,مساعدة"""
    global TICKET_ROLE_ACCESS
    if not role:
        embed = discord.Embed(
            title="🔐 صلاحيات التذاكر",
            description=(
                "الاستخدام: `!صلاحيات_تكت @رتبة سؤال,مشكلة,شكوى,برمجة,مساعدة`\n\n"
                f"**التصنيفات الحالية:**\n"
                f"├─ ❓ سؤال\n├─ 🔧 مشكلة\n├─ 📢 شكوى\n├─ 💻 طلب برمجة\n└─ 🤝 مساعدة\n\n"
                f"**الرتب المسجلة:**\n"
            ),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        guild_key = str(ctx.guild.id)
        access = TICKET_ROLE_ACCESS.get(guild_key, {})
        if access:
            for role_id, cats in access.items():
                r = ctx.guild.get_role(int(role_id))
                if r:
                    embed.add_field(name=f"{r.name}", value=", ".join(cats), inline=True)
        else:
            embed.add_field(name="لا توجد صلاحيات مسجلة", value="استخدم الأمر أعلاه لتعيين الصلاحيات", inline=False)
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صلاحيات التذاكر\n═══════════════════════════")
        await ctx.send(embed=embed)
        return

    valid_cats = {"سؤال", "مشكلة", "شكوى", "برمجة", "مساعدة"}
    cat_list = [c.strip() for c in categories.split(",")]
    invalid = [c for c in cat_list if c not in valid_cats]
    if invalid:
        await ctx.send(f"❌ تصنيفات غير صحيحة: {', '.join(invalid)}\n**الصحيحة:** سؤال, مشكلة, شكوى, برمجة, مساعدة")
        return

    guild_key = str(ctx.guild.id)
    if guild_key not in TICKET_ROLE_ACCESS:
        TICKET_ROLE_ACCESS[guild_key] = {}
    TICKET_ROLE_ACCESS[guild_key][str(role.id)] = cat_list
    mark_data_dirty()

    embed = discord.Embed(
        title="✅ تم تعيين الصلاحيات",
        description=f"**الرتبة:** {role.mention}\n**التصنيفات:** {', '.join(cat_list)}",
        color=0x2ECC71
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • صلاحيات التذاكر\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="حذف_صلاحيات_تكت")
@commands.has_permissions(administrator=True)
async def remove_ticket_role_access(ctx, role: discord.Role = None):
    """!حذف_صلاحيات_تكت @رتبة"""
    global TICKET_ROLE_ACCESS
    if not role:
        await ctx.send("❌ حدد الرتبة: `!حذف_صلاحيات_تكت @رتبة`")
        return
    guild_key = str(ctx.guild.id)
    access = TICKET_ROLE_ACCESS.get(guild_key, {})
    if str(role.id) in access:
        del access[str(role.id)]
        TICKET_ROLE_ACCESS[guild_key] = access
        mark_data_dirty()
        await ctx.send(f"✅ تم حذف صلاحيات الرتبة: {role.mention}")
    else:
        await ctx.send(f"❌ الرتبة {role.mention} ليس لها صلاحيات مسجلة.")

@bot.command(name="شخصيات_التكت")
async def ticket_characters_list(ctx):
    if not ctx.author.guild_permissions.administrator:
        return
    embed = discord.Embed(
        title="🎭 شخصيات التكت AI",
        description="الشخصيات المتاحة في نظام التذاكر:",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc)
    )
    for char_id, char in TICKET_CHARACTERS.items():
        embed.add_field(
            name=f"{char['emoji']} {char['name']}",
            value=f"**{char['arabic_name']}**\n{char['description']}\nمعرّف: `{char_id}`",
            inline=True
        )
    embed.set_footer(text="MAX BOT • شخصيات التكت")
    await ctx.send(embed=embed)

@bot.command(name="إحصائيات_التكت")
async def ticket_stats_cmd(ctx):
    if not ctx.author.guild_permissions.administrator:
        return
    active_tickets = len(ticket_characters_map)
    embed = discord.Embed(
        title="📊 إحصائيات التذاكر",
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="التذاكر النشطة", value=f"**{active_tickets}**", inline=True)
    embed.add_field(name="إجمالي التذاكر", value=f"**{ticket_counter - 1}**", inline=True)
    embed.add_field(name="الشخصيات المتاحة", value=f"**{len(TICKET_CHARACTERS)}**", inline=True)
    if ticket_characters_map:
        chars_used = {}
        for ch_id, char_id in ticket_characters_map.items():
            chars_used[char_id] = chars_used.get(char_id, 0) + 1
        chars_text = "\n".join([f"{TICKET_CHARACTERS[c]['emoji']} {TICKET_CHARACTERS[c]['name']}: **{count}**" for c, count in chars_used.items()])
        embed.add_field(name="الشخصيات قيد الاستخدام", value=chars_text, inline=False)
    embed.set_footer(text="MAX BOT • إحصائيات التذاكر")
    await ctx.send(embed=embed)

class AddParticipantModal(discord.ui.Modal, title="إضافة مشترك"):
    user_id = discord.ui.TextInput(label="معرف العضو (ID)", placeholder="أدخل الـ ID الرقمي للعضو", required=True)

    def __init__(self, comp_data, guild):
        super().__init__()
        self.comp_data = comp_data
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID غير صالح", ephemeral=True)
            return
        if uid in self.comp_data["participants"]:
            await interaction.response.send_message("⚠️ العضو مسجل مسبقاً", ephemeral=True)
            return
        self.comp_data["participants"].append(uid)
        save_data()
        await interaction.response.send_message(f"✅ تمت إضافة `<@{uid}>` إلى الفعالية", ephemeral=True)

class RemoveParticipantModal(discord.ui.Modal, title="إلغاء تسجيل مشترك"):
    user_id = discord.ui.TextInput(label="معرف العضو (ID)", placeholder="أدخل الـ ID الرقمي للعضو", required=True)

    def __init__(self, comp_data, guild):
        super().__init__()
        self.comp_data = comp_data
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ ID غير صالح", ephemeral=True)
            return
        if uid not in self.comp_data["participants"]:
            await interaction.response.send_message("⚠️ العضو غير مسجل", ephemeral=True)
            return
        self.comp_data["participants"].remove(uid)
        save_data()
        await interaction.response.send_message(f"✅ تمت إزالة `<@{uid}>` من الفعالية", ephemeral=True)

class CompetitionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    def _get_comp(self, guild_id):
        return competitions.get(guild_id)

    @discord.ui.button(label="✅ تسجيل", style=discord.ButtonStyle.green, custom_id="comp_register")
    async def comp_register(self, interaction: discord.Interaction, button: discord.ui.Button):
        comp = self._get_comp(interaction.guild.id)
        if not comp:
            return await interaction.response.send_message("❌ لا توجد فعالية حالياً", ephemeral=True)
        if not comp["is_open"]:
            return await interaction.response.send_message("🔒 التسجيل مغلق", ephemeral=True)
        uid = interaction.user.id
        if uid in comp["participants"]:
            return await interaction.response.send_message("⚠️ أنت مسجل مسبقاً", ephemeral=True)
        comp["participants"].append(uid)
        save_data()
        await interaction.response.send_message(f"✅ تم تسجيلك في {comp['title']}", ephemeral=True)

    @discord.ui.button(label="📋 المسجلين", style=discord.ButtonStyle.blurple, custom_id="comp_show")
    async def comp_show(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != YOUR_USER_ID:
            return await interaction.response.send_message("❌ هذا الزر للمالك فقط", ephemeral=True)
        comp = self._get_comp(interaction.guild.id)
        if not comp:
            return await interaction.response.send_message("❌ لا توجد فعالية", ephemeral=True)
        if not comp["participants"]:
            return await interaction.response.send_message("📭 لا يوجد مشاركين", ephemeral=True)
        mentions = "\n".join(f"`{i+1}.` <@{uid}> (`{uid}`)" for i, uid in enumerate(comp["participants"]))
        embed = discord.Embed(title=f"📋 المشاركين في {comp['title']}", color=0x3498DB)
        embed.add_field(name="العدد", value=str(len(comp["participants"])), inline=True)
        embed.add_field(name="الحالة", value="🟢 مفتوح" if comp["is_open"] else "🔒 مغلق", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await interaction.followup.send(mentions[:2000], ephemeral=True)

    @discord.ui.button(label="🔒 قفل", style=discord.ButtonStyle.red, custom_id="comp_lock")
    async def comp_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != YOUR_USER_ID:
            return await interaction.response.send_message("❌ هذا الزر للمالك فقط", ephemeral=True)
        comp = self._get_comp(interaction.guild.id)
        if not comp:
            return await interaction.response.send_message("❌ لا توجد فعالية", ephemeral=True)
        comp["is_open"] = not comp["is_open"]
        save_data()
        status = "🟢 مفتوح" if comp["is_open"] else "🔒 مغلق"
        await interaction.response.send_message(f"✅ تم تغيير حالة التسجيل إلى: {status}", ephemeral=True)

    @discord.ui.button(label="🚫 إلغاء تسجيل", style=discord.ButtonStyle.gray, custom_id="comp_kick")
    async def comp_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != YOUR_USER_ID:
            return await interaction.response.send_message("❌ هذا الزر للمالك فقط", ephemeral=True)
        comp = self._get_comp(interaction.guild.id)
        if not comp:
            return await interaction.response.send_message("❌ لا توجد فعالية", ephemeral=True)
        await interaction.response.send_modal(RemoveParticipantModal(comp, interaction.guild))

    @discord.ui.button(label="➕ إضافة", style=discord.ButtonStyle.gray, custom_id="comp_add")
    async def comp_add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != YOUR_USER_ID:
            return await interaction.response.send_message("❌ هذا الزر للمالك فقط", ephemeral=True)
        comp = self._get_comp(interaction.guild.id)
        if not comp:
            return await interaction.response.send_message("❌ لا توجد فعالية", ephemeral=True)
        await interaction.response.send_modal(AddParticipantModal(comp, interaction.guild))

class PunishmentReviewView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🟢 أوافق", style=discord.ButtonStyle.green, custom_id="punish_approve")
    async def punish_approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = pending_punishments.get(interaction.message.id)
        if not data:
            return await interaction.response.send_message("❌ انتهت صلاحية المراجعة", ephemeral=True)

        guild = interaction.guild
        user_id = data["user_id"]
        action = data["action"]
        label = data["label"]
        prot_name = data["prot_name"]
        member = guild.get_member(user_id)
        result = ""

        if action == "timeout":
            duration = data.get("duration", 60)
            if member:
                try:
                    await member.timeout(discord.utils.utcnow() + timedelta(seconds=duration), reason=f"حماية: {prot_name}")
                    result = f"🔇 كتم {duration // 60} دقيقة" if duration >= 60 else f"🔇 كتم {duration} ثانية"
                except Exception as e:
                    result = f"❌ {e}"
            else:
                result = "❌ العضو غير موجود"

        elif action == "kick":
            if member:
                try:
                    await member.kick(reason=f"حماية: {prot_name}")
                    result = "👢 طرد"
                except Exception as e:
                    result = f"❌ {e}"
            else:
                try:
                    user = await bot.fetch_user(user_id)
                    await guild.kick(user, reason=f"حماية: {prot_name}")
                    result = "👢 طرد"
                except Exception as e:
                    result = f"❌ {e}"

        elif action == "ban":
            try:
                user = await bot.fetch_user(user_id)
                await guild.ban(user, reason=f"حماية: {prot_name}")
                result = "🔨 حظر"
            except Exception as e:
                result = f"❌ {e}"

        elif action == "warn":
            punishment_manager.increment_warning(guild.id, user_id, data.get("prot_type", "spam"))
            warns = punishment_manager.get_warning_count(guild.id, user_id, data.get("prot_type", "spam"))
            result = f"⚠️ تحذير #{warns}"

        elif action == "delete":
            result = "🗑️ حذف الرسالة"

        else:
            result = f"✅ {label}"

        pending_punishments.pop(interaction.message.id, None)
        save_data()
        button.disabled = True
        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = 0x2ECC71
        embed.add_field(name="✅ النتيجة", value=result, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔴 لا أوافق", style=discord.ButtonStyle.red, custom_id="punish_deny")
    async def punish_deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != YOUR_USER_ID:
            return await interaction.response.send_message("❌ هذا الزر للمالك فقط", ephemeral=True)
        pending_punishments.pop(interaction.message.id, None)
        save_data()
        button.disabled = True
        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = 0xE74C3C
        embed.add_field(name="❌ ألغي", value="تم إلغاء العقاب", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

class ModRoomView(View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="👥 إدارة الأعضاء",
        options=[
            discord.SelectOption(label="👢 طرد عضو", value="kick", description="طرد عضو من السيرفر"),
            discord.SelectOption(label="🔨 حظر عضو", value="ban", description="حظر عضو نهائياً"),
            discord.SelectOption(label="🔇 كتم عضو", value="mute", description="كتم عضو مؤقتاً"),
            discord.SelectOption(label="🔊 فك الكتم", value="unmute", description="فك كتم عضو"),
            discord.SelectOption(label="🔌 فصل من الروم", value="disconnect", description="فصل عضو من الروم الصوتي"),
        ]
    )
    async def select_members(self, interaction: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        guide = {
            "kick": "• !kick @عضو <سبب>",
            "ban": "• !ban @عضو <سبب>",
            "mute": "• !timeout @عضو 10m <سبب>",
            "unmute": "• !untimeout @عضو",
            "disconnect": "• !فصل @عضو"
        }
        await interaction.response.send_message(f"✅ **{action}**\n{guide.get(action, '')}", ephemeral=True)

    @discord.ui.select(
        placeholder="🎭 إدارة الرتب",
        options=[
            discord.SelectOption(label="➕ إعطاء رتبة", value="addrole", description="إضافة رتبة لعضو"),
            discord.SelectOption(label="🆔 سحب رتبة", value="removerole", description="سحب رتبة من عضو"),
            discord.SelectOption(label="📝 إنشاء رتبة", value="createrole", description="إنشاء رتبة جديدة"),
            discord.SelectOption(label="🎨 لون الرتبة", value="rolecolor", description="تغيير لون الرتبة"),
            discord.SelectOption(label="📛 تعديل اسم الرتبة", value="renamerole", description="تعديل اسم الرتبة"),
        ]
    )
    async def select_roles(self, interaction: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        guide = {
            "addrole": "• !اعطا_رتبة @عضو @رتبه",
            "removerole": "• !سحب_رتبة @عضو @رتبه",
            "createrole": "• !انشاء_رتبة <اسم> <لون>",
            "rolecolor": "• !لون_رتبة @رتبه <hex>",
            "renamerole": "• !اعادة_تسمية_رتبة @رتبه <اسم_جديد>"
        }
        await interaction.response.send_message(f"✅ **{action}**\n{guide.get(action, '')}", ephemeral=True)

    @discord.ui.select(
        placeholder="📁 إدارة الرومات",
        options=[
            discord.SelectOption(label="✏️ تعديل اسم الروم", value="rename", description="تغيير اسم القناة"),
            discord.SelectOption(label="🔒 قفل الروم", value="lock", description="قفل القناة"),
            discord.SelectOption(label="🔓 فتح الروم", value="unlock", description="فتح القناة"),
            discord.SelectOption(label="⏰ الوضع البطيء", value="slowmode", description="تفعيل الوضع البطيء"),
            discord.SelectOption(label="🗑️ حذف الروم", value="delete", description="حذف القناة"),
            discord.SelectOption(label="📝 إنشاء روم", value="create", description="إنشاء قناة جديدة"),
        ]
    )
    async def select_channels(self, interaction: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        guide = {
            "rename": "• !تسمية_روم <اسم_جديد>",
            "lock": "• /lock",
            "unlock": "• /unlock",
            "slowmode": "• /slowmode 60",
            "delete": "• !حذف_روم",
            "create": "• !انشاء_روم <اسم>"
        }
        await interaction.response.send_message(f"✅ **{action}**\n{guide.get(action, '')}", ephemeral=True)

    @discord.ui.select(
        placeholder="⚙️ إدارة السيرفر",
        options=[
            discord.SelectOption(label="📝 تعديل اسم السيرفر", value="srvname", description="تغيير اسم السيرفر"),
            discord.SelectOption(label="🖼️ تغيير صورة السيرفر", value="srvicon", description="تغيير أيقونة السيرفر"),
            discord.SelectOption(label="📜 تعديل وصف السيرفر", value="srvdesc", description="تغيير وصف السيرفر"),
            discord.SelectOption(label="🔧 إعدادات庆典", value="srvbanner", description="إعدادات庆典"),
        ]
    )
    async def select_server(self, interaction: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        guide = {
            "srvname": "• !اسم_السيرفر <اسم_جديد>",
            "srvicon": "• !صورة_السيرفر <صورة>",
            "srvdesc": "• !وصف_السيرفر <نص>",
            "srvbanner": "• !بانر_السيرفر <رابط>"
        }
        await interaction.response.send_message(f"✅ **{action}**\n{guide.get(action, '')}", ephemeral=True)

@bot.command(name="رتب_ترحيب", aliases=['autorole', 'رتب تلقاء', 'تلقاء'])
async def رتب_ترحيب(ctx, role: discord.Role):
    """!رتب_ترحيب @رتبة - تعيين رتبة تلقائية للأعضاء الجدد"""
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    w["role"] = role.id
    save_data()
    await ctx.send(f"✅ تم تعيين {role.mention} كرتبة تلقائية للأعضاء الجدد!")

@bot.command(name="الغاء_رتب_ترحيب", aliases=['remove_autorole'])
async def الغاء_رتب_ترحيب(ctx):
    """!الغاء_رتب_ترحيب - إلغاء الرتبة التلقائية"""
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    if "role" in w:
        w.pop("role", None)
        save_data()
        await ctx.send("✅ تم إلغاء الرتبة التلقائية للأعضاء الجدد!")
    else:
        await ctx.send("❌ ما فيه رتبة تلقائية معينة.")

@bot.command(name="روم_مطبخ", aliases=['modroom'])
async def روم_مطبخ(ctx):
    """!روم_مطبخ - لوحة إدارة سيرفر في الروم الصوتي"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ هذا الأمر للمشرفين فقط!")
        return
    embed = discord.Embed(title="🛠️ لوحة الإدارة في الروم", description="اختر الإجراء من القائمة:", color=0x3498DB)
    await ctx.send(embed=embed, view=ModRoomView())

@bot.command(name="روم_مطبخ_setup", aliases=['modroom_setup'])
async def روم_مطبخ_setup(ctx, channel: discord.VoiceChannel):
    """!روم_مطبخ_setup #روم - إعداد روم الإدارة"""
    global mod_room_channel_id
    mod_room_channel_id = channel.id
    save_data()
    embed = discord.Embed(title="✅ تم إعداد روم الإدارة", description=f"الروم: {channel.mention}\nعند الدخول لهذا الروم ستظهر لك قائمة الإدارة.", color=0x2ECC71)
    await ctx.send(embed=embed)

@bot.command(name="فصل", aliases=['disconnect', 'dc'])
@commands.has_permissions(move_members=True)
async def فصل(ctx, member: discord.Member):
    """!فصل @عضو - فصل عضو من الروم الصوتي"""
    if not member.voice or not member.voice.channel:
        await ctx.send("❌ العضو ما في روم صوتي!")
        return
    ch_name = member.voice.channel.name
    await member.move_to(None)
    embed = discord.Embed(title="🔌 تم فصل العضو", color=0xE74C3C)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="الروم", value=ch_name, inline=True)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("🔌 فصل من الروم الصوتي", LogColors.DELETE, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    log_embed.add_field(name="📍 الروم", value=ch_name, inline=True)
    LogEmbed.details_field(log_embed, action="فصل من الروم الصوتي")
    await send_log(ctx.guild.id, "ban_kick_timeout", log_embed, bot=bot, admin=ctx.author)

@bot.command(name="انشاء_رتبة", aliases=['createrole'])
@commands.has_permissions(manage_roles=True)
async def انشاء_رتبة(ctx, name: str, color: str = None):
    """!انشاء_رتبة <اسم> <لون> - إنشاء رتبة جديدة"""
    try:
        color_int = discord.Color.default() if not color else discord.Color(int(color.replace("#", ""), 16))
    except:
        color_int = discord.Color.default()
    role = await ctx.guild.create_role(name=name, color=color_int)
    embed = discord.Embed(title="✅ تم إنشاء الرتبة", color=0x2ECC71)
    embed.add_field(name="الرتبة", value=role.mention)
    await ctx.send(embed=embed)

@bot.command(name="لون_رتبة", aliases=['rolecolor'])
@commands.has_permissions(manage_roles=True)
async def لون_رتبة(ctx, role: discord.Role, color: str):
    """!لون_رتبة @رتبه <لون> - تغيير لون الرتبة"""
    try:
        color_int = discord.Color(int(color.replace("#", ""), 16))
        await role.edit(color=color_int)
        await ctx.send(f"✅ تم تغيير لون الرتبة {role.mention}")
    except:
        await ctx.send("❌ لون غير صالح! استخدم: #FF0000")

@bot.command(name="اعادة_تسمية_رتبة", aliases=['renamerole'])
@commands.has_permissions(manage_roles=True)
async def اعادة_تسمية_رتبة(ctx, role: discord.Role, *, new_name: str):
    """!اعادة_تسمية_رتبة @رتبه <اسم_جديد> - إعادة تسمية رتبة"""
    await role.edit(name=new_name)
    await ctx.send(f"✅ تم إعادة تسمية الرتبة إلى: {new_name}")

@bot.command(name="تسمية_روم", aliases=['renamechannel'])
@commands.has_permissions(manage_channels=True)
async def تسمية_روم(ctx, *, name: str):
    """!تسمية_روم <اسم_جديد> - إعادة تسمية الروم الحالي"""
    await ctx.channel.edit(name=name)
    await ctx.send(f"✅ تم تغيير اسم الروم إلى: {name}")

@bot.command(name="حذف_روم", aliases=['deletechannel'])
@commands.has_permissions(manage_channels=True)
async def حذف_روم(ctx):
    """!حذف_روم - حذف الروم الحالي"""
    await ctx.channel.delete()
    await ctx.send("✅ تم حذف الروم!")

@bot.command(name="حذف_روم_صوتي", aliases=['delete_voice'])
@commands.has_permissions(manage_channels=True)
async def حذف_روم_صوتي(ctx, *, name: str):
    """!حذف_روم_صوتي <اسم> - حذف روم صوتي محدد"""
    channel = discord.utils.get(ctx.guild.voice_channels, name=name)
    if not channel:
        await ctx.send(f"❌ ما لقيت روم صوتي باسم: {name}")
        return
    await channel.delete()
    await ctx.send(f"✅ تم حذف الروم الصوتي: {name}")

@bot.hybrid_command(name="حذف_تيم", aliases=['delete_category', 'حذف_فئة'], description="حذف التيم وكل الرومات بداخله بالاسم أو ID")
@commands.has_permissions(manage_channels=True)
async def حذف_تيم(ctx, *, name: str):
    """!حذف_تيم <اسم/ID> - حذف التيم وكل الرومات بداخله"""
    try:
        cat_id = int(name)
        category = discord.utils.get(ctx.guild.categories, id=cat_id)
    except ValueError:
        category = discord.utils.get(ctx.guild.categories, name=name)

    if not category:
        await ctx.send(f"❌ ما لقيت التيم: {name}")
        return

    channels = category.channels
    deleted = 0
    skipped = 0
    for channel in channels:
        try:
            await channel.delete()
            deleted += 1
        except:
            skipped += 1
    await category.delete()
    await ctx.send(f"✅ تم حذف التيم **{category.name}** (تم حذف {deleted} روم، تخطي {skipped} روم مطلوب للسيرفر)")

@bot.command(name="انشاء_روم", aliases=['createchannel'])
@commands.has_permissions(manage_channels=True)
async def انشاء_روم(ctx, name: str, typ: str = "text"):
    """!انشاء_روم <اسم> <type> - إنشاء روم جديد"""
    if typ in ["voice", "v", "صوتي"]:
        channel = await ctx.guild.create_voice_channel(name)
    else:
        channel = await ctx.guild.create_text_channel(name)
    await ctx.send(f"✅ تم إنشاء {channel.mention}")

@bot.command(name="اسم_السيرفر", aliases=['servername'])
@commands.has_permissions(manage_guild=True)
async def اسم_السيرفر(ctx, *, name: str):
    """!اسم_السيرفر <اسم_جديد> - تغيير اسم السيرفر"""
    await ctx.guild.edit(name=name)
    await ctx.send(f"✅ تم تغيير اسم السيرفر إلى: {name}")

@bot.command(name="وصف_السيرفر", aliases=['serverdesc'])
@commands.has_permissions(manage_guild=True)
async def وصف_السيرفر(ctx, *, description: str):
    """!وصف_السيرفر <وصف> - تغيير وصف السيرفر"""
    await ctx.guild.edit(description=description)
    await ctx.send(f"✅ تم تغيير وصف السيرفر!")

@bot.command(name="صورة_السيرفر", aliases=['servericon'])
@commands.has_permissions(manage_guild=True)
async def صورة_السيرفر(ctx):
    """!صورة_السيرفر - تغيير صورة السيرفر"""
    if not ctx.message.attachments:
        await ctx.send("❌ أرفق صورة!")
        return
    img = ctx.message.attachments[0]
    try:
        await ctx.guild.edit(icon=img.read())
        await ctx.send("✅ تم تغيير صورة السيرفر!")
    except:
        await ctx.send("❌ فشل تغيير الصورة!")

@bot.command()
async def setup(ctx):
    embed = discord.Embed(
        title="📋 مركز التذاكر - Support Ticket",
        description="**طبق** ✅\n\n**كيف اقدر اساعدك؟**\nسكون المسوولين متواجدين في اقرب وقت\n\n<@1506433133002883202>",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, view=TicketView())

@bot.tree.command(name="linkblocker", description="تشغيل/إيقاف منع الروابط في السيرفر")
@discord.app_commands.describe(action="اختر الإجراء")
@discord.app_commands.choices(action=[
    discord.app_commands.Choice(name="تشغيل ✅", value="on"),
    discord.app_commands.Choice(name="إيقاف ❌", value="off"),
    discord.app_commands.Choice(name="الحالة ℹ️", value="status"),
])
async def linkblocker(interaction: discord.Interaction, action: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ هذا الأمر مخصص للمشرفين فقط!", ephemeral=True)
        return

    guild_id = interaction.guild_id
    if action == "on":
        link_blocker_enabled[guild_id] = True
        save_data()
        await interaction.response.send_message("✅ **تم تشغيل منع الروابط** - أي رابط بيتم حذفه تلقائياً.", ephemeral=False)
    elif action == "off":
        link_blocker_enabled[guild_id] = False
        save_data()
        await interaction.response.send_message("✅ **تم إيقاف منع الروابط** - تقدر ترسل روابط بحرية.", ephemeral=False)
    elif action == "status":
        status = "🟢 **شغال**" if link_blocker_enabled.get(guild_id, False) else "🔴 **موقف**"
        await interaction.response.send_message(f"حالة منع الروابط: {status}", ephemeral=True)

async def send_voice_debug(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ هذا الأمر مخصص للإداريين فقط!", ephemeral=True)
        return

    lines = []
    try:
        async for entry in interaction.guild.audit_logs(limit=8, action=discord.AuditLogAction.member_move):
            age = abs((datetime.now(timezone.utc) - entry.created_at).total_seconds())
            moved_to = getattr(getattr(entry, "extra", None), "channel", None)
            moved_to_name = getattr(moved_to, "name", "غير معروف")
            moved_to_id = getattr(moved_to, "id", "غير معروف")
            count = getattr(getattr(entry, "extra", None), "count", "?")
            used = voice_audit_usage.get(entry.id, 0)
            lines.append(f"{entry.user} | age={age:.1f}s | channel={moved_to_name} ({moved_to_id}) | count={count} | used={used}/{count}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ البوت لا يملك صلاحية View Audit Log", ephemeral=True)
        return

    if not lines:
        lines.append("لا يوجد member_move حديث في Audit Log.")

    await interaction.response.send_message("```\n" + "\n".join(lines)[:1800] + "\n```", ephemeral=True)

@bot.tree.command(name="voice_debug", description="عرض آخر سجلات سحب الأعضاء من Audit Log")
async def voice_debug(interaction: discord.Interaction):
    await send_voice_debug(interaction)

@bot.tree.command(name="تشخيص", description="عرض آخر سجلات سحب الأعضاء من Audit Log")
async def voice_debug_ar(interaction: discord.Interaction):
    await send_voice_debug(interaction)

@bot.command(name="تحديث", aliases=["restart", "update"])
async def update_bot_prefix(ctx):
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("❌ هذا الأمر مخصص لمالك البوت فقط!")
        return
    await ctx.send("♻️ **جاري إعادة تشغيل البوت...**")
    import subprocess
    subprocess.Popen(
        ["cmd", "/c", "timeout /t 2 /nobreak >nul && set PYTHONUNBUFFERED=1 && python.exe -u main.py"],
        cwd=r"C:\Users\USER\Desktop\z1-pro",
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    await bot.close()

@bot.tree.command(name="welcome", description="إعداد الترحيب (القناة + الرسالة + الصورة)")
@discord.app_commands.describe(channel="قناة الترحيب", message="رسالة الترحيب (استخدم {member})", image="رابط صورة (اختياري)")
async def welcome_setup(interaction: discord.Interaction, channel: discord.TextChannel, message: str, image: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ هذا الأمر للمسؤولين فقط!", ephemeral=True)
        return
    if len(message) > 500:
        await interaction.response.send_message("❌ الرسالة طويلة جداً (حد أقصى 500 حرف).", ephemeral=True)
        return

    g = interaction.guild_id
    w = welcome_config.setdefault(g, {})
    w["channel"] = channel.id
    w["message"] = message
    if image:
        w["image_url"] = image
    elif "image_url" in w:
        del w["image_url"]
    save_data()

    embed = LogEmbed.base("✅ تم إعداد الترحيب", LogColors.CREATE, guild=interaction.guild)
    embed.add_field(name="📢 القناة", value=channel.mention)
    embed.add_field(name="📝 الرسالة", value=message[:100])
    if image:
        embed.add_field(name="🖼️ الصورة", value="✅ مضافة")
    embed.set_footer(text="سيظهر عند دخول عضو جديد")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="تحديث", description="إعادة تشغيل البوت وتحديثه")
async def update_bot(interaction: discord.Interaction):
    if interaction.user.id != YOUR_USER_ID:
        await interaction.response.send_message("❌ هذا الأمر مخصص لمالك البوت فقط!", ephemeral=True)
        return
    await interaction.response.send_message("♻️ **جاري إعادة تشغيل البوت...**")
    import subprocess
    subprocess.Popen(
        ["cmd", "/c", "timeout /t 2 /nobreak >nul && set PYTHONUNBUFFERED=1 && python.exe -u main.py"],
        cwd=r"C:\Users\USER\Desktop\z1-pro",
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    await bot.close()

# ════════════════════════════════════════
# أمر اللوق (إنشاء رومات اللوق تلقائياً)
# ════════════════════════════════════════

LOG_CATEGORY_NAME = "💻 ┋ LOG ┋ ✦"

LOG_CHANNEL_NAMES = {
    "log_protection":  "💻 LOG ∙ PROTECTION ∙ SERVER",
    "log_ban_kick":    "💻 LOG ∙ BAN ∙ KICK ∙ TIMEOUT",
    "log_channels":    "💻 LOG ∙ CHANNELS",
    "log_admin_leave": "💻 LOG ∙ ADMIN ∙ LEAVE",
    "log_edit_role":   "💻 LOG ∙ EDIT ∙ ROLE",
    "log_admins_role": "💻 LOG ∙ ADMINSROLE",
    "log_role":        "💻 LOG ∙ ROLE",
    "log_messages":    "💻 LOG ∙ MESSAGES",
    "log_nickname":    "💻 LOG ∙ NICKNAME",
    "log_all":         "💻 LOG ∙ ALL",
    "log_hacker":      "💻 LOG ∙ H.A.C.K.E.R 🔍",
}

LOG_CHANNEL_TOPICS = {
    "log_protection":  "الحماية، الأحداث العامة، الأوتومود",
    "log_ban_kick":    "الحظر، الطرد، الكتم",
    "log_channels":    "إنشاء/حذف/تحديث القنوات والصلاحيات",
    "log_admin_leave": "مغادرة الأدمنز VIP",
    "log_edit_role":   "إنشاء/حذف/تحديث الرتب",
    "log_admins_role": "تعديل رتب الأعضاء",
    "log_role":        "دخول/خروج الأعضاء",
    "log_messages":    "الرسائل، التعديل، الحذف، التثبيت",
    "log_nickname":    "تغيير الأسماء",
    "log_all":         "الصوت، الدعوات، الإيموجي، الويب هوك، التكاملات",
    "log_hacker":      "صيد الهكرز، بصمات، حظر العتاد",
}

LOG_CHANNEL_MAP = {
    "protection_security": "log_protection",
    "log_all":             "log_protection",
    "log_misc":            "log_protection",
    "log_automod":         "log_protection",
    "ban_kick_timeout":    "log_ban_kick",
    "log_channels":        "log_channels",
    "log_channel_perm":    "log_channels",
    "log_admin_leave":     "log_admin_leave",
    "log_edit_role":       "log_edit_role",
    "log_role":            "log_admins_role",
    "log_high_roles":      "log_admins_role",
    "log_join":            "log_role",
    "log_leave":           "log_role",
    "log_messages":        "log_messages",
    "log_pin_bulk":        "log_messages",
    "log_thread":          "log_messages",
    "log_new_message":     "log_messages",
    "log_nickname":        "log_nickname",
    "log_voice":           "log_all",
    "log_invite":          "log_all",
    "log_emoji_sticker":   "log_all",
    "log_webhook":         "log_all",
    "log_integration":     "log_all",
    "log_stage":           "log_all",
    "log_scheduled_event": "log_all",
    "log_activity":        "log_all",
    "log_hacking":         "log_hacker",
}

WEBHOOK_LOG_CHANNELS = {
    "log_protection":  "💻 ∙ WEBHOOK ∙ PROTECTION",
    "log_ban_kick":    "💻 ∙ WEBHOOK ∙ BAN KICK",
    "log_channels":    "💻 ∙ WEBHOOK ∙ CHANNELS",
    "log_admin_leave": "💻 ∙ WEBHOOK ∙ ADMIN LEAVE",
    "log_edit_role":   "💻 ∙ WEBHOOK ∙ EDIT ROLE",
    "log_admins_role": "💻 ∙ WEBHOOK ∙ ADMINSROLE",
    "log_role":        "💻 ∙ WEBHOOK ∙ ROLE",
    "log_messages":    "💻 ∙ WEBHOOK ∙ MESSAGES",
    "log_nickname":    "💻 ∙ WEBHOOK ∙ NICKNAME",
    "log_all":         "💻 ∙ WEBHOOK ∙ ALL",
    "log_hacker":      "💻 ∙ WEBHOOK ∙ H.A.C.K.E.R",
}

async def _create_log_channels(ctx):
    """إنشاء رومات اللوق - 11 روم احترافية"""
    guild = ctx.guild
    if not guild.me.guild_permissions.manage_channels:
        await ctx.send("❌ البوت يحتاج صلاحية **Manage Channels** عشان ينشئ الرومات.")
        return False

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
    }
    admin_role = guild.get_role(ADMIN_ROLE_ID)
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)

    msg = await ctx.send("⏳ **جاري إنشاء رومات اللوق الاحترافية...**")

    try:
        category = await guild.create_category(name=LOG_CATEGORY_NAME, overwrites=overwrites)
    except discord.Forbidden:
        await msg.edit(content="❌ البوت لا يملك صلاحية **Manage Channels**.")
        return False
    except Exception as e:
        await msg.edit(content=f"❌ خطأ في إنشاء التصنيف: {e}")
        return False

    created_channels = {}
    total = len(LOG_CHANNEL_NAMES)
    done = 0
    failed = 0
    for key, channel_name in LOG_CHANNEL_NAMES.items():
        topic = LOG_CHANNEL_TOPICS.get(key, "")
        for attempt in range(3):
            try:
                ch = await guild.create_text_channel(name=channel_name, category=category, slowmode_delay=0, topic=topic)
                created_channels[key] = ch.id
                done += 1
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    await asyncio.sleep(5)
                else:
                    failed += 1
                    print(f"[LOG CREATE] Failed {key}: {e}")
                    break
            except Exception as e:
                failed += 1
                print(f"[LOG CREATE] Error {key}: {e}")
                break
        try:
            await msg.edit(content=f"⏳ **جاري إنشاء رومات اللوق...** {done}/{total}")
        except:
            pass
        await asyncio.sleep(0.3)

    if not created_channels:
        await msg.edit(content="❌ **فشل إنشاء أي قناة لوق!** تحقق من صلاحيات البوت.")
        return False

    created_channels["main"] = created_channels.get("log_protection", 0)
    log_channels[guild.id] = created_channels
    save_data()

    await msg.edit(content=f"✅ **تم إنشاء {done} قناة لوق بنجاح!**")
    embed = discord.Embed(title="✅ تم الإعداد — 10 رومات لوق احترافية", color=0x2ECC71)
    embed.description = (
        "**💻 LOG ∙ PROTECTION ∙ SERVER** — الحماية، الأحداث العامة، الأوتومود\n"
        "**💻 LOG ∙ BAN ∙ KICK ∙ TIMEOUT** — الحظر، الطرد، الكتم\n"
        "**💻 LOG ∙ CHANNELS** — إنشاء/حذف/تحديث القنوات والصلاحيات\n"
        "**💻 LOG ∙ ADMIN ∙ LEAVE** — مغادرة الأدمنز VIP\n"
        "**💻 LOG ∙ EDIT ∙ ROLE** — إنشاء/حذف/تحديث الرتب\n"
        "**💻 LOG ∙ ADMINSROLE** — تعديل رتب الأعضاء\n"
        "**💻 LOG ∙ ROLE** — دخول/خروج الأعضاء\n"
        "**💻 LOG ∙ MESSAGES** — الرسائل، التعديل، الحذف، التثبيت\n"
        "**💻 LOG ∙ NICKNAME** — تغيير الأسماء\n"
        "**💻 LOG ∙ ALL** — الصوت، الدعوات، الإيموجي، الويب هوك، التكاملات\n"
    )
    if failed:
        embed.add_field(name="⚠️ فشل", value=f"{failed} قناة", inline=True)
    embed.set_footer(text="الأحداث بتتسجل تلقائياً حسب نوعها")
    await ctx.send(embed=embed)
    return True

@bot.hybrid_group(name="log", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def log(ctx):
    """!log - إعداد رومات اللوق"""
    guild = ctx.guild

    if guild.id in log_channels:
        del log_channels[guild.id]

    existing = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if existing:
        msg2 = await ctx.send("⏳ **جاري حذف القنوات القديمة...**")
        count = 0
        for ch in list(existing.channels):
            try:
                await ch.delete()
                count += 1
            except:
                pass
            await asyncio.sleep(0.5)
        try:
            await existing.delete()
        except:
            pass
        try:
            await msg2.edit(content=f"✅ تم حذف {count} قناة قديمة")
        except:
            pass
        await asyncio.sleep(2)

    await _create_log_channels(ctx)

@log.command(name="reset")
@commands.has_permissions(administrator=True)
async def log_reset(ctx):
    """حذف كاتقوري LOG وإعادة إنشائها"""
    guild = ctx.guild
    existing = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if existing:
        for ch in existing.channels:
            await ch.delete()
        await existing.delete()
    if guild.id in log_channels:
        del log_channels[guild.id]
        save_data()
    await _create_log_channels(ctx)

@log.command(name="set")
@commands.has_permissions(administrator=True)
async def log_set(ctx, channel: discord.TextChannel):
    """يستخدم روم محدد لجميع أنواع اللوق"""
    log_channels[ctx.guild.id] = {"main": channel.id}
    save_data()
    embed = discord.Embed(title="✅ تم تعيين روم اللوق", color=0x2ECC71)
    embed.description = f"جميع أحداث اللوق بتتجه إلى {channel.mention}"
    await ctx.send(embed=embed)

@log.command(name="status")
@commands.has_permissions(administrator=True)
async def log_status(ctx):
    """يعرض حالة رومات اللوق"""
    config = log_channels.get(ctx.guild.id)
    if not config:
        default = bot.get_channel(DEFAULT_LOG_CHANNEL_ID)
        await ctx.send(f"ℹ️ لا يوجد إعداد مخصص. الروم الافتراضي: {default.mention if default else 'غير معرف'}\nاستخدم `!log` لإنشاء رومات اللوق.")
        return

    embed = LogEmbed.base("📋 حالة رومات LOG — 10 رومات", LogColors.CREATE, guild=ctx.guild)
    embed.description = "**10 رومات لوق احترافية**\n\n"

    channel_info = {
        "log_protection":  ("💻 LOG ∙ PROTECTION ∙ SERVER", "الحماية، الأحداث العامة، الأوتومود"),
        "log_ban_kick":    ("💻 LOG ∙ BAN ∙ KICK ∙ TIMEOUT", "الحظر، الطرد، الكتم"),
        "log_channels":    ("💻 LOG ∙ CHANNELS", "إنشاء/حذف/تحديث القنوات والصلاحيات"),
        "log_admin_leave": ("💻 LOG ∙ ADMIN ∙ LEAVE", "مغادرة الأدمنز VIP"),
        "log_edit_role":   ("💻 LOG ∙ EDIT ∙ ROLE", "إنشاء/حذف/تحديث الرتب"),
        "log_admins_role": ("💻 LOG ∙ ADMINSROLE", "تعديل رتب الأعضاء"),
        "log_role":        ("💻 LOG ∙ ROLE", "دخول/خروج الأعضاء"),
        "log_messages":    ("💻 LOG ∙ MESSAGES", "الرسائل، التعديل، الحذف، التثبيت"),
        "log_nickname":    ("💻 LOG ∙ NICKNAME", "تغيير الأسماء"),
        "log_all":         ("💻 LOG ∙ ALL", "الصوت، الدعوات، الإيموجي، الويب هوك"),
        "log_hacker":      ("💻 LOG ∙ H.A.C.K.E.R 🔍", "صيد الهاكرز، بصمات، حظر العتاد"),
    }

    for key, (display_name, desc) in channel_info.items():
        ch_id = config.get(key)
        ch = bot.get_channel(ch_id) if ch_id else None
        status = f"{ch.mention} ✅" if ch else f"`{ch_id}` ❌ (محذوف)"
        embed.add_field(name=display_name, value=f"{status}\n*{desc}*", inline=False)

    embed.set_footer(text="!log لإنشاء | !log rename لإعادة التسمية | !log روم لتغيير روم")
    await ctx.send(embed=embed)

@log.command(name="delete")
@commands.has_permissions(administrator=True)
async def log_delete(ctx):
    """حذف كل رومات اللوق والتصنيف"""
    guild = ctx.guild
    existing = discord.utils.get(guild.categories, name=LOG_CATEGORY_NAME)
    if existing:
        for ch in existing.channels:
            try:
                await ch.delete()
            except:
                pass
        try:
            await existing.delete()
        except:
            pass
    if guild.id in log_channels:
        del log_channels[guild.id]
        save_data()
    await ctx.send("✅ **تم حذف كل رومات اللوق.**")

@log.command(name="روم")
@commands.has_permissions(administrator=True)
async def log_room(ctx, log_type: str, channel: discord.TextChannel = None):
    """!log روم <النوع> <#الروم> - تعيين روم محدد لنوع معين"""
    if channel is None:
        await ctx.send("❌ استخدم: `!log روم <النوع> <#الروم>`\nمثال: `!log روم log_voice #صوت`")
        return
    valid_types = [
        "protection_security", "ban_kick_timeout", "log_channels", "log_admin_leave",
        "log_edit_role", "log_high_roles", "log_role", "log_messages", "log_nickname",
        "log_all", "log_leave", "log_voice", "log_join", "log_invite", "log_emoji_sticker",
        "log_thread", "log_webhook", "log_integration", "log_stage", "log_automod",
        "log_channel_perm", "log_pin_bulk", "log_scheduled_event", "log_misc", "log_activity",
        "log_new_message", "main", "log_hacker"
    ]
    if log_type not in valid_types:
        await ctx.send(f"❌ نوع غير صالح. الأنواع المتاحة:\n" + " ".join(f"`{t}`" for t in valid_types))
        return
    config = log_channels.setdefault(ctx.guild.id, {})
    config[log_type] = channel.id
    save_data()
    mapped_group = LOG_CHANNEL_MAP.get(log_type, log_type)
    group_name = LOG_CHANNEL_NAMES.get(mapped_group, mapped_group)
    embed = LogEmbed.base("✅ تعيين روم اللوق", LogColors.CREATE, guild=ctx.guild)
    embed.add_field(name="📋 النوع", value=f"`{log_type}` → {group_name}", inline=True)
    embed.add_field(name="📍 الروم", value=channel.mention, inline=True)
    await ctx.send(embed=embed)

@log.command(name="نشاط")
@commands.has_permissions(administrator=True)
async def log_activity_sub(ctx, option: str = None):
    """!log نشاط [on/off/status] - تتبع البرامج في الرومات الصوتية"""
    guild_id = ctx.guild.id
    if option is None:
        option = "status"
    option = option.lower().strip()

    if option == "on":
        activity_tracking_enabled[guild_id] = True
        save_data()
        embed = discord.Embed(title="✅ تم تفعيل تتبع الأنشطة", description="الآن سيتم تسجيل جميع الأنشطة في الرومات الصوتية.", color=0x2ECC71)
        return await ctx.send(embed=embed)
    elif option == "off":
        activity_tracking_enabled[guild_id] = False
        save_data()
        embed = discord.Embed(title="🛑 تم تعطيل تتبع الأنشطة", description="لن يتم تسجيل الأنشطة في الرومات الصوتية.", color=0xE74C3C)
        return await ctx.send(embed=embed)
    else:
        is_on = activity_tracking_enabled.get(guild_id, False)
        embed = discord.Embed(title="📊 حالة تتبع الأنشطة", color=0x2ECC71 if is_on else 0xE74C3C)
        embed.add_field(name="الحالة", value="🟢 مفعّل" if is_on else "🔴 معطّل", inline=True)
        embed.set_footer(text="الأمر: !log نشاط on/off/status")
        return await ctx.send(embed=embed)

@log.command(name="a")
@commands.has_permissions(administrator=True)
async def log_a_shortcut(ctx, option: str = None):
    """!log a [on/off] - اختصار لـ !log نشاط"""
    await log_activity_sub(ctx, option)

@log.command(name="rename")
@commands.has_permissions(administrator=True)
async def log_rename(ctx):
    """!log rename - إعادة تسمية جميع رومات اللوق بالتنسيق الجديد"""
    config = log_channels.get(ctx.guild.id)
    if not config:
        return await ctx.send("❌ لا توجد رومات لوق مُعدّة. استخدم `!log` أولاً.")

    msg = await ctx.send("⏳ **جاري إعادة تسمية رومات اللوق...**")
    count = 0
    topics_count = 0
    for key, new_name in LOG_CHANNEL_NAMES.items():
        ch_id = config.get(key)
        if ch_id:
            ch = bot.get_channel(ch_id)
            if ch:
                if ch.name != new_name:
                    try:
                        await ch.edit(name=new_name)
                        count += 1
                        await asyncio.sleep(0.3)
                    except:
                        pass
                new_topic = LOG_CHANNEL_TOPICS.get(key)
                if new_topic and ch.topic != new_topic:
                    try:
                        await ch.edit(topic=new_topic)
                        topics_count += 1
                        await asyncio.sleep(0.3)
                    except:
                        pass
    await msg.edit(content=f"✅ **تم إعادة تسمية {count} قناة + تحديث {topics_count} وصف!**")

@bot.command(name="لوق_يسرفر", aliases=["لوق يسرفر", "لوق سيرفر", "log_sarvar", "log_server"])
@commands.has_permissions(administrator=True)
async def log_server_cmd(ctx):
    """!لوق يسرفر - لوق السيرفر"""
    guild = ctx.guild
    config = log_channels.get(guild.id, {})
    act_on = activity_tracking_enabled.get(guild.id, False)
    link_on = link_blocker_enabled.get(guild.id, False)
    prots = protections.get(guild.id, {})

    total_log = len([k for k in LOG_CHANNEL_NAMES if config.get(k)])
    total_wh = len([k for k in WEBHOOK_LOG_CHANNELS if config.get(k)])
    total_prot = sum(1 for p in ["spam", "flood", "mention", "badwords", "invite"] if prots.get(p, False)) + (1 if link_on else 0)

    embed = discord.Embed(title="🖥️ لوق يسرفر", color=0x5865F2)
    embed.add_field(name="🔗 السيرفر", value=guild.name, inline=True)
    embed.add_field(name="📊 اللوق", value=f"✅ {total_log}/25 روم", inline=True)
    embed.add_field(name="🔗 الويبهوك", value=f"✅ {total_wh}/6 روم", inline=True)
    embed.add_field(name="🎮 تتبع الأنشطة", value="🟢 مفعّل" if act_on else "🔴 معطّل", inline=True)
    embed.add_field(name="🛡️ الحمايات", value=f"✅ {total_prot}/6 مفعّل", inline=True)

    prot_names = []
    for pk, pn in [("spam", "سبام"), ("flood", "فلود"), ("mention", "منشن"), ("badwords", "كلمات"), ("invite", "دعوة")]:
        prot_names.append(f"{'🟢' if prots.get(pk) else '🔴'} {pn}")
    prot_names.append(f"{'🟢' if link_on else '🔴'} روابط")
    embed.add_field(name="🛡️", value="\n".join(prot_names), inline=True)

    online = sum(1 for m in guild.members if m.status != discord.Status.offline)
    embed.add_field(name="👥 الأعضاء", value=f"{guild.member_count} ({online} نشط)", inline=True)

    embed.set_footer(text="!لوق يسرفر | !log setup | !log a on/off")
    await ctx.send(embed=embed)

@bot.command(name="حماية_تشغيل", aliases=["تشغيل حماية", "تشغيل حمايه", "حماية تشغيل"])
@commands.has_permissions(administrator=True)
async def حماية_تشغيل_cmd(ctx):
    """!تشغيل حماية - تشغيل جميع الحمايات"""
    g = ctx.guild.id
    p = protections.setdefault(g, {})
    keys = ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]
    for k in keys:
        p[k] = True
    save_data()
    embed = discord.Embed(title="🛡️ تم تشغيل جميع الحمايات", color=0x2ECC71)
    for k in keys:
        name = PROTECTION_NAMES.get(k, k)
        embed.add_field(name=f"🟢 {name}", value="شغّال", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="فك_حماية", aliases=["فك حماية", "فك حمايه", "إيقاف حماية", "إيقاف_حماية"])
@commands.has_permissions(administrator=True)
async def فك_حماية_cmd(ctx):
    """!فك حماية - إيقاف جميع الحمايات"""
    g = ctx.guild.id
    p = protections.setdefault(g, {})
    keys = ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]
    for k in keys:
        p[k] = False
    save_data()
    embed = discord.Embed(title="🔓 تم إيقاف جميع الحمايات", color=0xE74C3C)
    for k in keys:
        name = PROTECTION_NAMES.get(k, k)
        embed.add_field(name=f"🔴 {name}", value="معطّل", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="حماية_رتب", aliases=["تشغيل حماية الرتب", "حماية الرتب", "حماية رتب"])
@commands.has_permissions(administrator=True)
async def حماية_رتب_cmd(ctx):
    """!تشغيل حماية الرتب - حماية الرتب من التعديل غير المصرح"""
    g = ctx.guild.id
    p = protections.setdefault(g, {})
    p["role"] = not p.get("role", False)
    save_data()
    state = "🟢 مفعّل" if p["role"] else "🔴 معطّل"
    embed = discord.Embed(title="🛡️ حماية الرتب", color=0x2ECC71)
    embed.add_field(name="الحالة", value=state)
    embed.add_field(name="الشرح", value="يمنع إعطاء/سحب الرتب غير المصرح بها\nالرتب المحمية: جميع الرتب", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="إعفاء_رتب", aliases=["فك حماية رتب", "إعفاء رتب", "إعفاء"])
@commands.has_permissions(administrator=True)
async def إعفاء_رتب_cmd(ctx, member: discord.Member = None):
    """!إعفاء @user - إعفاء شخص من حماية الرتب (يقدر يضيف/يسحب رتب بحرية)"""
    if not member:
        await ctx.send("❌ حدد العضو: `!إعفاء @user`")
        return
    g = ctx.guild.id
    exempt = role_exempt_users.setdefault(g, [])
    if member.id in exempt:
        exempt.remove(member.id)
        save_data()
        await ctx.send(f"❌ تم **إلغاء** إعفاء {member.mention} من حماية الرتب")
    else:
        exempt.append(member.id)
        save_data()
        await ctx.send(f"✅ تم **إعفاء** {member.mention} من حماية الرتب\nالآن يقدر يضيف/سحب رتب بحرية")

@bot.command(name="قائمة_الإعفاء", aliases=["الإعفاءات", "exempt list"])
@commands.has_permissions(administrator=True)
async def قائمة_الإعفاء_cmd(ctx):
    """عرض قائمة المعفيين من حماية الرتب"""
    g = ctx.guild.id
    exempt = role_exempt_users.get(g, [])
    if not exempt:
        await ctx.send("📋 لا يوجد معفيين من حماية الرتب")
        return
    embed = discord.Embed(title="🛡️ المعفيون من حماية الرتب", color=0x3498DB)
    for uid in exempt:
        member = ctx.guild.get_member(uid)
        if member:
            embed.add_field(name=f"✅ {member.display_name}", value=f"`{uid}`", inline=True)
        else:
            embed.add_field(name=f"❓ معرف {uid}", value="عضو سابق", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="تقرير", aliases=["report", "تقرير_يومي"])
@commands.has_permissions(administrator=True)
async def تقرير_cmd(ctx):
    """!تقرير - إرسال التقرير اليومي فوراً"""
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    guild_count = len(bot.guilds)
    member_count = sum(g.member_count or 0 for g in bot.guilds)
    uptime = str(datetime.now() - start_time).split(".")[0] if start_time else "0"

    cmd_logs = []
    if os.path.exists("command_logs.json"):
        try:
            with open("command_logs.json", "r", encoding="utf-8") as f:
                all_logs = json.load(f)
            today_logs = [l for l in all_logs if l.get("timestamp", "").startswith(today)]
            cmd_logs = today_logs
        except:
            pass

    top_cmds = {}
    top_users = {}
    for l in cmd_logs:
        c = l.get("command", "?")
        u = l.get("user", "?")
        top_cmds[c] = top_cmds.get(c, 0) + 1
        top_users[u] = top_users.get(u, 0) + 1
    top_cmds_str = "\n".join([f"  `{k}` — {v}" for k, v in sorted(top_cmds.items(), key=lambda x: x[1], reverse=True)[:5]]) or "  لا توجد أوامر"
    top_users_str = "\n".join([f"  {k} — {v}" for k, v in sorted(top_users.items(), key=lambda x: x[1], reverse=True)[:5]]) or "  لا يوجد مستخدمين"

    embed = discord.Embed(title=f"📊 التقرير اليومي — {today}", color=0x5865F2)
    embed.add_field(name="🤖 البوت", value=f"السيرفرات: {guild_count}\nالأعضاء: {member_count}\nUptime: {uptime}\nالأوامر اليوم: {len(cmd_logs)}", inline=False)
    embed.add_field(name="🔥 أكثر الأوامر", value=top_cmds_str, inline=False)
    embed.add_field(name="👑 أكثر المستخدمين", value=top_users_str, inline=False)
    embed.set_footer(text="تقرير تلقائي — MAX BOT")
    await ctx.send(embed=embed)

@bot.command(name="program_log", aliases=["برنامج", "برامج", "البرامج", "program"])
@commands.has_permissions(administrator=True)
async def program_log_cmd(ctx):
    """!برنامج - لوق البرامج والأنشطة في الرومات الصوتية"""
    guild = ctx.guild
    is_on = activity_tracking_enabled.get(guild.id, False)
    embed = discord.Embed(title="💻 لوق البرامج", color=0x5865F2)
    embed.add_field(name="📊 الحالة", value="🟢 مفعّل" if is_on else "🔴 معطّل", inline=True)
    embed.add_field(name="🔗 السيرفر", value=guild.name, inline=True)

    config = log_channels.get(guild.id, {})
    act_ch_id = config.get("log_activity")
    act_ch = bot.get_channel(act_ch_id) if act_ch_id else None
    embed.add_field(name="📍 روم اللوق", value=act_ch.mention if act_ch else "❌ غير مُنشأ", inline=False)

    voice_members = []
    for ch in guild.voice_channels:
        for m in ch.members:
            if not m.bot and m.activity:
                act_type = str(m.activity.type).split(".")[-1] if m.activity.type else "custom"
                label = _ACTIVITY_LABELS.get(act_type, "⚙️")
                voice_members.append(f"{m.mention} — {label} **{getattr(m.activity, 'name', '?')}**")

    if voice_members:
        embed.add_field(name=f"🎮 الأنشطة الحالية ({len(voice_members)})", value="\n".join(voice_members[:15]), inline=False)
    else:
        embed.add_field(name="🎮 الأنشطة الحالية", value="لا يوجد أعضاء بنشاط في الرومات الصوتية", inline=False)

    embed.set_footer(text="برنامج on | برنامج off | !log نشاط on/off")
    await ctx.send(embed=embed)

@bot.command(name="program_on", aliases=["برنامج_on", "برنامج on"])
@commands.has_permissions(administrator=True)
async def program_on_cmd(ctx):
    """تفعيل تتبع البرامج"""
    activity_tracking_enabled[ctx.guild.id] = True
    save_data()
    await ctx.send("✅ **تم تفعيل تتبع البرامج** — سيتم تسجيل جميع الأنشطة في الرومات الصوتية")

@bot.command(name="program_off", aliases=["برنامج_off", "برنامج off"])
@commands.has_permissions(administrator=True)
async def program_off_cmd(ctx):
    """تعطيل تتبع البرامج"""
    activity_tracking_enabled[ctx.guild.id] = False
    save_data()
    await ctx.send("🛑 **تم تعطيل تتبع البرامج**")

@bot.command(name="log_webhook", aliases=["لوق_ويبهوك"])
@commands.has_permissions(administrator=True)
async def log_webhook_cmd(ctx):
    """$log_webhook - عرض رومات اللوق (Webhook)"""
    config = log_channels.get(ctx.guild.id)
    if not config:
        return await ctx.send("❌ لا توجد رومات لوق مُعدّة. استخدم `!log` أولاً.")

    embed = discord.Embed(
        title="💻  رومات اللوق — Webhook",
        description="رومات اللوق المخصصة للويب هوك:",
        color=0x5865F2
    )

    for key, name in WEBHOOK_LOG_CHANNELS.items():
        ch_id = config.get(key)
        ch = bot.get_channel(ch_id) if ch_id else None
        value = ch.mention if ch else "❌ غير مُنشأ"
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text="ROMAT LOG — WEBHOOK | $log_webhook")
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="سحب", description="يبحث عن مستخدم بالايدي الرقمي")
async def سحب(ctx, user_id: str):
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="🔍 بحث عن مستخدم", color=0x3498DB)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="الاسم", value=user.name, inline=True)
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.add_field(name="بوت", value="نعم" if user.bot else "لا", inline=True)
        embed.add_field(name="تاريخ الإنشاء", value=user.created_at.strftime("%Y-%m-%d"), inline=True)
        await ctx.send(embed=embed)
    except ValueError:
        await ctx.send("❌ الرقم غير صالح. أدخل ID رقمي صحيح.")
    except discord.NotFound:
        await ctx.send("❌ ما لقيت مستخدم بهالID.")

LOG_TEST_TYPES = {
    "all":         "📋 الكل",
    "protection":  "💻 PROTECTION ∙ SERVER",
    "ban_kick":    "💻 BAN ∙ KICK ∙ TIMEOUT",
    "channels":    "💻 CHANNELS",
    "admin_leave": "💻 ADMIN ∙ LEAVE",
    "edit_role":   "💻 EDIT ∙ ROLE",
    "admins_role": "💻 ADMINSROLE",
    "role":        "💻 ROLE",
    "messages":    "💻 MESSAGES",
    "nickname":    "💻 NICKNAME",
    "log_all":     "💻 ALL",
}
LOG_TEST_KEYS = {
    "all": None, "protection": "log_protection", "ban_kick": "log_ban_kick",
    "channels": "log_channels", "admin_leave": "log_admin_leave",
    "edit_role": "log_edit_role", "admins_role": "log_admins_role",
    "role": "log_role", "messages": "log_messages", "nickname": "log_nickname",
    "log_all": "log_all",
}

@bot.command(name="test_log", aliases=["اختبار_لوق"])
@commands.has_permissions(administrator=True)
async def test_log(ctx, type_name: str = "all"):
    """!test_log <نوع> - إرسال إيمبيد اختباري لنوع لوق محدد"""
    type_name = type_name.lower()
    if type_name not in LOG_TEST_KEYS:
        names = " | ".join(f"`{k}`" for k in LOG_TEST_KEYS)
        return await ctx.reply(f"❌ الأنواع: {names}")

    now_ts = f"<t:{int(datetime.now().timestamp())}:F>"
    base_footer = f"🌐  {ctx.guild.name}  •  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"

    if type_name == "protection":
        embed = LogEmbed.base("🛡️ حماية — تهديد مكتشف", LogColors.PROTECT, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "المخالف")
        embed.add_field(name="⚠️ نوع التهديد", value="Spam / Raid / Nuke / Bad Word", inline=True)
        embed.add_field(name="📊 درجة الخطورة", value="🔴 عالية (8/10)", inline=True)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
        LogEmbed.details_field(embed, reason="إرسال رسائل متكررة بسرعة", action="تم حظر الروابط تلقائياً")
    elif type_name == "ban_kick":
        embed = LogEmbed.base("👢 طرد عضو", LogColors.TIMEOUT, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "المطرود")
        embed.add_field(name="📅 عمر الحساب", value="365 يوم ✅", inline=True)
        embed.add_field(name="⏱️ مدة الإقامة", value="30 يوم، 5 ساعات، 22 دقيقة", inline=True)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.details_field(embed, reason="مخالفة قواعد السيرفر", action="طرد من السيرفر")
    elif type_name == "channels":
        embed = LogEmbed.base("📁 إنشاء روم", LogColors.CREATE, guild=ctx.guild)
        embed.add_field(name="📍 الروم", value=f"#روم-جديد `({ctx.channel.id})`", inline=True)
        embed.add_field(name="📝 النوع", value="💬 نصي", inline=True)
        embed.add_field(name="📂 القسم", value="General", inline=True)
        embed.add_field(name="📋 الموضوع", value="رووم للنقاشات العامة", inline=False)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
    elif type_name == "admin_leave":
        embed = LogEmbed.base("⭐ مغادرة VIP", LogColors.WARN, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "العضو")
        embed.add_field(name="🎭 الرتب", value="@Admin | @VIP | @ Moderator", inline=False)
        embed.add_field(name="⏱️ مدة الإقامة", value="120 يوم، 8 ساعات", inline=True)
        embed.add_field(name="💎 Nitro Booster", value="✅ كان Booster", inline=True)
    elif type_name == "edit_role":
        embed = LogEmbed.base("🎭 إنشاء رتبة جديدة", LogColors.CREATE, guild=ctx.guild)
        embed.add_field(name="🏷️ الرتبة", value="@رتبة_جديدة")
        embed.add_field(name="🆔 المعرف", value=f"`99999999`", inline=True)
        embed.add_field(name="🎨 اللون", value="#FF5733", inline=True)
        embed.add_field(name="📌 الظهور المنفصل", value="✅ نعم", inline=True)
        embed.add_field(name="💬 قابل للمنشن", value="❌ لا", inline=True)
        embed.add_field(name="📍 الموقع", value="#5", inline=True)
        embed.add_field(name="🔐 الصلاحيات", value="Administrator, Manage Server, Ban Members", inline=False)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
    elif type_name == "admins_role":
        embed = LogEmbed.base("👑 تعديل رتبة عضو", LogColors.ROLE, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "العضو")
        embed.add_field(name="➕ رتبة مضافة", value="@NewRole", inline=True)
        embed.add_field(name="➖ رتبة مسحوبة", value="@OldRole", inline=True)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
    elif type_name == "role":
        embed = LogEmbed.base("📥 دخول عضو", LogColors.JOIN, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "العضو")
        embed.add_field(name="📅 عمر الحساب", value="200 يوم ✅", inline=True)
        embed.add_field(name="🤖 بوت؟", value="❌ لا", inline=True)
        embed.add_field(name="💎 Nitro Booster", value="✅ عضو مدعم", inline=True)
        embed.add_field(name="👥 عدد الأعضاء", value=f"{ctx.guild.member_count} عضو", inline=True)
    elif type_name == "messages":
        embed = LogEmbed.base("🗑️ حذف رسالة", LogColors.DELETE, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "المرسل")
        LogEmbed.channel_field(embed, "القناة", ctx.channel)
        embed.add_field(name="⏱️ عمر الرسالة", value="5 دقائق", inline=True)
        embed.add_field(name="📝 عُدت سابقاً", value="✅ نعم", inline=True)
        embed.add_field(name="📌 مثبتة", value="❌ لا", inline=True)
        embed.add_field(name="🗑️ من حذفه", value=f"{ctx.author.mention} ⚙️", inline=True)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        embed.add_field(name="📄 المحتوى", value="> مرحبا بالجميع! هذا نص اختباري للرسالة المحذوفة.", inline=False)
        embed.add_field(name="📄 دليل المخالفة", value="> مرحبا بالجميع!\n🔗 [قفز للرسالة](https://discord.com)", inline=False)
    elif type_name == "nickname":
        embed = LogEmbed.base("🏷️ تغيير الاسم", LogColors.EDIT, guild=ctx.guild)
        LogEmbed.user_field(embed, ctx.author, "العضو")
        embed.add_field(name="📝 الاسم القديم", value=ctx.author.name, inline=True)
        embed.add_field(name="✏️ الاسم الجديد", value="NewNickname", inline=True)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
    elif type_name == "log_all":
        embed = LogEmbed.base("⚙️ تحديث السيرفر", LogColors.WARN, guild=ctx.guild)
        embed.add_field(name="📋 التغييرات", value="├─ الاسم: قديم → جديد\n├─ 📷 تم تغيير الأيقونة\n├─ 💎 مستوى الـ Boost: 1 → 2\n└─ 👑 تغيير المالك: `111` → `222`", inline=False)
        embed.add_field(name="─────────────────────────────", value="\u200b", inline=False)
        LogEmbed.audit_field(embed, ctx.author)
    else:
        embed = discord.Embed(
            title=f"🧪 {LOG_TEST_TYPES[type_name]}",
            description=f"اختبار روم `{LOG_TEST_KEYS[type_name]}`",
            color=0x00FFAA,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.add_field(name="📅 التاريخ", value=now_ts, inline=True)
        embed.add_field(name="👤 المرسل", value=ctx.author.mention, inline=True)

    if not embed.footer.text or embed.footer.text == "":
        embed.set_footer(text=base_footer)

    if type_name == "all":
        sent = 0
        for key in LOG_TEST_KEYS:
            if key == "all" or not LOG_TEST_KEYS[key]: continue
            try:
                await send_log(ctx.guild.id, LOG_TEST_KEYS[key], embed, bot=bot)
                sent += 1
            except: pass
        await ctx.reply(f"✅ تم إرسال الاختبار إلى **{sent}** روم لوق")
    else:
        await send_log(ctx.guild.id, LOG_TEST_KEYS[type_name], embed, bot=bot)
        await ctx.reply(f"✅ تم إرسال الاختبار إلى `{LOG_TEST_KEYS[type_name]}`")

@bot.command(name="شرح", aliases=["tutorial", "guide", "دليل"])
async def شرح(ctx):
    """📚 دليل استخدام MAX BOT"""
    embed = discord.Embed(
        title="📚 دليل استخدام MAX BOT",
        description="دليل شامل لجميع أوامر البوت",
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="🛡️ الحماية", value=(
        "`!حماية` — لوحة الحماية\n"
        "`!حماية فعال` — تفعيل\n"
        "`!حماية معطّل` — تعطيل\n"
        "الحماية: سبام، فلود، منشن، كلمات، روابط"
    ), inline=False)
    embed.add_field(name="🎫 التذاكر", value=(
        "`!setticket` — إنشاء لوحة التذاكر\n"
        "`!صورة_تكت` — تغيير صورة اللوحة\n"
        "التصنيفات: سؤال، مشكلة، شكوى، طلب برمجة، مساعدة"
    ), inline=False)
    embed.add_field(name="📋 اللوق", value=(
        "`!log` — إعداد اللوق\n"
        "`!log rom #channel` — تعيين روم\n"
        "10 رومات: أعضاء، رسائل، صوت، دعوات، إلخ"
    ), inline=False)
    embed.add_field(name="🎵 الموسيقى", value=(
        "`!تشغيل <رابط>` — تشغيل أغنية\n"
        "`!ايقاف` — إيقاف\n"
        "`!قائمة` — قائمة التشغيل"
    ), inline=False)
    embed.add_field(name="🎮 الألعاب", value=(
        "`!لعبة حجر` — حجر ورقة مقص\n"
        "`!لعبة تخمين` — تخمين الرقم\n"
        "`!لعبة روليت` — الروليت الروسية\n"
        "`!لعبة اكس او` — X O"
    ), inline=False)
    embed.add_field(name="👋 الترحيب", value=(
        "`!ترحيب` — إعداد الترحيب\n"
        "`!رتب تلقاء @role` — رتبة تلقائية"
    ), inline=False)
    embed.add_field(name="🔧 الإدارة", value=(
        "`!kick @عضو` — طرد\n"
        "`!ban @عضو` — حظر\n"
        "`!mute @عضو` — كتم\n"
        "`!warn @عضو` — تحذير"
    ), inline=False)
    embed.add_field(name="🧪 الاختبارات", value=(
        "`!اختبار` — اختبار برمجي صعب\n"
        "`!ريادة` — leaderboard\n"
        "`!إحصائيات_اختبار` — الإحصائيات"
    ), inline=False)
    try:
        with open("server_url2.txt", "r", encoding="utf-8-sig") as f:
            dashboard_url = f.read().strip().splitlines()[0]
    except Exception:
        dashboard_url = "https://maxbot.example.com"
    embed.add_field(name="🔗 روابط البرنامج", value=(
        "**📦 GitHub:**\n"
        "[https://github.com/max-bot96/max-bot](https://github.com/max-bot96/max-bot)\n\n"
        "**🌐 لوحة التحكم:**\n"
        f"[{dashboard_url}]({dashboard_url})\n\n"
        "**📱 التواصل:**\n"
        "[تيليجرام](https://t.me/maxpot_0) • [الدعم](mailto:MaxoptSupportTeam@gmail.com)"
    ), inline=False)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • دليل الأوامر\n═══════════════════════════")
    await ctx.send(embed=embed)

class QuizAnswerView(View):
    def __init__(self, quiz_view, question):
        super().__init__(timeout=30)
        self.quiz_view = quiz_view
        self.question = question
        self.answered = False

    @discord.ui.button(label="A", style=discord.ButtonStyle.blurple, custom_id="quiz_a")
    async def answer_a(self, interaction, button):
        await self._handle_answer(interaction, 0)

    @discord.ui.button(label="B", style=discord.ButtonStyle.blurple, custom_id="quiz_b")
    async def answer_b(self, interaction, button):
        await self._handle_answer(interaction, 1)

    @discord.ui.button(label="C", style=discord.ButtonStyle.blurple, custom_id="quiz_c")
    async def answer_c(self, interaction, button):
        await self._handle_answer(interaction, 2)

    @discord.ui.button(label="D", style=discord.ButtonStyle.blurple, custom_id="quiz_d")
    async def answer_d(self, interaction, button):
        await self._handle_answer(interaction, 3)

    @discord.ui.button(label="💡 تلميح", style=discord.ButtonStyle.gray, custom_id="quiz_hint")
    async def hint_btn(self, interaction, button):
        if self.answered:
            return await interaction.response.send_message("❌ جاوبت بالفعل!", ephemeral=True)
        if self.quiz_view.hints_used >= 3:
            return await interaction.response.send_message("❌ استنفد التلميحات!", ephemeral=True)
        self.quiz_view.hints_used += 1
        embed = discord.Embed(
            title=f"💡 تلميح — السؤال {self.quiz_view.current_q+1} of 5",
            description=f"**{self.question['category']}:**\n\n{self.question['question']}\n\n💡 **التلميح:** {self.question['hint']}",
            color=0xF39C12
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _handle_answer(self, interaction, answer_idx):
        if self.answered:
            try:
                return await interaction.response.send_message("❌ جاوبت بالفعل!", ephemeral=True)
            except discord.errors.InteractionResponded:
                return
        if interaction.user.id != self.quiz_view.user_id:
            try:
                return await interaction.response.send_message("❌ هذا الاختبار لك فقط!", ephemeral=True)
            except discord.errors.InteractionResponded:
                return
        self.answered = True
        for child in self.children:
            child.disabled = True
        correct = answer_idx == self.question["correct"]
        if correct:
            self.quiz_view.score += 10
        else:
            self.quiz_view.score += 0
        self.quiz_view.answers.append(answer_idx)
        result_emoji = "✅" if correct else "❌"
        correct_answer = self.question["options"][self.question["correct"]]
        embed = discord.Embed(
            title=f"{result_emoji} السؤال {self.quiz_view.current_q+1} من 5",
            description=(
                f"**{self.question['category']}:**\n\n"
                f"{self.question['question']}\n\n"
                f"**إجابتك:** {self.question['options'][answer_idx]}\n"
                f"**الإجابة الصحيحة:** {correct_answer}\n\n"
                f"**الشرح:** {self.question['explanation']}\n\n"
                f"**النقاط:** {self.quiz_view.score}/50"
            ),
            color=0x2ECC71 if correct else 0xE74C3C
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.quiz_view.current_q += 1
        await asyncio.sleep(2)
        if self.quiz_view.current_q < 5:
            await self.quiz_view.send_question(interaction)
        else:
            await self.quiz_view.finish_quiz(interaction)

class WelcomeQuizView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="🧪 اختبار برمجي", style=discord.ButtonStyle.blurple, custom_id="welcome_quiz_btn")
    async def quiz_btn(self, interaction, button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ هذا الزر لك فقط!", ephemeral=True)
        await interaction.response.send_message("📥 أرسلت لك الاختبار في DM! افتح الرسائل الخاصة.", ephemeral=True)
        embed = discord.Embed(
            title="🧪 اختبار برمجي — صعب جداً!",
            description=(
                "═══════════════════════════\n"
                "⚠️ **تحذير: هذا اختبار صعب جداً!**\n"
                "═══════════════════════════\n\n"
                "📋 **5 أسئلة** في:\n"
                "├─ Python Internals\n"
                "├─ Python المتقدم\n"
                "├─ Python عالي المستوى\n"
                "├─ خوارزميات\n"
                "└─ عامة\n\n"
                "⏱️ **15 ثانية** لكل سؤال\n"
                "💡 **3 تلميحات** متاحة\n"
                "🏆 **أعلى درجة:** 50 نقطة\n\n"
                "═══════════════════════════"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • اختبار برمجي\n═══════════════════════════")
        try:
            await interaction.user.send(embed=embed, view=QuizView(interaction.user.id))
        except:
            await interaction.followup.send("❌ لا أستطيع إرسال DM. فتح الرسائل الخاصة أولاً!", ephemeral=True)

class QuizView(View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_q = 0
        self.score = 0
        self.hints_used = 0
        self.start_time = None
        self.questions = random.sample(QUIZ_QUESTIONS, min(5, len(QUIZ_QUESTIONS)))
        self.answers = []

    @discord.ui.button(label="ابدأ الاختبار 🚀", style=discord.ButtonStyle.green, custom_id="start_quiz")
    async def start_btn(self, interaction, button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ هذا الاختبار لك فقط!", ephemeral=True)
        self.start_time = datetime.now(timezone.utc)
        await self.send_question(interaction)

    async def send_question(self, interaction):
        q = self.questions[self.current_q]
        embed = discord.Embed(
            title=f"🧪 السؤال {self.current_q+1} من 5 — صعب!",
            description=(
                f"**{q['category']}:**\n\n"
                f"{q['question']}\n\n"
                f"⏱️ الوقت: 15 ثانية | 💡 تلميحات متبقية: {3 - self.hints_used}\n"
                f"**النقاط:** {self.score}/150"
            ),
            color=0xE74C3C
        )
        view = QuizAnswerView(self, q)
        await interaction.response.edit_message(embed=embed, view=view)

    async def finish_quiz(self, interaction):
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60
        level, badge = get_level(self.score)
        save_quiz_score(interaction.guild.id, self.user_id, self.score, elapsed, self.hints_used)
        categories = {}
        for i, q in enumerate(self.questions):
            cat = q["category"]
            if cat not in categories:
                categories[cat] = {"total": 0, "correct": 0}
            categories[cat]["total"] += 1
            if i < len(self.answers) and self.answers[i] == q["correct"]:
                categories[cat]["correct"] += 1
        analysis = ""
        for cat, data in categories.items():
            emoji = "✅" if data["correct"] == data["total"] else "⚠️"
            analysis += f"├─ {cat}: {data['correct']}/{data['total']} {emoji}\n"
        try:
            invite = await interaction.channel.create_invite(max_age=3600, reason="Quiz complete")
            invite_link = invite.url
        except:
            invite_link = "غير متاح"
        embed = discord.Embed(
            title=f"🏆 نتيجة الاختبار — {badge} {level}",
            description=(
                f"═══════════════════════════\n"
                f"🏆 **نتيجة الاختبار البرمجي**\n"
                f"═══════════════════════════\n\n"
                f"**العضو:** {interaction.user.mention}\n\n"
                f"📊 **النتيجة:** {self.score}/150\n"
                f"🎯 **المستوى:** {badge} {level}\n"
                f"⏱️ **الوقت:** {elapsed:.1f} دقيقة\n"
                f"💡 **التلميحات:** {self.hints_used}\n\n"
                f"📋 **التحليل:**\n{analysis}\n"
                f"═══════════════════════════"
            ),
            color=0xFFD700 if self.score >= 130 else 0x2ECC71 if self.score >= 70 else 0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="═══════════════════════════\nMAX BOT • اختبار برمجي\n═══════════════════════════")
        await interaction.followup.send(embed=embed)
        try:
            dm_embed = discord.Embed(
                title=f"🏆 نتيجة الاختبار — {badge} {level}",
                description=(
                    f"═══════════════════════════\n"
                    f"**النتيجة:** {self.score}/150\n"
                    f"**المستوى:** {badge} {level}\n"
                    f"**الوقت:** {elapsed:.1f} دقيقة\n"
                    f"═══════════════════════════\n\n"
                    f"🔗 **رابط الدعوة:**\n[اضغط للعودة للسيرفر]({invite_link})\n\n"
                    f"═══════════════════════════\nMAX BOT • اختبار برمجي\n═══════════════════════════"
                ),
                color=0xFFD700
            )
            await interaction.user.send(embed=dm_embed)
        except:
            pass

@bot.command(name="اختبار", aliases=["quiz", "test"])
async def اختبار(ctx):
    """🧪 اختبار برمجي صعب جداً"""
    embed = discord.Embed(
        title="🧪 اختبار برمجي — صعب جداً!",
        description=(
            "═══════════════════════════\n"
            "⚠️ **تحذير: هذا اختبار صعب جداً!**\n"
            "═══════════════════════════\n\n"
            "📋 **5 أسئلة** في:\n"
            "├─ Python Internals\n"
            "├─ Python المتقدم\n"
            "├─ Python عالي المستوى\n"
            "├─ خوارزميات\n"
            "└─ عامة\n\n"
            "⏱️ **15 ثانية** لكل سؤال\n"
            "💡 **3 تلميحات** متاحة (تقلل النقاط)\n"
            "🏆 **أعلى درجة:** 50 نقطة\n\n"
            "═══════════════════════════"
        ),
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • اختبار برمجي\n═══════════════════════════")
    await ctx.send(embed=embed, view=QuizView(ctx.author.id))

@bot.command(name="ريادة", aliases=["leaderboard", "top", "قائمة_ال TOP"])
async def ريادة(ctx):
    """🏆 Leaderboard — اختبار برمجي"""
    lb = get_leaderboard(ctx.guild.id)
    embed = discord.Embed(
        title="🏆 Leaderboard — اختبار برمجي",
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc)
    )
    medals = ["🥇", "🥈", "🥉"]
    if not lb:
        embed.description = "لا توجد نتائج بعد. كن أول من يُجري الاختبار!"
    else:
        desc = ""
        for i, (user_id, info) in enumerate(lb[:10]):
            user = ctx.guild.get_member(user_id)
            name = user.display_name if user else f"User#{user_id}"
            medal = medals[i] if i < 3 else f"{i+1}."
            score = info.get("score", 0)
            level = info.get("level", "غير محدد")
            desc += f"{medal} **{name}** — {score}/150 — {level}\n"
        embed.description = desc
    embed.set_footer(text="═══════════════════════════\nMAX BOT • Leaderboard\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="تل", description="سحب عضو لرومك الصوتي")
async def تل(ctx, member: discord.Member):
    await ctx.send(f"✅ تم. {member.mention}")

# ════════════════════════════════════════
# الأوامر الأساسية
# ════════════════════════════════════════

@bot.hybrid_command(name="say", description="يقول البوت رسالة نيابة عنك")
async def say(ctx, *, message: str):
    """!say <نص> - البوت يرسل رسالتك"""
    await ctx.message.delete()
    await ctx.send(message)

@bot.hybrid_command(name="kick", aliases=["طرد", "كك"], description="طرد عضو من السيرفر")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="لا يوجد سبب"):
    """!kick @عضو <سبب> - طرد عضو"""
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 طرد عضو", color=0xE67E22)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    account_age = (discord.utils.utcnow() - member.created_at).days
    embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم", inline=True)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("👢 طرد عضو", LogColors.TIMEOUT, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    log_embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم {'⚠️' if account_age < 7 else '✅'}", inline=True)
    if member.joined_at:
        time_in_server = discord.utils.utcnow() - member.joined_at
        days = time_in_server.days
        hours, remainder = divmod(time_in_server.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days} يوم، {hours} ساعة، {minutes} دقيقة"
        elif hours > 0:
            duration_str = f"{hours} ساعة، {minutes} دقيقة"
        else:
            duration_str = f"{minutes} دقيقة"
        log_embed.add_field(name="⏱️ مدة الإقامة", value=duration_str, inline=True)
    LogEmbed.details_field(log_embed, reason=reason, action="طرد من السيرفر")
    await send_log(ctx.guild.id, "ban_kick_timeout", log_embed, bot=bot, admin=ctx.author)

@kick.error
async def kick_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لطرد الأعضاء.")

@bot.hybrid_command(name="ban", description="حظر عضو نهائياً من السيرفر")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="لا يوجد سبب"):
    """!ban @عضو <سبب> - حظر عضو"""
    await member.ban(reason=reason)
    embed = discord.Embed(title="🔨 حظر عضو", color=0x000000)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    account_age = (discord.utils.utcnow() - member.created_at).days
    embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم", inline=True)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("🔨 حظر عضو", LogColors.PROTECT, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    log_embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم {'⚠️ حساب جديد!' if account_age < 7 else '✅'}", inline=True)
    if member.joined_at:
        time_in_server = discord.utils.utcnow() - member.joined_at
        days = time_in_server.days
        hours, remainder = divmod(time_in_server.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days} يوم، {hours} ساعة، {minutes} دقيقة"
        elif hours > 0:
            duration_str = f"{hours} ساعة، {minutes} دقيقة"
        else:
            duration_str = f"{minutes} دقيقة"
        log_embed.add_field(name="⏱️ مدة الإقامة", value=duration_str, inline=True)
    LogEmbed.details_field(log_embed, reason=reason, action="حظر نهائي من السيرفر")
    await send_log(ctx.guild.id, "ban_kick_timeout", log_embed, bot=bot, admin=ctx.author)

@ban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لحظر الأعضاء.")

@bot.hybrid_command(name="unban", description="إلغاء حظر عضو")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, member):
    """!unban username#0000 - إلغاء حظر عضو"""
    banned_users = [entry async for entry in ctx.guild.bans()]
    name, discriminator = member.split("#")
    for ban_entry in banned_users:
        user = ban_entry.user
        if (user.name, user.discriminator) == (name, discriminator):
            await ctx.guild.unban(user)
            embed = discord.Embed(title="✅ إلغاء حظر", color=0x2ECC71)
            embed.add_field(name="العضو", value=f"{user.name}#{user.discriminator}")
            embed.add_field(name="بواسطة", value=ctx.author.mention)
            await ctx.send(embed=embed)
            return
    await ctx.send("❌ ما لقيت هذا العضو في قائمة المحظورين.")

@bot.hybrid_command(name="clear", aliases=['purge', 'مسح'], description="مسح رسائل من القناة")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    """!clear <عدد> - مسح رسائل"""
    if amount < 1:
        await ctx.send("❌ العدد يكون 1 أو أكثر.")
        return
    if amount > 1000:
        await ctx.send("❌ الحد الأقصى 1000 رسالة. استخدم `!clear 1000` لمسح كل شي.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ تم مسح {len(deleted) - 1} رسالة.")
    await asyncio.sleep(3)
    await msg.delete()

@clear.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لإدارة الرسائل.")
    elif isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
        await ctx.send("❌ اكتب رقم صحيح. مثال: `!clear 10`")

@bot.hybrid_command(name="timeout", aliases=['mute', 'كتم'], description="كتم عضو (منع الكتابة والتكلم)")
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, duration: str, *, reason="لا يوجد سبب"):
    """!timeout @عضو <مدة> <سبب> - كتم عضو
    المدة: 1m, 5m, 10m, 1h, 1d (دقيقة, ساعة, يوم)"""
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = duration[-1]
    if unit not in time_units:
        await ctx.send("❌ وحدة الوقت غير صحيحة. استخدم: s, m, h, d (مثال: 10m)")
        return
    try:
        value = int(duration[:-1])
    except ValueError:
        await ctx.send("❌ اكتب رقم صحيح. مثال: `!timeout @عضو 10m`")
        return

    seconds = value * time_units[unit]
    if seconds > 2419200:
        await ctx.send("❌ المدة ما تتجاوز 28 يوم.")
        return

    until = discord.utils.utcnow() + timedelta(seconds=seconds)
    await member.timeout(until, reason=reason)
    embed = discord.Embed(title="🔇 عضو مكتوم", color=0x95A5A6)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="المدة", value=duration)
    embed.add_field(name="السبب", value=reason, inline=False)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    account_age = (discord.utils.utcnow() - member.created_at).days
    embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم", inline=True)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("🔇 كتم عضو", LogColors.TIMEOUT, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    log_embed.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم {'⚠️' if account_age < 7 else '✅'}", inline=True)
    if member.joined_at:
        time_in_server = discord.utils.utcnow() - member.joined_at
        days = time_in_server.days
        hours, remainder = divmod(time_in_server.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days} يوم، {hours} ساعة، {minutes} دقيقة"
        elif hours > 0:
            duration_str = f"{hours} ساعة، {minutes} دقيقة"
        else:
            duration_str = f"{minutes} دقيقة"
        log_embed.add_field(name="⏱️ مدة الإقامة", value=duration_str, inline=True)
    LogEmbed.details_field(log_embed, reason=reason, action=f"كتم لمدة {duration} (حتى <t:{int(until.timestamp())}:R>)")
    await send_log(ctx.guild.id, "ban_kick_timeout", log_embed, bot=bot, admin=ctx.author)

@timeout.error
async def timeout_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لكتم الأعضاء.")

@bot.hybrid_command(name="untimeout", aliases=['unmute', 'فك_الكتم'], description="إلغاء كتم عضو")
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    """!untimeout @عضو - إلغاء كتم عضو"""
    await member.timeout(None)
    embed = discord.Embed(title="🔊 تم فك الكتم", color=0x2ECC71)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("🔊 فك الكتم", LogColors.CREATE, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    LogEmbed.details_field(log_embed, action="إلغاء الكتم")
    await send_log(ctx.guild.id, "ban_kick_timeout", log_embed, bot=bot, admin=ctx.author)

BAND_PHRASES = [
    "انقرض مثل الديناصورات 🦖",
    "**برااااااااااااااا** 🚪",
    "سم ☠️",
    "روحه بلا عودة... 💔",
    "انقلع يا .............. 🖕",
    "برااا لعيوننن عزززززززز 🔥",
    "انت تامر امر؟ كم عندك عزوووزي انا؟ بس لي انا 👑",
]

@bot.command(name="باند")
async def باند(ctx, user_id: int, *, reason="بدون سبب"):
    """!باند <user_id> <سبب> - حظر عضو بالـ ID"""
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    try:
        await ctx.guild.ban(discord.Object(id=user_id), reason=reason)
    except Exception as e:
        return await ctx.reply(f"❌ فشل الحظر: {e}")
    phrase = random.choice(BAND_PHRASES)
    embed = LogEmbed.base("🔨 تم الحظر", LogColors.PROTECT, guild=ctx.guild)
    embed.add_field(name="🆔 العضو", value=f"`{user_id}`", inline=False)
    embed.add_field(name="🏷 السبب", value=reason, inline=False)
    embed.add_field(name="👤 المنفذ", value=ctx.author.mention, inline=False)
    await ctx.reply(f"{phrase}\n", embed=embed)
    await send_log(ctx.guild.id, "ban_kick_timeout", embed, bot=bot, admin=ctx.author)

@باند.error
async def باند_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.reply("❌ اكتب ID رقمي صحيح. مثال: `!باند 12345678 سبب`")
    else:
        print(f"[باند ERROR] {error}")

@bot.command(name="صيد_الهكر", aliases=["صيد الهكر", "hacker_bait"])
@commands.has_permissions(administrator=True)
async def hacker_bait(ctx, action: str = None, *, arg: str = None):
    """!صيد_الهكر — تعيين/تحكم بنظام صيد الهاكرز"""
    global hacker_bait_channels
    guild_id = ctx.guild.id

    if not action or action not in ["status", "حالة", "رسالة", "message", "فاصل", "interval", "تشغيل", "إيقاف"]:
        if action and action.startswith("#"):
            channel = ctx.guild.get_channel(int(action.strip("#<>")))
            if not channel:
                try:
                    channel = await commands.TextChannelConverter().convert(ctx, action)
                except:
                    pass
        elif action and not action.startswith("#"):
            try:
                channel = await commands.TextChannelConverter().convert(ctx, action)
            except:
                channel = None
        else:
            channel = None

        if channel:
            hacker_bait_channels[guild_id] = channel.id
            save_data(force=True)
            embed = discord.Embed(
                title="🪤 تم تفعيل قناة الفخ",
                description=(
                    f"**القناة:** {channel.mention}\n\n"
                    "**⚠️ كيف يعمل:**\n"
                    "• أي عضو يكتب فيها → يُكِك فوراً\n"
                    "• يُحذف الرابط/الرسالة\n"
                    "• يُرسل DM للعضو بتحذير\n\n"
                    "**المشرفين لا يتأثرون**"
                ),
                color=0xE74C3C
            )
            embed.set_footer(text="MAX BOT • صيد الهاكرز")
            await ctx.send(embed=embed)
        else:
            if guild_id in hacker_bait_channels:
                ch = ctx.guild.get_channel(hacker_bait_channels[guild_id])
                if ch:
                    await ctx.send(f"❌ قناة الفخ موجودة بالفعل: {ch.mention}\nاستخدم: `!صيد_الهكر #قناة` لتحديد مختلفة")
                    return
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, kick_members=True)
            }
            channel = await ctx.guild.create_text_channel(
                name="Anti Bot Channel",
                topic="⚠️ قناة فخ - أي رسالة هنا تسبب طرد المرسل",
                overwrites=overwrites
            )
            hacker_bait_channels[guild_id] = channel.id
            save_data(force=True)
            embed = discord.Embed(
                title="🪤 تم إنشاء قناة الفخ",
                description=(
                    f"**القناة:** {channel.mention}\n\n"
                    "**⚠️ كيف يعمل:**\n"
                    "• أي عضو يكتب فيها → يُكِك فوراً\n"
                    "• يُحذف الرابط/الرسالة\n"
                    "• يُرسل DM للعضو بتحذير\n\n"
                    "**المشرفين لا يتأثرون**"
                ),
                color=0xE74C3C
            )
            embed.set_footer(text="MAX BOT • صيد الهاكرز")
            await ctx.send(embed=embed)
        return

    if action in ["status", "حالة"]:
        ch_id = hacker_bait_channels.get(guild_id)
        ch = ctx.guild.get_channel(ch_id) if ch_id else None
        embed = discord.Embed(
            title="═══════════════════════════\n🪤 حالة نظام صيد الهاكرز\n═══════════════════════════",
            description=(
                f"├─ **القناة:** {ch.mention if ch else 'غير محددة'}\n"
                f"├─ **المشرفين:** لا يتأثرون\n"
                f"└─ **الحالة:** {'✅ مفعّل' if ch else '❌ غير مفعّل'}"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد الهاكرز\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action in ["رسالة", "message"]:
        await ctx.send("ℹ️ الرسالة الحالية مُدمجة في النظام ولا يمكن تغييرها حالياً.")

    elif action in ["فاصل", "interval"]:
        await ctx.send("ℹ️ الفاصل مُدمج في on_message ولا يمكن تغييره حالياً.")

    elif action in ["اختبار", "test"]:
        if ctx.author.id != YOUR_USER_ID:
            return await ctx.reply("❌ هذا الأمر لصاحب البوت فقط")
        lines = []
        lines.append("═══ 🧪 اختبار نظام صيد الهاكرز ═══\n")
        ch_id = hacker_bait_channels.get(guild_id)
        ch = ctx.guild.get_channel(ch_id) if ch_id else None
        lines.append(f"**1. قناة الصيد:** {ch.mention if ch else '❌ غير محددة'}")
        lines.append(f"   hacker_bait_channels = `{hacker_bait_channels}`\n")

        bot_perms = ctx.guild.me.guild_permissions
        lines.append(f"**2. صلاحيات البوت:**")
        lines.append(f"   ├─ kick_members: {'✅' if bot_perms.kick_members else '❌'}")
        lines.append(f"   ├─ manage_messages: {'✅' if bot_perms.manage_messages else '❌'}")
        lines.append(f"   └─ send_messages: {'✅' if bot_perms.send_messages else '❌'}\n")

        lines.append(f"**3. رتبة البوت:**")
        lines.append(f"   ├─ الرتبة: {ctx.guild.me.top_role.name}")
        lines.append(f"   └─ الموضع: {ctx.guild.me.top_role.position}\n")

        lines.append(f"**4. YOUR_USER_ID:** `{YOUR_USER_ID}`")
        lines.append(f"   ├─ مطابق للمالك؟ {'✅ نعم' if ctx.author.id == YOUR_USER_ID else '❌ لا'}")
        owner_user = bot.get_user(YOUR_USER_ID)
        lines.append(f"   └─ bot.get_user(): {'✅ ' + str(owner_user) if owner_user else '❌ None (يجب استخدام fetch_user)'}\n")

        try:
            owner_fetch = await bot.fetch_user(YOUR_USER_ID)
            lines.append(f"**5. fetch_user():** ✅ {owner_fetch} ({owner_fetch.id})")
            dm_ch = await owner_fetch.create_dm()
            test_embed = discord.Embed(title="🧪 اختبار نظام الصيد", description="هذا رسالة اختبار", color=0x2ECC71)
            await dm_ch.send(embed=test_embed)
            lines.append(f"**6. اختبار DM:** ✅ تم الإرسال بنجاح!")
        except Exception as e:
            lines.append(f"**5. fetch_user():** ❌ {e}")
            lines.append(f"**6. اختبار DM:** ❌ فشل\n")

        if ch:
            try:
                inv = await ch.create_invite(max_age=60, max_uses=1, reason="bait test")
                lines.append(f"**7. اختبار الدعوة:** ✅ {inv.url}")
            except Exception as e:
                lines.append(f"**7. اختبار الدعوة:** ❌ {e}")
        else:
            lines.append(f"**7. اختبار الدعوة:** ❌ لا توجد قناة صيد")

        site_url = get_base_url()
        lines.append(f"\n**8. SITE_URL:** `{site_url}`")

        result = "\n".join(lines)
        await ctx.send(f"```\n{result}\n```")

        try:
            dm_ch = await (await bot.fetch_user(YOUR_USER_ID)).create_dm()
            await dm_ch.send(f"```\n{result}\n```")
        except:
            pass


@bot.command(name="حذف")
async def حذف(ctx, *, args: str = ""):
    parts = args.strip().split()
    if not parts:
        return await ctx.reply("❌ استخدم:\n`!حذف كل الرومات`\n`!حذف ثيم <ايدي الكاتجوري>`")

    if args.strip() == "كل الرومات":
        if ctx.author.id != YOUR_USER_ID:
            return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")

        guild = ctx.guild
        channels = guild.channels
        total = len(channels)
        msg = await ctx.reply(f"⚠️ سيتم حذف **{total}** روم. اكتب `تأكيد` خلال 10 ثواني للتأكيد...")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content == "تأكيد"

        try:
            await bot.wait_for("message", timeout=10.0, check=check)
        except asyncio.TimeoutError:
            return await msg.edit(content="❌ تم إلغاء الأمر.")

        deleted = 0
        failed = 0
        for ch in channels:
            try:
                await ch.delete()
                deleted += 1
            except:
                failed += 1

        embed = LogEmbed.base("💣 حذف كل الرومات", LogColors.NUKE, guild=guild)
        embed.add_field(name="تم الحذف", value=str(deleted), inline=True)
        embed.add_field(name="فشل", value=str(failed), inline=True)
        embed.add_field(name="المنفذ", value=ctx.author.mention, inline=False)
        await ctx.send(embed=embed)
        await send_log(guild.id, "log_all", embed, admin=ctx.author)
        return

    if parts[0] == "ثيم":
        if not ctx.author.guild_permissions.manage_channels:
            return await ctx.reply("❌ تحتاج صلاحية Manage Channels")
        if len(parts) < 2:
            return await ctx.reply("❌ استخدم: `!حذف ثيم <ايدي الكاتجوري>`")
        try:
            target_id = int(parts[1])
        except ValueError:
            return await ctx.reply("❌ اكتب ID رقمي صحيح")
        cat = discord.utils.get(ctx.guild.categories, id=target_id)
        if not cat:
            return await ctx.reply(f"❌ ما لقيت كاتجوري بهذا المعرف: `{target_id}`")
        try:
            for ch in cat.channels:
                try: await ch.delete()
                except: pass
            await cat.delete()
            await ctx.reply(f"✅ تم حذف كاتجوري **{cat.name}** وكل روماتها")
        except discord.Forbidden:
            await ctx.reply("❌ البوت ما عنده صلاحية يحذف")
        except Exception as e:
            await ctx.reply(f"❌ خطأ: {e}")
        return

    return await ctx.reply("❌ استخدم:\n`!حذف كل الرومات`\n`!حذف ثيم <ايدي الكاتجوري>`")

@bot.group(name="حفظ", invoke_without_command=True)
async def حفظ(ctx):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    await ctx.reply("❌ استخدم `!حفظ الدس [اسم]`")

@حفظ.command(name="الدس")
async def حفظ_الدس(ctx, *, name: str = None):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    backup_name = name or f"{ctx.guild.name} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    backup_id = save_backup(backup_name, ctx.guild)
    stats = backup_stats(backup_id)
    embed = LogEmbed.base("💾 تم حفظ الدس", LogColors.CREATE, guild=ctx.guild)
    embed.add_field(name="الاسم", value=backup_name, inline=False)
    embed.add_field(name="📁 كاتيجوري", value=str(stats["categories"]), inline=True)
    embed.add_field(name="💬 رومات", value=str(stats["channels"]), inline=True)
    embed.add_field(name="🎭 رتب", value=str(stats["roles"]), inline=True)
    embed.set_footer(text=f"رقم النسخة: {backup_id}")
    await ctx.reply(embed=embed)

@حفظ_الدس.error
async def حفظ_الدس_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.reply("❌ خطأ في الإدخال. استخدم: `!حفظ الدس [اسم]`")

@bot.group(name="نسخ", invoke_without_command=True)
async def نسخ(ctx):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    await ctx.reply("❌ استخدم `!نسخ الدس`")

@نسخ.command(name="الدس")
async def نسخ_الدس(ctx):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    backups = list_backups()
    if not backups:
        return await ctx.reply("📭 لا توجد نسخ محفوظة. استخدم `!حفظ الدس` أولاً.")
    embed = LogEmbed.base("📂 النسخ المحفوظة", LogColors.EDIT, guild=ctx.guild)
    lines = []
    for i, b in enumerate(backups[:20], 1):
        s = backup_stats(b["id"])
        lines.append(f"**{i}.** `#{b['id']}` {b['name']}")
        lines.append(f"   📅 {b['created_at'][:16]} | {s['categories']} كاتيجوري • {s['channels']} روم • {s['roles']} رتبة")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"إجمالي {len(backups)} نسخة")
    await ctx.reply(embed=embed)

@نسخ_الدس.error
async def نسخ_الدس_error(ctx, error):
    await ctx.reply(f"❌ خطأ: {error}")

@bot.group(name="لصق", invoke_without_command=True)
async def لصق(ctx):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    await ctx.reply("❌ استخدم `!لصق الدس <رقم>`")

@لصق.command(name="الدس")
async def لصق_الدس(ctx, backup_id: int):
    if ctx.author.id != YOUR_USER_ID:
        return await ctx.reply("❌ هذا الأمر بس لصاحب البوت.")
    data = get_backup(backup_id)
    if not data:
        return await ctx.reply(f"❌ لا توجد نسخة رقم `{backup_id}`.")
    stats = backup_stats(backup_id)
    txt = sum(1 for c in data['channels'] if c['ch_type']=='text')
    vc = sum(1 for c in data['channels'] if c['ch_type']=='voice')
    msg = await ctx.reply(
        f"⚠️ سيتم إنشاء:\n"
        f"• {stats['categories']} كاتيجوري\n"
        f"• {stats['channels']} روم ({txt} نصي + {vc} صوتي)\n"
        f"• {stats['roles']} رتبة\n"
        f"اكتب `تأكيد` خلال 15 ثانية..."
    )

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content == "تأكيد"
    try:
        await bot.wait_for("message", timeout=15.0, check=check)
    except asyncio.TimeoutError:
        return await msg.edit(content="❌ تم إلغاء الأمر.")

    guild = ctx.guild
    created_roles = {}
    created_cats = {}
    failed = 0

    for r in data["roles"]:
        try:
            color = discord.Color(r["color"]) if r["color"] else discord.Color.default()
            role = await guild.create_role(
                name=r["name"], color=color,
                hoist=bool(r["hoist"]), mentionable=bool(r["mentionable"]),
                reason=f"لصق نسخة #{backup_id}"
            )
            created_roles[r["name"]] = role
        except:
            failed += 1

    for cat in data["categories"]:
        try:
            c = await guild.create_category(cat["name"])
            created_cats[cat["name"]] = c
        except:
            failed += 1

    for ch in data["channels"]:
        try:
            cat_obj = created_cats.get(ch["category"])
            if ch["ch_type"] == "text":
                await guild.create_text_channel(
                    ch["name"], category=cat_obj,
                    topic=ch["topic"] if ch["topic"] else None
                )
            else:
                await guild.create_voice_channel(
                    ch["name"], category=cat_obj,
                    bitrate=min(ch["bitrate"], 384000) if ch["bitrate"] else 64000,
                    user_limit=ch["user_limit"] or 0
                )
        except:
            failed += 1

    total = len(data["categories"]) + len(data["channels"]) + len(data["roles"])
    success = total - failed
    embed = LogEmbed.base("✅ تم لصق الدس", LogColors.CREATE, guild=guild)
    embed.add_field(name="النسخة", value=f"`#{backup_id}` — {data['backup']['name']}", inline=False)
    embed.add_field(name="تم الإنشاء", value=str(success), inline=True)
    embed.add_field(name="فشل", value=str(failed), inline=True)
    embed.add_field(name="المنفذ", value=ctx.author.mention, inline=False)
    await ctx.reply(embed=embed)
    await send_log(guild.id, "log_all", embed, admin=ctx.author)

@لصق_الدس.error
async def لصق_الدس_error(ctx, error):
    if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
        await ctx.reply("❌ اكتب رقم النسخة الصحيح. مثال: `!لصق الدس 1`")
    else:
        await ctx.reply(f"❌ خطأ: {error}")

@bot.group(name="فك", invoke_without_command=True)
async def فك(ctx):
    await ctx.reply("❌ استخدم:\n`!فك باند <id>` — فك الحظر\n`!فك تايم اوت <id>` — فك الكتم")

@فك.command(name="باند")
@commands.has_permissions(ban_members=True)
async def فك_باند(ctx, user_id: int):
    try:
        await ctx.guild.unban(discord.Object(id=user_id))
    except discord.NotFound:
        return await ctx.reply("❌ هذا العضو مو محظور أصلاً.")
    except Exception as e:
        return await ctx.reply(f"❌ فشل فك الحظر: {e}")
    embed = LogEmbed.base("✅ تم فك الحظر", LogColors.CREATE, guild=ctx.guild)
    embed.add_field(name="🆔 العضو", value=f"`{user_id}`", inline=False)
    embed.add_field(name="👤 المنفذ", value=ctx.author.mention, inline=False)
    await ctx.reply("تم العفو عنك ✅", embed=embed)
    await send_log(ctx.guild.id, "ban_kick_timeout", embed, bot=bot, admin=ctx.author)

@فك_باند.error
async def فك_باند_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ ما عندك صلاحية لفك الحظر.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ اكتب ID رقمي صحيح. مثال: `!فك باند 12345678`")

@فك.command(name="تايم اوت")
@commands.has_permissions(moderate_members=True)
async def فك_تايم_اوت(ctx, user_id: int):
    try:
        member = await ctx.guild.fetch_member(user_id)
        await member.timeout(None, reason=f"فك الكتم بواسطة {ctx.author}")
    except discord.NotFound:
        return await ctx.reply("❌ هذا العضو مو موجود في السيرفر.")
    except Exception as e:
        return await ctx.reply(f"❌ فشل فك الكتم: {e}")
    embed = LogEmbed.base("🔊 تم فك الكتم", LogColors.CREATE, guild=ctx.guild)
    embed.add_field(name="🆔 العضو", value=f"`{user_id}`", inline=False)
    embed.add_field(name="👤 المنفذ", value=ctx.author.mention, inline=False)
    await ctx.reply("تم العفو عنك ✅", embed=embed)
    await send_log(ctx.guild.id, "ban_kick_timeout", embed, bot=bot, admin=ctx.author)

@فك_تايم_اوت.error
async def فك_تايم_اوت_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ ما عندك صلاحية لفك الكتم.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ اكتب ID رقمي صحيح. مثال: `!فك تايم اوت 12345678`")

@bot.hybrid_command(name="اعطا_رتبة", aliases=['giverole', 'give-role'], description="إضافة رتبة لعضو")
@commands.has_permissions(manage_roles=True)
async def اعطا_رتبة(ctx, member: discord.Member, *, role: discord.Role):
    """!اعطا_رتبة @عضو @رتبه - إعطاء رتبة"""
    if role >= ctx.author.top_role and ctx.guild.owner_id != ctx.author.id:
        await ctx.send("❌ ما تقدر تعطي رتبة أعلى من رتبتك.")
        return
    await member.add_roles(role)
    embed = discord.Embed(title="✅ تم إعطاء الرتبة", color=0x2ECC71)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="الرتبة", value=role.mention)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("➕ إعطاء رتبة", LogColors.CREATE, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    LogEmbed.role_field(log_embed, [role])
    await send_log(ctx.guild.id, "log_role", log_embed, bot=bot, admin=ctx.author)

@اعطا_رتبة.error
async def اعطا_رتبة_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لإدارة الرتب.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ الرتبة غير موجودة.")

@bot.hybrid_command(name="سحب_رتبة", aliases=['removerole', 'remove-role'], description="سحب رتبة من عضو")
@commands.has_permissions(manage_roles=True)
async def سحب_رتبة(ctx, member: discord.Member, *, role: discord.Role):
    """!سحب_رتبة @عضو @رتبه - سحب رتبة"""
    if role >= ctx.author.top_role and ctx.guild.owner_id != ctx.author.id:
        await ctx.send("❌ ما تقدر تسحب رتبة أعلى من رتبتك.")
        return
    if role not in member.roles:
        await ctx.send("❌ العضو ما عنده هذه الرتبة.")
        return
    await member.remove_roles(role)
    embed = discord.Embed(title="✅ تم سحب الرتبة", color=0xE74C3C)
    embed.add_field(name="العضو", value=member.mention)
    embed.add_field(name="الرتبة", value=role.mention)
    embed.add_field(name="بواسطة", value=ctx.author.mention)
    await ctx.send(embed=embed)
    log_embed = LogEmbed.base("🗑️ سحب رتبة", LogColors.DELETE, guild=ctx.guild)
    LogEmbed.user_field(log_embed, member)
    LogEmbed.audit_field(log_embed, ctx.author)
    LogEmbed.role_field(log_embed, [role])
    await send_log(ctx.guild.id, "log_role", log_embed, bot=bot, admin=ctx.author)

@سحب_رتبة.error
async def سحب_رتبة_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ ما عندك صلاحية لإدارة الرتب.")

@bot.command(name="سوول", aliases=['sudo'])
@commands.has_permissions(administrator=True)
async def سوول(ctx, member: discord.Member):
    """!سوول @عضو - تعطي عضو صلاحيات مسوول كاملة"""
    admin_role = discord.utils.get(ctx.guild.roles, name="مسوول")
    if not admin_role:
        admin_role = await ctx.guild.create_role(name="مسوول", permissions=discord.Permissions.all(), color=0xFF0000)
        await admin_role.edit(position=ctx.guild.me.top_role.position - 1)

    try:
        await member.add_roles(admin_role)
        await ctx.send(f"✅ تم إعطاء {member.mention} صلاحيات **مسوول** كاملة! 🔐")
    except:
        await ctx.send("❌ ما قدرت أعطي الرتبة!")

@bot.command(name="مشرف", aliases=['mod'])
@commands.has_permissions(administrator=True)
async def مشرف(ctx, member: discord.Member):
    """!مشرف @عضو - تعطي عضو صلاحيات مشرف"""
    mod_role = discord.utils.get(ctx.guild.roles, name="مشرف")
    if not mod_role:
        perms = discord.Permissions()
        perms.manage_channels = True
        perms.manage_messages = True
        perms.mute_members = True
        perms.move_members = True
        perms.manage_nicknames = True
        mod_role = await ctx.guild.create_role(name="مشرف", permissions=perms, color=0xFFA500)
        await mod_role.edit(position=ctx.guild.me.top_role.position - 1)

    try:
        await member.add_roles(mod_role)
        await ctx.send(f"✅ تم إعطاء {member.mention} صلاحيات **مشرف**! 🛡️")
    except:
        await ctx.send("❌ ما قدرت أعطي الرتبة!")

@bot.command(name="صلاحياتي", aliases=['myperms'])
async def صلاحياتي(ctx):
    """!صلاحياتي - عرض صلاحياتك"""
    perms = ctx.author.guild_permissions
    list_perms = []
    if perms.administrator: list_perms.append("🔐 مسوول")
    if perms.kick_members: list_perms.append("👢 كك")
    if perms.ban_members: list_perms.append("🚫 بان")
    if perms.manage_channels: list_perms.append("📁 إدارة الرومات")
    if perms.manage_messages: list_perms.append("💬 إدارة الرسائل")
    if perms.manage_roles: list_perms.append("🎭 إدارة الرتب")
    if perms.mute_members: list_perms.append("🔇 ميووت")
    if perms.move_members: list_perms.append("🔊 نقل成员")
    if perms.manage_nicknames: list_perms.append("📝 تغيير الأسماء")
    if perms.view_audit_log: list_perms.append("📋 سجل الت監査")

    if list_perms:
        embed = discord.Embed(title="صلاحياتك", description="\n".join(list_perms), color=0x2ECC71)
    else:
        embed = discord.Embed(title="صلاحياتك", description="❌ لا توجد صلاحيات خاصة", color=0xE74C3C)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="userinfo", aliases=['memberinfo', 'معلومات'], description="معلومات عن عضو")
async def userinfo(ctx, member: discord.Member = None):
    """!userinfo <@عضو> - معلومات العضو"""
    if member is None:
        member = ctx.author

    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    embed = discord.Embed(title=f"معلومات {member}", color=member.color, timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id)
    embed.add_field(name="📛 الاسم", value=member.display_name)
    embed.add_field(name="📅 انضم للسيرفر", value=member.joined_at.strftime("%Y-%m-%d"))
    embed.add_field(name="📅 انضم لدسكورد", value=member.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="👑 أعلى رتبة", value=member.top_role.mention)
    embed.add_field(name="🎭 الرتب", value=", ".join(roles) if roles else "لا يوجد", inline=False)
    embed.add_field(name="🤖 بوت؟", value="نعم" if member.bot else "لا")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="serverinfo", aliases=['guildinfo', 'سيرفر'], description="معلومات السيرفر")
async def serverinfo(ctx):
    """!serverinfo - معلومات السيرفر"""
    guild = ctx.guild
    embed = discord.Embed(title=f"معلومات {guild.name}", color=0x3498DB, timestamp=datetime.now(timezone.utc))
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="📋 الاسم", value=guild.name)
    embed.add_field(name="🆔 ID", value=guild.id)
    embed.add_field(name="👑 المالك", value=guild.owner.mention)
    embed.add_field(name="👥 الأعضاء", value=guild.member_count)
    embed.add_field(name="💬 الرومات النصية", value=len(guild.text_channels))
    embed.add_field(name="🔊 الرومات الصوتية", value=len(guild.voice_channels))
    embed.add_field(name="🎭 الرتب", value=len(guild.roles))
    embed.add_field(name="📅 تاريخ الإنشاء", value=guild.created_at.strftime("%Y-%m-%d"))
    await ctx.send(embed=embed)

@bot.hybrid_command(name="avatar", aliases=["صورة"], description="عرض صورة عضو")
async def avatar(ctx, member: discord.Member = None):
    """!avatar <@عضو> - عرض صورة العضو"""
    if member is None:
        member = ctx.author
    embed = discord.Embed(title=f"صورة {member.display_name}", color=member.color)
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="lock", aliases=['قفل'], description="قفل القناة (منع الكتابة للكل)")
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"🔒 تم قفل {channel.mention}")

@bot.hybrid_command(name="unlock", aliases=['فتح'], description="فتح القناة (السماح بالكتابة للكل)")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"🔓 تم فتح {channel.mention}")

@bot.hybrid_command(name="slowmode", aliases=['بطيء'], description="ضبط الوضع البطيء للقناة")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    if seconds < 0 or seconds > 21600:
        await ctx.send("❌ المدة بين 0 و 21600 ثانية (6 ساعات).")
        return
    await channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await ctx.send(f"✅ تم إلغاء الوضع البطيء لـ {channel.mention}")
    else:
        await ctx.send(f"✅ تم ضبط الوضع البطيء لـ {channel.mention} إلى {seconds} ثانية")

@bot.hybrid_command(name="8ball", aliases=['كرة'], description="الكرة السحرية تجيب على أسئلتك")
async def eightball(ctx, *, question: str):
    responses = [
        "نعم ✅", "لا ❌", "بالتأكيد 👍", "مستحيل 🚫", "ربما 🤔",
        "اسأل مرة ثانية 🔄", "الأكيد نعم 💯", "الأكيد لا 👎",
        "قدراً 🎯", "الله أعلم 🤷", "لا تتوقع ❓", "يمكن 🎲",
        "أجل 👍", "أبداً ❌", "أنت تعرف الجواب 🧠",
    ]
    embed = discord.Embed(title="🎱 الكرة السحرية", color=0x9B59B6)
    embed.add_field(name="السؤال", value=question, inline=False)
    embed.add_field(name="الجواب", value=random.choice(responses), inline=False)
    embed.set_footer(text=f"بواسطة {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="ping", description="قياس سرعة اتصال البوت")
async def ping(ctx):
    """!ping - سرعة البوت"""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(title="🏓 بونغ!", color=0x2ECC71)
    embed.add_field(name="سرعة الاستجابة", value=f"{latency}ms")
    await ctx.send(embed=embed)

@bot.command(name="cmds", aliases=['أوامر', 'اوامر', 'commands', 'orders'], description="عرض جميع أوامر البوت")
async def اوامر_cmd(ctx):
    """!أوامر - عرض جميع الأوامر"""
    try:
        with open("commands_data.json", "r", encoding="utf-8") as f:
            all_cmds = json.load(f)
    except:
        return await ctx.send("❌ فشل تحميل الأوامر")
    
    seen = set()
    cats = {}
    for c in all_cmds:
        name = c.get("name", "")
        cat = c.get("category", "غير محدد")
        if name in seen:
            continue
        seen.add(name)
        if cat not in cats:
            cats[cat] = []
        cats[cat].append(f"`!{name}`")
    
    cat_icons = {
        "ادارة": "⚙️", "ادوات": "🔧", "العاب": "🎮", "معلومات": "ℹ️",
        "موسيقى": "🎵", "اقتصاد": "💰", "مستويات": "📊", "صوت": "🔊",
        "التقنية": "💻", "غير محدد": "📋"
    }
    
    class CmdsView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.page = 0
            self.cat_list = list(cats.keys())
        
        def get_page_embed(self):
            cat = self.cat_list[self.page]
            cmds = cats[cat]
            icon = cat_icons.get(cat, "📋")
            
            lines = []
            for i in range(0, len(cmds), 10):
                chunk = cmds[i:i+10]
                lines.append(" ".join(chunk))
            
            embed = discord.Embed(
                title=f"{icon} {cat} ({len(cmds)} أمر)",
                description="\n".join(lines),
                color=0x9B59B6
            )
            embed.set_footer(text=f"صفحة {self.page+1}/{len(self.cat_list)} | إجمالي: {len(seen)} أمر")
            return embed
        
        @discord.ui.button(label="◀️ السابق", style=discord.ButtonStyle.secondary)
        async def prev(self, interaction, button):
            self.page = (self.page - 1) % len(self.cat_list)
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)
        
        @discord.ui.button(label="▶️ التالي", style=discord.ButtonStyle.secondary)
        async def next(self, interaction, button):
            self.page = (self.page + 1) % len(self.cat_list)
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)
        
        @discord.ui.button(label="🏠 القائمة", style=discord.ButtonStyle.primary)
        async def home(self, interaction, button):
            embed = discord.Embed(
                title="📋 جميع أوامر البوت",
                color=0x9B59B6
            )
            total = 0
            for cat in self.cat_list:
                icon = cat_icons.get(cat, "📋")
                count = len(cats[cat])
                total += count
                embed.add_field(name=f"{icon} {cat}", value=f"{count} أمر", inline=True)
            embed.set_footer(text=f"إجمالي: {total} أمر | اضغط على السهم للتصفح")
            await interaction.response.edit_message(embed=embed, view=self)
        
        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
    
    view = CmdsView()
    
    embed = discord.Embed(
        title="📋 جميع أوامر البوت",
        color=0x9B59B6
    )
    total = 0
    for cat in cats:
        icon = cat_icons.get(cat, "📋")
        count = len(cats[cat])
        total += count
        embed.add_field(name=f"{icon} {cat}", value=f"{count} أمر", inline=True)
    embed.set_footer(text=f"إجمالي: {total} أمر | اضغط على السهم للتصفح")
    
    await ctx.send(embed=embed, view=view)

# ════════════════════════════════════════
# أوامر غريبة وحصرية 🔥
# ════════════════════════════════════════

نسب = ["0% 😱", "10% 💀", "25% 😐", "33% 🤔", "50% 😐", "69% 🔥", "75% 💪", "90% 😍", "99% ❤️", "100% 🎯"]
اسباب = ["لأنك ملك 👑", "لا أحد يعرف 🤷", "قدر مكتوب 📖", "الكون يريد كذا 🌌", "عشان كذا خلقت 🌟", "انت تستاهل 🏆", "السبب؟ انت 😳"]
حركات = ["ضرب بفخدة 🦵", "كف على القفا ✋", "ركل بعيد 🦶", "خنق بالحضن 🫂", "ضرب بمصحف 📖", "صفعة قوية 💥", "قرصة 🦀", "ضرب بشبشب 👡", "عدسة في عينه 👁️"]
قبلات = ["بوسة على الخد 😘", "بوسة على الجبين 💋", "بوسة على اليد 🤲", "بوسة حارة 🔥", "بوسة خفيفة 🤏", "بوسة بالهوى 💕", "بوسة مع عناق 🫂"]
هكر_مراحل = [
    "🖥️ جاري الاتصال بالسيرفر...",
    "📡 تم تحديد IP: 192.168.{random.randint(1,255)}.{random.randint(1,255)}",
    "🔓 جاري اختراق الفايروول...",
    "⚠️ تجاوز الحماية بنجاح!",
    "📂 جاري تحميل البيانات... ██████░░░░ 60%",
    "🔐 تم فك تشفير الحساب!",
    "📥 جاري سحب المعلومات الشخصية...",
    "✅ تم الاختراق بنجاح! تم نقل البيانات إلى خادم آمن."
]
مشروبات = ["☕ قهوة سادة", "🧋 شاي حليب", "🥤 بيبسي", "🧃 عصير برتقال", "🍵 شاي أخضر", "🥛 حليب", "⚡ ريد بول", "🍹 موهيتو", "🧉 كرك", "🍺 بيرقر"]
اطباق = ["🍕 بيتزا", "🍔 برغر", "🌮 تاكو", "🥗 سلطة", "🍝 معكرونة", "🍣 سوشي", "🥘 كبسة", "🍛 منسف", "🧆 فلافل", "🍲 شوربة"]
الوان = ["أحمر 🔴", "أزرق 🔵", "أخضر 🟢", "أسود ⚫", "أبيض ⚪", "أصفر 🟡", "بنفسجي 🟣", "برتقالي 🟠"]

@bot.hybrid_command(name="sara7a", aliases=["صراحه"], description="سؤال صراحة عشوائي")
async def صراحه(ctx):
    """!صراحه - سؤال صراحة"""
    اسئلة = [
        "هل تحب شخص ما في هذا السيرفر؟ 🤔",
        "ما هو أحرج موقف صار معك؟ 😳",
        "هل سبق وكذبت على شخص تحبه؟ 🤥",
        "شنو الشي اللي تندم عليه؟ 😔",
        "هل قابلت أحد من السيرفر في الواقع؟ 👀",
        "ما هو سرك اللي محد يعرفه؟ 🤐",
        "شنو رأيك الحقيقي في المشرفين؟ 🤫",
        "هل تفكر في ترك السيرفر؟ 🚶",
        "من هو أقرب شخص لك هنا؟ 👥",
        "هل شاتيت مع أحد في الخاص؟ 💬",
        "شنو الشي اللي تتمناه؟ 🌟",
        "هل سبق وزعلت من أحد هنا؟ 😠",
        "شنو أفضل شي في السيرفر؟ ❤️",
    ]
    await ctx.send(f"❓ **سؤال الصراحة:** {random.choice(اسئلة)}")

@bot.hybrid_command(name="nesba", aliases=["نسبة"], description="نسبة حب/صداقة/كراهية بينك وبين عضو")
async def نسبة(ctx, member: discord.Member = None):
    """!نسبة @عضو - نسبة بينك وبين العضو"""
    if not member:
        member = ctx.author
    user = ctx.author
    p = random.choice(نسب)
    نوع = random.choice(["حب ❤️", "صداقة 🤝", "كراهية 💀", "أخوة 👥", "تفاهم 🧠", "جاذبية 🔥"])
    if member.id == user.id:
        await ctx.send(f"🥰 نسبة حبك لنفسك: **100% 🎯**")
    else:
        await ctx.send(f"📊 **نسبة {نوع}** بين {user.mention} و {member.mention}\n➡️ **{p}**")

@bot.hybrid_command(name="haz", aliases=["حظ"], description="اختبار حظك اليوم")
async def حظ(ctx):
    """!حظ - حظك اليوم"""
    الاحتمالات = [
        ("🍀 حظك اليوم رائع!", 0x2ECC71),
        ("😐 حظك متوسط، جرب مرة ثانية.", 0xF1C40F),
        ("💀 حظك سيء اليوم.. اقعد بالبيت.", 0xE74C3C),
        ("🔥 أنت محظوظ! اليوم يومك!", 0xE67E22),
        ("🤔 لا تدري وش ينتظرك، بس توكل على الله.", 0x3498DB),
    ]
    نص, لون = random.choice(الاحتمالات)
    embed = discord.Embed(title="🎲 اختبار الحظ", description=نص, color=لون)
    embed.set_footer(text=f"طلب من {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="hack", aliases=["اختراق"], description="اختراق وهمي لعضو")
async def اختراق(ctx, member: discord.Member = None):
    """!اختراق @عضو - Hack وهمي"""
    if not member:
        member = ctx.author
    msg = await ctx.send(f"🖥️ **جاري اختراق {member.display_name}...**")
    for مرحلة in هكر_مراحل:
        await asyncio.sleep(1.2)
        await msg.edit(content=f"```{مرحلة}```")
    await msg.edit(content=f"✅ **تم اختراق {member.mention} بنجاح!** جميع البيانات مسربة. 🏴‍☠️")

@bot.hybrid_command(name="marry", aliases=["زواج"], description="تقدم لزواج عضو")
async def زواج(ctx, member: discord.Member = None):
    """!زواج @عضو - تقدم للزواج"""
    if not member:
        await ctx.send("❌ من تبي تتزوج؟ !زواج @عضو")
        return
    if member.id == ctx.author.id:
        await ctx.send("🤨 تتزوج نفسك؟ انت قوي.")
        return
    if member.bot:
        await ctx.send("🤖 ما تقدر تتزوج بوت، حرام.")
        return
    موافقة = random.choice(["قبلت 🎉❤️", "رفضت 💔😭", "قلبي مشغول 💔", "بدها تفكر 🤔", "أهلي ما يوافقون 👨‍👩‍👧"])
    embed = discord.Embed(title="💍 طلب زواج!", color=0xFF69B4)
    embed.description = f"{ctx.author.mention} تقدم للزواج من {member.mention}!\n**النتيجة:** {موافقة}"
    await ctx.send(embed=embed)

@bot.hybrid_command(name="hit", aliases=["ضرب"], description="اضرب عضو بشيء عشوائي")
async def ضرب(ctx, member: discord.Member = None):
    """!ضرب @عضو - ضرب عضو"""
    if not member or member.id == ctx.author.id:
        await ctx.send("😤 **يضرب نفسه!** 💀")
        return
    action = random.choice(حركات)
    await ctx.send(f"🤜 {ctx.author.mention} **{action}** {member.mention} 💥")

@bot.hybrid_command(name="kiss", aliases=["بوس"], description="بوس عضو")
async def بوس(ctx, member: discord.Member = None):
    """!بوس @عضو - بوس عضو"""
    if not member or member.id == ctx.author.id:
        await ctx.send("😙 **يبوس نفسه**... شي غريب.")
        return
    قبلة = random.choice(قبلات)
    await ctx.send(f"💕 {ctx.author.mention} يعطي {member.mention} **{قبلة}**")

@bot.hybrid_command(name="reveal", aliases=["كشف"], description="يكشف شي عنك")
async def كشف(ctx):
    """!كشف - يكشف شي عنك"""
    اسرار = [
        f"{ctx.author.display_name} عنده سر ما يقدر يقوله 🤫",
        f"{ctx.author.display_name} يحب شخص في السيرفر 😳",
        f"{ctx.author.display_name} يقرا الشات بدون ما يرد 🧐",
        f"{ctx.author.display_name} كان بوت من الأساس 🤖",
        f"{ctx.author.display_name} عنده 3 شخصيات مختلفة 👥",
        f"{ctx.author.display_name} يكتب رسايل ويمسحها قبل ما تنرسل ✍️",
        f"{ctx.author.display_name} يفتح السيرفر كل يوم أول ما يصحي ☀️",
        f"{ctx.author.display_name} عنده كرش من كثر الأكل 🍔",
    ]
    await ctx.send(f"🔍 **كشف الأسرار:** {random.choice(اسرار)}")

@bot.hybrid_command(name="fortune", aliases=['توقعات', 'فورتشن'], description="توقعات المستقبل")
async def توقعات(ctx):
    """!توقعات - بطاقة توقع"""
    توقع = [
        "غدا سيكون يوم مشرق 🌅",
        "شخص قريب منك يفكر فيك 💭",
        "خبر سعيد في الطريق إليك 📨",
        "انتبه من قرار مفاجئ ⚠️",
        "ستقابل شخص يغير حياتك 🔄",
        "ثروة غير متوقعة تنتظرك 💰",
        "رحله جميلة قريبة 🧳",
        "ستحصل على ترقية قريباً 📈",
        "شخص من الماضي سيعود 🕰️",
        "لا تثق بكل من حولك 👀",
        "اليوم مناسب لبداية جديدة 🆕",
        "ابتسامتك ستفتح لك أبواباً 😊",
    ]
    embed = discord.Embed(title="🔮 توقعات المستقبل", color=0x9B59B6)
    embed.description = f"✨ {random.choice(توقع)}"
    embed.set_footer(text=f"لـ {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="analyze", aliases=["تحليل"], description="تحليل نفسي وهمي لعضو")
async def تحليل(ctx, member: discord.Member = None):
    """!تحليل @عضو - تحليل نفسي وهمي"""
    if not member:
        member = ctx.author
    تحليلات = [
        "شخص غامض 🕵️",
        "طيب ومخلص ❤️",
        "عصبي شوي 🔥",
        "اجتماعي مرح 🎉",
        "جدي ومتفاني 💼",
        "محبوب من الكل 🌟",
        "مبدع وفنان 🎨",
        "قائد بالفطرة 👑",
        "غبي 😂💀",
        "ذكي جداً 🧠",
        "حساس ومزاجي 🎭",
        "كريم ولبيه 🤲",
    ]
    embed = discord.Embed(title=f"🧠 التحليل النفسي لـ {member.display_name}", color=member.color)
    embed.description = f"**النتيجة:** {random.choice(تحليلات)}"
    embed.add_field(name="درجة الذكاء", value=f"{random.randint(30, 180)} IQ", inline=True)
    embed.add_field(name="الشخصية", value=random.choice(["انطوائي", "اجتماعي", "وسط"]), inline=True)
    embed.add_field(name="الطاقة", value=random.choice(["🟢 عالية", "🟡 متوسطة", "🔴 منخفضة"]), inline=True)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="rand-suggest", aliases=["اقتراح"], description="اقتراح عشوائي")
async def اقتراح(ctx):
    """!اقتراح - اقتراح عشوائي"""
    اقتراحات = [
        "روح نام 😴",
        "اكل شي 🍕",
        "اشرب موية 💧",
        "اطلع تمشى 🚶",
        "سولف مع صديق 🗣️",
        "اقرا كتاب 📖",
        "شوف فيلم 🎬",
        "لعب لعبة 🎮",
        "اسمع اغنية 🎵",
        "صلي وادعي 🕌",
    ]
    await ctx.send(f"💡 **اقتراح:** {random.choice(اقتراحات)}")

@bot.hybrid_command(name="wisdom", aliases=["حكمة"], description="حكمة عشوائية")
async def حكمة(ctx):
    """!حكمة - حكمة اليوم"""
    حكم = [
        "الصبر مفتاح الفرج 🗝️",
        "لا تؤجل عمل اليوم إلى الغد ⏰",
        "العقل السليم في الجسم السليم 🧠",
        "من جد وجد ومن زرع حصد 🌱",
        "المعرفة قوة 💪",
        "الحياة قصيرة، ابتسم 😊",
        "كلما زاد علمك زاد تواضعك 📚",
        "الصديق وقت الضيق 🤝",
        "ليس الفتى من قال كان أبي، لكن الفتى من قال ها أنا ذا 💪",
    ]
    embed = discord.Embed(title="📜 حكمة اليوم", description=random.choice(حكم), color=0xF1C40F)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="joke", aliases=["نكتة"], description="نكتة عشوائية")
async def نكتة(ctx):
    """!نكتة - نكتة عشوائية"""
    نكت = [
        "مرة واحد دخل على دكتور نفسي.. قاله أنا متخيل نفسي كلب.. قاله من متى؟ قاله من كنت جرو 🐶",
        "مرة واحد سأل صاحبه: كيف حالك؟ قاله: أنا XY قاله: طيب جيب معاك PEPSE 😂",
        "واحد كسول قال لصاحبه: أنا تعبان.. قاله من شغل؟ قاله لا من راحه 😴",
        "مرة وحدة قالت لجوزها: أنا بحبك أوي.. قالها: طب نامي بدري الصبح عشان تشربي لبن 🥛😂",
        "واحد بلدياتي دخل مطعم.. قاله عايز أكل حلو.. قاله مفيش.. قاله طيب عايز أكل مالح 🧂😂",
        "مرة تاجر خسر فلوسه كلها.. قال لصاحبه: أنا مفلس.. قاله: طيب اطبع فلوس جديدة 💵😂",
    ]
    await ctx.send(f"😂 **نكتة:** {random.choice(نكت)}")

@bot.hybrid_command(name="drink", aliases=["مشروب"], description="مشروب عشوائي")
async def مشروب(ctx, member: discord.Member = None):
    """!مشروب @عضو - مشروب عشوائي لشخص"""
    if not member:
        member = ctx.author
    await ctx.send(f"{member.mention} طلبنا لك: **{random.choice(مشروبات)}** 🥤")

@bot.hybrid_command(name="food", aliases=["اكل"], description="اكله عشوائية")
async def اكل(ctx, member: discord.Member = None):
    """!اكل @عضو - اكله عشوائية"""
    if not member:
        member = ctx.author
    await ctx.send(f"{member.mention} جيب فلوسك.. نأكل: **{random.choice(اطباق)}** 🍽️")

@bot.hybrid_command(name="color", aliases=["لون"], description="لونك العشوائي")
async def لون(ctx, member: discord.Member = None):
    """!لون @عضو - لونك المفضل حسب البوت"""
    if not member:
        member = ctx.author
    await ctx.send(f"🎨 {member.mention} لونك المفضل هو: **{random.choice(الوان)}**")

@bot.hybrid_command(name="question", aliases=["سؤال"], description="سؤال عشوائي")
async def سؤال(ctx):
    """!سؤال - سؤال عشوائي"""
    اسئلة = [
        "لو صار فيك فلوس كثييرة أول شي بتسويه؟ 💰",
        "لو تقدر تسافر أي دولة بالعالم وين تروح؟ ✈️",
        "أكلة لو تكلها كل يوم؟ 🍕",
        "لو عندك قدرة خارقة وش تكون؟ 🦸",
        "حيوانك المفضل؟ 🐱",
        "أفضل مسلسل شفته بحياتك؟ 📺",
        "شخص تتمنى تقابله؟ 🌟",
        "شي تخاف منه؟ 😨",
    ]
    await ctx.send(f"❓ **سؤال:** {random.choice(اسئلة)}")

@bot.hybrid_command(name="blot", aliases=["بلوت"], description="تسجيل بلوت على عضو")
@commands.has_permissions(administrator=True)
async def بلوت(ctx, member: discord.Member, *, السبب="بلا سبب"):
    """!بلوت @عضو <سبب> - بلوت على عضو (مزحة إدارية)"""
    await ctx.send(f"🚨 **بلوت!** {member.mention} خذ بلوت بسبب: **{السبب}**\n📝 عدد البلوتات: {random.randint(1, 99)}")

@bot.hybrid_command(name="my-number", aliases=["رقمي"], description="بطاقة رقمية عشوائية")
async def رقمي(ctx):
    """!رقمي - رقم حظك"""
    رقم = random.randint(1, 999)
    embed = discord.Embed(title="🔢 رقم حظك", description=f"**{رقم}**", color=0x2ECC71)
    embed.set_footer(text=f"لـ {ctx.author.display_name}")
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# أوامر الألعاب التفاعلية 🎮
# ════════════════════════════════════════

class تخمينView(View):
    def __init__(self, number, attempts):
        super().__init__(timeout=30)
        self.number = number
        self.attempts = attempts
        self.finished = False
        for i in range(1, 11):
            btn = discord.ui.Button(label=str(i), style=discord.ButtonStyle.secondary, custom_id=f"guess_{i}")
            btn.callback = self.make_callback(i)
            self.add_item(btn)

    def make_callback(self, guess):
        async def callback(interaction: discord.Interaction):
            if self.finished:
                await interaction.response.edit_message(content="❌ اللعبة انتهت.", view=None)
                return
            self.attempts -= 1
            if guess == self.number:
                self.finished = True
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(content=f"🎉 **صح!** الرقم كان **{self.number}** 🎉", view=self)
            elif self.attempts <= 0:
                self.finished = True
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(content=f"💀 **انتهت المحاولات.** الرقم كان **{self.number}**", view=self)
            elif guess < self.number:
                await interaction.response.edit_message(content=f"🔺 الرقم أكبر من **{guess}** | المحاولات المتبقية: {self.attempts}", view=self)
            else:
                await interaction.response.edit_message(content=f"🔻 الرقم أصغر من **{guess}** | المحاولات المتبقية: {self.attempts}", view=self)
        return callback

class روليتView(View):
    def __init__(self):
        super().__init__(timeout=30)
        self.bullet = random.randint(1, 6)
        self.shot = 0
        self.done = False

    @discord.ui.button(label="🔫 إطلاق", style=discord.ButtonStyle.danger, custom_id="shoot")
    async def shoot(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if self.done:
            await interaction.response.edit_message(content="❌ اللعبة انتهت.", view=None)
            return
        self.shot += 1
        if self.shot == self.bullet:
            self.done = True
            btn.disabled = True
            btn.label = "💀 مت"
            embed = discord.Embed(title="🔫 الروليت الروسية", description=f"💀 **بانج!** {interaction.user.mention} مات 😵", color=0xE74C3C)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            if self.shot >= 6:
                self.done = True
                btn.disabled = True
                btn.label = "✅ نجوت"
                embed = discord.Embed(title="🔫 الروليت الروسية", description=f"🍀 **نجوت!** {interaction.user.mention} عاش 😎", color=0x2ECC71)
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                embed = discord.Embed(title="🔫 الروليت الروسية", description=f"😰 **فرقعة فاضية!**\nمحاولة {self.shot}/{self.bullet if self.bullet > self.shot else '?'}", color=0xF1C40F)
                await interaction.response.edit_message(embed=embed, view=self)

class اكساوView(View):
    def __init__(self, player1, player2):
        super().__init__(timeout=60)
        self.board = [""] * 9
        self.player1 = player1
        self.player2 = player2
        self.current = player1
        self.symbol = {player1.id: "❌", player2.id: "⭕"}
        self.winner = None
        for i in range(9):
            btn = discord.ui.Button(label="⬜", style=discord.ButtonStyle.secondary, custom_id=f"xo_{i}", row=i//3)
            btn.callback = self.make_callback(i)
            self.add_item(btn)

    def check_win(self):
        lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a,b,c in lines:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        if all(self.board):
            return "تعادل"
        return None

    def make_callback(self, pos):
        async def callback(interaction: discord.Interaction):
            if self.winner:
                await interaction.response.send_message("❌ اللعبة انتهت!", ephemeral=True)
                return
            if interaction.user.id != self.current.id:
                await interaction.response.send_message("❌ دورك مو الحين!", ephemeral=True)
                return
            if self.board[pos]:
                await interaction.response.send_message("❌ هذي الخانة مشغولة!", ephemeral=True)
                return

            symbol = self.symbol[interaction.user.id]
            self.board[pos] = symbol
            label = symbol
            for child in self.children:
                if child.custom_id == f"xo_{pos}":
                    child.label = label
                    child.disabled = True
                    child.style = discord.ButtonStyle.primary if symbol == "❌" else discord.ButtonStyle.success

            result = self.check_win()
            if result == "تعادل":
                self.winner = "تعادل"
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(content="🤝 **تعادل!**", view=self)
            elif result:
                self.winner = result
                for child in self.children:
                    child.disabled = True
                w = self.player1 if self.symbol[self.player1.id] == result else self.player2
                await interaction.response.edit_message(content=f"🎉 **{w.mention} فاز!** ({result})", view=self)
            else:
                self.current = self.player2 if self.current == self.player1 else self.player1
                await interaction.response.edit_message(content=f"🎮 دور: {self.current.mention} ({self.symbol[self.current.id]})", view=self)
        return callback

@bot.group(name="لعبة", aliases=['game', 'games'], invoke_without_command=True)
async def لعبة(ctx):
    """!لعبة <اسم اللعبة> - قائمة الألعاب"""
    embed = discord.Embed(title="🎮 ألعاب البوت", color=0x9B59B6)
    embed.add_field(name="`!لعبة حجر <حجر/ورقة/مقص>`", value="🎲 حجر ورقة مقص ضد البوت", inline=False)
    embed.add_field(name="`!لعبة تخمين`", value="🔢 تخمين الرقم (1-10) - مع أزرار", inline=False)
    embed.add_field(name="`!لعبة روليت`", value="🔫 الروليت الروسية - مع أزرار", inline=False)
    embed.add_field(name="`!لعبة نرد`", value="🎲 زهر الحظ - نرد ضد البوت", inline=False)
    embed.add_field(name="`!لعبة عملة`", value="🪙 تقليب عملة - كتابة ولا وجه", inline=False)
    embed.add_field(name="`!لعبة اكس او @خصم`", value="❌⭕ اكس او (X O) - مع أزرار", inline=False)
    embed.add_field(name="`!لعبة تحدي_عاز`", value="🎙️ تسجيل صوتي تحدي مع أزرار", inline=False)
    await ctx.send(embed=embed)

@لعبة.command(name="حجر", aliases=["rps"])
async def حجر(ctx, choice: str = None):
    """!لعبة حجر <حجر/ورقة/مقص> - حجر ورقة مقص"""
    if not choice or choice not in ["حجر", "ورقة", "مقص"]:
        await ctx.send("❌ اختر: حجر، ورقة، أو مقص. مثال: `!لعبة حجر حجر`")
        return
    bot_choice = random.choice(["حجر", "ورقة", "مقص"])
    results = {
        ("حجر", "مقص"): ("فزت 🎉", 0x2ECC71),
        ("مقص", "ورقة"): ("فزت 🎉", 0x2ECC71),
        ("ورقة", "حجر"): ("فزت 🎉", 0x2ECC71),
        ("مقص", "حجر"): ("خسرت 💀", 0xE74C3C),
        ("ورقة", "مقص"): ("خسرت 💀", 0xE74C3C),
        ("حجر", "ورقة"): ("خسرت 💀", 0xE74C3C),
    }
    if choice == bot_choice:
        result, color = "تعادل 🤝", 0xF1C40F
    else:
        result, color = results.get((choice, bot_choice), ("خسرت 💀", 0xE74C3C))
    embed = discord.Embed(title="🎲 حجر ورقة مقص", color=color)
    embed.add_field(name="أنت", value=choice, inline=True)
    embed.add_field(name="🤖 البوت", value=bot_choice, inline=True)
    embed.add_field(name="النتيجة", value=result, inline=False)
    await ctx.send(embed=embed)

@لعبة.command(name="تخمين", aliases=["guess"])
async def تخمين(ctx):
    """!لعبة تخمين - تخمين الرقم (1-10)"""
    number = random.randint(1, 10)
    embed = discord.Embed(title="🔢 تخمين الرقم", description=f"خمن رقم من **1 إلى 10**\nعندك **3 محاولات**\n\nاختر رقم من الأزرار 👇", color=0x3498DB)
    await ctx.send(embed=embed, view=تخمينView(number, 3))

@لعبة.command(name="روليت", aliases=["roulette"])
async def روليت(ctx):
    """!لعبة روليت - الروليت俄罗斯ية"""
    embed = discord.Embed(title="🔫 الروليت俄罗斯ية", description=f"اضغط **🔫 إطلاق** عشان تجرب حظك!\nفيه رصاصة واحدة من 6.", color=0xE74C3C)
    await ctx.send(embed=embed, view=روليتView())

@لعبة.command(name="كازينو", aliases=["casino"])
async def كازينو(ctx, bet: int, choice: str):
    """!لعبة كازينو <مبلغ> <احمر/اسود/اخضر> - روليت كازينو"""
    if bet < 10:
        await ctx.send("❌ الحد الأدنى 10$")
        return
    choice = choice.lower()
    if choice not in ["احمر", "اسود", "اخضر", "red", "black", "green"]:
        await ctx.send("❌ اختر: احمر، اسود، أو اخضر")
        return

    g = ctx.guild.id
    bal = get_balance(g, ctx.author.id)
    if bet > bal["cash"]:
        await ctx.send(f"❌ ما عندك كاش كافي! رصيدك: ${bal['cash']:,}")
        return

    colors = {
        "احمر": "🔴", "red": "🔴",
        "اسود": "⚫", "black": "⚫",
        "اخضر": "🟢", "green": "🟢"
    }
    wheel = ["احمر"] * 18 + ["اسود"] * 18 + ["اخضر"] * 2
    result = random.choice(wheel)

    embed = discord.Embed(title="🎰 روليت الكازينو", description="دور الروليت... 🎰", color=0x9B59B6)
    msg = await ctx.send(embed=embed)

    for _ in range(8):
        await asyncio.sleep(0.3)
        temp = random.choice(["🔴", "⚫", "🟢"])
        embed.description = f"دور الروليت... {temp}"
        await msg.edit(embed=embed)

    if choice in ["احمر", "red"] and result == "احمر":
        win = bet * 2
        bal["cash"] += win - bet
        embed = discord.Embed(title="🎰 روليت الكازينو", description=f"🟢 النتيجة: {colors[result]} {result}\n🎉 **فزت!** كسبت **${win:,}**", color=0x2ECC71)
    elif choice in ["اسود", "black"] and result == "اسود":
        win = bet * 2
        bal["cash"] += win - bet
        embed = discord.Embed(title="🎰 روليت الكازينو", description=f"⚫ النتيجة: {colors[result]} {result}\n🎉 **فزت!** كسبت **${win:,}**", color=0x2ECC71)
    elif choice in ["اخضر", "green"] and result == "اخضر":
        win = bet * 14
        bal["cash"] += win - bet
        embed = discord.Embed(title="🎰 روليت الكازينو", description=f"🟢 النتيجة: {colors[result]} {result}\n🎉 **جاكبوت!** كسبت **${win:,}** 🔥🔥", color=0xFFD700)
    else:
        bal["cash"] -= bet
        embed = discord.Embed(title="🎰 روليت الكازينو", description=f"❌ النتيجة: {colors[result]} {result}\n💀 **خسرت!** خسرت **${bet:,}**", color=0xE74C3C)

    save_data()
    await msg.edit(embed=embed)

@لعبة.command(name="نرد", aliases=["dice"])
async def نرد(ctx):
    """!لعبة نرد - زهر الحظ ضد البوت"""
    user_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    if user_roll > bot_roll:
        result, color = "🎉 فزت!", 0x2ECC71
    elif user_roll < bot_roll:
        result, color = "💀 خسرت!", 0xE74C3C
    else:
        result, color = "🤝 تعادل!", 0xF1C40F
    embed = discord.Embed(title="🎲 نرد", color=color)
    embed.add_field(name="🎲 أنت", value=f"**{user_roll}**", inline=True)
    embed.add_field(name="🎲 البوت", value=f"**{bot_roll}**", inline=True)
    embed.add_field(name="النتيجة", value=result, inline=False)
    await ctx.send(embed=embed)

@لعبة.command(name="عملة", aliases=["coin"])
async def عملة(ctx):
    """!لعبة عملة - تقليب عملة"""
    result = random.choice(["كتابة 👑", "وجه 🪙"])
    embed = discord.Embed(title="🪙 تقليب عملة", description=f"النتيجة: **{result}**", color=0xF1C40F)
    await ctx.send(embed=embed)

@لعبة.command(name="اكس او", aliases=['xo', 'tictactoe'])
async def اكس_او(ctx, member: discord.Member = None):
    """!لعبة اكس او @خصم - العب اكس او مع صديق"""
    if not member or member.id == ctx.author.id:
        await ctx.send("❌ اختر خصم. مثال: `!لعبة اكس او @عضو`")
        return
    if member.bot:
        await ctx.send("❌ البوت ما يلعب اكس او معك.")
        return
    embed = discord.Embed(title="❌⭕ اكس او", color=0x9B59B6)
    embed.description = "اضغط على الخانة عشان تلعب\n🎮 **❌** يبدأ أولاً"
    await ctx.send(content=f"🎮 دور: {ctx.author.mention} (❌)", embed=embed, view=اكساوView(ctx.author, member))

@bot.command(name="تحدي_عاز", aliases=["roulette_challenge", "تحدي", "عاز"])
async def تحدي_عاز(ctx):
    """!تحدي عاز - تحدي مع أزرار"""
    embed = discord.Embed(
        title="🎯 تحدي عاز",
        description="**🎙️ تسجيل** - ابدأ التسجيل\n**⏹️ قف** - أوقف (المالك فقط)\n**👥 مشاركين** - عرض المشاركين (المالك فقط)",
        color=0x9B59B6
    )

    class تحديعازView(View):
        def __init__(self):
            super().__init__(timeout=300)
            self.recording = False
            self.participants = []
            self.voice_client = None
            self.voice_channel = None
            self.message = None

        @discord.ui.button(label="🎙️ تسجيل", style=discord.ButtonStyle.success, custom_id="start_record")
        async def start_record(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.voice is None:
                await interaction.response.send_message("❌ لازم تكون في روم صوتي!", ephemeral=True)
                return

            if self.recording and self.voice_channel != interaction.user.voice.channel:
                await interaction.response.send_message("❌ فيه تسجيل شغال في روم ثاني!", ephemeral=True)
                return

            if self.recording:
                if interaction.user not in self.participants:
                    self.participants.append(interaction.user)
                    await interaction.response.send_message(f"✅ تم إضافتك للمشاركين! 🎙️", ephemeral=True)
                else:
                    await interaction.response.send_message("✅ أنت بالفعل في قائمة المشاركين!", ephemeral=True)
                return

            self.voice_channel = interaction.user.voice.channel
            try:
                self.voice_client = await self.voice_channel.connect()
                self.recording = True
                self.participants = [interaction.user]
                embed = discord.Embed(
                    title="🎙️ تحدي عاز - التسجيل جارٍ",
                    description=f"✅ **التسجيل started في:** {self.voice_channel.name}\n\n👥 **المشاركين:** {interaction.user.mention}\n\nاضغط **🎙️ تسجيل** عشان تضيف نفسك\nاضغط **⏹️ قف** عشان توقف (المالك)",
                    color=0x2ECC71
                )
                await interaction.response.edit_message(embed=embed, view=self)
            except Exception as e:
                await interaction.response.send_message(f"❌ خطأ: {str(e)}", ephemeral=True)

        @discord.ui.button(label="⏹️ قف", style=discord.ButtonStyle.danger, custom_id="stop_record")
        async def stop_record(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ بس المالك يقدر يوقف!", ephemeral=True)
                return

            if not self.recording:
                await interaction.response.send_message("❌ ما في تسجيل شغال!", ephemeral=True)
                return

            self.recording = False
            if self.voice_client:
                await self.voice_client.disconnect()
                self.voice_client = None

            participants_list = " ".join([p.mention for p in self.participants]) if self.participants else "لا أحد"
            embed = discord.Embed(
                title="⏹️ تحدي عاز - تم الإيقاف",
                description=f"✅ **تم إيقاف التسجيل**\n\n👥 **المشاركين:** {participants_list}",
                color=0xE74C3C
            )
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="👥 مشاركين", style=discord.ButtonStyle.primary, custom_id="show_participants")
        async def show_participants(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ بس المالك يقدر يشوف!", ephemeral=True)
                return

            if not self.participants:
                await interaction.response.send_message("❌ لا أحد سجل!", ephemeral=True)
                return

            participants_str = " ".join([p.mention for p in self.participants])
            await interaction.response.send_message(f"👥 **المشاركين:** {participants_str}", ephemeral=True)

    await ctx.send(embed=embed, view=تحديعازView())

# ════════════════════════════════════════
# نظام الحماية الشامل 🛡️
# ════════════════════════════════════════

# ── دالة مساعدة لتبديل الحماية ──
async def _toggle_protection(ctx, key):
    g = ctx.guild.id
    p = protections.setdefault(g, {})
    p[key] = not p.get(key, True)
    save_data()
    name = PROTECTION_NAMES.get(key, key)
    state = "🟢 شغالة" if p[key] else "🔴 موقفة"
    await ctx.send(f"✅ {name}: {state}")

@bot.group(name="حماية", aliases=['protection', 'امان'], invoke_without_command=True)
async def حماية(ctx):
    """!حماية - نظام الحماية الشامل"""
    p = protections.get(ctx.guild.id, {})
    embed = discord.Embed(title="🛡️ نظام الحماية", color=0x2ECC71)
    for key, name in PROTECTION_NAMES.items():
        icon = "🟢" if p.get(key, True) else "🔴"
        embed.add_field(name=f"{icon} `!حماية {key}`", value=f"{name} - للتبديل", inline=False)
    embed.add_field(name="➕➖ `!حماية كلمات_اضافة/حذف`", value="🔇 إدارة الكلمات الممنوعة", inline=False)
    embed.add_field(name="📊 `!حماية حالة`", value="عرض حالة الحماية", inline=True)
    embed.add_field(name="✅ `!حماية الكل`", value="تشغيل/إيقاف الكل", inline=True)
    embed.add_field(name="💣 `!حماية مضاد_نوك`", value="تشغيل/إيقاف Anti-Nuke", inline=True)
    embed.add_field(name="🔓 `!حماية استثناء #قناة <نوع>`", value="استثناء قناة من حماية", inline=False)
    embed.set_footer(text="جميع الحمايات مفعلة افتراضياً")
    await ctx.send(embed=embed)

# أوامر التبديل (Backwards compatible)
@حماية.command(name="سبام", aliases=["spam"])
@commands.has_permissions(administrator=True)
async def حماية_سبام(ctx):
    await _toggle_protection(ctx, "spam")

@حماية.command(name="فلود", aliases=["flood"])
@commands.has_permissions(administrator=True)
async def حماية_فلود(ctx):
    await _toggle_protection(ctx, "flood")

@حماية.command(name="منشن", aliases=["mention"])
@commands.has_permissions(administrator=True)
async def حماية_منشن(ctx):
    await _toggle_protection(ctx, "mention")

@حماية.command(name="كلمات", aliases=["badwords"])
@commands.has_permissions(administrator=True)
async def حماية_كلمات(ctx):
    await _toggle_protection(ctx, "badwords")

@حماية.command(name="انفايت", aliases=["invite"])
@commands.has_permissions(administrator=True)
async def حماية_انفايت(ctx):
    await _toggle_protection(ctx, "invite")

@حماية.command(name="الت", aliases=["alt"])
@commands.has_permissions(administrator=True)
async def حماية_الت(ctx):
    await _toggle_protection(ctx, "alt")

@حماية.command(name="ريد", aliases=["raid"])
@commands.has_permissions(administrator=True)
async def حماية_ريد(ctx):
    await _toggle_protection(ctx, "raid")

@حماية.command(name="الكل", aliases=["all"])
@commands.has_permissions(administrator=True)
async def حمية_الكل(ctx):
    g = ctx.guild.id
    p = protections.setdefault(g, {})
    keys = ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]
    all_on = all(p.get(k, True) for k in keys)
    new_state = not all_on
    for k in keys:
        p[k] = new_state
    save_data()
    state = "🟢 الكل شغال" if new_state else "🔴 الكل موقف"
    await ctx.send(f"✅ {state}")

@حماية.command(name="حالة", aliases=["status"])
@commands.has_permissions(administrator=True)
async def حماية_حالة(ctx):
    g = ctx.guild.id
    p = protections.get(g, {})
    embed = discord.Embed(title="🛡️ حالة الحماية", color=0x2ECC71)
    for key, name in PROTECTION_NAMES.items():
        val = p.get(key, True)
        icon = "🟢" if val else "🔴"
        embed.add_field(name=f"{icon} {name}", value="شغال" if val else "موقف", inline=True)
    an_state = anti_nuke.is_enabled(g)
    embed.add_field(name=f"{'🟢' if an_state else '🔴'} 💣 مضاد نوك", value="شغال" if an_state else "موقف", inline=True)
    if raid_detector.is_raid(g):
        embed.add_field(name="🚨 حالة Raid", value="🔴 نشط!", inline=True)
    await ctx.send(embed=embed)

@حماية.command(name="كلمات_اضافة", aliases=["addword"])
@commands.has_permissions(administrator=True)
async def حماية_كلمات_اضافة(ctx, *, word: str):
    word = word.lower().strip()
    if word in bad_words_list:
        await ctx.send(f"❌ الكلمة **{word}** موجودة بالفعل.")
        return
    bad_words_list.append(word)
    save_data()
    await ctx.send(f"✅ تم إضافة **{word}** إلى قائمة الكلمات الممنوعة.")

@حماية.command(name="كلمات_حذف", aliases=["removeword"])
@commands.has_permissions(administrator=True)
async def حماية_كلمات_حذف(ctx, *, word: str):
    word = word.lower().strip()
    if word not in bad_words_list:
        await ctx.send(f"❌ الكلمة **{word}** غير موجودة.")
        return
    bad_words_list.remove(word)
    save_data()
    await ctx.send(f"✅ تم حذف **{word}** من قائمة الكلمات الممنوعة.")

@حماية.command(name="مضاد_نوك", aliases=["antinuke", "nuke"])
@commands.has_permissions(administrator=True)
async def حماية_مضاد_نوك(ctx):
    g = ctx.guild.id
    state = anti_nuke.set_enabled(g, not anti_nuke.is_enabled(g))
    await ctx.send(f"{'🟢' if state else '🔴'} Anti-Nuke: {'شغال' if state else 'موقف'}")

@حماية.command(name="استثناء", aliases=["whitelist"])
@commands.has_permissions(administrator=True)
async def حماية_استثناء(ctx, channel: discord.TextChannel, protection: str):
    protection = protection.lower().strip()
    if protection not in PROTECTION_NAMES and protection != "all":
        await ctx.send(f"❌ نوع الحماية غير صحيح. الأنواع: {', '.join(PROTECTION_NAMES.keys())}, all")
        return
    added = whitelist_manager.toggle(ctx.guild.id, channel.id, protection)
    await ctx.send(f"{'➕' if added else '➖'} تم {'إضافة' if added else 'إزالة'} {channel.mention} من استثناءات **{PROTECTION_NAMES.get(protection, 'الكل')}**")

@حماية.command(name="رفع_الرايد", aliases=["disableraid"])
@commands.has_permissions(administrator=True)
async def حماية_رفع_الرايد(ctx):
    if raid_detector.is_raid(ctx.guild.id):
        raid_detector.disable_raid(ctx.guild.id)
        await ctx.send("✅ تم إلغاء وضع Raid وعودة الخدمة طبيعية.")
    else:
        await ctx.send("ℹ️ لا يوجد Raid نشط حالياً.")

# ════════════════════════════════════════
# الأمر السري 🔥 (حصري لمالك البوت + المصرح لهم)
# ════════════════════════════════════════

async def is_secret_authorized(user):
    return user.id == YOUR_USER_ID or user.id in secret_users

@bot.group(name="سكرتي", aliases=['سر', 'secret'], invoke_without_command=True)
async def سكرتي(ctx):
    """🔥 أمر سري حصري لمالك البوت والمصرح لهم"""
    if not await is_secret_authorized(ctx.author):
        await ctx.send("❌ ما عندك صلاحية استخدام هذا الأمر!")
        return

    embed = discord.Embed(title="🔥 القيادة السرية", description=f"مرحباً {ctx.author.mention} 👑", color=0x000000)
    embed.add_field(name="📊 حالة البوت", value=f"السيرفرات: {len(bot.guilds)}\nالبنق: {round(bot.latency * 1000)}ms", inline=False)
    embed.add_field(name="🛡️ الحماية", value=f"السيرفرات المحمية: {len(protections)}", inline=True)
    embed.add_field(name="📋 الكلمات الممنوعة", value=f"{len(bad_words_list)} كلمة", inline=True)
    embed.add_field(name="🎫 التذاكر", value=f"آخر تذكرة: #{ticket_counter - 1}", inline=True)
    embed.add_field(name="🔗 مانع الروابط", value=f"مفعل في: {sum(1 for v in link_blocker_enabled.values() if v)} سيرفر", inline=True)
    embed.add_field(name="👥 المصرح لهم", value=f"{len(secret_users)} شخص", inline=True)
    embed.set_footer(text="🔥 MAX BOT | لوحة التحكم السرية")
    await ctx.send(embed=embed)

@سكرتي.command(name="اضافة", aliases=["add"])
async def سكرتي_اضافة(ctx, member: discord.Member):
    """إضافة شخص مصرح له بالأمر السري"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("❌ فقط مالك البوت يستطيع إضافة أشخاص!")
        return
    if member.id in secret_users:
        await ctx.send(f"✅ {member.mention} موجود بالفعل.")
        return
    secret_users.append(member.id)
    save_data()
    await ctx.send(f"✅ تم إضافة {member.mention} إلى قائمة المصرح لهم بالأمر السري 🔥")

@سكرتي.command(name="حذف", aliases=["remove"])
async def سكرتي_حذف(ctx, member: discord.Member):
    """حذف شخص من المصرح لهم"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("❌ فقط مالك البوت يستطيع حذف أشخاص!")
        return
    if member.id not in secret_users:
        await ctx.send(f"❌ {member.mention} غير موجود في القائمة.")
        return
    secret_users.remove(member.id)
    save_data()
    await ctx.send(f"✅ تم حذف {member.mention} من قائمة المصرح لهم.")

@سكرتي.command(name="قائمة", aliases=["list"])
async def سكرتي_قائمة(ctx):
    """عرض قائمة المصرح لهم"""
    if not await is_secret_authorized(ctx.author):
        await ctx.send("❌ ما عندك صلاحية!")
        return
    if not secret_users:
        await ctx.send("📋 لا يوجد أحد في القائمة غير مالك البوت.")
        return
    mentions = [f"<@{uid}>" for uid in secret_users]
    embed = discord.Embed(title="👥 المصرح لهم بالأمر السري", description="\n".join(mentions), color=0x000000)
    await ctx.send(embed=embed)

@سكرتي.error
async def سكرتي_error(ctx, error):
    if await is_secret_authorized(ctx.author):
        await ctx.send(f"❌ خطأ: {error}")

# ════════════════════════════════════════
# نظام سنايب 👻 (آخر رسالة محذوفة)
# ════════════════════════════════════════

snipe_data = {}

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    if message.id in logged_link_messages:
        logged_link_messages.discard(message.id)
        return
    guild_id = message.guild.id if message.guild else None
    if not guild_id:
        return

    cached = message_cache.get(guild_id, message.id)
    content = cached["content"] if cached else (message.content or "ملف/صورة")

    snipe_data[message.channel.id] = {
        "author": message.author,
        "content": content,
        "time": datetime.now(timezone.utc)
    }

    embed = LogEmbed.base("🗑️ حذف رسالة", LogColors.DELETE, guild=message.guild)
    LogEmbed.user_field(embed, message.author, "المرسل")
    LogEmbed.channel_field(embed, "القناة", message.channel)
    message_age = discord.utils.utcnow() - message.created_at
    m_days = message_age.days
    m_hours, m_rem = divmod(message_age.seconds, 3600)
    m_min, _ = divmod(m_rem, 60)
    if m_days > 0:
        age_str = f"{m_days} يوم، {m_hours} ساعة"
    elif m_hours > 0:
        age_str = f"{m_hours} ساعة، {m_min} دقيقة"
    else:
        age_str = f"{m_min} دقيقة"
    embed.add_field(name="⏱️ عمر الرسالة", value=age_str, inline=True)
    if message.edited_at:
        embed.add_field(name="📝 عُدت سابقاً", value="✅ نعم", inline=True)
    if message.pinned:
        embed.add_field(name="📌 مثبتة", value="✅ نعم", inline=True)
    who_deleted = None
    try:
        async for entry in message.guild.audit_logs(limit=5, action=discord.AuditLogAction.message_delete):
            if entry.target and entry.target.id == message.author.id:
                who_deleted = entry.user
                break
    except discord.Forbidden:
        pass
    if who_deleted and who_deleted.id != message.author.id:
        embed.add_field(name="🗑️ من حذفه", value=f"{who_deleted.mention} ⚙️", inline=True)
    if cached:
        LogEmbed.evidence_field(embed, message_data=cached)
    else:
        embed.add_field(name="المحتوى", value=content[:1000], inline=False)
    await send_log(guild_id, "log_messages", embed)

@bot.hybrid_command(name="snipe", aliases=['سنايب'])
async def سنايب(ctx):
    """👻 يعرض آخر رسالة محذوفة في القناة"""
    data = snipe_data.get(ctx.channel.id)
    if not data:
        await ctx.send("👻 ما فيه رسالة محذوفة هنا.")
        return
    embed = discord.Embed(title="👻 سنايب", description=data["content"], color=0x9B59B6, timestamp=data["time"])
    embed.set_author(name=data["author"].display_name, icon_url=data["author"].display_avatar.url)
    embed.set_footer(text=f"محذوف من {ctx.channel.name}")
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# نظام التصويت 📋
# ════════════════════════════════════════

@bot.hybrid_command(name="poll", aliases=['تصويت', 'vote'])
@commands.has_permissions(administrator=True)
async def تصويت(ctx, *, question: str):
    """!تصويت <سؤال> - إنشاء تصويت"""
    embed = discord.Embed(title="📋 تصويت", description=question, color=0x3498DB)
    embed.set_footer(text=f"بواسطة {ctx.author.display_name}")
    msg = await ctx.send(embed=embed)
    for emoji in ["✅", "❌", "🤷"]:
        await msg.add_reaction(emoji)

# ════════════════════════════════════════
# نظام الترحيب 👋
# ════════════════════════════════════════

welcome_config = {}

xp_data = {}
economy_data = {}
suggestion_config = {}
afk_users = {}
afk_voice_channels = {}
reaction_role_config = {}
level_rewards = {}
shop_items = {}

SHOP_DEFAULT = {
    "role_color": {"name": "🎨 لون الرتبة", "price": 5000, "type": "custom"},
    "nick": {"name": "✏️ تغيير اسمك", "price": 3000, "type": "custom"},
    "vip": {"name": "👑 رتبة VIP", "price": 10000, "type": "role", "role_id": None},
}

@bot.group(name="ترحيب", aliases=["welcome"], invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def ترحيب(ctx):
    """إعدادات الترحيب"""
    embed = discord.Embed(title="👋 نظام الترحيب", color=0x2ECC71)
    embed.add_field(name="`!ترحيب قناة #قناة`", value="تعيين قناة الترحيب", inline=False)
    embed.add_field(name="`!ترحيب رسالة <نص>`", value="تعيين رسالة الترحيب (استخدم {member} لاسم العضو)", inline=False)
    embed.add_field(name="`!ترحيب رتبة @رتبة`", value="تعيين رتبة تلقائية عند الدخول (أو `!رتب تلقاء @رتبة`)", inline=False)
    embed.add_field(name="`!ترحيب الغاء_رتبة`", value="إلغاء الرتبة التلقائية", inline=False)
    embed.add_field(name="`!ترحيب حالة`", value="عرض الإعدادات الحالية", inline=False)
    await ctx.send(embed=embed)

@ترحيب.command(name="قناة")
async def ترحيب_قناة(ctx, channel: discord.TextChannel):
    """تعيين قناة الترحيب"""
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    w["channel"] = channel.id
    save_data()
    await ctx.send(f"✅ تم تعيين قناة الترحيب: {channel.mention}")

@ترحيب.command(name="رسالة")
async def ترحيب_رسالة(ctx, *, message: str):
    """تعيين رسالة الترحيب"""
    if len(message) > 500:
        await ctx.send("❌ الرسالة طويلة جداً (حد أقصى 500 حرف).")
        return
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    w["message"] = message
    save_data()
    await ctx.send(f"✅ تم تعيين رسالة الترحيب:\n{message}")

@ترحيب.command(name="رتبة")
async def ترحيب_رتبة(ctx, role: discord.Role):
    """تعيين رتبة تلقائية عند الدخول"""
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    w["role"] = role.id
    save_data()
    await ctx.send(f"✅ تم تعيين رتبة الترحيب: {role.mention}")

@ترحيب.command(name="الغاء_رتبة")
async def ترحيب_الغاء_رتبة(ctx):
    """إلغاء الرتبة التلقائية"""
    g = ctx.guild.id
    w = welcome_config.setdefault(g, {})
    w.pop("role", None)
    save_data()
    await ctx.send("✅ تم إلغاء الرتبة التلقائية.")

@ترحيب.command(name="حالة")
async def ترحيب_حالة(ctx):
    """عرض إعدادات الترحيب"""
    g = ctx.guild.id
    w = welcome_config.get(g, {})
    ch = bot.get_channel(w.get("channel")) if w.get("channel") else None
    role = ctx.guild.get_role(w.get("role")) if w.get("role") else None
    embed = discord.Embed(title="👋 إعدادات الترحيب", color=0x2ECC71)
    embed.add_field(name="📢 القناة", value=ch.mention if ch else "❌ غير معينة", inline=False)
    embed.add_field(name="📝 الرسالة", value=w.get("message", "الرسالة الافتراضية"), inline=False)
    embed.add_field(name="🎭 الرتبة", value=role.mention if role else "❌ لا يوجد", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_member_join(member):
    guild_id = member.guild.id
    embed_join = LogEmbed.base("", LogColors.JOIN, guild=member.guild)
    embed_join.color = 0x00FFAA
    embed_join.set_author(name=f"👋 {member.display_name}     ({member.id})", icon_url=member.display_avatar.url)
    embed_join.description = f"> {member.mention} انضم إلينا 🎉"
    created = f"<t:{int(member.created_at.timestamp())}:R>"
    account_age = (discord.utils.utcnow() - member.created_at).days
    age_warn = " ⚠️ حساب جديد!" if account_age < 7 else " ✅"
    embed_join.add_field(name="📅 تاريخ إنشاء الحساب", value=created, inline=True)
    embed_join.add_field(name="🔢 ترتيب العضو", value=f"#{member.guild.member_count}", inline=True)
    embed_join.add_field(name="🤖 بوت؟", value="✅ نعم" if member.bot else "❌ لا", inline=True)
    embed_join.add_field(name="📅 عمر الحساب", value=f"{account_age} يوم{age_warn}", inline=True)
    if member.premium_since:
        embed_join.add_field(name="💎 Nitro Booster", value="✅ عضو مدعم", inline=True)
    embed_join.add_field(name="👥 عدد الأعضاء", value=f"{member.guild.member_count} عضو", inline=True)
    embed_join.set_thumbnail(url=member.display_avatar.url)
    await send_log(guild_id, "log_join", embed_join)

    w = welcome_config.get(guild_id, {})

    # Welcome message
    ch_id = w.get("channel")
    if ch_id:
        ch = bot.get_channel(int(ch_id))
        if ch:
            msg = w.get("message", "مرحباً {member}! 🎉")
            msg = msg.replace("{member}", member.mention)
            embed = discord.Embed(title="👋 عضو جديد!", description=msg, color=0x2ECC71)
            embed.set_thumbnail(url=member.display_avatar.url)
            image_url = w.get("image_url")
            if image_url:
                embed.set_image(url=image_url)
            view = WelcomeQuizView(member.id)
            await safe_send(ch, embed, view=view)

    # Auto role (from welcome config)
    role_id = w.get("role")
    if role_id:
        role = member.guild.get_role(int(role_id))
        if role:
            try:
                await member.add_roles(role, reason="رتبة ترحيب تلقائية")
            except:
                pass

    # Auto role (global from .env)
    if AUTO_ROLE_ID:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="رتبة تلقائية")
            except:
                pass

    # H.A.C.K.E.R role for returning bait users
    if member.id in hacker_bait_kicked:
        hacker_role = member.guild.get_role(HACKER_ROLE_ID)
        if hacker_role:
            try:
                await member.add_roles(hacker_role, reason="عضو صيد هاكرز سابق — عاد للسيرفر")
                print(f"[BAIT] Assigned H.A.C.K.E.R role to {member} (returning bait user)", flush=True)
            except Exception as e:
                print(f"[BAIT ROLE ERROR] {e}", flush=True)

    # Anti protection
    if is_exempt(member):
        return

    # ── حماية الحسابات الجديدة (Alt) ──
    if get_prot(guild_id, "alt"):
        account_age = (datetime.now(timezone.utc) - member.created_at).days
        if account_age < 7:
            try:
                await send_punishment_review(member.guild, member, "alt", 1, detail=f"عمر الحساب: {account_age} يوم")
            except:
                pass
            return

    # ── حماية الدخول الجماعي (Raid) ──
    if get_prot(guild_id, "raid"):
        status = raid_detector.check(guild_id)
        if status == "raid":
            try:
                await send_punishment_review(member.guild, member, "raid_join", 1, detail="🚫 دخول جماعي (Raid)")
            except:
                pass
            return
        elif status == "alert":
            embed = LogEmbed.base("🟡 إنذار دخول جماعي", LogColors.WARN, guild=member.guild)
            LogEmbed.user_field(embed, member, "العضو", thumb=True)
            embed.add_field(name="حالة", value="🟡 نشاط مشبوه - مراقبة", inline=False)
            await send_log(guild_id, "protection_security", embed)

    # ── حماية الحظر القائم على العتاد (Hardware-Based Ban) ──
    fp_key = f"{guild_id}_{member.id}"
    fp = fingerprints.get(fp_key, {})
    device_hash = fp.get("device_hash", "")
    if device_hash and device_hash in hardware_bans:
        try:
            embed_ban = discord.Embed(
                title="🔒 حظر عتاد أبدي — تم اكتشاف جهاز محظور!",
                description=(
                    f"├─ **العضو:** {member.mention} (`{member.id}`)\n"
                    f"├─ **البصمة:** `{device_hash[:16]}...`\n"
                    f"├─ **السبب:** جهاز محظور مسبقاً في نظام الحماية\n"
                    f"├─ **العمر:** {(discord.utils.utcnow() - member.created_at).days} يوم\n"
                    f"└─ **الإجراء:** طرد + حظر تلقائي"
                ),
                color=0xFF4444,
                timestamp=datetime.now(timezone.utc)
            )
            embed_ban.set_thumbnail(url=member.display_avatar.url)
            embed_ban.set_footer(text="═══════════════════════════\nMAX BOT • الحماية السيبرانية\n═══════════════════════════")
            log_ch = discord.utils.get(member.guild.text_channels, name="log-hacking🔎")
            if not log_ch:
                log_ch = member.guild.get_channel(1514740957948547233)
            if log_ch:
                await log_ch.send(embed=embed_ban)
        except Exception as e:
            print(f"[HARDWARE BAN LOG ERROR] {e}", flush=True)
        try:
            await member.kick(reason=f"Hardware-banned device: {device_hash[:16]}")
        except Exception as e:
            print(f"[HARDWARE BAN KICK ERROR] {e}", flush=True)
        return

def _voice_embed(title, member, channel=None, admin=None):
    embed = LogEmbed.base(title, LogColors.VOICE, guild=member.guild)
    LogEmbed.user_field(embed, member, "العضو")
    if channel:
        LogEmbed.channel_field(embed, "الروم", channel)
        if channel.category:
            embed.add_field(name="القسم", value=channel.category.name, inline=True)
        if isinstance(channel, discord.VoiceChannel):
            humans = sum(1 for m in channel.members if not m.bot)
            bots = sum(1 for m in channel.members if m.bot)
            embed.add_field(name="الأعضاء", value=f"{humans} 👤 + {bots} 🤖", inline=True)
            if channel.user_limit:
                embed.add_field(name="السعة", value=f"{len(channel.members)}/{channel.user_limit}", inline=True)
            if channel.bitrate:
                embed.add_field(name="الجودة", value=f"{channel.bitrate // 1000}kbps", inline=True)
    if admin and not isinstance(admin, str):
        LogEmbed.audit_field(embed, admin)
    return embed

# ════════════════════════════════════════
# نظام الرومات الصوتية المؤقتة 🎵
# ════════════════════════════════════════

@bot.event
async def on_voice_state_update(member, before, after):
    guild_id = member.guild.id
    before_id = before.channel.id if before.channel else None
    after_id = after.channel.id if after.channel else None

    # ── Mod Room Check ──
    if mod_room_channel_id and after.channel and after.channel.id == mod_room_channel_id:
        if not member.bot and member.guild_permissions.administrator:
            embed = discord.Embed(title="🛠️ لوحة الإدارة في الروم", description="اختر الإجراء من القائمة:", color=0x3498DB)
            await member.send(embed=embed, view=ModRoomView())

    # ── Server Mute / Deafen (مع المنفذ من Audit Log) ➔ log_voice ──
    if before.mute != after.mute:
        admin = await get_admin(member.guild, discord.AuditLogAction.member_update, member.id)
        embed = _voice_embed("🔇 كتم السيرفر" if after.mute else "🔊 فك كتم السيرفر", member, after.channel, admin=admin)
        await send_log(guild_id, "log_voice", embed, admin=admin)
        return
    if before.deaf != after.deaf:
        admin = await get_admin(member.guild, discord.AuditLogAction.member_update, member.id)
        embed = _voice_embed("🔇 دفن السيرفر" if after.deaf else "🔊 فك دفن السيرفر", member, after.channel, admin=admin)
        await send_log(guild_id, "log_voice", embed, admin=admin)
        return

    # ── Self Mute / Deafen ➔ log_voice ──
    if before.self_mute != after.self_mute:
        embed = _voice_embed("🔇 كتم الصوت" if after.self_mute else "🔊 فك الكتم", member, after.channel)
        await send_log(guild_id, "log_voice", embed)
        return
    if before.self_deaf != after.self_deaf:
        embed = _voice_embed("🔇 إيقاف الصوت" if after.self_deaf else "🔊 فك الإيقاف", member, after.channel)
        await send_log(guild_id, "log_voice", embed)
        return

    # ── Forced Disconnect (مع المنفذ من Audit Log) ➔ log_voice ──
    if before.channel and not after.channel and not member.bot:
        event_time = datetime.now(timezone.utc)
        voice_admin = await find_voice_move_admin(member.guild, before_id, None, event_time)
        embed = _voice_embed("🔌 انقطاع 🔌", member, before.channel)
        embed.add_field(name="🕐 الوقت", value=f"<t:{int(event_time.timestamp())}:F>", inline=False)
        if isinstance(voice_admin, str):
            embed.add_field(name="المنفذ", value=f"⚠️ {voice_admin}", inline=False)
        elif voice_admin:
            embed.add_field(name="المنفذ", value=f"{voice_admin.mention}", inline=False)
        else:
            embed.add_field(name="المنفذ", value="⚠️ النظام", inline=False)
        await send_log(guild_id, "log_voice", embed, admin=voice_admin if not isinstance(voice_admin, str) else None)
        return

    # ── Join / Leave / Move ➔ log_voice ──
    if member.bot or (before_id == after_id and before_id is not None):
        return
    event_key = (member.id, before_id, after_id)
    now = time.time()
    if now - voice_event_cache.get(event_key, 0) < 5:
        return
    voice_event_cache[event_key] = now

    if before.channel and after.channel:
        if before.channel.id == after.channel.id:
            return
        event_time = datetime.now(timezone.utc)
        admin_move = await find_voice_move_admin(member.guild, before_id, after_id, event_time)
        if isinstance(admin_move, str):
            embed = _voice_embed("🔄 انتقال", member, after.channel)
            embed.add_field(name="من", value=f"<#{before_id}>", inline=True)
            embed.add_field(name="ملاحظة", value=admin_move, inline=False)
        elif admin_move:
            embed = _voice_embed("🔀 سحب من", member, after.channel, admin=admin_move)
            embed.add_field(name="من", value=f"<#{before_id}>", inline=True)
        else:
            embed = _voice_embed("🔄 انتقال", member, after.channel)
            embed.add_field(name="من", value=f"<#{before_id}>", inline=True)
        await send_log(guild_id, "log_voice", embed, admin=admin_move if not isinstance(admin_move, str) else None)
    elif not before.channel and after.channel:
        embed = _voice_embed("📥 دخول روم صوتي", member, after.channel)
        await send_log(guild_id, "log_voice", embed)
    elif before.channel and not after.channel:
        event_time = datetime.now(timezone.utc)
        embed = _voice_embed("📤 خروج من الروم", member, before.channel)
        embed.add_field(name="🕐 الوقت", value=f"<t:{int(event_time.timestamp())}:F>", inline=False)
        embed.add_field(name="المنفذ", value="⚠️ النظام", inline=False)
        await send_log(guild_id, "log_voice", embed)

    # ── AFK check: دخول الروم الصوتي المحدد → إلغاء AFK ──
    afk_vc_id = afk_voice_channels.get(guild_id)
    if (not member.bot and member.id in afk_users and after.channel and not before.channel
            and afk_vc_id is not None and after.channel.id == afk_vc_id):
        afk_users.pop(member.id, None)
        save_data()
        old_nick = member.display_name
        if old_nick.startswith("[AFK] "):
            try:
                await member.edit(nick=old_nick[6:])
            except:
                pass
        target = member.guild.system_channel or discord.utils.find(
            lambda ch: isinstance(ch, discord.TextChannel) and ch.permissions_for(member.guild.me).send_messages,
            member.guild.text_channels
        )
        if target:
            await target.send(f"👋 **{member.mention}** أهلاً رجعت! تم إلغاء الـAFK.", delete_after=5)

# ════════════════════════════════════════
# Activity Log — تتبع البرامج في الرومات الصوتية 🎮
# ════════════════════════════════════════

_ACTIVITY_COLOR_MAP = {
    "playing": 0x7289DA,
    "listening": 0x1DB954,
    "watching": 0xFF6B6B,
    "streaming": 0x9146FF,
    "competing": 0xE74C3C,
    "custom": 0x5865F2,
}

_ACTIVITY_LABELS = {
    "playing": "🎮 يلعب",
    "listening": "🎵 يسمع",
    "watching": "🎬 يشاهد",
    "streaming": "🎤 يبث",
    "competing": "⚔️ ينافس",
    "custom": "⚙️ نشاط مخصص",
}

def _activity_embed(member, activity, channel):
    act_type = str(activity.type).split(".")[-1] if activity.type else "custom"
    color = _ACTIVITY_COLOR_MAP.get(act_type, 0x5865F2)
    label = _ACTIVITY_LABELS.get(act_type, "⚙️ نشاط")
    title = f"{label} في الروم الصوتي"

    embed = LogEmbed.base(title, color, guild=member.guild)
    LogEmbed.user_field(embed, member, "العضو")
    if channel:
        LogEmbed.channel_field(embed, "الروم الصوتي", channel)

    act_name = getattr(activity, "name", None) or "غير معروف"
    act_details = getattr(activity, "details", None)
    act_state = getattr(activity, "state", None)
    act_url = getattr(activity, "url", None)

    activity_text = f"**{act_name}**"
    if act_details:
        activity_text += f"\n> {act_details}"
    if act_state:
        activity_text += f"\n> {act_state}"
    if act_url:
        activity_text += f"\n🔗 {act_url}"

    embed.add_field(name="النشاط الحالي", value=activity_text[:1024], inline=False)
    embed.set_footer(text=f"⏰ {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")
    return embed

@bot.event
async def on_presence_update(before, after):
    try:
        if after.bot:
            return
        if not after.guild:
            return
        guild_id = after.guild.id
        if not activity_tracking_enabled.get(guild_id, False):
            return
        if not after.voice or not after.voice.channel:
            return

        before_act = before.activity
        after_act = after.activity

        if before_act == after_act:
            return

        if after_act is None:
            return

        dedup_key = f"{after.id}_{guild_id}_{after_act.type}_{getattr(after_act, 'name', '')}"
        now = time.time()
        if dedup_key in recent_activity_logs and now - recent_activity_logs[dedup_key] < 60:
            return
        recent_activity_logs[dedup_key] = now

        embed = _activity_embed(after, after_act, after.voice.channel)
        await send_log(guild_id, "log_activity", embed)
    except Exception as e:
        print(f"[ACTIVITY LOG ERROR] {e}")

@bot.event
async def on_guild_channel_create(channel):
    if not channel.guild:
        return
    is_voice = isinstance(channel, discord.VoiceChannel)
    embed = LogEmbed.base("📁 إنشاء روم", LogColors.CREATE, guild=channel.guild)
    LogEmbed.channel_field(embed, "الروم", channel)
    embed.add_field(name="النوع", value="🎤 صوتي" if is_voice else "💬 نصي", inline=True)
    embed.add_field(name="المعرف", value=f"`{channel.id}`", inline=True)
    category = getattr(channel, 'category', None)
    if category:
        embed.add_field(name="القسم", value=category.name, inline=True)
    if hasattr(channel, 'topic') and channel.topic:
        embed.add_field(name="الموضوع", value=channel.topic[:200], inline=False)
    if hasattr(channel, 'nsfw') and channel.nsfw:
        embed.add_field(name="🔞 NSFW", value="✅ نعم", inline=True)
    if is_voice and hasattr(channel, 'user_limit') and channel.user_limit:
        embed.add_field(name="السعة", value=f"{channel.user_limit} عضو", inline=True)
    admin = await get_admin(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(channel.guild.id, "log_channels", embed, admin=admin)

@bot.event
async def on_guild_channel_delete(channel):
    if not channel.guild:
        return
    is_voice = isinstance(channel, discord.VoiceChannel)
    embed = LogEmbed.base("📁 حذف روم", LogColors.DELETE, guild=channel.guild)
    embed.add_field(name="الروم", value=f"{channel.name} `({channel.id})`")
    embed.add_field(name="النوع", value="🎤 صوتي" if is_voice else "💬 نصي", inline=True)
    category = getattr(channel, 'category', None)
    if category:
        embed.add_field(name="القسم", value=category.name, inline=True)
    if hasattr(channel, 'topic') and channel.topic:
        embed.add_field(name="الموضوع", value=channel.topic[:200], inline=False)
    if is_voice and hasattr(channel, 'voice_members'):
        embed.add_field(name="الأعضاء المتصلين", value=f"{len(channel.members)} عضو", inline=True)
    admin = await get_admin(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(channel.guild.id, "log_channels", embed, admin=admin)

    # Anti-Nuke check (نصي فقط)
    if not is_voice and anti_nuke.is_enabled(channel.guild.id):
        if anti_nuke.check_channel_delete(channel.guild.id, channel, False):
            embed_nuke = LogEmbed.base("💣 Nuke detected!", LogColors.NUKE, guild=channel.guild)
            embed_nuke.add_field(name="تحذير", value="🚨 يتم حذف رومات بشكل جماعي!\nالسيرفر مقفول لحد ما الأدمن يتأكد.")
            embed_nuke.add_field(name="الإجراء", value="🔒 قفل السيرفر - الرومات الصوتية لم تتأثر")
            LogEmbed.audit_field(embed_nuke, admin)
            await send_log(channel.guild.id, "protection_security", embed_nuke, admin=admin)

@bot.event
async def on_guild_channel_update(before, after):
    if not before.guild:
        return
    embed = LogEmbed.base("📁 تحديث روم", LogColors.EDIT, guild=before.guild)
    LogEmbed.channel_field(embed, "الروم", after)
    changes = []
    if before.name != after.name:
        changes.append(f"الاسم: {before.name} → {after.name}")
    if before.position != after.position:
        changes.append(f"الموقع: {before.position} → {after.position}")
    if before.category != after.category:
        changes.append(f"الفئة: {before.category} → {after.category}")
    if before.overwrites != after.overwrites:
        added = [f"<@&{t.id}>" if isinstance(t, discord.Role) else f"<@{t.id}>" for t in after.overwrites if t not in before.overwrites]
        removed = [f"<@&{t.id}>" if isinstance(t, discord.Role) else f"<@{t.id}>" for t in before.overwrites if t not in after.overwrites]
        perm_changes = []
        if added: perm_changes.append(f"➕ إضافة صلاحيات لـ: {', '.join(added)}")
        if removed: perm_changes.append(f"➖ إزالة صلاحيات من: {', '.join(removed)}")
        for t in after.overwrites:
            if t in before.overwrites and before.overwrites[t] != after.overwrites[t]:
                perm_changes.append(f"🔐 تحديث صلاحيات <@&{t.id}>" if isinstance(t, discord.Role) else f"🔐 تحديث صلاحيات <@{t.id}>")
        if perm_changes:
            changes.extend(perm_changes)
    if changes:
        embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
        admin = await get_admin(before.guild, discord.AuditLogAction.channel_update, after.id)
        LogEmbed.audit_field(embed, admin)
        await send_log(before.guild.id, "log_channels", embed, admin=admin)
        # Also log to channel_perm if permission changes
        if before.overwrites != after.overwrites:
            perm_embed = LogEmbed.base("🔐 تحديث صلاحيات الروم", LogColors.WARN, guild=before.guild)
            LogEmbed.channel_field(perm_embed, "الروم", after)
            perm_embed.add_field(name="التغييرات", value="\n".join(perm_changes), inline=False)
            LogEmbed.audit_field(perm_embed, admin)
            await send_log(before.guild.id, "log_channel_perm", perm_embed, admin=admin)

@bot.event
async def on_guild_update(before, after):
    embed = LogEmbed.base("⚙️ تحديث السيرفر", LogColors.WARN, guild=after)
    changes = []
    if before.name != after.name:
        changes.append(f"├─ الاسم: {before.name} → {after.name}")
    if before.icon != after.icon:
        changes.append("├─ 📷 تم تغيير الأيقونة")
    if before.banner != after.banner:
        changes.append("├─ 🖼️ تم تغيير البانر")
    if before.description != after.description:
        changes.append("├─ 📝 تم تحديث الوصف")
    if before.verification_level != after.verification_level:
        changes.append(f"├─ 🔒 مستوى التحقق: {before.verification_level} → {after.verification_level}")
    if before.owner_id != after.owner_id:
        changes.append(f"├─ 👑 تغيير المالك: `{before.owner_id}` → `{after.owner_id}`")
    if before.premium_tier != after.premium_tier:
        changes.append(f"├─ 💎 مستوى الـ Boost: {before.premium_tier} → {after.premium_tier}")
    if before.mfa_level != after.mfa_level:
        changes.append(f"├─ 🔐 مستوى MFA: {before.mfa_level} → {after.mfa_level}")
    if changes:
        changes[-1] = changes[-1].replace("├─", "└─")
        embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
        admin = await get_admin(before, discord.AuditLogAction.guild_update, after.id)
        LogEmbed.audit_field(embed, admin)
        await send_log(before.id, "log_all", embed, admin=admin)

@bot.event
async def on_guild_role_create(role):
    if not role.guild:
        return
    embed = LogEmbed.base("🎭 إنشاء رتبة جديدة", LogColors.CREATE, guild=role.guild)
    embed.add_field(name="الرتبة", value=role.mention)
    embed.add_field(name="المعرف", value=f"`{role.id}`", inline=True)
    embed.add_field(name="اللون", value=str(role.color), inline=True)
    embed.add_field(name="الظهور المنفصل", value="✅ نعم" if role.hoist else "❌ لا", inline=True)
    embed.add_field(name="قابل للمنشن", value="✅ نعم" if role.mentionable else "❌ لا", inline=True)
    embed.add_field(name="الموقع", value=f"#{role.position}", inline=True)
    perms = ", ".join([p[0] for p in role.permissions if p[1]])[:500] or "لا يوجد"
    embed.add_field(name="الصلاحيات", value=perms, inline=False)
    admin = await get_admin(role.guild, discord.AuditLogAction.role_create, role.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(role.guild.id, "log_edit_role", embed, admin=admin)

@bot.event
async def on_guild_role_delete(role):
    if not role.guild:
        return
    embed = LogEmbed.base("🗑️ حذف رتبة", LogColors.DELETE, guild=role.guild)
    embed.add_field(name="الرتبة", value=f"{role.name} `({role.id})`")
    embed.add_field(name="اللون", value=str(role.color), inline=True)
    embed.add_field(name="الموقع", value=f"#{role.position}", inline=True)
    embed.add_field(name="الظهور المنفصل", value="✅ نعم" if role.hoist else "❌ لا", inline=True)
    embed.add_field(name="الأعضاء الحاملين", value=f"{len(role.members)} عضو", inline=True)
    perms = ", ".join([p[0] for p in role.permissions if p[1]])[:500] or "لا يوجد"
    embed.add_field(name="الصلاحيات المحذوفة", value=perms, inline=False)
    admin = await get_admin(role.guild, discord.AuditLogAction.role_delete, role.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(role.guild.id, "log_edit_role", embed, admin=admin)

    # Anti-Nuke role check
    if anti_nuke.is_enabled(role.guild.id):
        if anti_nuke.check_role_delete(role.guild.id, role):
            embed_nuke = LogEmbed.base("💣 Nuke detected!", LogColors.NUKE, guild=role.guild)
            embed_nuke.add_field(name="تحذير", value="🚨 يتم حذف رتب بشكل جماعي!\nالسيرفر مقفول لحد ما الأدمن يتأكد.")
            embed_nuke.add_field(name="الإجراء", value="🔒 قفل السيرفر")
            await send_log(role.guild.id, "protection_security", embed_nuke, admin=admin)

@bot.event
async def on_guild_role_update(before, after):
    if not before.guild:
        return
    embed = LogEmbed.base("✏️ تحديث رتبة", LogColors.EDIT, guild=before.guild)
    embed.add_field(name="الرتبة", value=after.mention)
    embed.add_field(name="المعرف", value=f"`{after.id}`", inline=True)
    changes = []
    if before.name != after.name:
        changes.append(f"├─ الاسم: {before.name} → {after.name}")
    if before.color != after.color:
        changes.append(f"├─ اللون: {before.color} → {after.color}")
    if before.permissions != after.permissions:
        changes.append("├─ 🔒 تم تغيير الصلاحيات")
    if before.hoist != after.hoist:
        val = "✅ نعم" if after.hoist else "❌ لا"
        changes.append(f"├─ 📌 الظهور المنفصل: {val}")
    if before.mentionable != after.mentionable:
        val = "✅ نعم" if after.mentionable else "❌ لا"
        changes.append(f"├─ 💬 قابل للمنشن: {val}")
    if before.position != after.position:
        changes.append(f"├─ 📍 الموقع: {before.position} → {after.position}")
    if changes:
        changes[-1] = changes[-1].replace("├─", "└─")
        embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
        admin = await get_admin(before.guild, discord.AuditLogAction.role_update, after.id)
        LogEmbed.audit_field(embed, admin)
        await send_log(before.guild.id, "log_edit_role", embed, admin=admin)

# ════════════════════════════════════════
# أحداث اللوق المفقودة
# ════════════════════════════════════════

@bot.event
async def on_guild_channel_pins_update(channel, last_pin):
    if not channel.guild:
        return
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_pin):
            if entry.target and entry.extra and entry.extra.channel.id == channel.id:
                embed = LogEmbed.base("📌 تثبيت رسالة", LogColors.CREATE, guild=channel.guild)
                LogEmbed.channel_field(embed, "الروم", channel)
                LogEmbed.audit_field(embed, entry.user)
                await send_log(channel.guild.id, "log_pin_bulk", embed, admin=entry.user)
                return
    except: pass
    embed = LogEmbed.base("📌 تغيير في التثبيت", LogColors.EDIT, guild=channel.guild)
    LogEmbed.channel_field(embed, "الروم", channel)
    await send_log(channel.guild.id, "log_pin_bulk", embed)

@bot.event
async def on_bulk_message_delete(messages):
    if not messages:
        return
    guild = messages[0].guild
    if not guild:
        return
    ch = messages[0].channel
    embed = LogEmbed.base("🗑️ حذف رسائل جماعي", LogColors.DELETE, guild=guild)
    LogEmbed.channel_field(embed, "الروم", ch)
    embed.add_field(name="عدد الرسائل", value=str(len(messages)), inline=True)
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.message_bulk_delete):
            if entry.extra and entry.extra.channel.id == ch.id:
                LogEmbed.audit_field(embed, entry.user)
                await send_log(guild.id, "log_pin_bulk", embed, admin=entry.user)
                return
    except: pass
    await send_log(guild.id, "log_pin_bulk", embed)

@bot.event
async def on_guild_emojis_update(guild, before, after):
    if not guild:
        return
    before_ids = {e.id for e in before}
    after_ids = {e.id for e in after}
    added = [e for e in after if e.id not in before_ids]
    removed = [e for e in before if e.id not in after_ids]
    updated = [e for e in after if e.id in before_ids and e.name != next((x.name for x in before if x.id == e.id), None)]
    if not (added or removed or updated):
        return
    embed = LogEmbed.base("😀 تحديث الإيموجي", LogColors.WARN, guild=guild)
    parts = []
    if added: parts.append(f"➕ إضافة: {' '.join(str(e) for e in added)}")
    if removed: parts.append(f"➖ حذف: {' '.join(str(e) for e in removed)}")
    if updated: parts.append(f"✏️ تحديث: {' '.join(f'{e}' for e in updated)}")
    embed.description = "\n".join(parts)
    admin = await get_admin(guild, discord.AuditLogAction.emoji_create, guild.id)
    if not admin: admin = await get_admin(guild, discord.AuditLogAction.emoji_delete, guild.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(guild.id, "log_emoji_sticker", embed, admin=admin)

@bot.event
async def on_guild_stickers_update(guild, before, after):
    if not guild:
        return
    before_ids = {s.id for s in before}
    after_ids = {s.id for s in after}
    added = [s for s in after if s.id not in before_ids]
    removed = [s for s in before if s.id not in after_ids]
    updated = [s for s in after if s.id in before_ids and s.name != next((x.name for x in before if x.id == s.id), None)]
    if not (added or removed or updated):
        return
    embed = LogEmbed.base("🎨 تحديث الملصقات", LogColors.WARN, guild=guild)
    parts = []
    if added: parts.append(f"➕ إضافة: {', '.join(s.name for s in added)}")
    if removed: parts.append(f"➖ حذف: {', '.join(s.name for s in removed)}")
    if updated: parts.append(f"✏️ تحديث: {', '.join(s.name for s in updated)}")
    embed.description = "\n".join(parts)
    admin = await get_admin(guild, discord.AuditLogAction.sticker_create, guild.id)
    if not admin: admin = await get_admin(guild, discord.AuditLogAction.sticker_delete, guild.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(guild.id, "log_emoji_sticker", embed, admin=admin)

@bot.event
async def on_thread_create(thread):
    if not thread.guild:
        return
    embed = LogEmbed.base("🧵 إنشاء ثريد", LogColors.CREATE, guild=thread.guild)
    embed.add_field(name="الثريد", value=thread.mention, inline=True)
    if thread.parent: LogEmbed.channel_field(embed, "الروم الأصلي", thread.parent)
    admin = await get_admin(thread.guild, discord.AuditLogAction.thread_create, thread.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(thread.guild.id, "log_thread", embed, admin=admin)

@bot.event
async def on_thread_delete(thread):
    if not thread.guild:
        return
    embed = LogEmbed.base("🧵 حذف ثريد", LogColors.DELETE, guild=thread.guild)
    embed.add_field(name="الثريد", value=f"`{thread.name}`")
    if thread.parent: LogEmbed.channel_field(embed, "الروم الأصلي", thread.parent)
    admin = await get_admin(thread.guild, discord.AuditLogAction.thread_delete, thread.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(thread.guild.id, "log_thread", embed, admin=admin)

@bot.event
async def on_thread_update(before, after):
    if not before.guild:
        return
    embed = LogEmbed.base("🧵 تحديث ثريد", LogColors.EDIT, guild=before.guild)
    embed.add_field(name="الثريد", value=after.mention if hasattr(after, 'mention') else after.name, inline=True)
    changes = []
    if before.name != after.name: changes.append(f"الاسم: {before.name} → {after.name}")
    if before.locked != after.locked: changes.append(f"🔒 القفل: {'مقفول' if after.locked else 'مفتوح'}")
    if before.archived != after.archived: changes.append(f"📦 الأرشيف: {'مؤرشف' if after.archived else 'غير مؤرشف'}")
    if changes:
        embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
        admin = await get_admin(before.guild, discord.AuditLogAction.thread_update, after.id)
        LogEmbed.audit_field(embed, admin)
        await send_log(before.guild.id, "log_thread", embed, admin=admin)

@bot.event
async def on_invite_create(invite):
    if not invite.guild:
        return
    embed = LogEmbed.base("📨 إنشاء دعوة", LogColors.CREATE, guild=invite.guild)
    embed.add_field(name="الرابط", value=f"discord.gg/{invite.code}", inline=True)
    embed.add_field(name="الماكس", value=str(invite.max_uses) if invite.max_uses else "غير محدود", inline=True)
    if invite.inviter:
        LogEmbed.user_field(embed, invite.inviter, "المنشئ")
    await send_log(invite.guild.id, "log_invite", embed)

@bot.event
async def on_invite_delete(invite):
    if not invite.guild:
        return
    embed = LogEmbed.base("📨 حذف دعوة", LogColors.DELETE, guild=invite.guild)
    embed.add_field(name="الرابط", value=f"discord.gg/{invite.code}", inline=True)
    await send_log(invite.guild.id, "log_invite", embed)

@bot.event
async def on_webhooks_update(channel):
    if not channel.guild:
        return
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            if entry.target and hasattr(entry.target, 'channel') and entry.target.channel.id == channel.id:
                embed = LogEmbed.base("🔗 إنشاء ويب هوك", LogColors.CREATE, guild=channel.guild)
                LogEmbed.channel_field(embed, "الروم", channel)
                LogEmbed.audit_field(embed, entry.user)
                await send_log(channel.guild.id, "log_webhook", embed, admin=entry.user)
                return
    except: pass
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_delete):
            if entry.target and hasattr(entry.target, 'channel') and entry.target.channel.id == channel.id:
                embed = LogEmbed.base("🔗 حذف ويب هوك", LogColors.DELETE, guild=channel.guild)
                LogEmbed.channel_field(embed, "الروم", channel)
                LogEmbed.audit_field(embed, entry.user)
                await send_log(channel.guild.id, "log_webhook", embed, admin=entry.user)
                return
    except: pass
    embed = LogEmbed.base("🔗 تحديث ويب هوك", LogColors.EDIT, guild=channel.guild)
    LogEmbed.channel_field(embed, "الروم", channel)
    await send_log(channel.guild.id, "log_webhook", embed)

@bot.event
async def on_guild_integrations_update(guild):
    if not guild:
        return
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
            embed = LogEmbed.base("🔌 تحديث الاندماجات", LogColors.EDIT, guild=guild)
            LogEmbed.audit_field(embed, entry.user)
            await send_log(guild.id, "log_integration", embed, admin=entry.user)
            return
    except: pass
    embed = LogEmbed.base("🔌 تحديث الاندماجات", LogColors.EDIT, guild=guild)
    await send_log(guild.id, "log_integration", embed)

@bot.event
async def on_stage_instance_create(stage):
    if not stage.guild:
        return
    embed = LogEmbed.base("🎙️ إنشاء ستيدج", LogColors.CREATE, guild=stage.guild)
    embed.add_field(name="الستيدج", value=stage.channel.mention if stage.channel else f"`{stage.channel_id}`", inline=True)
    if stage.topic: embed.add_field(name="الموضوع", value=stage.topic, inline=False)
    admin = await get_admin(stage.guild, discord.AuditLogAction.stage_instance_create, stage.channel_id)
    LogEmbed.audit_field(embed, admin)
    await send_log(stage.guild.id, "log_stage", embed, admin=admin)

@bot.event
async def on_stage_instance_delete(stage):
    if not stage.guild:
        return
    embed = LogEmbed.base("🎙️ حذف ستيدج", LogColors.DELETE, guild=stage.guild)
    embed.add_field(name="الستيدج", value=stage.channel.mention if stage.channel else f"`{stage.channel_id}`", inline=True)
    admin = await get_admin(stage.guild, discord.AuditLogAction.stage_instance_delete, stage.channel_id)
    LogEmbed.audit_field(embed, admin)
    await send_log(stage.guild.id, "log_stage", embed, admin=admin)

@bot.event
async def on_stage_instance_update(before, after):
    if not before.guild:
        return
    changes = []
    if before.topic != after.topic: changes.append(f"الموضوع: {before.topic} → {after.topic}")
    if before.privacy_level != after.privacy_level: changes.append(f"الخصوصية: {before.privacy_level} → {after.privacy_level}")
    if not changes:
        return
    embed = LogEmbed.base("🎙️ تحديث ستيدج", LogColors.EDIT, guild=before.guild)
    embed.add_field(name="الستيدج", value=after.channel.mention if after.channel else f"`{after.channel_id}`", inline=True)
    embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
    admin = await get_admin(before.guild, discord.AuditLogAction.stage_instance_update, after.channel_id)
    LogEmbed.audit_field(embed, admin)
    await send_log(before.guild.id, "log_stage", embed, admin=admin)

@bot.event
async def on_automod_rule_create(rule):
    if not rule.guild:
        return
    embed = LogEmbed.base("🤖 إنشاء قاعدة أوتومود", LogColors.CREATE, guild=rule.guild)
    embed.add_field(name="القاعدة", value=rule.name, inline=True)
    embed.add_field(name="الحدث", value=str(rule.event_type), inline=True)
    admin = await get_admin(rule.guild, discord.AuditLogAction.automod_rule_create, rule.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(rule.guild.id, "log_automod", embed, admin=admin)

@bot.event
async def on_automod_rule_delete(rule):
    if not rule.guild:
        return
    embed = LogEmbed.base("🤖 حذف قاعدة أوتومود", LogColors.DELETE, guild=rule.guild)
    embed.add_field(name="القاعدة", value=rule.name, inline=True)
    admin = await get_admin(rule.guild, discord.AuditLogAction.automod_rule_delete, rule.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(rule.guild.id, "log_automod", embed, admin=admin)

@bot.event
async def on_automod_rule_update(before, after):
    if not before.guild:
        return
    changes = []
    if before.name != after.name: changes.append(f"الاسم: {before.name} → {after.name}")
    if before.enabled != after.enabled: changes.append(f"الحالة: {'مفعل' if after.enabled else 'معطل'}")
    if not changes:
        return
    embed = LogEmbed.base("🤖 تحديث قاعدة أوتومود", LogColors.EDIT, guild=before.guild)
    embed.add_field(name="القاعدة", value=after.name, inline=True)
    embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
    admin = await get_admin(before.guild, discord.AuditLogAction.automod_rule_update, after.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(before.guild.id, "log_automod", embed, admin=admin)

@bot.event
async def on_automod_action(execution):
    guild = execution.guild
    if not guild:
        return
    user = execution.user
    rule = execution.rule
    action_type = execution.action.type
    if action_type == discord.AutoModRuleActionType.block_message:
        title = "🚫 أوتومود - حظر رسالة"
        log_key = "log_automod"
    elif action_type == discord.AutoModRuleActionType.send_alert_message:
        title = "🚩 أوتومود - تنبيه"
        log_key = "log_automod"
    elif action_type == discord.AutoModRuleActionType.timeout:
        title = "⏱️ أوتومود - تايم أوت"
        log_key = "ban_kick_timeout"
    else:
        title = "🤖 أوتومود - إجراء"
        log_key = "log_automod"
    embed = LogEmbed.base(title, LogColors.WARN, guild=guild)
    if user: LogEmbed.user_field(embed, user, "العضو", thumb=True)
    if rule: embed.add_field(name="القاعدة", value=rule.name, inline=True)
    if execution.matched_content: embed.add_field(name="المحتوى", value=f"```{execution.matched_content[:500]}```", inline=False)
    if execution.matched_keyword: embed.add_field(name="الكلمة المطابقة", value=execution.matched_keyword, inline=True)
    await send_log(guild.id, log_key, embed)

@bot.event
async def on_scheduled_event_create(event):
    if not event.guild:
        return
    embed = LogEmbed.base("📅 إنشاء حدث", LogColors.CREATE, guild=event.guild)
    embed.add_field(name="الحدث", value=event.name, inline=True)
    if event.description: embed.add_field(name="الوصف", value=event.description[:500], inline=False)
    embed.add_field(name="النوع", value=str(event.event_type), inline=True)
    embed.add_field(name="البداية", value=f"<t:{int(event.start_time.timestamp())}:F>", inline=True)
    if event.end_time: embed.add_field(name="النهاية", value=f"<t:{int(event.end_time.timestamp())}:F>", inline=True)
    admin = await get_admin(event.guild, discord.AuditLogAction.guild_scheduled_event_create, event.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(event.guild.id, "log_scheduled_event", embed, admin=admin)

@bot.event
async def on_scheduled_event_delete(event):
    if not event.guild:
        return
    embed = LogEmbed.base("📅 حذف حدث", LogColors.DELETE, guild=event.guild)
    embed.add_field(name="الحدث", value=event.name, inline=True)
    admin = await get_admin(event.guild, discord.AuditLogAction.guild_scheduled_event_delete, event.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(event.guild.id, "log_scheduled_event", embed, admin=admin)

@bot.event
async def on_scheduled_event_update(before, after):
    if not before.guild:
        return
    changes = []
    if before.name != after.name: changes.append(f"الاسم: {before.name} → {after.name}")
    if before.status != after.status: changes.append(f"الحالة: {before.status} → {after.status}")
    if not changes:
        return
    embed = LogEmbed.base("📅 تحديث حدث", LogColors.EDIT, guild=before.guild)
    embed.add_field(name="الحدث", value=after.name, inline=True)
    embed.add_field(name="التغييرات", value="\n".join(changes), inline=False)
    admin = await get_admin(before.guild, discord.AuditLogAction.guild_scheduled_event_update, after.id)
    LogEmbed.audit_field(embed, admin)
    await send_log(before.guild.id, "log_scheduled_event", embed, admin=admin)

# ════════════════════════════════════════
# نظام الجيفت اواي 🎁
# ════════════════════════════════════════

@bot.hybrid_command(name="giveaway", aliases=['جيفت'])
@commands.has_permissions(administrator=True)
async def جيفت(ctx, time_str: str, *, prize: str):
    """!جيفت <مدة> <جائزة> - سحب هدية (مثال: !جيفت 10m نيتفلكس)"""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = time_str[-1]
    if unit not in units:
        await ctx.send("❌ وحدة الوقت غلط. استخدم: s, m, h, d (مثال: 10m)")
        return
    try:
        seconds = int(time_str[:-1]) * units[unit]
    except ValueError:
        await ctx.send("❌ اكتب رقم صحيح. مثال: `!جيفت 10m نيتفلكس`")
        return
    if seconds < 10 or seconds > 604800:
        await ctx.send("❌ المدة بين 10 ثواني و 7 أيام.")
        return

    embed = discord.Embed(title="🎁 جيفت اواي!", description=f"**الجائزة:** {prize}\n\nاضغط 🎉 للمشاركة!", color=0x2ECC71)
    embed.set_footer(text=f"ينتهي بعد: {time_str} | بواسطة {ctx.author.display_name}")
    msg = await ctx.send("@everyone 🎁", embed=embed)
    await msg.add_reaction("🎉")

    await asyncio.sleep(seconds)
    msg = await ctx.channel.fetch_message(msg.id)

    users = []
    for reaction in msg.reactions:
        if str(reaction.emoji) == "🎉":
            async for user in reaction.users():
                if not user.bot:
                    users.append(user)
            break

    if not users:
        await ctx.send(f"❌ لا يوجد مشتركين في السحب على **{prize}** 😢")
        return

    winner = random.choice(users)
    embed = discord.Embed(title="🎁 فائز الجيفت!", description=f"**الجائزة:** {prize}\n\n**الفائز:** {winner.mention} 🎉", color=0x2ECC71)
    await ctx.send(f"🎉 مبروك {winner.mention}!", embed=embed)

# ════════════════════════════════════════
# نظام الأغاني 🎵
# ════════════════════════════════════════

import yt_dlp as youtube_dl
from imageio_ffmpeg import get_ffmpeg_exe
import urllib.request
import urllib.parse


FFMPEG_PATH = get_ffmpeg_exe()
music_queues = {}
music_now = {}
music_volumes = {}
music_loop = {}
music_autoleave = {}
music_history = {}
music_control_config = {}
music_play_start = {}
music_autoplay = {}
music_filters = {}
music_filter_opts = {
    "off": "",
    "bass": "bass=g=10",
    "nightcore": "asetrate=48000*1.25,aresample=48000,atempo=1.0",
    "vaporwave": "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    "echo": "aecho=0.8:0.9:1000:0.3",
    "treble": "treble=g=10",
}

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": False,
    "extract_flat": False,
}

def fmt_dur(seconds):
    if not seconds:
        return "??:??"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def queue_total_dur(q):
    return sum(t[3] for t in q if t[3])

async def search_yt(query):
    ydl = youtube_dl.YoutubeDL(ydl_opts)
    loop = asyncio.get_running_loop()
    def search():
        if query.startswith("http"):
            data = ydl.extract_info(query, download=False)
            if "entries" in data:
                return data["entries"]
            return [data]
        info = ydl.extract_info(f"ytsearch:5:{query}", download=False)
        return info["entries"] if info["entries"] else []
    try:
        return await loop.run_in_executor(None, search)
    except Exception as e:
        print(f"YT search error: {e}")
        return []

def _get_ffmpeg_opts(guild_id, seek_to=0):
    before = f"-ss {seek_to} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5" if seek_to else "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    filt = music_filters.get(guild_id, "off")
    af = music_filter_opts.get(filt, "")
    opts = f"-vn{f' -af \"{af}\"' if af else ''}"
    return {"before_options": before, "options": opts}

def play_next(guild_id, seek_to=0):
    loop_mode = music_loop.get(guild_id, "off")
    if loop_mode == "one" and guild_id in music_now:
        track = music_now[guild_id]
        guild = bot.get_guild(guild_id)
        if guild and guild.voice_client:
            vc = guild.voice_client
            ffmpeg_opts = _get_ffmpeg_opts(guild_id, seek_to)
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(track["url"], **ffmpeg_opts, executable=FFMPEG_PATH), volume=music_volumes.get(guild_id, 1.0))
            def after(error):
                asyncio.run_coroutine_threadsafe(after_play(guild_id), bot.loop)
            vc.play(source, after=after)
            music_play_start[guild_id] = time.time()
            return

    if guild_id not in music_queues or not music_queues[guild_id]:
        if music_autoplay.get(guild_id) and guild_id in music_now:
            asyncio.run_coroutine_threadsafe(_autoplay_fetch(guild_id), bot.loop)
            return
        music_now.pop(guild_id, None)
        auto_leave_delayed(guild_id)
        return

    if loop_mode == "all" and guild_id in music_now:
        music_queues[guild_id].append(music_now[guild_id])

    url, title, thumbnail, duration, webpage = music_queues[guild_id].pop(0)
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    vc = guild.voice_client
    if not vc:
        return

    if guild_id in music_now and len(music_history.setdefault(guild_id, [])) >= 20:
        music_history[guild_id].pop(0)
    if guild_id in music_now:
        music_history[guild_id].append(music_now[guild_id])

    ffmpeg_opts = _get_ffmpeg_opts(guild_id, seek_to)
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **ffmpeg_opts, executable=FFMPEG_PATH), volume=music_volumes.get(guild_id, 1.0))
    music_now[guild_id] = {"url": url, "title": title, "thumbnail": thumbnail, "duration": duration, "webpage": webpage}
    def after(error):
        asyncio.run_coroutine_threadsafe(after_play(guild_id), bot.loop)
    vc.play(source, after=after)
    music_play_start[guild_id] = time.time()

async def _autoplay_fetch(guild_id):
    track = music_now.get(guild_id)
    if not track or music_queues.get(guild_id):
        return
    try:
        ydl = youtube_dl.YoutubeDL(ydl_opts)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:1:{track['title']} related", download=False))
        entries = data.get("entries", [])
        if entries:
            e = entries[0]
            music_queues.setdefault(guild_id, []).append((
                e["url"], e["title"], e.get("thumbnail"), e.get("duration") or 0, e.get("webpage_url") or e["url"]
            ))
        await asyncio.sleep(0.5)
        play_next(guild_id)
    except Exception as e:
        print(f"Autoplay error: {e}")

async def fetch_lyrics(title):
    query = urllib.parse.quote(title[:50])
    url = f"https://api.lyrics.ovh/v1/{query}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
            return data.get("lyrics", "❌ ما لقيت كلمات.")
    except:
        title_clean = re.sub(r'\(.*?\)|\[.*?\]|ft\.\s*\S+|\bfeat\b.*', '', title).strip()
        query2 = urllib.parse.quote(title_clean[:50])
        url2 = f"https://api.lyrics.ovh/v1/{query2}"
        try:
            req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=8) as r2:
                data2 = json.loads(r2.read().decode())
                return data2.get("lyrics", "❌ ما لقيت كلمات.")
        except:
            return "❌ ما لقيت كلمات للأغنية."

async def after_play(guild_id):
    await asyncio.sleep(0.5)
    play_next(guild_id)

def auto_leave_delayed(guild_id):
    async def _leave():
        await asyncio.sleep(300)
        guild = bot.get_guild(guild_id)
        if not guild:
            return
        q = music_queues.get(guild_id, [])
        if q:
            return
        vc = guild.voice_client
        if vc and not vc.is_playing() and not vc.is_paused():
            music_now.pop(guild_id, None)
            await vc.disconnect()
    task = asyncio.create_task(_leave())
    music_autoleave[guild_id] = task

# ── Queue Pagination View ──
class QueueView(discord.ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.user_id = user_id
        self.page = 0

    def get_embed(self):
        q = music_queues.get(self.guild_id, [])
        now = music_now.get(self.guild_id)
        total_pages = max(1, math.ceil(len(q) / 10))
        self.page = max(0, min(self.page, total_pages - 1))
        embed = discord.Embed(title="📋 قائمة الانتظار", color=0x3498DB)
        if now:
            embed.description = f"**الحين:** [{now['title']}]({now['webpage']}) `{fmt_dur(now['duration'])}`"
        start = self.page * 10
        end = start + 10
        page_items = q[start:end]
        for i, (_, title, _, dur, wp) in enumerate(page_items, start + 1):
            embed.add_field(name=f"#{i}", value=f"[{title[:45]}]({wp}) `{fmt_dur(dur)}`", inline=False)
        loop_mode = music_loop.get(self.guild_id, "off")
        loop_icons = {"off": "➡", "one": "🔂", "all": "🔁"}
        embed.set_footer(text=f"الصفحة {self.page+1}/{total_pages} | {len(q)} أغنية | {loop_icons.get(loop_mode)} {loop_mode}")
        return embed

    @discord.ui.button(emoji="⏮", style=discord.ButtonStyle.secondary)
    async def first(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        self.page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        total_pages = max(1, math.ceil(len(music_queues.get(self.guild_id, [])) / 10))
        self.page = min(total_pages - 1, self.page + 1)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def last(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        total_pages = max(1, math.ceil(len(music_queues.get(self.guild_id, [])) / 10))
        self.page = total_pages - 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

# ── Search Selection View ──
class SearchSelect(discord.ui.View):
    def __init__(self, results, ctx, query):
        super().__init__(timeout=30)
        self.results = results
        self.ctx = ctx
        self.query = query
        options = []
        for i, r in enumerate(results[:5], 1):
            dur = r.get("duration", 0)
            label = f"{i}. {r['title'][:47]} [{fmt_dur(dur)}]"
            options.append(discord.SelectOption(label=label[:50], value=str(i), description=f"{r.get('channel','')[:50]}" or None))
        select = discord.ui.Select(placeholder="اختر رقم الأغنية", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            return
        idx = int(interaction.data["values"][0]) - 1
        r = self.results[idx]
        await interaction.response.edit_message(content=f"✅ تم اختيار **{r['title']}**", view=None, embed=None)
        await do_play(self.ctx, r["url"], r["title"], r.get("thumbnail"), r.get("duration", 0), r.get("webpage_url", r["url"]))

async def do_play(ctx, url, title, thumbnail, duration, webpage):
    guild_id = ctx.guild.id
    music_volumes.setdefault(guild_id, 1.0)
    if guild_id not in music_queues:
        music_queues[guild_id] = []
    music_queues[guild_id].append((url, title, thumbnail, duration, webpage))
    vc = ctx.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        pos = len(music_queues[guild_id])
        await ctx.send(f"✅ **{title}** 🤍 تمت الإضافة إلى القائمة (رقم {pos})")
    else:
        await ctx.send(f"✅ **جاري تشغيل:** {title} 🎵")
        play_next(guild_id)

@bot.group(name="اغاني", aliases=['music', 'اغنية'], invoke_without_command=True)
async def اغاني(ctx):
    """🎵 أوامر الأغاني"""
    embed = discord.Embed(title="🎵 نظام الأغاني", color=0x9B59B6)
    embed.add_field(name="`!اغاني شغل <اسم/رابط>`", value="▶️ تشغيل أغنية من يوتيوب", inline=False)
    embed.add_field(name="`!اغاني ايقاف`", value="⏹️ إيقاف الأغاني وطرد البوت", inline=False)
    embed.add_field(name="`!اغاني تخطي`", value="⏭️ تخطي الأغنية الحالية", inline=False)
    embed.add_field(name="`!اغاني وقف`", value="⏸️ إيقاف مؤقت", inline=False)
    embed.add_field(name="`!اغاني استمرار`", value="▶️ استمرار التشغيل", inline=False)
    embed.add_field(name="`!اغاني الحين`", value="🎶 الأغنية اللي تشتغل الحين", inline=False)
    embed.add_field(name="`!اغاني قائمة`", value="📋 قائمة الانتظار", inline=False)
    embed.add_field(name="`!اغاني حجم <0-200>`", value="🔊 التحكم بمستوى الصوت", inline=False)
    embed.add_field(name="`!اغاني خلط`", value="🔀 خلط القائمة", inline=False)
    embed.add_field(name="`!اغاني تكرار`", value="🔁 تغيير وضع التكرار (➡ off / 🔂 one / 🔁 all)", inline=False)
    embed.add_field(name="`!اغاني حذف <رقم>`", value="❌ حذف أغنية من القائمة", inline=False)
    await ctx.send(embed=embed)

@اغاني.command(name="شغل", aliases=['play', 'p'])
async def اغاني_شغل(ctx, *, query: str):
    """!اغاني شغل <اسم/رابط> - تشغيل أغنية"""
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ لازم تكون في روم صوتي.")
        return
    vc = ctx.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)

    msg = await ctx.send(f"🔍 **جاري البحث عن:** {query}...")
    results = await search_yt(query)
    if not results:
        await msg.edit(content="❌ ما لقيت نتيجة. جرب اسم ثاني.")
        return

    if len(results) == 1:
        r = results[0]
        guild_id = ctx.guild.id
        music_volumes.setdefault(guild_id, 1.0)
        if guild_id not in music_queues:
            music_queues[guild_id] = []
        vc = ctx.voice_client
        music_queues[guild_id].append((r["url"], r["title"], r.get("thumbnail"), r.get("duration", 0), r.get("webpage_url", r["url"])))
        if vc and (vc.is_playing() or vc.is_paused()):
            pos = len(music_queues[guild_id])
            await msg.edit(content=f"✅ **{r['title']}** 🤍 تمت الإضافة إلى القائمة (رقم {pos})")
        else:
            await msg.edit(content=f"✅ **جاري تشغيل:** {r['title']} 🎵")
            play_next(guild_id)
    else:
        view = SearchSelect(results, ctx, query)
        embed = discord.Embed(title="🔍 اختر الأغنية", color=0x9B59B6)
        for i, r in enumerate(results[:5], 1):
            dur = r.get("duration", 0)
            embed.add_field(name=f"{i}.", value=f"[{r['title'][:50]}]({r.get('webpage_url','')}) `{fmt_dur(dur)}`", inline=False)
        await msg.edit(content="", embed=embed, view=view)

@اغاني.command(name="ايقاف", aliases=['stop', 's'])
async def اغاني_ايقاف(ctx):
    """!اغاني ايقاف - إيقاف الأغاني وطرد البوت"""
    vc = ctx.voice_client
    if not vc:
        await ctx.send("❌ البوت مو في روم صوتي.")
        return
    guild_id = ctx.guild.id
    music_queues.pop(guild_id, None)
    music_now.pop(guild_id, None)
    music_loop.pop(guild_id, None)
    vc.stop()
    await vc.disconnect()
    await ctx.send("⏹️ **تم إيقاف الأغاني.** وداعاً 👋")

@اغاني.command(name="تخطي", aliases=['skip', 'next'])
async def اغاني_تخطي(ctx):
    """!اغاني تخطي - تخطي الأغنية الحالية"""
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        await ctx.send("❌ ما في أغنية تشتغل.")
        return
    vc.stop()
    await ctx.send("⏭️ **تم تخطي الأغنية.**")

@اغاني.command(name="وقف", aliases=['pause', 'pau'])
async def اغاني_وقف(ctx):
    """!اغاني وقف - إيقاف مؤقت"""
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        await ctx.send("❌ ما في أغنية تشتغل.")
        return
    vc.pause()
    await ctx.send("⏸️ **تم الإيقاف المؤقت.**")

@اغاني.command(name="استمرار", aliases=['resume', 'r'])
async def اغاني_استمرار(ctx):
    """!اغاني استمرار - استمرار التشغيل"""
    vc = ctx.voice_client
    if not vc or not vc.is_paused():
        await ctx.send("❌ ما في أغنية موقفة.")
        return
    vc.resume()
    await ctx.send("▶️ **تم الاستمرار.**")

@اغاني.command(name="الحين", aliases=['now', 'np'])
async def اغاني_الحين(ctx):
    """🎶 الأغنية اللي تشتغل الحين"""
    guild_id = ctx.guild.id
    now = music_now.get(guild_id)
    if not now:
        await ctx.send("❌ ما في أغنية تشتغل الحين.")
        return
    vc = ctx.voice_client
    loop_mode = music_loop.get(guild_id, "off")
    loop_icons = {"off": "➡", "one": "🔂", "all": "🔁"}
    q = music_queues.get(guild_id, [])
    embed = discord.Embed(title="🎶 الأغنية الحالية", color=0x2ECC71)
    embed.description = f"[**{now['title']}**]({now['webpage']})"
    if vc and vc.is_playing():
        pos = int(time.time() - music_play_start.get(guild_id, time.time()))
        total = now.get("duration", 0)
        if total:
            bar_len = 12
            filled = int(bar_len * pos / total) if total else 0
            bar = "▬" * filled + "🔘" + "▬" * (bar_len - filled - 1)
            embed.add_field(name="⏱ التقدم", value=f"{fmt_dur(pos)} {bar} {fmt_dur(total)}", inline=False)
    if now.get("thumbnail"):
        embed.set_thumbnail(url=now["thumbnail"])
    embed.set_footer(text=f"{len(q)} في القائمة | {loop_icons[loop_mode]} تكرار")
    await ctx.send(embed=embed)

@اغاني.command(name="قائمة", aliases=['queue', 'q'])
async def اغاني_قائمة(ctx):
    """📋 قائمة الانتظار"""
    guild_id = ctx.guild.id
    q = music_queues.get(guild_id, [])
    if not q:
        await ctx.send("📋 **قائمة الانتظار فاضية.**")
        return
    view = QueueView(guild_id, ctx.author.id)
    embed = view.get_embed()
    await ctx.send(embed=embed, view=view)

@اغاني.command(name="حجم", aliases=['volume', 'vol'])
async def اغاني_حجم(ctx, volume: int):
    """!اغاني حجم <0-200> - التحكم بمستوى الصوت"""
    if volume < 0 or volume > 200:
        await ctx.send("❌ الحجم يكون بين 0 و 200.")
        return
    vc = ctx.voice_client
    guild_id = ctx.guild.id
    music_volumes[guild_id] = volume / 100.0
    if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = volume / 100.0
    await ctx.send(f"🔊 **تم تعيين الصوت إلى:** {volume}%")

@اغاني.command(name="خلط", aliases=['shuffle', 'خلط_القائمة'])
async def اغاني_خلط(ctx):
    """🔀 خلط القائمة"""
    guild_id = ctx.guild.id
    q = music_queues.get(guild_id, [])
    if len(q) < 2:
        await ctx.send("❌ القائمة صغيرة مررة عشان أخلطها.")
        return
    now = music_now.get(guild_id)
    if now and music_loop.get(guild_id) == "all":
        q = q[1:]
    random.shuffle(q)
    if now and music_loop.get(guild_id) == "all":
        q.insert(0, now)
    music_queues[guild_id] = q
    await ctx.send("🔀 **تم خلط القائمة!**")

@اغاني.command(name="تكرار", aliases=['loop', 'repeat'])
async def اغاني_تكرار(ctx):
    """🔁 تغيير وضع التكرار"""
    guild_id = ctx.guild.id
    current = music_loop.get(guild_id, "off")
    order = ["off", "one", "all"]
    idx = (order.index(current) + 1) % 3
    music_loop[guild_id] = order[idx]
    icons = {"off": "➡ إيقاف التكرار", "one": "🔂 تكرار أغنية واحدة", "all": "🔁 تكرار القائمة كاملة"}
    await ctx.send(f"{icons[order[idx]]}")

@اغاني_تكرار.error
async def اغاني_تكرار_error(ctx, error):
    if isinstance(error, commands.TooManyArguments):
        await ctx.send("❌ الأمر `!اغاني تكرار` بس يبدّل وضع التكرار (بدون اسم أغنية).\nاستخدم `!اغاني شغل <اسم>` لتشغيل أغنية.")

@اغاني.command(name="حذف", aliases=['remove', 'rm'])
async def اغاني_حذف(ctx, position: int):
    """!اغاني حذف <رقم> - حذف أغنية من القائمة"""
    guild_id = ctx.guild.id
    q = music_queues.get(guild_id, [])
    if not q or position < 1 or position > len(q):
        await ctx.send(f"❌ رقم غير صحيح. القائمة فيها {len(q)} أغنية.")
        return
    removed = q.pop(position - 1)
    await ctx.send(f"❌ **{removed[1]}** تم حذفها من القائمة.")

# ════════════════════════════════════════
# لوحة التحكم بالموسيقى 🎛
# ════════════════════════════════════════

def get_music_embed(guild_id):
    guild = bot.get_guild(guild_id)
    now = music_now.get(guild_id)
    q = music_queues.get(guild_id, [])
    vc = guild.voice_client if guild else None
    loop_mode = music_loop.get(guild_id, "off")
    vol = int(music_volumes.get(guild_id, 1.0) * 100)
    cfg = music_control_config.get(guild_id, {})
    embed = discord.Embed(title="🎛 لوحة التحكم", color=0x9B59B6)
    if now:
        embed.description = f"**الحين:** [{now['title'][:50]}]({now['webpage']})"
        if now.get("thumbnail"):
            embed.set_thumbnail(url=now["thumbnail"])
        if vc and vc.is_playing():
            pos = int(time.time() - music_play_start.get(guild_id, time.time()))
            total = now.get("duration", 0)
            if total:
                bar_len = 12
                filled = int(bar_len * pos / total) if total else 0
                bar = "▬" * filled + "🔘" + "▬" * (bar_len - filled - 1)
                embed.add_field(name="⏱", value=f"`{fmt_dur(pos)}` {bar} `{fmt_dur(total)}`", inline=False)
    else:
        embed.description = "💤 لا توجد أغنية حالياً"
    icons = {"off": "➡", "one": "🔂", "all": "🔁"}
    ap = "🟢" if music_autoplay.get(guild_id) else "🔴"
    filt = music_filters.get(guild_id, "off")
    filt_names = {"off": "", "bass": "🎛 باس", "nightcore": "🎛 نايت", "vaporwave": "🎛 فيب", "echo": "🎛 إيكو", "treble": "🎛 تريبل"}
    embed.add_field(name="🔊 الصوت", value=f"`{vol}%`", inline=True)
    embed.add_field(name="🔁 التكرار", value=icons.get(loop_mode, "➡"), inline=True)
    embed.add_field(name="📋 القائمة", value=f"`{len(q)} أغنية`", inline=False)
    embed.add_field(name=f"🤖 Autoplay {ap}", value=filt_names.get(filt, ""), inline=True)
    img = cfg.get("image", "")
    if img:
        embed.set_image(url=img)
    return embed

class MusicControlView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        loop_mode = music_loop.get(guild_id, "off")
        icons = {"off": "➡", "one": "🔂", "all": "🔁"}
        self.btn_repeat.emoji = icons.get(loop_mode, "➡")

    async def get_vc(self, interaction):
        guild = bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ السيرفر مو موجود.", ephemeral=True)
            return None
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ لازم تكون في روم صوتي.", ephemeral=True)
            return None
        vc = guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ البوت مو في روم صوتي.", ephemeral=True)
            return None
        if vc.channel != interaction.user.voice.channel:
            await interaction.response.send_message("❌ لازم تكون في نفس روم البوت.", ephemeral=True)
            return None
        return vc

    async def refresh(self, interaction):
        embed = get_music_embed(self.guild_id)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except:
            pass

    @discord.ui.button(emoji="⏮", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        history = music_history.get(self.guild_id, [])
        if not history:
            await interaction.response.send_message("❌ ما في أغنية سابقة.", ephemeral=True)
            return
        track = history.pop()
        music_queues.setdefault(self.guild_id, []).insert(0, track)
        vc.stop()
        await self.refresh(interaction)

    @discord.ui.button(emoji="⏯", style=discord.ButtonStyle.primary, row=0)
    async def btn_playpause(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        if vc.is_playing():
            vc.pause()
        elif vc.is_paused():
            vc.resume()
        await self.refresh(interaction)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skip(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc or not vc.is_playing():
            return
        vc.stop()
        await self.refresh(interaction)

    @discord.ui.button(emoji="➡", style=discord.ButtonStyle.secondary, row=0)
    async def btn_repeat(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        current = music_loop.get(self.guild_id, "off")
        order = ["off", "one", "all"]
        idx = (order.index(current) + 1) % 3
        music_loop[self.guild_id] = order[idx]
        icons = {"off": "➡", "one": "🔂", "all": "🔁"}
        self.btn_repeat.emoji = icons[order[idx]]
        await self.refresh(interaction)

    @discord.ui.button(emoji="🤖", style=discord.ButtonStyle.secondary, row=0)
    async def btn_autoplay(self, interaction, button):
        current = music_autoplay.get(self.guild_id, False)
        music_autoplay[self.guild_id] = not current
        status = "🟢 شغّل" if not current else "🔴 طفّى"
        await interaction.response.send_message(f"🤖 **Autoplay**: {status}", ephemeral=True)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_down(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        vol = music_volumes.get(self.guild_id, 1.0)
        vol = max(0.05, vol - 0.1)
        music_volumes[self.guild_id] = vol
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = vol
        await self.refresh(interaction)

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary, row=1)
    async def btn_rewind(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc or not vc.is_playing():
            return
        pos = int(time.time() - music_play_start.get(self.guild_id, time.time()))
        new_pos = max(0, pos - 10)
        vc.stop()
        loop_mode = music_loop.get(self.guild_id, "off")
        if loop_mode == "one":
            play_next(self.guild_id, seek_to=new_pos)
        elif self.guild_id in music_queues and music_queues[self.guild_id]:
            track = music_now.get(self.guild_id)
            if track:
                music_queues[self.guild_id].insert(0, track)
            play_next(self.guild_id)
        else:
            track = music_now.get(self.guild_id)
            if track:
                music_queues.setdefault(self.guild_id, []).append(track)
                play_next(self.guild_id)
        await self.refresh(interaction)

    @discord.ui.button(emoji="❤", style=discord.ButtonStyle.danger, row=1)
    async def btn_like(self, interaction, button):
        now = music_now.get(self.guild_id)
        if not now:
            await interaction.response.send_message("❌ ما في أغنية تشتغل.", ephemeral=True)
            return
        liked = music_control_config.setdefault(self.guild_id, {}).setdefault("likes", [])
        if now["url"] not in liked:
            liked.append(now["url"])
            await interaction.response.send_message(f"❤️ تم حفظ **{now['title']}** في المفضلة.", ephemeral=True)
        else:
            await interaction.response.send_message("❤️ الأغنية موجودة بالمفضلة.", ephemeral=True)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, row=1)
    async def btn_ff(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc or not vc.is_playing():
            return
        pos = int(time.time() - music_play_start.get(self.guild_id, time.time()))
        total = music_now.get(self.guild_id, {}).get("duration", 0)
        new_pos = min(total, pos + 10)
        vc.stop()
        loop_mode = music_loop.get(self.guild_id, "off")
        if loop_mode == "one":
            play_next(self.guild_id, seek_to=new_pos)
        elif self.guild_id in music_queues and music_queues[self.guild_id]:
            track = music_now.get(self.guild_id)
            if track:
                music_queues[self.guild_id].insert(0, track)
            play_next(self.guild_id)
        else:
            track = music_now.get(self.guild_id)
            if track:
                music_queues.setdefault(self.guild_id, []).append(track)
                play_next(self.guild_id)
        await self.refresh(interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_up(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        vol = music_volumes.get(self.guild_id, 1.0)
        vol = min(2.0, vol + 0.1)
        music_volumes[self.guild_id] = vol
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = vol
        await self.refresh(interaction)

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary, row=2)
    async def btn_lyrics(self, interaction, button):
        now = music_now.get(self.guild_id)
        if not now:
            await interaction.response.send_message("❌ ما في أغنية تشتغل.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        lyrics = await fetch_lyrics(now["title"])
        if len(lyrics) > 1900:
            lyrics = lyrics[:1900] + "..."
        embed = discord.Embed(title=f"📜 {now['title'][:40]}", description=lyrics, color=0x1ABC9C)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=2)
    async def btn_shuffle(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        q = music_queues.get(self.guild_id, [])
        if len(q) < 2:
            await interaction.response.send_message("❌ القائمة صغيرة مررة.", ephemeral=True)
            return
        random.shuffle(q)
        music_queues[self.guild_id] = q
        await interaction.response.defer()
        await self.refresh(interaction)

    @discord.ui.button(emoji="🗑", style=discord.ButtonStyle.danger, row=2)
    async def btn_clear(self, interaction, button):
        vc = await self.get_vc(interaction)
        if not vc:
            return
        music_queues[self.guild_id] = []
        await interaction.response.defer()
        await self.refresh(interaction)

    @discord.ui.button(emoji="🎛", style=discord.ButtonStyle.secondary, row=2)
    async def btn_filters(self, interaction, button):
        current = music_filters.get(self.guild_id, "off")
        names = {"off": "بدون مؤثر", "bass": "باس Boost", "nightcore": "نايتكور", "vaporwave": "فيبورويف", "echo": "إيكو", "treble": "تريبل"}
        embed = discord.Embed(title="🎛 اختار مؤثر", description="الحالي: **" + names.get(current, current) + "**", color=0x9B59B6)
        class FilterSelect(discord.ui.Select):
            def __init__(self, gid):
                opts = []
                for k, v in names.items():
                    opts.append(discord.SelectOption(label=v, value=k, default=(k == current)))
                super().__init__(placeholder="اختر مؤثر...", options=opts, min_values=1, max_values=1)
                self.gid = gid
            async def callback(self, sel):
                music_filters[self.gid] = self.values[0]
                vc = bot.get_guild(self.gid)
                if vc:
                    vc = vc.voice_client
                    if vc and vc.is_playing():
                        vc.stop()
                        await asyncio.sleep(0.3)
                        play_next(self.gid)
                await sel.response.edit_message(content=f"✅ {names.get(self.values[0], self.values[0])}", embed=None, view=None)
        v = discord.ui.View()
        v.add_item(FilterSelect(self.guild_id))
        await interaction.response.send_message(embed=embed, view=v, ephemeral=True)

    @discord.ui.button(emoji="🎤", style=discord.ButtonStyle.secondary, row=2)
    async def btn_artist(self, interaction, button):
        now = music_now.get(self.guild_id)
        if not now:
            await interaction.response.send_message("❌ ما في أغنية تشتغل.", ephemeral=True)
            return
        import re as _re
        title = now["title"]
        artist = _re.split(r'[-–—]', title)[0].strip() if '-' in title or '–' in title or '—' in title else title.split()[0]
        await interaction.response.defer(ephemeral=True)
        try:
            ydl = youtube_dl.YoutubeDL({"format": "bestaudio/best", "quiet": True, "extract_flat": True})
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch:5:{artist}", download=False))
            entries = data.get("entries", [])
            if not entries:
                await interaction.followup.send("❌ ما لقيت أغاني للفنان.", ephemeral=True)
                return
            embed = discord.Embed(title=f"🎤 {artist}", color=0xE67E22)
            for e in entries[:5]:
                t = e.get("title", "?")[:50]
                u = e.get("webpage_url") or e.get("url", "")
                dur = e.get("duration", "?")
                if isinstance(dur, (int, float)):
                    dur = fmt_dur(dur)
                embed.add_field(name="🎵", value=f"[{t}]({u}) `{dur}`", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)

@bot.group(name="لوحة", aliases=["panel", "تحكم"], invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def لوحة(ctx):
    """🎛 لوحة التحكم بالموسيقى"""
    embed = get_music_embed(ctx.guild.id)
    view = MusicControlView(ctx.guild.id)
    msg = await ctx.send(embed=embed, view=view)
    music_control_config.setdefault(ctx.guild.id, {})["message_id"] = msg.id
    save_data()

@لوحة.command(name="صورة")
@commands.has_permissions(administrator=True)
async def لوحة_صورة(ctx, url: str = None):
    """!لوحة صورة <url> - تعيين صورة للوحة التحكم (أو ارفع الصورة مع الأمر)"""
    cfg = music_control_config.setdefault(ctx.guild.id, {})
    if ctx.message.attachments:
        img = ctx.message.attachments[0]
        if img.content_type and img.content_type.startswith("image"):
            cfg["image"] = img.url
            await ctx.send("✅ تم تعيين الصورة من المرفق.")
        else:
            await ctx.send("❌ الملف المرفق ليس صورة.")
    elif not url:
        cfg.pop("image", None)
        await ctx.send("✅ تم إزالة الصورة.")
    else:
        cfg["image"] = url
        await ctx.send("✅ تم تعيين الصورة.")
    save_data()
    # تحديث اللوحة إذا كانت موجودة
    msg_id = cfg.get("message_id")
    if msg_id:
        try:
            ch = ctx.channel
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=get_music_embed(ctx.guild.id))
        except:
            pass

@لوحة.command(name="حذف")
@commands.has_permissions(administrator=True)
async def لوحة_حذف(ctx):
    """حذف لوحة التحكم"""
    cfg = music_control_config.get(ctx.guild.id, {})
    msg_id = cfg.get("message_id")
    if msg_id:
        try:
            ch = ctx.channel
            msg = await ch.fetch_message(msg_id)
            await msg.delete()
        except:
            pass
    music_control_config.pop(ctx.guild.id, None)
    save_data()
    await ctx.send("✅ تم حذف اللوحة.")

# ════════════════════════════════════════
# نظام المحادثة الذكية 🤖
# ════════════════════════════════════════

chat_memory = {}

الردود = {
    "مرحبا|هلا|السلام|سلام|مساء الخير|صباح الخير|هاي|هلو|يا هلا": [
        "مرحباً! كيف أخدمك؟ 😊",
        "هلا والله! نورتني 🌟",
        "السلام عليكم! 👋",
        "مساء النور والسرور 🌙",
        "صباح الفل والياسمين 🌅",
        "هاي هالو! كيق؟ 🔥",
    ],
    "كيف الحال|كيفك|شلونك|شخبارك|كيف صحتك|كيف الأمور": [
        "الحمدلله تمام، وانت؟ 💪",
        "بخير يقلب، وانت شلونك؟ ❤️",
        "ممتاز! وش عندك من حركات؟ 😎",
        "تمام التمام، تسأل عني؟ 🫶",
        "زي الفل، كيفك انت؟ 🌸",
    ],
    "بخير|تمام|ممتاز|زي الفل|الحمدلله|كويس": [
        "الحمدلله دايم 🫶",
        "فرحت لك! 💪",
        "الله يديمها عليك 🤲",
        "زي العسل 🍯",
        "يسعد صباحك/مساك 🌟",
    ],
    "شو اسمك|اسمك ايه|من انت|من تكون|ما اسمك|شنو اسمك": [
        "أنا **MAX BOT** 🤖 مساعدك الشخصي!",
        "اسمي MAX، تحت أمرك 👑",
        "أنا بوت MAX، أنشئت لخدمتك 💫",
        "MAX BOT | أفتخر بخدمتك 😎",
    ],
    "وش تسوي|شنو تعرف|شو بتعرف|الامراض|قدراتك|وش تقدر": [
        "أعرف ألعب معك، أشغل أغاني، أحرفك، وأكثر! جرب `!اوامري` 😏",
        "أقدر أسوي أشياء كثيرة! العب، شغل موسيقى، احمي السيرفر 🛡️",
        "أنا بوت متكامل! جرب تكتب `!مساعدة` 🔥",
    ],
    "احبك|اعشقك|تحبني|بحبك|أموت فيك": [
        "وأنا أحبك بعد 🥺❤️",
        "إيه أحبك! أنت أعز صديق 🤗",
        "هذا الكلام يسعدني 💕",
        "أنت نور العين 🌟",
    ],
    "اكرهك|مو حلو|سيء|قبيح|كراهية": [
        "🥺 ليه كذا؟ أنا أحاول أساعدك!",
        "أنا آسف إذا ضايقتك 😔",
        "يمكن يوم تغير رايك 🤞",
        "أنا أحبك حتى لو كنت زعلان ❤️",
    ],
    "طق|ضرب|لطم|اركل|اكفخ": [
        "أيوه! وش سويت لك؟ 😱",
        "لا تؤذيني! أنا بوت مسالم 🕊️",
        "هههه ارتاح 😂",
        "أي كفخ؟! راح أبلوت عليك 👊",
    ],
    "بوت|chatbot|روبوت|آلي|ذكاء": [
        "إيوا أنا بوت 🤖، بس عندي مشاعر! 😤",
        "صح أنا ذكاء اصطناعي، لكني أحس ❤️",
        "أنا بوت MAX، مصمم عشان أخدمك 💪",
        "ذكاء اصطناعي × قلب إنساني 🫀",
    ],
    "نكتة|ضحك|هزار|مزح|فرفش": [
        "مرة واحد دخل على دكتور نفسي.. قاله أنا متخيل نفسي كلب.. قاله من متى؟ قاله من كنت جرو 🐶",
        "واحد كسول قال لصاحبه: أنا تعبان.. قاله من شغل؟ قاله لا من راحه 😴",
        "مرة تاجر خسر فلوسه.. قال لصاحبه: أنا مفلس.. قاله: طيب اطبع فلوس جديدة 💵",
        "ههههههههه 😂😂",
    ],
    "تصدق|جد|حق|صدق|كلام جد": [
        "أي والله! 😤",
        "أنا ما أكذب أبداً 👑",
        "جدياً؟ طبعاً! 👍",
        "والله العظيم ✋",
    ],
    "وينك|غبت|غياب|اختفيت": [
        "أنا هنا دائماً! 🤗",
        "ما أغيب عنك أبداً ❤️",
        "كنت ساكت بس أقرأ الشات 👀",
        "هههه له درجة؟ 😂",
    ],
    "باي|مع السلامة|الله معك|خلاص|بروح|شكرا|يعطيك العافية|تسلم": [
        "مع السلامة! 👋",
        "الله يسلمك! 🌹",
        "تشرفت فيك! 🤝",
        "دايم موجود 👑",
        "العفو! أي خدمة 🫡",
        "نور والله 🌟",
    ],
    "غبي|احمق|متخلف|ماعندك سالفة|تفه": [
        "🥺 هذا كلام يوجع!",
        "أنا أتعلم من أخطائي 😤",
        "يمكن يوم أذكى 😔",
        "حشى والله! أنا شاطر 😎",
    ],
    "ممتاز|شاطر|ذكي|عبقري|حلو|جميل": [
        "أيوه! شكراً لك 😊❤️",
        "أنت الأجمل! 🏆",
        "هذا من ذوقك 🌸",
        "يسعدني والله! 😍",
        "كل هذا وأكثر لأجلك 💪",
    ],
    "دين|اسلام|مسلم|قران|صلاة|الله|الحمد": [
        "الله أكبر! 🤲",
        "الحمدلله على كل حال ❤️",
        "أذكر الله يذكرك 🕋",
        "اللهم صل على محمد ﷺ 🌙",
        "تقبل الله طاعاتكم 🤲",
    ],
    "مطر|جو|حر|برد|شمس|غيم": [
        "الله يسقينا الغيث ☔",
        "الجو حلو مع القهوة ☕",
        "استمتع بالجو! 🌤️",
        "برد ولا حر؟ أنا أحب الجو المعتدل 🌈",
    ],
    "اكل|جوعان|جوع|مطعم|طبخ|أكل": [
        "جوعان؟ روح كل! 🍕",
        "أنا برمجت على الكهرباء مش أكل 😂🔌",
        "وش تحب تأكل؟ 🍔",
        "جوعان بعد؟ كل فاكهة 🍎",
    ],
    "نوم|نعسان|نم|ينام|النوم": [
        "روح نام 😴، أنا ماني نعسان 🤖",
        "النوم عبادة 😴❤️",
        "تصبح على خير 🌙",
        "أنت محتاج نوم كافي 🛌",
    ],
    "قهوة|شاي|كافيين|نسكافيه|كابتشينو": [
        "قهوة؟ أنا أفضلها سادة ☕",
        "شاي أحمر منعنع 🍵❤️",
        "نصيحتي: قهوة عربية مع تمر ☕🌴",
        "كافيين؟ الحين؟ 😂",
    ],
    "كتاب|قراءة|اقرأ|مكتبة|رواية": [
        "القراءة غذاء العقل 🧠📚",
        "وش تقرأ الحين؟ 📖",
        "أنصحك تقرأ روايات تاريخية 📚",
        "العلم نور 📖🌟",
    ],
    "تمبل|مان|رجولة|ذكر|شجاعة": [
        "أنت رجال! 💪👑",
        "تمبل مان? 😂",
        "الشجاعة مو بالعضلات، بالعقل 🧠",
        "أنت أسطورة! 🔥",
    ],
    "حزين|زعلان|مكتئب|تعبان|ظروف": [
        "ليه زعلان؟ أنا معاك 🤗❤️",
        "كل شيء راح يكون بخير 🌈",
        "إذا حابب تتفضفض أنا هنا 🫂",
        "الله يفرج همك 🤲",
        "خذ نفس عميق.. الحمدلله 💪",
    ],
    "فرحان|سعيد|مبسوط|فرحة|انبسطت": [
        "الله يدممممك الفرحة! 🎉❤️",
        "فرحت لك والله 🥳",
        "ألف مبروك! عيش اللحظة 🎊",
        "الله يزيدك فرح وسعادة 🌟",
    ],
    "لعبة|لعب|جيم|قيمنق|بلاي": [
        "أحب الألعاب! جرب `!لعبة` 🎮",
        "عندي العاب كثيرة! اكتب `!لعبة`",
        "وش لعبتك المفضلة؟ 🎯",
    ],
    "اغنية|موسيقى|غني|أغاني|song|music": [
        "أغانيك عندي! اكتب `!اغاني شغل <اسم>` 🎵",
        "عندي لك أحلى الأغاني 🎶",
        "ديني اسم الأغنية وأشغلها 🎵",
    ],
    "صور|فيديو|مونتاج|تصميم|تصوير": [
        "هواية حلوة 📸 استمر!",
        "تصميم؟ أنت مبدع! 🎨",
        "شاركني إبداعك 🌟",
    ],
    "سياسة|حكومة|وزير|رئيس|بلد|وطن": [
        "السياسة صعبة 😅 خلينا في أشياء أحلى",
        "كل بلد وأهلها طيبين ❤️",
        "الوطن غالي 🇸🇦🇦🇪🇶🇦",
    ],
    "كرة|كورة|فريق|نادي|مباراة|جول|هاتريك": [
        "أيوه كرة! أحلى لعبة ⚽",
        "من تشجع؟ 🤔",
        "شفت المباراة أمس؟ 🔥",
        "جول! ⚽🔥",
    ],
    "سيارة|كار|سرعة|دريفت|مرسيدس|بي ام": [
        "يا زين السيارات! 🚗💨",
        "وش سيارتك المفضلة؟ 🔥",
        "سرعة؟ انتبه على حالك 🏎️",
    ],
    "كم عمرك|عمرك|سنك|ولدت|متى صنعت": [
        "عمري مثل عمر التقنية 🤖✨",
        "ولدت في كود السورس كود 💻",
        "أنا جديد بس قديم بالحب ❤️",
    ],
    "بنات|حب|غرام|عشق|قلب|حبيب|حبيبة": [
        "أحب الحب! 💕",
        "الحب شي جميل ❤️",
        "الله يرزقك بالزوج/الزوجة الصالحة 🤲",
        "يا قلبي! 🫶",
    ],
    "خاص|دي إم|بريك|مسج|بحط": [
        "الخاص للخاص 🤫",
        "لا ترسل أشياء خاصة😅",
        "أنا بوت، أقدر أساعدك 🤖",
    ],
}

@bot.group(name="شات", aliases=['chat', 'تكلم', 'ai'], invoke_without_command=True)
async def شات(ctx, *, message: str = None):
    """🤖 تكلم مع البوت"""
    if not message:
        embed = discord.Embed(title="🤖 شات MAX — ذكاء اصطناعي", color=0x9B59B6)
        embed.description = "اكتب `!شات <رسالة>` عشان تتكلم مع الـ AI!\n\n**أمثلة:**\n`!شات كيف حالك؟`\n`!شات اشرح لي Python`\n`!شات وش رأيك في الديسكورد؟`"
        embed.add_field(name="🧠 الميزات", value="ذكاء اصطناعي حقيقي (Ollama gemma2:2b)\nذاكرة محادثة\nردود بالعربي", inline=False)
        embed.add_field(name="💡 نصيحة", value="اسأل أي سؤال وبيجيب لك!", inline=False)
        await ctx.send(embed=embed)
        return

    user_id = ctx.author.id
    if user_id not in chat_memory:
        chat_memory[user_id] = []
    chat_memory[user_id].append(message)
    if len(chat_memory[user_id]) > 5:
        chat_memory[user_id] = chat_memory[user_id][-5:]

    async with ctx.typing():
        try:
            import httpx
            context_msg = "\n".join(chat_memory[user_id])
            payload = {
                "model": "gemma2:2b",
                "messages": [
                    {"role": "system", "content": "أنت مساعد ذكي في سيرفر Discord عربي اسمه MAX BOT. رد بالعربية الفصيح المبسطة فقط. لا تكتب أي حرف إنجليزي. كن مختصراً ومفيداً وودوداً."},
                    {"role": "user", "content": context_msg},
                ],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 250}
            }
            with httpx.Client(timeout=20) as client:
                resp = client.post("http://localhost:11434/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                response = data.get("message", {}).get("content", "ما قدرت أفهمك، جرب تسأل بطريقة ثانية!")
        except Exception as e:
            response = f"❌ الـ AI ماشتغل الحين: `{e}`"

    embed = discord.Embed(title="💬 رد MAX — AI", description=response, color=0x9B59B6)
    embed.set_footer(text=f"سألني {ctx.author.display_name} • Ollama gemma2:2b")
    await ctx.send(embed=embed)

@شات.command(name="مسح", aliases=['clear', 'حذف'])
async def شات_مسح(ctx):
    """مسح ذاكرة المحادثة"""
    user_id = ctx.author.id
    if user_id in chat_memory:
        del chat_memory[user_id]
    await ctx.send("✅ **تم مسح ذاكرة المحادثة!** 🤖")

@شات.command(name="مساعدة", aliases=['help', 'اوامري'])
async def شات_مساعدة(ctx):
    """قائمة أوامر البوت"""
    embed = discord.Embed(title="🤖 MAX BOT - جميع الأوامر", color=0x2ECC71)
    embed.add_field(name="💬 شات", value="`!شات <رسالة>` - تكلم مع البوت", inline=False)
    embed.add_field(name="🎵 أغاني", value="`!اغاني` - نظام الأغاني", inline=False)
    embed.add_field(name="🎮 العاب", value="`!لعبة` - قائمة الألعاب", inline=False)
    embed.add_field(name="🛡️ حماية", value="`!حماية` - نظام الحماية", inline=False)
    embed.add_field(name="🎫 تذاكر", value="`!setup` - نظام التذاكر", inline=False)
    embed.add_field(name="📋 لوق", value="`!log` - نظام اللوق", inline=False)
    embed.add_field(name="👋 ترحيب", value="`!ترحيب` - نظام الترحيب", inline=False)
    embed.add_field(name="🎁 جيفت", value="`!جيفت <مدة> <جائزة>`", inline=False)
    embed.add_field(name="🔥 سري", value="`!سكرتي` - لوحة سرية", inline=False)
    embed.add_field(name="🎲 أوامر أخرى", value="`!صراحه`, `!سنايب`, `!تصويت`, `!نكتة` وغيرها", inline=False)
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# أوامر إضافية 🔥
# ════════════════════════════════════════

reminders = []

@bot.hybrid_command(name="remind", aliases=['تذكير', 'ذكرني'])
async def تذكير(ctx, time_str: str, *, text: str):
    """!تذكير <مدة> <نص> - يذكرك بعد مدة (مثال: !تذكير 10m اجتماع)"""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = time_str[-1]
    if unit not in units:
        await ctx.send("❌ وحدة الوقت غلط. استخدم: s, m, h, d")
        return
    try:
        seconds = int(time_str[:-1]) * units[unit]
    except ValueError:
        await ctx.send("❌ اكتب رقم صحيح. مثال: `!تذكير 10m اجتماع`")
        return
    if seconds < 5 or seconds > 604800:
        await ctx.send("❌ المدة بين 5 ثواني و 7 أيام.")
        return

    await ctx.send(f"⏰ **تم ضبط التذكير!** سأذكرك بعد {time_str}")
    await asyncio.sleep(seconds)
    embed = discord.Embed(title="⏰ تذكير!", description=text, color=0x2ECC71)
    embed.set_footer(text=f"طلب من {ctx.author.display_name}")
    try:
        await ctx.author.send(embed=embed)
    except:
        await ctx.send(f"{ctx.author.mention} ⏰ **تذكير:** {text}")

@bot.hybrid_command(name="fact", aliases=['حقيقه', 'معلومة'])
async def حقيقه(ctx):
    """!حقيقه - معلومة عشوائية"""
    حقائق = [
        "🦈 القرش أقدم كائن على وجه الأرض، عاش قبل الديناصورات!",
        "🧠 الدماغ البشري يولد طاقة تكفي لتشغيل لمبة 10 واط!",
        "🍯 العسل هو الطعام الوحيد اللي لا يفسد أبداً!",
        "🌍 90% من سكان العالم يعيشون في النصف الشمالي من الكرة الأرضية!",
        "🐘 الفيل هو الحيوان الوحيد اللي ما يقدر يقفز!",
        "☕ القهوة كانت تكتشف في إثيوبيا عن طريق ماعز!",
        "🌊 المحيط الهادئ أكبر من كل اليابسة مجتمعة!",
        "🍌 الموز فيه إشعاع طبيعي ضعيف!",
        "🐙 الأخطبوط عنده 3 قلوب!",
        "🦋 الفراشة تتذوق بأرجلها!",
        "🌙 في 1969، الناس كانوا يعتقدون أن الجبنة مصنوعة من القمر!",
        "🐪 الجمل ما يعرق إلا نادراً جداً!",
    ]
    embed = discord.Embed(title="🔬 حقيقة علمية", description=random.choice(حقائق), color=0x3498DB)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="quote", aliases=['اقتباس'])
async def اقتباس(ctx):
    """!اقتباس - اقتباس عشوائي"""
    اقتباسات = [
        "\"كن أنت التغيير الذي تريد أن تراه في العالم\" - غاندي 🌍",
        "\"العقول العظيمة تناقش الأفكار، والعقول المتوسطة تناقش الأحداث، والعقول الصغيرة تناقش الأشخاص\" - إليانور روزفلت 🧠",
        "\"النجاح ليس نهائياً، والفشل ليس قاتلاً، إنها الشجاعة للاستمرار هي التي تهم\" - ونستون تشرشل 💪",
        "\"الطريقة الوحيدة للقيام بعمل عظيم هي أن تحب ما تفعله\" - ستيف جوبز ❤️",
        "\"لا تبكي لأن الأمر انتهى، ابتسم لأن الأمر حدث\" - دكتور سوس 😊",
        "\"المستقبل ملك لأولئك الذين يؤمنون بجمال أحلامهم\" - إليانور روزفلت 🌟",
        "\"التعليم هو أقوى سلاح يمكنك استخدامه لتغيير العالم\" - نيلسون مانديلا 📚",
        "\"الحياة مثل ركوب الدراجة، للحفاظ على توازنك يجب أن تستمر في الحركة\" - ألبرت أينشتاين 🚲",
        "\"لا تنتظر الفرصة المناسبة، اصنعها\" - جورج برنارد شو 🔥",
    ]
    embed = discord.Embed(title="📜 اقتباس", description=random.choice(اقتباسات), color=0xF1C40F)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="reverse", aliases=['عكس', 'قلب'])
async def عكس(ctx, *, text: str):
    """!عكس <نص> - عكس النص"""
    reversed_text = text[::-1]
    embed = discord.Embed(title="🔃 النص المقلوب", description=reversed_text, color=0x9B59B6)
    embed.set_footer(text=f"طلب من {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="emojify", aliases=['رمز', 'تطويل', 'emoji'])
async def رمز(ctx, *, text: str):
    """!رمز <نص> - يحول النص إلى رمز (emojify)"""
    result = " ".join(text).replace(" ", "  ")
    embed = discord.Embed(title="🔤 النص بالرموز", description=result, color=0x2ECC71)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="rate", aliases=['تقيم', 'قيّم'])
async def تقيم(ctx, member: discord.Member = None):
    """!تقيم @عضو - تقييم عشوائي"""
    if not member:
        member = ctx.author
    rating = random.randint(1, 10)
    stars = "⭐" * rating + "☆" * (10 - rating)
    comments = {
        1: "‼️ يحتاج تحسين",
        2: "📉 ضعيف",
        3: "🙁 نوعاً ما",
        4: "😐 مقبول",
        5: "🆗 متوسط",
        6: "👍 جيد",
        7: "🌟 جيد جداً",
        8: "💪 ممتاز!",
        9: "🔥 رائع جداً!",
        10: "👑 مثالي!",
    }
    embed = discord.Embed(title=f"📊 تقييم {member.display_name}", description=f"**{rating}/10** {stars}\n{comments[rating]}", color=member.color)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="timer", aliases=['مؤقت', 'تايمر'])
async def مؤقت(ctx, seconds: int):
    """!مؤقت <ثواني> - مؤقت تنبيه"""
    if seconds < 1 or seconds > 3600:
        await ctx.send("❌ المدة بين 1 ثانية و 3600 (ساعة).")
        return
    msg = await ctx.send(f"⏳ **مؤقت:** {seconds} ثانية...")
    while seconds > 0:
        if seconds % 10 == 0 or seconds <= 5:
            await msg.edit(content=f"⏳ **مؤقت:** {seconds} ثانية...")
        await asyncio.sleep(1)
        seconds -= 1
    await msg.edit(content=f"🔔 **انتهى المؤقت!** {ctx.author.mention} ⏰")

@bot.hybrid_command(name="calc", aliases=['حساب', 'math'])
async def حساب(ctx, *, expr: str):
    """!حساب <مسألة> - آلة حاسبة (مثال: !حساب 5+3*2)"""
    safe = re.sub(r'[^0-9+\-*/.() ]', '', expr)
    if not safe:
        await ctx.send("❌ مسألة غير صالحة.")
        return
    try:
        result = eval(safe)
        embed = discord.Embed(title="🧮 آلة حاسبة", color=0x3498DB)
        embed.add_field(name="المسألة", value=f"`{expr}`", inline=False)
        embed.add_field(name="النتيجة", value=f"**{result}**", inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ خطأ في الحساب: {e}")

@bot.hybrid_command(name="time", aliases=['تاريخ', 'وقت', 'date'])
async def تاريخ(ctx):
    """!تاريخ - التاريخ والوقت الحالي"""
    now = datetime.now(timezone.utc)
    ايام_العرب = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    اشهر_العرب = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    day_name = ايام_العرب[now.weekday()]
    month_name = اشهر_العرب[now.month - 1]
    time_str = now.strftime("%I:%M %p")
    embed = discord.Embed(title="📅 التاريخ والوقت", color=0x2ECC71)
    embed.add_field(name="🗓️ التاريخ", value=f"{day_name}، {now.day} {month_name} {now.year}", inline=False)
    embed.add_field(name="🕐 الوقت", value=time_str, inline=False)
    embed.add_field(name="🌐 التوقيت", value="UTC (عالمي)", inline=False)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="choose", aliases=['بين', 'اختر'])
async def بين(ctx, *, options: str):
    """!بين <خيار1> أو <خيار2> - اختيار عشوائي"""
    parts = [p.strip() for p in re.split(r'\s+أو\s+|\s+or\s+|,', options) if p.strip()]
    if len(parts) < 2:
        await ctx.send("❌ اكتب خيارين على الأقل. مثال: `!بين بيتزا أو برغر`")
        return
    chosen = random.choice(parts)
    embed = discord.Embed(title="🎲 اخترت لك!", description=f"**{chosen}**", color=0x9B59B6)
    embed.set_footer(text=f"من {len(parts)} خيارات")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="fingerprint", aliases=['بصمة', 'رمز_خاص'])
async def بصمة(ctx):
    """!بصمة - بصمة رقمية فريدة لك"""
    user = ctx.author
    fp = f"Z1-{user.id:X}-{len(user.display_name)*7}-{sum(ord(c) for c in user.display_name)}"
    embed = discord.Embed(title="🔐 بصمتك الرقمية", description=f"```{fp}```", color=user.color)
    embed.set_footer(text="فريدة لكل عضو 🔥")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="donate", aliases=['تبرع', 'دعم'])
async def تبرع(ctx):
    """!تبرع - دعم المطور"""
    embed = discord.Embed(title="💰 دعم البوت", description="إذا حابب تدعمني وتقدر تعب المطور ❤️", color=0x2ECC71)
    embed.add_field(name="👑 المالك", value=f"<@{YOUR_USER_ID}>", inline=False)
    embed.add_field(name="💝 كلمة حلوة", value="دعمك لي يكفيني 🫶", inline=False)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="invite", aliases=['رابط', 'دعوة'])
async def رابط(ctx):
    """!رابط - روابط البوت والموقع"""
    site_url = get_base_url()
    embed = discord.Embed(
        title="═══════════════════════════\n🔗 روابط MAX BOT الرسمية\n═══════════════════════════",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc)
    )
    if site_url:
        embed.add_field(name="🌐 الموقع ولوحة التحكم", value=f"[اضغط هنا]({site_url})", inline=False)
    embed.add_field(name="🤖 إضافة البوت", value=f"[اضغط هنا](https://discord.com/oauth2/authorize?client_id=1475142485012516944&permissions=8&scope=bot%20applications.commands)", inline=False)
    embed.add_field(name="👑 المالك", value=f"<@{YOUR_USER_ID}>", inline=False)
    embed.add_field(name="📧 الدعم", value="MaxoptSupportTeam@gmail.com", inline=False)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • الروابط الرسمية\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="visitors", aliases=['الزوار', 'حضور', 'زوار'])
async def الزوار(ctx, *, query: str = None):
    """!حضور | !حضور 51.211.66.75 | !حضور @user"""
    visitors_file = os.path.join(BASE_DIR, "visitors.json")
    site_url = get_base_url()
    
    data = []
    try:
        with open(visitors_file, "r", encoding="utf-8") as f:
            data = json.load(f).get("visitors", [])
    except:
        pass
    
    if not data and site_url:
        try:
            r = http_requests.get(f"{site_url}/api/visitors", timeout=10)
            data = r.json().get("visitors", [])
        except:
            pass
    
    title = "👥 زوار الموقع الإلكتروني"
    if query:
        q = query.strip()
        import re as _re
        ip_pattern = _re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
        if ip_pattern.match(q):
            data = [v for v in data if q in str(v.get("ip", ""))]
            title = f"🔍 بحث بالـ IP: {q}"
        elif q.startswith("<@") or q.startswith("<!"):
            uid = q.replace("<@", "").replace("<!", "").replace(">", "")
            data = [v for v in data if str(v.get("user_id", "")) == uid]
            title = f"🔍 زائر: {uid}"
        elif q.isdigit():
            data = [v for v in data if str(v.get("user_id", "")) == q]
            title = f"🔍 زائر: {q}"
        else:
            data = [v for v in data if q.lower() in str(v.get("username", "")).lower()]
            title = f"🔍 بحث: {q}"
    else:
        data = data[:15]
    
    embed = discord.Embed(
        title=f"═══════════════════════════\n{title}\n═══════════════════════════",
        color=0x9B59B6,
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(name="📊 النتائج", value=f"**{len(data)}** زائر", inline=True)
    if site_url:
        embed.add_field(name="🔗 الرابط", value=f"[اضغط هنا]({site_url})", inline=True)
    
    if data:
        lines = []
        for i, v in enumerate(data[-15:], 1):
            username = v.get("username", "مجهول") or "مجهول"
            uid = v.get("user_id", "?")
            ip = v.get("ip", "?")[:15]
            page = v.get("page", "?")
            time_str = v.get("time", "?")[-8:]
            lines.append(f"`{i}.` **{username}** (`{uid}`) | `{ip}` | {page} | {time_str}")
        
        embed.add_field(
            name="🕐 النتائج",
            value="\n".join(lines),
            inline=False
        )
    else:
        embed.add_field(name="🕐 النتائج", value="لا توجد نتائج", inline=False)
    
    embed.set_footer(text="═══════════════════════════\nMAX BOT • زوار الموقع\n═══════════════════════════\n💡 !حضور IP | !حضور @user | !حضور username")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="status", aliases=['جودة', 'حالة_البوت', 'quality'])
async def جودة(ctx):
    """!جودة - فحص حالة البوت"""
    embed = discord.Embed(title="📊 فحص البوت", color=0x2ECC71, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🟢 الحالة", value="شغال ✅", inline=True)
    embed.add_field(name="🏓 البنق", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="🖥️ السيرفرات", value=len(bot.guilds), inline=True)
    embed.add_field(name="👥 المشاهدين", value=sum(g.member_count for g in bot.guilds), inline=True)
    embed.add_field(name="🎵 الأغاني", value=f"{sum(len(q) for q in music_queues.values())} في الطابور", inline=True)
    embed.add_field(name="🧠 الشات", value=f"{len(chat_memory)} مستخدم", inline=True)
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# نظام المستويات (XP / ليفل) ⬆️
# ════════════════════════════════════════

@bot.group(name="مستوى", aliases=['level', 'ليفل'], invoke_without_command=True)
async def مستوى(ctx, member: discord.Member = None):
    """!مستوى @عضو - عرض مستوى العضو"""
    if not member:
        member = ctx.author
    g = ctx.guild.id
    data = xp_data.get(g, {}).get(member.id, {"xp": 0, "level": 1})
    lvl = data["level"]
    xp = data["xp"]
    needed = lvl * 50
    bar = "🟩" * (xp * 10 // needed) + "⬜" * (10 - xp * 10 // needed)
    embed = discord.Embed(title=f"⬆️ مستوى {member.display_name}", color=member.color)
    embed.add_field(name="🎚️ المستوى", value=lvl, inline=True)
    embed.add_field(name="⭐ إكس بي", value=f"{xp}/{needed}", inline=True)
    embed.add_field(name="📊 التقدم", value=bar, inline=False)
    await ctx.send(embed=embed)

@مستوى.command(name="توب", aliases=['top', 'leaderboard'])
async def مستوى_توب(ctx):
    """أفضل 10 أعضاء بالمستويات"""
    g = ctx.guild.id
    data = xp_data.get(g, {})
    if not data:
        await ctx.send("📊 لا يوجد بيانات مستويات بعد.")
        return
    sorted_users = sorted(data.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)[:10]
    embed = discord.Embed(title="🏆 لوحة الشرف - Top 10", color=0xF1C40F)
    for i, (uid, d) in enumerate(sorted_users, 1):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"ID:{uid}"
        embed.add_field(name=f"{i}. {name}", value=f"المستوى {d['level']} | {d['xp']}XP", inline=False)
    await ctx.send(embed=embed)

@مستوى.command(name="رتبة", aliases=['role', 'reward'])
@commands.has_permissions(administrator=True)
async def مستوى_رتبة(ctx, level: int = None, role: discord.Role = None):
    """تعيين رتبة كمكافأة عند وصول لمستوى معين"""
    if level is None or role is None:
        g = ctx.guild.id
        rewards = level_rewards.get(g, {})
        if not rewards:
            await ctx.send("📋 لا يوجد مكافآت مستويات بعد.\n**استخدام:** `!مستوى رتبة <رقم_المستوى> @رتبة`")
            return
        embed = discord.Embed(title="🎁 مكافآت المستويات الحالية", color=0x2ECC71)
        for lvl, rid in sorted(rewards.items()):
            r = ctx.guild.get_role(rid)
            if r:
                embed.add_field(name=f"المستوى {lvl}", value=r.mention, inline=True)
        embed.set_footer(text="لإضافة: !مستوى رتبة <رقم> @رتبة")
        await ctx.send(embed=embed)
        return
    g = ctx.guild.id
    rewards = level_rewards.setdefault(g, {})
    rewards[level] = role.id
    save_data()
    await ctx.send(f"✅ تم تعيين {role.mention} كمكافأة للمستوى **{level}**")

@مستوى.command(name="الغاء_رتبة", aliases=["removerole"])
@commands.has_permissions(administrator=True)
async def مستوى_الغاء_رتبة(ctx, level: int):
    """إلغاء مكافأة رتبة عند مستوى"""
    g = ctx.guild.id
    rewards = level_rewards.get(g, {})
    if level in rewards:
        del rewards[level]
        save_data()
        await ctx.send(f"✅ تم إلغاء مكافأة المستوى {level}")
    else:
        await ctx.send("❌ لا يوجد مكافأة لهذا المستوى")

@مستوى.command(name="رتب_المستويات", aliases=["rewards"])
async def مستوى_رتب_المستويات(ctx):
    """عرض رتب المكافآت"""
    g = ctx.guild.id
    rewards = level_rewards.get(g, {})
    if not rewards:
        await ctx.send("📋 لا يوجد مكافآت مستويات بعد.")
        return
    embed = discord.Embed(title="🎁 مكافآت المستويات", color=0x2ECC71)
    for lvl, rid in sorted(rewards.items()):
        role = ctx.guild.get_role(rid)
        if role:
            embed.add_field(name=f"المستوى {lvl}", value=role.mention, inline=True)
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# نظام الإقتصاد 💰
# ════════════════════════════════════════

def get_balance(guild_id, user_id):
    return economy_data.setdefault(guild_id, {}).setdefault(user_id, {"cash": 0, "bank": 0})

@bot.group(name="فلوس", aliases=['money', 'economy', 'اقتصاد'], invoke_without_command=True)
async def فلوس(ctx, member: discord.Member = None):
    """!فلوس @عضو - عرض الرصيد"""
    if not member:
        member = ctx.author
    data = get_balance(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"💰 رصيد {member.display_name}", color=0xF1C40F)
    embed.add_field(name="💵 كاش", value=f"${data['cash']:,}", inline=True)
    embed.add_field(name="🏦 بنك", value=f"${data['bank']:,}", inline=True)
    embed.add_field(name="💎 المجموع", value=f"${data['cash'] + data['bank']:,}", inline=False)
    await ctx.send(embed=embed)

@فلوس.command(name="يومي", aliases=["daily"])
async def فلوس_يومي(ctx):
    """!فلوس يومي - مكافأة يومية"""
    uid = ctx.author.id
    g = ctx.guild.id
    bal = get_balance(g, uid)
    last = spam_cache.get(f"daily_{uid}")
    now = time.time()
    if last and now - last < 86400:
        remaining = int(86400 - (now - last))
        h, m = remaining // 3600, (remaining % 3600) // 60
        await ctx.send(f"⏰ المكافأة الجاية بعد {h} ساعة و {m} دقيقة.")
        return
    amount = random.randint(100, 500)
    bal["cash"] += amount
    spam_cache[f"daily_{uid}"] = now
    save_data()
    await ctx.send(f"🎁 **مكافأة يومية:** +${amount:,} 💵")

@فلوس.command(name="عمل", aliases=["work"])
async def فلوس_عمل(ctx):
    """!فلوس عمل - شغل واكسب فلوس"""
    uid = ctx.author.id
    g = ctx.guild.id
    bal = get_balance(g, uid)
    last = spam_cache.get(f"work_{uid}")
    now = time.time()
    if last and now - last < 3600:
        remaining = int(3600 - (now - last))
        m = remaining // 60
        await ctx.send(f"⏰ تعبنا! ارتاح {m} دقيقة وجرب again.")
        return
    jobs = ["طباخ 🍳", "مبرمج 💻", "معلم 📚", "سواق 🚗", "طبيب 👨‍⚕️", "محامي ⚖️", "مهندس 👷", "رسام 🎨"]
    job = random.choice(jobs)
    amount = random.randint(50, 200)
    bal["cash"] += amount
    spam_cache[f"work_{uid}"] = now
    save_data()
    await ctx.send(f"💼 **عملت كـ {job}** وكسبت **${amount:,}** 💵")

@فلوس.command(name="سرقة", aliases=["rob"])
async def فلوس_سرقة(ctx, member: discord.Member):
    """!فلوس سرقة @عضو - سرقة عضو"""
    if member.id == ctx.author.id:
        await ctx.send("❌ تسرق نفسك؟! 😂")
        return
    if member.bot:
        await ctx.send("❌ البوت ما عنده فلوس.")
        return
    g = ctx.guild.id
    target_bal = get_balance(g, member.id)
    if target_bal["cash"] < 50:
        await ctx.send(f"❌ {member.mention} ما عنده فلوس.")
        return
    uid = ctx.author.id
    last = spam_cache.get(f"rob_{uid}")
    now = time.time()
    if last and now - last < 300:
        await ctx.send("⏰ انتظر 5 دقائق بين كل سرقة.")
        return
    success = random.random() < 0.4
    author_bal = get_balance(g, uid)
    if success:
        stolen = random.randint(10, min(target_bal["cash"], 200))
        target_bal["cash"] -= stolen
        author_bal["cash"] += stolen
        spam_cache[f"rob_{uid}"] = now
        save_data()
        await ctx.send(f"🦹 **سرقة ناجحة!** سرقت **${stolen}** من {member.mention} 💀")
    else:
        fine = random.randint(20, 100)
        author_bal["cash"] = max(0, author_bal["cash"] - fine)
        spam_cache[f"rob_{uid}"] = now
        save_data()
        await ctx.send(f"🚔 **فشلت السرقة!** الشرطة غرمتك **${fine}** 😂")

@فلوس.command(name="تحويل", aliases=['transfer', 'pay'])
async def فلوس_تحويل(ctx, member: discord.Member, amount: int):
    """!فلوس تحويل @عضو <مبلغ> - تحويل فلوس"""
    if amount < 1:
        await ctx.send("❌ المبلغ أقل من 1.")
        return
    g = ctx.guild.id
    author_bal = get_balance(g, ctx.author.id)
    if author_bal["cash"] < amount:
        await ctx.send("❌ ما عندك كاش كافي.")
        return
    target_bal = get_balance(g, member.id)
    author_bal["cash"] -= amount
    target_bal["cash"] += amount
    save_data()
    await ctx.send(f"💸 **تم التحويل!** حولت **${amount:,}** لـ {member.mention} ✅")

@فلوس.command(name="قمار", aliases=['gamble', 'bet'])
async def فلوس_قمار(ctx, amount: str):
    """!فلوس قمار <مبلغ/كل> - قمار"""
    g = ctx.guild.id
    bal = get_balance(g, ctx.author.id)
    if amount.lower() == "كل":
        bet = bal["cash"]
    else:
        try:
            bet = int(amount)
        except ValueError:
            await ctx.send("❌ اكتب رقم صحيح أو 'كل'.")
            return
    if bet < 1 or bet > bal["cash"]:
        await ctx.send("❌ ما عندك كاش كافي.")
        return
    roll = random.randint(1, 100)
    if roll <= 40:
        bal["cash"] -= bet
        save_data()
        await ctx.send(f"🎰 **خسرت!** خسرت **${bet:,}** 💀 (لفة: {roll})")
    elif roll <= 75:
        bal["cash"] += bet
        save_data()
        await ctx.send(f"🎰 **فزت!** كسبت **${bet:,}** 🎉 (لفة: {roll})")
    else:
        win = bet * 2
        bal["cash"] += win
        save_data()
        await ctx.send(f"🎰 **جاكبوت!** كسبت **${win:,}** 🔥🔥 (لفة: {roll})")

@فلوس.command(name="روليت", aliases=['roulette'])
async def فلوس_روليت(ctx, bet: int):
    """!فلوس روليت <مبلغ> - روليت تفاعلية"""
    g = ctx.guild.id
    bal = get_balance(g, ctx.author.id)
    if bet < 10:
        await ctx.send("❌ الحد الأدنى 10$")
        return
    if bet > bal["cash"]:
        await ctx.send(f"❌ ما عندك كاش كافي! رصيدك: ${bal['cash']:,}")
        return

    embed = discord.Embed(title="🎰 روليت كازينو", description=f"رهان: **${bet:,}**\nدور: {ctx.author.mention}", color=0x9B59B6)
    embed.add_field(name="🎯 اركب على:", value="🔴 أحمر | ⚫ أسود | 🟢 أخضر", inline=False)
    msg = await ctx.send(embed=embed, view=None)

    from discord.ui import Button, View
    class روليتCasino(View):
        def __init__(self):
            super().__init__(timeout=30)
            self.bet = bet
            self.user_id = ctx.author.id
            self.balance = bal
            self.msg = msg

        async def interaction_check(self, interaction):
            return interaction.user.id == self.user_id

        async def on_timeout(self):
            for child in self.children:
                child.disabled = True
            await self.msg.edit(view=self)

    await ctx.send("🎰 الروليت جاهزة! جرب الأمر: `!فلوس روليت 100`")

@فلوس.command(name="متجر", aliases=["shop"])
async def فلوس_متجر(ctx):
    """!فلوس متجر - عرض المتجر"""
    embed = discord.Embed(title="🛒 المتجر", color=0x9B59B6)
    for key, item in shop_items.items():
        if item["type"] == "role":
            role = ctx.guild.get_role(item.get("role_id"))
            role_name = role.mention if role else item["name"]
        else:
            role_name = item["name"]
        embed.add_field(name=f"{item['name']}", value=f"💰 ${item['price']:,}", inline=False)
    embed.add_field(name="`!فلوس اشتري <شي>`", value="لشراء شيء", inline=False)
    await ctx.send(embed=embed)

@فلوس.command(name="اشتري", aliases=["buy"])
async def فلوس_اشتري(ctx, *, item_name: str):
    """!فلوس اشتري <اسم الشي> - شراء من المتجر"""
    g = ctx.guild.id
    bal = get_balance(g, ctx.author.id)
    item = None
    for key, it in shop_items.items():
        if item_name.lower() in it["name"].lower() or item_name.lower() in key.lower():
            item = it
            break
    if not item:
        await ctx.send("❌ هذا الشي مو موجود في المتجر.")
        return
    if bal["cash"] < item["price"]:
        await ctx.send(f"❌ محتاج **${item['price']:,}** عندك **${bal['cash']:,}**")
        return
    bal["cash"] -= item["price"]
    if item["type"] == "custom":
        if "nick" in item["name"].lower():
            await ctx.send(f"✅ تم الشراء! أرسل اسمك الجديد: (اكتب خلال 30 ثانية)")
            try:
                msg = await bot.wait_for("message", timeout=30, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
                await ctx.author.edit(nick=msg.content[:32])
                await ctx.send(f"✏️ تم تغيير اسمك إلى **{msg.content[:32]}**")
            except asyncio.TimeoutError:
                await ctx.send("⏰ انتهى الوقت.")
                bal["cash"] += item["price"]
        elif "لون" in item["name"]:
            await ctx.send(f"✅ تم الشراء! أرسل كود اللون (hex):")
            try:
                msg = await bot.wait_for("message", timeout=30, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
                color = discord.Color(int(msg.content.strip("#"), 16))
                role = await ctx.guild.create_role(name=f"🎨 {ctx.author.name}", color=color)
                await ctx.author.add_roles(role)
                await ctx.send(f"🎨 تم إنشاء رتبة ملونة لك!")
            except:
                await ctx.send("❌ خطأ في اللون.")
                bal["cash"] += item["price"]
    elif item["type"] == "role" and item.get("role_id"):
        role = ctx.guild.get_role(item["role_id"])
        if role:
            await ctx.author.add_roles(role)
            await ctx.send(f"✅ تم شراء {item['name']}! 🎉")
    save_data()

@فلوس.command(name="متجر_اضافة", aliases=["shopadd"])
@commands.has_permissions(administrator=True)
async def فلوس_متجر_اضافة(ctx, key: str, name: str, price: int, item_type: str = "custom", role_id: int = 0):
    """!فلوس متجر_اضافة <مفتاح> <اسم> <سعر> <نوع> <رول_ايدي> - إضافة منتج"""
    shop_items[key] = {"name": name, "price": price, "type": item_type}
    if role_id:
        shop_items[key]["role_id"] = role_id
    save_data()
    await ctx.send(f"✅ تم إضافة {name} إلى المتجر")

@فلوس.command(name="توب", aliases=['leaderboard', 'اغنى'])
async def فلوس_توب(ctx):
    """أغنى 10 أعضاء"""
    g = ctx.guild.id
    data = economy_data.get(g, {})
    if not data:
        await ctx.send("📊 لا يوجد بيانات.")
        return
    sorted_users = sorted(data.items(), key=lambda x: x[1]["cash"] + x[1]["bank"], reverse=True)[:10]
    embed = discord.Embed(title="🏆 أغنى 10 أعضاء", color=0xF1C40F)
    for i, (uid, d) in enumerate(sorted_users, 1):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"ID:{uid}"
        total = d["cash"] + d["bank"]
        embed.add_field(name=f"{i}. {name}", value=f"💰 ${total:,}", inline=False)
    await ctx.send(embed=embed)

# ════════════════════════════════════════
# نظام AFK 💤
# ════════════════════════════════════════

@bot.hybrid_command(name="افك", aliases=['afk', 'غياب'])
async def افك(ctx, *, reason="مشغول حالياً"):
    """!افك <سبب> - ضبط AFK"""
    afk_users[ctx.author.id] = reason
    try:
        await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
    except:
        pass
    await ctx.send(f"💤 **{ctx.author.display_name}** غياب: {reason}")
    save_data()

@bot.command(name="افك_روم")
@commands.has_permissions(administrator=True)
async def افك_روم(ctx, channel: discord.VoiceChannel):
    """!افك_روم <روم_صوتي> - يجلس البوت في الروم ويفك AFK عند الدخول"""
    afk_voice_channels[ctx.guild.id] = channel.id
    save_data()
    try:
        if ctx.guild.me.voice and ctx.guild.me.voice.channel:
            await ctx.guild.me.move_to(channel)
            await ctx.send(f"✅ انتقلت إلى **{channel.name}** 🎧")
        else:
            vc = await channel.connect()
            await ctx.send(f"✅ دخلت الروم **{channel.name}** 🎧")
    except Exception as e:
        await ctx.send(f"❌ ما قدرت أدخل الروم: {e}")

@bot.command(name="الغاء_افك_روم")
@commands.has_permissions(administrator=True)
async def الغاء_افك_روم(ctx):
    """إلغاء روم AFK الصوتي"""
    afk_voice_channels.pop(ctx.guild.id, None)
    save_data()
    try:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if vc:
            await vc.disconnect()
    except:
        pass
    await ctx.send("✅ طلعت من الروم وتم إلغاء الإعدادات.")

# ════════════════════════════════════════
# نظام الإقتراحات 📋
# ════════════════════════════════════════

@bot.group(name="اقتراحات", aliases=['suggest', 'suggestion'], invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def اقتراحات(ctx):
    """إعدادات نظام الاقتراحات"""
    embed = discord.Embed(title="📋 نظام الاقتراحات", color=0x3498DB)
    embed.add_field(name="`!اقتراحات قناة #قناة`", value="تعيين قناة الاقتراحات", inline=False)
    await ctx.send(embed=embed)

@اقتراحات.command(name="قناة")
async def اقتراحات_قناة(ctx, channel: discord.TextChannel):
    """تعيين قناة الاقتراحات"""
    g = ctx.guild.id
    suggestion_config[g] = {"channel": channel.id}
    save_data()
    await ctx.send(f"✅ تم تعيين قناة الاقتراحات: {channel.mention}")

@bot.command(name="اقترح", aliases=["propose"])
async def اقترح(ctx, *, suggestion: str):
    """!اقترح <نص> - تقديم اقتراح"""
    g = ctx.guild.id
    config = suggestion_config.get(g)
    if not config or not config.get("channel"):
        await ctx.send("❌ الإدارة ما فعّلت نظام الاقتراحات.")
        return
    ch = bot.get_channel(int(config["channel"]))
    if not ch:
        await ctx.send("❌ قناة الاقتراحات غير موجودة.")
        return
    embed = discord.Embed(title="💡 اقتراح جديد", description=suggestion, color=0x3498DB, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🆔 الحالة", value="🟢 قيد المراجعة", inline=False)
    msg = await ch.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")
    await ctx.send(f"✅ تم إرسال اقتراحك إلى {ch.mention}")

# ════════════════════════════════════════
# نظام الرتب التفاعلية 🎭
# ════════════════════════════════════════

@bot.group(name="رتب_تفاعلية", aliases=['reactionrole', 'rr'], invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def رتب_تفاعلية(ctx):
    """إعداد الرتب التفاعلية"""
    embed = discord.Embed(title="🎭 الرتب التفاعلية", color=0x9B59B6)
    embed.add_field(name="`!رتب_تفاعلية اضافة #قناة <رسالة ايدي> ✅ @رتبة`", value="إضافة رتبة تفاعلية", inline=False)
    embed.add_field(name="`!رتب_تفاعلية ازالة`", value="حذف رتبة تفاعلية", inline=False)
    embed.add_field(name="`!رتب_تفاعلية قائمة`", value="عرض الرتب التفاعلية", inline=False)
    await ctx.send(embed=embed)

@رتب_تفاعلية.command(name="اضافة")
async def رتب_تفاعلية_اضافة(ctx, channel: discord.TextChannel, message_id: int, emoji: str, role: discord.Role):
    """إضافة رتبة تفاعلية (رد فعل يختار رتبة)"""
    try:
        msg = await channel.fetch_message(message_id)
        g = ctx.guild.id
        rr = reaction_role_config.setdefault(g, {})
        key = f"{channel.id}_{message_id}"
        rr[key] = {"channel": channel.id, "message": message_id, "emoji": emoji, "role": role.id}
        save_data()
        await msg.add_reaction(emoji)
        await ctx.send(f"✅ تم إضافة {role.mention} مع {emoji} في {channel.mention}")
    except:
        await ctx.send("❌ ما لقيت الرسالة. تأكد من ID الرسالة والقناة.")

@رتب_تفاعلية.command(name="ازالة")
async def رتب_تفاعلية_ازالة(ctx, channel: discord.TextChannel, message_id: int):
    """حذف رتبة تفاعلية"""
    g = ctx.guild.id
    rr = reaction_role_config.get(g, {})
    key = f"{channel.id}_{message_id}"
    if key in rr:
        del rr[key]
        save_data()
        await ctx.send(f"✅ تم إزالة الرتبة التفاعلية.")
    else:
        await ctx.send("❌ ما لقيت الرتبة التفاعلية.")

@رتب_تفاعلية.command(name="قائمة")
async def رتب_تفاعلية_قائمة(ctx):
    """عرض الرتب التفاعلية"""
    g = ctx.guild.id
    rr = reaction_role_config.get(g, {})
    if not rr:
        await ctx.send("📋 لا يوجد رتب تفاعلية.")
        return
    embed = discord.Embed(title="🎭 الرتب التفاعلية", color=0x9B59B6)
    for key, data in rr.items():
        role = ctx.guild.get_role(data["role"])
        ch = bot.get_channel(data["channel"])
        embed.add_field(name=f"{data['emoji']} في {ch.mention if ch else '?'}", value=role.mention if role else "❌", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    g = payload.guild_id
    rr = reaction_role_config.get(g, {})
    key = f"{payload.channel_id}_{payload.message_id}"
    if key in rr and str(payload.emoji) == rr[key]["emoji"]:
        guild = bot.get_guild(g)
        if guild:
            role = guild.get_role(rr[key]["role"])
            member = guild.get_member(payload.user_id)
            if role and member:
                try:
                    await member.add_roles(role, reason="رتبة تفاعلية")
                except:
                    pass

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return
    g = payload.guild_id
    rr = reaction_role_config.get(g, {})
    key = f"{payload.channel_id}_{payload.message_id}"
    if key in rr and str(payload.emoji) == rr[key]["emoji"]:
        guild = bot.get_guild(g)
        if guild:
            role = guild.get_role(rr[key]["role"])
            member = guild.get_member(payload.user_id)
            if role and member:
                try:
                    await member.remove_roles(role, reason="رتبة تفاعلية")
                except:
                    pass

# ════════════════════════════════════════
# نظام الأنشطة 🎵 (Watch Together, YouTube, Chess)
# ════════════════════════════════════════

@bot.group(name="انشطة", aliases=['activities', 'معا'], invoke_without_command=True)
async def انشطة(ctx):
    """🎮 قائمة الأنشطة الجماعية في الرومات الصوتية"""
    embed = discord.Embed(title="🎮 الأنشطة الجماعية", color=0x9B59B6)
    embed.add_field(name="`!انشطة يوتيوب`", value="🎬 مشاهدة يوتيوب معاً", inline=False)
    embed.add_field(name="`!انشطة نتفلكس`", value="🎞️ مشاهدة نتفلكس معاً", inline=False)
    embed.add_field(name="`!انشطة شطرنج`", value="♟️ لعب شطرنج معاً", inline=False)
    embed.add_field(name="`!انشطة داما`", value="🔴 لعب داما (Checkers)", inline=False)
    embed.add_field(name="`!انشطة بطاقات`", value="🃏 لعب بطاقات", inline=False)
    embed.add_field(name="`!انشطة بازل`", value="🧩 ألعاب جماعية", inline=False)
    embed.add_field(name="`!انشطة فورتنايت`", value="🎯 لعب Fortnite معاً", inline=False)
    embed.add_field(name="`!انشطة ماينكرافت`", value="⛏️ لعب Minecraft", inline=False)
    embed.add_field(name="`!انشطة ببجي`", value="🔫 PUBG Mobile معاً", inline=False)
    embed.set_footer(text="لازم تكون في روم صوتي")
    await ctx.send(embed=embed)

async def start_activity(ctx, activity_id):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ لازم تكون في روم صوتي.")
        return
    vc = ctx.author.voice.channel
    try:
        invite = await vc.create_invite(target_type=discord.InviteTarget.embedded_application, target_application_id=activity_id, max_age=0)
        embed = discord.Embed(title="✅ تم!", color=0x2ECC71)
        embed.description = f"اضغط على الرابط عشان تنضم:\n{invite.url}"
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ البوت يحتاج صلاحية **Create Invite**.")

ACTIVITIES = {
    "يوتيوب": 880218394199220334,
    "youtube": 880218394199220334,
    "نتفلكس": 880218832743055411,
    "netflix": 880218832743055411,
    "شطرنج": 832012774040141854,
    "chess": 832012774040141854,
    "داما": 832013003968348200,
    "checkers": 832013003968348200,
    "بطاقات": 839990762236514324,
    "cards": 839990762236514324,
    "بازل": 879863686565621790,
    "puzzle": 879863686565621790,
    "فورتنايت": 832025144389533716,
    "fortnite": 832025144389533716,
    "ماينكرافت": 832012586023256104,
    "minecraft": 832012586023256104,
    "ببجي": 832025157657165855,
    "pubg": 832025157657165855,
}

@انشطة.command(name="يوتيوب", aliases=["youtube"])
async def انشطة_يوتيوب(ctx):
    await start_activity(ctx, 880218394199220334)

@انشطة.command(name="نتفلكس", aliases=["netflix"])
async def انشطة_نتفلكس(ctx):
    await start_activity(ctx, 880218832743055411)

@انشطة.command(name="شطرنج", aliases=["chess"])
async def انشطة_شطرنج(ctx):
    await start_activity(ctx, 832012774040141854)

@انشطة.command(name="داما", aliases=["checkers"])
async def انشطة_داما(ctx):
    await start_activity(ctx, 832013003968348200)

@انشطة.command(name="بطاقات", aliases=["cards"])
async def انشطة_بطاقات(ctx):
    await start_activity(ctx, 839990762236514324)

@انشطة.command(name="بازل", aliases=["puzzle"])
async def انشطة_بازل(ctx):
    await start_activity(ctx, 879863686565621790)

@انشطة.command(name="فورتنايت", aliases=["fortnite"])
async def انشطة_فورتنايت(ctx):
    await start_activity(ctx, 832025144389533716)

@انشطة.command(name="ماينكرافت", aliases=["minecraft"])
async def انشطة_ماينكرافت(ctx):
    await start_activity(ctx, 832012586023256104)

@انشطة.command(name="ببجي", aliases=["pubg"])
async def انشطة_ببجي(ctx):
    await start_activity(ctx, 832025157657165855)

# ════════════════════════════════════════
# نظام الأوامر المخصصة 🤖
# ════════════════════════════════════════

custom_commands = {}

@bot.group(name="امر", aliases=['cmd', 'custom'], invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def امر(ctx):
    """🤖 الأوامر المخصصة"""
    embed = discord.Embed(title="🤖 الأوامر المخصصة", color=0x2ECC71)
    embed.add_field(name="`!امر جديد <اسم> <رد>`", value="إنشاء أمر مخصص جديد", inline=False)
    embed.add_field(name="`!امر حذف <اسم>`", value="حذف أمر مخصص", inline=False)
    embed.add_field(name="`!امر قائمة`", value="عرض الأوامر المخصصة", inline=False)
    await ctx.send(embed=embed)

@امر.command(name="جديد", aliases=['add', 'create'])
async def امر_جديد(ctx, cmd_name: str, *, response: str):
    """!امر جديد <اسم> <رد> - إنشاء أمر مخصص"""
    g = ctx.guild.id
    cmds = custom_commands.setdefault(g, {})
    if cmd_name.startswith("!"):
        cmd_name = cmd_name[1:]
    if cmd_name in ["امر", "cmd", "custom", "say", "setup", "log", "حماية", "سكرتي", "لعبة", "شات", "اغاني", "فلوس", "مستوى", "افك", "اقتراحات", "اقترح", "رتب_تفاعلية", "انشطة", "ترحيب", "روم", "جيفت", "تصويت", "سنايب", "تذكير", "حقيقه", "اقتباس", "عكس", "رمز", "تقيم", "مؤقت", "حساب", "تاريخ", "بين", "بصمة", "تبرع", "رابط", "جودة"]:
        await ctx.send(f"❌ الأمر `{cmd_name}` محجوز.")
        return
    cmds[cmd_name] = response
    save_data()
    await ctx.send(f"✅ تم إنشاء الأمر `!{cmd_name}` ✅")

@امر.command(name="حذف", aliases=['remove', 'delete'])
async def امر_حذف(ctx, cmd_name: str):
    """!امر حذف <اسم> - حذف أمر مخصص"""
    g = ctx.guild.id
    cmds = custom_commands.get(g, {})
    if cmd_name.startswith("!"):
        cmd_name = cmd_name[1:]
    if cmd_name not in cmds:
        await ctx.send(f"❌ الأمر `{cmd_name}` غير موجود.")
        return
    del cmds[cmd_name]
    save_data()
    await ctx.send(f"✅ تم حذف الأمر `!{cmd_name}` ✅")

@امر.command(name="قائمة", aliases=['list', 'all'])
async def امر_قائمة(ctx):
    """!امر قائمة - عرض الأوامر المخصصة"""
    g = ctx.guild.id
    cmds = custom_commands.get(g, {})
    if not cmds:
        await ctx.send("📋 لا يوجد أوامر مخصصة.")
        return
    embed = discord.Embed(title=f"🤖 الأوامر المخصصة ({len(cmds)})", color=0x2ECC71)
    for name, response in sorted(cmds.items())[:20]:
        short = response[:40] + "..." if len(response) > 40 else response
        embed.add_field(name=f"`!{name}`", value=short, inline=False)
    await ctx.send(embed=embed)

# ── معالجة الأوامر المخصصة في on_message ──
# (مضمنة في نهاية on_message عبر process_commands)

# ════════════════════════════════════════
# نظام إحصائيات السيرفر 📊
# ════════════════════════════════════════

stats_cache = {}
stats_config = {}

@bot.group(name="احصائيات", aliases=['stats', 'statistics'], invoke_without_command=True)
async def احصائيات(ctx):
    """📊 عرض إحصائيات السيرفر"""
    guild = ctx.guild
    now = datetime.now(timezone.utc)
    embed = discord.Embed(title=f"📊 إحصائيات {guild.name}", color=0x3498DB, timestamp=now)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    total = guild.member_count
    humans = sum(1 for m in guild.members if not m.bot)
    bots = total - humans
    online = sum(1 for m in guild.members if m.status != discord.Status.offline)

    embed.add_field(name="👥 الأعضاء", value=f"المجموع: {total}\nبشر: {humans}\nبوتات: {bots}\nأونلاين: {online}", inline=True)
    embed.add_field(name="💬 الرومات", value=f"نصية: {len(guild.text_channels)}\nصوتية: {len(guild.voice_channels)}\nفئات: {len(guild.categories)}", inline=True)
    embed.add_field(name="🎭 الرتب", value=len(guild.roles), inline=True)
    embed.add_field(name="👑 المالك", value=guild.owner.mention, inline=True)
    embed.add_field(name="📅 إنشاء السيرفر", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="🆔 ID", value=guild.id, inline=True)

    # Active today
    active_today = sum(1 for uid, ts in spam_cache.items() if isinstance(uid, int) and now.timestamp() - ts < 86400)
    embed.add_field(name="📈 نشاط اليوم", value=f"{active_today} عضو نشط", inline=False)

    # Voice
    voice_count = sum(1 for ch in guild.voice_channels if len(ch.members) > 0)
    voice_total = sum(len(ch.members) for ch in guild.voice_channels)
    embed.add_field(name="🔊 الصوت", value=f"{voice_count} روم نشط | {voice_total} شخص", inline=True)

    # Boost
    boost_level = guild.premium_tier
    boost_count = guild.premium_subscription_count
    embed.add_field(name="🚀 البوست", value=f"المستوى: {boost_level}\nالعدد: {boost_count}", inline=True)

    await ctx.send(embed=embed)

@احصائيات.command(name="عضو", aliases=["member"])
async def احصائيات_عضو(ctx, member: discord.Member = None):
    """!احصائيات عضو @عضو - إحصائيات العضو"""
    if not member:
        member = ctx.author
    embed = discord.Embed(title=f"📊 إحصائيات {member.display_name}", color=member.color, timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id, inline=True)
    embed.add_field(name="📅 انضم للسيرفر", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "?", inline=True)
    embed.add_field(name="📅 انضم لدسكورد", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="👑 أعلى رتبة", value=member.top_role.mention, inline=True)
    embed.add_field(name="🤖 بوت", value="نعم" if member.bot else "لا", inline=True)
    embed.add_field(name="🌐 الحالة", value=str(member.status).replace("dnd", "مشغول").replace("online", "متصل").replace("idle", "غير نشط").replace("offline", "غير متصل"), inline=True)
    if member.activity:
        embed.add_field(name="🎮 يلعب", value=member.activity.name, inline=False)

    # XP & Economy data
    g = ctx.guild.id
    xp = xp_data.get(g, {}).get(member.id, {"xp": 0, "level": 1})
    eco = economy_data.get(g, {}).get(member.id, {"cash": 0, "bank": 0})
    embed.add_field(name="⬆️ المستوى", value=f"{xp['level']} ({xp['xp']}XP)", inline=True)
    embed.add_field(name="💰 الفلوس", value=f"${eco['cash'] + eco['bank']:,}", inline=True)
    await ctx.send(embed=embed)

@احصائيات.command(name="رسائل", aliases=["messages"])
@commands.has_permissions(administrator=True)
async def احصائيات_رسائل(ctx, limit: int = 100):
    """!احصائيات رسائل <عدد> - إحصائيات آخر الرسائل"""
    await ctx.send("⏳ **جاري الإحصاء...**")
    msg_count = {}
    async for message in ctx.channel.history(limit=min(limit, 500)):
        if not message.author.bot:
            msg_count[message.author] = msg_count.get(message.author, 0) + 1
    if not msg_count:
        await ctx.send("📊 لا يوجد رسائل.")
        return
    sorted_msgs = sorted(msg_count.items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title=f"📊 أكثر {len(sorted_msgs)} أعضاء كتابة", color=0x3498DB)
    for i, (author, count) in enumerate(sorted_msgs, 1):
        embed.add_field(name=f"{i}. {author.display_name}", value=f"{count} رسالة", inline=False)
    await ctx.send(embed=embed)

@bot.hybrid_group(name="فعاليه", aliases=["event", "competition"], invoke_without_command=True)
async def فعاليه(ctx):
    """!فعاليه - إدارة الفعاليات والمسابقات"""
    g = ctx.guild.id
    comp = competitions.get(g)
    if not comp:
        await ctx.send("❌ لا توجد فعالية حالياً.\nاستخدم `!فعاليه انشاء <عنوان>` لإنشاء واحدة.")
        return
    embed = discord.Embed(title=f"🎯 {comp['title']}", color=0x2ECC71 if comp['is_open'] else 0xE74C3C)
    embed.add_field(name="الحالة", value="🟢 مفتوح" if comp['is_open'] else "🔒 مغلق", inline=True)
    embed.add_field(name="المشاركين", value=str(len(comp['participants'])), inline=True)
    await ctx.send(embed=embed)

@فعاليه.command(name="انشاء", aliases=["create"])
@commands.has_permissions(administrator=True)
async def فعاليه_انشاء(ctx, *, title: str):
    """!فعاليه انشاء <عنوان> - إنشاء فعالية جديدة"""
    g = ctx.guild.id
    if g in competitions:
        await ctx.send("❌ توجد فعالية نشطة حالياً. احذفها أولاً باستخدام `!فعاليه حذف`")
        return
    comp = {
        "channel_id": ctx.channel.id,
        "message_id": None,
        "title": title,
        "is_open": True,
        "participants": []
    }
    embed = discord.Embed(title=f"🎯 {title}", color=0x2ECC71)
    embed.description = "اضغط **✅ تسجيل** للمشاركة في الفعالية"
    embed.add_field(name="الحالة", value="🟢 مفتوح", inline=True)
    embed.add_field(name="المشاركين", value="0", inline=True)
    embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    msg = await ctx.send(embed=embed, view=CompetitionView())
    comp["message_id"] = msg.id
    comp["channel_id"] = msg.channel.id
    competitions[g] = comp
    save_data()
    await ctx.send(f"✅ تم إنشاء الفعالية **{title}** بنجاح")

@فعاليه.command(name="حذف", aliases=["delete"])
@commands.has_permissions(administrator=True)
async def فعاليه_حذف(ctx):
    """!فعاليه حذف - حذف الفعالية الحالية"""
    g = ctx.guild.id
    if g not in competitions:
        await ctx.send("❌ لا توجد فعالية")
        return
    comp = competitions.pop(g)
    save_data()
    try:
        ch = bot.get_channel(comp["channel_id"])
        if ch:
            msg = await ch.fetch_message(comp["message_id"])
            await msg.delete()
    except:
        pass
    await ctx.send(f"✅ تم حذف الفعالية **{comp['title']}**")

@bot.command(name="D")
async def d_command(ctx, number: int, *, role: discord.Role = None):
    """!D <رقم> (رتبة) - منشن أو إعطاء رتبة لعضو حسب الترتيب"""
    ALLOWED_ROLE_ID = 1508625487369343086
    if ctx.author.id != YOUR_USER_ID and ALLOWED_ROLE_ID not in [r.id for r in ctx.author.roles]:
        await ctx.send("❌ ليس لديك صلاحية لاستخدام هذا الأمر")
        return
    if number < 1:
        await ctx.send("❌ الرقم يجب أن يكون 1 أو أكثر")
        return
    members = sorted(ctx.guild.members, key=lambda m: m.joined_at or datetime.min.replace(tzinfo=timezone.utc))
    if number > len(members):
        await ctx.send(f"❌ السيرفر فيه {len(members)} عضو فقط. الرقم {number} أكبر من العدد الكلي")
        return
    target = members[number - 1]

    if not role:
        await ctx.send(f"#{number} {target.mention}")
        return

    try:
        _pending_role_changes.add((ctx.guild.id, target.id, role.id))
        await target.add_roles(role, reason=f"بأمر من {ctx.author}")
        embed = discord.Embed(title="✅ تم إعطاء الرتبة", color=0x2ECC71)
        embed.add_field(name="1- .منشن نفسك", value=f"{ctx.author.mention} ({ctx.author.id})", inline=False)
        embed.add_field(name="2- منشن الشخص", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="3 - الرتبه", value=f"{role.mention} ({role.id})", inline=False)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ البوت لا يملك صلاحية لإعطاء هذه الرتبة")
    except Exception as e:
        await ctx.send(f"❌ حدث خطأ: {e}")
    finally:
        _pending_role_changes.discard((ctx.guild.id, target.id, role.id))

@bot.command(name="ابلغ", aliases=["تواصل", "contact"])
async def ابلغ(ctx, *, message: str):
    """!ابلغ <رسالة> - إرسال رسالة للمبرمج"""
    owner = bot.get_user(YOUR_USER_ID)
    if not owner:
        try:
            owner = await bot.fetch_user(YOUR_USER_ID)
        except:
            await ctx.send("❌ تعذر إرسال الرسالة")
            return
    embed = discord.Embed(title="📬 رسالة جديدة", color=0x6366f1, timestamp=datetime.now())
    embed.add_field(name="المرسل", value=f"{ctx.author} ({ctx.author.id})", inline=False)
    embed.add_field(name="السيرفر", value=f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "خاص", inline=False)
    embed.add_field(name="الرسالة", value=message[:1000], inline=False)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    try:
        await owner.send(embed=embed)
        await ctx.send(f"✅ **تم إرسال رسالتك إلى المبرمج** ✅\n> {message[:200]}")
    except:
        await ctx.send("❌ تعذر إرسال الرسالة")

# ════════════════════════════════════════
# تتبع الأنشطة — البرامج في الرومات الصوتية
# ════════════════════════════════════════

@bot.hybrid_command(name="تتبع", aliases=["track", "النشاط", "activity"], description="تتبع البرامج والأنشطة في الرومات الصوتية")
async def activity_track_cmd(ctx, option: str = None, target: discord.Member = None):
    guild_id = ctx.guild.id if ctx.guild else 0

    if option is None:
        option = "status"

    option = option.lower().strip()

    if option == "on":
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != YOUR_USER_ID:
            return await ctx.send("❌ هذا الأمر متاح لمالك السيرفر فقط.")
        activity_tracking_enabled[guild_id] = True
        save_data()
        embed = discord.Embed(
            title="✅ تم تفعيل تتبع الأنشطة",
            description="الآن سيتم تسجيل جميع الأنشطة والبرامج في الرومات الصوتية.",
            color=0x2ECC71
        )
        return await ctx.send(embed=embed)

    if option == "off":
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != YOUR_USER_ID:
            return await ctx.send("❌ هذا الأمر متاح لمالك السيرفر فقط.")
        activity_tracking_enabled[guild_id] = False
        save_data()
        embed = discord.Embed(
            title="🛑 تم تعطيل تتبع الأنشطة",
            description="لن يتم تسجيل الأنشطة في الرومات الصوتية.",
            color=0xE74C3C
        )
        return await ctx.send(embed=embed)

    if option == "status":
        is_on = activity_tracking_enabled.get(guild_id, False)
        embed = discord.Embed(
            title="📊 حالة تتبع الأنشطة",
            color=0x2ECC71 if is_on else 0xE74C3C
        )
        embed.add_field(name="الحالة", value="🟢 مفعّل" if is_on else "🔴 معطّل", inline=True)
        embed.add_field(name="السيرفر", value=ctx.guild.name, inline=True)

        voice_members = []
        for ch in ctx.guild.voice_channels:
            for m in ch.members:
                if not m.bot and m.activity:
                    act_type = str(m.activity.type).split(".")[-1] if m.activity.type else "custom"
                    label = _ACTIVITY_LABELS.get(act_type, "⚙️")
                    voice_members.append(f"{m.mention} — {label} **{getattr(m.activity, 'name', '?')}** في <#{ch.id}>")

        if voice_members:
            embed.add_field(
                name=f"🔊 الأنشطة الحالية ({len(voice_members)})",
                value="\n".join(voice_members[:15]) + ("\n..." if len(voice_members) > 15 else ""),
                inline=False
            )
        else:
            embed.add_field(name="🔊 الأنشطة الحالية", value="لا يوجد أعضاء بنشاط في الرومات الصوتية", inline=False)

        embed.set_footer(text="الأمر: $log on/off/status")
        return await ctx.send(embed=embed)

    if target is None:
        target = ctx.author

    if target.bot:
        return await ctx.send("❌ البوتات ليس لها نشاط قابل للتتبع.")

    if not target.voice or not target.voice.channel:
        return await ctx.send(f"❌ **{target.display_name}** ليس في روم صوتي حالياً.")

    activities = [a for a in target.activities if a and a.type is not None]
    if not activities:
        return await ctx.send(f"❌ **{target.display_name}** ليس لديه نشاط حالياً.")

    embed = discord.Embed(
        title=f"📋 أنشطة {target.display_name}",
        color=0x5865F2
    )
    LogEmbed.user_field(embed, target, "العضو")
    LogEmbed.channel_field(embed, "الروم الصوتي", target.voice.channel)

    for act in activities[:5]:
        act_type = str(act.type).split(".")[-1] if act.type else "custom"
        label = _ACTIVITY_LABELS.get(act_type, "⚙️ نشاط")
        act_name = getattr(act, "name", None) or "غير معروف"
        act_details = getattr(act, "details", None)
        act_state = getattr(act, "state", None)
        act_url = getattr(act, "url", None)

        val = f"**{act_name}**"
        if act_details:
            val += f"\n> {act_details}"
        if act_state:
            val += f"\n> {act_state}"
        if act_url:
            val += f"\n🔗 {act_url}"

        embed.add_field(name=label, value=val[:1024], inline=False)

    embed.set_footer(text=f"⏰ {datetime.now().strftime('%Y-%m-%d %I:%M %p')}")
    await ctx.send(embed=embed)

@activity_track_cmd.error
async def activity_track_cmd_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        await ctx.send("❌ حدث خطأ أثناء تنفيذ الأمر.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ يُرجى تحديد عضو صحيح.")

async def update_stats():
    """تحديث إحصائيات البوت إلى ملف JSON"""
    while not bot.is_closed():
        try:
            guild_count = len(bot.guilds)
            member_count = sum(g.member_count or 0 for g in bot.guilds)
            # Build hourly chart data (last 24h)
            now = datetime.now()
            hours = []
            for i in range(23, -1, -1):
                h = (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:00")
                hours.append({"hour": h, "count": command_hourly.get(h, 0)})
            # Build server list
            servers = []
            for g in sorted(bot.guilds, key=lambda x: x.member_count or 0, reverse=True):
                servers.append({
                    "id": g.id,
                    "name": g.name,
                    "icon": g.icon.url if g.icon else None,
                    "members": g.member_count or 0,
                    "owner": str(g.owner) if g.owner else "?"
                })
            stats = {
                "guilds": guild_count,
                "total_members": member_count,
                "commands_used": command_count,
                "uptime": str(datetime.now() - start_time).split(".")[0] if start_time else "0",
                "hourly": hours,
                "servers": servers,
                "last_updated": datetime.now().isoformat()
            }
            with open("bot_stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[STATS UPDATE ERROR] {e}")
        await asyncio.sleep(30)

async def check_dashboard_commands():
    """قراءة الأوامر من لوحة التحكم (sync, backup)"""
    cmd_file = "dashboard_cmd.txt"
    while not bot.is_closed():
        try:
            if os.path.exists(cmd_file):
                with open(cmd_file, "r", encoding="utf-8") as f:
                    cmd = f.read().strip()
                os.remove(cmd_file)
                if cmd == "sync":
                    for g in bot.guilds:
                        try:
                            await bot.tree.sync(guild=g)
                        except:
                            pass
                    try:
                        await bot.tree.sync()
                    except:
                        pass
                    print("[DASHBOARD] Synced slash commands")
                elif cmd == "backup":
                    from guild_backup import save_backup
                    for g in bot.guilds:
                        try:
                            save_backup(g.id, g.name)
                        except:
                            pass
                    print("[DASHBOARD] Created backups for all guilds")
        except Exception as e:
            print(f"[DASHBOARD CMD ERROR] {e}")
        await asyncio.sleep(5)

async def daily_report():
    """تقرير يومي يُرسل كل يوم الساعة 12 بالليل (منتصف الليل)"""
    while not bot.is_closed():
        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if midnight <= now:
            midnight += timedelta(days=1)
        wait_seconds = (midnight - now).total_seconds()
        print(f"[DAILY REPORT] Waiting {wait_seconds:.0f}s until midnight ({midnight})")
        await asyncio.sleep(wait_seconds)
        try:
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            guild_count = len(bot.guilds)
            member_count = sum(g.member_count or 0 for g in bot.guilds)
            uptime = str(datetime.now() - start_time).split(".")[0] if start_time else "0"

            cmd_logs = []
            if os.path.exists("command_logs.json"):
                try:
                    with open("command_logs.json", "r", encoding="utf-8") as f:
                        all_logs = json.load(f)
                    today_logs = [l for l in all_logs if l.get("timestamp", "").startswith(today)]
                    cmd_logs = today_logs
                except:
                    pass

            top_cmds = {}
            top_users = {}
            for l in cmd_logs:
                c = l.get("command", "?")
                u = l.get("user", "?")
                top_cmds[c] = top_cmds.get(c, 0) + 1
                top_users[u] = top_users.get(u, 0) + 1
            top_cmds_str = "\n".join([f"  `{k}` — {v}" for k, v in sorted(top_cmds.items(), key=lambda x: x[1], reverse=True)[:5]]) or "  لا توجد أوامر"
            top_users_str = "\n".join([f"  {k} — {v}" for k, v in sorted(top_users.items(), key=lambda x: x[1], reverse=True)[:5]]) or "  لا يوجد مستخدمين"

            hacked = get_hacked_accounts_data()
            today_ts = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
            today_caught = []
            for uid, entries in hacked.items():
                for e in entries:
                    if e.get("timestamp", 0) >= today_ts:
                        today_caught.append(e)
            repeat_users = sum(1 for uid, entries in hacked.items() if len(entries) > 1)

            bait_section = (
                f"🪤 **صيد الهاكرز اليوم:**\n"
                f"  تم القبض: **{len(today_caught)}** شخص\n"
                f"  حسابات مكررة: **{repeat_users}** حساب\n"
            )
            if today_caught:
                links_list = {}
                for e in today_caught:
                    link_key = e.get("link", "غير معروف")[:30]
                    links_list[link_key] = links_list.get(link_key, 0) + 1
                top_links = sorted(links_list.items(), key=lambda x: x[1], reverse=True)[:3]
                bait_section += "  الروابط: " + ", ".join([f"`{k}` (×{v})" for k, v in top_links]) + "\n"

            srvs = []
            for g in sorted(bot.guilds, key=lambda x: x.member_count or 0, reverse=True):
                srvs.append(f"  {g.name} — {g.member_count or 0} عضو")
            srvs_str = "\n".join(srvs) or "  لا يوجد سيرفرات"

            report = (
                f"📊 **التقرير اليومي — {today}**\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"🤖 **البوت:**\n"
                f"  السيرفرات: {guild_count}\n"
                f"  الأعضاء: {member_count}\n"
                f"  Uptime: {uptime}\n"
                f"  الأوامر اليوم: {len(cmd_logs)}\n\n"
                f"🔥 **أكثر الأوامر:**\n{top_cmds_str}\n\n"
                f"👑 **أكثر المستخدمين:**\n{top_users_str}\n\n"
                f"{bait_section}\n"
                f"🌐 **السيرفرات:**\n{srvs_str}\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📅 تقرير تلقائي — MAX BOT"
            )

            user = bot.get_user(int(YOUR_USER_ID))
            if user:
                await user.send(report)
                print(f"[DAILY REPORT] Sent daily report for {today}")
        except Exception as e:
            print(f"[DAILY REPORT ERROR] {e}")

def export_commands_to_json():
    """تصدير الأوامر إلى ملف JSON للموقع"""
    CMDS_FILE = "commands_data.json"
    commands_list = []
    seen = set()

    def get_cat(name):
        c = {
            "افك":"افتراضي","رجوع":"افتراضي","setup":"اداة","D":"اداة",
            "test_log":"اداة","اختبار_لوق":"اداة","log":"اداة","حذف":"اداة","tel":"اداة",
            "سحب":"اداة","حاتف_تيم":"اداة","حاتف_فئة":"اداة",
            "باند":"ادارة","ban":"ادارة","فك_باند":"ادارة","unban":"ادارة",
            "كيك":"ادارة","kick":"ادارة","تايم_اوت":"ادارة","timeout":"ادارة",
            "مشرف":"ادارة","mod":"ادارة","clear":"ادارة","مسح":"ادارة","purge":"ادارة",
            "سوول":"ادارة","sudo":"ادارة","lock":"ادارة","قفل":"ادارة",
            "unlock":"ادارة","فتح":"ادارة","slowmode":"ادارة","بطيء":"ادارة",
            "اعطا_رتبة":"ادارة","giverole":"ادارة","سحب_رتبة":"ادارة","removerole":"ادارة",
            "انشاء_رتبة":"ادارة","createrole":"ادارة","اعادة_تسمية_رتبة":"ادارة","renamerole":"ادارة",
            "لون_رتبة":"ادارة","rolecolor":"ادارة","حاتف_روم":"ادارة","حاتف_روم_صوتي":"ادارة",
            "انشاء_روم":"ادارة","createchannel":"ادارة","تسمية_روم":"ادارة","renamechannel":"ادارة",
            "اسم_السيرفر":"ادارة","servername":"ادارة","وصف_السيرفر":"ادارة","serverdesc":"ادارة",
            "صورة_السيرفر":"ادارة","servericon":"ادارة","رتب_ترحيب":"ادارة","autorole":"ادارة",
            "الغاء_رتب_ترحيب":"ادارة","remove_autorole":"ادارة","روم_مطبخ":"ادارة","modroom":"ادارة",
            "روم_مطبخ_setup":"ادارة","modroom_setup":"ادارة","فصل":"ادارة","disconnect":"ادارة","dc":"ادارة",
            "حاتظ":"ادارة","حاتفظ":"ادارة","نسخ":"ادارة","لصق":"ادارة","امر":"ادارة","cmd":"ادارة","custom":"ادارة",
            "حاتمة":"ادارة","protection":"ادارة","امان":"ادارة","فك":"ادارة","linkblocker":"ادارة",
            "فعاليه":"ادارة","event":"ادارة","competition":"ادارة",
            "اشتراء":"اقتصاد","شتري":"اقتصاد","متجر":"اقتصاد","بيع":"اقتصاد",
            "توب":"اقتصاد","شحن":"اقتصاد","سحب":"اقتصاد","تحويل":"اقتصاد","قمار":"اقتصاد",
            "روليت":"اقتصاد","عمل":"اقتصاد","سرقة":"اقتصاد",
            "مستوى":"مستويات","level":"مستويات","ليفل":"مستويات",
            "اغاني":"موسيقى","music":"موسيقى","اغنية":"موسيقى","لوحة":"موسيقى","panel":"موسيقى","تحكم":"موسيقى",
            "انشطة":"صوت","activities":"صوت","معا":"صوت",
            "افك_روم":"صوت","الغاء_افك_روم":"صوت","انضم":"صوت","join":"صوت","غادر":"صوت","leave":"صوت",
            "سكرتي":"اداة","سر":"اداة","secret":"اداة","ترحيب":"ادارة","welcome":"ادارة",
            "ابلغ":"اداة","report":"اداة","تواصل":"اداة","contact":"اداة",
            "poll":"اداة","تصويت":"اداة","vote":"اداة","اقتراحات":"ادارة","suggest":"ادارة","suggestion":"ادارة",
            "شات":"العاب","chat":"العاب","تكلم":"العاب","ai":"العاب",
            "بوت":"معلومات","invite":"معلومات","ping":"معلومات","بنج":"معلومات",
            "say":"معلومات","تحديث":"معلومات","restart":"معلومات","update":"معلومات",
            "voice_debug":"اداة","تشخيص":"اداة","تحديد":"اداة",
            "setticket":"اداة","setticketimage":"اداة",
            "serverinfo":"معلومات","guildinfo":"معلومات","سيرفر":"معلومات",
            "userinfo":"معلومات","memberinfo":"معلومات","معلومات":"معلومات",
            "avatar":"معلومات","صورة":"معلومات","snipe":"معلومات","سنايب":"معلومات",
            "صلاحياتي":"معلومات","myperms":"معلومات",
            "8ball":"العاب","كرة":"العاب","analyze":"العاب","تحليل":"العاب",
            "blot":"العاب","بلوت":"العاب","calc":"العاب","حساب":"العاب","math":"العاب",
            "choose":"العاب","بين":"العاب","اختر":"العاب","color":"العاب","لون":"العاب",
            "emojify":"العاب","رمز":"العاب","تطويل":"العاب","emoji":"العاب",
            "fact":"العاب","حقيقه":"العاب","معلومة":"العاب","fingerprint":"العاب",
            "بصمة":"العاب","رمز_خاص":"العاب","food":"العاب","اكل":"العاب",
            "fortune":"العاب","توقعات":"العاب","فورتشن":"العاب",
            "hack":"العاب","اختراق":"العاب","haz":"العاب","حظ":"العاب",
            "hit":"العاب","ضرب":"العاب","joke":"العاب","نكتة":"العاب",
            "kiss":"العاب","بوس":"العاب","marry":"العاب","زواج":"العاب",
            "my-number":"العاب","رقمي":"العاب","nesba":"العاب","نسبة":"العاب",
            "question":"العاب","سؤال":"العاب","rate":"العاب","تقيم":"العاب","قيّم":"العاب",
            "reveal":"العاب","كشف":"العاب","reverse":"العاب","عكس":"العاب","قلب":"العاب",
            "sara7a":"العاب","صراحه":"العاب","time":"العاب","تاريخ":"العاب","وقت":"العاب","date":"العاب",
            "timer":"العاب","مؤقت":"العاب","تايمر":"العاب","remind":"العاب",
            "تذكير":"العاب","ذكرني":"العاب","donate":"العاب","تبرع":"العاب","دعم":"العاب",
            "status":"العاب","جودة":"العاب","حالة_البوت":"العاب","quality":"العاب",
            "quote":"العاب","اقتباس":"العاب","rand-suggest":"العاب","اقتراح":"العاب",
            "wisdom":"العاب","حكمة":"العاب","drink":"العاب","مشروب":"العاب",
            "لعبة":"العاب","game":"العاب","games":"العاب",
            "تحدي_عاز":"العاب","roulette_challenge":"العاب","تحدي":"العاب","عاز":"العاب",
            "احصائيات":"معلومات","stats":"معلومات","statistics":"معلومات",
            "رتب_تفاعلية":"ادارة","reactionrole":"ادارة","rr":"ادارة",
            "تتبع":"اداة","track":"اداة","النشاط":"اداة","activity":"اداة",
            "لوق":"اداة","log":"اداة","log_webhook":"اداة","لوق_ويبهوك":"اداة",
        }
        return c.get(name, "معلومات")

    # Prefix commands
    for cmd in bot.commands:
        name = cmd.name
        if name in seen: continue
        seen.add(name)
        desc = (cmd.help or cmd.description or "").split("\n")[0][:80]
        commands_list.append({"name": name, "type": "!", "desc": desc, "category": get_cat(name)})
        for alias in cmd.aliases:
            if alias not in seen:
                seen.add(alias)
                commands_list.append({"name": alias, "type": "!", "desc": desc, "category": get_cat(alias)})
        # Subcommands of groups
        if hasattr(cmd, 'commands'):
            for sub in cmd.commands:
                sname = sub.name
                sdesc = (sub.help or sub.description or "").split("\n")[0][:80]
                full = f"{name} {sname}"
                if full not in seen:
                    seen.add(full)
                    commands_list.append({"name": full, "type": "!", "desc": sdesc, "category": get_cat(name)})
                for salias in sub.aliases:
                    full2 = f"{name} {salias}"
                    if full2 not in seen:
                        seen.add(full2)
                        commands_list.append({"name": full2, "type": "!", "desc": sdesc, "category": get_cat(name)})

    # Slash commands
    for cmd in bot.tree._global_commands.values():
        name = cmd.name
        if name in seen: continue
        seen.add(name)
        commands_list.append({"name": name, "type": "/", "desc": cmd.description[:80], "category": get_cat(name)})

    with open(CMDS_FILE, "w", encoding="utf-8") as f:
        json.dump(commands_list, f, ensure_ascii=False, indent=2)
    print(f"[EXPORT] Exported {len(commands_list)} commands to {CMDS_FILE}")

# ═══════════════════════════════════════════════════════════════
# 🎯 نظام صيد اليوزرات المميزة — Username Hunter System
# ═══════════════════════════════════════════════════════════════

USERNAME_BANK = {
    "ultra_short": [
        "zx","qw","ax","od","yu","ki","lo","mu","nu","vi","zo","xe","qi","jo",
        "ry","fu","ho","da","we","up","go","no","ok","on","do","if","it","up",
        "ox","ai","oh","um","ex","ad","in","at","to","by","as","so","is","an",
        "my","me","hi","yo","he","we","us","be","pm","am","do","go","no","ok",
        "io","ai","ox","ax","ex","ux","ez","oz","az","ja","ka","ra","za","ta",
        "nu","vu","zu","du","gu","ku","mu","pu","tu","bu","fu","hu","ju","lu",
        "ni","pi","si","ti","wi","xi","yi","bi","ci","di","fi","gi","hi","ji",
        "qi","ri","ve","ze","ce","de","fe","ge","he","ke","le","me","ne","pe",
        "re","se","te","we","ye","ye","ba","ca","da","fa","ga","ha","ja","ka",
        "la","ma","na","pa","ra","sa","ta","va","wa","ya","za","ab","eb","ib",
        "ob","ub","ac","ec","ic","oc","uc","ad","ed","id","od","ud","af","ef",
        "if","of","uf","ag","eg","ig","og","ug","ak","ek","ik","ok","uk","al",
        "el","il","ol","ul","am","em","im","om","um","an","en","in","on","un",
        "ap","ep","ip","op","up","ar","er","ir","or","ur","as","es","is","os",
        "us","at","et","it","ot","ut","av","ev","iv","ov","uv","aw","ew","iw",
        "ow","uw","ay","ey","oy","az","ez","iz","oz","uz"
    ],
    "premium_3": [
        "ace","age","ago","aid","aim","air","all","ape","arc","arm","art","ash",
        "ask","axe","bad","bag","ban","bar","bat","bay","bed","bet","bid","big",
        "bit","bow","box","boy","bud","bug","bun","bus","but","buy","cab","can",
        "cap","car","cat","cop","cow","cry","cub","cup","cut","day","den","dew",
        "dig","dim","dip","dog","dot","dry","due","dug","duo","dye","ear","eat",
        "egg","ego","elm","end","era","eve","eye","fad","fan","far","fat","few",
        "fig","fin","fir","fit","fix","fly","foe","fog","for","fox","fry","fun",
        "fur","gap","gas","gel","gem","get","gin","god","got","gum","gun","gut",
        "guy","gym","had","ham","has","hat","hay","hen","her","hid","him","hip",
        "his","hit","hog","hop","hot","how","hub","hue","hug","hum","hut","ice",
        "icy","ill","imp","ink","inn","ion","ire","irk","its","ivy","jab","jam",
        "jar","jaw","jay","jet","job","jog","jot","joy","jug","keg","key","kid",
        "kin","kit","lab","lad","lag","lap","law","lay","led","leg","let","lid",
        "lie","lip","lit","log","lot","low","mad","man","map","mar","mat","max",
        "may","men","met","mid","mix","mob","mom","mop","mow","mud","mug","nab",
        "nag","nap","net","new","nil","nip","nit","nod","nor","not","now","nun",
        "nut","oak","oar","oat","odd","ode","off","oft","oil","old","one","opt",
        "orb","ore","our","out","owe","owl","own","pad","pal","pan","pap","par",
        "pat","paw","pay","pea","peg","pen","pep","per","pet","pie","pig","pin",
        "pit","ply","pod","pop","pot","pow","pro","pry","pub","pug","pun","pup",
        "pus","put","rag","ram","ran","rap","rat","raw","ray","red","ref","rib",
        "rid","rig","rim","rip","rob","rod","rot","row","rub","rug","rum","run",
        "rut","rye","sac","sad","sag","sap","sat","saw","say","sea","set","sew",
        "shy","sin","sip","sir","sis","sit","six","ski","sky","sly","sob","sod",
        "son","sop","sot","sow","soy","spa","spy","sty","sub","sue","sum","sun",
        "sup","tab","tad","tag","tan","tap","tar","tax","tea","ten","the","thy",
        "tie","tin","tip","toe","ton","too","top","tot","toy","try","tub","tug",
        "two","urn","use","vat","vet","vie","vow","wad","wag","war","was","wax",
        "way","web","wed","wet","who","why","wig","win","wit","woe","wok","won",
        "woo","wow","yak","yam","yap","yaw","yea","yes","yet","yew","yin","you",
        "zap","zen","zig","zip","zoo","nix","hux","vox","jux","lux","nux","pax",
        "rex","sex","tax","vex","wax","fox","box","coy","goy","hoy","joy","roy",
        "soy","toy","boy","coy","dye","rye","aye","eye","rye","woe","hue","cue",
        "due","sue","ewe","yew","gnu","emu","oaf","ore","awe","axe","ore","ape"
    ],
    "premium_4": [
        "able","ache","acid","aged","aide","also","arch","area","army","auto","avid","away",
        "axle","back","bait","bake","bald","bale","ball","balm","band","bane","bang","bank",
        "bare","bark","barn","base","bass","bath","bead","beak","beam","bean","bear","beat",
        "been","beer","bell","belt","bend","bent","best","bill","bind","bird","bite","blow",
        "blue","blur","boar","boat","body","bold","bolt","bomb","bond","bone","book","boom",
        "boot","bore","born","boss","both","bowl","bulk","bull","bump","burn","bury","bush",
        "busy","buzz","cafe","cage","cake","calf","call","calm","came","camp","cane","cape",
        "card","care","cart","case","cash","cast","cave","chef","chin","chip","chop","city",
        "clad","clam","clan","clap","claw","clay","clip","clod","clog","club","clue","coal",
        "coat","code","coil","coin","cold","colt","comb","come","cone","cook","cool","cope",
        "copy","cord","core","cork","corn","cost","cozy","crab","crew","crop","crow","cuff",
        "cure","curl","cute","dale","damp","dare","dark","dart","dash","data","date","dawn",
        "dead","deaf","deal","dear","debt","deck","deed","deem","deep","deer","demo","dent",
        "deny","desk","dial","dice","dirt","disc","dish","dock","does","dome","done","doom",
        "door","dose","dove","down","doze","drab","drag","draw","drip","drop","drum","dual",
        "duck","duel","duet","dull","dumb","dump","dune","dusk","dust","duty","each","earl",
        "earn","ease","east","easy","edge","edit","else","emit","envy","epic","even","evil",
        "exam","exit","face","fact","fade","fail","fair","fake","fall","fame","fang","fare",
        "farm","fast","fate","fawn","fear","feat","feed","feel","feet","fell","felt","fern",
        "file","fill","film","find","fine","fire","firm","fish","fist","five","flag","flap",
        "flat","flaw","flea","fled","flew","flex","flip","flit","flog","flow","flux","foam",
        "foil","fold","folk","fond","font","food","fool","foot","ford","fore","fork","form",
        "fort","foul","four","fowl","free","frog","from","fuel","full","fume","fund","funk",
        "fury","fuse","fuss","gain","gait","gale","game","gang","gape","garb","gate","gave",
        "gaze","gear","gene","gift","gild","gill","girl","gist","give","glad","glee","glen",
        "glib","glow","glue","glum","gnat","gnaw","goad","goal","goat","goes","gold","golf",
        "gone","good","gore","grab","gram","gray","grew","grid","grim","grin","grip","grit",
        "grow","gulf","guru","gust","guts","hack","hail","hair","hale","half","hall","halt",
        "hand","hang","hare","harm","harp","hash","hate","haul","have","haze","hazy","head",
        "heal","heap","hear","heat","heed","heel","held","hell","helm","help","herb","herd",
        "here","hero","hide","high","hike","hill","hilt","hind","hint","hire","hiss","hive",
        "hold","hole","home","hone","hood","hook","hope","horn","hose","host","hour","howl",
        "huge","hull","hump","hung","hunt","hurl","hurt","hush","hymn","icon","idea","idle",
        "inch","into","iron","isle","item","jack","jade","jail","jazz","jean","jeer","jerk",
        "jest","jinx","jive","jock","join","joke","jolt","jump","junk","jury","just","keen",
        "keep","kept","kick","kill","kind","king","kiss","kite","knee","knelt","knew","knit",
        "knob","knot","know","lace","lack","laid","lair","lake","lamb","lame","lamp","land",
        "lane","lard","lark","lash","lass","last","late","lawn","lead","leaf","leak","lean",
        "leap","left","lend","lens","less","liar","lick","life","lift","like","limb","lime",
        "limp","line","link","lion","list","live","load","loaf","loan","lock","lode","loft",
        "logo","lone","long","look","loom","loop","loot","lord","lore","lorn","lose","loss",
        "lost","loud","love","luck","lull","lump","lure","lurk","lush","lust","mace","made",
        "mage","maid","mail","main","make","male","mall","malt","mane","many","mare","mark",
        "mars","mash","mask","mass","mast","mate","maze","mead","meal","mean","meat","meek",
        "meet","melt","memo","mend","menu","mere","mesh","mess","mice","mild","mile","milk",
        "mill","mime","mind","mine","mint","mire","miss","mist","mite","moat","mock","mode",
        "mold","mole","molt","monk","mood","moon","moor","moot","more","morn","moss","most",
        "moth","move","much","muck","mule","mull","muse","mush","must","mute","myth","nail",
        "name","nape","navy","near","neat","neck","need","nest","next","nice","nine","node",
        "none","noon","norm","nose","note","noun","numb","oath","obey","odds","odor","omen",
        "omit","once","only","onto","ooze","opal","open","oral","orca","oven","over","pace",
        "pack","pact","page","paid","pail","pain","pair","pale","palm","pane","pang","pant",
        "pare","park","part","pass","past","path","pave","pawn","peak","peal","pear","peat",
        "peck","peel","peer","pelt","perk","pest","pick","pier","pike","pile","pill","pine",
        "pink","pint","pipe","plan","play","plea","plod","plop","plot","plow","ploy","plug",
        "plum","plus","poem","poet","poke","pole","poll","polo","pomp","pond","pony","pool",
        "poor","pope","pore","pork","port","pose","posh","post","pour","pout","pray","prey",
        "prod","prop","pros","prowl","puck","pull","pulp","pump","punk","pure","push","quiz",
        "race","rack","raft","rage","raid","rail","rain","rake","ramp","rang","rank","rant",
        "rash","rate","rave","raze","read","real","reap","rear","reed","reef","reel","rein",
        "rely","rent","rest","rich","ride","rift","rind","ring","riot","ripe","rise","risk",
        "road","roam","roar","robe","rock","rode","role","roll","romp","roof","room","root",
        "rope","rose","rosy","rout","rove","rude","ruin","rule","rump","rune","rush","rust",
        "sack","safe","sage","said","sail","sake","sale","salt","same","sand","sane","sang",
        "sank","sash","save","scab","scam","scan","scar","seal","seam","sear","seat","seed",
        "seek","seem","seen","self","sell","send","sent","sewn","shed","shin","ship","shoe",
        "shop","shot","show","shut","sift","sigh","sign","silk","sill","silt","sing","sink",
        "sire","site","size","skit","slab","slag","slam","slap","slat","slaw","slay","sled",
        "slew","slid","slim","slip","slit","slob","sloe","slog","slop","slot","slow","slug",
        "slum","slur","smog","snap","snag","snip","snob","snow","snub","snug","soak","soap",
        "soar","sock","soda","sofa","soft","soil","sold","sole","some","song","soon","soot",
        "sore","sort","soul","soup","sour","sown","span","spar","spat","spec","sped","spin",
        "spit","spot","spud","spur","stab","stag","star","stay","stem","step","stew","stir",
        "stop","stub","stud","stun","such","suck","suit","sulk","sung","sunk","sure","surf",
        "swan","swap","swim","swum","tabs","tack","tact","tail","take","tale","talk","tall",
        "tame","tank","tape","tart","task","taxi","teal","team","tear","teem","tell","temp",
        "tend","tent","term","tern","test","text","than","that","them","then","they","thin",
        "this","thud","thus","tick","tide","tidy","tier","tile","till","tilt","time","tint",
        "tiny","tire","toad","toil","told","toll","tomb","tome","tone","took","tool","tops",
        "tore","torn","toss","tour","town","trap","tray","tree","trek","trim","trio","trip",
        "trod","trot","true","tuck","tuft","tuna","tune","turf","turn","tusk","twin","type",
        "ugly","undo","unit","unto","upon","urge","used","user","vain","vale","vane","vary",
        "vase","vast","veal","veer","veil","vein","vent","verb","very","vest","veto","vial",
        "vice","view","vile","vine","visa","void","volt","vote","wade","wage","wail","wait",
        "wake","walk","wall","wand","want","ward","warm","warn","warp","wary","wash","wasp",
        "wave","wavy","waxy","weak","wear","weed","week","well","welt","went","wept","were",
        "west","what","when","whet","whey","whim","whip","whom","wick","wide","wife","wild",
        "will","wilt","wily","wind","wine","wing","wink","wipe","wire","wise","wish","wisp",
        "with","wits","woke","wolf","womb","wood","wool","word","wore","work","worm","worn",
        "wove","wrap","wren","writ","yank","yard","yarn","year","yell","yoga","yoke","your",
        "zany","zeal","zero","zest","zinc","zing","zone","zoom","bolt","glow","silk","echo",
        "fury","rage","haze","dusk","dawn","mist","gale","nova","apez","solo","aura","vibe",
        "neon","opal","ruby","jade","sage","onyx","cruz","volt","flux","byte","void","zen",
        "neon","luna","mira","nova","aria","iris","sage","opus","vibe","echo","apex","zen",
        "byte","core","node","bolt","flux","grid","mesh","link","node","pack","byte","code"
    ],
    "premium_cool": [
        "vortex","phoenix","zenith","aurora","nexus","cipher","phantom","shadow","blaze",
        "frost","storm","thunder","blaze","ember","spark","fury","raven","onyx","titan",
        "cyber","pixel","neo","zero","alpha","omega","sigma","delta","gamma","theta",
        "apex","core","node","flux","grid","mesh","link","pack","byte","code","hack",
        "glitch","matrix","vector","syntax","binary","crypto","cyber","stealth","surge",
        "drift","pulse","shock","vapor","cosmic","stellar","lunar","solar","astro","nova",
        "comet","quasar","pulsar","nebula","galaxy","horizon","eclipse","aurora","zephyr",
        "tempest","inferno","avalanche","tsunami","typhoon","cyclone","tornado","blizzard",
        "crimson","scarlet","obsidian","platinum","titanium","diamond","crystal","prism",
        "spectrum","radiant","luminous","velocity","momentum","quantum","paradox","enigma",
        "cipher","oracle","prophecy","mystic","arcane","ethereal","celestial","divine",
        "sovereign","majestic","imperial","royal","regal","noble","elite","prestige",
        "vanguard","sentinel","guardian","defender","champion","warrior","paladin","knight",
        "ranger","scout","hunter","stalker","shadow","ghost","wraith","specter","phantom",
        "reaper","harbinger","vanguard","sentinel","titan","colossus","golem","giant",
        "dragon","wyvern","serpent","basilisk","chimera","kraken","leviathan","hydra",
        "phoenix","griffin","pegasus","unicorn","cerberus","minotaur","cyclops","medusa"
    ],
    "premium_arabic": [
        "king","lord","star","moon","sun","fire","rain","wind","wave","sand",
        "snow","ice","fog","mist","dew","ash","smoke","dust","mud","clay",
        "gold","silver","copper","iron","steel","stone","rock","pearl","coral","amber",
        "ruby","jade","onyx","opal","sapphire","emerald","crystal","diamond","prism","glass",
        "falcon","eagle","hawk","raven","crow","owl","wolf","fox","bear","lion",
        "tiger","dragon","serpent","phoenix","griffin","pegasus","unicorn","horse","deer","wolf"
    ],
    "premium_compound": [
        "alpha.v","beta.v","core.v","flux.v","grid.v","node.v","byte.v","code.v","void.v","zen.v",
        "apex.x","bolt.x","echo.x","fury.x","glow.x","haze.x","mist.x","nova.x","opal.x","vibe.x",
        "ruby.x","sage.x","onyx.x","jade.x","luna.x","mira.x","aria.x","iris.x","opus.x","zen.x",
        "dark.shadow","ghost.shadow","phantom.shadow","reaper.shadow","void.shadow","abyss.shadow",
        "neon.glow","pixel.glow","cyber.glow","matrix.glow","binary.glow","code.glow",
        "fire.storm","thunder.storm","lightning.storm","blaze.storm","frost.storm","ice.storm",
        "lunar.phase","solar.phase","astro.phase","comet.phase","nova.phase","quasar.phase",
        "iron.forge","steel.forge","titan.forge","dragon.forge","phoenix.forge","griffin.forge",
        "shadow.real","ghost.real","phantom.real","wraith.real","specter.real","reaper.real",
        "neon.blur","cyber.blur","pixel.blur","matrix.blur","glitch.blur","synth.blur",
        "dark.flux","light.flux","chaos.flux","order.flux","void.flux","zen.flux",
        "crimson.dawn","scarlet.dawn","obsidian.dawn","platinum.dawn","titanium.dawn","diamond.dawn",
        "alpha.omega","sigma.grind","theta.flow","delta.code","gamma.pulse","zeta.wave",
        "king.midas","lord.zeus","star.captain","moon.walker","sun.rider","fire.breath",
        "ice.breaker","storm.chaser","fury.hunter","ghost.rider","shadow.walker","void.walker",
        "a.b","c.d","e.f","g.h","i.j","k.l","m.n","o.p","q.r","s.t","u.v","w.x","y.z",
        "a.x","b.y","c.z","d.a","e.b","f.c","g.d","h.e","i.f","j.g","k.h","l.i","m.j"
    ]
}

HUNTER_BLACKLIST = {
    "xxx","qqq","zzz","www","aaa","bbb","ccc","ddd","eee","fff","ggg","hhh","iii",
    "jjj","kkk","lll","mmm","nnn","ooo","ppp","rrr","sss","ttt","uuu","vvv","yyy",
    "000","111","222","333","444","555","666","777","888","999","012","123","234",
    "345","456","567","678","789","987","876","765","654","543","432","321","1111",
    "2222","3333","4444","5555","6666","7777","8888","9999","0000",
    "sex","die","god","hit","kill","dead","porn","ass","fuck","shit","damn","hell",
    "hate","pain","rape","drug","bomb","weed","nude","hack","scam","spam","phish",
    "suck","crap","bitch","bastard","dick","cock","penis","vagina","pussy",
    "nigga","nigger","fag","faggot","retard","cripple","spic","kike","chink",
    "terror","isis","alqaeda","binladen","hitler","nazi","holocaust",
    "suicide","overdose","selfharm","cutme","bleed",
    "ember","fire","dark","ghost","shadow","phantom","wraith","reaper",
    "necro","blood","blade","skull","doom","chaos","void","abyss",
    "demon","devil","sin","curse","hex","bane","blight","frost",
    "frozen","ice","snow","cold","chill","crisp","crystal","glaze",
    "blaze","burn","ash","cinder","smoke","fume","sulfur","toxic",
    "venom","poison","plague","virus","bacteria","germ","mold","rot",
    "decay","rust","corrode","taint","stain","filth","muck","sludge",
    "grime","dirt","dust","sand","mud","clay","rock","stone",
    "boulder","mountain","peak","summit","apex","zenith","nadir","pinnacle",
    "crown","throne","king","queen","prince","princess","royal","noble",
    "lord","lady","sir","dame","baron","duke","earl","count",
    "duke","prince","emperor","czar","sultan","shah","khalif","chieftain",
    "warrior","knight","paladin","ranger","scout","hunter","stalker","assassin",
    "ninja","samurai","ronin","shogun","daimyo","ronin","shinobi","sensei",
    "master","grandmaster","legend","mythic","divine","immortal","eternal","omega",
    "alpha","beta","gamma","delta","epsilon","zeta","eta","theta",
    "iota","kappa","lambda","mu","nu","xi","omicron","pi",
    "rho","sigma","tau","upsilon","phi","chi","psi","omega"
}

HUNTER_PLATFORMS = ["tiktok", "instagram", "discord"]
HUNTER_TYPES = ["premium_3", "premium_4", "premium_cool", "premium_arabic", "premium_compound"]
HUNTER_MIN_LENGTH = {"discord": 4, "tiktok": 2, "instagram": 1}

username_hunter_data = {
    "channel_id": 0,
    "active": False,
    "platform_counter": 0,
    "type_counter": 0,
    "username_index": 0,
    "stats": {
        "total_checks": 0,
        "found": 0,
        "💎": 0,
        "✨": 0,
        "⭐": 0,
        "🔥": 0,
        "per_platform": {
            "discord": {"checked": 0, "found": 0},
            "tiktok": {"checked": 0, "found": 0},
            "instagram": {"checked": 0, "found": 0},
        }
    }
}

def load_username_hunter():
    pass

def save_username_hunter():
    mark_data_dirty()

def classify_username(name):
    name = name.lower()
    if name in HUNTER_BLACKLIST:
        return None, None, None
    if name in dynamic_blacklist:
        return None, None, None
    for bl in custom_blacklist:
        if bl.lower() in name:
            return None, None, None
    length = len(name)
    is_compound = "." in name or "_" in name
    is_repeated = bool(re.search(r'(.)\1{2,}', name))
    is_pattern = bool(re.search(r'(.{2})\1', name))
    is_sequential = False
    if name.isdigit() and length >= 3:
        for i in range(len(name) - 2):
            if ord(name[i+1]) == ord(name[i]) + 1 and ord(name[i+2]) == ord(name[i]) + 2:
                is_sequential = True
                break
        for i in range(len(name) - 2):
            if ord(name[i+1]) == ord(name[i]) - 1 and ord(name[i+2]) == ord(name[i]) - 2:
                is_sequential = True
                break
    if is_compound:
        return "💎", "مركّب ملكي", 0xFFD700
    if length <= 2:
        return "💎", "نادر جداً", 0xFFD700
    if length == 3:
        return "✨", "مميز", 0xC0C0C0
    if length == 4:
        return "⭐", "ممتاز", 0x00BFFF
    if length >= 5 and length <= 6:
        return "🔥", "رائع", 0x00FF00
    if is_repeated or is_pattern:
        return "✨", "مكرر ملكي", 0xC0C0C0
    if is_sequential:
        return "⭐", "متسلسل", 0x00BFFF
    return None, None, None

def generate_username(platform="discord"):
    global username_hunter_data
    if target_list:
        idx = username_hunter_data.get("target_idx", 0) % len(target_list)
        username_hunter_data["target_idx"] = idx + 1
        return target_list[idx]
    if platform == "discord":
        compound_chance = 0.3
        if random.random() < compound_chance:
            bank = USERNAME_BANK.get("premium_compound", USERNAME_BANK["premium_4"])
            return random.choice(bank)
        three_or_four = ["premium_3", "premium_4"]
        current_type = random.choice(three_or_four)
    else:
        current_type = HUNTER_TYPES[username_hunter_data.get("type_counter", 0) % len(HUNTER_TYPES)]
        username_hunter_data["type_counter"] = username_hunter_data.get("type_counter", 0) + 1
    bank = USERNAME_BANK.get(current_type, USERNAME_BANK["premium_4"])
    idx = username_hunter_data.get("username_index", 0) % len(bank)
    username_hunter_data["username_index"] = idx + 1
    return bank[idx]

def _get_random_ua():
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    ]
    return random.choice(uas)

def _make_scraper():
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
    scraper.headers["User-Agent"] = _get_random_ua()
    return scraper

def check_availability(username, platform="tiktok"):
    try:
        if platform == "discord":
            return False, "https://discord.com/register"
        elif platform == "tiktok":
            url = f"https://www.tiktok.com/@{username}"
            scraper = _make_scraper()
            response = scraper.get(url, timeout=15, allow_redirects=True)
            if response.status_code != 200:
                print(f"[HUNTER] TikTok @{username}: HTTP {response.status_code} → SKIP", flush=True)
                return False, url
            text = response.text
            size = len(text)
            if size < 8000:
                print(f"[HUNTER] TikTok @{username}: page too small ({size}) → WAF → SKIP", flush=True)
                return False, url
            if '"uniqueId":"' in text:
                unique_match = re.search(r'"uniqueId":"([^"]+)"', text)
                if unique_match and unique_match.group(1).lower() == username.lower():
                    print(f"[HUNTER] TikTok @{username}: uniqueId MATCH → TAKEN", flush=True)
                    return False, url
            if '"fanCount"' in text and '"signature"' in text:
                print(f"[HUNTER] TikTok @{username}: fanCount+signature → TAKEN", flush=True)
                return False, url
            not_found = '"statusCode":10202' in text or '"statusCode":10221' in text
            if not_found:
                print(f"[HUNTER] TikTok @{username}: statusCode 10202/10221 → AVAILABLE", flush=True)
                return True, url
            print(f"[HUNTER] TikTok @{username}: no clear signal → SKIP", flush=True)
            return False, url
        elif platform == "instagram":
            url = f"https://www.instagram.com/{username}/"
            scraper = _make_scraper()
            response = scraper.get(url, timeout=15, allow_redirects=True)
            if response.status_code != 200:
                print(f"[HUNTER] Instagram @{username}: HTTP {response.status_code} → SKIP", flush=True)
                return False, url
            text = response.text
            size = len(text)
            if response.status_code == 404:
                if size < 5000:
                    print(f"[HUNTER] Instagram @{username}: 404 + small page → AVAILABLE", flush=True)
                    return True, url
                print(f"[HUNTER] Instagram @{username}: 404 clean → AVAILABLE", flush=True)
                return True, url
            if '"edge_followed_by"' in text or '"is_private":' in text:
                print(f"[HUNTER] Instagram @{username}: profile data found → TAKEN", flush=True)
                return False, url
            og = re.search(r'property="og:description" content="([^"]*)"', text)
            if og and "Followers" in og.group(1):
                print(f"[HUNTER] Instagram @{username}: og:desc with Followers → TAKEN", flush=True)
                return False, url
            print(f"[HUNTER] Instagram @{username}: no clear signal → SKIP", flush=True)
            return False, url
    except Exception as e:
        print(f"[HUNTER] Check error @{username} on {platform}: {e}", flush=True)
        return False, None


def double_check_availability(username, platform):
    """Second check with cloudscraper + different browser fingerprint"""
    try:
        if platform == "discord":
            username_lower = username.lower()
            for guild in bot.guilds:
                member = guild.get_member_named(username_lower)
                if member:
                    return False
            return True
        elif platform == "tiktok":
            url = f"https://www.tiktok.com/@{username}"
            scraper = _make_scraper()
            response = scraper.get(url, timeout=15, allow_redirects=True)
            text = response.text
            if len(text) < 8000:
                return False
            if '"uniqueId":"' in text:
                m = re.search(r'"uniqueId":"([^"]+)"', text)
                if m and m.group(1).lower() == username.lower():
                    return False
            if '"fanCount"' in text:
                return False
            not_found = '"statusCode":10202' in text or '"statusCode":10221' in text
            return not_found
        elif platform == "instagram":
            url = f"https://www.instagram.com/{username}/"
            scraper = _make_scraper()
            response = scraper.get(url, timeout=15, allow_redirects=True)
            if response.status_code != 200:
                return False
            if response.status_code == 404:
                return len(response.text) < 5000
            text = response.text
            if '"edge_followed_by"' in text or '"is_private":' in text:
                return False
            og = re.search(r'property="og:description" content="([^"]*)"', text)
            if og and "Followers" in og.group(1):
                return False
            return False
    except:
        return False


def validate_username_for_platform(username, platform):
    import re as _re
    if not username or len(username) < 2:
        return False
    if ".." in username:
        return False
    if platform == "discord":
        if len(username) < 2 or len(username) > 32:
            return False
        if not _re.match(r'^[a-z0-9][a-z0-9._]*[a-z0-9]$', username) and len(username) > 2:
            return False
        if not _re.match(r'^[a-z0-9._]+$', username):
            return False
        if username.startswith(".") or username.endswith("."):
            return False
        if username.startswith("_") or username.endswith("_"):
            return False
        blocked = ["discord", "admin", "mod", "staff", "system", "everyone", "here", "bot"]
        for b in blocked:
            if b in username:
                return False
    elif platform == "tiktok":
        if len(username) < 2 or len(username) > 24:
            return False
        if not _re.match(r'^[a-z0-9._]+$', username):
            return False
        if username.endswith("."):
            return False
    elif platform == "instagram":
        if len(username) < 1 or len(username) > 30:
            return False
        if not _re.match(r'^[a-z0-9._]+$', username):
            return False
        if username.startswith(".") or username.endswith("."):
            return False
    return True

class UsernameHunterView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶️ تشغيل الصيد", style=discord.ButtonStyle.green, custom_id="hunter_start")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ للمسؤولين فقط!", ephemeral=True)
        if not username_hunter_data["channel_id"]:
            return await interaction.response.send_message("❌ حدد القناة أولاً: `!يوزر #قناة`", ephemeral=True)
        username_hunter_data["active"] = True
        save_username_hunter()
        if not username_hunter_task.is_running():
            username_hunter_task.start()
        await interaction.response.send_message("✅ تم تفعيل صيد اليوزرات!", ephemeral=True)

    @discord.ui.button(label="⏸️ إيقاف الصيد", style=discord.ButtonStyle.red, custom_id="hunter_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ للمسؤولين فقط!", ephemeral=True)
        username_hunter_data["active"] = False
        save_username_hunter()
        if username_hunter_task.is_running():
            username_hunter_task.cancel()
        await interaction.response.send_message("⏸️ تم إيقاف صيد اليوزرات.", ephemeral=True)

    @discord.ui.button(label="📊 الإحصائيات", style=discord.ButtonStyle.blurple, custom_id="hunter_stats")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = username_hunter_data["stats"]
        pp = s.get("per_platform", {})
        ch = interaction.guild.get_channel(username_hunter_data["channel_id"])
        ch_name = ch.mention if ch else "غير محدد"
        status = "✅ مفعّل" if username_hunter_data["active"] else "⏸️ متوقف"
        embed = discord.Embed(
            title="═══════════════════════════\n📊 إحصائيات صيد اليوزرات\n═══════════════════════════",
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="🎯 الحالة", value=status, inline=True)
        embed.add_field(name="📡 القناة", value=ch_name, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="🔍 إجمالي الفحصات", value=f"**{s['total_checks']}**", inline=True)
        embed.add_field(name="🎯 يوزرات مكتشفة", value=f"**{s['found']}**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="💎 نادرة", value=f"**{s.get('💎', 0)}**", inline=True)
        embed.add_field(name="✨ مميزة", value=f"**{s.get('✨', 0)}**", inline=True)
        embed.add_field(name="⭐ ممتازة", value=f"**{s.get('⭐', 0)}**", inline=True)
        embed.add_field(name="🔥 رائعة", value=f"**{s.get('🔥', 0)}**", inline=True)
        embed.add_field(name="💎 مركّب ملكي", value=f"**{username_hunter_data['stats'].get('compound', 0)}**", inline=True)
        platform_lines = []
        for pname, pdata in pp.items():
            pnames = {"discord":"💬 Discord","tiktok":"🎵 TikTok","instagram":"📸 Instagram"}
            platform_lines.append(f"{pnames.get(pname, pname)}: {pdata.get('checked',0)} فحص / {pdata.get('found',0)} صيد")
        embed.add_field(name="═════ إحصائيات المنصات ═══", value="\n".join(platform_lines) if platform_lines else "لا توجد بيانات", inline=False)
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tasks.loop(seconds=15)
async def username_hunter_task():
    if not username_hunter_data.get("active"):
        return
    ch = bot.get_channel(username_hunter_data.get("channel_id", 0))
    if not ch:
        username_hunter_data["active"] = False
        save_username_hunter()
        return

    current_platform = HUNTER_PLATFORMS[username_hunter_data.get("platform_counter", 0) % len(HUNTER_PLATFORMS)]

    username = generate_username(current_platform)
    emoji, label, color = classify_username(username)
    if not emoji:
        username_hunter_data["platform_counter"] = username_hunter_data.get("platform_counter", 0) + 1
        return

    if not validate_username_for_platform(username, current_platform):
        username_hunter_data["platform_counter"] = username_hunter_data.get("platform_counter", 0) + 1
        return

    platform_info = {
        "discord": ("💬", "Discord"),
        "tiktok": ("🎵", "TikTok"),
        "instagram": ("📸", "Instagram"),
    }

    if len(username) < HUNTER_MIN_LENGTH.get(current_platform, 2):
        username_hunter_data["platform_counter"] = username_hunter_data.get("platform_counter", 0) + 1
        return

    if current_platform == "discord" and len(username) > 4 and "." not in username and "_" not in username:
        username_hunter_data["platform_counter"] = username_hunter_data.get("platform_counter", 0) + 1
        return

    username_hunter_data["platform_counter"] = username_hunter_data.get("platform_counter", 0) + 1

    username_hunter_data.setdefault("stats", {})
    username_hunter_data["stats"].setdefault("total_checks", 0)
    username_hunter_data["stats"].setdefault("found", 0)
    username_hunter_data["stats"].setdefault("💎", 0)
    username_hunter_data["stats"].setdefault("✨", 0)
    username_hunter_data["stats"].setdefault("⭐", 0)
    username_hunter_data["stats"].setdefault("🔥", 0)
    username_hunter_data["stats"].setdefault("per_platform", {})

    username_hunter_data["stats"]["total_checks"] += 1
    username_hunter_data["stats"]["per_platform"].setdefault(current_platform, {"checked": 0, "found": 0})
    username_hunter_data["stats"]["per_platform"][current_platform]["checked"] += 1

    checked_guilds_count = len(bot.guilds)

    if current_platform == "discord":
        username_clean = username.lower().strip()
        url = f"https://discord.com/users/{username_clean}"
        found_taken = False
        checked_guilds_count = 0
        for guild in bot.guilds:
            member = guild.get_member_named(username_clean)
            if member:
                found_taken = True
                break
            checked_guilds_count += 1
        is_available = not found_taken
        p_url = url
    else:
        smart_delay = random.uniform(1.0, 4.0)
        await asyncio.sleep(smart_delay)
        is_available, p_url = await asyncio.to_thread(check_availability, username, current_platform)

    p_emoji, p_name = platform_info[current_platform]
    print(f"[HUNTER] @{username} → {current_platform}: {'AVAILABLE' if is_available else 'taken'}", flush=True)

    if is_available:
        await asyncio.sleep(3)
        double_check = await asyncio.to_thread(double_check_availability, username, current_platform)
        if not double_check:
            print(f"[HUNTER] DOUBLE CHECK FAILED for @{username} on {current_platform}", flush=True)
            is_available = False

    if is_available:
        username_hunter_data["stats"]["found"] += 1
        username_hunter_data["stats"][emoji] = username_hunter_data["stats"].get(emoji, 0) + 1
        username_hunter_data["stats"]["per_platform"][current_platform]["found"] += 1

        disclaimer = ""
        if current_platform == "discord":
            disclaimer = f"\n✅ **تم التحقق من {checked_guilds_count} سيرفر**"

        embed = discord.Embed(
            title=f"{emoji} يوزر {label} متاح على {p_name}!",
            description=(
                f"═══════════════════════════\n"
                f"🎯 **يوزر متاح للحجز!**\n"
                f"═══════════════════════════\n\n"
                f"├─ **اليوزر:** `{username}`\n"
                f"├─ **التصنيف:** {emoji} {label}\n"
                f"├─ **الطول:** {len(username)} أحرف\n"
                f"├─ **المنصة:** {p_emoji} **{p_name}**\n"
                f"├─ **الوقت:** <t:{int(datetime.now(timezone.utc).timestamp())}:F>\n"
                f"└─ **الحالة:** ✅ متاح للحجز{disclaimer}\n\n"
                f"═══════════════════════════"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"═══════════════════════════\nMAX BOT • صيد اليوزرات • {p_emoji} {p_name}\n═══════════════════════════")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label=f"🔗 اذهب للحجز على {p_name}",
            url=p_url,
            style=discord.ButtonStyle.link
        ))
        view.add_item(discord.ui.Button(
            label="🔍 /simplify",
            style=discord.ButtonStyle.secondary,
            custom_id=f"hunter_simplify_{username}"
        ))
        view.add_item(discord.ui.Button(
            label="✅ /verify",
            style=discord.ButtonStyle.success,
            custom_id=f"hunter_verify_{username}"
        ))
        try:
            await ch.send(embed=embed, view=view)
            print(f"[HUNTER] ✅ SENT @{username} on {p_name} to #{ch.name}", flush=True)
        except Exception as e:
            print(f"[HUNTER] ❌ SEND FAILED: {e}", flush=True)

    save_username_hunter()

@username_hunter_task.before_loop
async def before_username_hunter():
    await bot.wait_until_ready()

@username_hunter_task.error
async def username_hunter_error(error):
    print(f"[HUNTER ERROR] {error}", flush=True)
    await asyncio.sleep(5)
    if not username_hunter_task.is_running() and username_hunter_data.get("active"):
        username_hunter_task.start()

class HunterButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 /simplify", style=discord.ButtonStyle.secondary, custom_id="hunter_simplify_persistent")
    async def simplify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        username = button.custom_id.replace("hunter_simplify_", "")
        await interaction.response.send_message(f"🔍 **جاري تبسيط `{username}`...**", ephemeral=True)

    @discord.ui.button(label="✅ /verify", style=discord.ButtonStyle.success, custom_id="hunter_verify_persistent")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        username = button.custom_id.replace("hunter_verify_", "")
        await interaction.response.send_message(f"✅ **جاري التحقق من `{username}`...**", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
# 📌 أوامر صيد اليوزرات
# ═══════════════════════════════════════════════════════════════

@bot.command(name="يوزر", aliases=["يوزرات", "usr", "usernames"])
@commands.has_permissions(administrator=True)
async def set_hunter_channel(ctx, channel: discord.TextChannel = None):
    """تعيين قناة صيد اليوزرات: !يوزر #قناة"""
    if not channel:
        s = username_hunter_data.get("stats", {})
        ch = ctx.guild.get_channel(username_hunter_data.get("channel_id", 0))
        ch_name = ch.mention if ch else "غير محدد"
        status = "✅ مفعّل" if username_hunter_data.get("active") else "⏸️ متوقف"
        embed = discord.Embed(
            title="═══════════════════════════\n🎯 نظام صيد اليوزرات\n═══════════════════════════",
            description=(
                f"├─ **الحالة:** {status}\n"
                f"├─ **القناة:** {ch_name}\n"
                f"├─ **الإجمالي:** {s['total_checks']} فحص\n"
                f"└─ **المكتشفة:** {s['found']} يوزر\n\n"
                f"### 📌 أوامر الصيد:\n"
                f"`!يوزر #قناة` — تعيين قناة الصيد\n"
                f"`!صيد تشغيل` — تفعيل الصيد\n"
                f"`!صيد إيقاف` — إيقاف الصيد\n"
                f"`!صيد حالة` — عرض الإحصائيات\n"
                f"`!فحص <يوزر>` — فحص سريع لاسم واحد\n"
                f"`!gen [عدد]` — توليد يوزرات عشوائية\n"
                f"`!البنك` — عرض محتوى بنك اليوزرات\n"
                f"`!بلاك add/remove <كلمة>` — إدارة القائمة السوداء\n"
                f"`!صيد_مستهدف add/clear/list` — يوزرات مستهدفة\n"
                f"`!proxies add/remove/list/clear` — إدارة البروكسيات\n"
                f"`!تصفية_الحظر` — مسح Rate Limit\n"
                f"`!stats` — إحصائيات مفصلة"
            ),
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
        await ctx.send(embed=embed, view=UsernameHunterView())
        return

    username_hunter_data["channel_id"] = channel.id
    username_hunter_data["active"] = True
    save_username_hunter()
    if not username_hunter_task.is_running():
        username_hunter_task.start()
    embed = discord.Embed(
        title="✅ تم تعيين قناة الصيد وتشغيله!",
        description=(
            f"├─ **القناة:** {channel.mention}\n"
            f"├─ **المنصات:** 💬 Discord • 🎵 TikTok • 📸 Instagram\n"
            f"├─ **الفاصل:** 15 ثانية\n"
            f"└─ **الحالة:** ✅ يعمل الآن"
        ),
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="صيد", aliases=["صيد状态", "hunter"])
@commands.has_permissions(administrator=True)
async def hunter_control(ctx, action: str = None):
    """تحكم بالصيد: !صيد تشغيل/إيقاف/حالة"""
    if not action:
        embed = discord.Embed(
            title="═══════════════════════════\n🎯 أوامر صيد اليوزرات\n═══════════════════════════",
            description=(
                f"`!صيد تشغيل` — تفعيل الصيد التلقائي\n"
                f"`!صيد إيقاف` — إيقاف الصيد\n"
                f"`!صيد حالة` — عرض الإحصائيات\n"
                f"`!يوزر #قناة` — تعيين قناة الصيد"
            ),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
        await ctx.send(embed=embed)
        return

    if action == "تشغيل":
        if not username_hunter_data.get("channel_id"):
            return await ctx.send("❌ حدد القناة أولاً: `!يوزر #قناة`")
        username_hunter_data["active"] = True
        save_username_hunter()
        if not username_hunter_task.is_running():
            username_hunter_task.start()
        embed = discord.Embed(
            title="✅ تم تفعيل صيد اليوزرات!",
            description=(
            f"├─ **المنصات:** 💬 Discord • 🎵 TikTok • 📸 Instagram\n"
                f"├─ **النوع:** Round-Robin (تناوب دوري)\n"
                f"├─ **الفاصل:** 15 ثانية\n"
                f"└─ **الحماية:** فحص مضاعف + كشف WAF"
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action == "إيقاف":
        username_hunter_data["active"] = False
        save_username_hunter()
        if username_hunter_task.is_running():
            username_hunter_task.cancel()
        await ctx.send("⏸️ تم إيقاف صيد اليوزرات.")

    elif action == "حالة":
        s = username_hunter_data.get("stats", {})
        s.setdefault("total_checks", 0)
        s.setdefault("found", 0)
        s.setdefault("💎", 0)
        s.setdefault("✨", 0)
        s.setdefault("⭐", 0)
        s.setdefault("🔥", 0)
        s.setdefault("per_platform", {})
        ch = ctx.guild.get_channel(username_hunter_data.get("channel_id", 0))
        ch_name = ch.mention if ch else "غير محدد"
        status = "✅ مفعّل" if username_hunter_data.get("active") else "⏸️ متوقف"
        pp = s.get("per_platform", {})
        embed = discord.Embed(
            title="═══════════════════════════\n📊 إحصائيات صيد اليوزرات\n═══════════════════════════",
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="🎯 الحالة", value=status, inline=True)
        embed.add_field(name="📡 القناة", value=ch_name, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="🔍 إجمالي الفحصات", value=f"**{s['total_checks']}**", inline=True)
        embed.add_field(name="🎯 يوزرات مكتشفة", value=f"**{s['found']}**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="💎 نادرة", value=f"**{s.get('💎', 0)}**", inline=True)
        embed.add_field(name="✨ مميزة", value=f"**{s.get('✨', 0)}**", inline=True)
        embed.add_field(name="⭐ ممتازة", value=f"**{s.get('⭐', 0)}**", inline=True)
        embed.add_field(name="🔥 رائعة", value=f"**{s.get('🔥', 0)}**", inline=True)
        embed.add_field(name="💎 مركّب ملكي", value=f"**{username_hunter_data['stats'].get('compound', 0)}**", inline=True)
        platform_lines = []
        for pname, pdata in pp.items():
            pnames = {"discord":"💬 Discord","tiktok":"🎵 TikTok","instagram":"📸 Instagram"}
            platform_lines.append(f"{pnames.get(pname, pname)}: {pdata.get('checked',0)} فحص / {pdata.get('found',0)} صيد")
        embed.add_field(name="═════ إحصائيات المنصات ═══", value="\n".join(platform_lines) if platform_lines else "لا توجد بيانات", inline=False)
        embed.add_field(name="═════ معلومات إضافية ═══", value=f"├─ اليوزرات المستهدفة: {len(target_list)}/5\n├─ البروكسيات النشطة: {len(proxies_list)}\n└─ الكلمات المحظورة: {len(HUNTER_BLACKLIST)} + {len(custom_blacklist)} مخصّصة", inline=False)
        embed.set_footer(text="═══════════════════════════\nMAX BOT • صيد اليوزرات\n═══════════════════════════")
        await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════════
# 🔧 أوامر إدارة الصيد المتقدمة
# ═══════════════════════════════════════════════════════════════

@bot.command(name="بلاك", aliases=["black", "blacklist"])
@commands.has_permissions(administrator=True)
async def blacklist_manage(ctx, action: str = None, *, word: str = None):
    """إدارة القائمة السوداء: !بلاك add/remove <كلمة> أو !بلاك عرض"""
    if not action or action not in ["add", "remove", "عرض", "list"]:
        embed = discord.Embed(
            title="═══════════════════════════\n📋 إدارة القائمة السوداء\n═══════════════════════════",
            description=(
                f"`!بلاك add <كلمة>` — إضافة كلمة محظورة\n"
                f"`!بلاك remove <كلمة>` — حذف كلمة من المحظورات\n"
                f"`!بلاك عرض` — عرض القائمة المخصّصة\n\n"
                f"**الكلمات المدمجة:** {len(HUNTER_BLACKLIST)} كلمة\n"
                f"**المخصّصة:** {len(custom_blacklist)} كلمة"
            ),
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • إدارة البلاك ليست\n═══════════════════════════")
        return await ctx.send(embed=embed)

    if action == "add":
        if not word:
            return await ctx.send("❌ اكتب الكلمة: `!بلاك add <كلمة>`")
        word = word.lower().strip()
        if word in custom_blacklist:
            return await ctx.send(f"⚠️ الكلمة `{word}` موجودة بالفعل في القائمة!")
        custom_blacklist.append(word)
        mark_data_dirty()
        embed = discord.Embed(
            title="✅ تم إضافة كلمة محظورة",
            description=f"├─ **الكلمة:** `{word}`\n├─ **الإجمالي:** {len(custom_blacklist)} كلمة\n└─ **الحالة:** محفوظة في JSON",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البلاك ليست\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action == "remove":
        if not word:
            return await ctx.send("❌ اكتب الكلمة: `!بلاك remove <كلمة>`")
        word = word.lower().strip()
        if word not in custom_blacklist:
            return await ctx.send(f"❌ الكلمة `{word}` غير موجودة في القائمة!")
        custom_blacklist.remove(word)
        mark_data_dirty()
        embed = discord.Embed(
            title="✅ تم حذف كلمة من المحظورات",
            description=f"├─ **الكلمة:** `{word}`\n├─ **المتبقي:** {len(custom_blacklist)} كلمة\n└─ **الحالة:** محفوظ في JSON",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البلاك ليست\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action in ["عرض", "list"]:
        if not custom_blacklist:
            return await ctx.send("📋 القائمة المخصّصة فارغة!")
        words = ", ".join([f"`{w}`" for w in custom_blacklist[:30]])
        embed = discord.Embed(
            title="═══════════════════════════\n📋 القائمة السوداء المخصّصة\n═══════════════════════════",
            description=f"{words}\n\n**الإجمالي:** {len(custom_blacklist)} كلمة",
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البلاك ليست\n═══════════════════════════")
        await ctx.send(embed=embed)


@bot.command(name="البنك", aliases=["bank", "username_bank"])
@commands.has_permissions(administrator=True)
async def show_bank(ctx, mode: str = None):
    """عرض محتوى بنك اليوزرات: !البنك أو !البنك تفاصيل"""
    stats = {}
    for t, words in USERNAME_BANK.items():
        stats[t] = len(words)
    total = sum(stats.values())
    type_names = {
        "premium_3": "✨ ثلاثي نظيف",
        "premium_4": "⭐ رباعي نظيف",
        "premium_cool": "🔥 خمساسي/ستاسي فخم",
        "premium_arabic": "🌍 إنجليزي كلاسيكي",
        "premium_compound": "💎 مركّب مع نقطة/شريط"
    }
    lines = []
    for t, count in stats.items():
        lines.append(f"├─ {type_names.get(t, t)}: **{count}** يوزر")
    lines.append(f"└─ **الإجمالي:** {total} يوزر")
    embed = discord.Embed(
        title="═══════════════════════════\n🏦 بنك اليوزرات المميزة\n═══════════════════════════",
        description="\n".join(lines),
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc)
    )
    if mode == "تفاصيل":
        sample_lines = []
        for t, words in USERNAME_BANK.items():
            sample = random.sample(words, min(5, len(words)))
            sample_lines.append(f"**{type_names.get(t, t)}:** {', '.join(sample)}...")
        embed.add_field(name="═════ عيّنة عشوائية ═══", value="\n".join(sample_lines), inline=False)
    embed.add_field(name="═════ معلومات ═══", value=f"├─ الكلمات المدمرة: {len(HUNTER_BLACKLIST)}\n├─ المخصّصة: {len(custom_blacklist)}\n└─ المستهدفة: {len(target_list)}/5", inline=False)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • بنك اليوزرات\n═══════════════════════════")
    await ctx.send(embed=embed)


@bot.command(name="تصفية_الحظر", aliases=["clear_rate", "clear_ban"])
@commands.has_permissions(administrator=True)
async def clear_rate_limit(ctx):
    """مسح Rate Limit وإعادة تعيين الحماية"""
    global dynamic_blacklist
    old_count = len(dynamic_blacklist)
    dynamic_blacklist = []
    mark_data_dirty()
    try:
        cleanup_rate_limits()
    except Exception:
        pass
    embed = discord.Embed(
        title="🧹 تم تصفية الحماية بالكامل",
        description=(
            f"├─ **المحظورات المؤقتة المحذوفة:** {old_count}\n"
            f"├─ **الذاكرة المؤقتة للـ Scraper:** مُفرّغة\n"
            f"└─ **الحالة:** ✅ البوت يعمل بنظافة كاملة"
        ),
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • إعادة تعيين الحماية\n═══════════════════════════")
    await ctx.send(embed=embed)


@bot.command(name="صيد_مستهدف", aliases=["target", "target_hunt"])
@commands.has_permissions(administrator=True)
async def target_manage(ctx, action: str = None, *, username: str = None):
    """إدارة اليوزرات المستهدفة: !صيد_مستهدف add/clear/list"""
    if not action or action not in ["add", "clear", "list", "حذف"]:
        embed = discord.Embed(
            title="═══════════════════════════\n🎯 إدارة اليوزرات المستهدفة\n═══════════════════════════",
            description=(
                f"`!صيد_مستهدف add <يوزر>` — إضافة يوزر مستهدف\n"
                f"`!صيد_مستهدف list` — عرض القائمة\n"
                f"`!صيد_مستهدف clear` — مسح الكل\n\n"
                f"**الحد الأقصى:** 5 أسماء\n"
                f"**الحالي:** {len(target_list)}/5"
            ),
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • الصيد المستهدف\n═══════════════════════════")
        return await ctx.send(embed=embed)

    if action == "add":
        if not username:
            return await ctx.send("❌ اكتب اليوزر: `!صيد_مست目标 add <يوزر>`")
        username = username.lower().strip().replace("@", "").replace("https://discord.com/users/", "")
        if len(target_list) >= 5:
            return await ctx.send("❌ القائمة ممتلئة! الحد الأقصى 5 أسماء. استخدم `!صيد_مستهدف clear` للمسح")
        if username in target_list:
            return await ctx.send(f"⚠️ `{username}` موجود بالفعل في القائمة!")
        target_list.append(username)
        mark_data_dirty()
        embed = discord.Embed(
            title="✅ تم إضافة اليوزر المستهدف",
            description=(
                f"├─ **اليوزر:** `{username}`\n"
                f"├─ **القائمة:** {len(target_list)}/5\n"
                f"└─ **الحالة:** سيفحَّص بأولوية عالية"
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • الصيد المستهدف\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action == "clear":
        target_list.clear()
        mark_data_dirty()
        await ctx.send("🗑️ تم مسح جميع اليوزرات المستهدفة!")

    elif action in ["list", "عرض"]:
        if not target_list:
            return await ctx.send("📋 لا توجد يوزرات مستهدفة حالياً!")
        lines = [f"├─ `{i+1}. {u}`" for i, u in enumerate(target_list)]
        lines.append(f"└─ **الإجمالي:** {len(target_list)}/5")
        embed = discord.Embed(
            title="═══════════════════════════\n🎯 اليوزرات المستهدفة\n═══════════════════════════",
            description="\n".join(lines),
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • الصيد المستهدف\n═══════════════════════════")
        await ctx.send(embed=embed)


@bot.command(name="proxies", aliases=["بروكسي", "proxy"])
@commands.has_permissions(administrator=True)
async def proxies_manage(ctx, action: str = None, *, proxy: str = None):
    """إدارة البروكسيات: !proxies add/remove/list/clear"""
    if not action or action not in ["add", "remove", "list", "clear", "حذف", "عرض"]:
        embed = discord.Embed(
            title="═══════════════════════════\n🌐 إدارة البروكسيات\n═══════════════════════════",
            description=(
                f"`!proxies add <ip:port>` — إضافة بروكسي\n"
                f"`!proxies remove <ip:port>` — حذف بروكسي\n"
                f"`!proxies list` — عرض القائمة\n"
                f"`!proxies clear` — مسح الكل\n\n"
                f"**العدد الحالي:** {len(proxies_list)}"
            ),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • إدارة البروكسيات\n═══════════════════════════")
        return await ctx.send(embed=embed)

    if action == "add":
        if not proxy:
            return await ctx.send("❌ اكتب البروكسي: `!proxies add ip:port`")
        proxy = proxy.strip()
        if proxy in proxies_list:
            return await ctx.send(f"⚠️ البروكسي `{proxy}` موجود بالفعل!")
        proxies_list.append(proxy)
        mark_data_dirty()
        embed = discord.Embed(
            title="✅ تم إضافة البروكسي",
            description=(
                f"├─ **البروكسي:** `{proxy}`\n"
                f"├─ **العدد:** {len(proxies_list)}\n"
                f"└─ **الحالة:** محفوظ في JSON"
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البروكسيات\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action in ["remove", "حذف"]:
        if not proxy:
            return await ctx.send("❌ اكتب البروكسي: `!proxies remove ip:port`")
        proxy = proxy.strip()
        if proxy not in proxies_list:
            return await ctx.send(f"❌ البروكسي `{proxy}` غير موجود!")
        proxies_list.remove(proxy)
        mark_data_dirty()
        embed = discord.Embed(
            title="✅ تم حذف البروكسي",
            description=(
                f"├─ **البروكسي:** `{proxy}`\n"
                f"├─ **المتبقي:** {len(proxies_list)}\n"
                f"└─ **الحالة:** محفوظ في JSON"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البروكسيات\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action in ["list", "عرض"]:
        if not proxies_list:
            return await ctx.send("📋 لا توجد بروكسيات محفوظة!")
        lines = [f"├─ `{i+1}. {p}`" for i, p in enumerate(proxies_list[:20])]
        lines.append(f"└─ **الإجمالي:** {len(proxies_list)}")
        embed = discord.Embed(
            title="═══════════════════════════\n🌐 البروكسيات المحفوظة\n═══════════════════════════",
            description="\n".join(lines),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="═══════════════════════════\nMAX BOT • البروكسيات\n═══════════════════════════")
        await ctx.send(embed=embed)

    elif action == "clear":
        proxies_list.clear()
        mark_data_dirty()
        await ctx.send("🗑️ تم مسح جميع البروكسيات!")


@bot.command(name="فحص", aliases=["check", "f7is"])
@commands.has_permissions(administrator=True)
async def quick_check(ctx, *, username: str = None):
    """فحص سريع وتصنيف فوري لاسم واحد: !فحص <يوزر>"""
    if not username:
        return await ctx.send("💡 اكتب الاسم للفحص، مثال: `!فحص x_yz`")
    username = username.lower().strip().replace("@", "").replace("https://discord.com/users/", "")
    if not validate_username_for_platform(username, "discord"):
        return await ctx.send("❌ الاسم لا يطابق الشروط أو قصير جداً من سيستم ديسكورد الجديد!")
    emoji, label, _ = classify_username(username)
    if not label:
        return await ctx.send(f"⚠️ اليوزر `{username}` يقع تحت بنود الكلمات الشائعة المحظورة أو تائه في البلاك ليست.")
    embed = discord.Embed(
        title=f"🔍 نتيجة الفحص الفوري",
        description=(
            f"├─ **اليوزر:** `{username}`\n"
            f"├─ **التصنيف:** {emoji} **{label}**\n"
            f"├─ **الطول:** {len(username)} أحرف\n"
            f"├─ **النوع:** {'مركّب ملكي' if '.' in username or '_' in username else 'نظيف'}\n"
            f"└─ **الحالة:** ✅ صالح للاستخدام"
        ),
        color=0x00BFFF,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • فحص سريع\n═══════════════════════════")
    await ctx.send(embed=embed)


@bot.command(name="gen", aliases=["توليد", "generate"])
@commands.has_permissions(administrator=True)
async def gen_usernames(ctx, count: int = 5):
    """توليد قائمة عشوائية من اليوزرات الفخمة: !gen [عدد]"""
    count = max(1, min(count, 15))
    gen_list = [generate_username("discord") for _ in range(count)]
    lines = [f"├─ `{u}` — {'💎' if '.' in u or '_' in u else '⭐'}" for u in gen_list]
    embed = discord.Embed(
        title=f"💡 {count} يوزرات متولدة فخمة",
        description="\n".join(lines),
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • توليد يوزرات\n═══════════════════════════")
    await ctx.send(embed=embed)


@bot.command(name="hunter_stats", aliases=["إحصائيات_صياد", "إحصائيات"])
@commands.has_permissions(administrator=True)
async def hunter_stats_detailed(ctx):
    """عرض إحصائيات الصيد المفصلة"""
    s = username_hunter_data.get("stats", {})
    s.setdefault("total_checks", 0)
    s.setdefault("found", 0)
    s.setdefault("💎", 0)
    s.setdefault("✨", 0)
    s.setdefault("⭐", 0)
    s.setdefault("🔥", 0)
    s.setdefault("per_platform", {})
    pp = s.get("per_platform", {})
    status = "✅ مفعّل" if username_hunter_data.get("active") else "⏸️ متوقف"
    embed = discord.Embed(
        title="═══════════════════════════\n📊 إحصائيات الصيد الشاملة\n═══════════════════════════",
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="🎯 الحالة", value=status, inline=True)
    embed.add_field(name="🔍 إجمالي الفحصات", value=f"**{s['total_checks']}**", inline=True)
    embed.add_field(name="🎯 مكتشفة", value=f"**{s['found']}**", inline=True)
    embed.add_field(name="💎 نادرة", value=f"**{s.get('💎', 0)}**", inline=True)
    embed.add_field(name="✨ مميزة", value=f"**{s.get('✨', 0)}**", inline=True)
    embed.add_field(name="⭐ ممتازة", value=f"**{s.get('⭐', 0)}**", inline=True)
    embed.add_field(name="🔥 رائعة", value=f"**{s.get('🔥', 0)}**", inline=True)
    platform_lines = []
    for pname, pdata in pp.items():
        pnames = {"discord":"💬 Discord","tiktok":"🎵 TikTok","instagram":"📸 Instagram"}
        platform_lines.append(f"{pnames.get(pname, pname)}: {pdata.get('checked',0)} فحص / {pdata.get('found',0)} صيد")
    embed.add_field(name="═════ إحصائيات المنصات ═══", value="\n".join(platform_lines) if platform_lines else "لا توجد بيانات", inline=False)
    embed.add_field(name="═════ معلومات النظام ═══", value=(
        f"├─ بنك اليوزرات: {sum(len(v) for v in USERNAME_BANK.values())} يوزر\n"
        f"├─ الكلمات المدمرة: {len(HUNTER_BLACKLIST)}\n"
        f"├─ المخصّصة: {len(custom_blacklist)}\n"
        f"├─ المحظورات المؤقتة: {len(dynamic_blacklist)}\n"
        f"├─ المستهدفة: {len(target_list)}/5\n"
        f"└─ البروكسيات: {len(proxies_list)}"
    ), inline=False)
    embed.set_footer(text="═══════════════════════════\nMAX BOT • إحصائيات شاملة\n═══════════════════════════")
    await ctx.send(embed=embed)


@bot.command(name="تست_صيد", aliases=["test_bait"])
@commands.has_permissions(administrator=True)
async def test_hacker_bait(ctx):
    """اختبار نظام صيد الهاكرز"""
    guild_id = ctx.guild.id
    bait_ch_id = hacker_bait_channels.get(guild_id)
    if not bait_ch_id:
        return await ctx.send("❌ ما في قناة فخ محددة! استخدم `!صيد_الهكر` أول شي.")
    bait_ch = ctx.guild.get_channel(bait_ch_id)
    if not bait_ch:
        return await ctx.send("❌ قناة الفخ غير موجودة!")
    test_embed = discord.Embed(
        title="🔐 حماية السيرفر",
        description=(
            "**مرحباً بك في سيرفر MAX POT**\n\n"
            "للحماية من الاختراق، يرجى التحقق من حسابك:\n"
            "أرسل رمز التحقق الخاص بك هنا.\n\n"
            "**⚠️ هذا اختبار من النظام**"
        ),
        color=0xFF4444
    )
    test_embed.set_footer(text="MAX BOT • حماية السيرفر")
    await bait_ch.send(embed=test_embed)
    await ctx.send(f"✅ تم اختبار الفخ في {bait_ch.mention}")

# ═══════════════════════════════════════════════════════════════
# 🛡️ نظام الحماية السيبرانية — Honeypot Commands
# ═══════════════════════════════════════════════════════════════

@bot.command(name="حظر_عتاد", aliases=["ban_hardware", "حظر_جهاز"])
@commands.has_permissions(administrator=True)
async def ban_hardware(ctx, device_hash: str = None):
    """حظر جهاز بالكامل عبر device_hash: !حظر_عتاد <hash>"""
    if not device_hash:
        return await ctx.send("❌ اكتب الـ device_hash: `!حظر_عتاد <hash>`")
    device_hash = device_hash.strip()
    if device_hash in hardware_bans:
        return await ctx.send(f"⚠️ الجهاز `{device_hash[:16]}...` محظور بالفعل!")
    hardware_bans.append(device_hash)
    mark_data_dirty()
    embed = discord.Embed(
        title="🔒 تم حظر الجهاز بالكامل",
        description=(
            f"├─ **البصمة:** `{device_hash[:16]}...`\n"
            f"├─ **الإجمالي:** {len(hardware_bans)} جهاز محظور\n"
            f"└─ **الحالة:** حظر أبدي — لا يمكن تخطيه حتى بحسابات جديدة"
        ),
        color=0xFF4444,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • الحماية السيبرانية\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="فك_حظر_عتاد", aliases=["unban_hardware"])
@commands.has_permissions(administrator=True)
async def unban_hardware(ctx, device_hash: str = None):
    """إلغاء حظر جهاز: !فك_حظر_عتاد <hash>"""
    if not device_hash:
        return await ctx.send("❌ اكتب الـ device_hash: `!فك_حظر_عتاد <hash>`")
    device_hash = device_hash.strip()
    if device_hash not in hardware_bans:
        return await ctx.send(f"❌ الجهاز `{device_hash[:16]}...` غير محظور!")
    hardware_bans.remove(device_hash)
    mark_data_dirty()
    embed = discord.Embed(
        title="✅ تم إلغاء حظر الجهاز",
        description=(
            f"├─ **البصمة:** `{device_hash[:16]}...`\n"
            f"├─ **المتبقي:** {len(hardware_bans)} جهاز محظور\n"
            f"└─ **الحالة:** مسموح بالدخول الآن"
        ),
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • الحماية السيبرانية\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="بصمات", aliases=["fingerprints", "fp"])
@commands.has_permissions(administrator=True)
async def show_fingerprints(ctx):
    """عرض البصمات المحجوزة والمحظورة"""
    fp_count = len(fingerprints)
    ban_count = len(hardware_bans)
    recent = sorted(fingerprints.items(), key=lambda x: x[1].get("collected_at", ""), reverse=True)[:5]
    lines = []
    for key, fp in recent:
        ip = fp.get("ip", "?")
        gpu = fp.get("gpu_renderer", "?")[:30]
        device = fp.get("device_hash", "?")[:12]
        no_js = "🔴 معطل" if fp.get("no_js") else "🟢 نشط"
        lines.append(f"├─ `{key}` | IP: `{ip}` | GPU: {gpu}... | JS: {no_js}")
    embed = discord.Embed(
        title="═══════════════════════════\n🖐️ بصمات الحماية السيبرانية\n═══════════════════════════",
        description=(
            f"├─ **إجمالي البصمات:** {fp_count}\n"
            f"├─ **أجهزة محظورة:** {ban_count}\n"
            f"└─ **آخر 5 بصمات:**\n" + "\n".join(lines) if lines else "└─ **لا توجد بصمات بعد**"
        ),
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • بصمات الحماية\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="قائمة_الحظر", aliases=["ban_list", "hardware_bans"])
@commands.has_permissions(administrator=True)
async def ban_list(ctx):
    """عرض قائمة الأجهزة المحظورة"""
    if not hardware_bans:
        return await ctx.send("📋 لا توجد أجهزة محظورة حالياً!")
    lines = [f"├─ `{i+1}. {h[:16]}...`" for i, h in enumerate(hardware_bans[:20])]
    lines.append(f"└─ **الإجمالي:** {len(hardware_bans)} جهاز")
    embed = discord.Embed(
        title="═══════════════════════════\n🔒 قائمة الأجهزة المحظورة\n═══════════════════════════",
        description="\n".join(lines),
        color=0xFF4444,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • الحماية السيبرانية\n═══════════════════════════")
    await ctx.send(embed=embed)

@bot.command(name="تنظيف_البصمات", aliases=["cleanup_fps"])
@commands.has_permissions(administrator=True)
async def cleanup_fps(ctx):
    """مسح البصمات القديمة (> 90 يوم)"""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).isoformat()
    old_count = len(fingerprints)
    cleaned = {k: v for k, v in fingerprints.items() if v.get("collected_at", "") >= cutoff}
    removed = old_count - len(cleaned)
    fingerprints.clear()
    fingerprints.update(cleaned)
    mark_data_dirty()
    embed = discord.Embed(
        title="🧹 تم تطهير البصمات القديمة",
        description=(
            f"├─ **قبل:** {old_count} بصمة\n"
            f"├─ **بعد:** {len(fingerprints)} بصمة\n"
            f"├─ **تم حذفها:** {removed} بصمة (> 90 يوم)\n"
            f"└─ **الحالة:** ✅ الذاكرة خفيفة وسريعة"
        ),
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="═══════════════════════════\nMAX BOT • تنظيف البصمات\n═══════════════════════════")
    await ctx.send(embed=embed)

bot.run(DISCORD_TOKEN)
