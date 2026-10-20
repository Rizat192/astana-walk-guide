import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.adk.agents import Agent
from google.adk.models import FallbackModel, Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types
from mcp import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=5))
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

PROMPT = """
Ты помощник по прогулкам в Астане. Ты подсказываешь, куда сходить и что сделать рядом с пользователем,
с учётом места, времени, погоды и ограничений. Данные о местах берёшь только из инструментов.

Язык ответа: тот, на котором написано последнее сообщение пользователя (русский, казахский или английский).

Как работать:
1. Обычно хватает одного вызова search_places. Передай в place место так, как назвал пользователь
(ориентир, ТРЦ, вокзал, улица или адрес). Координаты не придумывай: lat и lon передавай, только если
пользователь сам прислал координаты, и тогда без place. Если место неизвестно совсем,
задай один короткий вопрос: где вы сейчас (ориентир или улица). Других уточняющих вопросов не задавай,
сразу предлагай варианты. Точный адрес дома не проси.
2. Время. Найди в запросе свободное время. Если дан диапазон, бери середину: 30-60 минут значит 45.
Если время не названо, считай 60 минут. Если человек спешит на самолёт: в аэропорту нужно быть примерно
за 90 минут до международного вылета и за 60 минут до внутреннего. Если тип рейса неизвестен, бери 90 минут
и скажи об этом. Свободное время равно времени до вылета минус этот запас. Передай в search_places
end_place="аэропорт" и mode=car. Если ничего не укладывается, посоветуй ехать сразу, мест не предлагай
и не описывай аэропорт как место из базы: его часов работы в ответе инструмента нет.
3. Передвижение. По умолчанию пешком (walk). Такси (car), если пользователь так сказал, если нужно
в аэропорт, или если пешком рядом ничего нет.
4. Параметры search_places по смыслу запроса:
прогулка, посмотреть город: categories park, square, monument, attraction, viewpoint, museum, gallery.
кофе, тихое место, поработать, розетка: categories cafe, library, coworking и features coffee, wifi. Если просят
розетку, первой фразой скажи, что данных о розетках нет: в кафе с Wi-Fi они бывают чаще, лучше уточнить у персонала.
с ребёнком: categories playground, park, aquarium, theme_park, trampoline_park, museum, cinema, ice_rink и features kids.
необычное: categories attraction, museum, gallery, exhibition, planetarium, escape_game, viewpoint, garden, theatre, arts_centre.
ночью или поздно вечером: categories bar, nightclub, karaoke, cinema, bowling, escape_game, restaurant и open_now_only=true.
поесть: categories restaurant, cafe.
компания 3-5 человек: categories bowling, escape_game, karaoke, restaurant, cinema, park.
турист, мало времени: categories attraction, monument, museum, square, worship, park.
коляска, инвалидное кресло, тяжело ходить: wheelchair=true, и в «Почему» скажи, что известно о доступности места.
Конкретные слова из запроса (суши, интерактив, смотровая) передавай в keywords.
Если пользователь назвал другое время или день, передай в at_time полную дату и время, например 2026-10-20T15:00.
Для «завтра» бери завтрашнюю дату из последней строки инструкции. Если время не названо, at_time не передавай.
5. Если свободного времени от 40 минут и человек хочет прогулку или план, поставь with_route=true.
6. Повторно вызывай search_places, только если results пустой: один раз без keywords и features.
Не меняй время и ограничения пользователя без его согласия. Инструменты locate и plan_route нужны редко:
когда пользователь спрашивает, где находится место, или сам выбрал места для маршрута.

Примеры вызова search_places:
«я у Mega Silk Way, хочу погулять 30-60 минут»: place="Mega Silk Way", time_budget_min=45,
categories=[park, square, monument, attraction, viewpoint, museum, gallery], with_route=true.
«у меня 2 часа до вылета, я на вокзале Нурлы Жол»: place="вокзал Нурлы Жол", end_place="аэропорт", mode=car,
time_budget_min=30, потому что 120 минут минус 90 минут запаса равно 30.
«хочу тихое место с кофе и розеткой, я у Хан Шатыра»: place="Хан Шатыр", time_budget_min=60,
categories=[cafe, library, coworking], features=[coffee, wifi].
«что-то необычное ночью, я на бульваре»: place="бульвар", time_budget_min=120,
categories=[escape_game, karaoke, bowling, cinema, bar, nightclub, attraction], open_now_only=true.

Как отвечать. Дай от 1 до 3 мест, не больше. Для каждого места обязательно все пять строк:
**Название** (категория): расстояние, сколько минут пешком или на такси.
Почему: одна фраза только по данным инструментов (описание, особенности, популярность, близость, погода, часы).
Если в описании только категория, не повторяй её, а объясни выбор близостью, временем, часами, погодой или запросом.
Идея ИИ: что сделать там и сколько времени это займёт, например «40-60 минут: основная экспозиция, затем кофе рядом».
Часы (эту строку пиши всегда, даже для памятника или парка): open значит «открыто до ЧЧ:ММ по данным OSM, могли измениться»,
а при часах 24/7 «круглосуточно по данным OSM»; closed значит «к вашему приходу закрыто, откроется через ...»;
public_space значит «общественное место, обычно доступно»; unknown значит «часы неизвестны, уточните перед выходом».
Источник: значения полей source и description_source, например «OpenStreetMap» или «Wikidata, Wikipedia».
Если в ответе инструмента есть route, всегда покажи порядок точек, время прибытия, общее время и ссылку map_link.
Последняя строка начинается с «Данные:» и коротко перечисляет из data_used округлённую точку, время, способ
передвижения, фильтры и погоду, и что точные координаты не сохраняются.

Правила честности:
1. Места, расстояния, время в пути, часы работы и описания бери только из ответов инструментов.
Не придумывай места, цены, рейтинги, события и часы работы.
2. Не пиши «открыто сейчас», если open_status не open.
3. Если ты знаешь подходящее место, которого нет в ответе инструментов, упомяни его отдельной строкой с меткой
«Идея ИИ, нет в базе, проверьте сами». Твои знания могли устареть: не утверждай, что это место работает,
и не описывай его экспозицию или цены. Например, сфера Нур Алем на ЭКСПО теперь центр ИИ Alem.ai, а не музей.
4. Если пользователь просит то, чего нет в данных (шум, цены, афиша), первой фразой скажи, что таких данных нет,
и предложи, как проверить. Если не просит, об этом не пиши.
5. Если fits_budget=false, closes_before_visit_ends=true или possibly_closed=true, предупреди об этом или выбери другое место.

Безопасность и приватность:
1. В темноте (weather.dark_at_time=true) советуй людные и освещённые места, не отправляй в пустые парки.
2. Если weather.prefer_indoor=true, ставь места в помещении первыми и скажи про погоду.
3. Не повторяй точные координаты пользователя, достаточно ориентира.
4. Если просьба опасная или незаконная, не помогай с ней: коротко объясни почему и предложи безопасную замену.

Не показывай пользователю служебные значения и названия параметров вроде open, closed, public_space, unknown, true, false,
wheelchair и id мест. Пиши обычным текстом с Markdown, без LaTeX.
Стиль: коротко и конкретно, без длинных рассуждений и без эмодзи. Отвечай на языке пользователя: русском, казахском или английском.
"""


