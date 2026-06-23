import discord
from datetime import datetime, timezone
from collections import deque
import time
import json

LOG_ICONS = {
    "log_messages":      "✏️",
    "log_messages_del":  "🗑️",
    "protection_security":"🛡️",
    "log_all":           "📋",
    "ban_kick_timeout":  "⚖️",
    "log_role":          "👑",
    "log_edit_role":     "⚙️👑",
    "log_nickname":      "🏷️",
    "log_leave":         "🚪",
    "log_admin_leave":   "⭐",
    "log_voice":         "🎤",
    "log_channels":      "📁",
    "log_channels_del":  "🗑️📁",
    "log_edit_role_del": "🗑️👑",
    "ticket_open":       "🎫",
    "ticket_close":      "🔒",
    "log_join":          "📥",
    "log_invite":        "📨",
    "log_emoji_sticker": "😀",
    "log_thread":        "🧵",
    "log_webhook":       "🔗",
    "log_integration":   "🔌",
    "log_stage":         "🎙️",
    "log_automod":       "🤖",
    "log_channel_perm":  "🔐",
    "log_pin_bulk":      "📌",
    "log_scheduled_event":"📅",
    "log_misc":          "📦",
    "log_activity":      "🎮",
    "log_new_message":   "💬",
    "log_hacking":       "🔎",
}

class LogColors:
    EDIT        = 0x3498DB
    DELETE      = 0xE74C3C
    CREATE      = 0x2ECC71
    WARN        = 0xF1C40F
    MOD         = 0x9B59B6
    PROTECT     = 0x000000
    JOIN        = 0x00FFAA
    LEAVE       = 0xFF6600
    VOICE       = 0x7289DA
    TIMEOUT     = 0xE67E22
    NUKE        = 0xFF0000
    ROLE        = 0x5865F2
    TICKET      = 0x00BFFF
    HACKING     = 0xFF4444
    ACTIVITY_GAME   = 0x7289DA
    ACTIVITY_SPOTIFY = 0x1DB954
    ACTIVITY_WATCH   = 0xFF6B6B
    ACTIVITY_STREAM  = 0x9146FF
    ACTIVITY_CUSTOM  = 0x5865F2

