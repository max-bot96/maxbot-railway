import discord
from discord.ext import commands
from protection_engine import PROTECTION_NAMES
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, ADMIN_ROLE_ID


class Protection(commands.Cog):
    """🛡️ نظام الحماية"""
    
    def __init__(self, bot):
        self.bot = bot
        self.protections = {}
        self.role_exempt_users = {}
        self.load_protection_data()
    
    def load_protection_data(self):
        data = load_data()
        self.protections = {int(k): v for k, v in data.get("protections", {}).items()}
        self.role_exempt_users = {int(k): v for k, v in data.get("role_exempt_users", {}).items()}
    
    def save_protection_data(self):
        data = load_data()
        data["protections"] = {str(k): v for k, v in self.protections.items()}
        data["role_exempt_users"] = {str(k): v for k, v in self.role_exempt_users.items()}
        mark_data_dirty()
        save_data()
    
    async def _toggle_protection(self, ctx, key):
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        p[key] = not p.get(key, False)
        self.save_protection_data()
        state = "🟢 مفعّل" if p[key] else "🔴 معطّل"
        name = PROTECTION_NAMES.get(key, key)
        embed = discord.Embed(title=f"🛡️ حماية {name}", color=0x2ECC71 if p[key] else 0xE74C3C)
        embed.add_field(name="الحالة", value=state)
        await ctx.send(embed=embed)
    
    @commands.group(name="حماية", aliases=['protection', 'امان'], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def حماية(self, ctx):
        """!حماية - عرض حالة الحماية"""
        p = self.protections.get(ctx.guild.id, {})
        
        prot_names = []
        for key in ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]:
            state = "🟢" if p.get(key) else "🔴"
            name = PROTECTION_NAMES.get(key, key)
            prot_names.append(f"{state} {name}")
        
        embed = discord.Embed(title="🛡️ حالة الحماية", color=0x5865F2)
        embed.add_field(name="الحمايات", value="\n".join(prot_names), inline=False)
        embed.set_footer(text="حماية سبام | حماية فلود | حماية منشن | etc.")
        await ctx.send(embed=embed)
    
    @حمة.command(name="سبام")
    async def حماية_سبام(self, ctx):
        await self._toggle_protection(ctx, "spam")
    
    @حمة.command(name="فلود")
    async def حماية_فلود(self, ctx):
        await self._toggle_protection(ctx, "flood")
    
    @حمة.command(name="منشن")
    async def حماية_منشن(self, ctx):
        await self._toggle_protection(ctx, "mention")
    
    @حمة.command(name="كلمات")
    async def حماية_كلمات(self, ctx):
        await self._toggle_protection(ctx, "badwords")
    
    @حمة.command(name="انفايت")
    async def حماية_انفايت(self, ctx):
        await self._toggle_protection(ctx, "invite")
    
    @حمة.command(name="ال")
    async def حماية_ال(self, ctx):
        await self._toggle_protection(ctx, "alt")
    
    @حمة.command(name="ريد")
    async def حماية_ريد(self, ctx):
        await self._toggle_protection(ctx, "raid")
    
    @حمة.command(name="كل")
    async def حماية_الكل(self, ctx):
        """تشغيل جميع الحمايات"""
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        for key in ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]:
            p[key] = True
        self.save_protection_data()
        embed = discord.Embed(title="🛡️ تم تشغيل جميع الحمايات", color=0x2ECC71)
        for key in ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]:
            name = PROTECTION_NAMES.get(key, key)
            embed.add_field(name=f"🟢 {name}", value="شغّال", inline=True)
        await ctx.send(embed=embed)
    
    @حمة.command(name="حالة")
    async def حماية_حالة(self, ctx):
        """عرض حالة الحماية التفصيلية"""
        p = self.protections.get(ctx.guild.id, {})
        embed = discord.Embed(title="🛡️ حالة الحماية التفصيلية", color=0x5865F2)
        for key in ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]:
            name = PROTECTION_NAMES.get(key, key)
            state = "🟢 مفعّل" if p.get(key) else "🔴 معطّل"
            embed.add_field(name=name, value=state, inline=True)
        await ctx.send(embed=embed)
    
    @حمة.command(name="كلمات_اضافة")
    async def حماية_كلمات_اضافة(self, ctx, *, word: str):
        """إضافة كلمة محظورة"""
        data = load_data()
        bad_words = data.get("bad_words", {})
        words = bad_words.setdefault(str(ctx.guild.id), [])
        if word.lower() not in words:
            words.append(word.lower())
            mark_data_dirty()
            save_data()
            await ctx.send(f"✅ تمت إضافة الكلمة: `{word}`")
        else:
            await ctx.send(f"⚠️ الكلمة موجودة مسبقاً: `{word}`")
    
    @حمة.command(name="كلمات_حذف")
    async def حماية_كلمات_حذف(self, ctx, *, word: str):
        """حذف كلمة محظورة"""
        data = load_data()
        bad_words = data.get("bad_words", {})
        words = bad_words.get(str(ctx.guild.id), [])
        if word.lower() in words:
            words.remove(word.lower())
            mark_data_dirty()
            save_data()
            await ctx.send(f"✅ تمت إزالة الكلمة: `{word}`")
        else:
            await ctx.send(f"❌ الكلمة غير موجودة: `{word}`")
    
    @حمة.command(name="استثناء")
    async def حماية_استثناء(self, ctx, channel: discord.TextChannel, protection: str):
        """استثناء قناة من نوع حماية"""
        from protection_engine import WhitelistManager
        protection = protection.lower().strip()
        if protection not in PROTECTION_NAMES and protection != "all":
            await ctx.send(f"❌ نوع الحماية غير معروف: `{protection}`")
            return
        whitelist_manager = WhitelistManager()
        added = whitelist_manager.toggle(ctx.guild.id, channel.id, protection)
        await ctx.send(f"{'➕' if added else '➖'} تم {'إضافة' if added else 'إزالة'} {channel.mention} من استثناءات **{PROTECTION_NAMES.get(protection, 'الكل')}**")
    
    @commands.command(name="حماية_تشغيل", aliases=["تشغيل حماية", "تشغيل حمايه", "حماية تشغيل"])
    @commands.has_permissions(administrator=True)
    async def حماية_تشغيل_cmd(self, ctx):
        """تشغيل جميع الحمايات"""
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        keys = ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]
        for k in keys:
            p[k] = True
        self.save_protection_data()
        embed = discord.Embed(title="🛡️ تم تشغيل جميع الحمايات", color=0x2ECC71)
        for k in keys:
            name = PROTECTION_NAMES.get(k, k)
            embed.add_field(name=f"🟢 {name}", value="شغّال", inline=True)
        await ctx.send(embed=embed)
    
    @commands.command(name="فك_حماية", aliases=["فك حماية", "فك حمايه", "إيقاف حماية", "إيقاف_حماية"])
    @commands.has_permissions(administrator=True)
    async def فك_حماية_cmd(self, ctx):
        """إيقاف جميع الحمايات"""
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        keys = ["spam", "flood", "mention", "badwords", "invite", "alt", "raid"]
        for k in keys:
            p[k] = False
        self.save_protection_data()
        embed = discord.Embed(title="🔓 تم إيقاف جميع الحمايات", color=0xE74C3C)
        for k in keys:
            name = PROTECTION_NAMES.get(k, k)
            embed.add_field(name=f"🔴 {name}", value="معطّل", inline=True)
        await ctx.send(embed=embed)
    
    @commands.command(name="حماية_رتب", aliases=["تشغيل حماية الرتب", "حماية الرتب", "حماية رتب"])
    @commands.has_permissions(administrator=True)
    async def حماية_رتب_cmd(self, ctx):
        """حماية الرتب من التعديل غير المصرح"""
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        p["role"] = not p.get("role", False)
        self.save_protection_data()
        state = "🟢 مفعّل" if p["role"] else "🔴 معطّل"
        embed = discord.Embed(title="🛡️ حماية الرتب", color=0x2ECC71)
        embed.add_field(name="الحالة", value=state)
        embed.add_field(name="الشرح", value="يمنع إعطاء/سحب الرتب غير المصرح بها", inline=False)
        await ctx.send(embed=embed)
    
    @commands.command(name="إعفاء_رتب", aliases=["فك حماية رتب", "إعفاء رتب", "إعفاء"])
    @commands.has_permissions(administrator=True)
    async def إعفاء_رتب_cmd(self, ctx, member: discord.Member = None):
        """إعفاء عضو من حماية الرتب"""
        if not member:
            await ctx.send("❌ حدد العضو: `!إعفاء @user`")
            return
        g = ctx.guild.id
        exempt = self.role_exempt_users.setdefault(g, [])
        if member.id in exempt:
            exempt.remove(member.id)
            self.save_protection_data()
            await ctx.send(f"❌ تم **إلغاء** إعفاء {member.mention} من حماية الرتب")
        else:
            exempt.append(member.id)
            self.save_protection_data()
            await ctx.send(f"✅ تم **إعفاء** {member.mention} من حماية الرتب")
    
    @commands.command(name="قائمة_الإعفاء", aliases=["الإعفاءات", "exempt list"])
    @commands.has_permissions(administrator=True)
    async def قائمة_الإعفاء_cmd(self, ctx):
        """عرض قائمة المعفيين من حماية الرتب"""
        g = ctx.guild.id
        exempt = self.role_exempt_users.get(g, [])
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
    
    @commands.command(name="حماية_تهكير")
    @commands.has_permissions(administrator=True)
    async def حماية_تهكير_cmd(self, ctx):
        """تشغيل/إيقاف الحماية من التهكير (Anti-Nuke)"""
        g = ctx.guild.id
        p = self.protections.setdefault(g, {})
        p["nuke"] = not p.get("nuke", False)
        self.save_protection_data()
        state = "🟢 مفعّل" if p["nuke"] else "🔴 معطّل"
        embed = discord.Embed(title="🛡️ حماية التهكير (Anti-Nuke)", color=0x2ECC71 if p["nuke"] else 0xE74C3C)
        embed.add_field(name="الحالة", value=state)
        embed.add_field(name="الشرح", value="يمنع الحذف الجماعي للرومات والرتب", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Protection(bot))
