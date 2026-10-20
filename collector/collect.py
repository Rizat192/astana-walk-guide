import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BBOX = (50.98, 71.20, 51.30, 71.75)
CENTER = (51.13, 71.43)
RADIUS_KM = 22
UA = "AstanaWalkAssistant/0.1 (GDG Build with AI hackathon)"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

QUERY = """
[out:json][timeout:300][bbox:{0},{1},{2},{3}];
(
  nwr["amenity"~"^(cafe|restaurant|bar|pub|nightclub|karaoke_box|cinema|theatre|arts_centre|library|planetarium|coworking_space)$"];
  nwr["tourism"~"^(museum|gallery|attraction|viewpoint|zoo|aquarium|theme_park)$"];
  nwr["leisure"~"^(park|garden|playground|water_park|ice_rink|bowling_alley|escape_game|amusement_arcade|trampoline_park)$"];
  nwr["shop"="mall"];
  nwr["office"="coworking"];
  nwr["historic"~"^(monument|memorial)$"]["name"];
  nwr["tourism"="artwork"]["name"];
  nwr["amenity"="place_of_worship"]["wikidata"];
);
out center;
"""

SPARQL = """
SELECT DISTINCT ?item ?itemLabel ?coord ?typeEn ?ended WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius}" .
  }}
  ?article schema:about ?item ; schema:isPartOf ?wiki .
  FILTER(?wiki IN (<https://ru.wikipedia.org/>, <https://en.wikipedia.org/>))
  OPTIONAL {{ ?item wdt:P576|wdt:P3999 ?ended . }}
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeEn . FILTER(LANG(?typeEn) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en,kk". }}
}}
"""

RULES = [
    ("tourism", {"museum"}, "museum"),
    ("tourism", {"gallery"}, "gallery"),
    ("amenity", {"planetarium"}, "planetarium"),
    ("tourism", {"zoo"}, "zoo"),
    ("tourism", {"aquarium"}, "aquarium"),
    ("tourism", {"theme_park"}, "theme_park"),
    ("leisure", {"water_park"}, "water_park"),
    ("tourism", {"viewpoint"}, "viewpoint"),
    ("amenity", {"theatre"}, "theatre"),
    ("amenity", {"cinema"}, "cinema"),
    ("amenity", {"arts_centre"}, "arts_centre"),
    ("amenity", {"library"}, "library"),
    ("amenity", {"coworking_space"}, "coworking"),
    ("office", {"coworking"}, "coworking"),
    ("amenity", {"nightclub"}, "nightclub"),
    ("amenity", {"karaoke_box"}, "karaoke"),
    ("amenity", {"bar", "pub"}, "bar"),
    ("amenity", {"cafe"}, "cafe"),
    ("amenity", {"restaurant"}, "restaurant"),
    ("shop", {"mall"}, "mall"),
    ("leisure", {"ice_rink"}, "ice_rink"),
    ("leisure", {"bowling_alley"}, "bowling"),
    ("leisure", {"escape_game"}, "escape_game"),
    ("leisure", {"amusement_arcade"}, "arcade"),
    ("leisure", {"trampoline_park"}, "trampoline_park"),
    ("leisure", {"park"}, "park"),
    ("leisure", {"garden"}, "garden"),
    ("leisure", {"playground"}, "playground"),
    ("amenity", {"place_of_worship"}, "worship"),
    ("historic", {"monument", "memorial"}, "monument"),
    ("tourism", {"artwork"}, "monument"),
    ("tourism", {"attraction"}, "attraction"),
]

