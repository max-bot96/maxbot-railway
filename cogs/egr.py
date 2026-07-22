import asyncio

import discord
from discord.ext import commands
from discord.ui import View, Select

from services.prayer import prayer_engine
from services.settings import settings_service
from services.scheduler import Scheduler

ALLOWED_CHANNEL_NAME = "بوابة-الأجر"

PRAYER_NAMES_AR = ["الفجر", "الظهر", "العصر", "المغرب", "العشاء"]


class RegionSelect(View):
    def __init__(self, user_id, callback_fn, timeout=120):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.callback_fn = callback_fn
        self.message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⏰ انتهى الوقت. أعد تشغيل الأمر.", view=self)
            except:
                pass

    @classmethod
    async def create(cls, user_id, callback_fn):
        regions = await settings_service.list_regions()
        view = cls(user_id, callback_fn)
        options = [discord.SelectOption(label=r["name_ar"], value=str(r["id"]), description=r["name_en"][:100]) for r in regions]

        select = Select(placeholder="اختر المنطقة", options=options)

        async def select_callback(interaction):
            if interaction.user.id != view.user_id:
                return await interaction.response.send_message("❌ هذا ليس أمرك.", ephemeral=True)
            await view.callback_fn(interaction, int(select.values[0]))

        select.callback = select_callback
        view.add_item(select)
        return view