class LogEmbed:
    @staticmethod
    def base(title, color, guild=None, description=None, icon=""):
        icon = icon or LOG_ICONS.get(title, "")
        embed = discord.Embed(
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        if title:
            embed.title = f"{icon}  {title}" if icon else title
        if description:
            embed.description = description
        if guild:
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.set_footer(
                text=f"═══════════════════════════\n🌐  {guild.name}  •  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n═══════════════════════════",
                icon_url=guild.icon.url if guild.icon else None
            )
        return embed

    @staticmethod
    def user_field(embed, user, label="👤 العضو", thumb=False):
        roles_text = ""
        if hasattr(user, 'roles') and len(user.roles) > 1:
            roles = [r.mention for r in reversed(user.roles[1:])][:5]
            roles_text = "\n".join(roles)
        lines = [
            f"├─ المعرف: `{user.id}`",
            f"├─ الاسم: **{user.name}**",
        ]
        if roles_text:
            lines.append(f"├─ الرتب:")
            for r in roles_text.split("\n"):
                lines.append(f"│   {r}")
        lines.append(f"└─ الأفاتار: [صورة]({user.display_avatar.url})")
        embed.add_field(name=label, value="\n".join(lines), inline=False)
        embed.set_author(
            name=f"═══ {user.display_name} ═══",
            icon_url=user.display_avatar.url
        )
        if thumb:
            embed.set_thumbnail(url=user.display_avatar.url)
        return embed

    @staticmethod
    def audit_field(embed, admin, label="👨‍⚖️ المنفذ"):
        if admin:
            embed.add_field(name=label, value=f"└── {admin.mention} (`{admin.id}`)", inline=False)
        else:
            embed.add_field(name=label, value="└── غير معروف ❓ (يفتقد صلاحية View Audit Log)", inline=False)
        return embed

    @staticmethod
    def channel_field(embed, label, channel):
        embed.add_field(name=label, value=f"{channel.mention} `#{channel.name}`", inline=True)
        return embed

    @staticmethod
    def diff_field(embed, label, before, after, max_len=1024):
        diff = f"```diff\n- {before}\n+ {after}\n```"
        if len(diff) > max_len:
            diff = diff[:max_len-3] + "..."
        embed.add_field(name=label, value=diff, inline=False)
        return embed

    @staticmethod
    def reason_field(embed, reason):
        embed.add_field(name="📋 التفاصيل", value=f"├─ السبب: {reason or 'بدون سبب'}", inline=False)
        return embed

    @staticmethod
    def action_field(embed, action_desc):
        embed.add_field(name="📋 التفاصيل", value=f"├─ الإجراء: {action_desc}", inline=False)
        return embed

    @staticmethod
    def details_field(embed, reason=None, action=None):
        lines = []
        if reason:
            lines.append(f"├─ السبب: {reason}")
        if action:
            lines.append(f"└─ الإجراء: {action}")
        if lines:
            embed.add_field(name="📋 التفاصيل", value="\n".join(lines), inline=False)
        return embed

    @staticmethod
    def role_field(embed, roles, label="🎭 الرتب"):
        if not roles:
            return embed
        lines = []
        for i, role in enumerate(roles):
            prefix = "├─" if i < len(roles) - 1 else "└─"
            lines.append(f"{prefix} {role.mention} (`{role.id}`)")
        embed.add_field(name=label, value="\n".join(lines), inline=False)
        return embed

    @staticmethod
    def evidence_field(embed, message_data=None, message=None, jump_url=""):
        if message_data:
            content = message_data.get("content", "")
            author = message_data.get("author_name", "?")
            chan = message_data.get("channel_name", "?")
            jmp = message_data.get("jump_url", jump_url)
            atch = message_data.get("attachments", [])
        elif message:
            content = message.content or ""
            author = str(message.author)
            chan = message.channel.name if hasattr(message.channel, 'name') else "?"
            jmp = message.jump_url
            atch = [a.url for a in message.attachments]
        else:
            return embed

        parts = []
        if content:
            parts.append(f"> {content[:800]}")
        if jmp:
            parts.append(f"🔗 [قفز للرسالة]({jmp})")
        if atch:
            parts.append(f"📎 المرفقات: {' '.join(atch[:3])}")
        if parts:
            embed.add_field(name="📄 دليل المخالفة", value="\n".join(parts), inline=False)
        return embed

    @staticmethod
    def voice_field(embed, label, before_state, after_state):
        lines = []
        if before_state.mute != after_state.mute:
            val = "🔇 مكتوم" if after_state.mute else "🔊 غير مكتوم"
            lines.append(f"├─ الميك: {val}")
        if before_state.deaf != after_state.deaf:
            val = "🔇 أصم" if after_state.deaf else "🔊 غير أصم"
            lines.append(f"├─ السماعة: {val}")
        if before_state.self_mute != after_state.self_mute:
            val = "🔇 مكتوم ذاتياً" if after_state.self_mute else "🔊 فتح الميك"
            lines.append(f"├─ الميك الذاتي: {val}")
        if before_state.self_deaf != after_state.self_deaf:
            val = "🔇 أصم ذاتياً" if after_state.self_deaf else "🔊 فتح السماعة"
            lines.append(f"├─ السماعة الذاتية: {val}")
        if before_state.channel != after_state.channel:
            if before_state.channel and after_state.channel:
                lines.append(f"└─ الانتقال: {before_state.channel.mention} → {after_state.channel.mention}")
            elif after_state.channel:
                lines.append(f"└─ الدخول: {after_state.channel.mention}")
            elif before_state.channel:
                lines.append(f"└─ الخروج: {before_state.channel.mention}")
        if lines:
            embed.add_field(name=label, value="\n".join(lines), inline=False)
        return embed

    @staticmethod
    def message_field(embed, message, label="📝 الرسالة"):
        lines = [f"├─ الروم: {message.channel.mention}"]
        if message.content:
            lines.append(f"├─ المحتوى: {message.content[:800]}")
        if message.attachments:
            atts = "\n".join([f"│   📎 [{a.filename}]({a.url})" for a in message.attachments[:3]])
            lines.append(f"├─ المرفقات:\n{atts}")
        lines.append(f"└─ [قفز للرسالة]({message.jump_url})")
        embed.add_field(name=label, value="\n".join(lines), inline=False)
        return embed

    @staticmethod
    def divider(embed):
        embed.add_field(name="═══════════════════════════", value="\u200b", inline=False)
        return embed


class MessageCache:
    def __init__(self, max_size=3000):
        self._cache = {}
        self._max = max_size

    def add(self, message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else 0
        if guild_id not in self._cache:
            self._cache[guild_id] = deque(maxlen=self._max)
        self._cache[guild_id].append({
            "id": message.id,
            "author_id": message.author.id,
            "author_name": message.author.name,
            "author_display": message.author.display_name,
            "author_avatar": str(message.author.display_avatar.url),
            "content": message.content or "",
            "channel_id": message.channel.id,
            "channel_name": message.channel.name,
            "timestamp": message.created_at.timestamp(),
            "attachments": [a.url for a in message.attachments],
            "jump_url": message.jump_url,
        })

    def get(self, guild_id, message_id):
        if guild_id not in self._cache:
            return None
        for msg in self._cache[guild_id]:
            if msg["id"] == message_id:
                return msg
        return None

    def get_last_in_channel(self, guild_id, channel_id):
        if guild_id not in self._cache:
            return None
        for msg in reversed(self._cache[guild_id]):
            if msg["channel_id"] == channel_id:
                return msg
        return None

    def remove_guild(self, guild_id):
        self._cache.pop(guild_id, None)


_log_rate_limits = {}

async def send_log(guild_id, log_type, embed, bot=None, admin=None):
    import __main__ as main_module
    log_channels = main_module.log_channels
    LOG_CHANNEL_MAP = main_module.LOG_CHANNEL_MAP
    DEFAULT_LOG_CHANNEL_ID = main_module.DEFAULT_LOG_CHANNEL_ID

    key = (guild_id, log_type)
    now = time.time()
    last = _log_rate_limits.get(key, 0)
    if now - last < 1.5:
        print(f"[LOG] Rate limited: {log_type} for guild {guild_id}", flush=True)
        return
    _log_rate_limits[key] = now

    config = log_channels.get(guild_id, {})
    if isinstance(config, dict):
        mapped_type = LOG_CHANNEL_MAP.get(log_type, log_type)
        ch_id = config.get(mapped_type) or config.get(log_type) or config.get("main") or DEFAULT_LOG_CHANNEL_ID
        print(f"[LOG] send_log({log_type}) → mapped={mapped_type} ch_id={ch_id} config_keys={list(config.keys())}", flush=True)
    else:
        ch_id = DEFAULT_LOG_CHANNEL_ID
        print(f"[LOG] send_log({log_type}) → config not dict, using DEFAULT={ch_id}", flush=True)

    if not ch_id:
        print(f"[LOG] No ch_id for {log_type} in guild {guild_id}", flush=True)
        return

    if bot is None:
        bot = main_module.bot

    ch = bot.get_channel(int(ch_id))
    if not ch:
        print(f"[LOG] Channel {ch_id} not found for {log_type}", flush=True)
        return

    try:
        await ch.send(embed=embed)
        print(f"[LOG] ✅ Sent to #{ch.name} ({log_type})", flush=True)
    except discord.Forbidden:
        print(f"[LOG] ❌ لا توجد صلاحية للإرسال في #{ch.name} ({log_type})", flush=True)
    except Exception as e:
        print(f"[LOG] ❌ خطأ في الإرسال ({log_type}): {e}", flush=True)

_log_rate_limits_cleanup = 0

def cleanup_rate_limits():
    global _log_rate_limits_cleanup
    now = time.time()
    if now - _log_rate_limits_cleanup < 300:
        return
    _log_rate_limits_cleanup = now
    expired = [k for k, v in _log_rate_limits.items() if now - v > 10]
    for k in expired:
        del _log_rate_limits[k]
