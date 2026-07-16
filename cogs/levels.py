import discord
from discord.ext import commands
import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty


class Levels(commands.Cog):
    """📈 نظام المستويات والـ XP"""

    def __init__(self, bot):
        self.bot = bot
        self.xp_cooldown = {}

    def _load_xp_data(self):
        data = load_data()
        return {int(k): {int(u): v for u, v in users.items()} for k, users in data.get("xp", {}).items()}

    def _save_xp_data(self, xp_data):
        data = load_data()
        data["xp"] = {str(k): {str(u): v for u, v in users.items()} for k, users in xp_data.items()}
        mark_data_dirty()
        save_data()

    def _load_level_rewards(self):
        data = load_data()
        return {int(k): {int(l): r for l, r in rewards.items()} for k, rewards in data.get("level_rewards", {}).items()}

    def _save_level_rewards(self, rewards):
        data = load_data()
        data["level_rewards"] = {str(k): {str(l): r for l, r in v.items()} for k, v in rewards.items()}
        mark_data_dirty()
        save_data()

    def get_level_from_xp(self, xp):
        level = 1
        xp_needed = 100
        while xp >= xp_needed:
            xp -= xp_needed
            level += 1
            xp_needed = int(xp_needed * 1.5)
        return level

    def get_xp_for_level(self, level):
        xp_needed = 100
        for _ in range(level - 1):
            xp_needed = int(xp_needed * 1.5)
        return xp_needed

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        import time
        now = time.time()
        last_xp = self.xp_cooldown.get(message.author.id, 0)
        if now - last_xp < 60:
            return
        self.xp_cooldown[message.author.id] = now
        xp_data = self._load_xp_data()
        guild_data = xp_data.setdefault(message.guild.id, {})
        user_data = guild_data.setdefault(message.author.id, {"xp": 0, "level": 1})
        old_level = user_data.get("level", 1)
        user_data["xp"] = user_data.get("xp", 0) + random.randint(15, 25)
        new_level = self.get_level_from_xp(user_data["xp"])
        user_data["level"] = new_level
        self._save_xp_data(xp_data)
        if new_level > old_level:
            embed = discord.Embed(
                title="🎉 ترقية!",
                description=f"**{message.author.mention}** وصل للمستوى **{new_level}**!",
                color=0xF1C40F
            )
            await message.channel.send(embed=embed, delete_after=10)
            level_rewards = self._load_level_rewards()
            guild_rewards = level_rewards.get(message.guild.id, {})
            if new_level in guild_rewards:
                role_id = guild_rewards[new_level]
                role = message.guild.get_role(role_id)
                if role:
                    try:
                        await message.author.add_roles(role, reason=f"Level {new_level} reward")
                        reward_embed = discord.Embed(
                            title="🎁 مكافأة المستوى!",
                            description=f"حصلت على رتبة **{role.name}**!",
                            color=0x2ECC71
                        )
                        await message.channel.send(embed=reward_embed, delete_after=10)
                    except:
                        pass

    @commands.command(name="rank", aliases=["مستوى"])
    async def rank_cmd(self, ctx, member: discord.Member = None):
        """عرض مستوى عضو"""
        member = member or ctx.author
        xp_data = self._load_xp_data()
        guild_data = xp_data.get(ctx.guild.id, {})
        user_data = guild_data.get(member.id, {"xp": 0, "level": 1})
        xp = user_data.get("xp", 0)
        level = user_data.get("level", 1)
        xp_needed = self.get_xp_for_level(level)
        xp_in_level = xp
        for i in range(1, level):
            xp_in_level -= self.get_xp_for_level(i)
        progress = int((xp_in_level / xp_needed) * 100) if xp_needed > 0 else 0
        bar_length = 20
        filled = int(bar_length * progress / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        embed = discord.Embed(title=f"📊 {member.display_name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="المستوى", value=f"**{level}**", inline=True)
        embed.add_field(name="الـ XP", value=f"**{xp:,}**", inline=True)
        embed.add_field(name="التقدم", value=f"```{bar}``` {progress}% ({xp_in_level}/{xp_needed})", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["لوحة_المتصدرين"])
    async def leaderboard_cmd(self, ctx):
        """لوحة متصدرين"""
        xp_data = self._load_xp_data()
        guild_data = xp_data.get(ctx.guild.id, {})
        sorted_users = sorted(guild_data.items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:10]
        if not sorted_users:
            await ctx.send("❌ لا يوجد بيانات بعد!")
            return
        embed = discord.Embed(title="🏆 لوحة المتصدرين", color=0xF1C40F)
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(sorted_users):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"غير معروف ({user_id})"
            xp = data.get("xp", 0)
            level = data.get("level", 1)
            prefix = medals[i] if i < 3 else f"**#{i+1}**"
            embed.add_field(name=f"{prefix} {name}", value=f"المستوى **{level}** | **{xp:,}** XP", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="setlevelreward", aliases=["مكافأة_مستوى"])
    @commands.has_permissions(administrator=True)
    async def setlevelreward_cmd(self, ctx, level: int = None, role: discord.Role = None):
        """تعيين مكافأة المستوى"""
        if not level or not role:
            await ctx.send("❌ حدد: `!setlevelreward <level> @role`")
            return
        level_rewards = self._load_level_rewards()
        guild_rewards = level_rewards.setdefault(ctx.guild.id, {})
        guild_rewards[level] = role.id
        self._save_level_rewards(level_rewards)
        await ctx.send(f"✅ مكافأة المستوى **{level}** = {role.mention}")

    @commands.command(name="removereward", aliases=["حذف_مكافأة"])
    @commands.has_permissions(administrator=True)
    async def removereward_cmd(self, ctx, level: int = None):
        """حذف مكافأة المستوى"""
        if not level:
            await ctx.send("❌ حدد المستوى: `!removereward <level>`")
            return
        level_rewards = self._load_level_rewards()
        guild_rewards = level_rewards.get(ctx.guild.id, {})
        if level in guild_rewards:
            del guild_rewards[level]
            self._save_level_rewards(level_rewards)
            await ctx.send(f"✅ تم حذف مكافأة المستوى **{level}**")
        else:
            await ctx.send(f"❌ لا توجد مكافأة للمستوى **{level}**!")

    @commands.command(name="rewards", aliases=["المكافآت"])
    async def rewards_cmd(self, ctx):
        """عرض المكافآت"""
        level_rewards = self._load_level_rewards()
        guild_rewards = level_rewards.get(ctx.guild.id, {})
        if not guild_rewards:
            await ctx.send("❌ لا توجد مكافآت بعد!")
            return
        embed = discord.Embed(title="🎁 مكافآت المستويات", color=0x2ECC71)
        for level, role_id in sorted(guild_rewards.items()):
            role = ctx.guild.get_role(role_id)
            role_name = role.mention if role else f"رتبة محذوفة ({role_id})"
            embed.add_field(name=f"المستوى {level}", value=role_name, inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="setxp", aliases=["تعيين_xp"])
    @commands.has_permissions(administrator=True)
    async def setxp_cmd(self, ctx, member: discord.Member = None, amount: int = None):
        """تعيين XP لعضو"""
        if not member or not amount:
            await ctx.send("❌ حدد: `!setxp @user <amount>`")
            return
        xp_data = self._load_xp_data()
        guild_data = xp_data.setdefault(ctx.guild.id, {})
        user_data = guild_data.setdefault(member.id, {"xp": 0, "level": 1})
        user_data["xp"] = amount
        user_data["level"] = self.get_level_from_xp(amount)
        self._save_xp_data(xp_data)
        await ctx.send(f"✅ تم تعيين XP {member.mention} إلى **{amount:,}** (المستوى **{user_data['level']}**)")

    @commands.command(name="resetxp", aliases=["إعادة_تعيين"])
    @commands.has_permissions(administrator=True)
    async def resetxp_cmd(self, ctx, member: discord.Member = None):
        """إعادة تعيين XP لعضو"""
        if not member:
            await ctx.send("❌ حدد العضو: `!resetxp @user`")
            return
        xp_data = self._load_xp_data()
        guild_data = xp_data.get(ctx.guild.id, {})
        if member.id in guild_data:
            del guild_data[member.id]
            self._save_xp_data(xp_data)
            await ctx.send(f"✅ تم إعادة تعيين XP {member.mention}")
        else:
            await ctx.send(f"❌ {member.mention} لا يملك بيانات XP!")

    @commands.command(name="xpleaderboard", aliases=["لوحة_xp"])
    async def xpleaderboard_cmd(self, ctx):
        """لوحة XP المفصلة"""
        xp_data = self._load_xp_data()
        guild_data = xp_data.get(ctx.guild.id, {})
        sorted_users = sorted(guild_data.items(), key=lambda x: x[1].get("xp", 0), reverse=True)[:15]
        if not sorted_users:
            await ctx.send("❌ لا يوجد بيانات بعد!")
            return
        embed = discord.Embed(title="📊 لوحة XP المفصلة", color=0x5865F2)
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(sorted_users):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"غير معروف ({user_id})"
            xp = data.get("xp", 0)
            level = data.get("level", 1)
            prefix = medals[i] if i < 3 else f"**#{i+1}**"
            embed.add_field(name=f"{prefix} {name}", value=f"المستوى **{level}** | **{xp:,}** XP", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Levels(bot))
