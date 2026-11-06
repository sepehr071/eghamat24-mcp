"""Eghamat24 extra tools: flight + hotel tours, tourist attractions, photos, similar hotels, special offers."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import http
from .hotels import (
    CheckIn,
    HotelRef,
    Nights,
    _card,
    _date,
    _deg,
    _locations,
    _norm,
    _property,
    _search,
    _text,
    _toman,
)
from .registry import tool

IMAGES = "https://www.eghamat24.com/app/public/hotel_images/original/"
Adults = Annotated[int, Field(ge=1, le=9, description="Adults travelling together (one room).")]
Origin = Annotated[str, Field(description="Departure city with flights (Tehran, Shiraz, Esfahan...), slug or Persian.")]


async def _city(text: str, need: str | None = None) -> dict[str, Any]:
    """The location row of a city by slug or Persian name; `need` is a row field that must be set (tours_uri...)."""
    want = _norm(text)
    cities = [x for x in await _locations() if x["type"] == "city"]
    hit = [x for x in cities if want in (_norm(x["name"]), _norm(x["english_name"] or ""))]
    pool = [x for x in cities if not need or x[need]]
    if not hit:
        near = [x["english_name"] for x in cities if want in _norm(x["name"] + " " + (x["english_name"] or ""))]
        raise ToolError(f"Unknown city {text!r}." + (f" Did you mean: {', '.join(near[:6])}?" if near else ""))
    if need and not hit[0][need]:
        raise ToolError(
            f"{hit[0]['name']} has no {need.split('_')[0]} on the site. Try: {', '.join(x['english_name'] for x in pool)}."
        )
    return hit[0]


def _star(v: Any) -> int | None:
    return int(v) if v and str(v).isdigit() else None


def _leg(t: dict[str, Any]) -> dict[str, Any]:
    """One flight direction: stops and the routes with airline, airports and times."""
    return {
        "stops": t["stops"],
        "flights": [
            {
                "airline": r["company"]["name"] if r.get("company") else None,
                "flight": r["carrier_number"],
                "from": r["origin_airport"]["iata"],
                "to": r["destination_airport"]["iata"],
                "departs": r["departure_time"][:16],
                "arrives": r["arriving_time"][:16],
                "class": r["carrier_class"],
                "ticket": r["carrier_ticket_type"],
            }
            for r in t["routes"]
        ],
    }


def _tour_params(origin: dict, dest: dict, start, nights: int, adults: int) -> dict[str, Any]:
    return {
        "origin_id": origin["id"],
        "destination_id": dest["id"],
        "check_in": start.isoformat(),
        "length_of_stay": nights,
        "rooms[0][adult_count]": adults,
    }


@tool("Flight and hotel tours")
async def eg_tours(
    city: Annotated[str, Field(description="Destination slug from eg_cities or Persian name.")],
    origin: Origin = "Tehran",
    check_in: CheckIn = None,
    nights: Nights = 2,
    adults: Adults = 2,
    hotel: Annotated[
        str | None,
        Field(description="`hotel` value of this tool or eg_search: list its packages."),
    ] = None,
    sort: Annotated[Literal["price", "rating", "stars"], Field(description="Hotel order.")] = "price",
    limit: Annotated[int, Field(ge=1, le=60)] = 15,
) -> dict[str, Any]:
    """Find flight-plus-hotel tour packages to a city, or the packages of one hotel with flight times.

    Without `hotel`: hotels with the cheapest package for all `adults` (`price_total`) and per person; with it: that
    hotel's packages (room, meal plan, flights). Prices Toman, flight included. Only some cities sell tours; empty
    means flights are full, try eg_tour_calendar.
    """
    dest, org = await _city(city, "tours_uri"), await _city(origin, "flights_uri")
    start = _date(check_in)
    q = _tour_params(org, dest, start, nights, adults)
    head = {"from": org["name"], "to": dest["name"], "check_in": start.isoformat(), "nights": nights, "adults": adults}
    if hotel:
        p = await _property(hotel)
        v = await http.fetch("/api/tours/v2/static/property/by-params", {**q, "property_id": p["id"]})
        packages = []
        for t in sorted(v["property_tours"], key=lambda t: t["price"]):
            room, plan = t["rooms"][0], t["rooms"][0]["rate_plan"]
            packages.append(
                {
                    "room": room["name"].strip(),
                    "sleeps": room["capacity"],
                    "extra_beds": room["extra_capacity"],
                    "plan": plan["name"].strip(),
                    "board": plan["board_type"],
                    "price_total": _toman(t["price"]),
                    "per_person": round(_toman(t["price"]) / adults),
                    "outbound": _leg(t["transportation"]["departure"]),
                    "return": _leg(t["transportation"]["return"]),
                }
            )
        return {
            **head,
            "hotel": p["full_name"],
            "found": len(packages),
            "currency": "Toman",
            "packages": packages[:limit],
        }
    v = await http.fetch("/api/tours/v2/static/city/by-params", q)
    keys = {"price": lambda h: h["min_price"], "rating": lambda h: -h["rating"], "stars": lambda h: -(h["star"] or 0)}
    rows = sorted(v["city_tours"], key=keys[sort])
    return {
        **head,
        "found": len(rows),
        "currency": "Toman",
        "hotels": [
            {
                "name": h["full_name"],
                "hotel": h["tour_uri"],
                "stars": _star(h["star"]),
                "rating": h["rating"] or None,
                "reviews": h["comment_count"],
                "price_total": _toman(h["min_price"]),
                "per_person": round(_toman(h["min_price"]) / adults),
                "price_up_to": _toman(h["max_price"]) if h["max_price"] != h["min_price"] else None,
                "address": h["address"],
            }
            for h in rows[:limit]
        ],
    }


@tool("Tour price calendar")
async def eg_tour_calendar(
    city: Annotated[str, Field(description="Destination slug or Persian name.")],
    origin: Origin = "Tehran",
    from_date: Annotated[str | None, Field(description="YYYY-MM-DD or Jalali. Default tomorrow.")] = None,
    nights: Nights = 2,
    adults: Adults = 2,
    days: Annotated[int, Field(ge=1, le=31, description="Departure days.")] = 14,
) -> dict[str, Any]:
    """Show the cheapest flight-plus-hotel package price per departure day.

    A missing day has no package. Prices Toman for all `adults` together. Hotels for one day: eg_tours.
    """
    dest, org = await _city(city, "tours_uri"), await _city(origin, "flights_uri")
    start = _date(from_date)
    v = await http.fetch(
        "/api/tours/v2/price-calendar",
        {k: x for k, x in _tour_params(org, dest, start, nights, adults).items() if k != "check_in"}
        | {"from_date": start.isoformat()},
    )
    end = (start + timedelta(days=days)).isoformat()
    rows = [
        {"depart": r["departure_date"], "return": r["return_date"], "price_total": _toman(r["price"])}
        for r in v["price_calendar"]
        if start.isoformat() <= r["departure_date"] < end
    ]
    cheapest = min(rows, key=lambda r: r["price_total"], default=None)
    return {
        "from": org["name"],
        "to": dest["name"],
        "nights": nights,
        "adults": adults,
        "currency": "Toman",
        "cheapest": cheapest,
        "days": rows,
    }


def _plain(html: Any, n: int = 900) -> str | None:
    return _text(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip(), n)


@tool("Tourist attractions")
async def eg_attractions(
    city: Annotated[str, Field(description="Slug or Persian name.")],
    query: Annotated[str | None, Field(description="Name part, Persian.")] = None,
    type: Annotated[str | None, Field(description="Type as in results, e.g. shopping_center.")] = None,
    attraction_id: Annotated[int | None, Field(description="Read this attraction (id from the list).")] = None,
    limit: Annotated[int, Field(ge=1, le=60)] = 20,
) -> dict[str, Any]:
    """List the sights, shrines, malls and other places of a city, or read one.

    An attraction's `id` feeds eg_search `attraction_id`. With `attraction_id` here: text, coordinates, type.
    """
    c = await _city(city)
    if attraction_id:
        a = (await http.fetch(f"/attractions/show/{attraction_id}"))["attraction"]
        if str(a["city_id"]) != str(c["id"]):
            raise ToolError(f"Attraction {attraction_id} is not in {c['name']}.")
        return {
            "id": a["id"],
            "city": c["english_name"],
            "name": a["name"],
            "type": a["type"],
            "lat": _deg(a["location"]["latitude"]),
            "lng": _deg(a["location"]["longitude"]),
            "description": _plain(a["description"], 1500),
            "hint": "Pass this id to eg_search as attraction_id to list hotels near it.",
        }
    rows = (await http.fetch(f"/attractions/get-by-city-id/{c['id']}"))["attractions"]
    types = sorted({a["type"] for a in rows})
    want = _norm(query) if query else None
    rows = [a for a in rows if (not type or a["type"] == type) and (not want or want in _norm(a["name"]))]
    rows.sort(key=lambda a: -a["priority"])
    return {
        "city": c["english_name"],
        "found": len(rows),
        "types": types,
        "attractions": [
            {
                "id": a["id"],
                "name": a["name"],
                "type": a["type"],
                "lat": _deg(a["location"]["latitude"]),
                "lng": _deg(a["location"]["longitude"]),
            }
            for a in rows[:limit]
        ],
    }


@tool("Hotel photos")
async def eg_photos(
    hotel: HotelRef,
    limit: Annotated[int, Field(ge=1, le=60)] = 20,
) -> dict[str, Any]:
    """List a hotel's photo URLs: main picture, gallery and each room type.

    URLs are full-size JPEGs.
    """
    p = await _property(hotel)
    files, types = await asyncio.gather(
        http.fetch(f"/properties/{p['id']}/files", {"order_by[0][name]": "priority", "order_by[0][type]": "asc"}),
        http.fetch(f"/properties/{p['id']}/room-types"),
    )
    names = {r["id"]: r["name"].strip() for r in types["room_types"]}
    shown = [f for f in files["property_files"] if f["published"] and f["is_gallery_visible"] and f["type"] == "jpg"]
    url = lambda f: IMAGES + f["name"]  # noqa: E731
    rooms: dict[str, list[str]] = {}
    for f in shown:
        if f["room_type_id"]:
            rooms.setdefault(names.get(f["room_type_id"], "room"), []).append(url(f))
    hotel_urls = [url(f) for f in shown if not f["room_type_id"]]
    main = next((url(f) for f in shown if f["is_main"]), hotel_urls[0] if hotel_urls else None)
    return {
        "name": p["full_name"],
        "hotel": p["uri"],
        "main": main,
        "hotel_photos": hotel_urls[:limit],
        "more_hotel_photos": max(0, len(hotel_urls) - limit),
        "room_photos": [{"room": r, "photos": u[:4]} for r, u in rooms.items()],
    }


@tool("Similar hotels")
async def eg_similar(
    hotel: HotelRef,
    limit: Annotated[int, Field(ge=1, le=10)] = 8,
) -> dict[str, Any]:
    """List the hotels the site suggests as alternatives to one hotel, with a starting price.

    `price_from` is the undated price per night in Toman; real prices: eg_rooms.
    """
    p = await _property(hotel)
    v = await http.fetch(f"/properties/suggestion-by-property/{p['id']}")
    return {
        "name": p["full_name"],
        "similar": [
            {
                "name": s["full_name"],
                "hotel": s["uri"],
                "stars": _star(s["star"]),
                "rating": s["rating"] or None,
                "reviews": s["comment_count"],
                "price_from": s["min_price"],
                "discount_percent": s["discount_percent"] or None,
                "address": s["address"],
            }
            for s in v["property_suggest"][:limit]
        ],
    }


Special = Literal["free_cancellation", "one_night", "latest_discount"]


@tool("Special offers")
async def eg_specials(
    kind: Annotated[
        Special,
        Field(description="free_cancellation needs city."),
    ],
    city: Annotated[str | None, Field(description="Slug or Persian name; required for free_cancellation.")] = None,
    limit: Annotated[int, Field(ge=1, le=60)] = 15,
) -> dict[str, Any]:
    """List hotels on one of the site's offer pages: free cancellation, one-night offers or latest discounts.

    Undated: `price_from` is the starting price per night in Toman, absent when the site lists none. Dates: eg_rooms.
    """
    c = await _city(city) if city else None
    if kind == "free_cancellation":
        if not c:
            cities = (await http.fetch("/locations/get-by-free-cancellation-promotion"))["locations"]
            raise ToolError(
                "free_cancellation needs a city. Cities with offers: " + ", ".join(x["english_name"] for x in cities)
            )
        v = await http.fetch(f"/properties/get-by-free-cancellation-promotion/{c['id']}")
    elif kind == "one_night":
        v = await http.fetch("/properties/get-by-promotion-class/per_night")
    else:
        v = await http.fetch("/properties/hotel/get-latest-discount")
        for p in v["properties"]:  # this list sends Toman, the others Rial
            p["min_price"] = p["min_price"] * 10
    rows = [p for p in v["properties"] if not c or p["city_id"] == c["id"]]
    cities = {x["id"]: x["english_name"] for x in await _locations() if x["type"] == "city"}
    out = []
    for p in rows[:limit]:
        card = _card(p, "available", 1)
        for k in ("id", "status", "stay_total", "price_up_to"):
            card.pop(k, None)
        out.append({"city": cities.get(p["city_id"]), **card})
    # some offers come without any price (min_price null); the price then exists only for dates with free rooms
    for city_name in {h["city"] for h in out if h["price_from"] is None and h["city"]}:
        try:
            cards, _ = await _search(city_name, None, 1, "hotel")
        except ToolError:
            continue
        price = {x["id"]: x["price_from"] for x in cards}
        for p, h in zip(rows, out, strict=False):
            if h["city"] == city_name and h["price_from"] is None:
                h["price_from"] = price.get(p["id"])
    return {"kind": kind, "found": len(rows), "hotels": out}
