import time
import discord
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# ════════════════════════════════════════
# نظام التصعيد الافتراضي
# ════════════════════════════════════════

PUNISHMENT_CONFIG = {
    "spam": {
        "name": "السبام",
        "levels": [
            {"score": 1, "action": "warn", "duration": 0, "label": "تحذير"},
            {"score": 2, "action": "timeout", "duration": 30, "label": "كتم 30 ثانية"},
            {"score": 3, "action": "timeout", "duration": 300, "label": "كتم 5 دقائق"},
            {"score": 4, "action": "timeout", "duration": 3600, "label": "كتم ساعة"},
            {"score": 5, "action": "kick", "duration": 0, "label": "طرد"},
            {"score": 6, "action": "ban", "duration": 0, "label": "حظر"},
        ]
    },
    "flood": {
        "name": "الفلود",
        "levels": [
            {"score": 1, "action": "delete", "duration": 0, "label": "حذف الرسالة"},
        ]
    },
    "mention": {
        "name": "المنشن الجماعي",
        "levels": [
            {"score": 1, "action": "timeout", "duration": 300, "label": "كتم 5 دقائق"},
            {"score": 2, "action": "timeout", "duration": 3600, "label": "كتم ساعة"},
        ]
    },
    "badwords": {
        "name": "الكلمات الممنوعة",
        "levels": [
            {"score": 1, "action": "delete", "duration": 0, "label": "حذف الرسالة"},
            {"score": 2, "action": "warn", "duration": 0, "label": "تحذير"},
            {"score": 3, "action": "timeout", "duration": 600, "label": "كتم 10 دقائق"},
        ]
    },
    "alt": {
        "name": "حساب جديد",
        "levels": [
            {"score": 1, "action": "timeout", "duration": 3600, "label": "كتم ساعة"},
        ]
    },
    "invite": {
        "name": "رابط سيرفر آخر",
        "levels": [
            {"score": 1, "action": "warn", "duration": 0, "label": "تحذير"},
            {"score": 2, "action": "timeout", "duration": 3600, "label": "كتم ساعة"},
            {"score": 3, "action": "ban", "duration": 0, "label": "حظر"},
        ]
    },
    "raid_join": {
        "name": "دخول جماعي",
        "levels": [
            {"score": 1, "action": "kick", "duration": 0, "label": "طرد"},
        ]
    },
}


# ════════════════════════════════════════
# كاشف السبام الذكي
# ════════════════════════════════════════

class SpamDetector:
    def __init__(self):
        self._scores = {}

    def check(self, user_id):
        now = time.time()
        data = self._scores.get(user_id, {"times": [], "score": 0, "last_decay": now})
        data["times"] = [t for t in data["times"] if now - t < 30]
        data["times"].append(now)

        if now - data["last_decay"] > 60:
            data["score"] = max(0, data["score"] - 1)
            data["last_decay"] = now

        count_5 = len([t for t in data["times"] if now - t < 5])
        count_10 = len([t for t in data["times"] if now - t < 10])
        count_30 = len([t for t in data["times"] if now - t < 30])

        if count_30 >= 30:
            data["score"] = max(data["score"], 5)
        elif count_10 >= 20:
            data["score"] = max(data["score"], 4)
        elif count_10 >= 15:
            data["score"] = max(data["score"], 3)
        elif count_5 >= 10:
            data["score"] = max(data["score"], 2)
        elif count_5 >= 5:
            data["score"] = max(data["score"], 1)

        self._scores[user_id] = data
        return data["score"]

    def get_punishment(self, score, prot_type="spam"):
        levels = PUNISHMENT_CONFIG.get(prot_type, PUNISHMENT_CONFIG["spam"])["levels"]
        best = levels[0]
        for lvl in levels:
            if score >= lvl["score"]:
                best = lvl
        return best

    def decay(self, user_id):
        now = time.time()
        data = self._scores.get(user_id)
        if not data or now - data["last_decay"] > 120:
            self._scores.pop(user_id, None)


