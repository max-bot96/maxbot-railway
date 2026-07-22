import os
import sys
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.connection import init_db, get_session, close_db


COUNTRY = {
    "name_ar": "المملكة العربية السعودية",
    "name_en": "Saudi Arabia",
    "iso_code": "SA",
    "timezone_default": "Asia/Riyadh",
}

REGIONS = [
    {"name_ar": "منطقة الرياض", "name_en": "Riyadh Region"},
    {"name_ar": "منطقة مكة المكرمة", "name_en": "Makkah Region"},
    {"name_ar": "منطقة المدينة المنورة", "name_en": "Madinah Region"},
    {"name_ar": "منطقة القصيم", "name_en": "Al-Qassim Region"},
    {"name_ar": "المنطقة الشرقية", "name_en": "Eastern Region"},
    {"name_ar": "منطقة عسير", "name_en": "Asir Region"},
    {"name_ar": "منطقة تبوك", "name_en": "Tabuk Region"},
    {"name_ar": "منطقة حائل", "name_en": "Ha'il Region"},
    {"name_ar": "منطقة الحدود الشمالية", "name_en": "Northern Borders Region"},
    {"name_ar": "منطقة جازان", "name_en": "Jazan Region"},
    {"name_ar": "منطقة نجران", "name_en": "Najran Region"},
    {"name_ar": "منطقة الباحة", "name_en": "Al-Bahah Region"},
    {"name_ar": "منطقة الجوف", "name_en": "Al-Jawf Region"},
]