class CitySelect(View):
    def __init__(self, user_id, region_id, callback_fn, timeout=120):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.callback_fn = callback_fn
        self.message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⏰ انتهى الوقت. أعد تشغيل الأمر.", view=self)
            except:
                pass

    @classmethod
    async def create(cls, user_id, region_id, callback_fn):
        cities = await settings_service.list_cities_by_region(region_id)
        view = cls(user_id, region_id, callback_fn)
        options = [discord.SelectOption(label=c.name_ar, value=str(c.id), description=c.name_en[:100]) for c in cities]

        select = Select(placeholder="اختر المدينة", options=options)

        async def select_callback(interaction):
            if interaction.user.id != view.user_id:
                return await interaction.response.send_message("❌ هذا ليس أمرك.", ephemeral=True)
            await view.callback_fn(interaction, int(select.values[0]))

        select.callback = select_callback
        view.add_item(select)
        return view


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = Scheduler(bot)
        self._channel_lock = {}

    def cog_unload(self):
        self.scheduler.stop()

    async def cog_load(self):
        self.scheduler.start()
        print("[EGR] ✅ New Islamic cog loaded (DB mode)")

    async def _require_channel(self, ctx):
        gs = await settings_service.get(ctx.guild.id)
        stored = gs.channel_id if gs else None
        allowed = stored or self._channel_lock.get(ctx.guild.id)
        if allowed:
            if ctx.channel.id != allowed:
                try:
                    await ctx.message.delete()
                except:
                    pass
                ch = ctx.guild.get_channel(allowed)
                name = ch.mention if ch else "#تم-حذف-الروم"
                await ctx.send(f"⚠️ هذا الأمر يعمل فقط في {name}", delete_after=10)
                return False
        elif ctx.channel.name != ALLOWED_CHANNEL_NAME:
            try:
                await ctx.message.delete()
            except:
                pass
            await ctx.send(f"⚠️ هذا الأمر يعمل فقط في #{ALLOWED_CHANNEL_NAME}", delete_after=10)
            return False
        return True

    async def _send_menu(self, ctx, city, timings):
        embed = discord.Embed(
            title="🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ",
            description=f"📍 {city.name_ar} ({city.name_en})" if city else "📍 لم يتم تحديد مدينة بعد",
            color=0x107c41,
        )

        if timings:
            lines = []
            for i, key in enumerate(["fajr", "dhuhr", "asr", "maghrib", "isha"]):
                lines.append(f"**{PRAYER_NAMES_AR[i]}**: `{timings[key]}`")
            embed.add_field(name="🕒 مواقيت الصلاة", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🕒 مواقيت الصلاة", value="⚠️ تعذر جلب المواقيت", inline=False)

        gs = await settings_service.get(ctx.guild.id)
        status = "✅ مفعل" if (gs and gs.enabled) else "❌ غير مفعل"
        channel_info = ""
        if gs and gs.channel_id:
            ch = ctx.guild.get_channel(gs.channel_id)
            if ch:
                channel_info = f"📢 قناة التنبيهات: {ch.mention}"

        cmds = (
            "━━━━━━━━━━━━━━━━━\n"
            "**الأوامر المتاحة:**\n"
            "• `!أجر #قناة` — تعيين قناة التنبيهات (أدمن)\n"
            "• `!أجر مدينة` — تغيير المدينة الافتراضية (أدمن)\n"
            "• `!أجر شغل` — تشغيل التنبيهات التلقائية (أدمن)\n"
            "• `!أجر إيقاف` — إيقاف التنبيهات (أدمن)"
        )
        embed.add_field(name="📋 القائمة", value=cmds, inline=False)

        footer = f"الحالة: {status}"
        if channel_info:
            footer += f" | {channel_info}"
        embed.set_footer(text=footer)

        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            await asyncio.sleep(2)
            await ctx.send("⚠️ عذراً، سيرفرات ديسكورد تواجه عطلاً مؤقتاً.", delete_after=10)

    # ── !أجر (main: public menu + admin channel set via mention) ──

    @commands.group(name="اجر", invoke_without_command=True, case_insensitive=True)
    async def ajr(self, ctx):
        if not await self._require_channel(ctx):
            return

        channel_mentions = ctx.message.channel_mentions
        if channel_mentions:
            if not ctx.author.guild_permissions.manage_guild:
                embed = discord.Embed(
                    title="❌ صلاحية مفقودة",
                    description="تحتاج صلاحية **Manage Server** لتعيين القناة.",
                    color=0xe74c3c,
                )
                return await ctx.send(embed=embed, delete_after=10)
            target = channel_mentions[0]
            await settings_service.set_channel(ctx.guild.id, target.id)
            self._channel_lock[ctx.guild.id] = target.id
            embed = discord.Embed(
                title="✅ تم تعيين قناة التنبيهات",
                description=f"تم تحديد {target.mention} كقناة للتنبيهات",
                color=0x2ecc71,
            )
            return await ctx.send(embed=embed)

        gs = await settings_service.get(ctx.guild.id)
        city = None
        timings = None
        if gs and gs.default_city_id:
            city = await settings_service.get_city_by_id(gs.default_city_id)
            if city:
                timings = await prayer_engine.get_today_times(city.id)

        await self._send_menu(ctx, city, timings)

    # ── !أجر مدينة ──

    @ajr.command(name="مدينة")
    @commands.has_permissions(manage_guild=True)
    async def ajr_city(self, ctx):
        if not await self._require_channel(ctx):
            return
        view = await RegionSelect.create(ctx.author.id, self._handle_region_selected)
        resp = await ctx.send("🌍 **اختر المنطقة:**", view=view)
        view.message = resp

    async def _handle_region_selected(self, interaction, region_id):
        view = await CitySelect.create(interaction.user.id, region_id, self._handle_city_selected)
        await interaction.response.edit_message(content="🏙️ **اختر المدينة:**", view=view)
        view.message = await interaction.original_response()

    async def _handle_city_selected(self, interaction, city_id):
        city = await settings_service.get_city_by_id(city_id)
        if not city:
            return await interaction.response.send_message("❌ المدينة غير موجودة.", ephemeral=True)
        await settings_service.set_city(interaction.guild_id, city_id)
        embed = discord.Embed(
            title="✅ تم حفظ المدينة",
            description=f"تم تعيين **{city.name_ar}** كالمدينة الافتراضية للسيرفر.",
            color=0x2ecc71,
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    # ── !أجر شغل ──

    @ajr.command(name="شغل")
    @commands.has_permissions(manage_guild=True)
    async def ajr_enable(self, ctx):
        if not await self._require_channel(ctx):
            return

        gs = await settings_service.get(ctx.guild.id)
        if not gs or not gs.default_city_id:
            embed = discord.Embed(
                title="⚠️ لم يتم تحديد المدينة",
                description="لم يتم تحديد المدينة الافتراضية لهذا السيرفر.\nالرجاء اختيار المدينة من القائمة.",
                color=0xf39c12,
            )
            await ctx.send(embed=embed)
            view = await RegionSelect.create(ctx.author.id, lambda i, rid: self._handle_region_for_enable(i, rid, ctx))
            resp = await ctx.send("🌍 **اختر المنطقة:**", view=view)
            view.message = resp
            return

        await settings_service.set_channel(ctx.guild.id, ctx.channel.id)
        self._channel_lock[ctx.guild.id] = ctx.channel.id
        await settings_service.set_enabled(ctx.guild.id, True)

        city = await settings_service.get_city_by_id(gs.default_city_id)
        city_name = city.name_ar if city else "غير معروفة"

        embed = discord.Embed(
            title="✅ تم تفعيل التنبيهات",
            description=(
                "تم **تفعيل** التنبيهات التلقائية بنجاح!\n\n"
                "📢 سيتم إرسال:\n"
                "• 🔔 تنبيه عند كل صلاة (أذان)\n\n"
                f"📍 المدينة: **{city_name}**\n"
                f"📢 القناة: {ctx.channel.mention}"
            ),
            color=0x2ecc71,
        )
        await ctx.send(embed=embed)

    async def _handle_region_for_enable(self, interaction, region_id, ctx):
        view = await CitySelect.create(ctx.author.id, region_id, lambda i, cid: self._handle_city_for_enable(i, cid, ctx))
        await interaction.response.edit_message(content="🏙️ **اختر المدينة:**", view=view)
        view.message = await interaction.original_response()

    async def _handle_city_for_enable(self, interaction, city_id, ctx):
        city = await settings_service.get_city_by_id(city_id)
        if not city:
            return await interaction.response.send_message("❌ المدينة غير موجودة.", ephemeral=True)
        await settings_service.set_city(ctx.guild.id, city_id)
        await settings_service.set_channel(ctx.guild.id, ctx.channel.id)
        self._channel_lock[ctx.guild.id] = ctx.channel.id
        await settings_service.set_enabled(ctx.guild.id, True)

        embed = discord.Embed(
            title="✅ تم تفعيل التنبيهات",
            description=(
                f"تم تعيين **{city.name_ar}** كالمدينة الافتراضية.\n"
                "تم **تفعيل** التنبيهات التلقائية بنجاح!"
            ),
            color=0x2ecc71,
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    # ── !أجر إيقاف ──

    @ajr.command(name="إيقاف")
    @commands.has_permissions(manage_guild=True)
    async def ajr_disable(self, ctx):
        if not await self._require_channel(ctx):
            return
        await settings_service.set_enabled(ctx.guild.id, False)
        embed = discord.Embed(
            title="⏹️ تم إيقاف التنبيهات",
            description="تم **إيقاف** التنبيهات التلقائية في هذا السيرفر.",
            color=0xe74c3c,
        )
        await ctx.send(embed=embed)

    # ── error handler ──

    @ajr.error
    @ajr_city.error
    @ajr_enable.error
    @ajr_disable.error
    async def ajr_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                title="❌ صلاحية مفقودة",
                description="تحتاج صلاحية **Manage Server** لاستخدام هذا الأمر.",
                color=0xe74c3c,
            )
            return await ctx.send(embed=embed, delete_after=10)

        if isinstance(error, commands.CommandNotFound):
            return

        try:
            if isinstance(error, discord.DiscordServerError):
                embed = discord.Embed(
                    title="⚠️ عطل مؤقت",
                    description="سيرفرات ديسكورد تواجه مشكلة مؤقتة. حاول مرة أخرى.",
                    color=0xf39c12,
                )
                await ctx.send(embed=embed, delete_after=10)
                return
        except:
            pass

        embed = discord.Embed(title="⚠️ حدث خطأ", description="حدث خطأ غير متوقع. حاول مرة أخرى.", color=0xe74c3c)
        await ctx.send(embed=embed, delete_after=10)


async def setup(bot):
    await bot.add_cog(Egr(bot))
