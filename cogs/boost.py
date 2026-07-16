import discord
from discord.ext import commands
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty
from log_service import LogEmbed, LogColors, send_log


class Boost(commands.Cog):
    """💎 نظام البوست"""

    def __init__(self, bot):
        self.bot = bot

    def _load_boost_config(self):
        data = load_data()
        return data.get("boost_config", {})

    def _save_boost_config(self, config):
        data = load_data()
        data["boost_config"] = config
        mark_data_dirty()
        save_data()

    @commands.command(name="setboost", aliases=["تعيين_بوست"])
    @commands.has_permissions(administrator=True)
    async def setboost_cmd(self, ctx, channel: discord.TextChannel = None):
        """تعيين روم إشعار البوست"""
        if not channel:
            await ctx.send("❌ حدد القناة: `!setboost #channel`")
            return
        config = self._load_boost_config()
        config[str(ctx.guild.id)] = {"channel": channel.id, "enabled": True}
        self._save_boost_config(config)
        embed = discord.Embed(title="💎 تم تعيين روم البوست", color=0xFF73FA)
        embed.add_field(name="القناة", value=channel.mention, inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="boosttoggle", aliases=["تشغيل_بوست"])
    @commands.has_permissions(administrator=True)
    async def boosttoggle_cmd(self, ctx):
        """تشغيل/إيقاف إشعار البوست"""
        config = self._load_boost_config()
        guild_config = config.setdefault(str(ctx.guild.id), {"enabled": True})
        guild_config["enabled"] = not guild_config.get("enabled", True)
        self._save_boost_config(config)
        state = "🟢 مفعّل" if guild_config["enabled"] else "🔴 معطّل"
        embed = discord.Embed(title="💎 حالة البوست", color=0xFF73FA if guild_config["enabled"] else 0xE74C3C)
        embed.add_field(name="الحالة", value=state)
        await ctx.send(embed=embed)

    @commands.command(name="boostmsg", aliases=["رسالة_بوست"])
    @commands.has_permissions(administrator=True)
    async def boostmsg_cmd(self, ctx, *, message: str = None):
        """تعيين رسالة البوست"""
        if not message:
            await ctx.send("❌ حدد الرسالة: `!boostmsg <message>`")
            return
        config = self._load_boost_config()
        guild_config = config.setdefault(str(ctx.guild.id), {})
        guild_config["message"] = message
        self._save_boost_config(config)
        await ctx.send(f"✅ تم تحديث رسالة البوست:\n{message}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.premium_since == after.premium_since:
            return
        if after.premium_since and not before.premium_since:
            config = self._load_boost_config()
            guild_config = config.get(str(after.guild.id), {})
            if not guild_config.get("enabled", True):
                return
            channel_id = guild_config.get("channel")
            if not channel_id:
                return
            channel = after.guild.get_channel(channel_id)
            if not channel:
                return
            custom_msg = guild_config.get("message", "")
            if custom_msg:
                message = custom_msg.replace("{user}", after.mention)
                message = message.replace("{server}", after.guild.name)
                message = message.replace("{count}", str(after.guild.premium_subscription_count))
            else:
                message = f"💎 **{after.display_name}** has boosted the server!"
            embed = discord.Embed(
                title="💎 Server Boosted!",
                description=message,
                color=0xFF73FA
            )
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text=f"Total boosts: {after.guild.premium_subscription_count}")
            try:
                await channel.send(embed=embed)
            except:
                pass
            log_embed = LogEmbed.base("💎 بوست جديد", LogColors.MOD, guild=after.guild)
            LogEmbed.user_field(log_embed, after, "المبوست", thumb=True)
            log_embed.add_field(name="عدد البوستات", value=str(after.guild.premium_subscription_count), inline=True)
            await send_log(after.guild.id, "log_misc", log_embed)

    @commands.command(name="boosters", aliases=["المبوستين"])
    async def boosters_cmd(self, ctx):
        """عرض قائمة المبوستين"""
        boosters = [m for m in ctx.guild.premium_subscribers]
        if not boosters:
            await ctx.send("❌ لا يوجد مبوستين حالياً!")
            return
        embed = discord.Embed(title="💎 المبوستين", color=0xFF73FA)
        embed.add_field(name="العدد", value=f"**{len(boosters)}**", inline=True)
        embed.add_field(name="عدد البوستات", value=f"**{ctx.guild.premium_subscription_count}**", inline=True)
        for booster in boosters[:20]:
            since = f"<t:{int(booster.premium_since.timestamp())}:R>" if booster.premium_since else "غير معروف"
            embed.add_field(name=f"💎 {booster.display_name}", value=since, inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="booststats", aliases=["إحصائيات_بوست"])
    async def booststats_cmd(self, ctx):
        """إحصائيات البوست"""
        embed = discord.Embed(title="💎 إحصائيات البوست", color=0xFF73FA)
        embed.add_field(name="عدد البوستات", value=f"**{ctx.guild.premium_subscription_count}**", inline=True)
        embed.add_field(name="Tier", value=f"**{ctx.guild.premium_tier}**", inline=True)
        embed.add_field(name="المboosterز", value=f"**{len(ctx.guild.premium_subscribers)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="boostthanked", aliases=["شكر_البوست"])
    @commands.has_permissions(administrator=True)
    async def boostthanked_cmd(self, ctx, member: discord.Member = None):
        """شكر عضو على البوست"""
        if not member:
            await ctx.send("❌ حدد العضو: `!boostthanked @user`")
            return
        embed = discord.Embed(title="💎 شكراً على البوست!", color=0xFF73FA)
        embed.description = f"شكراً **{member.mention}** على البوست! 🎉\nنتمنى لك وقتاً ممتعاً في السيرفر!"
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Boost(bot))
