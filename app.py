from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

import geonamescache
import pandas as pd
import streamlit as st
import swisseph as swe
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import uuid
# ==================== 1. Security (Fixed) ====================
KEY_FILE = "license.key"

def get_machine_id():
    return hex(uuid.getnode())

def generate_password(mid):
    # مطابقة تامة لمنطق أداة فك الحماية الثابتة
    digits = ''.join(filter(str.isdigit, mid))
    if not digits: 
        try:
            digits = str(int(mid, 16))
        except:
            return "Error"
    num = int(digits)
    result = round(abs(num / 2 * 3.14))
    return str(result)[:6]

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = os.path.exists(KEY_FILE)

if not st.session_state['authenticated']:
    st.set_page_config(page_title="Security", layout="centered")
    st.title("Security Activation - Ask the programmer for your password")
    st.warning("Send your Machine ID to programmer email : mulham81ahmed@gmail.com ")

    mid = get_machine_id()
    st.info(f"Machine ID: {mid}")
    pwd = st.text_input("Enter Activation Key:", type="password")
    
    if st.button("Activate"):
        if pwd == generate_password(mid):
            with open(KEY_FILE, "w") as f: 
                f.write(pwd)
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error("Invalid Activation Key.")
            
    st.stop()


# ==================== إعدادات Swiss Ephemeris ====================
swe.set_ephe_path('')  # استخدام وضع Moshier الافتراضي للتقويم الفلكي الدقيق

# ==================== الثوابت وقوائم الكواكب والحكام ====================

TARGET_PLANETS = ['Mars', 'Rahu', 'Ketu', 'Saturn', 'Neptune', 'Uranus', 'Pluto']
SLOW_PLANETS = ['Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']
HAZARD_CONJUNCT_PLANETS = ['Rahu', 'Ketu', 'Mars', 'Pluto', 'Neptune', 'Uranus', 'Saturn']

ORB = 3.0             # 3 درجات قوسية للكواكب حسب معايير اللجنة
ANGULAR_ORB = 6.0     # 0 إلى 6 درجات أقصى حد مسموح للاقتران بالأوتاد والبيوت (1، 6، 8، 12)
URANUS_CYCLE_DIVISOR = 4.2857  # معامل التقسيم الخاص بالنظرية (دورة أورانوس ~84 سنة)

PLANET_IDS = {
    'Sun': swe.SUN,
    'Moon': swe.MOON,
    'Mars': swe.MARS,
    'Jupiter': swe.JUPITER,
    'Saturn': swe.SATURN,
    'Uranus': swe.URANUS,
    'Neptune': swe.NEPTUNE,
    'Pluto': swe.PLUTO,
    'Rahu': swe.MEAN_NODE,
    'Ketu': -1,  # يُحسب تلقائياً بإضافة 180 درجة لـ Rahu
}

PLANET_NAMES_AR = {
    'Sun': 'الشمس',
    'Moon': 'القمر',
    'Mars': 'المريخ',
    'Jupiter': 'المشتري',
    'Saturn': 'زحل',
    'Uranus': 'أورانوس',
    'Neptune': 'نبتون',
    'Pluto': 'بلوتو',
    'Rahu': 'راخو (العقدة الشمالية)',
    'Ketu': 'كيتو (العقدة الجنوبية)'
}

# جدول حكام الأبراج للتحقق من حاكم الطالع
SIGN_RULERS = {
    0: ['Mars'],               # الحمل
    1: ['Venus'],              # الثور
    2: ['Mercury'],            # الجوزاء
    3: ['Moon'],               # السرطان
    4: ['Sun'],                # الأسد
    5: ['Mercury'],            # العذراء
    6: ['Venus'],              # الميزان
    7: ['Mars', 'Pluto'],      # العقرب
    8: ['Jupiter'],            # القوس
    9: ['Saturn'],             # الجدي
    10: ['Saturn', 'Uranus'],  # الدلو
    11: ['Jupiter', 'Neptune'] # الحوت
}