SA_CITIES = {
    0: [  # Riyadh
        ("01", "الرياض", "Riyadh", 24.7136, 46.6753),
        ("02", "الدرعية", "Diriyah", 24.7539, 46.5756),
        ("03", "الخرج", "Al-Kharj", 24.1556, 47.3347),
        ("04", "الدوادمي", "Al-Duwadmi", 24.5075, 44.3922),
        ("05", "المجمعة", "Al-Majma'ah", 25.9033, 45.3361),
        ("06", "القويعية", "Al-Quway'iyah", 24.0733, 45.2825),
        ("07", "وادي الدواسر", "Wadi Al-Dawasir", 20.4658, 44.7769),
        ("08", "الأفلاج", "Al-Aflaj", 22.2922, 46.7250),
        ("09", "الزلفي", "Al-Zulfi", 26.2994, 44.8144),
        ("10", "شقراء", "Shaqra", 25.2503, 45.2517),
        ("11", "حوطة بني تميم", "Hotat Bani Tamim", 23.4975, 46.7850),
        ("12", "عفيف", "Afif", 23.9144, 42.9169),
        ("13", "السليل", "Al-Sulayyil", 20.4600, 45.5744),
        ("14", "ضرما", "Dhurma", 24.6033, 46.1256),
        ("15", "المزاحمية", "Al-Muzahimiyah", 24.4700, 46.2572),
        ("16", "رماح", "Rimah", 25.5614, 47.1842),
        ("17", "ثادق", "Thadiq", 25.2956, 45.8633),
        ("18", "حريملاء", "Huraymila", 25.1300, 46.1258),
        ("19", "الحريق", "Al-Hariq", 23.6389, 46.5142),
        ("20", "الغاط", "Al-Ghat", 26.0319, 44.9672),
        ("21", "مرات", "Marat", 25.0725, 45.4625),
    ],
    1: [  # Makkah
        ("01", "مكة المكرمة", "Makkah", 21.4225, 39.8262),
        ("02", "جدة", "Jeddah", 21.4858, 39.1925),
        ("03", "الطائف", "Taif", 21.2667, 40.4167),
        ("04", "القنفذة", "Al-Qunfudhah", 19.1261, 41.0789),
        ("05", "الليث", "Al-Leith", 20.1486, 40.2761),
        ("06", "رابغ", "Rabigh", 22.7989, 39.0342),
        ("07", "خليص", "Khulays", 22.1400, 39.3344),
        ("08", "الخرمة", "Al-Khurmah", 21.9175, 42.0503),
        ("09", "رنية", "Ranyah", 21.2575, 42.8281),
        ("10", "تربة", "Turabah", 21.2142, 41.6275),
        ("11", "الجموم", "Al-Jumum", 21.6136, 39.6944),
        ("12", "الكامل", "Al-Kamil", 22.2575, 39.4639),
        ("13", "أضم", "Adham", 20.4722, 40.0236),
        ("14", "الموية", "Al-Muwayh", 22.4347, 41.7581),
        ("15", "ميسان", "Maysan", 20.1425, 40.5292),
        ("16", "بحرة", "Bahrah", 21.4000, 39.4500),
    ],
    2: [  # Madinah
        ("01", "المدينة المنورة", "Madinah", 24.4667, 39.6000),
        ("02", "ينبع", "Yanbu", 24.0894, 38.0636),
        ("03", "العلا", "Al-Ula", 26.6167, 37.9167),
        ("04", "المهد", "Al-Mahd", 23.5000, 40.8667),
        ("05", "الحناكية", "Al-Hinakiyah", 24.8833, 40.5167),
        ("06", "بدر", "Badr", 23.7833, 38.7833),
        ("07", "خيبر", "Khaybar", 25.6833, 39.3000),
        ("08", "العيص", "Al-Is", 25.3667, 37.9333),
        ("09", "وادي الفرع", "Wadi Al-Far", 24.3167, 39.3333),
        ("10", "السويرقية", "Al-Suwayriqiyah", 23.8833, 40.3000),
    ],
    3: [  # Al-Qassim
        ("01", "بريدة", "Buraydah", 26.3333, 43.9667),
        ("02", "عنيزة", "Unayzah", 26.0833, 43.9833),
        ("03", "الرس", "Ar Rass", 25.8667, 43.4833),
        ("04", "المذنب", "Al-Midhnab", 25.8667, 43.9833),
        ("05", "البكيرية", "Al-Bukayriyah", 26.1500, 43.6500),
        ("06", "البدائع", "Al-Badai", 25.7833, 43.4167),
        ("07", "الأسياح", "Al-Asyah", 26.4333, 44.0833),
        ("08", "النبهانية", "Al-Nabhaniyah", 25.6000, 42.8000),
        ("09", "عيون الجواء", "Uyun Al-Jiwa", 25.8333, 43.6000),
        ("10", "رياض الخبراء", "Riyad Al-Khabra", 25.9167, 43.5000),
        ("11", "عقلة الصقور", "Uqlat Al-Suqur", 25.8333, 42.2000),
        ("12", "ضرية", "Dhariyah", 25.3333, 42.1333),
        ("13", "الشماسية", "Al-Shammasiyah", 26.1667, 43.8333),
    ],
    4: [  # Eastern Province
        ("01", "الدمام", "Dammam", 26.4333, 50.1000),
        ("02", "الأحساء", "Al-Ahsa", 25.3833, 49.5833),
        ("03", "حفر الباطن", "Hafar Al-Batin", 28.4333, 45.9667),
        ("04", "الجبيل", "Jubail", 27.0000, 49.6500),
        ("05", "القطيف", "Al-Qatif", 26.5500, 50.0167),
        ("06", "الخبر", "Al-Khobar", 26.2833, 50.2000),
        ("07", "رأس تنورة", "Ras Tanura", 26.6500, 50.1500),
        ("08", "بقيق", "Buqayq", 25.9333, 49.6667),
        ("09", "النعيرية", "Al-Nairyah", 27.4667, 48.4833),
        ("10", "قرية العليا", "Qaryat Al-Ulya", 27.5000, 47.7000),
        ("11", "الخفجي", "Al-Khafji", 28.4333, 48.5000),
        ("12", "سيهات", "Sayhat", 26.4833, 50.0500),
        ("13", "عنك", "Anak", 26.4500, 50.0667),
    ],
    5: [  # Asir
        ("01", "أبها", "Abha", 18.2167, 42.5000),
        ("02", "خميس مشيط", "Khamis Mushait", 18.3000, 42.7333),
        ("03", "بيشة", "Bisha", 20.0000, 42.6000),
        ("04", "النماص", "Al-Namas", 19.1167, 42.1333),
        ("05", "محايل", "Muhayil", 18.5500, 42.0333),
        ("06", "سراة عبيدة", "Sarat Abidah", 18.0833, 43.2500),
        ("07", "رجال المع", "Rijal Alma", 18.2500, 42.3000),
        ("08", "تثليث", "Tathlith", 19.5167, 43.5000),
        ("09", "ظهران الجنوب", "Dhahran Al-Janub", 17.6333, 43.5000),
        ("10", "أحد رفيدة", "Ahad Rafidah", 18.2000, 42.4000),
        ("11", "بلقرن", "Balqarn", 19.4000, 42.1000),
        ("12", "المجاردة", "Al-Majaridah", 18.3833, 42.1833),
        ("13", "تنومة", "Tanumah", 19.0000, 42.1667),
        ("14", "البرك", "Al-Birk", 18.2167, 41.5500),
        ("15", "بارق", "Bariq", 18.9333, 41.9333),
    ],
    6: [  # Tabuk
        ("01", "تبوك", "Tabuk", 28.3833, 36.5667),
        ("02", "تيماء", "Tayma", 27.6333, 38.5333),
        ("03", "أملج", "Umluj", 25.0500, 37.2667),
        ("04", "الوجه", "Al-Wajh", 26.2333, 36.4667),
        ("05", "ضباء", "Duba", 27.3500, 35.6833),
        ("06", "حقل", "Haql", 29.2833, 36.7333),
        ("07", "البدع", "Al-Bad", 28.4833, 35.0167),
    ],
    7: [  # Ha'il
        ("01", "حائل", "Ha'il", 27.5167, 41.6833),
        ("02", "بقعاء", "Baq'a", 27.9333, 42.6667),
        ("03", "الغزالة", "Al-Ghazalah", 27.7500, 41.7500),
        ("04", "الشنان", "Al-Shinan", 27.8833, 42.0333),
        ("05", "الحائط", "Al-Hait", 27.1500, 42.1500),
        ("06", "موقق", "Mawqaq", 27.4667, 41.3333),
        ("07", "السليمي", "Al-Sulaymi", 27.3833, 41.9000),
        ("08", "سميراء", "Samira", 27.3000, 42.2667),
        ("09", "الشملي", "Al-Shamli", 27.8333, 41.2000),
    ],
    8: [  # Northern Borders
        ("01", "عرعر", "Arar", 30.9833, 41.0167),
        ("02", "رفحاء", "Rafha", 29.6333, 43.5000),
        ("03", "طريف", "Turaif", 31.6833, 38.6500),
        ("04", "العويقيلة", "Al-Uwayqilah", 30.3333, 41.9167),
    ],
    9: [  # Jazan
        ("01", "جازان", "Jazan", 16.8833, 42.5500),
        ("02", "صبيا", "Sabya", 17.1500, 42.6333),
        ("03", "أبو عريش", "Abu Arish", 16.9667, 42.8333),
        ("04", "صامطة", "Samtah", 16.6000, 42.9500),
        ("05", "الحرث", "Al-Harth", 16.8333, 42.3333),
        ("06", "الداير", "Al-Dayir", 17.1833, 42.7333),
        ("07", "الريث", "Al-Rayth", 17.1333, 42.5000),
        ("08", "العارضة", "Al-Ardah", 16.6500, 42.6833),
        ("09", "العيدابي", "Al-Aydabi", 17.0000, 42.8667),
        ("10", "الفرش", "Al-Farsh", 16.7833, 42.5833),
        ("11", "فيفا", "Fifa", 17.2667, 42.3833),
        ("12", "القطايف", "Al-Qatayf", 16.7333, 42.6500),
        ("13", "الدرب", "Al-Darb", 17.7167, 42.2500),
        ("14", "بيش", "Baysh", 17.3833, 42.4833),
        ("15", "ضمد", "Damad", 17.0833, 42.7500),
        ("16", "هروب", "Harub", 17.0000, 42.6000),
    ],
    10: [  # Najran
        ("01", "نجران", "Najran", 17.5667, 44.2167),
        ("02", "شرورة", "Sharurah", 17.4667, 47.1167),
        ("03", "حبونا", "Hubuna", 17.3000, 44.1500),
        ("04", "بدر الجنوب", "Badr Al-Janub", 17.8000, 44.7000),
        ("05", "يدمة", "Yadamah", 17.0500, 44.3000),
        ("06", "ثار", "Thar", 17.4500, 44.3500),
        ("07", "خباش", "Khabash", 16.9500, 44.0000),
        ("08", "الخرخير", "Al-Kharkhir", 18.0000, 45.0000),
    ],
    11: [  # Al-Bahah
        ("01", "الباحة", "Al-Bahah", 20.0000, 41.4667),
        ("02", "المندق", "Al-Mandaq", 20.0667, 41.2833),
        ("03", "المخواة", "Al-Mikhwah", 19.7833, 41.4333),
        ("04", "بنى حسن", "Bani Hasan", 20.0167, 41.3667),
        ("05", "غامد الزناد", "Ghamid Al-Zinad", 19.9000, 41.5500),
        ("06", "الحجرة", "Al-Hajrah", 19.6833, 41.3500),
        ("07", "القرى", "Al-Qura", 19.9833, 41.3833),
        ("08", "بلجرشي", "Baljurashi", 19.8500, 41.5667),
        ("09", "النعيرية", "Al-Na'iriyah", 20.0333, 41.4500),
        ("10", "الشقيق", "Al-Shiqiq", 19.9000, 41.4500),
    ],
    12: [  # Al-Jawf
        ("01", "سكاكا", "Sakaka", 29.9667, 40.2000),
        ("02", "القريات", "Al-Qurayyat", 31.3333, 37.3500),
        ("03", "دومة الجندل", "Dumat Al-Jandal", 29.8167, 39.8667),
        ("04", "طبرجل", "Tabarjal", 30.5000, 38.2167),
        ("05", "النبك", "Al-Nabk", 30.0333, 40.1167),
    ],
}