WD_TYPES = [
    ("museum", "museum"), ("gallery", "gallery"), ("planetarium", "planetarium"),
    ("aquarium", "aquarium"), ("oceanarium", "aquarium"), ("zoo", "zoo"),
    ("water park", "water_park"), ("amusement park", "theme_park"), ("theme park", "theme_park"),
    ("opera", "theatre"), ("theatre", "theatre"), ("theater", "theatre"), ("circus", "theatre"),
    ("concert hall", "arts_centre"), ("philharmonic", "arts_centre"), ("cultural center", "arts_centre"),
    ("library", "library"), ("cinema", "cinema"),
    ("mosque", "worship"), ("church", "worship"), ("cathedral", "worship"), ("synagogue", "worship"),
    ("temple", "worship"), ("shopping", "mall"), ("park", "park"), ("garden", "garden"),
    ("square", "square"), ("boulevard", "square"), ("pedestrian", "square"), ("promenade", "square"),
    ("embankment", "square"), ("monument", "monument"), ("memorial", "monument"), ("statue", "monument"),
    ("sculpture", "monument"), ("tower", "attraction"), ("palace", "attraction"), ("pyramid", "attraction"),
    ("château", "attraction"), ("official residence", "attraction"), ("world's fair", "attraction"),
    ("children's railway", "attraction"), ("skyscraper", "attraction"), ("bridge", "attraction"),
    ("ice rink", "ice_rink"), ("stadium", "attraction"), ("arena", "attraction"), ("exhibition", "attraction"),
    ("tourist attraction", "attraction"), ("landmark", "attraction"), ("building", "attraction"),
]
WD_SKIP = (
    "kindergarten", "industrial", "business", "technology", "parking", "car park", "office", "residential",
    "school", "university", "hospital", "company", "embassy", "district", "village", "street", "road",
    "airport", "station", "hotel", "bank", "ministry", "government", "court", "water tower",
)
HUBS = {"international airport": "airport", "railway station": "railway_station", "bus station": "bus_station"}
HUB_PREFIX = {"airport": "Аэропорт", "railway_station": "Вокзал", "bus_station": "Автовокзал"}
CLOSED = re.compile(r"\b(находил(ась|ся)|существовал[аи]?|снес[её]н[аы]?|был[аи]? закрыт[аы]?|демонтирован[аы]?)\b")

LABELS = {
    "museum": "Музей", "gallery": "Галерея", "planetarium": "Планетарий", "zoo": "Зоопарк",
    "aquarium": "Океанариум", "theme_park": "Парк развлечений", "water_park": "Аквапарк",
    "viewpoint": "Смотровая площадка", "theatre": "Театр", "cinema": "Кинотеатр",
    "arts_centre": "Арт-центр", "library": "Библиотека", "coworking": "Коворкинг",
    "nightclub": "Ночной клуб", "karaoke": "Караоке", "bar": "Бар", "cafe": "Кафе",
    "restaurant": "Ресторан", "mall": "Торговый центр", "ice_rink": "Каток", "bowling": "Боулинг",
    "escape_game": "Квест-комната", "arcade": "Игровой зал", "trampoline_park": "Батутный центр",
    "park": "Парк", "garden": "Сад", "playground": "Детская площадка", "worship": "Религиозное место",
    "monument": "Памятник", "attraction": "Достопримечательность", "square": "Площадь или бульвар",
}
UNNAMED = {"playground": "Детская площадка", "park": "Сквер", "viewpoint": "Смотровая точка", "ice_rink": "Каток"}
INDOOR = {
    "museum", "gallery", "planetarium", "aquarium", "water_park", "theatre", "cinema", "arts_centre",
    "library", "coworking", "nightclub", "karaoke", "bar", "cafe", "restaurant", "mall", "bowling",
    "escape_game", "arcade", "trampoline_park", "worship",
}
OUTDOOR = {"zoo", "theme_park", "viewpoint", "park", "garden", "playground", "monument", "square"}
BIG = {"mall", "park", "garden", "square", "zoo", "theme_park", "water_park"}
RELIGION = {"muslim": "Мечеть", "christian": "Храм", "jewish": "Синагога", "buddhist": "Буддийский храм"}
MUSEUM = {
    "history": "исторический", "art": "художественный", "local": "краеведческий", "military": "военный",
    "science": "научный", "technology": "технический", "children": "детский", "nature": "природный",
    "railway": "железнодорожный", "archaeological": "археологический", "ethnography": "этнографический",
    "memorial": "мемориальный", "music": "музыкальный",
}
CUISINE = {
    "coffee_shop": "кофейня", "kazakh": "казахская кухня", "italian": "итальянская кухня",
    "japanese": "японская кухня", "sushi": "суши", "pizza": "пицца", "burger": "бургеры",
    "asian": "азиатская кухня", "uzbek": "узбекская кухня", "georgian": "грузинская кухня",
    "turkish": "турецкая кухня", "european": "европейская кухня", "russian": "русская кухня",
    "chinese": "китайская кухня", "korean": "корейская кухня", "steak_house": "стейки",
    "seafood": "морепродукты", "dessert": "десерты", "cake": "торты", "ice_cream": "мороженое",
    "tea": "чай", "breakfast": "завтраки", "international": "интернациональная кухня",
    "regional": "местная кухня", "shawarma": "шаурма", "kebab": "кебаб", "bakery": "выпечка",
    "american": "американская кухня", "french": "французская кухня", "indian": "индийская кухня",
    "uyghur": "уйгурская кухня", "arab": "арабская кухня", "grill": "гриль", "bubble_tea": "бабл-ти",
}
FEATURE_TEXT = {
    "wifi": "есть Wi-Fi", "outdoor_seating": "летняя веранда", "kids": "есть детская зона",
    "vegetarian": "есть вегетарианское меню", "halal": "халяль", "24_7": "работает круглосуточно",
    "takeaway": "можно взять с собой", "free": "вход свободный", "paid": "вход платный", "lit": "есть освещение",
}
WHEELCHAIR = {"yes": "доступно на коляске", "limited": "частично доступно на коляске", "no": "на коляске недоступно"}
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
})


