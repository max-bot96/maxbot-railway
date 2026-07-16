import discord
from discord.ext import commands
import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty


class Games(commands.Cog):
    """🎮 نظام الألعاب"""

    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}

    @commands.command(name="rps", aliases=["ورقة_حجر_مقص"])
    async def rps_cmd(self, ctx, choice: str = None):
        """ورقة حجر مقص"""
        if not choice:
            await ctx.send("❌ حدد: `!rps <ورقة/حجر/مقص>`")
            return
        choices_map = {"ورقة": "📄", "حجر": "🪨", "مقص": "✂️", "rock": "🪨", "paper": "📄", "scissors": "✂️"}
        choice_lower = choice.lower()
        if choice_lower not in choices_map:
            await ctx.send("❌ اختر: `ورقة` أو `حجر` أو `مقص`")
            return
        user_choice = choice_lower
        bot_choice = random.choice(list(choices_map.keys()))
        user_emoji = choices_map[user_choice]
        bot_emoji = choices_map[bot_choice]
        if user_choice == bot_choice:
            result = "🤝 تعادل!"
            color = 0xF1C40F
        elif (user_choice in ["ورقة", "paper"] and bot_choice in ["حجر", "rock"]) or \
             (user_choice in ["حجر", "rock"] and bot_choice in ["مقص", "scissors"]) or \
             (user_choice in ["مقص", "scissors"] and bot_choice in ["ورقة", "paper"]):
            result = "🎉 ربحت!"
            color = 0x2ECC71
        else:
            result = "❌ خسرت!"
            color = 0xE74C3C
        embed = discord.Embed(title="🎮 ورقة حجر مقص", color=color)
        embed.add_field(name="أنت", value=user_emoji, inline=True)
        embed.add_field(name="البوت", value=bot_emoji, inline=True)
        embed.add_field(name="النتيجة", value=result, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="coinflip", aliases=["قلب_العملة"])
    async def coinflip_cmd(self, ctx):
        """قلب العملة"""
        result = random.choice(["👑", "🪙"])
        embed = discord.Embed(title="🪙 قلب العملة", color=0xF1C40F)
        embed.add_field(name="النتيجة", value=result, inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="dice", aliases=["نرد"])
    async def dice_cmd(self, ctx, sides: int = 6):
        """رمي النرد"""
        if sides < 2 or sides > 100:
            sides = 6
        result = random.randint(1, sides)
        embed = discord.Embed(title="🎲 رمي النرد", color=0x9B59B6)
        embed.add_field(name="النتيجة", value=f"**{result}**", inline=True)
        embed.add_field(name="النوع", value=f"1-{sides}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="trivia", aliases=["�� Quiz"])
    async def trivia_cmd(self, ctx):
        """سؤال سريع"""
        questions = [
            {"q": "ما عاصمة فرنسا؟", "a": "باريس", "options": ["لندن", "باريس", "برلين", "روما"]},
            {"q": "كم عدد كواكب المجموعة الشمسية؟", "a": "8", "options": ["7", "8", "9", "10"]},
            {"q": "ما أكبر كوكب في المجموعة الشمسية؟", "a": "المشتري", "options": ["زحل", "المشتري", "الأرض", "نبتون"]},
            {"q": "ما هو الحيوان الأسرع في العالم؟", "a": "الفهد", "options": ["الأسد", "الفهد", "الحصان", "النسر"]},
            {"q": "كم عدد أضلاع المثلث؟", "a": "3", "options": ["2", "3", "4", "5"]},
            {"q": "ما هي اللغة الأكثر تحدثاً في العالم؟", "a": "الصينية", "a": "الإنجليزية", "options": ["الإنجليزية", "الإسبانية", "الصينية", "العربية"]},
            {"q": "في أي سنة نزل الإنسان على القمر؟", "a": "1969", "options": ["1965", "1969", "1972", "1975"]},
            {"q": "ما هو العنصر الكيميائي الذي رمزه O؟", "a": "الأكسجين", "options": ["الذهب", "الأكسجين", "الفضة", "الحديد"]},
        ]
        q_data = random.choice(questions)
        options = q_data["options"]
        random.shuffle(options)
        embed = discord.Embed(title="❓ سؤال سريع", description=q_data["q"], color=0x5865F2)
        for i, opt in enumerate(options, 1):
            embed.add_field(name=f"{'🔹' if opt != q_data['a'] else '✅'} {i}.", value=opt, inline=False)
        embed.set_footer(text="أرسل الرقم الصحيح!")
        await ctx.send(embed=embed)
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=15)
            try:
                answer = int(msg.content)
                if 1 <= answer <= len(options):
                    selected = options[answer - 1]
                    if selected == q_data["a"]:
                        await ctx.send(f"✅ إجابة صحيحة! **{q_data['a']}**")
                    else:
                        await ctx.send(f"❌ إجابة خاطئة! الإجابة الصحيحة: **{q_data['a']}**")
                else:
                    await ctx.send(f"❌ رقم غير صالح! الإجابة: **{q_data['a']}**")
            except ValueError:
                await ctx.send(f"❌ أدخل رقم! الإجابة: **{q_data['a']}**")
        except:
            await ctx.send(f"⏰ انتهى الوقت! الإجابة: **{q_data['a']}**")

    @commands.command(name="race", aliases=["سباق"])
    async def race_cmd(self, ctx, member: discord.Member = None):
        """سباق بينك وبين عضو آخر"""
        if not member:
            await ctx.send("❌ حدد العضو: `!race @user`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدرتسابق مع نفسك!")
            return
        user_progress = 0
        bot_progress = 0
        track = "⬛" * 10
        embed = discord.Embed(title="🏁 سباق!", color=0x5865F2)
        embed.add_field(name=f"🏁 {ctx.author.display_name}", value=f"{'🟩' * user_progress}{'⬛' * (10 - user_progress)}", inline=False)
        embed.add_field(name=f"🏁 {member.display_name}", value=f"{'🟩' * bot_progress}{'⬛' * (10 - bot_progress)}", inline=False)
        msg = await ctx.send(embed=embed)
        while user_progress < 10 and bot_progress < 10:
            await asyncio.sleep(1)
            if random.random() > 0.5:
                user_progress = min(10, user_progress + random.randint(1, 3))
            else:
                bot_progress = min(10, bot_progress + random.randint(1, 3))
            embed = discord.Embed(title="🏁 سباق!", color=0x5865F2)
            embed.add_field(name=f"🏁 {ctx.author.display_name}", value=f"{'🟩' * user_progress}{'⬛' * (10 - user_progress)}", inline=False)
            embed.add_field(name=f"🏁 {member.display_name}", value=f"{'🟩' * bot_progress}{'⬛' * (10 - bot_progress)}", inline=False)
            await msg.edit(embed=embed)
        if user_progress >= 10:
            await ctx.send(f"🎉 {ctx.author.mention} ربح السباق!")
        else:
            await ctx.send(f"🎉 {member.mention} ربح السباق!")

    @commands.command(name="tictactoe", aliases=["اكس_او"])
    async def tictactoe_cmd(self, ctx, member: discord.Member = None):
        """اكس أو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!tictactoe @user`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدر تلعب مع نفسك!")
            return
        board = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        current_player = ctx.author
        symbol = "❌"
        await ctx.send(f"🎯 **{ctx.author.display_name}** vs **{member.display_name}**\n**{ctx.author.display_name}** يبدأ بـ ❌")
        def check(m):
            return m.author == current_player and m.channel == ctx.channel
        for _ in range(9):
            embed = discord.Embed(title="🎮 اكس أو", color=0x5865F2)
            embed.description = f"**{board[0]}** | **{board[1]}** | **{board[2]}**\n**{board[3]}** | **{board[4]}** | **{board[5]}**\n**{board[6]}** | **{board[7]}** | **{board[8]}**"
            await ctx.send(embed=embed)
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=30)
                pos = int(msg.content) - 1
                if pos < 0 or pos > 8 or board[pos] in ["❌", "⭕"]:
                    await ctx.send("❌ مكان غير صالح!", delete_after=2)
                    continue
                board[pos] = symbol
                winning_combos = [
                    [0,1,2], [3,4,5], [6,7,8],
                    [0,3,6], [1,4,7], [2,5,8],
                    [0,4,8], [2,4,6]
                ]
                for combo in winning_combos:
                    if board[combo[0]] == board[combo[1]] == board[combo[2]] == symbol:
                        embed = discord.Embed(title="🎉 فوز!", color=0x2ECC71)
                        embed.description = f"**{current_player.display_name}** فاز بـ {symbol}!"
                        await ctx.send(embed=embed)
                        return
                symbol = "⭕" if symbol == "❌" else "❌"
                current_player = member if current_player == ctx.author else ctx.author
            except:
                await ctx.send("⏰ انتهى الوقت!")
                return
        await ctx.send("🤝 تعادل!")


import asyncio


async def setup(bot):
    await bot.add_cog(Games(bot))
