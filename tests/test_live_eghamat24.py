import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

PARSIS = "/MashhadHotels/ParsisHotel.html"


async def test_live_cities(client):
    r = (await client.call_tool("eg_cities", {"query": "Mashhad"})).structured_content
    assert r["destinations"][0]["city"] == "Mashhad" and r["destinations"][0]["hotels"] > 100


async def test_live_search_and_rooms(client):
    args = {"city": "Mashhad", "sort": "price_asc", "limit": 5}
    r = (await client.call_tool("eg_search", args)).structured_content
    assert r["found"] > 20 and all(h["price_from"] > 100_000 for h in r["hotels"]), r
    rooms = (await client.call_tool("eg_rooms", {"hotel": r["hotels"][0]["hotel"]})).structured_content
    assert rooms["offers"] and rooms["offers"][0]["total"] > 0, rooms


async def test_live_hotel_reviews_questions(client):
    h = (await client.call_tool("eg_hotel", {"hotel": PARSIS})).structured_content
    assert h["stars"] == 5 and h["facilities"]["hotel"] and h["nearby"]
    r = (await client.call_tool("eg_reviews", {"hotel": PARSIS})).structured_content
    assert r["total_reviews"] > 50 and len(r["reviews"]) == 10
    q = (await client.call_tool("eg_questions", {"hotel": PARSIS})).structured_content
    assert q["total"] >= 0


async def test_live_price_calendar_and_deals(client):
    c = (await client.call_tool("eg_price_calendar", {"hotel": PARSIS, "days": 5})).structured_content
    assert len(c["nights"]) == 5
    d = (await client.call_tool("eg_deals", {"city": "Kish", "min_discount": 1})).structured_content
    assert "hotels" in d


async def test_live_tours_attractions_specials(client):
    t = (await client.call_tool("eg_tours", {"city": "Mashhad", "limit": 3})).structured_content
    assert t["found"] > 20 and t["hotels"][0]["price_total"] > 1_000_000
    c = (await client.call_tool("eg_tour_calendar", {"city": "Mashhad", "days": 5})).structured_content
    assert c["days"]
    a = (await client.call_tool("eg_attractions", {"city": "Mashhad", "limit": 3})).structured_content
    assert a["found"] > 50
    s = (await client.call_tool("eg_specials", {"kind": "free_cancellation", "city": "Mashhad"})).structured_content
    assert s["hotels"]


async def test_live_photos_similar_reviews(client):
    p = (await client.call_tool("eg_photos", {"hotel": PARSIS})).structured_content
    assert p["main"] and p["hotel_photos"]
    assert (await client.call_tool("eg_similar", {"hotel": PARSIS})).structured_content["similar"]
    r = (await client.call_tool("eg_reviews", {"hotel": PARSIS})).structured_content
    assert r["total_reviews"] >= r["reviews_with_text"]