def http_json(url, params=None, data=None, tries=3):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=400) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(10 * (attempt + 1))


def fetch_osm():
    query = QUERY.format(*BBOX)
    for url in OVERPASS:
        try:
            res = http_json(url, data={"data": query}, tries=2)
            if "runtime error" in res.get("remark", ""):
                raise RuntimeError(res["remark"])
            print(f"overpass ok: {url}, elements: {len(res['elements'])}")
            return res["elements"]
        except Exception as e:
            print(f"overpass failed: {url}: {e}")
    sys.exit("all overpass servers failed")


def category_of(tags):
    return next((cat for key, values, cat in RULES if tags.get(key) in values), None)


def features_of(tags, name):
    low = name.lower()
    checks = {
        "coffee": "coffee" in tags.get("cuisine", "") or "coffee" in low or "кофе" in low,
        "wifi": tags.get("internet_access") in {"wlan", "yes", "wifi"},
        "outdoor_seating": tags.get("outdoor_seating") == "yes",
        "kids": tags.get("kids_area") == "yes" or tags.get("changing_table") == "yes",
        "vegetarian": tags.get("diet:vegetarian") in {"yes", "only"},
        "halal": tags.get("diet:halal") in {"yes", "only"},
        "24_7": tags.get("opening_hours") == "24/7",
        "takeaway": tags.get("takeaway") in {"yes", "only"},
        "free": tags.get("fee") == "no",
        "paid": tags.get("fee") == "yes",
        "lit": tags.get("lit") == "yes",
    }
    return [key for key, ok in checks.items() if ok]


def indoor_of(cat, tags):
    if cat in INDOOR or tags.get("indoor") == "yes" or tags.get("covered") == "yes" or "building" in tags:
        return True
    return False if cat in OUTDOOR else None


def address_of(tags):
    street, house = tags.get("addr:street"), tags.get("addr:housenumber")
    return f"{street}, {house}" if street and house else street


