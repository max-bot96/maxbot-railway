import discord
from discord.ext import commands
import sys
import os
import random
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty
from log_service import LogEmbed, LogColors, send_log


class Fun(commands.Cog):
    """🎮 الأوامر الترفيهية"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="meme", aliases=["ميم"])
    async def meme_cmd(self, ctx):
        """إرسال ميم عشوائي"""
        memes = [
            "😂 تم إرسال ميم",
            "🤣 ميم جميل",
            "💀 هذا ميم رائع",
            "😹 ميم مضحك",
            "🤣 لا أستطيع التوقف عن الضحك",
        ]
        embed = discord.Embed(title="🎭 ميم عشوائي", description=random.choice(memes), color=0x9B59B6)
        await ctx.send(embed=embed)

    @commands.command(name="8ball", aliases=["8ball"])
    async def eight_ball_cmd(self, ctx, *, question: str = None):
        """كرة الثماني السحرية"""
        if not question:
            await ctx.send("❌ اسأل سؤالاً!")
            return
        responses = [
            "✅ نعم بالتأكيد!",
            "✅ أيوه طبعاً!",
            "❌ لا لا لا!",
            "❌ مستحيل!",
            "🤔 يمكن...",
            "🤔 لعل و عسى",
            "✅ أكيد!",
            "❌ ما أعتقد",
            "🤔 سأتحقق لاحقاً",
            "✅ نعم!",
            "❌ لا!",
            "🤔 حظك اليوم مش حلو",
            "✅ بالطبع!",
            "❌ أبداً!",
        ]
        embed = discord.Embed(title="🎱 كرة الثماني", color=0x9B59B6)
        embed.add_field(name="السؤال", value=question, inline=False)
        embed.add_field(name="الإجابة", value=random.choice(responses), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="poll", aliases=["تصويت"])
    async def poll_cmd(self, ctx, *, question: str = None):
        """إنشاء تصويت"""
        if not question:
            await ctx.send("❌ حدد السؤال: `!poll <question>`")
            return
        embed = discord.Embed(title="📊 تصويت", description=question, color=0x5865F2)
        embed.set_footer(text=f"صوّت بواسطة {ctx.author.display_name}")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

    @commands.command(name="rate", aliases=["تقييم"])
    async def rate_cmd(self, ctx, *, thing: str = None):
        """تقييم شيء ما"""
        if not thing:
            await ctx.send("❌ حدد الشيء: `!rate <thing>`")
            return
        rating = random.randint(0, 10)
        stars = "⭐" * rating + "☆" * (10 - rating)
        embed = discord.Embed(title="⭐ تقييم", color=0xF1C40F)
        embed.add_field(name="الشيء", value=thing, inline=False)
        embed.add_field(name="التقييم", value=f"{stars}\n**{rating}/10**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="ship", aliases=["זוגية"])
    async def ship_cmd(self, ctx, member1: discord.Member = None, member2: discord.Member = None):
        """حساب التوافق بين عضوين"""
        if not member1 or not member2:
            await ctx.send("❌ حدد عضوين: `!ship @user1 @user2`")
            return
        ship_percent = random.randint(0, 100)
        if ship_percent >= 80:
            status = "❤️ توافق عالي! ينصح بالارتباط!"
            color = 0xE74C3C
        elif ship_percent >= 50:
            status = "💕 توافق متوسط، يمكن المحاولة!"
            color = 0xFF69B4
        elif ship_percent >= 30:
            status = "💔 توافق منخفض..."
            color = 0xE67E22
        else:
            status = "💀 لا توافق نهائياً!"
            color = 0x747F8D
        bar_length = 10
        filled = int(bar_length * ship_percent / 100)
        bar = "❤️" * filled + "🤍" * (bar_length - filled)
        embed = discord.Embed(title="💘 توافق", color=color)
        embed.add_field(name=f"{member1.display_name}", value="❤️", inline=True)
        embed.add_field(name=f"{member2.display_name}", value="❤️", inline=True)
        embed.add_field(name="النتيجة", value=f"**{ship_percent}%**\n{bar}\n{status}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="say", aliases=["قل"])
    async def say_cmd(self, ctx, *, text: str = None):
        """جعل البوت يقول شيئاً"""
        if not text:
            await ctx.send("❌ حدد النص: `!say <text>`")
            return
        await ctx.message.delete()
        await ctx.send(text)

    @commands.command(name="echo", aliases=["تكرار"])
    async def echo_cmd(self, ctx, *, text: str = None):
        """تكرار النص"""
        if not text:
            await ctx.send("❌ حدد النص: `!echo <text>`")
            return
        embed = discord.Embed(description=text, color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.command(name="reverse", aliases=["عكس"])
    async def reverse_cmd(self, ctx, *, text: str = None):
        """عكس النص"""
        if not text:
            await ctx.send("❌ حدد النص: `!reverse <text>`")
            return
        reversed_text = text[::-1]
        embed = discord.Embed(title="🔄 عكس النص", color=0x9B59B6)
        embed.add_field(name="الأصلي", value=text, inline=False)
        embed.add_field(name="المعكوس", value=reversed_text, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="binary", aliases=["ثنائي"])
    async def binary_cmd(self, ctx, *, text: str = None):
        """تحويل النص إلى ثنائي"""
        if not text:
            await ctx.send("❌ حدد النص: `!binary <text>`")
            return
        binary = ' '.join(format(ord(c), '08b') for c in text)
        embed = discord.Embed(title="💻 تحويل ثنائي", color=0x2ECC71)
        embed.add_field(name="النص", value=text, inline=False)
        embed.add_field(name="ثنائي", value=f"```{binary}```", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="choose", aliases=["اختر"])
    async def choose_cmd(self, ctx, *, choices: str = None):
        """اختيار عشوائي من خيارات"""
        if not choices:
            await ctx.send("❌ حدد الخيارات مفصولة بـ |: `!choose option1 | option2 | option3`")
            return
        options = [c.strip() for c in choices.split("|")]
        if len(options) < 2:
            await ctx.send("❌ تحتاج خيارين على الأقل!")
            return
        chosen = random.choice(options)
        embed = discord.Embed(title="🎲 اختيار عشوائي", color=0x5865F2)
        embed.add_field(name="الخيارات", value="\n".join(f"• {o}" for o in options), inline=False)
        embed.add_field(name="الاختيار", value=f"**{chosen}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="roll", aliases=["رمي"])
    async def roll_cmd(self, ctx, sides: int = 6):
        """رمي نرد"""
        result = random.randint(1, sides)
        embed = discord.Embed(title="🎲 رمي النرد", color=0x9B59B6)
        embed.add_field(name="النتيجة", value=f"**{result}**", inline=True)
        embed.add_field(name="النوع", value=f"1-{sides}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="howgay", aliases=["شذوذ"])
    async def howgay_cmd(self, ctx, member: discord.Member = None):
        """نسبة الشذوذ"""
        member = member or ctx.author
        percent = random.randint(0, 100)
        if percent > 75:
            status = "🏳️‍🌈 مثلي تماماً!"
        elif percent > 50:
            status = "🏳️‍🌈 يميل للشذوذ"
        elif percent > 25:
            status = "🤔 قد يكون"
        else:
            status = "💪 مذكر!"
        embed = discord.Embed(title="🏳️‍🌈 نسبة الشذوذ", color=0xFF69B4)
        embed.add_field(name=member.display_name, value=f"**{percent}%**\n{status}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="simp", aliases=["تحب"])
    async def simp_cmd(self, ctx, member: discord.Member = None):
        """نسبة الحب"""
        member = member or ctx.author
        percent = random.randint(0, 100)
        embed = discord.Embed(title="💕 نسبة الحب", color=0xE74C3C)
        embed.add_field(name=member.display_name, value=f"**{percent}%** حب", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="slap", aliases=["صفعة"])
    async def slap_cmd(self, ctx, member: discord.Member = None):
        """ gave someone a slap"""
        if not member:
            await ctx.send("❌ حدد العضو: `!slap @user`")
            return
        embed = discord.Embed(title="👋 صفعة!", color=0xE74C3C)
        embed.description = f"**{ctx.author.display_name}** gave **{member.display_name}** a slap! 👋"
        await ctx.send(embed=embed)

    @commands.command(name="hug", aliases=["عناق"])
    async def hug_cmd(self, ctx, member: discord.Member = None):
        """عناق لعضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!hug @user`")
            return
        embed = discord.Embed(title="🤗 عناق!", color=0xFF69B4)
        embed.description = f"**{ctx.author.display_name}** عانق **{member.display_name}**! 🤗"
        await ctx.send(embed=embed)

    @commands.command(name="kiss", aliases=["قبلة"])
    async def kiss_cmd(self, ctx, member: discord.Member = None):
        """قبلة لعضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!kiss @user`")
            return
        embed = discord.Embed(title="💋 قبلة!", color=0xE74C3C)
        embed.description = f"**{ctx.author.display_name}** قبل **{member.display_name}**! 💋"
        await ctx.send(embed=embed)

    @commands.command(name="cry", aliases=["بكي"])
    async def cry_cmd(self, ctx):
        """البكي"""
        embed = discord.Embed(title="😢 يبكي!", description=f"**{ctx.author.display_name}** يبكي! 😭", color=0x3498DB)
        await ctx.send(embed=embed)

    @commands.command(name="laugh", aliases=["ضحك"])
    async def laugh_cmd(self, ctx):
        """الضحك"""
        embed = discord.Embed(title="😂 يضحك!", description=f"**{ctx.author.display_name}** يضحك! 🤣", color=0xF1C40F)
        await ctx.send(embed=embed)

    @commands.command(name="wave", aliases=["تلويح"])
    async def wave_cmd(self, ctx, member: discord.Member = None):
        """تلويح لعضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!wave @user`")
            return
        embed = discord.Embed(title="👋 يلوّح!", description=f"**{ctx.author.display_name}** يلوّح لـ **{member.display_name}**! 👋", color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.command(name="highfive", aliases=["تصفيق"])
    async def highfive_cmd(self, ctx, member: discord.Member = None):
        """تصفيق"""
        if not member:
            await ctx.send("❌ حدد العضو: `!highfive @user`")
            return
        embed = discord.Embed(title="🖐️ تصفية!", description=f"**{ctx.author.display_name}** and **{member.display_name}** high five! 🖐️", color=0x2ECC71)
        await ctx.send(embed=embed)

    @commands.command(name="pat", aliases=["دلال"])
    async def pat_cmd(self, ctx, member: discord.Member = None):
        """دلال لعضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!pat @user`")
            return
        embed = discord.Embed(title="🤗 دلال!", description=f"**{ctx.author.display_name}** يدلل **{member.display_name}**! 🤗", color=0xFF69B4)
        await ctx.send(embed=embed)

    @commands.command(name="punch", aliases=["لكم"])
    async def punch_cmd(self, ctx, member: discord.Member = None):
        """لكم عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!punch @user`")
            return
        embed = discord.Embed(title="👊 لكم!", description=f"**{ctx.author.display_name}** لكم **{member.display_name}**! 👊", color=0xE74C3C)
        await ctx.send(embed=embed)

    @commands.command(name="bite", aliases=["عض"])
    async def bite_cmd(self, ctx, member: discord.Member = None):
        """عض عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!bite @user`")
            return
        embed = discord.Embed(title="🦷 عض!", description=f"**{ctx.author.display_name}** عض **{member.display_name}**! 🦷", color=0x9B59B6)
        await ctx.send(embed=embed)

    @commands.command(name="lick", aliases=["لعق"])
    async def lick_cmd(self, ctx, member: discord.Member = None):
        """لعق عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!lick @user`")
            return
        embed = discord.Embed(title="👅 لعق!", description=f"**{ctx.author.display_name}** لعق **{member.display_name}**! 👅", color=0xFF69B4)
        await ctx.send(embed=embed)

    @commands.command(name="poke", aliases=["دغدغة"])
    async def poke_cmd(self, ctx, member: discord.Member = None):
        """دغدغة عضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!poke @user`")
            return
        embed = discord.Embed(title="👉 دغدغة!", description=f"**{ctx.author.display_name}** دغدغ **{member.display_name}**! 👉", color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.command(name="stonk", aliases=["stock"])
    async def stonk_cmd(self, ctx):
        """stonks"""
        embed = discord.Embed(title="📈 STONKS!", description="**stonks** 📈", color=0x2ECC71)
        await ctx.send(embed=embed)

    @commands.command(name="notstonk", aliases=["notstock"])
    async def notstonk_cmd(self, ctx):
        """not stonks"""
        embed = discord.Embed(title="📉 Not Stonks!", description="**not stonks** 📉", color=0xE74C3C)
        await ctx.send(embed=embed)

    @commands.command(name="f", aliases=["احترام"])
    async def f_cmd(self, ctx):
        """F to pay respects"""
        embed = discord.Embed(title="🫡 F to pay respects", description=f"**{ctx.author.display_name}** pays respects", color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.command(name="clap", aliases=["تصفيق_يد"])
    async def clap_cmd(self, ctx, *, text: str = None):
        """تصفيق"""
        if not text:
            await ctx.send("❌ حدد النص: `!clap <text>`")
            return
        clapped = " 👏 ".join(text.split())
        embed = discord.Embed(title="👏 تصفيق!", description=clapped, color=0xF1C40F)
        await ctx.send(embed=embed)

    @commands.command(name="emojify", aliases=["تحويل_إيموجي"])
    async def emojify_cmd(self, ctx, *, text: str = None):
        """تحويل النص إلى إيموجي"""
        if not text:
            await ctx.send("❌ حدد النص: `!emojify <text>`")
            return
       emojis = {
            'a': '🇦', 'b': '🇧', 'c': '🇨', 'd': '🇩', 'e': '🇪',
            'f': '🇫', 'g': '🇬', 'h': '🇭', 'i': '🇮', 'j': '🇯',
            'k': '🇰', 'l': '🇱', 'm': '🇲', 'n': '🇳', 'o': '🇴',
            'p': '🇵', 'q': '🇶', 'r': '🇷', 's': '🇸', 't': '🇹',
            'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽', 'y': '🇾',
            'z': '🇿', ' ': '  '
        }
        result = ''.join(emojis.get(c.lower(), c) for c in text)
        await ctx.send(result)

    @commands.command(name="password", aliases=["كلمة_سر"])
    async def password_cmd(self, ctx, length: int = 16):
        """إنشاء كلمة سر عشوائية"""
        import string
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(random.choice(chars) for _ in range(length))
        embed = discord.Embed(title="🔑 كلمة سر عشوائية", color=0x2ECC71)
        embed.add_field(name="كلمة السر", value=f"```{password}```", inline=False)
        embed.add_field(name="الطول", value=f"**{length}** حرف", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="color", aliases=["لون"])
    async def color_cmd(self, ctx, member: discord.Member = None):
        """عرض لون رتبة العضو"""
        member = member or ctx.author
        color = member.color
        embed = discord.Embed(title=f"🎨 لون {member.display_name}", color=color)
        embed.add_field(name="اللون", value=f"**{str(color)}**", inline=True)
        embed.add_field(name="Hex", value=f"`{color.value:06x}`", inline=True)
        embed.add_field(name="RGB", value=f"`{color.r}, {color.g}, {color.b}`", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="remind", aliases=["تذكير"])
    async def remind_cmd(self, ctx, minutes: int = None, *, text: str = None):
        """تذكير بعد وقت"""
        if not minutes or not text:
            await ctx.send("❌ حدد: `!remind <minutes> <text>`")
            return
        await ctx.send(f"✅ سأتذكرك بعد **{minutes}** دقيقة!")
        await asyncio.sleep(minutes * 60)
        embed = discord.Embed(title="⏰ تذكير!", description=f"{ctx.author.mention}\n{text}", color=0xF1C40F)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
