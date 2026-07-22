"""Initial schema: countries, regions, cities, guild_settings, guild_city, prayer_cache

Revision ID: 001
Revises:
Create Date: 2026-07-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "countries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name_ar", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("iso_code", sa.String(2), nullable=False, unique=True),
        sa.Column("timezone_default", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id"), nullable=False),
        sa.Column("name_ar", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("official_code", sa.String(20), nullable=True),
        sa.Column("name_ar", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Riyadh"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_city_name_ar", "cities", ["name_ar"])
    op.create_index("idx_city_name_en", "cities", ["name_en"])

    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("default_city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="ar"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "guild_city",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "city_id"),
    )

    op.create_table(
        "prayer_cache",
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("fajr", sa.String(5), nullable=False),
        sa.Column("sunrise", sa.String(5), nullable=False),
        sa.Column("dhuhr", sa.String(5), nullable=False),
        sa.Column("asr", sa.String(5), nullable=False),
        sa.Column("maghrib", sa.String(5), nullable=False),
        sa.Column("isha", sa.String(5), nullable=False),
        sa.Column("timings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("city_id", "date"),
    )
    op.create_index("idx_prayer_city_date", "prayer_cache", ["city_id", "date"])


def downgrade() -> None:
    op.drop_table("prayer_cache")
    op.drop_table("guild_city")
    op.drop_table("guild_settings")
    op.drop_index("idx_city_name_en")
    op.drop_index("idx_city_name_ar")
    op.drop_table("cities")
    op.drop_table("regions")
    op.drop_table("countries")
