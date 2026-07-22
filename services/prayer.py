import asyncio
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from adhanpy import PrayerTimes
from adhanpy.calculation import CalculationMethod

from db.connection import get_session
from db.models import City, PrayerCache


CALC_METHOD = CalculationMethod.UMM_AL_QURA
TZ_RIYADH = ZoneInfo("Asia/Riyadh")
PRAYER_KEYS = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
PRAYER_KEYS_DISPLAY = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]


class PrayerEngine:
    async def get_today_times(self, city_id: int, session: Optional[AsyncSession] = None) -> Optional[dict]:
        today = date.today().isoformat()
        close_session = False
        if session is None:
            session = await get_session()
            close_session = True

        try:
            result = await session.execute(
                select(PrayerCache).where(
                    and_(PrayerCache.city_id == city_id, PrayerCache.date == today)
                )
            )
            cached = result.scalar_one_or_none()
            if cached:
                return {
                    "fajr": cached.fajr,
                    "sunrise": cached.sunrise,
                    "dhuhr": cached.dhuhr,
                    "asr": cached.asr,
                    "maghrib": cached.maghrib,
                    "isha": cached.isha,
                    "timings": cached.timings,
                    "date": cached.date,
                }

            city_result = await session.execute(select(City).where(City.id == city_id))
            city = city_result.scalar_one_or_none()
            if not city:
                return None

            times = self._calculate(city.latitude, city.longitude)
            await self._store(session, city_id, today, times)
            return times
        finally:
            if close_session:
                await session.close()

    async def get_month_times(self, city_id: int, year: int, month: int) -> list[dict]:
        session = await get_session()
        try:
            start = f"{year}-{month:02d}-01"
            result = await session.execute(
                select(PrayerCache).where(
                    and_(PrayerCache.city_id == city_id, PrayerCache.date >= start)
                ).order_by(PrayerCache.date)
            )
            rows = result.scalars().all()
            return [
                {
                    "date": r.date,
                    "fajr": r.fajr,
                    "sunrise": r.sunrise,
                    "dhuhr": r.dhuhr,
                    "asr": r.asr,
                    "maghrib": r.maghrib,
                    "isha": r.isha,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def precalc_all_cities(self):
        session = await get_session()
        today = date.today().isoformat()
        try:
            result = await session.execute(select(City))
            cities = result.scalars().all()
            count = 0
            for city in cities:
                times = self._calculate(city.latitude, city.longitude)
                await self._store(session, city.id, today, times)
                count += 1
                if count % 50 == 0:
                    await session.commit()
                    print(f"[PRECALC] {count}/{len(cities)} cities done")
            await session.commit()
            print(f"[PRECALC] ✅ All {count} cities pre-calculated")
        finally:
            await session.close()

    def _calculate(self, lat: float, lng: float) -> dict:
        pt = PrayerTimes(
            coordinates=(lat, lng),
            date=datetime.now(TZ_RIYADH),
            calculation_method=CALC_METHOD,
            time_zone=TZ_RIYADH,
        )

        return {
            "fajr": pt.fajr.strftime("%H:%M"),
            "sunrise": pt.sunrise.strftime("%H:%M"),
            "dhuhr": pt.dhuhr.strftime("%H:%M"),
            "asr": pt.asr.strftime("%H:%M"),
            "maghrib": pt.maghrib.strftime("%H:%M"),
            "isha": pt.isha.strftime("%H:%M"),
        }

    async def _store(self, session: AsyncSession, city_id: int, today: str, times: dict):
        existing = await session.execute(
            select(PrayerCache).where(
                and_(PrayerCache.city_id == city_id, PrayerCache.date == today)
            )
        )
        if existing.scalar_one_or_none():
            return
        pc = PrayerCache(
            city_id=city_id,
            date=today,
            fajr=times["fajr"],
            sunrise=times["sunrise"],
            dhuhr=times["dhuhr"],
            asr=times["asr"],
            maghrib=times["maghrib"],
            isha=times["isha"],
            timings=times,
        )
        session.add(pc)


prayer_engine = PrayerEngine()
