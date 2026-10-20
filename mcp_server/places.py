import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from itertools import permutations
from pathlib import Path

DATA = Path(os.environ.get("POI_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
TZ = timezone(timedelta(hours=5))
UA = "AstanaWalkAssistant/0.1 (GDG Build with AI hackathon)"
VIEWBOX = "71.20,51.30,71.75,50.98"

POIS = json.loads((DATA / "poi.json").read_text(encoding="utf-8"))
ANCHORS = json.loads((DATA / "anchors.json").read_text(encoding="utf-8")) if (DATA / "anchors.json").exists() else []
META = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
BY_ID = {p["id"]: p for p in POIS}

MODES = {
    "walk": {"speed": 75, "detour": 1.3, "overhead": 0, "label": "пешком", "maps": "walking"},
    "car": {"speed": 650, "detour": 1.3, "overhead": 5, "label": "на такси или машине", "maps": "driving"},
}
VISIT = {
    "cafe": (30, 60), "restaurant": (60, 90), "bar": (60, 120), "nightclub": (120, 240), "karaoke": (90, 180),
    "cinema": (120, 150), "theatre": (120, 180), "arts_centre": (60, 120), "exhibition": (45, 90), "library": (60, 120),
    "coworking": (60, 180), "planetarium": (45, 60), "museum": (60, 90), "gallery": (30, 60),
    "attraction": (10, 30), "viewpoint": (10, 20), "zoo": (90, 150), "aquarium": (60, 90),
    "theme_park": (90, 180), "water_park": (120, 240), "park": (10, 45), "garden": (10, 30),
    "playground": (20, 45), "mall": (60, 120), "ice_rink": (60, 90), "bowling": (60, 120),
    "escape_game": (60, 90), "arcade": (30, 60), "trampoline_park": (60, 90), "worship": (20, 40),
    "monument": (5, 15), "square": (10, 20),
}
TYPICAL_HOURS = {
    "mall": "10:00-22:00", "cafe": "09:00-22:00", "restaurant": "11:00-23:00", "bar": "18:00-02:00",
    "nightclub": "22:00-05:00", "karaoke": "18:00-04:00", "cinema": "10:00-00:00", "gallery": "10:00-19:00",
    "museum": "10:00-18:00, часто выходной в понедельник", "theatre": "спектакли обычно вечером",
    "exhibition": "10:00-18:00 в дни выставок",
    "library": "09:00-18:00", "coworking": "09:00-21:00", "aquarium": "10:00-20:00", "zoo": "10:00-19:00",
    "worship": "днём, во время молитв вход может быть ограничен", "attraction": "днём",
}
TYPICAL_RANGE = {
    "mall": "10:00-22:00", "cafe": "09:00-22:00", "restaurant": "11:00-23:00", "bar": "18:00-02:00",
    "nightclub": "22:00-05:00", "karaoke": "18:00-04:00", "cinema": "10:00-00:00", "museum": "10:00-18:00",
    "gallery": "10:00-19:00", "exhibition": "10:00-18:00", "library": "09:00-18:00", "coworking": "09:00-21:00", "aquarium": "10:00-20:00",
    "zoo": "10:00-19:00", "theatre": "11:00-22:00", "attraction": "10:00-20:00", "worship": "06:00-21:00",
}
PUBLIC = {"park", "garden", "square", "monument", "playground", "viewpoint"}
SKY = [(0, "ясно"), (2, "переменная облачность"), (3, "пасмурно"), (48, "туман"), (57, "морось"), (67, "дождь"),
       (77, "снег"), (82, "ливень"), (86, "снегопад"), (99, "гроза")]
ALIASES = {
    "старый вокзал": "Вокзал Астана", "нурлы жол": "Вокзал Астана Нурлы Жол", "вокзал": "Вокзал Астана Нурлы Жол",
    "мега силк вей": "Mega Silk Way", "мега": "Mega Silk Way", "mega": "Mega Silk Way",
    "экспо": "Всемирная выставка 2017 года", "expo": "Всемирная выставка 2017 года",
    "нур алем": "Всемирная выставка 2017 года", "нұр әлем": "Всемирная выставка 2017 года",
    "nur alem": "Всемирная выставка 2017 года", "аэропорт": "Аэропорт Нурсултан Назарбаев",
    "airport": "Аэропорт Нурсултан Назарбаев", "пирамида": "Дворец мира и согласия", "акорда": "Ак орда",
    "нуржол": "Водно-зелёный бульвар", "бульвар": "Водно-зелёный бульвар",
}
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
})
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)(?:\s*-\s*(?:Mo|Tu|We|Th|Fr|Sa|Su))?"
SPAN = r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}"
RULE = re.compile(rf"((?:{DAY}\s*,?\s*)*)((?:{SPAN}\s*,?\s*)+|off|closed)")

