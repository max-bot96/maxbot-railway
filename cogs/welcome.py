import discord
from discord.ext import commands
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, AUTO_ROLE_ID
from log_service import LogEmbed, LogColors, send_log


class Welcome(commands.Cog):
    """👋 نظام الترحيب والرتبة التلقائية"""

    def __init__(self, bot):
        self.bot = bot

    def _load_welcome_config(self):
        data = load_data()
        return {int(k): v for k, v in data.get("welcome", {}).items()}

    def _save_welcome_config(self, config):
        data = load_data()
        data["welcome"] = {str(k): v for k, v in config.items()}
        mark_data_dirty()
        save_data()

    @commands.command(name="setwelcome", aliases=["تعيين_ترحيب"])
    @commands.has_permissions(administrator=True)
    async def setwelcome_cmd(self, ctx, channel: discord.TextChannel = None, *, message: str = None):
        """تعيين قناة الترحيب والرسالة"""
        if not channel:
            await ctx.send("❌ حدد القناة: `!setwelcome #channel الرسالة`")
            return
        config = self._load_welcome_config()
        guild_config = config.setdefault(ctx.guild.id, {"channel": channel.id, "message": "مرحباً {user}!", "enabled": True})
        guild_config["channel"] = channel.id
        if message:
            guild_config["message"] = message
        self._save_welcome_config(config)
        embed = discord.Embed(title="👋 تم تعيين الترحيب", color=0x2ECC71)
        embed.add_field(name="القناة", value=channel.mention, inline=True)
        embed.add_field(name="الرسالة", value=message or guild_config.get("message", ""), inline=False)
        embed.add_field(name="المتغيرات", value="`{user}` - منشن العضو\n`{server}` - اسم السيرفر\n`{count}` - عدد الأعضاء", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="welcomemsg", aliases=["رسالة_ترحيب"])
    @commands.has_permissions(administrator=True)
    async def welcomemsg_cmd(self, ctx, *, message: str):
        """تعديل رسالة الترحيب"""
        config = self._load_welcome_config()
        guild_config = config.setdefault(ctx.guild.id, {"channel": ctx.channel.id, "message": message, "enabled": True})
        guild_config["message"] = message
        self._save_welcome_config(config)
        await ctx.send(f"✅ تم تحديث رسالة الترحيب:\n{message}")

    @commands.command(name="welcometoggle", aliases=["تشغيل_ترحيب"])
    @commands.has_permissions(administrator=True)
    async def welcometoggle_cmd(self, ctx):
        """تشغيل/إيقاف الترحيب"""
        config = self._load_welcome_config()
        guild_config = config.setdefault(ctx.guild.id, {"enabled": True})
        guild_config["enabled"] = not guild_config.get("enabled", True)
        self._save_welcome_config(config)
        state = "🟢 مفعّل" if guild_config["enabled"] else "🔴 معطّل"
        embed = discord.Embed(title="👋 حالة الترحيب", color=0x2ECC71 if guild_config["enabled"] else 0xE74C3C)
        embed.add_field(name="الحالة", value=state)
        await ctx.send(embed=embed)

    @commands.command(name="testwelcome", aliases=["اختبار_ترحيب"])
    @commands.has_permissions(administrator=True)
    async def testwelcome_cmd(self, ctx):
        """اختبار رسالة الترحيب"""
        config = self._load_welcome_config()
        guild_config = config.get(ctx.guild.id, {})
        channel_id = guild_config.get("channel")
        if not channel_id:
            await ctx.send("❌ لم يتم تعيين قناة الترحيب بعد!")
            return
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            await ctx.send("❌ قناة الترحيب غير موجودة!")
            return
        message = guild_config.get("message", "مرحباً {user}!")
        message = message.replace("{user}", ctx.author.mention)
        message = message.replace("{server}", ctx.guild.name)
        message = message.replace("{count}", str(ctx.guild.member_count))
        embed = discord.Embed(title=f"👋 {ctx.guild.name}", description=message, color=0x5865F2)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.set_footer(text=f"عدد الأعضاء: {ctx.guild.member_count}")
        await channel.send(embed=embed)
        await ctx.send(f"✅ تم إرسال رسالة الترحيب إلى {channel.mention}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        config = self._load_welcome_config()
        guild_config = config.get(member.guild.id, {})
        if not guild_config.get("enabled", True):
            return
        channel_id = guild_config.get("channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return
        message = guild_config.get("message", "مرحباً {user}!")
        message = message.replace("{user}", member.mention)
        message = message.replace("{server}", member.guild.name)
        message = message.replace("{count}", str(member.guild.member_count))
        embed = discord.Embed(title=f"👋 {member.guild.name}", description=message, color=0x5865F2)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"عدد الأعضاء: {member.guild.member_count}")
        try:
            await channel.send(embed=embed)
        except:
            pass
        auto_role_id = AUTO_ROLE_ID
        if auto_role_id:
            role = member.guild.get_role(auto_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto Role")
                except:
                    pass
        log_embed = LogEmbed.base("📥 عضو جديد", LogColors.JOIN, guild=member.guild)
        LogEmbed.user_field(log_embed, member, "العضو الجديد", thumb=True)
        await send_log(member.guild.id, "log_join", log_embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.bot:
            return
        log_embed = LogEmbed.base("🚪 عضو غادر", LogColors.LEAVE, guild=member.guild)
        LogEmbed.user_field(log_embed, member, "العضو", thumb=True)
        roles = [r.mention for r in reversed(member.roles[1:])][:5]
        if roles:
            log_embed.add_field(name="الرتب", value=" • ".join(roles), inline=False)
        await send_log(member.guild.id, "log_leave", log_embed)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
