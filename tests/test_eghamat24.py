from datetime import date

import httpx
import pytest
from conftest import fixture

from eghamat24_mcp import hotels, http

pytestmark = pytest.mark.anyio

TOOLS = {
    "eg_cities",
    "eg_search",
    "eg_deals",
    "eg_hotel",
    "eg_rooms",
    "eg_price_calendar",
    "eg_reviews",
    "eg_questions",
    "eg_photos",
    "eg_similar",
    "eg_attractions",
    "eg_specials",
    "eg_tours",
    "eg_tour_calendar",
}
PARSIS = "/MashhadHotels/ParsisHotel.html"


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(hotels, "_today", lambda: date(2026, 11, 1))


@pytest.fixture
def site(api):
    """Fake upstream for one hotel (id 1253)."""
    api["/locations"] = fixture("locations.json")
    api["/search/get-properties-v2"] = fixture("search.json")
    api["/properties/property-detail"] = fixture("detail.json")
    api["/api/property/v1/facilities/search"] = fixture("facility_filters.json")
    api["/api/tours/v2/static/city/by-params"] = fixture("tour_city.json")
    api["/api/tours/v2/static/property/by-params"] = fixture("tour_property.json")
    api["/api/tours/v2/price-calendar"] = fixture("tour_calendar.json")
    api["/attractions/get-by-city-id/36"] = fixture("city_attractions.json")
    api["/attractions/show/1"] = fixture("attraction_show.json")
    api["/properties/suggestion-by-property/1253"] = fixture("similar.json")
    api["/properties/get-by-free-cancellation-promotion/36"] = fixture("free_cancel.json")
    api["/locations/get-by-free-cancellation-promotion"] = fixture("free_cancel_cities.json")
    api["/properties/get-by-promotion-class/per_night"] = fixture("one_night.json")
    api["/properties/hotel/get-latest-discount"] = fixture("latest.json")
    api["/categories/get-by-city-id"] = fixture("categories.json")
    for name, path in [
        ("scores", "scores"),
        ("rules", "rules"),
        ("services", "services"),
        ("facilities", "facilities"),
        ("promotions", "promotions"),
        ("attractions", "attractions"),
        ("room-types", "room_types"),
        ("rate-plans", "rate_plans"),
        ("v2/rooms-rates", "rates"),
        ("comments", "comments"),
        ("comments/travel-goal-count", "goals"),
        ("questions", "questions"),
        ("files", "files"),
    ]:
        api[f"/properties/1253/{name}"] = fixture(f"{path}.json")
    return api


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name
        assert "title" not in str(t.input_schema.get("properties", {}).values()), t.name


def test_jalali_date_and_past_dates():
    assert hotels._date("1405-08-19") == date(2026, 11, 10)
    assert hotels._date("۱۴۰۵/۰۸/۱۹") == date(2026, 11, 10)
    assert hotels._date(None) == date(2026, 11, 2)
    with pytest.raises(Exception, match="past"):
        hotels._date("2026-10-01")


def test_hotel_ref_forms():
    for ref in (
        PARSIS,
        "https://www.eghamat24.com" + PARSIS + "?check_in=2026-11-10",
        "Mashhad/Parsis",
        "Mashhad ParsisHotel",
    ):
        assert hotels._resolve_hotel_ref(ref) == ("Mashhad", "Parsis"), ref
    assert hotels._resolve_hotel_ref("/MashhadStays/Jahan2Stay.html") == ("Mashhad", "Jahan2")
    with pytest.raises(Exception, match="Cannot read"):
        hotels._resolve_hotel_ref("???")


async def test_cities_filters_and_names_provinces(client, site):
    r = (await client.call_tool("eg_cities", {"query": "Mashhad"})).structured_content
    assert r["destinations"][0]["city"] == "Mashhad" and r["destinations"][0]["hotels"] == 260
    assert r["destinations"][0]["province"]


