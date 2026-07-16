import discord
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp
from datetime import datetime, timezone, timedelta

DATA_FILE = "bot_data.json"
PRAYER_API = "https://api.aladhan.com/v1/timingsByCity"
PRAYER_METHOD = 4
DATABASE_URL = os.getenv("DATABASE_URL")


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = self._load_content()
        self.session = None
        self.pool = None
        self.use_db = False

    def _load_content(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    # ── Storage ──

    async def _init_storage(self):
        if DATABASE_URL:
            try:
                import asyncpg
                self.pool = await asyncpg.create_pool(DATABASE_URL)
                async with self.pool.acquire() as conn:
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS server_settings (
                            guild_id BIGINT PRIMARY KEY,
                            city VARCHAR(100) DEFAULT 'Makkah',
                            country VARCHAR(10) DEFAULT 'SA',
                            city_name VARCHAR(100) DEFAULT 'مكة المكرمة',
                            channel_id BIGINT,
                            active BOOLEAN DEFAULT FALSE
                        )
                    ''')
                self.use_db = True
                print("[EGR] PostgreSQL connected", flush=True)
            except Exception as e:
                print(f"[EGR] PostgreSQL failed, using JSON: {e}", flush=True)

    async def _get_config(self, guild_id):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow('SELECT * FROM server_settings WHERE guild_id = $1', guild_id)
                    if row:
                        return dict(row)
                    await conn.execute('INSERT INTO server_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING', guild_id)
            except:
                pass
        data = load_data()
        return data.get("egr", {}).get(str(guild_id), {})

    async def _save_config(self, guild_id, config):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO server_settings (guild_id, city, country, city_name, channel_id, active)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (guild_id) DO UPDATE SET
                            city = $2, country = $3, city_name = $4, channel_id = $5, active = $6
                    ''', guild_id, config.get("city", "Makkah"), config.get("country", "SA"),
                       config.get("city_name", "مكة المكرمة"),
                       config.get("channel_id"), config.get("active", False))
                return
            except:
                pass
        data = load_data()
        if "egr" not in data:
            data["egr"] = {}
        data["egr"][str(guild_id)] = config
        save_data(data)

    async def _get_active_configs(self):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch('SELECT guild_id, channel_id FROM server_settings WHERE active = TRUE')
                    return [dict(r) for r in rows]
            except:
                pass
        data = load_data()
        return [{"guild_id": int(k), "channel_id": v.get("channel_id")}
                for k, v in data.get("egr", {}).items() if v.get("active") and v.get("channel_id")]

    # ── API ──

    async def _fetch_prayer_times(self, city, country):
        url = f"{PRAYER_API}?city={city}&country={country}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("timings", {})
        except:
            return None

    def _get_random_item(self, category, field=None):
        items = self.content.get(category, [])
        if not items:
            return None
        item = random.choice(items)
        if isinstance(item, dict) and field:
            return item.get(field, str(item))
        return item

    # ── Hourly Sender (أدعية وأذكار فقط) ──

    @tasks.loop(hours=1)
    async def hourly_sender(self):
        await self.bot.wait_until_ready()
        active = await self._get_active_configs()
        for cfg in active:
            channel = self.bot.get_channel(int(cfg["channel_id"]))
            if not channel:
                continue

            pool = []
            for item in self.content.get("adhkar_morning", []):
                pool.append(("🌅 أذكار", item))
            for item in self.content.get("adhkar_evening", []):
                pool.append(("🌆 أذكار المساء", item))
            for item in self.content.get("duas", []):
                pool.append(("🤲 دعاء", item))
            if not pool:
                continue

            label, text = random.choice(pool)
            text = str(text)[:1024]

            embed = discord.Embed(title=label, description=text, color=0x107c41, timestamp=datetime.now(timezone.utc))
            embed.set_footer(text="🕌 تذكير تلقائي | كل ساعة")
            try:
                await channel.send(embed=embed)
            except:
                pass

    # ── The ONE Command ──

    @commands.command(name="اجر")
    async def ajr_unified(self, ctx):
        config = await self._get_config(ctx.guild.id)
        city = config.get("city", "Makkah")
        country = config.get("country", "SA")
        city_name = config.get("city_name", "مكة المكرمة")
        city_display = f"{city_name} ({city})"

        await ctx.typing()

        timings = await self._fetch_prayer_times(city, country)

        ayah_item = self._get_random_item("ayat")
        hadith = self._get_random_item("ahadith")
        dhikr = self._get_random_item("adhkar_morning")

        now = datetime.now(timezone.utc) + timedelta(hours=3)
        date_str = now.strftime("%Y-%m-%d")

        embed = discord.Embed(
            title="🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ الُموَحَّدَةُ",
            description="جميع الأذكار والمواقيت والنفحات الإيمانية في شاشة واحدة.",
            color=0x107c41
        )

        if timings:
            prayers_text = (
                f"**المدينة:** {city_display}\n"
                f"• 🌆 الفجر: `{timings.get('Fajr', '---')}` | ☀️ الظهر: `{timings.get('Dhuhr', '---')}`\n"
                f"• ⛅ العصر: `{timings.get('Asr', '---')}` | 🌅 المغرب: `{timings.get('Maghrib', '---')}`\n"
                f"• 🌌 العشاء: `{timings.get('Isha', '---')}`"
            )
        else:
            prayers_text = f"**المدينة:** {city_display}\n⚠️ تعذر جلب أوقات الصلاة"
        embed.add_field(name="🕒 مواقيت الصلاة اليوم:", value=prayers_text, inline=False)

        if ayah_item:
            embed.add_field(name="📖 آية وتدبر اليوم:",
                            value=f"*{ayah_item['text']}*\n**التفسير:** {ayah_item.get('tafsir', '')}"[:1024],
                            inline=False)

        if hadith:
            embed.add_field(name="📚 من مشكاة النبوة (حديث شريف):", value=hadith[:1024], inline=False)

        if dhikr:
            embed.add_field(name="📿 ذكر وتذكير الساعة:", value=dhikr[:1024], inline=False)

        active_status = "🟢 مفعل" if config.get("active") else "🔴 غير مفعل"
        embed.add_field(
            name="⚙️ الإعدادات",
            value=f"الإرسال التلقائي: {active_status}\n"
                  f"`!المدينة [الاسم]` - تغيير المدينة\n"
                  f"`!تلقائي تشغيل` - تفعيل التذكير الدوري\n"
                  f"`!تلقائي إيقاف` - إيقاف التذكير الدوري",
            inline=False
        )
        embed.set_footer(text=f"التاريخ: {date_str} | التخزين: {'PostgreSQL' if self.use_db else 'JSON'}")
        await ctx.send(embed=embed)

    # ── Settings ──

    @commands.command(name="المدينة")
    async def set_city(self, ctx, *, city_name=None):
        if not city_name:
            await ctx.send("❌ اكتب اسم المدينة: `!المدينة مكة` أو `!المدينة القاهرة` أو `!المدينة London`")
            return
        config = await self._get_config(ctx.guild.id)
        config["city"] = city_name
        config["country"] = "SA"
        config["city_name"] = city_name
        await self._save_config(ctx.guild.id, config)
        await ctx.send(f"✅ تم تعيين المدينة: **{city_name}** 🕌")

    @commands.command(name="تلقائي")
    async def auto_toggle(self, ctx, *, mode=None):
        if mode not in ["تشغيل", "إيقاف"]:
            await ctx.send("❌ استخدم: `!تلقائي تشغيل` أو `!تلقائي إيقاف`")
            return
        config = await self._get_config(ctx.guild.id)
        if mode == "تشغيل":
            config["active"] = True
            config["channel_id"] = ctx.channel.id
            if "city" not in config:
                config["city"] = "Makkah"
                config["country"] = "SA"
                config["city_name"] = "مكة المكرمة"
            await self._save_config(ctx.guild.id, config)
            await ctx.send(f"✅ تم تفعيل الإرسال التلقائي في {ctx.channel.mention}")
        else:
            config["active"] = False
            await self._save_config(ctx.guild.id, config)
            await ctx.send("🔴 تم إيقاف الإرسال التلقائي")

    def cog_unload(self):
        self.hourly_sender.cancel()

    async def cog_load(self):
        await self._init_storage()
        self.hourly_sender.start()


async def setup(bot):
    await bot.add_cog(Egr(bot))