class City(NamedTuple):
    geonameid: str
    name: str
    country_code: str
    latitude: float
    longitude: float
    admin1: str
    population: int

@dataclass
class USMRow:
    risk_year: int             # السنة الحرجة كعدد صحيح (مثلاً 2008)
    risk_power: str            # قوة الخطر (عالي جداً / متوسط)
    trigger_planets: str       # الكواكب مسببة الخطر
    mechanism: str             # كيفية الخطر
    quarter: str               # الربع السنوي المتوقع الخطر داخله
    exact_date: date
    age: float
    cycle_type: str
    condition_2_met: bool
    is_priority_planet: bool

# ==================== تحميل البيانات الجغرافية ====================

@st.cache_resource
def load_cities() -> list[City]:
    gc = geonamescache.GeonamesCache()
    cities_list = []
    for city_id, city_data in gc.get_cities().items():
        if city_data.get("population", 0) >= 15000:
            cities_list.append(
                City(
                    geonameid=city_id,
                    name=city_data.get("name", ""),
                    country_code=city_data.get("countrycode", ""),
                    latitude=city_data.get("latitude", 0.0),
                    longitude=city_data.get("longitude", 0.0),
                    admin1=city_data.get("admin1code", ""),
                    population=city_data.get("population", 0),
                )
            )
    return cities_list

@st.cache_resource
def load_countries() -> dict:
    gc = geonamescache.GeonamesCache()
    return gc.get_countries()

def get_cities_by_country(country_code: str) -> list[City]:
    cities = load_cities()
    return sorted(
        [c for c in cities if c.country_code == country_code],
        key=lambda c: c.population,
        reverse=True,
    )

def get_timezone_for_city(city: City) -> str | None:
    try:
        tf = TimezoneFinder()
        return tf.timezone_at(lat=city.latitude, lng=city.longitude)
    except Exception:
        return None

# ==================== الحسابات الفلكية والأدوات المساعدة ====================

def get_quarter_string(month: int) -> str:
    """تحديد الربع السنوي بناءً على الشهر"""
    if 1 <= month <= 3:
        return "الربع الأول (Q1)"
    elif 4 <= month <= 6:
        return "الربع الثاني (Q2)"
    elif 7 <= month <= 9:
        return "الربع الثالث (Q3)"
    else:
        return "الربع الرابع (Q4)"

def get_julian_day(dt_utc: datetime) -> float:
    """تحويل التاريخ والوقت (UTC) إلى التاريخ اليولياني (Julian Day)"""
    decimal_hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, decimal_hour)

def get_planet_longitude(planet_name: str, dt_utc: datetime) -> float:
    """حساب درجة موقع الكوكب أو النقطة بدقة عالية من 0 الحمل"""
    jd = get_julian_day(dt_utc)
    if planet_name == 'Ketu':
        rahu_pos = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
        return (rahu_pos + 180.0) % 360.0
    
    planet_id = PLANET_IDS.get(planet_name)
    if planet_id is not None:
        res = swe.calc_ut(jd, planet_id)
        return res[0][0]
    
    raise ValueError(f"اسم الكوكب غير معروف: {planet_name}")