async def test_search_converts_rial_to_toman_and_sorts(client, site):
    args = {"city": "mashhad", "check_in": "1405-08-19", "sort": "price_asc"}
    r = (await client.call_tool("eg_search", args)).structured_content
    q = site.calls[-1].url.params
    assert q["destination_name"] == "Mashhad" and q["check_in"] == "2026-11-10" and q["group_type"] == "hotel"
    prices = [h["price_from"] for h in r["hotels"]]
    assert prices == sorted(prices) and prices[0] % 1000 == 0 and prices[0] < 10_000_000
    parsis = next(h for h in r["hotels"] if h["hotel"] == PARSIS)
    assert parsis["price_from"] == 4_000_000 and parsis["stars"] == 5 and parsis["status"] == "available"
    assert {h["status"] for h in r["hotels"]} == {"available", "min_stay"}  # sold out hidden by default
    assert r["sold_out"] == 2


async def test_search_filters(client, site):
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "min_stars": 5})).structured_content
    assert r["hotels"] and all(h["stars"] == 5 for h in r["hotels"])
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "type": "apartment_hotel"})).structured_content
    assert r["hotels"] and all(h["type"] == "apartment_hotel" for h in r["hotels"])
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "include_sold_out": True})).structured_content
    assert any(h["status"] == "sold_out" and "price_from" not in h for h in r["hotels"])
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "max_price": 4_000_000})).structured_content
    assert all(h["price_from"] <= 4_000_000 for h in r["hotels"])
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "name": "پارسیس"})).structured_content
    assert [h["hotel"] for h in r["hotels"]] == [PARSIS]


async def test_search_unknown_city_is_an_error(client, site):
    r = await client.call_tool("eg_search", {"city": "Nowhere"})
    assert r.is_error and "eg_cities" in r.content[0].text


async def test_deals_sorted_by_discount(client, site):
    r = (await client.call_tool("eg_deals", {"city": "Mashhad", "min_discount": 1})).structured_content
    d = [h["discount_percent"] for h in r["hotels"]]
    assert d == sorted(d, reverse=True) and d[0] >= 1


async def test_hotel_profile(client, site):
    r = (await client.call_tool("eg_hotel", {"hotel": PARSIS})).structured_content
    assert r["stars"] == 5 and r["check_in_time"] == "14:00" and r["scores_out_of_10"]["overall"] == 6.8
    assert r["facilities"]["hotel"] and "exist" not in str(r["facilities"])
    meters = [a["meters"] for a in r["nearby"]]
    assert meters == sorted(meters) and len({a["name"] for a in r["nearby"]}) == len(r["nearby"])
    assert len(r["perks"]) == len(set(r["perks"]))
    assert not any(x["title"] == "ورود و خروج" for x in r["rules"])
    q = site.calls[0].url.params
    assert q["property_name"] == "Parsis" and q["city_name"] == "Mashhad"


async def test_hotel_not_found(client, api):
    api["/properties/property-detail"] = lambda r: httpx.Response(422, json={"message": "bad", "errors": {}})
    r = await client.call_tool("eg_hotel", {"hotel": "Mashhad/Zzz"})
    assert r.is_error and "eg_search" in r.content[0].text


async def test_rooms_prices_for_stay(client, site):
    r = (
        await client.call_tool("eg_rooms", {"hotel": PARSIS, "check_in": "2026-11-10", "nights": 2})
    ).structured_content
    q = next(c for c in site.calls if c.url.path.endswith("rooms-rates")).url.params
    assert q["from_date"] == "2026-11-10" and q["to_date"] == "2026-11-12"
    eco = r["offers"][0]
    assert eco["room_id"] == 36630 and eco["plan"] and eco["total"] == 8_000_000 and eco["per_night"] == [4_000_000] * 2
    assert eco["list_total"] == 12_925_000 and eco["free_cancel"] is True
    totals = [o["total"] for o in r["offers"]]
    assert totals == sorted(totals)
    assert r["check_out"] == "2026-11-12"


async def test_rooms_reports_missing_nights_and_guest_filter(client, site):
    r = (
        await client.call_tool("eg_rooms", {"hotel": PARSIS, "check_in": "2026-11-10", "nights": 3})
    ).structured_content
    assert not r["offers"] and r["not_bookable"][0]["why"] == "no price for some nights"
    r = (
        await client.call_tool("eg_rooms", {"hotel": PARSIS, "check_in": "2026-11-10", "guests": 2})
    ).structured_content
    assert r["offers"] and all(o["capacity"] + o["extra_beds"] >= 2 for o in r["offers"])


