import discord
from discord.ext import commands
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty, TICKET_CATEGORY_ID, TICKET_ROLE_ID, TICKET_MANAGER_ROLE_ID, TICKET_LOG_CHANNEL_ID
from log_service import LogEmbed, LogColors, send_log


class Tickets(commands.Cog):
    """🎫 نظام التذاكر"""

    def __init__(self, bot):
        self.bot = bot
        self.ticket_counter = 1

    def _load_ticket_data(self):
        data = load_data()
        return {
            "counter": data.get("ticket_counter", 1),
            "log_channels": {int(k): v for k, v in data.get("ticket_log_channels", {}).items()},
            "role_access": data.get("ticket_role_access", {}),
        }

    def _save_ticket_data(self, ticket_data):
        data = load_data()
        data["ticket_counter"] = ticket_data.get("counter", 1)
        data["ticket_log_channels"] = {str(k): v for k, v in ticket_data.get("log_channels", {}).items()}
        data["ticket_role_access"] = ticket_data.get("role_access", {})
        mark_data_dirty()
        save_data()

    @commands.command(name="ticket", aliases=["تذكرة"])
    async def ticket_cmd(self, ctx):
        """فتح تذكرة جديدة"""
        category_id = TICKET_CATEGORY_ID
        if not category_id:
            await ctx.send("❌ نظام التذاكر غير مُعد!")
            return
        category = self.bot.get_channel(category_id)
        if not category:
            await ctx.send("❌ كاتيقوري التذاكر غير موجود!")
            return
        ticket_data = self._load_ticket_data()
        ticket_num = ticket_data.get("counter", 1)
        ticket_data["counter"] = ticket_num + 1
        self._save_ticket_data(ticket_data)
        channel_name = f"ticket-{ticket_num}"
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if TICKET_MANAGER_ROLE_ID:
            role = ctx.guild.get_role(TICKET_MANAGER_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if TICKET_ROLE_ID:
            role = ctx.guild.get_role(TICKET_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        try:
            channel = await ctx.guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
            embed = discord.Embed(title=f"🎫 تذكرة #{ticket_num}", description=f"مرحباً {ctx.author.mention}\nاشرح مشكلتك وسنساعدك!", color=0x00BFFF)
            embed.set_footer(text="انقر على 🔒 لإغلاق التذكرة")
            view = TicketView()
            await channel.send(embed=embed, view=view)
            await ctx.send(f"✅ تم فتح التذكرة: {channel.mention}", delete_after=10)
            log_embed = LogEmbed.base("🎫 تذكرة جديدة", LogColors.TICKET, guild=ctx.guild)
            LogEmbed.user_field(log_embed, ctx.author, "المستخدم", thumb=True)
            log_embed.add_field(name="رقم التذكرة", value=f"#{ticket_num}", inline=True)
            log_embed.add_field(name="القناة", value=channel.mention, inline=True)
            await send_log(ctx.guild.id, "ticket_open", log_embed)
        except discord.Forbidden:
            await ctx.send("❌ لا أملك صلاحية إنشاء القنوات!")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="close", aliases=["إغلاق"])
    async def close_cmd(self, ctx):
        """إغلاق التذكرة"""
        if not ctx.channel.name.startswith("ticket-"):
            await ctx.send("❌ هذا ليس روم تذاكر!")
            return
        embed = discord.Embed(title="🔒 جاري إغلاق التذكرة...", color=0xE74C3C)
        embed.add_field(name="بواسطة", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        log_embed = LogEmbed.base("🔒 إغلاق تذكرة", LogColors.TICKET, guild=ctx.guild)
        LogEmbed.user_field(log_embed, ctx.author, "أغلقها", thumb=True)
        log_embed.add_field(name="القناة", value=ctx.channel.mention, inline=True)
        await send_log(ctx.guild.id, "ticket_close", log_embed)
        import asyncio
        await asyncio.sleep(3)
        try:
            await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")
        except:
            pass

    @commands.command(name="adduser", aliases=["إضافة_عضو"])
    async def adduser_cmd(self, ctx, member: discord.Member = None):
        """إضافة عضو للتذكرة"""
        if not member:
            await ctx.send("❌ حدد العضو: `!adduser @user`")
            return
        if not ctx.channel.name.startswith("ticket-"):
            await ctx.send("❌ هذا ليس روم تذاكر!")
            return
        try:
            await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
            embed = discord.Embed(title="✅ تم الإضافة", color=0x2ECC71)
            embed.add_field(name="العضو", value=member.mention, inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="removeuser", aliases=["إزالة_عضو"])
    async def removeuser_cmd(self, ctx, member: discord.Member = None):
        """إزالة عضو من التذكرة"""
        if not member:
            await ctx.send("❌ حدد العضو: `!removeuser @user`")
            return
        if not ctx.channel.name.startswith("ticket-"):
            await ctx.send("❌ هذا ليس روم تذاكر!")
            return
        try:
            await ctx.channel.set_permissions(member, read_messages=False, send_messages=False)
            embed = discord.Embed(title="✅ تم الإزالة", color=0xE74C3C)
            embed.add_field(name="العضو", value=member.mention, inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @commands.command(name="ticket_log", aliases=["روم_التذاكر"])
    @commands.has_permissions(administrator=True)
    async def ticket_log_cmd(self, ctx, channel: discord.TextChannel = None):
        """تعيين روم لوق التذاكر"""
        channel = channel or ctx.channel
        ticket_data = self._load_ticket_data()
        ticket_data["log_channels"][ctx.guild.id] = channel.id
        self._save_ticket_data(ticket_data)
        await ctx.send(f"✅ تم تعيين روم لوق التذاكر: {channel.mention}")


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction, button):
        embed = discord.Embed(title="🔒 جاري إغلاق التذكرة...", color=0xE74C3C)
        embed.add_field(name="بواسطة", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)
        import asyncio
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except:
            pass

    @discord.ui.button(label="📝 معلومات", style=discord.ButtonStyle.blurple, custom_id="ticket_info")
    async def ticket_info(self, interaction, button):
        embed = discord.Embed(title="📝 معلومات التذكرة", color=0x5865F2)
        embed.add_field(name="القناة", value=interaction.channel.mention, inline=True)
        embed.add_field(name="تاريخ الإنشاء", value=f"<t:{int(interaction.channel.created_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TicketActions(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