def tag_description(cat, tags, feats):
    label = LABELS[cat]
    if cat == "worship":
        label = RELIGION.get(tags.get("religion"), label)
    if cat == "museum" and tags.get("museum") in MUSEUM:
        label = f"{MUSEUM[tags['museum']]} музей"
    parts = [label]
    kinds = [CUISINE[c.strip()] for c in tags.get("cuisine", "").split(";") if c.strip() in CUISINE]
    if kinds:
        parts.append(", ".join(dict.fromkeys(kinds)))
    extra = [FEATURE_TEXT[f] for f in feats if f in FEATURE_TEXT and not (f == "kids" and cat == "playground")]
    if tags.get("wheelchair") in WHEELCHAIR:
        extra.append(WHEELCHAIR[tags["wheelchair"]])
    if extra:
        parts.append(", ".join(extra))
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def make_poi(pid, source, url, name, cat, lat, lon, **fields):
    poi = {
        "id": pid, "source": source, "source_url": url, "name": name, "names": {}, "named": True,
        "category": cat, "category_ru": LABELS[cat], "lat": round(lat, 6), "lon": round(lon, 6),
        "features": [], "indoor": indoor_of(cat, {}), "opening_hours": None, "hours_checked": None,
        "wheelchair": None, "address": None, "phone": None, "website": None,
        "description": f"{LABELS[cat]}.", "description_source": "tags", "description_url": None,
        "wikidata": None, "wikipedia": None, "wiki_views_60d": None, "possibly_closed": False, "_richness": 0,
    }
    poi.update(fields)
    return poi


def normalize(el):
    tags = el.get("tags", {})
    cat = category_of(tags)
    if not cat or tags.get("access") in {"private", "no"} or tags.get("opening_hours") in {"closed", "off"}:
        return None
    real_name = tags.get("name:ru") or tags.get("name") or tags.get("brand") or tags.get("name:en") or tags.get("name:kk")
    if not real_name and cat not in UNNAMED:
        return None
    center = el.get("center", {})
    lat, lon = el.get("lat", center.get("lat")), el.get("lon", center.get("lon"))
    if lat is None or lon is None:
        return None
    name = real_name or UNNAMED[cat]
    feats = features_of(tags, name)
    osm_desc = tags.get("description:ru") or tags.get("description")
    wikidata = tags.get("wikidata", "")
    return make_poi(
        f"osm:{el['type']}/{el['id']}", "OpenStreetMap", f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        name, cat, lat, lon,
        names={k: tags[f"name:{k}"] for k in ("ru", "kk", "en") if tags.get(f"name:{k}")},
        named=bool(real_name),
        features=feats,
        indoor=indoor_of(cat, tags),
        opening_hours=tags.get("opening_hours"),
        hours_checked=tags.get("check_date:opening_hours") or tags.get("check_date"),
        wheelchair=tags.get("wheelchair") if tags.get("wheelchair") in WHEELCHAIR else None,
        address=address_of(tags),
        phone=tags.get("phone") or tags.get("contact:phone"),
        website=tags.get("website") or tags.get("contact:website") or tags.get("contact:instagram"),
        description=osm_desc or tag_description(cat, tags, feats),
        description_source="osm" if osm_desc else "tags",
        wikidata=wikidata if re.fullmatch(r"Q\d+", wikidata) else None,
        wikipedia=tags.get("wikipedia"),
        _richness=len(tags),
    )


def dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def near(a, b, meters):
    if abs(a["lat"] - b["lat"]) > meters / 100000 or abs(a["lon"] - b["lon"]) > meters / 60000:
        return False
    return dist_m(a["lat"], a["lon"], b["lat"], b["lon"]) < meters


def name_key(name):
    return re.sub(r"\W+", "", name.lower().translate(TRANSLIT))


def same_name(a, b):
    a, b = name_key(a), name_key(b)
    if not a or not b or set(re.findall(r"\d", a)) != set(re.findall(r"\d", b)):
        return False
    shorter, longer = sorted((a, b), key=len)
    return (len(shorter) >= 5 and shorter in longer) or SequenceMatcher(None, a, b).ratio() >= 0.7


def dedup(pois):
    kept = []
    for p in sorted(pois, key=lambda x: -x["_richness"]):
        radius = 300 if p["category"] in BIG else 80
        duplicate = p["named"] and any(
            k["named"] and k["category"] == p["category"] and near(p, k, radius) and same_name(p["name"], k["name"])
            for k in kept
        )
        if not duplicate:
            kept.append(p)
    return kept


