from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_session
from db.models import GuildSetting, GuildCity, City


class SettingsService:
    async def get(self, guild_id: int, session: Optional[AsyncSession] = None) -> Optional[GuildSetting]:
        close = False
        if session is None:
            session = await get_session()
            close = True
        try:
            result = await session.execute(
                select(GuildSetting).where(GuildSetting.guild_id == guild_id)
            )
            return result.scalar_one_or_none()
        finally:
            if close:
                await session.close()

    async def set_channel(self, guild_id: int, channel_id: int):
        session = await get_session()
        try:
            gs = await self.get(guild_id, session)
            if gs:
                gs.channel_id = channel_id
                gs.updated_at = datetime.now(timezone.utc)
            else:
                gs = GuildSetting(guild_id=guild_id, channel_id=channel_id)
                session.add(gs)
            await session.commit()
        finally:
            await session.close()

    async def set_city(self, guild_id: int, city_id: int):
        session = await get_session()
        try:
            gs = await self.get(guild_id, session)
            if gs:
                gs.default_city_id = city_id
                gs.updated_at = datetime.now(timezone.utc)
            else:
                gs = GuildSetting(guild_id=guild_id, default_city_id=city_id)
                session.add(gs)
            await session.commit()
        finally:
            await session.close()

    async def set_enabled(self, guild_id: int, enabled: bool):
        session = await get_session()
        try:
            gs = await self.get(guild_id, session)
            if gs:
                gs.enabled = enabled
                gs.updated_at = datetime.now(timezone.utc)
            else:
                gs = GuildSetting(guild_id=guild_id, enabled=enabled)
                session.add(gs)
            await session.commit()
        finally:
            await session.close()

    async def add_city(self, guild_id: int, city_id: int):
        session = await get_session()
        try:
            existing = await session.execute(
                select(GuildCity).where(
                    GuildCity.guild_id == guild_id,
                    GuildCity.city_id == city_id,
                )
            )
            if not existing.scalar_one_or_none():
                session.add(GuildCity(guild_id=guild_id, city_id=city_id))
                await session.commit()
        finally:
            await session.close()

    async def remove_city(self, guild_id: int, city_id: int):
        session = await get_session()
        try:
            await session.execute(
                delete(GuildCity).where(
                    GuildCity.guild_id == guild_id,
                    GuildCity.city_id == city_id,
                )
            )
            await session.commit()
        finally:
            await session.close()

    async def search_cities(self, query: str, limit: int = 25) -> list[City]:
        session = await get_session()
        try:
            result = await session.execute(
                select(City)
                .where(City.name_ar.ilike(f"%{query}%"))
                .limit(limit)
            )
            return list(result.scalars().all())
        finally:
            await session.close()

    async def get_city_by_id(self, city_id: int) -> Optional[City]:
        session = await get_session()
        try:
            result = await session.execute(select(City).where(City.id == city_id))
            return result.scalar_one_or_none()
        finally:
            await session.close()

    async def list_regions(self) -> list:
        from sqlalchemy import text
        session = await get_session()
        try:
            result = await session.execute(text("SELECT id, name_ar, name_en FROM regions ORDER BY name_ar"))
            return [{"id": r[0], "name_ar": r[1], "name_en": r[2]} for r in result.fetchall()]
        finally:
            await session.close()

    async def list_cities_by_region(self, region_id: int) -> list[City]:
        session = await get_session()
        try:
            result = await session.execute(
                select(City).where(City.region_id == region_id).order_by(City.name_ar)
            )
            return list(result.scalars().all())
        finally:
            await session.close()


settings_service = SettingsService()