_weather_cache = {}
_geocode_cache = {}
_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]


def get_json(url, params, timeout=10):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def travel_min(meters, mode):
    m = MODES[mode]
    return round(m["overhead"] + meters * m["detour"] / m["speed"])


def rounded(lat, lon):
    return round(float(lat), 3), round(float(lon), 3)


def local_time(at_time=None):
    now = datetime.now(TZ)
    if at_time:
        clock = re.fullmatch(r"(\d{1,2}):(\d{2})", at_time.strip())
        if clock:
            t = now.replace(hour=int(clock[1]) % 24, minute=int(clock[2]), second=0, microsecond=0)
            return t + timedelta(days=1) if t < now - timedelta(hours=2) else t
        try:
            t = datetime.fromisoformat(at_time.strip())
            return t.astimezone(TZ) if t.tzinfo else t.replace(tzinfo=TZ)
        except ValueError:
            pass
    return now.replace(second=0, microsecond=0)


def expand_days(text):
    out = []
    for a, b in re.findall(r"(Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*-\s*(Mo|Tu|We|Th|Fr|Sa|Su))?", text):
        i, j = DAYS.index(a), DAYS.index(b or a)
        out += [(i + k) % 7 for k in range((j - i) % 7 + 1)]
    return out


def clock_min(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def parse_hours(value):
    if value.strip() == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    schedule = {}
    for m in RULE.finditer(value):
        day_text, spans = m.group(1).strip(" ,"), m.group(2)
        days = expand_days(day_text) if day_text else list(range(7))
        ranges = [] if spans in ("off", "closed") else [
            (clock_min(a), clock_min(b)) for a, b in re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", spans)
        ]
        for d in days:
            schedule[d] = ranges
    leftover = re.sub(r"[\s;,]", "", RULE.sub("", value))
    return schedule if schedule and not leftover else None


def open_left(schedule, when):
    day, minute = when.weekday(), when.hour * 60 + when.minute
    for start, end in schedule.get(day, []):
        if start < end and start <= minute < end:
            return end - minute
        if end <= start and minute >= start:
            return 1440 - minute + end
    for start, end in schedule.get((day - 1) % 7, []):
        if end <= start and minute < end:
            return end - minute
    return None


def opens_in(schedule, when):
    return next((step for step in range(0, 7 * 1440, 5) if open_left(schedule, when + timedelta(minutes=step))), None)


def confidence(poi, when):
    try:
        fresh = (when.date() - date.fromisoformat((poi.get("hours_checked") or "")[:10])).days <= 365
    except ValueError:
        fresh = False
    return "high" if fresh else "medium"


def hours_info(poi, when):
    raw = poi["opening_hours"]
    schedule = parse_hours(raw) if raw else None
    if schedule is not None:
        checked = poi.get("hours_checked")
        note = "по данным OpenStreetMap" + (f", проверено {checked[:10]}" if checked else "") + "; часы могли измениться"
        info = {"hours": raw, "confidence": confidence(poi, when), "note": note}
        if raw.strip() == "24/7":
            return {**info, "status": "open", "note": "круглосуточно, " + note}
        left = open_left(schedule, when)
        if left is None:
            return {**info, "status": "closed", "opens_in_min": opens_in(schedule, when)}
        return {**info, "status": "open", "closes_in_min": left}
    if raw:
        return {"status": "unknown", "hours": raw, "confidence": "low", "note": "часы записаны в непонятном формате, проверьте сами"}
    business = poi["phone"] or poi["website"] or "paid" in poi["features"]
    if poi["category"] in PUBLIC and poi["indoor"] is not True and not business:
        return {"status": "public_space", "hours": None, "confidence": "medium",
                "note": "открытое общественное место, обычно доступно всегда"}
    typical = TYPICAL_HOURS.get(poi["category"])
    hint = f"; обычно {typical} (оценка по типу места, не проверено)" if typical else ""
    span = TYPICAL_RANGE.get(poi["category"])
    likely = open_left(parse_hours(span), when) is not None if span else None
    if likely is False:
        hint += ", в это время такие места обычно закрыты"
    return {"status": "unknown", "hours": None, "confidence": "low", "likely_open": likely,
            "note": f"часы неизвестны{hint}; уточните перед выходом"}


def forecast(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    hit = _weather_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    fields = "temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code"
    params = {
        "latitude": key[0], "longitude": key[1], "timezone": "Asia/Almaty", "wind_speed_unit": "ms",
        "forecast_days": 3, "daily": "sunrise,sunset", "current": fields, "hourly": fields,
    }
    for attempt in range(2):
        try:
            res = get_json("https://api.open-meteo.com/v1/forecast", params, timeout=6)
            res["current"]["temperature_2m"]
            _weather_cache[key] = (time.time(), res)
            return res
        except Exception:
            if attempt:
                return None


def weather(lat, lon, when=None):
    res = forecast(lat, lon)
    if not res:
        return None
    cur, label = res["current"], "сейчас"
    hourly = res.get("hourly", {})
    stamp = when.strftime("%Y-%m-%dT%H:00") if when else ""
    if when and abs((when - datetime.now(TZ)).total_seconds()) > 5400 and stamp in hourly.get("time", []):
        i = hourly["time"].index(stamp)
        cur = {k: hourly[k][i] for k in cur if k in hourly}
        label = f"прогноз на {when:%d.%m %H:00}"
    daily = res.get("daily", {})
    days = daily.get("time", [])
    d = days.index(when.date().isoformat()) if when and when.date().isoformat() in days else 0
    sky = next((text for limit, text in SKY if cur["weather_code"] <= limit), "осадки")
    return {
        "summary": f"{label}: {cur['temperature_2m']:+.0f}°C, ощущается как {cur['apparent_temperature']:+.0f}°C, "
                   f"ветер {cur['wind_speed_10m']:.0f} м/с, {sky}",
        "prefer_indoor": cur["apparent_temperature"] <= -10 or cur["wind_speed_10m"] >= 10
        or cur["precipitation"] >= 0.5 or cur["temperature_2m"] >= 32 or cur["weather_code"] >= 95,
        "sunrise": (daily.get("sunrise") or ["T06:00"])[d][-5:],
        "sunset": (daily.get("sunset") or ["T18:00"])[d][-5:],
        "source": "Open-Meteo",
    }


def name_key(name):
    return re.sub(r"\W+", "", name.lower().translate(TRANSLIT))


def name_score(query, name):
    key = name_key(name)
    if not key or not query:
        return 0.0
    if key == query:
        return 1.0
    shorter, longer = sorted((query, key), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return 0.9 if shorter == query else 0.8
    return SequenceMatcher(None, query, key).ratio()


def nominatim(text):
    if text in _geocode_cache:
        return _geocode_cache[text]
    with _nominatim_lock:
        wait = 1.1 - (time.time() - _nominatim_last[0])
        if wait > 0:
            time.sleep(wait)
        _nominatim_last[0] = time.time()
        try:
            res = get_json("https://nominatim.openstreetmap.org/search", {
                "q": text, "format": "jsonv2", "limit": 1, "viewbox": VIEWBOX, "bounded": 1, "accept-language": "ru",
            })
        except Exception:
            return None
    hit = {"name": res[0]["display_name"].split(",")[0], "address": res[0]["display_name"],
           "lat": float(res[0]["lat"]), "lon": float(res[0]["lon"])} if res else None
    _geocode_cache[text] = hit
    return hit


def locate(place):
    text = place.strip().lower()
    alias = next((ALIASES[k] for k in sorted(ALIASES, key=len, reverse=True) if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text)), None)
    query = name_key(alias or place)
    candidates = [(a["name"], a["lat"], a["lon"], "Wikidata", 0) for a in ANCHORS]
    candidates += [(p["name"], p["lat"], p["lon"], p["source"], p["wiki_views_60d"] or 0) for p in POIS if p["named"]]
    ranked = sorted(((name_score(query, c[0]), c[4], c) for c in candidates), key=lambda x: (-x[0], -x[1]))
    good = [c for score, _, c in ranked if score >= 0.75]
    if good:
        name, lat, lon, source, _ = good[0]
        lat, lon = rounded(lat, lon)
        others = list(dict.fromkeys(c[0] for c in good[1:] if c[0] != name))[:2]
        return {"found": True, "name": name, "lat": lat, "lon": lon, "precision": "примерно 100 м", "source": source,
                "other_matches": others}
    hit = nominatim(f"{place}, Астана")
    if hit:
        lat, lon = rounded(hit["lat"], hit["lon"])
        return {"found": True, "name": hit["name"], "address": hit["address"], "lat": lat, "lon": lon,
                "precision": "примерно 100 м", "source": "OpenStreetMap Nominatim"}
    return {"found": False, "note": "Место не найдено. Попросите пользователя назвать ближайший ориентир, улицу или ТРЦ."}


def card(p, d, leg, back, total, hours, closes_soon, budget, end):
    low, high = VISIT[p["category"]]
    item = {
        "id": p["id"], "name": p["name"], "category": p["category_ru"], "distance_m": int(round(d, -1)),
        "travel_min": leg, "to_end_min": back if end else None, "visit_min": f"{low}-{high}", "total_min": total,
        "fits_budget": total <= budget, "open_status": hours["status"], "hours": hours["hours"],
        "hours_confidence": hours["confidence"], "hours_note": hours["note"], "likely_open": hours.get("likely_open"),
        "closes_in_min": hours.get("closes_in_min"), "opens_in_min": hours.get("opens_in_min"),
        "closes_before_visit_ends": closes_soon or None, "indoor": p["indoor"], "features": p["features"],
        "wheelchair": p["wheelchair"] or "нет данных", "description": p["description"][:240],
        "description_source": p["description_source"], "popularity_wiki_views_60d": p["wiki_views_60d"],
        "possibly_closed": p["possibly_closed"] or None, "address": p["address"], "source": p["source"],
        "link": p["source_url"],
    }
    return {k: v for k, v in item.items() if v is not None and v != []}


def search(lat=None, lon=None, time_budget_min=60, categories=None, keywords=None, features=None, mode="walk",
           open_now_only=False, indoor_only=False, wheelchair=False, at_time=None, end_lat=None, end_lon=None,
           limit=8, place=None, end_place=None, with_route=False):
    located = {}
    if place:
        located["start"] = locate(place)
        if not located["start"]["found"]:
            return {"error": "Место пользователя не найдено.", "note": located["start"]["note"]}
        lat, lon = located["start"]["lat"], located["start"]["lon"]
    if lat is None or lon is None:
        return {"error": "Нет места пользователя.", "note": "Передайте place (ориентир или адрес) или lat и lon."}
    if end_place:
        located["end"] = locate(end_place)
        if located["end"]["found"]:
            end_lat, end_lon = located["end"]["lat"], located["end"]["lon"]
    if end_lat is not None and end_lon is not None and mode == "walk" and dist_m(lat, lon, end_lat, end_lon) > 3000:
        mode = "car"
    result = nearby(lat, lon, time_budget_min, categories, keywords, features, mode, open_now_only, indoor_only,
                    wheelchair, at_time, end_lat, end_lon, limit)
    if located:
        result["located"] = {k: {"name": v["name"], "source": v["source"]} if v["found"] else "не найдено"
                             for k, v in located.items()}
    if with_route and result["results"]:
        fitting = [r for r in result["results"] if r["fits_budget"]] or result["results"]
        ids, seen = [], set()
        for r in fitting:
            if r["category"] not in seen:
                ids.append(r["id"])
                seen.add(r["category"])
        ids = (ids + [r["id"] for r in fitting if r["id"] not in ids])[:3]
        plan = route(lat, lon, ids, mode, time_budget_min, at_time, end_lat, end_lon)
        result["route"] = {k: v for k, v in plan.items() if k not in ("data_used", "weather")}
    return result


def nearby(lat, lon, time_budget_min, categories, keywords, features, mode, open_now_only, indoor_only, wheelchair,
           at_time, end_lat, end_lon, limit):
    lat, lon = rounded(lat, lon)
    mode = mode if mode in MODES else "walk"
    budget = max(10, int(time_budget_min or 60))
    when = local_time(at_time)
    end = rounded(end_lat, end_lon) if end_lat is not None and end_lon is not None else None
    sky = weather(lat, lon, when)
    bad_weather = bool(sky and sky["prefer_indoor"])
    clock = when.strftime("%H:%M")
    dark = not (sky["sunrise"] <= clock <= sky["sunset"]) if sky else not 7 <= when.hour < 18
    if sky:
        sky = {**sky, "dark_at_time": dark}
    m = MODES[mode]
    max_leg = min(30 if mode == "walk" else 45, budget * 0.5)
    radius = max(300, (max_leg - m["overhead"]) * m["speed"] / m["detour"])
    cats = {c for c in categories or [] if c in VISIT}
    words = [w.lower().strip() for w in keywords or [] if w.strip()]
    wanted = [f for f in features or [] if f]
    rows = []
    for p in POIS:
        if (cats and p["category"] not in cats) or (not cats and not p["named"]):
            continue
        d = dist_m(lat, lon, p["lat"], p["lon"])
        if d > radius or (indoor_only and p["indoor"] is False) or (wheelchair and p["wheelchair"] == "no"):
            continue
        leg = travel_min(d, mode)
        back = travel_min(dist_m(p["lat"], p["lon"], *end), mode) if end else 0
        low = VISIT[p["category"]][0]
        total = leg + low + back
        hours = hours_info(p, when + timedelta(minutes=leg))
        if open_now_only and hours["status"] == "closed":
            continue
        closes_soon = hours.get("closes_in_min") is not None and hours["closes_in_min"] < low
        text = f"{p['name']} {p['description']} {p['category_ru']}".lower()
        s = 1.0 - min(leg / max_leg, 1.0) * 0.6
        s += 0.4 * min(sum(w in text for w in words), 2) + 0.25 * sum(f in p["features"] for f in wanted)
        s += min(math.log10((p["wiki_views_60d"] or 0) + 1) / 8, 0.45)
        s += 0.15 if p["description_source"] != "tags" else 0
        s += {"open": 0.2, "public_space": 0.15, "unknown": -0.1, "closed": -1.0}[hours["status"]]
        s -= 0.9 if hours.get("likely_open") is False else 0
        s -= 0.4 * (not p["named"]) + 0.8 * p["possibly_closed"] + 0.6 * (total > budget) + 0.5 * closes_soon
        if bad_weather:
            s += 0.2 if p["indoor"] else -0.5 if p["indoor"] is False else 0
        if dark and p["indoor"] is False:
            s += 0.2 if "lit" in p["features"] else -0.3
        if wheelchair and p["wheelchair"] in ("yes", "limited"):
            s += 0.3
        rows.append((s, p, d, leg, back, total, hours, closes_soon))
    rows.sort(key=lambda r: -r[0])
    cap = limit if len(cats) == 1 else 3
    picked, per_cat = [], Counter()
    for r in rows:
        if per_cat[r[1]["category"]] < cap and len(picked) < limit:
            picked.append(r)
            per_cat[r[1]["category"]] += 1
    notes = []
    if not picked:
        notes.append("В радиусе поиска ничего не нашлось. Предложите увеличить время, сменить способ передвижения или убрать фильтры.")
    if picked and all(r[5] > budget for r in picked):
        notes.append("Ни одно место не укладывается в свободное время с учётом дороги"
                     + (" до конечной точки. Советуйте ехать сразу туда" if end else ". Предложите место ближе")
                     + " и скажите это первой фразой.")
    if bad_weather:
        notes.append("Погода неблагоприятная, места в помещении подняты выше.")
    if any(r[6]["status"] == "unknown" for r in picked):
        notes.append("У части мест часы работы неизвестны, не обещайте, что они открыты.")
    if dark:
        notes.append("В это время темно: для прогулок на улице выбирайте людные и освещённые места.")
    filters = {"categories": sorted(cats), "keywords": words, "features": wanted, "open_now_only": open_now_only,
               "indoor_only": indoor_only, "wheelchair": wheelchair}
    return {
        "data_used": {
            "point": f"{lat:.3f}, {lon:.3f} (округлено примерно до 100 м, не сохраняется)",
            "time": when.strftime("%Y-%m-%d %H:%M") + " (Астана, UTC+5)",
            "mode": m["label"], "time_budget_min": budget, "search_radius_m": int(round(radius, -1)),
            "end_point": f"{end[0]:.3f}, {end[1]:.3f}" if end else None,
            "filters": {k: v for k, v in filters.items() if v},
            "data_sources": "OpenStreetMap (ODbL), Wikidata, Wikipedia (CC BY-SA), погода Open-Meteo",
            "data_collected": META["collected_at"][:10],
        },
        "weather": sky,
        "results": [card(*r[1:], budget=budget, end=end) for r in picked],
        "notes": notes,
    }


def maps_link(start, stops, end, mode):
    points = [f"{p['lat']},{p['lon']}" for p in stops]
    params = {"api": 1, "origin": f"{start[0]},{start[1]}", "travelmode": MODES[mode]["maps"],
              "destination": f"{end[0]},{end[1]}" if end else points[-1]}
    waypoints = points if end else points[:-1]
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params)


def plan_stops(start, places, end, mode, when):
    def legs(order):
        points = [start, *[(p["lat"], p["lon"]) for p in order], *([end] if end else [])]
        return [travel_min(dist_m(*a, *b), mode) for a, b in zip(points, points[1:])]

    best = min(permutations(places), key=lambda order: sum(legs(order)))
    times = legs(best)
    t, low_total, high_total, stops, notes = when, 0, 0, [], []
    for p, leg in zip(best, times):
        t += timedelta(minutes=leg)
        low, high = VISIT[p["category"]]
        hours = hours_info(p, t)
        stops.append({k: v for k, v in {
            "id": p["id"], "name": p["name"], "category": p["category_ru"], "travel_min": leg,
            "arrive": t.strftime("%H:%M"), "visit_min": f"{low}-{high}", "open_status_on_arrival": hours["status"],
            "hours": hours["hours"], "hours_note": hours["note"], "closes_in_min": hours.get("closes_in_min"),
        }.items() if v is not None})
        if hours["status"] == "closed":
            notes.append(f"{p['name']} будет закрыто к моменту прихода, замените эту точку.")
        t += timedelta(minutes=low)
        low_total += leg + low
        high_total += leg + high
    end_leg = times[-1] if end else 0
    return best, stops, low_total + end_leg, high_total + end_leg, end_leg, notes


def route(start_lat, start_lon, place_ids, mode="walk", time_budget_min=None, at_time=None, end_lat=None, end_lon=None):
    start = rounded(start_lat, start_lon)
    end = rounded(end_lat, end_lon) if end_lat is not None and end_lon is not None else None
    mode = mode if mode in MODES else "walk"
    places = [BY_ID[i] for i in dict.fromkeys(place_ids) if i in BY_ID][:5]
    missing = [i for i in place_ids if i not in BY_ID]
    if not places:
        return {"error": "Ни один id не найден в базе. Сначала вызовите search_places.", "missing_ids": missing}
    budget = int(time_budget_min) if time_budget_min else None
    when = local_time(at_time)
    dropped = []
    best, stops, low_total, high_total, end_leg, notes = plan_stops(start, places, end, mode, when)
    while budget and low_total > budget and len(places) > 1:
        dropped.append(places.pop()["name"])
        best, stops, low_total, high_total, end_leg, notes = plan_stops(start, places, end, mode, when)
    if dropped:
        notes.append("Чтобы уложиться во время, убраны точки с меньшим приоритетом: " + ", ".join(dropped) + ".")
    if budget and low_total > budget:
        notes.append("Даже одна точка не укладывается во время, предложите место ближе.")
    elif budget and high_total > budget:
        notes.append("Уложитесь, если не задерживаться в каждой точке.")
    sky = weather(*start, when)
    return {
        "data_used": {
            "start": f"{start[0]:.3f}, {start[1]:.3f} (округлено примерно до 100 м, не сохраняется)",
            "end_point": f"{end[0]:.3f}, {end[1]:.3f}" if end else None,
            "time": when.strftime("%Y-%m-%d %H:%M") + " (Астана, UTC+5)", "mode": MODES[mode]["label"],
            "travel_estimate": "по прямой с поправкой на улицы, без учёта пробок и светофоров",
        },
        "stops": stops,
        "end_leg_min": end_leg if end else None,
        "total_min": f"{low_total}-{high_total}",
        "time_budget_min": budget,
        "fits_budget": low_total <= budget if budget else None,
        "finish_at": (when + timedelta(minutes=low_total)).strftime("%H:%M"),
        "map_link": maps_link(start, best, end, mode),
        "weather": sky["summary"] if sky else None,
        "missing_ids": missing or None,
        "notes": notes,
    }