def wd_category(types):
    labels = [t for t in types if not any(s in t for s in WD_SKIP)]
    return next((cat for key, cat in WD_TYPES if any(key in t for t in labels)), None)


def fetch_wikidata():
    query = SPARQL.format(lat=CENTER[0], lon=CENTER[1], radius=RADIUS_KM)
    res = http_json("https://query.wikidata.org/sparql", params={"query": query, "format": "json"})
    items = {}
    for row in res["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        lon, lat = map(float, re.findall(r"-?\d+(?:\.\d+)?", row["coord"]["value"])[:2])
        item = items.setdefault(qid, {"name": row["itemLabel"]["value"], "lat": lat, "lon": lon, "types": [], "ended": False})
        if "typeEn" in row:
            item["types"].append(row["typeEn"]["value"].lower())
        if "ended" in row:
            item["ended"] = True
    found, anchors = {}, []
    for qid, item in items.items():
        name = re.sub(r"\s*\([^)]*\)", "", item["name"]).strip()
        if item["name"] == qid:
            continue
        kind = next((HUBS[t] for t in item["types"] if t in HUBS), None)
        prefix = HUB_PREFIX.get(kind, "")
        anchors.append({
            "id": f"wikidata:{qid}", "name": name if prefix.lower() in name.lower() else f"{prefix} {name}",
            "kind": kind or "place", "lat": round(item["lat"], 6), "lon": round(item["lon"], 6),
        })
        cat = None if kind or item["ended"] else wd_category(item["types"])
        if cat:
            found[qid] = {**item, "name": name, "category": cat}
    return found, anchors


def merge_wikidata(pois, items):
    known = {p["wikidata"] for p in pois if p["wikidata"]}
    matched = added = 0
    for qid, item in items.items():
        if qid in known:
            continue
        radius = 800 if item["category"] in BIG else 200
        match = next((
            p for p in pois
            if p["named"] and near(p, item, radius) and any(same_name(n, item["name"]) for n in [p["name"], *p["names"].values()])
        ), None)
        if match:
            match["wikidata"] = match["wikidata"] or qid
            matched += 1
        else:
            pois.append(make_poi(
                f"wikidata:{qid}", "Wikidata", f"https://www.wikidata.org/wiki/{qid}",
                item["name"], item["category"], item["lat"], item["lon"], wikidata=qid,
            ))
            added += 1
    print(f"wikidata: {len(items)} items, matched {matched}, added {added}")


def short_text(text, limit=320):
    text = re.sub(r"\s*\([^()]*\)", "", re.sub(r"\s+", " ", text.replace("́", ""))).strip()
    if not text:
        return ""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    return out or text[:limit].rsplit(" ", 1)[0] + "…"


def wiki_links(qids):
    links = {}
    for i in range(0, len(qids), 50):
        res = http_json("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "sitelinks",
            "sitefilter": "ruwiki|enwiki|kkwiki", "format": "json",
        })
        for qid, ent in res.get("entities", {}).items():
            site = next((s for s in ("ruwiki", "enwiki", "kkwiki") if s in ent.get("sitelinks", {})), None)
            if site:
                for key in {qid, ent.get("redirects", {}).get("from")} - {None}:
                    links[key] = (site[:2], ent["sitelinks"][site]["title"])
        time.sleep(1)
    return links