async def test_rooms_sold_out_night(client, site):
    rates = fixture("rates.json")
    for x in rates["value"]["room_rates"]:
        x["inventory"] = 0
    site["/properties/1253/v2/rooms-rates"] = rates
    r = (await client.call_tool("eg_rooms", {"hotel": PARSIS, "check_in": "2026-11-10"})).structured_content
    assert not r["offers"] and {b["why"] for b in r["not_bookable"]} == {"sold out for some nights"}


async def test_price_calendar(client, site):
    args = {"hotel": PARSIS, "from_date": "2026-11-10", "days": 3}
    r = (await client.call_tool("eg_price_calendar", args)).structured_content
    assert r["cheapest"] == 4_000_000
    assert [n["night"] for n in r["nights"]] == ["2026-11-10", "2026-11-11", "2026-11-12"]
    assert r["nights"][0]["from"] == 4_000_000 and r["nights"][2]["sold_out"] is True  # fixture has two days


async def test_reviews_first_page_has_scores(client, site):
    r = (await client.call_tool("eg_reviews", {"hotel": PARSIS})).structured_content
    assert (
        r["total_reviews"] == 187
        and r["reviews_with_text"] == 152
        and r["scores_out_of_10"]["overall"] == 6.8
        and r["trip_types"]["family"] == 157
    )
    first = r["reviews"][0]
    assert isinstance(first["rooms"], list) and len(first["date"]) == 10 and "\r" not in str(first)
    r2 = (await client.call_tool("eg_reviews", {"hotel": PARSIS, "page": 2})).structured_content
    assert "scores_out_of_10" not in r2 and site.calls[-1].url.params["page"] == "2"


async def test_questions(client, site):
    r = (await client.call_tool("eg_questions", {"hotel": PARSIS, "limit": 2})).structured_content
    assert r["total"] == 4 and len(r["questions"][0]["answers"]) == 1


async def test_upstream_errors_are_readable(client, api):
    api["/locations"] = lambda r: httpx.Response(403, text="blocked")
    r = await client.call_tool("eg_cities", {})
    assert r.is_error and "403" in r.content[0].text


async def test_refuses_other_hosts(monkeypatch):
    monkeypatch.setattr(http, "SITE", "https://evil.example")
    with pytest.raises(http.ApiError):
        await http.fetch("/x")


async def test_search_server_filters(client, site):
    args = {
        "city": "Mashhad",
        "facilities": ["استخر", "پارکینگ"],
        "beds": 2,
        "board": "room_only",
        "area": "حرم",
    }
    await client.call_tool("eg_search", args)
    q = site.calls[-1].url.params.multi_items()
    assert ("facilities[]", "91") in q and ("facilities[]", "90") in q
    assert ("bed[]", "2") in q and ("board_types[]", "room_only") in q and ("categories[]", "585") in q
    assert next(c for c in site.calls if c.url.path.endswith("categories/get-by-city-id")).url.params["city_id"] == "36"


async def test_search_bad_facility_or_area_lists_choices(client, site):
    r = await client.call_tool("eg_search", {"city": "Mashhad", "facilities": ["zzz"]})
    assert r.is_error and "Filterable" in r.content[0].text
    r = await client.call_tool("eg_search", {"city": "Mashhad", "area": "zzz"})
    assert r.is_error and "Use one of" in r.content[0].text


async def test_search_price_is_per_night_for_long_stays(client, site):
    r = (await client.call_tool("eg_search", {"city": "Mashhad", "nights": 2, "name": "پارسیس"})).structured_content
    h = r["hotels"][0]
    assert h["stay_total"] == 2 * h["price_from"]


async def test_reviews_total_is_the_sites_count(client, site):
    r = (await client.call_tool("eg_reviews", {"hotel": PARSIS, "page": 2})).structured_content
    assert r["total_reviews"] == 187 and r["reviews_with_text"] == 152 and "scores_out_of_10" not in r


async def test_rooms_has_cancellation_rule(client, site):
    r = (await client.call_tool("eg_rooms", {"hotel": PARSIS, "check_in": "2026-11-10"})).structured_content
    assert "کنسلی" in r["cancellation"]


async def test_search_guests_and_attraction(client, site):
    args = {"city": "Mashhad", "check_in": "2026-11-10", "nights": 2, "guests": 2, "attraction_id": 1, "limit": 3}
    r = (await client.call_tool("eg_search", args)).structured_content
    q = next(c for c in site.calls if c.url.path == "/search/get-properties-v2").url.params
    assert q["attraction_id"] == "1"
    assert any(h.get("price_for_guests") for h in r["hotels"])


