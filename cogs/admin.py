import discord
from discord.ext import commands
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, ADMIN_ROLE_ID, YOUR_USER_ID
from log_service import LogEmbed, LogColors, send_log


class Admin(commands.Cog):
    """⚙️ أوامر الإدارة"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="sayas", aliases=["قول_ك"])
    @commands.has_permissions(administrator=True)
    async def sayas_cmd(self, ctx, channel: discord.TextChannel = None, *, text: str = None):
        """إرسال رسالة عبر البوت في قناة محددة"""
        if not channel or not text:
            await ctx.send("❌ حدد: `!sayas #channel <text>`")
            return
        await ctx.message.delete()
        await channel.send(text)

    @commands.command(name="embed", aliases=["امبد"])
    @commands.has_permissions(administrator=True)
    async def embed_cmd(self, ctx, channel: discord.TextChannel = None, title: str = None, *, text: str = None):
        """إرسال امبد في قناة"""
        if not channel or not title or not text:
            await ctx.send("❌ حدد: `!embed #channel <title> <description>`")
            return
        await ctx.message.delete()
        embed = discord.Embed(title=title, description=text, color=0x5865F2)
        await channel.send(embed=embed)

    @commands.command(name="editmsg", aliases=["تعديل_رسالة"])
    @commands.has_permissions(administrator=True)
    async def editmsg_cmd(self, ctx, message_id: int = None, *, text: str = None):
        """تعديل رسالة أرسلها البوت"""
        if not message_id or not text:
            await ctx.send("❌ حدد: `!editmsg <message_id> <new text>`")
            return
        try:
            msg = await ctx.channel.fetch_message(message_id)
            if msg.author != self.bot.user:
                await ctx.send("❌ لا أستطيع تعديل هذه الرسالة!")
                return
            await msg.edit(content=text)
            await ctx.send("✅ تم التعديل!", delete_after=3)
        except:
            await ctx.send("❌ الرسالة غير موجودة!")

    @commands.command(name="purge", aliases=["مسح_كامل"])
    @commands.has_permissions(administrator=True)
    async def purge_cmd(self, ctx, amount: int = 50):
        """مسح الرسائل بشكل كامل"""
        if amount < 1 or amount > 1000:
            await ctx.send("❌ العدد يجب أن يكون بين 1 و 1000!")
            return
        deleted = 0
        while deleted < amount:
            batch = min(100, amount - deleted)
            d = await ctx.channel.purge(limit=batch + 1)
            deleted += len(d) - 1
            import asyncio
            await asyncio.sleep(1)
        msg = await ctx.send(f"✅ تم مسح **{deleted}** رسالة")
        import asyncio
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command(name="role", aliases=["رتبة"])
    @commands.has_permissions(manage_roles=True)
    async def role_cmd(self, ctx, member: discord.Member = None, role: discord.Role = None):
        """إضافة/إزالة رتبة لعضو"""
        if not member or not role:
            await ctx.send("❌ حدد: `!role @user @role`")
            return
        if role >= ctx.author.top_role:
            await ctx.send("❌ لا تقدر تعدل رتبة أعلى من رتبتك!")
            return
        if role in member.roles:
            await member.remove_roles(role, reason=f"Removed by {ctx.author}")
            await ctx.send(f"✅ تم إزالة {role.mention} من {member.mention}")
        else:
            await member.add_roles(role, reason=f"Added by {ctx.author}")
            await ctx.send(f"✅ تم إضافة {role.mention} لـ {member.mention}")

    @commands.command(name="createrole", aliases=["إنشاء_رتبة"])
    @commands.has_permissions(manage_roles=True)
    async def createrole_cmd(self, ctx, name: str = None, color: str = None):
        """إنشاء رتبة جديدة"""
        if not name:
            await ctx.send("❌ حدد: `!createrole <name> [hex color]`")
            return
        role_color = 0x5865F2
        if color:
            try:
                role_color = int(color.strip('#'), 16)
            except:
                pass
        role = await ctx.guild.create_role(name=name, color=role_color, reason=f"Created by {ctx.author}")
        await ctx.send(f"✅ تم إنشاء الرتبة {role.mention}")

    @commands.command(name="deleterole", aliases=["حذف_رتبة"])
    @commands.has_permissions(manage_roles=True)
    async def deleterole_cmd(self, ctx, role: discord.Role = None):
        """حذف رتبة"""
        if not role:
            await ctx.send("❌ حدد: `!deleterole @role`")
            return
        if role >= ctx.author.top_role:
            await ctx.send("❌ لا تقدر تحذف رتبة أعلى من رتبتك!")
            return
        await role.delete(reason=f"Deleted by {ctx.author}")
        await ctx.send(f"✅ تم حذف الرتبة")

    @commands.command(name="mute", aliases=["كتم_دائم"])
    @commands.has_permissions(moderate_members=True)
    async def mute_cmd(self, ctx, member: discord.Member = None, *, reason: str = "لا يوجد سبب"):
        """كتم عضو بشكل دائم"""
        if not member:
            await ctx.send("❌ حدد العضو: `!mute @user [سبب]`")
            return
        try:
            await member.timeout(discord.utils.utcnow() + discord.timedelta(days=365), reason=reason)
            embed = discord.Embed(title="🔇 تم الكتم الدائم", color=0xE74C3C)
            embed.add_field(name="المكتوم", value=member.mention, inline=True)
            embed.add_field(name="السبب", value=reason, inline=False)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية الكتم!")

    @commands.command(name="unmute", aliases=["فك_كتم_دائم"])
    @commands.has_permissions(moderate_members=True)
    async def unmute_cmd(self, ctx, member: discord.Member = None):
        """فك الكتم الدائم"""
        if not member:
            await ctx.send("❌ حدد العضو: `!unmute @user`")
            return
        try:
            await member.timeout(None, reason=f"Unmuted by {ctx.author}")
            await ctx.send(f"✅ تم فك كتم {member.mention}")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية فك الكتم!")

    @commands.command(name="nick", aliases=["اسم"])
    @commands.has_permissions(manage_nicknames=True)
    async def nick_cmd(self, ctx, member: discord.Member = None, *, nickname: str = None):
        """تغيير اسم العضو"""
        if not member or not nickname:
            await ctx.send("❌ حدد: `!nick @user <new nickname>`")
            return
        try:
            old_name = member.display_name
            await member.edit(nick=nickname, reason=f"Changed by {ctx.author}")
            await ctx.send(f"✅ تم تغيير اسم {member.mention} من **{old_name}** إلى **{nickname}**")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية تغيير الأسماء!")

    @commands.command(name="channel", aliases=["قناة"])
    @commands.has_permissions(manage_channels=True)
    async def channel_cmd(self, ctx, action: str = None, channel: discord.TextChannel = None):
        """إدارة القنوات"""
        if not action:
            await ctx.send("❌ حدد: `!channel <lock/unlock/nsfw/topic> [#channel]`")
            return
        channel = channel or ctx.channel
        if action.lower() == "lock":
            await channel.set_permissions(ctx.guild.default_role, send_messages=False)
            await ctx.send(f"✅ تم قفل {channel.mention}")
        elif action.lower() == "unlock":
            await channel.set_permissions(ctx.guild.default_role, send_messages=True)
            await ctx.send(f"✅ تم فتح {channel.mention}")
        elif action.lower() == "nsfw":
            await channel.edit(nsfw=not channel.is_nsfw())
            state = "محتوىросл" if channel.is_nsfw() else "غير محتوىadult"
            await ctx.send(f"✅ تم تغيير حالة {channel.mention} إلى {state}")
        elif action.lower() == "topic":
            await ctx.send("❌ حدد الموضوع: `!channel topic <topic>`")
        else:
            await ctx.send("❌ إجراء غير معروف!")

    @commands.command(name="clone", aliases=["نسخ"])
    @commands.has_permissions(manage_channels=True)
    async def clone_cmd(self, ctx, channel: discord.TextChannel = None):
        """نسخ قناة"""
        if not channel:
            channel = ctx.channel
        try:
            new_channel = await channel.clone(reason=f"Cloned by {ctx.author}")
            await ctx.send(f"✅ تم نسخ القناة: {new_channel.mention}")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية النسخ!")

    @commands.command(name="slowmode", aliases=["بطيء"])
    @commands.has_permissions(manage_channels=True)
    async def slowmode_cmd(self, ctx, seconds: int = 0, channel: discord.TextChannel = None):
        """وضع البطء"""
        channel = channel or ctx.channel
        try:
            await channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send(f"✅ تم إيقاف البطء في {channel.mention}")
            else:
                await ctx.send(f"✅ تم تعيين البطء في {channel.mention}: **{seconds}** ثانية")
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية التعديل!")

    @commands.command(name="announce", aliases=["إعلان"])
    @commands.has_permissions(administrator=True)
    async def announce_cmd(self, ctx, channel: discord.TextChannel = None, *, text: str = None):
        """إرسال إعلان"""
        if not channel or not text:
            await ctx.send("❌ حدد: `!announce #channel <text>`")
            return
        await ctx.message.delete()
        embed = discord.Embed(title="📢 إعلان", description=text, color=0xF1C40F)
        embed.set_footer(text=f"بواسطة {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await channel.send(embed=embed)

    @commands.command(name="serverbackup", aliases=["نسخ_احتياطي"])
    @commands.has_permissions(administrator=True)
    async def serverbackup_cmd(self, ctx):
        """إنشاء نسخة احتياطية للسيرفر"""
        await ctx.send("✅ جاري إنشاء النسخة الاحتياطية...")
        from guild_backup import save_backup
        try:
            result = await save_backup(ctx.guild)
            if result:
                await ctx.send(f"✅ تم إنشاء النسخة الاحتياطية بنجاح!")
            else:
                await ctx.send("❌ خطأ في إنشاء النسخة الاحتياطية!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="serverlist", aliases=["قائمة_السيرفرات"])
    @commands.has_permissions(administrator=True)
    async def serverlist_cmd(self, ctx):
        """عرض قائمة السيرفرات"""
        embed = discord.Embed(title="📋 قائمة السيرفرات", color=0x5865F2)
        embed.add_field(name="عدد السيرفرات", value=str(len(self.bot.guilds)), inline=True)
        for guild in self.bot.guilds[:20]:
            embed.add_field(
                name=guild.name,
                value=f"Members: {guild.member_count} | ID: {guild.id}",
                inline=True
            )
        await ctx.send(embed=embed)

    @commands.command(name="botinfo", aliases=["معلومات_البوت"])
    async def botinfo_cmd(self, ctx):
        """عرض معلومات البوت"""
        import platform
        embed = discord.Embed(title="🤖 معلومات البوت", color=0x5865F2)
        embed.add_field(name="الاسم", value=self.bot.user.name, inline=True)
        embed.add_field(name="المعرف", value=self.bot.user.id, inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="السيرفرات", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="الأعضاء", value=str(len(self.bot.users)), inline=True)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="uptime", aliases=["وقت_التشغيل"])
    async def uptime_cmd(self, ctx):
        """عرض وقت التشغيل"""
        import time
        from datetime import datetime
        try:
            from main import start_time
            uptime = datetime.now() - start_time
        except:
            uptime_seconds = int(time.time())
            uptime = "غير معروف"
        embed = discord.Embed(title="⏰ وقت التشغيل", color=0x2ECC71)
        if isinstance(uptime, str):
            embed.add_field(name="الوقت", value=uptime, inline=True)
        else:
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            embed.add_field(name="الوقت", value=f"{days} يوم، {hours} ساعة، {minutes} دقيقة، {seconds} ثانية", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="restart", aliases=["إعادة_تشغيل"])
    @commands.has_permissions(administrator=True)
    async def restart_cmd(self, ctx):
        """إعادة تشغيل البوت"""
        embed = discord.Embed(title="🔄 جاري إعادة التشغيل...", color=0xF1C40F)
        await ctx.send(embed=embed)
        import asyncio
        await asyncio.sleep(2)
        try:
            await self.bot.close()
        except:
            pass

    @commands.command(name="eval", aliases=["تقييم"])
    @commands.is_owner()
    async def eval_cmd(self, ctx, *, code: str = None):
        """تقييم كود Python"""
        if not code:
            await ctx.send("❌ حدد الكود!")
            return
        try:
            result = eval(code)
            embed = discord.Embed(title="✅ النتيجة", color=0x2ECC71)
            embed.add_field(name="النتيجة", value=f"```{str(result)[:1000]}```", inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(title="❌ خطأ", color=0xE74C3C)
            embed.add_field(name="الخطأ", value=f"```{str(e)[:1000]}```", inline=False)
            await ctx.send(embed=embed)

    @commands.command(name="exec", aliases=["تنفيذ"])
    @commands.is_owner()
    async def exec_cmd(self, ctx, *, code: str = None):
        """تنفيذ كود Python"""
        if not code:
            await ctx.send("❌ حدد الكود!")
            return
        try:
            import io
            import contextlib
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exec(code, {'bot': self.bot, 'ctx': ctx, 'discord': discord})
            output = stdout.getvalue()
            if output:
                embed = discord.Embed(title="✅ الإخراج", color=0x2ECC71)
                embed.add_field(name="الإخراج", value=f"```{output[:1000]}```", inline=False)
                await ctx.send(embed=embed)
            else:
                await ctx.send("✅ تم التنفيذ!")
        except Exception as e:
            embed = discord.Embed(title="❌ خطأ", color=0xE74C3C)
            embed.add_field(name="الخطأ", value=f"```{str(e)[:1000]}```", inline=False)
            await ctx.send(embed=embed)

    @commands.command(name="loadcog", aliases=["تحميل_كوج"])
    @commands.is_owner()
    async def loadcog_cmd(self, ctx, cog_name: str = None):
        """تحميل كوج"""
        if not cog_name:
            await ctx.send("❌ حدد اسم الكوج!")
            return
        try:
            await self.bot.load_extension(f"cogs.{cog_name}")
            await ctx.send(f"✅ تم تحميل {cog_name}")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="unloadcog", aliases=["إلغاء_تحميل_كوج"])
    @commands.is_owner()
    async def unloadcog_cmd(self, ctx, cog_name: str = None):
        """إلغاء تحميل كوج"""
        if not cog_name:
            await ctx.send("❌ حدد اسم الكوج!")
            return
        try:
            await self.bot.unload_extension(f"cogs.{cog_name}")
            await ctx.send(f"✅ تم إلغاء تحميل {cog_name}")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="reloadcog", aliases=["إعادة_تحميل_كوج"])
    @commands.is_owner()
    async def reloadcog_cmd(self, ctx, cog_name: str = None):
        """إعادة تحميل كوج"""
        if not cog_name:
            await ctx.send("❌ حدد اسم الكوج!")
            return
        try:
            await self.bot.reload_extension(f"cogs.{cog_name}")
            await ctx.send(f"✅ تم إعادة تحميل {cog_name}")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="cogs", aliases=["الكوجات"])
    @commands.is_owner()
    async def cogs_cmd(self, ctx):
        """عرض الكوجات المحملة"""
        cogs = list(self.bot.cogs.keys())
        embed = discord.Embed(title="📦 الكوجات المحملة", color=0x5865F2)
        embed.add_field(name="العدد", value=str(len(cogs)), inline=True)
        embed.add_field(name="القائمة", value="\n".join(cogs) if cogs else "لا توجد كوجات", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="pingall", aliases=["منشن_الكل"])
    @commands.has_permissions(administrator=True)
    async def pingall_cmd(self, ctx):
        """منشن جميع الأعضاء"""
        await ctx.message.delete()
        members = [m.mention for m in ctx.guild.members if not m.bot]
        chunks = [members[i:i+20] for i in range(0, len(members), 20)]
        for chunk in chunks:
            await ctx.send(" ".join(chunk))
            import asyncio
            await asyncio.sleep(1)

    @commands.command(name="clearroles", aliases=["مسح_الرتب"])
    @commands.has_permissions(administrator=True)
    async def clearroles_cmd(self, ctx):
        """مسح جميع الرتب غير المستخدمة"""
        unused_roles = []
        for role in ctx.guild.roles:
            if role.name == "@everyone":
                continue
            if len(role.members) == 0:
                unused_roles.append(role)
        if not unused_roles:
            await ctx.send("✅ لا توجد رتب غير مستخدمة!")
            return
        for role in unused_roles:
            try:
                await role.delete()
                import asyncio
                await asyncio.sleep(0.5)
            except:
                pass
        await ctx.send(f"✅ تم مسح **{len(unused_roles)}** رتبة غير مستخدمة!")

    @commands.command(name="lockserver", aliases=["قفل_السيرفر"])
    @commands.has_permissions(administrator=True)
    async def lockserver_cmd(self, ctx):
        """قفل السيرفر (منع إرسال الرسائل)"""
        await ctx.guild.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 تم قفل السيرفر!")

    @commands.command(name="unlockserver", aliases=["فتح_السيرفر"])
    @commands.has_permissions(administrator=True)
    async def unlockserver_cmd(self, ctx):
        """فتح السيرفر"""
        await ctx.guild.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 تم فتح السيرفر!")


async def setup(bot):
    await bot.add_cog(Admin(bot))