# ════════════════════════════════════════
# كاشف الدخول الجماعي (Raid)
# ════════════════════════════════════════

class RaidDetector:
    def __init__(self):
        self._joins = defaultdict(list)
        self._raid_mode = {}

    def check(self, guild_id, timestamp=None):
        now = timestamp or time.time()
        joins = self._joins[guild_id]
        joins.append(now)
        joins[:] = [t for t in joins if now - t < 30]

        count_10 = len([t for t in joins if now - t < 10])
        count_30 = len([t for t in joins if now - t < 30])

        if count_10 >= 5:
            self._raid_mode[guild_id] = True
            return "raid"
        if count_30 >= 10:
            return "alert"
        return "safe"

    def is_raid(self, guild_id):
        return self._raid_mode.get(guild_id, False)

    def disable_raid(self, guild_id):
        self._raid_mode[guild_id] = False
        self._joins[guild_id] = []

    def get_raid_mode(self):
        return self._raid_mode


# ════════════════════════════════════════
# حماية الحذف الجماعي (Anti-Nuke)
# ════════════════════════════════════════

class AntiNuke:
    def __init__(self):
        self._delete_log = defaultdict(list)
        self._nuked = {}
        self._enabled = {}

    def set_enabled(self, guild_id, state):
        self._enabled[guild_id] = state
        if not state:
            self._nuked.pop(guild_id, None)
        return state

    def is_enabled(self, guild_id):
        return self._enabled.get(guild_id, True)

    def is_nuked(self, guild_id):
        return self._nuked.get(guild_id, {}).get("active", False)

    def check_channel_delete(self, guild_id, channel, is_voice):
        if is_voice:
            return False
        now = time.time()
        log = self._delete_log[f"ch_{guild_id}"]
        log.append({"id": channel.id, "name": channel.name, "type": "text", "time": now})
        log[:] = [x for x in log if now - x["time"] < 10]
        if len(log) >= 3:
            self._nuked[guild_id] = {"active": True, "type": "channels", "time": now, "items": list(log)}
            return True
        return False

    def check_role_delete(self, guild_id, role):
        now = time.time()
        log = self._delete_log[f"role_{guild_id}"]
        log.append({"id": role.id, "name": role.name, "color": str(role.color), "permissions": role.permissions.value, "time": now})
        log[:] = [x for x in log if now - x["time"] < 10]
        if len(log) >= 3:
            self._nuked[guild_id] = {"active": True, "type": "roles", "time": now, "items": list(log)}
            return True
        return False

    def get_nuked_items(self, guild_id):
        data = self._nuked.get(guild_id)
        return data.get("items", []) if data else []

    def get_nuke_type(self, guild_id):
        data = self._nuked.get(guild_id)
        return data.get("type") if data else None

    def disable_nuke(self, guild_id):
        self._nuked.pop(guild_id, None)
        self._delete_log.pop(f"ch_{guild_id}", None)
        self._delete_log.pop(f"role_{guild_id}", None)

    def get_enabled_data(self):
        return dict(self._enabled)

    def set_enabled_data(self, data):
        self._enabled = data

    def clear_guild(self, guild_id):
        self._nuked.pop(guild_id, None)
        self._delete_log.pop(f"ch_{guild_id}", None)
        self._delete_log.pop(f"role_{guild_id}", None)
        self._enabled.pop(guild_id, None)


# ════════════════════════════════════════
# مدير العقوبات (تصعيد تدريجي)
# ════════════════════════════════════════

