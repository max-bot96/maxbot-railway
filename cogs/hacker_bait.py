import discord
from discord.ext import commands
import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, YOUR_USER_ID, HACKER_ROLE_ID
from log_service import LogEmbed, LogColors, send_log


class HackerBait(commands.Cog):
    """🔎 صيد الهاكرز"""

    def __init__(self, bot):
        self.bot = bot

    def _load_bait_channels(self):
        data = load_data()
        return {int(k): v for k, v in data.get("hacker_bait_channels", {}).items()}

    def _save_bait_channels(self, channels):
        data = load_data()
        data["hacker_bait_channels"] = {str(k): v for k, v in channels.items()}
        mark_data_dirty()
        save_data()

    def _load_hacker_bait_kicked(self):
        data = load_data()
        return set(data.get("hacker_bait_kicked", []))

    def _save_hacker_bait_kicked(self, kicked):
        data = load_data()
        data["hacker_bait_kicked"] = list(kicked)
        mark_data_dirty()
        save_data()

    def analyze_url(self, text):
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

    def get_severity(self, account_age, url_analyses):
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

    def get_attack_methods(self, text):
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

    @commands.command(name="setbait", aliases=["تعيين_صيد"])
    @commands.has_permissions(administrator=True)
    async def setbait_cmd(self, ctx, channel: discord.TextChannel = None):
        """تعيين روم صيد الهاكرز"""
        if not channel:
            await ctx.send("❌ حدد القناة: `!setbait #channel`")
            return
        bait_channels = self._load_bait_channels()
        bait_channels[ctx.guild.id] = channel.id
        self._save_bait_channels(bait_channels)
        await ctx.send(f"✅ تم تعيين روم الصيد: {channel.mention}")

    @commands.command(name="baittoggle", aliases=["تشغيل_صيد"])
    @commands.has_permissions(administrator=True)
    async def baittoggle_cmd(self, ctx):
        """تشغيل/إيقاف صيد الهاكرز"""
        bait_channels = self._load_bait_channels()
        if ctx.guild.id in bait_channels:
            del bait_channels[ctx.guild.id]
            self._save_bait_channels(bait_channels)
            await ctx.send("🔴 تم إيقاف صيد الهاكرز!")
        else:
            bait_channels[ctx.guild.id] = ctx.channel.id
            self._save_bait_channels(bait_channels)
            await ctx.send("🟢 تم تشغيل صيد الهاكرز!")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        bait_channels = self._load_bait_channels()
        if message.guild.id not in bait_channels:
            return
        url_analyses = self.analyze_url(message.content)
        if not url_analyses:
            return
        account_age = (discord.utils.utcnow() - message.author.created_at).days
        color, severity_label = self.get_severity(account_age, url_analyses)
        methods = self.get_attack_methods(message.content)
        embed = LogEmbed.base("🔎 رسالة مشبوهة", LogColors.HACKING, guild=message.guild)
        LogEmbed.user_field(embed, message.author, "المرسل", thumb=True)
        embed.add_field(name="عمر الحساب", value=f"**{account_age}** يوم", inline=True)
        embed.add_field(name="الخطورة", value=severity_label, inline=True)
        for u in url_analyses:
            embed.add_field(name="الرابط", value=f"`{u['url'][:80]}`\n{u['verdict']}", inline=False)
        embed.add_field(name="طرق الهجوم", value="\n".join(f"• {m}" for m in methods), inline=False)
        LogEmbed.channel_field(embed, "القناة", message.channel)
        LogEmbed.message_field(embed, message)
        await send_log(message.guild.id, "log_hacking", embed)
        if message.guild.me.top_role >= message.guild.get_role(HACKER_ROLE_ID) if HACKER_ROLE_ID else False:
            try:
                await message.author.timeout(
                    discord.utils.utcnow() + discord.timedelta(hours=1),
                    reason="疑似 حساب هاكر - صيد"
                )
            except:
                pass
        embed_dm = discord.Embed(
            title="⚠️ تم اكتشاف رسالة مشبوهة!",
            description=f"لقد أرسلت رسالة مشبوهة في **{message.guild.name}**",
            color=color
        )
        embed_dm.add_field(name="الرسالة", value=message.content[:500], inline=False)
        embed_dm.add_field(name="السبب", value="\n".join(f"• {m}" for m in methods), inline=False)
        embed_dm.add_field(name="⚠️ تحذير", value="إذا كنت ضحية للاختراق، يرجى تغيير كلمة المرور فوراً!", inline=False)
        try:
            await message.author.send(embed=embed_dm)
        except:
            pass

    @commands.command(name="baitstats", aliases=["إحصائيات_الصيد"])
    @commands.has_permissions(administrator=True)
    async def baitstats_cmd(self, ctx):
        """عرض إحصائيات الصيد"""
        bait_channels = self._load_bait_channels()
        is_active = ctx.guild.id in bait_channels
        kicked = self._load_hacker_bait_kicked()
        embed = discord.Embed(title="🔎 إحصائيات صيد الهاكرز", color=0x5865F2)
        embed.add_field(name="الحالة", value="🟢 مفعّل" if is_active else "🔴 معطّل", inline=True)
        if is_active:
            ch = ctx.guild.get_channel(bait_channels[ctx.guild.id])
            embed.add_field(name="القناة", value=ch.mention if ch else "غير موجودة", inline=True)
        embed.add_field(name="المحظورين", value=str(len(kicked)), inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HackerBait(bot))
