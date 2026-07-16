import discord
from discord.ext import commands
import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty


class Economy(commands.Cog):
    """💰 نظام الاقتصاد"""

    def __init__(self, bot):
        self.bot = bot

    def _load_economy(self):
        data = load_data()
        return {int(k): {int(u): v for u, v in users.items()} for k, users in data.get("economy", {}).items()}

    def _save_economy(self, economy):
        data = load_data()
        data["economy"] = {str(k): {str(u): v for u, v in users.items()} for k, users in economy.items()}
        mark_data_dirty()
        save_data()

    def _get_user_data(self, economy, guild_id, user_id):
        guild_data = economy.setdefault(guild_id, {})
        return guild_data.setdefault(user_id, {"balance": 0, "bank": 0, "daily": 0, "work": 0})

    @commands.command(name="balance", aliases=[" رصيد", "money"])
    async def balance_cmd(self, ctx, member: discord.Member = None):
        """عرض الرصيد"""
        member = member or ctx.author
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, member.id)
        embed = discord.Embed(title=f"💰 رصيد {member.display_name}", color=0xF1C40F)
        embed.add_field(name="💵 المحفضة", value=f"**{user_data.get('balance', 0):,}** عملة", inline=True)
        embed.add_field(name="🏦 البنك", value=f"**{user_data.get('bank', 0):,}** عملة", inline=True)
        embed.add_field(name="💎 الإجمالي", value=f"**{user_data.get('balance', 0) + user_data.get('bank', 0):,}** عملة", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="daily", aliases=["يومي"])
    async def daily_cmd(self, ctx):
        """المكافأة اليومية"""
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        import time
        now = time.time()
        last_claim = user_data.get("daily", 0)
        if now - last_claim < 86400:
            remaining = 86400 - (now - last_claim)
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await ctx.send(f"❌ جرب بعد **{hours}** ساعة و **{minutes}** دقيقة!")
            return
        reward = random.randint(500, 2000)
        user_data["balance"] = user_data.get("balance", 0) + reward
        user_data["daily"] = now
        self._save_economy(economy)
        embed = discord.Embed(title="🎁 المكافأة اليومية", color=0x2ECC71)
        embed.add_field(name="المكافأة", value=f"**{reward:,}** عملة", inline=True)
        embed.add_field(name="الرصيد الجديد", value=f"**{user_data['balance']:,}** عملة", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="work", aliases=["عمل"])
    async def work_cmd(self, ctx):
        """العمل وكسب العملات"""
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        import time
        now = time.time()
        last_work = user_data.get("work", 0)
        if now - last_work < 3600:
            remaining = 3600 - (now - last_work)
            minutes = int(remaining // 60)
            await ctx.send(f"❌ جرب بعد **{minutes}** دقيقة!")
            return
        jobs = [
            ("程序员", random.randint(1000, 3000)),
            ("مطور ويب", random.randint(800, 2500)),
            ("مصمم", random.randint(700, 2000)),
            ("كاتب محتوى", random.randint(500, 1500)),
            ("送بيتزا", random.randint(400, 1200)),
            ("توصيل", random.randint(300, 1000)),
        ]
        job, reward = random.choice(jobs)
        user_data["balance"] = user_data.get("balance", 0) + reward
        user_data["work"] = now
        self._save_economy(economy)
        embed = discord.Embed(title="💼 عمل جديد!", color=0x3498DB)
        embed.add_field(name="العمل", value=job, inline=True)
        embed.add_field(name="الراتب", value=f"**{reward:,}** عملة", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="deposit", aliases=["إيداع"])
    async def deposit_cmd(self, ctx, amount: str = None):
        """إيداع عملات في البنك"""
        if not amount:
            await ctx.send("❌ حدد المبلغ: `!deposit <amount/all>`")
            return
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        balance = user_data.get("balance", 0)
        if amount.lower() == "all":
            amount_val = balance
        else:
            try:
                amount_val = int(amount)
            except ValueError:
                await ctx.send("❌ أدخل رقم صحيح!")
                return
        if amount_val <= 0:
            await ctx.send("❌ المبلغ يجب أن يكون أكبر من 0!")
            return
        if amount_val > balance:
            await ctx.send("❌ ما عندك المبلغ ده!")
            return
        user_data["balance"] -= amount_val
        user_data["bank"] = user_data.get("bank", 0) + amount_val
        self._save_economy(economy)
        embed = discord.Embed(title="🏦 تم الإيداع", color=0x2ECC71)
        embed.add_field(name="المبلغ", value=f"**{amount_val:,}** عملة", inline=True)
        embed.add_field(name="الرصيد الجديد", value=f"**{user_data['balance']:,}** عملة", inline=True)
        embed.add_field(name="البنك", value=f"**{user_data['bank']:,}** عملة", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="withdraw", aliases=["سحب"])
    async def withdraw_cmd(self, ctx, amount: str = None):
        """سحب عملات من البنك"""
        if not amount:
            await ctx.send("❌ حدد المبلغ: `!withdraw <amount/all>`")
            return
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        bank = user_data.get("bank", 0)
        if amount.lower() == "all":
            amount_val = bank
        else:
            try:
                amount_val = int(amount)
            except ValueError:
                await ctx.send("❌ أدخل رقم صحيح!")
                return
        if amount_val <= 0:
            await ctx.send("❌ المبلغ يجب أن يكون أكبر من 0!")
            return
        if amount_val > bank:
            await ctx.send("❌ ما عندك المبلغ ده في البنك!")
            return
        user_data["bank"] -= amount_val
        user_data["balance"] = user_data.get("balance", 0) + amount_val
        self._save_economy(economy)
        embed = discord.Embed(title="💸 تم السحب", color=0xE67E22)
        embed.add_field(name="المبلغ", value=f"**{amount_val:,}** عملة", inline=True)
        embed.add_field(name="الرصيد", value=f"**{user_data['balance']:,}** عملة", inline=True)
        embed.add_field(name="البنك", value=f"**{user_data['bank']:,}** عملة", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="pay", aliases=["إرسال", "transfer"])
    async def pay_cmd(self, ctx, member: discord.Member = None, amount: int = None):
        """إرسال عملات لعضو"""
        if not member or not amount:
            await ctx.send("❌ حدد: `!pay @user <amount>`")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ لا تقدر ترسل لنفسك!")
            return
        economy = self._load_economy()
        sender = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        if sender.get("balance", 0) < amount:
            await ctx.send("❌ ما عندك المبلغ ده!")
            return
        receiver = self._get_user_data(economy, ctx.guild.id, member.id)
        sender["balance"] -= amount
        receiver["balance"] = receiver.get("balance", 0) + amount
        self._save_economy(economy)
        embed = discord.Embed(title="💸 تم الإرسال", color=0x9B59B6)
        embed.add_field(name="المرسل", value=ctx.author.mention, inline=True)
        embed.add_field(name="المستلم", value=member.mention, inline=True)
        embed.add_field(name="المبلغ", value=f"**{amount:,}** عملة", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["لوحة", "top"])
    async def leaderboard_cmd(self, ctx):
        """لوحة المتصدرين"""
        economy = self._load_economy()
        guild_data = economy.get(ctx.guild.id, {})
        sorted_users = sorted(guild_data.items(), key=lambda x: x[1].get("balance", 0) + x[1].get("bank", 0), reverse=True)[:10]
        if not sorted_users:
            await ctx.send("❌ لا يوجد بيانات بعد!")
            return
        embed = discord.Embed(title="🏆 لوحة المتصدرين", color=0xF1C40F)
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(sorted_users):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"غير معروف ({user_id})"
            total = data.get("balance", 0) + data.get("bank", 0)
            prefix = medals[i] if i < 3 else f"**#{i+1}**"
            embed.add_field(name=f"{prefix} {name}", value=f"**{total:,}** عملة", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="shop", aliases=["متجر"])
    async def shop_cmd(self, ctx):
        """عرض المتجر"""
        embed = discord.Embed(title="🛒 المتجر", color=0x9B59B6)
        embed.add_field(name="🏷️ تغيير الاسم", value="**5,000** عملة\n`!buy rename <الاسم الجديد>`", inline=False)
        embed.add_field(name="🎨 لون مخصص", value="**3,000** عملة\n`!buy color <hex>`", inline=False)
        embed.add_field(name="⭐ رتبة خاصة", value="**10,000** عملة\n`!buy specialrole`", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buy", aliases=["شراء"])
    async def buy_cmd(self, ctx, item: str = None, *, value: str = None):
        """شراء من المتجر"""
        if not item:
            await ctx.send("❌ حدد الصنف: `!buy <item> [value]`")
            return
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        prices = {"rename": 5000, "color": 3000, "specialrole": 10000}
        price = prices.get(item.lower())
        if not price:
            await ctx.send("❌ الصنف غير موجود! استخدم `!shop` لعرض المتجر")
            return
        if user_data.get("balance", 0) < price:
            await ctx.send(f"❌ تحتاج **{price:,}** عملة لشراء هذا الصنف!")
            return
        user_data["balance"] -= price
        self._save_economy(economy)
        embed = discord.Embed(title="✅ تم الشراء", color=0x2ECC71)
        embed.add_field(name="الصنف", value=item, inline=True)
        embed.add_field(name="السعر", value=f"**{price:,}** عملة", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="slots", aliases=["ماكينة"])
    async def slots_cmd(self, ctx, bet: int = 100):
        """ماكينة القمار"""
        economy = self._load_economy()
        user_data = self._get_user_data(economy, ctx.guild.id, ctx.author.id)
        if user_data.get("balance", 0) < bet:
            await ctx.send(f"❌ تحتاج **{bet:,}** عملة!")
            return
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        results = [random.choice(symbols) for _ in range(3)]
        if results[0] == results[1] == results[2]:
            winnings = bet * 10
            result = "🎉 JACKPOT!"
            color = 0xF1C40F
            user_data["balance"] += winnings
        elif results[0] == results[1] or results[1] == results[2] or results[0] == results[2]:
            winnings = bet * 2
            result = "🎉 ربحت!"
            color = 0x2ECC71
            user_data["balance"] += winnings
        else:
            winnings = -bet
            result = "❌ خسرت!"
            color = 0xE74C3C
            user_data["balance"] -= bet
        self._save_economy(economy)
        embed = discord.Embed(title="🎰 ماكينة القمار", color=color)
        embed.add_field(name="النتيجة", value=f"**{results[0]} | {results[1]} | {results[2]}**", inline=False)
        embed.add_field(name=result, value=f"**{abs(winnings):,}** عملة", inline=True)
        embed.add_field(name="الرصيد", value=f"**{user_data['balance']:,}** عملة", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Economy(bot))