class PunishmentManager:
    def __init__(self):
        self._warnings = {}

    def get_warning_count(self, guild_id, user_id, prot_type):
        return self._warnings.get(guild_id, {}).get(user_id, {}).get(prot_type, 0)

    def increment_warning(self, guild_id, user_id, prot_type):
        g = self._warnings.setdefault(guild_id, {})
        u = g.setdefault(user_id, {})
        u[prot_type] = u.get(prot_type, 0) + 1
        return u[prot_type]

    def reset_warnings(self, guild_id, user_id, prot_type=None):
        if guild_id not in self._warnings:
            return
        if user_id not in self._warnings[guild_id]:
            return
        if prot_type:
            self._warnings[guild_id][user_id].pop(prot_type, None)
        else:
            self._warnings[guild_id][user_id] = {}

    async def execute(self, guild, user, prot_type, score, reason=None):
        config = PUNISHMENT_CONFIG.get(prot_type, PUNISHMENT_CONFIG["spam"])
        levels = config["levels"]
        action_desc = ""

        for lvl in reversed(levels):
            if score >= lvl["score"]:
                action = lvl["action"]
                duration = lvl["duration"]
                action_desc = lvl["label"]

                if action == "delete":
                    return f"🗑️ حذف الرسالة"

                elif action == "warn":
                    self.increment_warning(guild.id, user.id, prot_type)
                    warns = self.get_warning_count(guild.id, user.id, prot_type)
                    return f"⚠️ تحذير #{warns} للـ {config['name']}"

                elif action == "timeout":
                    try:
                        await user.timeout(discord.utils.utcnow() + timedelta(seconds=duration), reason=f"حماية: {config['name']}")
                        return f"🔇 كتم {duration // 60} دقيقة" if duration >= 60 else f"🔇 كتم {duration} ثانية"
                    except discord.Forbidden:
                        return f"❌ فشل الكتم (صلاحيات غير كافية)"
                    except Exception as e:
                        return f"❌ فشل الكتم: {e}"

                elif action == "kick":
                    try:
                        await user.kick(reason=f"حماية: {config['name']}")
                        return "👢 طرد"
                    except discord.Forbidden:
                        return "❌ فشل الطرد (صلاحيات غير كافية)"
                    except Exception as e:
                        return f"❌ فشل الطرد: {e}"

                break

        return action_desc

    def get_punishment_action(self, prot_type, score):
        """ترجع معلومات العقاب {action, duration, label} بدون تنفيذ"""
        config = PUNISHMENT_CONFIG.get(prot_type, PUNISHMENT_CONFIG["spam"])
        for lvl in reversed(config["levels"]):
            if score >= lvl["score"]:
                return dict(lvl)
        return None

    def get_warnings_data(self):
        return dict(self._warnings)

    def set_warnings_data(self, data):
        self._warnings = data

    def clear_guild(self, guild_id):
        self._warnings.pop(guild_id, None)


# ════════════════════════════════════════
# مدير الاستثناءات (Whitelist)
# ════════════════════════════════════════

class WhitelistManager:
    def __init__(self):
        self._whitelist = {}

    def is_whitelisted(self, guild_id, channel_id, prot_type):
        g = self._whitelist.get(guild_id, {})
        ch = g.get(channel_id, [])
        return prot_type in ch or "all" in ch

    def toggle(self, guild_id, channel_id, prot_type):
        g = self._whitelist.setdefault(guild_id, {})
        ch = g.setdefault(channel_id, [])
        if prot_type in ch:
            ch.remove(prot_type)
            return False
        else:
            ch.append(prot_type)
            return True

    def get_whitelist(self, guild_id):
        return self._whitelist.get(guild_id, {})

    def set_whitelist(self, guild_id, data):
        self._whitelist[guild_id] = data

    def get_all(self):
        return dict(self._whitelist)

    def set_all(self, data):
        self._whitelist = data

    def clear_guild(self, guild_id):
        self._whitelist.pop(guild_id, None)


# ════════════════════════════════════════
# أسماء الحمايات
# ════════════════════════════════════════

PROTECTION_NAMES = {
    "spam": "🚫 سبام",
    "flood": "📋 فلود",
    "mention": "👥 منشن",
    "badwords": "🔇 كلمات",
    "invite": "🔗 انفايت",
    "alt": "🆕 الت",
    "raid": "🚫 ريد",
}
