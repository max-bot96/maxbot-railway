import os
from datetime import datetime, timezone
from sqlalchemy import (Column, Integer, BigInteger, String, Float, Boolean,
                        ForeignKey, Index, Text, JSON, TIMESTAMP)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_ar = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    iso_code = Column(String(2), nullable=False, unique=True)
    timezone_default = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    regions = relationship("Region", back_populates="country")


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=False)
    name_ar = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    country = relationship("Country", back_populates="regions")
    cities = relationship("City", back_populates="region")


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)
    official_code = Column(String(20), nullable=True)
    name_ar = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    timezone = Column(String(50), nullable=False, default="Asia/Riyadh")
    created_at = Column(TIMESTAMP(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    region = relationship("Region", back_populates="cities")
    guild_settings = relationship("GuildSetting", back_populates="default_city")
    guild_cities = relationship("GuildCity", back_populates="city")
    prayer_caches = relationship("PrayerCache", back_populates="city")

    __table_args__ = (
        Index("idx_city_name_ar", "name_ar"),
        Index("idx_city_name_en", "name_en"),
    )


class GuildSetting(Base):
    __tablename__ = "guild_settings"

    guild_id = Column(BigInteger, primary_key=True, autoincrement=False)
    channel_id = Column(BigInteger, nullable=True)
    default_city_id = Column(Integer, ForeignKey("cities.id"), nullable=True)
    language = Column(String(10), nullable=False, default="ar")
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    default_city = relationship("City", back_populates="guild_settings")
    guild_cities = relationship("GuildCity", back_populates="guild_setting")


class GuildCity(Base):
    __tablename__ = "guild_city"

    guild_id = Column(BigInteger, primary_key=True, autoincrement=False)
    city_id = Column(Integer, ForeignKey("cities.id"), primary_key=True)

    guild_setting = relationship("GuildSetting", back_populates="guild_cities")
    city = relationship("City", back_populates="guild_cities")


class PrayerCache(Base):
    __tablename__ = "prayer_cache"

    city_id = Column(Integer, ForeignKey("cities.id"), primary_key=True)
    date = Column(String(10), primary_key=True)
    fajr = Column(String(5), nullable=False)
    sunrise = Column(String(5), nullable=False)
    dhuhr = Column(String(5), nullable=False)
    asr = Column(String(5), nullable=False)
    maghrib = Column(String(5), nullable=False)
    isha = Column(String(5), nullable=False)
    timings = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=utcnow, nullable=False)

    city = relationship("City", back_populates="prayer_caches")

    __table_args__ = (
        Index("idx_prayer_city_date", "city_id", "date"),
    )
