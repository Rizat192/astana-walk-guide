import os
import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

import places

CATEGORIES = (
    "cafe, restaurant, bar, nightclub, karaoke, cinema, theatre, arts_centre, library, coworking, museum, gallery, "
    "planetarium, attraction, viewpoint, monument, square, park, garden, playground, zoo, aquarium, theme_park, "
    "water_park, mall, ice_rink, bowling, escape_game, arcade, trampoline_park, worship"
)
FEATURES = "coffee, wifi, outdoor_seating, kids, vegetarian, halal, 24_7, takeaway, free, paid, lit"

mcp = MCPServer(
    "astana-places",
    instructions="Places database of Astana built from OpenStreetMap, Wikidata and Wikipedia. "
                 "Coordinates are rounded to about 100 m and are not stored.",
    log_level="WARNING",
)


@mcp.tool()
def locate(
    place: Annotated[str, Field(description="Landmark, mall, station or address the user mentioned, "
                                            "e.g. 'Mega Silk Way', 'Байтерек', 'вокзал Нурлы Жол', 'улица Кенесары 40'")],
) -> dict:
    """Turn a place name or address in Astana into approximate coordinates (rounded to about 100 m).
    Use it when the user says where they are instead of sharing exact coordinates."""
    return places.locate(place)


@mcp.tool()
def search_places(
    place: Annotated[str | None, Field(description="Where the user is, as they said it: landmark, mall, station or "
                                                   "address. Use it instead of lat and lon")] = None,
    lat: Annotated[float | None, Field(description="Latitude of the user, if they shared coordinates")] = None,
    lon: Annotated[float | None, Field(description="Longitude of the user, if they shared coordinates")] = None,
    time_budget_min: Annotated[int, Field(description="All free time in minutes, travel included")] = 60,
    categories: Annotated[list[str] | None, Field(description=f"Place types to include, any of: {CATEGORIES}")] = None,
    keywords: Annotated[list[str] | None, Field(description="Words to look for in names and descriptions")] = None,
    features: Annotated[list[str] | None, Field(description=f"Preferred features, any of: {FEATURES}")] = None,
    mode: Annotated[Literal["walk", "car"], Field(description="walk, or car for taxi")] = "walk",
    open_now_only: Annotated[bool, Field(description="Drop places known to be closed on arrival")] = False,
    indoor_only: Annotated[bool, Field(description="Only indoor places")] = False,
    wheelchair: Annotated[bool, Field(description="User needs step-free access for a wheelchair or stroller")] = False,
    at_time: Annotated[str | None, Field(description="Start time 'HH:MM' or ISO datetime in Astana time, empty means now")] = None,
    end_lat: Annotated[float | None, Field(description="Latitude of the place the user must reach at the end, e.g. the airport")] = None,
    end_lon: Annotated[float | None, Field(description="Longitude of that end place")] = None,
    end_place: Annotated[str | None, Field(description="Name of the place the user must reach at the end, "
                                                       "e.g. 'аэропорт'. Use it instead of end_lat and end_lon")] = None,
    with_route: Annotated[bool, Field(description="Also build a micro-route through the best 2-3 places")] = False,
    limit: Annotated[int, Field(description="How many places to return")] = 8,
) -> dict:
    """Search the Astana places database near the user, in one call.
    Finds the user's place by name, then for each place computes distance, travel time, whether the visit fits
    the time budget, opening status on arrival with a confidence level, plus weather and darkness at that time.
    With with_route=true it also returns a ready micro-route with arrival times and a map link.
    Only places returned here may be recommended as facts."""
    return places.search(lat, lon, time_budget_min, categories, keywords, features, mode, open_now_only,
                         indoor_only, wheelchair, at_time, end_lat, end_lon, limit, place, end_place, with_route)


@mcp.tool()
def plan_route(
    start_lat: Annotated[float, Field(description="Latitude of the start point")],
    start_lon: Annotated[float, Field(description="Longitude of the start point")],
    place_ids: Annotated[list[str], Field(description="2-4 ids from search_places, most wanted first")],
    mode: Annotated[Literal["walk", "car"], Field(description="walk, or car for taxi")] = "walk",
    time_budget_min: Annotated[int | None, Field(description="All free time in minutes, travel included")] = None,
    at_time: Annotated[str | None, Field(description="Start time 'HH:MM' or ISO datetime in Astana time, empty means now")] = None,
    end_lat: Annotated[float | None, Field(description="Latitude of the final point, if the user must end somewhere")] = None,
    end_lon: Annotated[float | None, Field(description="Longitude of the final point")] = None,
) -> dict:
    """Build a micro-route through places found by search_places.
    Picks the fastest order, gives arrival times, opening status on arrival and a map link.
    If the route does not fit the time budget, the least wanted places are dropped."""
    return places.route(start_lat, start_lon, place_ids, mode, time_budget_min, at_time, end_lat, end_lon)


if __name__ == "__main__" and "--stdio" in sys.argv:
    mcp.run()
elif __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
    )