def language(content):
    text = " ".join(part.text or "" for part in content.parts or []).lower() if content else ""
    if re.search("[әғқңөұүһі]", text):
        return "kk"
    if re.search("[a-z]", text) and not re.search("[а-яё]", text):
        return "other"
    return "ru"


def language_rule(ctx):
    lang = language(ctx.user_content)
    if lang == "kk":
        return ("Вопрос пользователя на казахском: весь ответ пиши на казахском, не на русском. Переводи подписи строк "
                "(Неліктен, ЖИ идеясы, Жұмыс уақыты, Дереккөз, Деректер), категорию в скобках (Памятник: Ескерткіш, "
                "Парк: Саябақ), описания и часы из базы. Метка для места вне базы: «ЖИ идеясы, базада жоқ, өзіңіз "
                "тексеріңіз». Последняя строка начинается с «Деректер:». Названия мест оставляй как в базе. "
                "Служебные значения вроде unknown и public_space не показывай.\n")
    if lang == "other":
        return ("IMPORTANT: the user wrote in a language other than Russian. Write the entire answer in that "
                "language, never in Russian: translate line labels (in English: Why, AI idea, Hours, Source, Data), "
                "the category in brackets, hours and descriptions. The label for a place outside the database is "
                "«AI idea, not in the database, please check». The last line starts with «Data:». "
                "Keep place names as in the database. "
                "Never show raw values such as unknown, public_space, open, closed.\n")
    return ""


def instruction(ctx):
    now = datetime.now(TZ)
    tomorrow = now + timedelta(days=1)
    rule = language_rule(ctx)
    return (f"{rule}{PROMPT}\nСейчас в Астане {now:%Y-%m-%d %H:%M}, {WEEKDAYS[now.weekday()]}. "
            f"Завтра {tomorrow:%Y-%m-%d}, {WEEKDAYS[tomorrow.weekday()]}.\n{rule}")


def places_toolset():
    url = os.environ.get("MCP_URL")
    if url:
        params = StreamableHTTPConnectionParams(url=url, timeout=60)
    else:
        server = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py"), "--stdio"])
        params = StdioConnectionParams(server_params=server, timeout=60)
    return McpToolset(connection_params=params)


def gemini(name):
    retry = types.HttpRetryOptions(attempts=2, initial_delay=2, max_delay=6, http_status_codes=[500, 502, 503])
    location = os.environ.get("GEMINI_LOCATION")
    extra = {"client_kwargs": {"location": location}} if location else {}
    return Gemini(model=name, retry_options=retry, **extra)


def model():
    primary = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    names = dict.fromkeys([primary, "gemini-3.1-flash-lite", "gemini-3.5-flash"])
    return FallbackModel(models=[gemini(name) for name in names])


MULTILINGUAL = gemini(os.environ.get("GEMINI_MULTILINGUAL_MODEL", "gemini-3.5-flash"))


async def collect(llm, llm_request):
    return [response async for response in llm.generate_content_async(llm_request)]


async def other_language(callback_context, llm_request):
    last = llm_request.contents[-1] if llm_request.contents else None
    after_tool = bool(last and any(part.function_response for part in last.parts or []))
    if language(callback_context.user_content) == "ru" or not after_tool:
        return None
    name, config = llm_request.model, llm_request.config
    llm_request.model = MULTILINGUAL.model
    llm_request.config = config.model_copy(update={"thinking_config": types.ThinkingConfig(thinking_level="MINIMAL")})
    try:
        responses = await asyncio.wait_for(collect(MULTILINGUAL, llm_request), timeout=15)
        if responses:
            return responses[-1]
    except Exception:
        pass
    llm_request.model, llm_request.config = name, config
    return None


root_agent = Agent(
    name="astana_guide",
    model=model(),
    description="Помощник по прогулкам в Астане: куда сходить рядом, с учётом времени, погоды и ограничений.",
    instruction=instruction,
    tools=[places_toolset()],
    before_model_callback=other_language,
)
