import discord
from discord.ext import commands
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, ADMIN_ROLE_ID
from log_service import LogEmbed, LogColors, send_log


class Log(commands.Cog):
    """📋 نظام الـ Log"""

    def __init__(self, bot):
        self.bot = bot

    def _load_log_channels(self):
        data = load_data()
        return {int(k): v for k, v in data.get("log_channels", {}).items()}

    def _save_log_channels(self, channels):
        data = load_data()
        data["log_channels"] = {str(k): v for k, v in channels.items()}
        mark_data_dirty()
        save_data()

    @commands.group(name="log", aliases=["لوق"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def log_group(self, ctx):
        """نظام الـ Log - 12 روم"""
        config = self._load_log_channels().get(ctx.guild.id, {})
        if not config:
            await ctx.send("❌ لم يتم تعيين أي روم لوق بعد!")
            return
        embed = discord.Embed(title="📋 روم اللوق", color=0x5865F2)
        types = {
            "messages": "💬 الرسائل",
            "messages_del": "🗑️ الرسائل المحذوفة",
            "protection_security": "🛡️ الحماية",
            "ban_kick_timeout": "⚖️ الحظر والطرد والكتم",
            "log_role": "👑 الرتب",
            "log_nickname": "🏷️ الأسماء",
            "log_leave": "🚪 المغادرين",
            "log_voice": "🎤 الصوت",
            "log_channels": "📁 القنوات",
            "log_thread": "🧵 الثريدات",
            "log_emoji_sticker": "😀 الإيموجي",
            "ticket_open": "🎫 التذاكر",
        }
        for key, label in types.items():
            mapped = config.get(key) or config.get("main")
            if mapped:
                ch = ctx.guild.get_channel(mapped)
                val = ch.mention if ch else f"`{mapped}`"
            else:
                val = "❌ غير معيّن"
            embed.add_field(name=label, value=val, inline=True)
        await ctx.send(embed=embed)

    @log_group.command(name="تعيين")
    @commands.has_permissions(administrator=True)
    async def log_set(self, ctx, log_type: str, channel: discord.TextChannel = None):
        """تعيين روم اللوق: !log تعيين <النوع> #channel"""
        valid_types = [
            "messages", "messages_del", "protection_security", "ban_kick_timeout",
            "log_role", "log_nickname", "log_leave", "log_voice", "log_channels",
            "log_thread", "log_emoji_sticker", "ticket_open", "log_join",
            "log_invite", "log_webhook", "log_automod", "log_channel_perm",
            "log_pin_bulk", "log_scheduled_event", "log_misc", "log_activity",
            "log_new_message", "log_hacking", "log_edit_role", "log_channels_del",
            "log_edit_role_del", "log_admin_leave"
        ]
        if log_type not in valid_types:
            await ctx.send(f"❌ نوع اللوق غير صحيح!\nالأنواع المتاحة:\n`{'`, `'.join(valid_types)}`")
            return
        channel = channel or ctx.channel
        log_channels = self._load_log_channels()
        guild_config = log_channels.setdefault(ctx.guild.id, {})
        guild_config[log_type] = channel.id
        self._save_log_channels(log_channels)
        await ctx.send(f"✅ تم تعيين `{log_type}` إلى {channel.mention}")

    @log_group.command(name="حذف")
    @commands.has_permissions(administrator=True)
    async def log_delete(self, ctx, *, log_type: str):
        """حذف روم اللوق: !log حذف <النوع>"""
        log_channels = self._load_log_channels()
        guild_config = log_channels.get(ctx.guild.id, {})
        if log_type in guild_config:
            del guild_config[log_type]
            self._save_log_channels(log_channels)
            await ctx.send(f"✅ تم حذف روم اللوق `{log_type}`")
        else:
            await ctx.send(f"❌ نوع اللوق `{log_type}` غير موجود!")

    @log_group.command(name="كلها")
    @commands.has_permissions(administrator=True)
    async def log_all(self, ctx, channel: discord.TextChannel = None):
        """تعيين كل أنواع اللوق لروم واحد"""
        channel = channel or ctx.channel
        log_channels = self._load_log_channels()
        guild_config = log_channels.setdefault(ctx.guild.id, {})
        types = [
            "messages", "messages_del", "protection_security", "ban_kick_timeout",
            "log_role", "log_nickname", "log_leave", "log_voice", "log_channels",
            "log_thread", "log_emoji_sticker", "ticket_open", "log_join",
            "log_invite", "log_webhook", "log_automod", "log_channel_perm",
            "log_pin_bulk", "log_scheduled_event", "log_misc", "log_activity",
            "log_new_message", "log_hacking", "log_edit_role", "log_channels_del",
            "log_edit_role_del", "log_admin_leave"
        ]
        for t in types:
            guild_config[t] = channel.id
        self._save_log_channels(log_channels)
        embed = discord.Embed(title="📋 تم تعيين كل اللوق", color=0x2ECC71)
        embed.add_field(name="القناة", value=channel.mention, inline=True)
        embed.add_field(name="عدد الأنواع", value=f"{len(types)} نوع", inline=True)
        await ctx.send(embed=embed)

    @log_group.command(name="حالة")
    @commands.has_permissions(administrator=True)
    async def log_status(self, ctx):
        """عرض حالة الـ Log"""
        log_channels = self._load_log_channels()
        guild_config = log_channels.get(ctx.guild.id, {})
        embed = discord.Embed(title="📋 حالة الـ Log", color=0x5865F2)
        total = 0
        active = 0
        for key in ["messages", "messages_del", "protection_security", "ban_kick_timeout",
                     "log_role", "log_nickname", "log_leave", "log_voice", "log_channels",
                     "log_thread", "log_emoji_sticker", "ticket_open"]:
            total += 1
            if key in guild_config:
                active += 1
        embed.add_field(name="الروم النشطة", value=f"{active}/{total}", inline=True)
        embed.add_field(name="الروم الإجمالية", value=str(len(guild_config)), inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Log(bot))