def enrich_wiki(pois):
    links = wiki_links(sorted({p["wikidata"] for p in pois if p["wikidata"]}))
    targets = {}
    for p in pois:
        article = links.get(p["wikidata"])
        tag = re.match(r"^([a-z]{2,3}):(.+)$", p["wikipedia"] or "")
        if not article and tag:
            article = (tag.group(1), tag.group(2))
        if article:
            targets.setdefault(article[0], {}).setdefault(article[1], []).append(p)
    for lang, titles in targets.items():
        names = list(titles)
        for i in range(0, len(names), 20):
            batch = names[i:i + 20]
            res = http_json(f"https://{lang}.wikipedia.org/w/api.php", params={
                "action": "query", "prop": "extracts|pageviews", "exintro": 1, "explaintext": 1,
                "exlimit": "max", "titles": "|".join(batch), "redirects": 1, "format": "json", "formatversion": 2,
            })
            query = res.get("query", {})
            moved = {x["from"]: x["to"] for x in query.get("normalized", []) + query.get("redirects", [])}
            pages = {page["title"]: page for page in query.get("pages", [])}
            for title in batch:
                final = moved.get(title, title)
                final = moved.get(final, final)
                page = pages.get(final)
                if not page or page.get("missing"):
                    continue
                views = page.get("pageviews")
                text = short_text(page.get("extract", ""))
                for p in titles[title]:
                    p["wiki_views_60d"] = sum(v for v in views.values() if v) if views else None
                    if text:
                        p["possibly_closed"] = bool(CLOSED.search(text.lower()))
                        p["description"] = text
                        p["description_source"] = "wikipedia"
                        p["description_url"] = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(final.replace(' ', '_'))}"
            time.sleep(1)


def pct(pois, test):
    return round(100 * sum(1 for p in pois if test(p)) / max(len(pois), 1), 1)


def save(pois, anchors):
    DATA.mkdir(exist_ok=True)
    for p in pois:
        p.pop("_richness", None)
    pois.sort(key=lambda p: (p["category"], p["name"]))
    (DATA / "poi.json").write_text(json.dumps(pois, ensure_ascii=False, indent=1), encoding="utf-8")
    if anchors:
        anchors.sort(key=lambda a: a["name"])
        (DATA / "anchors.json").write_text(json.dumps(anchors, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["id", "name", "category", "lat", "lon", "opening_hours", "wheelchair", "indoor", "features",
            "address", "phone", "website", "description", "description_source", "wiki_views_60d",
            "possibly_closed", "source", "source_url"]
    with open(DATA / "poi.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows([";".join(p[c]) if c == "features" else p[c] for c in cols] for p in pois)
    meta = {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": dict(zip(("south", "west", "north", "east"), BBOX)),
        "total": len(pois),
        "anchors": len(anchors),
        "by_source": dict(Counter(p["source"] for p in pois).most_common()),
        "by_category": dict(Counter(p["category"] for p in pois).most_common()),
        "coverage_pct": {
            "named": pct(pois, lambda p: p["named"]),
            "opening_hours": pct(pois, lambda p: p["opening_hours"]),
            "wheelchair": pct(pois, lambda p: p["wheelchair"]),
            "contacts": pct(pois, lambda p: p["phone"] or p["website"]),
            "description_wikipedia": pct(pois, lambda p: p["description_source"] == "wikipedia"),
            "description_osm": pct(pois, lambda p: p["description_source"] == "osm"),
            "description_from_tags": pct(pois, lambda p: p["description_source"] == "tags"),
            "possibly_closed": pct(pois, lambda p: p["possibly_closed"]),
        },
        "sources": [
            {"name": "OpenStreetMap via Overpass API", "license": "ODbL 1.0", "attribution": "© OpenStreetMap contributors"},
            {"name": "Wikidata", "license": "CC0 1.0"},
            {"name": "Wikipedia", "license": "CC BY-SA 4.0"},
        ],
    }
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def main():
    pois = dedup([p for p in map(normalize, fetch_osm()) if p])
    anchors = []
    try:
        items, anchors = fetch_wikidata()
        merge_wikidata(pois, items)
    except Exception as e:
        print(f"wikidata skipped: {e}")
    try:
        enrich_wiki(pois)
    except Exception as e:
        print(f"wiki enrichment skipped: {e}")
    meta = save(pois, anchors)
    print(f"saved {meta['total']} places and {len(anchors)} location anchors to data/")
    for key, value in {**meta["by_source"], **meta["by_category"]}.items():
        print(f"  {key}: {value}")
    for key, value in meta["coverage_pct"].items():
        print(f"  {key}: {value}%")


if __name__ == "__main__":
    main()