async def seed():
    await init_db()
    session = await get_session()

    try:
        result = await session.execute(text("SELECT COUNT(*) FROM countries"))
        count = result.scalar()
        if count > 0:
            print("[SEED] ⚡ Database already seeded — skipping")
            return

        await session.execute(
            text("""
                INSERT INTO countries (name_ar, name_en, iso_code, timezone_default, created_at, updated_at)
                VALUES (:name_ar, :name_en, :iso_code, :tz, NOW(), NOW())
            """),
            {"name_ar": COUNTRY["name_ar"], "name_en": COUNTRY["name_en"],
             "iso_code": COUNTRY["iso_code"], "tz": COUNTRY["timezone_default"]},
        )
        await session.commit()
        print(f"[SEED] ✅ Country: {COUNTRY['name_ar']}")

        region_ids = {}
        for i, reg in enumerate(REGIONS):
            result = await session.execute(
                text("""
                    INSERT INTO regions (country_id, name_ar, name_en, created_at, updated_at)
                    VALUES (1, :name_ar, :name_en, NOW(), NOW())
                    RETURNING id
                """),
                {"name_ar": reg["name_ar"], "name_en": reg["name_en"]},
            )
            region_ids[i] = result.scalar()
        await session.commit()
        print(f"[SEED] ✅ {len(REGIONS)} regions inserted")

        total_cities = 0
        for region_idx, cities in SA_CITIES.items():
            reg_id = region_ids[region_idx]
            for code, name_ar, name_en, lat, lng in cities:
                await session.execute(
                    text("""
                        INSERT INTO cities (region_id, official_code, name_ar, name_en,
                                            latitude, longitude, timezone, created_at, updated_at)
                        VALUES (:rid, :code, :name_ar, :name_en, :lat, :lng, 'Asia/Riyadh', NOW(), NOW())
                    """),
                    {"rid": reg_id, "code": code, "name_ar": name_ar,
                     "name_en": name_en, "lat": lat, "lng": lng},
                )
                total_cities += 1
        await session.commit()
        print(f"[SEED] ✅ {total_cities} cities inserted")

    except Exception as e:
        await session.rollback()
        print(f"[SEED] ❌ Error: {e}")
        raise
    finally:
        await close_db()

    print(f"[SEED] 🎉 Seed complete: 1 country, {len(REGIONS)} regions, {total_cities} cities")


if __name__ == "__main__":
    asyncio.run(seed())