def calculate_whole_sign_houses(ascendant_longitude: float) -> dict[int, float]:
    """توزيع البيوت بنظام البرج الكامل (Whole Sign / كل برج بيت)"""
    ascendant_sign = int(ascendant_longitude // 30)
    houses = {}
    for i in range(12):
        house_number = i + 1
        sign_index = (ascendant_sign + i) % 12
        houses[house_number] = sign_index * 30.0
    return houses

def is_within_orb(pos1: float, pos2: float, orb: float = ORB) -> bool:
    """التحقق مما إذا كانت المسافة القوسية ضمن الجرم المسموح"""
    diff = abs(pos1 - pos2)
    diff = min(diff, 360.0 - diff)
    return diff <= orb

def get_sign_zero_degree(deg: float) -> float:
    """إرجاع درجة 0 من البرج الذي تقع فيه النقطة"""
    return math.floor(deg / 30.0) * 30.0

def is_planet_ruler_or_near_asc(planet_name: str, transit_dt: datetime, natal_asc: float, natal_rulers: list[str]) -> bool:
    """التحقق مما إذا كان الكوكب العابر (أو مقترنه) حاكماً للطالع أو قريباً من درجة الطالع"""
    if planet_name in natal_rulers:
        return True
    
    planet_pos = get_planet_longitude(planet_name, transit_dt)
    if is_within_orb(planet_pos, natal_asc, ORB):
        return True
        
    for h_p in HAZARD_CONJUNCT_PLANETS:
        if h_p == planet_name:
            continue
        h_pos = get_planet_longitude(h_p, transit_dt)
        t_pos = get_planet_longitude(planet_name, transit_dt)
        if is_within_orb(h_pos, t_pos, ORB):
            if h_p in natal_rulers or is_within_orb(h_pos, natal_asc, ORB):
                return True
                
    return False

# ==================== الدالة الرئيسية للتطبيق ====================

def libephemeris():
    st.set_page_config(page_title="استرو رادار- توقيت الخطر الجسيم", layout="wide")
    st.title("نظام نظرية استرو رادار- نسخة الشركات و الدول - (للفلكي و المبرمج الدكتور : ملهم احمد)")
    st.caption(" -  نظام كل برج بيت -   تثبيت 84 سنة دورة أورانوس الكاملة للتوقع - أوربت 3.0 درجات - نطاق 0-6 درجات للأوتاد - دقة +/- 6 شهور عن وقوع الحدث")
    st.markdown("---")

    # تحميل بيانات الدول والمدن
    countries_data = load_countries()
    country_options = {f"{c['name']} ({code})": code for code, c in countries_data.items()}
    sorted_country_names = sorted(country_options.keys())

    col1, col2, col3 = st.columns(3)

    with col1:
        name = st.text_input("اسم الفرد / الكيان / الدولة", placeholder="أدخل الاسم هنا...")
        selected_country_label = st.selectbox("اختر الدولة", sorted_country_names)
        selected_country_code = country_options[selected_country_label]

    with col2:
        available_cities = get_cities_by_country(selected_country_code)
        if available_cities:
            city_names = [f"{c.name} (تعداد: {c.population:,})" for c in available_cities]
            selected_city_index = st.selectbox("اختر المدينة", range(len(city_names)), format_func=lambda x: city_names[x])
            selected_city = available_cities[selected_city_index]
        else:
            st.error("لم يتم العثور على مدن لهذه الدولة.")
            selected_city = None

        dob = st.date_input("تاريخ الميلاد / الاستقلال", min_value=date(1800, 1, 1), max_value=date(2100, 1, 1), value=date(1990, 1, 1))

    with col3:
        # إلغاء إدخال ساعة الميلاد واعتماد منتصف النهار افتراضياً وتثبيت نظام كل برج بيت
        tob = time(12, 0)
        st.info("تم اعتماد نظام (كل برج بيت - Whole Sign) تلقائياً .")

        # تثبيت سنة التوقع لـ 84 سنة تلقائياً
        start_year = dob.year
        end_year = start_year + 84
        st.write(f"**نطاق التوقع الممتد تلقائياً (84 سنة - دورة أورانوس):** {start_year} - {end_year}")

    # زر التحليل والتنفيذ
    if st.button("تشغيل خوارزمية تحليل النظرية", type="primary", use_container_width=True):
        if not name:
            st.warning("يرجى إدخال الاسم قبل بدء التحليل.")
            st.stop()
        if not selected_city:
            st.error("يرجى اختيار مدينة صحيحة.")
            st.stop()

        with st.spinner("جاري معالجة المواضع الفلكية وتطبيق قواعد الأوتاد ودورة أورانوس (84 سنة) بنظام كل برج بيت..."):
            
            # ضبط التوقيت العالمي (UTC) افتراضياً عند منتصف النهار (12:00)
            tz_str = get_timezone_for_city(selected_city)
            if tz_str:
                try:
                    local_tz = ZoneInfo(tz_str)
                    local_dt = datetime.combine(dob, tob).replace(tzinfo=local_tz)
                    utc_dt = local_dt.astimezone(timezone.utc)
                except ZoneInfoNotFoundError:
                    utc_dt = datetime.combine(dob, tob).replace(tzinfo=timezone.utc)
            else:
                utc_dt = datetime.combine(dob, tob).replace(tzinfo=timezone.utc)

            # تحديد نظام البيوت والطالع بناءً على نظام (كل برج بيت - Whole Sign) اعتماداً على البرج الشمسي
            asc_degree = get_planet_longitude("Sun", utc_dt)
            mc_degree = (asc_degree + 90.0) % 360.0
            houses = calculate_whole_sign_houses(asc_degree)
            house_system_name = "Whole Sign (كل برج بيت)"

            # تحديد حاكم الطالع
            asc_sign_index = int(asc_degree // 30)
            natal_rulers = SIGN_RULERS.get(asc_sign_index, ['Mars'])

            # حساب مواقع الكواكب ومسافة 0 الحمل
            natal_positions = {}
            distances_from_aries = {}
            for planet in TARGET_PLANETS:
                pos = get_planet_longitude(planet, utc_dt)
                natal_positions[planet] = pos
                distances_from_aries[planet] = pos % 360.0

            priority_planet = min(distances_from_aries, key=distances_from_aries.get)

            # بناء نقاط الأوتاد والبيوت الحساسة (1، 6، 8، 12) مع نطاق 0 - 6 درجات
            angular_houses = [1, 6, 8, 12]
            target_house_cusps = {h: houses[h] for h in angular_houses}

            usm_results: list[USMRow] = []

            # فحص دورات الكواكب
            for planet, natal_pos in natal_positions.items():
                base_age = distances_from_aries[planet] / URANUS_CYCLE_DIVISOR
                
                cycles_to_check = [
                    (base_age, "دورة أساسية"),
                    (base_age + 42.0, "دورة المعارضة (42 سنة)"),
                    (base_age + 84.0, "دورة العودة (84 سنة)")
                ]

                is_priority = (planet == priority_planet)

                for target_age, cycle_label in cycles_to_check:
                    days_to_add = target_age * 365.2425
                    target_utc_date = utc_dt + timedelta(days=days_to_add)
                    
                    # استخراج السنة كعدد صحيح
                    current_risk_year = int(target_utc_date.year)

                    # فحص نطاق الـ 84 سنة المعتمد
                    if start_year <= current_risk_year <= end_year:
                        condition_1_met = False
                        active_transits = []
                        matched_mechanisms = []

                        for t_planet in SLOW_PLANETS:
                            t_pos = get_planet_longitude(t_planet, target_utc_date)
                            hit_angle = False

                            # تطبيق نطاق الاقتران بالأوتاد (0 - 6 درجات)
                            for h_num, cusp_deg in target_house_cusps.items():
                                # فحص القرب المباشر من درجة الوتد ضمن نطاق ANGULAR_ORB (6 درجات)
                                if is_within_orb(t_pos, cusp_deg, ANGULAR_ORB):
                                    hit_angle = True
                                    t_ar = PLANET_NAMES_AR.get(t_planet, t_planet)
                                    matched_mechanisms.append(f"عبور {t_ar} على وتد/بيت ({h_num}) ضمن نطاق (0-6°)")
                                    break
                                
                                # فحص إضافي لنطاق 0 إلى 6 درجات من بداية البيت
                                if is_within_orb(t_pos, (cusp_deg + ANGULAR_ORB) % 360.0, ORB):
                                    hit_angle = True
                                    t_ar = PLANET_NAMES_AR.get(t_planet, t_planet)
                                    matched_mechanisms.append(f"عبور {t_ar} في نطاق (0-6°) للبيت ({h_num})")
                                    break

                            if hit_angle:
                                condition_1_met = True
                                if t_planet not in active_transits:
                                    active_transits.append(t_planet)

                        # فحص الشرط الإضافي للكوارث
                        condition_2_met = False
                        if condition_1_met:
                            for active_p in active_transits:
                                is_conjunct_hazard = active_p in HAZARD_CONJUNCT_PLANETS
                                if not is_conjunct_hazard:
                                    for h_c in HAZARD_CONJUNCT_PLANETS:
                                        if is_within_orb(get_planet_longitude(active_p, target_utc_date), get_planet_longitude(h_c, target_utc_date), ORB):
                                            is_conjunct_hazard = True
                                            break
                                
                                is_ruler_or_asc = is_planet_ruler_or_near_asc(active_p, target_utc_date, asc_degree, natal_rulers)

                                if is_conjunct_hazard and is_ruler_or_asc:
                                    condition_2_met = True
                                    matched_mechanisms.append("اقتران بحاكم الطالع / اتصالات مدمرة")
                                    break

                        if condition_1_met:
                            # تحديث قوة الخطر وكيفية الخطر
                            risk_power = "خطر شديد جداً (تحول كارثي)" if condition_2_met else "تنبيه خطر متوسط على الأوتاد"
                            
                            trigger_ar = PLANET_NAMES_AR.get(planet, planet)
                            active_ar_list = [PLANET_NAMES_AR.get(p, p) for p in active_transits]
                            trigger_planets_str = f"{trigger_ar} (عبور: {', '.join(active_ar_list)})"
                            
                            mechanism_str = " | ".join(set(matched_mechanisms)) if matched_mechanisms else "عبور كواكب بطيئة على الأوتاد الحساسة"
                            quarter_str = get_quarter_string(target_utc_date.month)

                            usm_results.append(
                                USMRow(
                                    risk_year=current_risk_year,
                                    risk_power=risk_power,
                                    trigger_planets=trigger_planets_str,
                                    mechanism=mechanism_str,
                                    quarter=quarter_str,
                                    exact_date=target_utc_date.date(),
                                    age=target_age,
                                    cycle_type=cycle_label,
                                    condition_2_met=condition_2_met,
                                    is_priority_planet=is_priority
                                )
                            )

            # ==================== عرض الجدول والمخرجات ====================
            st.subheader(f"📊 جدول نتائج تحليل النظرية: {name}")
            st.write(f"**نطاق التوقع:** {start_year} - {end_year} (84 سنة) | **نظام البيوت:** {house_system_name} | **درجة الطالع:** {asc_degree:.2f}° | **الأوربت:** {ORB}°")

            if not usm_results:
                st.success("الوضع الفلكي مستقر: لم يتم رصد تقاطعات تطابق الشروط الحرجة ضمن نطاق الـ 84 سنة.")
            else:
                # ترتيب النتائج حسب السنة
                usm_results.sort(key=lambda x: x.risk_year)

                # بناء DataFrame يطابق جدول المخرجات المطلوب
                table_data = []
                for r in usm_results:
                    table_data.append({
                        "السنوات الحرجة": r.risk_year,
                        "قوة الخطر": r.risk_power,
                        "الكواكب مسببة الخطر": r.trigger_planets,
                        "كيفية الخطر": r.mechanism,
                        "الربع السنوي المتوقع للخطر داخل السنة": r.quarter
                    })

                df_display = pd.DataFrame(table_data)

                # عرض الجدول بشكل منسق وأنيق على واجهة Streamlit
                st.dataframe(
                    df_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "السنوات الحرجة": st.column_config.NumberColumn("السنوات الحرجة", format="%d"),
                    }
                )

                # زر تحميل البيانات بصيغة CSV كبديل مناسب للغة العربية
                csv_data = df_display.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 تحميل جدول النتائج بصيغة CSV",
                    data=csv_data,
                    file_name=f"USM_Risk_Report_{name}_{dob.year}.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

# تشغيل التطبيق
if __name__ == "__main__":
    libephemeris()
