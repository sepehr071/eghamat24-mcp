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
    _locations,
    _norm,
    _property,
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
    city: Annotated[str, Field(description="Destination city slug from eg_cities or Persian name (Mashhad, Kish...).")],
    origin: Origin = "Tehran",
    check_in: CheckIn = None,
    nights: Nights = 2,
    adults: Adults = 2,
    hotel: Annotated[
        str | None,
        Field(
            description="A hotel (the `hotel` value of this tool or eg_search): list its tour packages with flights."
        ),
    ] = None,
    sort: Annotated[Literal["price", "rating", "stars"], Field(description="Order of the hotel list.")] = "price",
    limit: Annotated[int, Field(ge=1, le=60)] = 15,
) -> dict[str, Any]:
    """Find flight-plus-hotel tour packages to a city, or the packages of one hotel with their flight times.

    Use it for "Tehran to Mashhad for 2 nights with the flight included". Without `hotel` it lists hotels with the
    cheapest package for all `adults` together (`price_total`) and per person; with `hotel` it lists that hotel's
    packages (room, meal plan, round-trip flights). Prices are Toman, flight included. Only some cities sell tours.
    Empty results mean the flight seats for those dates are full: try other dates with eg_tour_calendar.
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
    city: Annotated[str, Field(description="Destination city slug or Persian name.")],
    origin: Origin = "Tehran",
    from_date: Annotated[
        str | None, Field(description="First departure day, YYYY-MM-DD or Jalali. Default: tomorrow.")
    ] = None,
    nights: Nights = 2,
    adults: Adults = 2,
    days: Annotated[int, Field(ge=1, le=31, description="How many departure days to list.")] = 14,
) -> dict[str, Any]:
    """Show the cheapest flight-plus-hotel package price for each departure day, to pick the cheapest day to leave.

    Use it for "when is a Tehran to Kish tour cheapest". A day missing from the list has no package (flights full).
    Prices are Toman for all `adults` together. For the hotels on one day use eg_tours.
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
    city: Annotated[str, Field(description="City slug from eg_cities or Persian name.")],
    query: Annotated[str | None, Field(description="Part of the attraction name, Persian.")] = None,
    type: Annotated[str | None, Field(description="Attraction type as shown in results, e.g. shopping_center.")] = None,
    attraction_id: Annotated[
        int | None, Field(description="Get the description of this attraction (id from this list).")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=60)] = 20,
) -> dict[str, Any]:
    """List the sights, shrines, malls and other places of a city, or read the description of one.

    Use it as a city guide ("what to see in Mashhad") and to pick a place to stay near: pass an attraction's `id`
    to eg_search as `attraction_id`. With `attraction_id` here you get its text, coordinates and type.
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
            "lat": a["location"]["latitude"],
            "lng": a["location"]["longitude"],
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
                "lat": a["location"]["latitude"],
                "lng": a["location"]["longitude"],
            }
            for a in rows[:limit]
        ],
    }


@tool("Hotel photos")
async def eg_photos(
    hotel: HotelRef,
    limit: Annotated[int, Field(ge=1, le=60, description="Most photos to list.")] = 20,
) -> dict[str, Any]:
    """List the photo URLs of a hotel: the main picture, the hotel gallery and the photos of each room type.

    Use it to show or describe how a hotel and its rooms look. URLs are full-size JPEGs on eghamat24.com.
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

    Use it when a hotel is sold out or too dear. `price_from` is the site's undated starting price per night in
    Toman; get real prices for dates with eg_rooms or eg_search.
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
        Field(
            description="free_cancellation = hotels with free cancellation (needs city); one_night = the site's "
            "one-night offers; latest_discount = hotels with the newest discounts."
        ),
    ],
    city: Annotated[str | None, Field(description="City slug or Persian name; required for free_cancellation.")] = None,
    limit: Annotated[int, Field(ge=1, le=60)] = 15,
) -> dict[str, Any]:
    """List hotels on one of the site's offer pages: free cancellation, one-night offers or the latest discounts.

    Use it for "hotels with free cancellation in Shiraz" or "any one-night offers". These pages carry no dates:
    `price_from` is the starting price per night in Toman and can change; follow up with eg_rooms for dates.
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
    return {"kind": kind, "found": len(rows), "hotels": out}
