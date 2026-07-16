import discord
from discord.ext import commands
from discord import Permissions
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, ADMIN_ROLE_ID
from log_service import LogEmbed, LogColors, send_log


class Moderation(commands.Cog):
    """👮 إدارة الأعضاء"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="kick", aliases=["طرد"])
    @commands.has_permissions(kick_members=True)
    async def kick_cmd(self, ctx, member: discord.Member = None, *, reason: str = "لا يوجد سبب"):
        """طرد عضو من السيرفر"""
        if not member:
            await ctx.send("❌ حدد العضو: `!kick @user [سبب]`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدر تطرد نفسك!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ لا تقدر تطرد شخص برتبة أعلى أو مساوية لك!")
            return
        try:
            await member.kick(reason=reason)
            embed = discord.Embed(title="👢 تم الطرد", color=0xE67E22)
            embed.add_field(name="المطرود", value=member.mention, inline=True)
            embed.add_field(name="المطرد", value=ctx.author.mention, inline=True)
            embed.add_field(name="السبب", value=reason, inline=False)
            await ctx.send(embed=embed)
            log_embed = LogEmbed.base("👢 طرد عضو", LogColors.TIMEOUT, guild=ctx.guild)
            LogEmbed.user_field(log_embed, member, "المطرود", thumb=True)
            LogEmbed.audit_field(log_embed, ctx.author)
            LogEmbed.reason_field(log_embed, reason)
            await send_log(ctx.guild.id, "ban_kick_timeout", log_embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية الطرد!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="ban", aliases=["حظر"])
    @commands.has_permissions(ban_members=True)
    async def ban_cmd(self, ctx, member: discord.Member = None, *, reason: str = "لا يوجد سبب"):
        """حظر عضو من السيرفر"""
        if not member:
            await ctx.send("❌ حدد العضو: `!ban @user [سبب]`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدر تحظر نفسك!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ لا تقدر تحظر شخص برتبة أعلى أو مساوية لك!")
            return
        try:
            await member.ban(reason=reason, delete_message_days=1)
            embed = discord.Embed(title="🔨 تم الحظر", color=0xE74C3C)
            embed.add_field(name="المحظور", value=member.mention, inline=True)
            embed.add_field(name="المحظر", value=ctx.author.mention, inline=True)
            embed.add_field(name="السبب", value=reason, inline=False)
            await ctx.send(embed=embed)
            log_embed = LogEmbed.base("🔨 حظر عضو", LogColors.PROTECT, guild=ctx.guild)
            LogEmbed.user_field(log_embed, member, "المحظور", thumb=True)
            LogEmbed.audit_field(log_embed, ctx.author)
            LogEmbed.reason_field(log_embed, reason)
            await send_log(ctx.guild.id, "ban_kick_timeout", log_embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية الحظر!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="unban", aliases=["فك_حظر"])
    @commands.has_permissions(ban_members=True)
    async def unban_cmd(self, ctx, user_id: int = None):
        """فك الحظر عن مستخدم"""
        if not user_id:
            await ctx.send("❌ حدد معرف المستخدم: `!unban 123456789`")
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            embed = discord.Embed(title="✅ تم فك الحظر", color=0x2ECC71)
            embed.add_field(name="المستخدم", value=f"{user.name} (`{user.id}`)", inline=True)
            await ctx.send(embed=embed)
            log_embed = LogEmbed.base("✅ فك حظر", LogColors.CREATE, guild=ctx.guild)
            LogEmbed.user_field(log_embed, user, "المستخدم", thumb=True)
            LogEmbed.audit_field(log_embed, ctx.author)
            await send_log(ctx.guild.id, "ban_kick_timeout", log_embed)
        except discord.NotFound:
            await ctx.send("❌ المستخدم غير محظور!")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية فك الحظر!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="timeout", aliases=["كتم", "silence"])
    @commands.has_permissions(moderate_members=True)
    async def timeout_cmd(self, ctx, member: discord.Member = None, duration: int = 10, *, reason: str = "لا يوجد سبب"):
        """كتم عضو (بالدقائق)"""
        if not member:
            await ctx.send("❌ حدد العضو: `!timeout @user [دقائق] [سبب]`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدر تكتم نفسك!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ لا تقدر تكتم شخص برتبة أعلى أو مساوية لك!")
            return
        try:
            from datetime import timedelta
            await member.timeout(timedelta(minutes=duration), reason=reason)
            embed = discord.Embed(title="🔇 تم الكتم", color=0xE67E22)
            embed.add_field(name="المكتوم", value=member.mention, inline=True)
            embed.add_field(name="المدة", value=f"{duration} دقيقة", inline=True)
            embed.add_field(name="السبب", value=reason, inline=False)
            await ctx.send(embed=embed)
            log_embed = LogEmbed.base("🔇 كتم عضو", LogColors.TIMEOUT, guild=ctx.guild)
            LogEmbed.user_field(log_embed, member, "المكتوم", thumb=True)
            LogEmbed.audit_field(log_embed, ctx.author)
            LogEmbed.reason_field(log_embed, reason)
            await send_log(ctx.guild.id, "ban_kick_timeout", log_embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية الكتم!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="untimeout", aliases=["فك_كتم"])
    @commands.has_permissions(moderate_members=True)
    async def untimeout_cmd(self, ctx, member: discord.Member = None):
        """فك الكتم عن عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!untimeout @user`")
            return
        try:
            await member.timeout(None)
            embed = discord.Embed(title="🔊 تم فك الكتم", color=0x2ECC71)
            embed.add_field(name="العضو", value=member.mention, inline=True)
            await ctx.send(embed=embed)
            log_embed = LogEmbed.base("🔊 فك الكتم", LogColors.CREATE, guild=ctx.guild)
            LogEmbed.user_field(log_embed, member, "العضو", thumb=True)
            LogEmbed.audit_field(log_embed, ctx.author)
            await send_log(ctx.guild.id, "ban_kick_timeout", log_embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية فك الكتم!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="clear", aliases=["مسح"])
    @commands.has_permissions(manage_messages=True)
    async def clear_cmd(self, ctx, amount: int = 5):
        """حذف رسائل من القناة"""
        if amount < 1 or amount > 100:
            await ctx.send("❌ العدد يجب أن يكون بين 1 و 100!")
            return
        try:
            deleted = await ctx.channel.purge(limit=amount + 1)
            msg = await ctx.send(f"✅ تم حذف **{len(deleted) - 1}** رسالة")
            import asyncio
            await asyncio.sleep(3)
            await msg.delete()
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية حذف الرسائل!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")
    
    @commands.command(name="lock", aliases=["قفل"])
    @commands.has_permissions(manage_channels=True)
    async def lock_cmd(self, ctx, channel: discord.TextChannel = None):
        """قفل القناة"""
        channel = channel or ctx.channel
        try:
            await channel.set_permissions(ctx.guild.default_role, send_messages=False)
            embed = discord.Embed(title="🔒 تم قفل القناة", color=0xE74C3C)
            embed.add_field(name="القناة", value=channel.mention, inline=True)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية التعديل!")
    
    @commands.command(name="unlock", aliases=["فتح"])
    @commands.has_permissions(manage_channels=True)
    async def unlock_cmd(self, ctx, channel: discord.TextChannel = None):
        """فتح القناة"""
        channel = channel or ctx.channel
        try:
            await channel.set_permissions(ctx.guild.default_role, send_messages=True)
            embed = discord.Embed(title="🔓 تم فتح القناة", color=0x2ECC71)
            embed.add_field(name="القناة", value=channel.mention, inline=True)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية التعديل!")
    
    @commands.command(name="slowmode", aliases=["بطيء"])
    @commands.has_permissions(manage_channels=True)
    async def slowmode_cmd(self, ctx, seconds: int = 0):
        """وضع البطء"""
        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send("✅ تم إيقاف وضع البطء")
            else:
                await ctx.send(f"✅ تم تعيين البطء: **{seconds}** ثانية")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية التعديل!")
    
    @commands.command(name="warn", aliases=["تحذير"])
    @commands.has_permissions(moderate_members=True)
    async def warn_cmd(self, ctx, member: discord.Member = None, *, reason: str = "لا يوجد سبب"):
        """تحذير عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!warn @user [سبب]`")
            return
        data = load_data()
        warns = data.setdefault("warns", {})
        guild_warns = warns.setdefault(str(ctx.guild.id), {})
        user_warns = guild_warns.setdefault(str(member.id), [])
        user_warns.append({"reason": reason, "by": ctx.author.id, "time": str(discord.utils.utcnow())})
        mark_data_dirty()
        save_data()
        warn_count = len(user_warns)
        embed = discord.Embed(title="⚠️ تم التحذير", color=0xF1C40F)
        embed.add_field(name="العضو", value=member.mention, inline=True)
        embed.add_field(name="العدد", value=f"{warn_count} تحذيرات", inline=True)
        embed.add_field(name="السبب", value=reason, inline=False)
        await ctx.send(embed=embed)
        if warn_count >= 3:
            try:
                await member.kick(reason=f"3 تحذيرات - {reason}")
                await ctx.send(f"✅ تم طرد {member.mention} بسبب 3 تحذيرات!")
            except:
                pass
    
    @commands.command(name="warns", aliases=["تحذيرات"])
    async def warns_cmd(self, ctx, member: discord.Member = None):
        """عرض تحذيرات عضو"""
        if not member:
            member = ctx.author
        data = load_data()
        warns = data.get("warns", {})
        guild_warns = warns.get(str(ctx.guild.id), {})
        user_warns = guild_warns.get(str(member.id), [])
        if not user_warns:
            await ctx.send(f"✅ {member.mention} لا يملك تحذيرات!")
            return
        embed = discord.Embed(title=f"⚠️ تحذيرات {member.display_name}", color=0xF1C40F)
        for i, w in enumerate(user_warns[:10], 1):
            by = ctx.guild.get_member(w.get("by", 0))
            by_name = by.display_name if by else "غير معروف"
            embed.add_field(name=f"#{i}", value=f"**السبب:** {w.get('reason', '?')}\n**بواسطة:** {by_name}", inline=False)
        embed.set_footer(text=f"إجمالي: {len(user_warns)} تحذيرات")
        await ctx.send(embed=embed)
    
    @commands.command(name="userinfo", aliases=["معلومات", "info"])
    async def userinfo_cmd(self, ctx, member: discord.Member = None):
        """عرض معلومات عضو"""
        member = member or ctx.author
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        acc_age = (now - member.created_at).days if member.created_at else 0
        srv_age = (now - member.joined_at).days if member.joined_at else 0
        badges = []
        if hasattr(member, 'public_flags') and member.public_flags:
            for flag in member.public_flags:
                name = flag.name.replace("_", " ").title() if hasattr(flag, 'name') else str(flag)
                badges.append(name)
        badges_text = ", ".join(badges) if badges else "No Badges"
        roles = [r.mention for r in reversed(member.roles[1:])][:10]
        roles_text = " • ".join(roles) if roles else "لا توجد رتب"
        embed = discord.Embed(title=f"👤 {member.display_name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="المعرف", value=f"`{member.id}`", inline=True)
        embed.add_field(name="الاسم", value=member.name, inline=True)
        embed.add_field(name="البارادات", value=f"`{badges_text}`", inline=False)
        embed.add_field(name="تاريخ الإنشاء", value=f"<t:{int(member.created_at.timestamp())}:F>\n({acc_age} يوم)", inline=True)
        embed.add_field(name="تاريخ الانضمام", value=f"<t:{int(member.joined_at.timestamp())}:R>\n({srv_age} يوم)", inline=True)
        embed.add_field(name="الرتب", value=roles_text, inline=False)
        is_booster = member.premium_since is not None
        embed.add_field(name="💎 بوست", value="نعم" if is_booster else "لا", inline=True)
        await ctx.send(embed=embed)
    
    @commands.command(name="avatar", aliases=["صورة"])
    async def avatar_cmd(self, ctx, member: discord.Member = None):
        """عرض صورة الأفاتار"""
        member = member or ctx.author
        embed = discord.Embed(title=f"🖼️ صورة {member.display_name}", color=member.color)
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="serverinfo", aliases=["سيرفر", "server"])
    async def serverinfo_cmd(self, ctx):
        """عرض معلومات السيرفر"""
        guild = ctx.guild
        embed = discord.Embed(title=f"📊 {guild.name}", color=0x5865F2)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="المالك", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="الأعضاء", value=f"{guild.member_count}", inline=True)
        embed.add_field(name="القنوات", value=f"{guild.channel_count}", inline=True)
        embed.add_field(name="الرتب", value=f"{len(guild.roles)}", inline=True)
        embed.add_field(name="الإيموجي", value=f"{len(guild.emojis)}", inline=True)
        embed.add_field(name="البوست", value=f"Tier {guild.premium_tier} ({guild.premium_subscription_count})", inline=True)
        embed.add_field(name="تاريخ الإنشاء", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=False)
        await ctx.send(embed=embed)
    
    @commands.command(name="ping")
    async def ping_cmd(self, ctx):
        """عرض سرعة البوت"""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(title="🏓 Pong!", color=0x2ECC71)
        embed.add_field(name="ال_latency", value=f"`{latency}ms`", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