async def test_tours_city_and_hotel(client, site):
    r = (await client.call_tool("eg_tours", {"city": "Mashhad", "check_in": "2026-11-10"})).structured_content
    q = next(c for c in site.calls if "city/by-params" in c.url.path).url.params
    assert q["origin_id"] == "112" and q["destination_id"] == "36" and q["rooms[0][adult_count]"] == "2"
    prices = [h["price_total"] for h in r["hotels"]]
    assert prices == sorted(prices) and r["hotels"][0]["per_person"] * 2 == prices[0] and prices[0] % 1000 == 0
    r = (
        await client.call_tool("eg_tours", {"city": "Mashhad", "check_in": "2026-11-10", "hotel": PARSIS})
    ).structured_content
    pk = r["packages"]
    assert [p["price_total"] for p in pk] == sorted(p["price_total"] for p in pk)
    assert pk[0]["outbound"]["flights"][0]["from"] == "THR" and pk[0]["return"]["flights"][0]["to"] == "THR"


async def test_tours_need_a_tour_city(client, site):
    r = await client.call_tool("eg_tours", {"city": "Babolsar"})
    assert r.is_error and "tours" in r.content[0].text


async def test_tour_calendar(client, site):
    r = (
        await client.call_tool("eg_tour_calendar", {"city": "Mashhad", "from_date": "2026-11-02", "days": 3})
    ).structured_content
    assert len(r["days"]) <= 3 and r["cheapest"]["price_total"] == min(d["price_total"] for d in r["days"])


async def test_attractions_list_and_detail(client, site):
    r = (await client.call_tool("eg_attractions", {"city": "Mashhad", "query": "خاور"})).structured_content
    assert r["found"] >= 1 and r["attractions"][0]["id"] == 1
    d = (await client.call_tool("eg_attractions", {"city": "Mashhad", "attraction_id": 1})).structured_content
    assert d["description"] and "<" not in d["description"]
    bad = await client.call_tool("eg_attractions", {"city": "Kish", "attraction_id": 1})
    assert bad.is_error


async def test_photos_group_rooms(client, site):
    r = (await client.call_tool("eg_photos", {"hotel": PARSIS})).structured_content
    assert r["main"].startswith("https://www.eghamat24.com/app/public/hotel_images/original/")
    assert r["hotel_photos"] and r["room_photos"][0]["room"]


async def test_similar(client, site):
    r = (await client.call_tool("eg_similar", {"hotel": PARSIS})).structured_content
    assert len(r["similar"]) == 3 and r["similar"][0]["price_from"] == 10_000_000


async def test_specials(client, site):
    r = (await client.call_tool("eg_specials", {"kind": "free_cancellation", "city": "Mashhad"})).structured_content
    assert r["hotels"][0]["price_from"] == 8_546_000 and "id" not in r["hotels"][0]
    r = (await client.call_tool("eg_specials", {"kind": "one_night"})).structured_content
    assert r["found"] == 3
    r = (await client.call_tool("eg_specials", {"kind": "latest_discount"})).structured_content
    assert r["hotels"][1]["price_from"] == 8_546_000  # this list sends Toman
    r = await client.call_tool("eg_specials", {"kind": "free_cancellation"})
    assert r.is_error and "city" in r.content[0].text


async def test_headers_match_the_web_app(api):
    api["/api/x"] = {"value": 1}
    await http.fetch("/api/x")
    h = api.calls[0].headers
    assert h["accept"] == "*/*" and h["referer"] == "https://www.eghamat24.com/"
    assert h["sec-fetch-site"] == "same-origin" and "origin" not in h and h["accept-language"].startswith("fa-IR")


async def test_proxy_list_rotates_after_block(api, monkeypatch):
    monkeypatch.setenv("EGHAMAT24_MCP_PROXY", "http://a:1, http://b:2")
    assert http._proxies() == ["http://a:1", "http://b:2"]
    api["/api/x"] = lambda r: httpx.Response(403, json={})
    with pytest.raises(http.ApiError):
        await http.fetch("/api/x")
    assert http._proxy_index == 1
