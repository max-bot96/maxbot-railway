import asyncio
from datetime import datetime, timezone
from typing import Optional

import pytz
from discord import AllowedMentions, Embed
from discord.ext import tasks

from sqlalchemy import text

from db.connection import get_session
from db.models import GuildSetting, City
from services.prayer import prayer_engine, PRAYER_KEYS

PRAYER_NAMES_AR = ["الفجر", "الظهر", "العصر", "المغرب", "العشاء"]
PRAYER_NAMES_EN = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

ADHAN_DUA = 'ترديد الأذان مع المؤذن، ثم الصلاة على النبي ﷺ والدعاء: "اللهم رب هذه الدعوة التامة، والصلاة القائمة، آتِ محمداً الوسيلة والفضيلة، وابعثه مقاماً محموداً الذي وعدته"'
SAJDAH_HADITH = '«أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ، فَأَكْثِرُوا الدُّعَاءَ»'

ALERTS_SENT = {}


class Scheduler:
    def __init__(self, bot):
        self.bot = bot
        self._precalc_done = False

    def start(self):
        self.daily_precalc.start()
        self.alert_scanner.start()

    def stop(self):
        self.daily_precalc.cancel()
        self.alert_scanner.cancel()

    @tasks.loop(time=datetime.strptime("00:05", "%H:%M").time())
    async def daily_precalc(self):
        await self.bot.wait_until_ready()
        print("[SCHEDULER] ⏰ Daily precalc started")
        await prayer_engine.precalc_all_cities()

    @daily_precalc.before_loop
    async def before_daily_precalc(self):
        if not self._precalc_done:
            await self.bot.wait_until_ready()
            print("[SCHEDULER] 🚀 Startup precalc")
            await prayer_engine.precalc_all_cities()
            self._precalc_done = True

    @tasks.loop(seconds=45)
    async def alert_scanner(self):
        await self.bot.wait_until_ready()
        tz_ryadh = pytz.timezone("Asia/Riyadh")
        now_ryadh = datetime.now(tz_ryadh)
        current_time = now_ryadh.strftime("%H:%M")
        today_str = now_ryadh.strftime("%Y-%m-%d")

        session = await get_session()
        try:
            result = await session.execute(text("""
                SELECT gs.guild_id, gs.channel_id, gs.default_city_id,
                       c.name_ar, c.name_en
                FROM guild_settings gs
                JOIN cities c ON c.id = gs.default_city_id
                WHERE gs.enabled = TRUE AND gs.channel_id IS NOT NULL
                  AND gs.default_city_id IS NOT NULL
            """))
            guilds = result.fetchall()
        finally:
            await session.close()

        for row in guilds:
            guild_id, channel_id, city_id, city_ar, city_en = row

            session = await get_session()
            try:
                cache = await session.execute(text("""
                    SELECT fajr, sunrise, dhuhr, asr, maghrib, isha
                    FROM prayer_cache
                    WHERE city_id = :cid AND date = :d
                """), {"cid": city_id, "d": today_str})
                timings = cache.fetchone()
            finally:
                await session.close()

            if not timings:
                continue

            timing_map = {
                "fajr": timings[0],
                "sunrise": timings[1],
                "dhuhr": timings[2],
                "asr": timings[3],
                "maghrib": timings[4],
                "isha": timings[5],
            }

            for idx, key in enumerate(PRAYER_KEYS):
                prayer_time = timing_map.get(key)
                if not prayer_time or prayer_time != current_time:
                    continue

                dedup_key = f"{city_id}_{key}_{today_str}"
                if ALERTS_SENT.get(dedup_key):
                    continue
                ALERTS_SENT[dedup_key] = True
                if len(ALERTS_SENT) > 10000:
                    ALERTS_SENT.clear()

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue

                prayer_label = PRAYER_NAMES_AR[idx]
                alert_text = f"📢 @everyone | حان الآن موعد أذان صلاة **{prayer_label}** في **{city_ar}** 🕋"

                embed = Embed(
                    title=f"🕌 {prayer_label} - {city_ar}",
                    description=f"{now_ryadh.strftime('%Y-%m-%d %H:%M')} Asia/Riyadh",
                    color=0x107c41,
                )
                embed.add_field(name="📖 الذكر عند الأذان", value=ADHAN_DUA, inline=False)
                embed.add_field(name="💡 أثر صلاتك", value=f"*{SAJDAH_HADITH}*", inline=False)
                embed.set_footer(text=f"🕌 {city_ar}")

                try:
                    await channel.send(
                        content=alert_text,
                        embed=embed,
                        allowed_mentions=AllowedMentions(everyone=True),
                    )
                    print(f"[ALERT] ✅ {prayer_label} sent to guild {guild_id}")
                except Exception as e:
                    print(f"[ALERT] ❌ Failed guild {guild_id}: {e}")

                await asyncio.sleep(0.3)
