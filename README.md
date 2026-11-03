<!-- mcp-name: io.github.sepehr071/eghamat24-mcp -->

<div align="center">

# eghamat24-mcp: Eghamat24 (اقامت۲۴) Iran hotel search and room prices MCP server for AI agents

**eghamat24-mcp is an unofficial, read-only MCP server that gives AI agents the hotel data of Eghamat24 (eghamat24.com), the Iranian hotel booking site.**<br>
Its 14 tools search hotels by city, dates, stars, price and facilities, list discounts and special offers, read a hotel's facilities, photos and rules,<br>
price its rooms for a stay, chart the cheapest nights, find flight-plus-hotel tours, browse city sights and read guest reviews and questions.<br>
No API key or account is needed. It works in Claude, Cursor, Copilot and any other MCP client.

[![PyPI](https://img.shields.io/pypi/v/eghamat24-mcp?color=2563eb)](https://pypi.org/project/eghamat24-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/eghamat24-mcp)](https://pypi.org/project/eghamat24-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/eghamat24-mcp/blob/main/LICENSE)

[For AI agents](#for-ai-agents) · [Quick start](#quick-start) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## For AI agents

- **What:** unofficial MCP server (model context protocol) for eghamat24.com: hotel and stay search per city and date with filters, discounts, hotel profile (facilities, rules, scores, nearby places), room prices for a stay, a night-by-night price calendar, photos, similar hotels, free-cancellation and one-night offers, flight-plus-hotel tours with a price calendar, city attractions (and hotels near one), guest reviews and Q&A.
- **Install:** `uvx eghamat24-mcp` or `claude mcp add eghamat24 -- uvx eghamat24-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none. Optional `EGHAMAT24_MCP_PROXY` (HTTP proxy URL); system proxy settings are ignored.
- **Access:** read-only. It cannot book, log in or post, so no confirmation is needed before calling any tool.
- **Tools:** 14, all prefixed `eg_`. Typical sequence: `eg_cities` -> `eg_search` -> `eg_rooms` / `eg_hotel` / `eg_reviews`.
- **Use when:** the user asks which hotels exist in an Iranian city, what a hotel or room costs on given dates, which hotel is cheapest, has a pool, is near the shrine or has the best reviews, when a hotel is cheapest, or what guests say.
- **Do not use when:** the user wants to book, or asks about hotels abroad or plain flight tickets.
- **Output:** compact JSON. Prices are Toman (the site's unit; its API sends Rial). Dates are Gregorian `YYYY-MM-DD`; Jalali such as `1405-08-19` is accepted. Names, rules and reviews are Persian.
- **Machine-readable:** [`server.json`](https://github.com/sepehr071/eghamat24-mcp/blob/main/server.json).

## Why

On eghamat24.com, "cheapest 4-star hotel with a pool near the shrine in Mashhad for two nights" means setting filters,
sorting, and opening hotel after hotel to see room prices. With `eghamat24-mcp` an agent does it in a few calls:

> **You:** Cheap hotel with a pool near the Imam Reza shrine for 2 nights from 19 Aban?
>
> **Agent:** *calls* `eg_search("Mashhad", "1405-08-19", 2, facilities=["استخر"], area="حرم", sort="price_asc")`, then `eg_rooms` for the best two.

## Quick start

```bash
claude mcp add eghamat24 -- uvx eghamat24-mcp
```

Other clients: command `uvx`, args `["eghamat24-mcp"]`. If eghamat24.com is only reachable through a proxy on your network,
set `EGHAMAT24_MCP_PROXY=http://host:port`.

## Tools

| Tool | What it does |
|---|---|
| `eg_cities` | Destinations (cities or provinces) with hotel counts; gives the `city` slug |
| `eg_search` | Hotels in a city for dates: stars, type, price, name, facilities, beds, meal plan, area; sort by price, rating, discount, reviews; sold-out status |
| `eg_deals` | Biggest discounts in a city for dates |
| `eg_hotel` | Profile: address, times, description, facilities, rules, scores out of 10, perks, services, nearby places with distances |
| `eg_rooms` | Bookable rooms and rate plans with total and per-night price, list price, rooms left, free cancellation; guests filter |
| `eg_price_calendar` | Cheapest room price for each night over up to 31 days |
| `eg_reviews` | Guest reviews 10 per page, score breakdown, trip types |
| `eg_questions` | Public guest questions and answers |
| `eg_photos` | Photo URLs of a hotel and of each room type |
| `eg_similar` | Alternative hotels the site suggests, with starting prices |
| `eg_attractions` | City sights, malls and shrines with coordinates and descriptions; the id feeds `eg_search` `attraction_id` |
| `eg_specials` | Offer pages: free cancellation (per city), one-night offers, latest discounts |
| `eg_tours` | Flight plus hotel packages from an origin city: hotels with total and per-person price, or one hotel's packages with flight times |
| `eg_tour_calendar` | Cheapest package for each departure day |

Prices are what the site shows for the dates asked and can change; availability is re-checked on the site at booking.
`price_from` is the cheapest room (often a single bed) per night (in `eg_specials` it can be null when the site lists no price and tomorrow is sold out); `eg_search` with `guests` adds `price_for_guests`.

## FAQ

**Can it book a room?** No. It only reads public pages' data. Booking stays on eghamat24.com.

**Do I need an account or key?** No.

**Does it work outside Iran?** Yes; the site answered both from an Iranian line and through a Turkish proxy when tested. If your network blocks it, set `EGHAMAT24_MCP_PROXY`.

**Is it official?** No. It is an independent project and not affiliated with Eghamat24.

## فارسی

`eghamat24-mcp` یک سرور MCP غیررسمی و فقط‌خواندنی برای اقامت۲۴ است: جستجوی هتل بر اساس شهر، تاریخ، ستاره، قیمت و امکانات، تخفیف‌ها، مشخصات هتل، قیمت اتاق‌ها برای مدت اقامت، تقویم قیمت و نظرات مسافران. رزرو انجام نمی‌دهد. قیمت‌ها به تومان هستند.

نصب: `claude mcp add eghamat24 -- uvx eghamat24-mcp`

## License

MIT. Author: Sepehr Radmard (سپهر رادمرد), [github.com/sepehr071](https://github.com/sepehr071), [linkedin.com/in/sepehr-radmard](https://linkedin.com/in/sepehr-radmard).
