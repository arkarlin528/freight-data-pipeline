"""
Mock carrier websites to crawl. Fictional carriers, fictional prices, always online.

Three carriers, three very different sources, like the real world:

  /asl/tariffs?page=N   Andaman Sea Lines: server-rendered HTML table, paginated, port *names*,
                        "USD 1,250.00" prices, "On request" rows, a date-range column.
  /mcl/rates            Mekong Container Lines: JavaScript app; the HTML is an empty shell and the
                        rates arrive from /mcl/api/rates as JSON (prices in cents, 40'HC style codes).
  /ssc/rates.csv        Straits Shipping Co.: a semicolon CSV export with comma decimals.

Each source also contains a few bad rows (unknown ports, unsupported containers, zero prices,
duplicates) so the pipeline's validation has something to catch. Set MOCK_FLAKY_EVERY=N to make
every Nth request fail with 503 (exercises retries) and MOCK_MARKET_DAY=n to move some prices.

Run:  uvicorn mock_site.app:app --port 8900
"""

from __future__ import annotations

import calendar
import hashlib
import itertools
import os
from datetime import date

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

app = FastAPI(title="Mock carrier sites", docs_url=None, redoc_url=None)

PORTS = {
    "THLCH": "Laem Chabang, Thailand",
    "THBKK": "Bangkok, Thailand",
    "SGSIN": "Singapore",
    "MYPKG": "Port Klang, Malaysia",
    "VNSGN": "Ho Chi Minh City, Vietnam",
    "IDJKT": "Jakarta, Indonesia",
    "MMRGN": "Yangon, Myanmar",
    "CNSHA": "Shanghai, China",
    "HKHKG": "Hong Kong",
    "JPTYO": "Tokyo, Japan",
    "NLRTM": "Rotterdam, Netherlands",
    "USLAX": "Los Angeles, USA",
}
HUBS = ["THLCH", "SGSIN", "VNSGN"]
# Rough distance class per destination, so prices look plausible.
DISTANCE = {
    "THLCH": 1,
    "THBKK": 1,
    "SGSIN": 1,
    "MYPKG": 1,
    "VNSGN": 1,
    "IDJKT": 2,
    "MMRGN": 2,
    "CNSHA": 3,
    "HKHKG": 2,
    "JPTYO": 4,
    "NLRTM": 9,
    "USLAX": 8,
}
CONTAINERS = {"20GP": 1.0, "40GP": 1.6, "40HC": 1.7}

_request_counter = itertools.count(1)


@app.middleware("http")
async def flaky(request: Request, call_next):  # type: ignore[no-untyped-def]
    every = int(os.getenv("MOCK_FLAKY_EVERY", "0"))
    if every and request.url.path != "/robots.txt" and next(_request_counter) % every == 0:
        return PlainTextResponse("Service temporarily unavailable", status_code=503, headers={"Retry-After": "1"})
    return await call_next(request)


def _validity(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last)


def _price(carrier: str, origin: str, dest: str, container: str, valid_from: date) -> float:
    """Deterministic per lane and month, different per carrier."""
    seed = int(hashlib.sha256(f"{carrier}{origin}{dest}{container}{valid_from}".encode()).hexdigest()[:8], 16)
    base = 220 + 95 * max(DISTANCE[origin], DISTANCE[dest]) + (seed % 140) - 70
    # MOCK_MARKET_DAY=n simulates the market moving: about 1 lane in 5 changes price by -15%..+25%.
    day = int(os.getenv("MOCK_MARKET_DAY", "0"))
    if day:
        move = int(hashlib.sha256(f"{seed}{day}".encode()).hexdigest()[:4], 16)
        if move % 5 == 0:
            base *= 1 + ((move % 41) - 15) / 100
    return round(base * CONTAINERS[container], 2)


def _lanes(carrier: str) -> list[tuple[str, str, str, float]]:
    valid_from, _ = _validity()
    rows = []
    for origin in HUBS:
        for dest in PORTS:
            if dest == origin:
                continue
            for container in CONTAINERS:
                rows.append((origin, dest, container, _price(carrier, origin, dest, container, valid_from)))
    return rows


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return "User-agent: *\nDisallow: /asl/admin\nDisallow: /internal/\nCrawl-delay: 1\n"


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<html><body><h1>Mock carrier sites</h1><ul>
    <li><a href="/asl/tariffs">Andaman Sea Lines: tariff table (HTML)</a></li>
    <li><a href="/mcl/rates">Mekong Container Lines: rate finder (JavaScript)</a></li>
    <li><a href="/ssc/rates.csv">Straits Shipping Co.: rate sheet (CSV)</a></li>
    </ul><p>All carriers and prices are fictional.</p></body></html>"""


# --- Andaman Sea Lines: paginated HTML --------------------------------------------------------

ASL_EQUIPMENT = {"20GP": "20' Standard", "40GP": "40' Standard", "40HC": "40' High Cube"}
ASL_PAGE_SIZE = 25


def _asl_rows() -> list[tuple[str, str, str, str, str]]:
    valid_from, valid_to = _validity()
    valid = f"{valid_from:%d %b %Y} – {valid_to:%d %b %Y}"
    rows = []
    for i, (origin, dest, container, price) in enumerate(_lanes("ASL")):
        rate = "On request" if i % 17 == 5 else f"USD {price:,.2f}"
        rows.append((PORTS[origin], PORTS[dest], ASL_EQUIPMENT[container], rate, valid))
    # Dirty data: a port nobody maps, and a row repeated on the next page.
    rows.insert(7, ("Kuala Tanjung, Indonesia", PORTS["SGSIN"], "20' Standard", "USD 410.00", valid))
    rows.insert(ASL_PAGE_SIZE + 1, rows[3])
    return rows


@app.get("/asl/tariffs", response_class=HTMLResponse)
def asl_tariffs(page: int = 1) -> str:
    rows = _asl_rows()
    pages = (len(rows) + ASL_PAGE_SIZE - 1) // ASL_PAGE_SIZE
    chunk = rows[(page - 1) * ASL_PAGE_SIZE : page * ASL_PAGE_SIZE]
    body = "".join(
        f"<tr><td class='pol'>{o}</td><td class='pod'>{d}</td><td class='eqp'>{e}</td>"
        f"<td class='rate'>{r}</td><td class='validity'>{v}</td></tr>"
        for o, d, e, r, v in chunk
    )
    nav = f"<a class='next' href='/asl/tariffs?page={page + 1}'>Next ›</a>" if page < pages else ""
    return f"""<html><head><title>Andaman Sea Lines: Tariffs</title></head><body>
    <h1>Ocean freight tariffs</h1><p class="note">All-in rates per container. Fictional data.</p>
    <table id="tariffs"><thead><tr><th>From</th><th>To</th><th>Equipment</th><th>Rate</th><th>Valid</th></tr></thead>
    <tbody>{body}</tbody></table>
    <div class="pager">Page {page} of {pages} {nav}</div></body></html>"""


# --- Mekong Container Lines: JavaScript app over a JSON API --------------------------------------

MCL_EQUIPMENT = {"20GP": "20'GP", "40GP": "40'GP", "40HC": "40'HC"}


@app.get("/mcl/api/rates")
def mcl_api() -> JSONResponse:
    valid_from, valid_to = _validity()
    items = [
        {
            "pol": o,
            "pod": d,
            "eqp": MCL_EQUIPMENT[c],
            "price_cents": round(p * 100),
            "ccy": "usd",
            "effective": valid_from.isoformat(),
            "expiry": valid_to.isoformat(),
        }
        for o, d, c, p in _lanes("MCL")
    ]
    items[4]["price_cents"] = 0  # dirty: zero price
    items.append({**items[10], "eqp": "45'HC"})  # dirty: unsupported equipment
    return JSONResponse({"carrier": "MCL", "count": len(items), "rates": items})


@app.get("/mcl/rates", response_class=HTMLResponse)
def mcl_page() -> str:
    # Nothing useful in the HTML itself: a scraper must run the JavaScript (or call the API).
    return """<html><head><title>Mekong Container Lines: Rate finder</title></head><body>
    <h1>Rate finder</h1><div id="status">Loading rates…</div>
    <table id="rates" hidden>
    <thead><tr><th>POL</th><th>POD</th><th>Equipment</th><th>Price</th><th>Valid</th></tr></thead>
    <tbody></tbody></table>
    <script>
      fetch('/mcl/api/rates').then(r => r.json()).then(data => {
        const tbody = document.querySelector('#rates tbody');
        for (const r of data.rates) {
          const tr = document.createElement('tr');
          tr.dataset.rate = JSON.stringify(r);
          tr.innerHTML = `<td>${r.pol}</td><td>${r.pod}</td><td>${r.eqp}</td>` +
            `<td>${(r.price_cents / 100).toFixed(2)} ${r.ccy.toUpperCase()}</td><td>${r.effective} → ${r.expiry}</td>`;
          tbody.appendChild(tr);
        }
        document.querySelector('#rates').hidden = false;
        document.querySelector('#status').textContent = data.count + ' rates';
      });
    </script></body></html>"""


# --- Straits Shipping Co.: CSV export --------------------------------------------------------------


@app.get("/ssc/rates.csv")
def ssc_csv() -> Response:
    valid_from, valid_to = _validity()
    lines = ["origin_code;destination_code;container;amount;currency;valid_from;valid_to"]
    for o, d, c, p in _lanes("SSC"):
        amount = f"{p:.2f}".replace(".", ",")  # European decimal comma
        lines.append(f"{o};{d};{c};{amount};USD;{valid_from:%d/%m/%Y};{valid_to:%d/%m/%Y}")
    lines.append(f"THLCH;XXXXX;20GP;300,00;USD;{valid_from:%d/%m/%Y};{valid_to:%d/%m/%Y}")  # dirty: bad port
    lines.append(f"SGSIN;JPTYO;40HC;999,00;USD;{valid_to:%d/%m/%Y};{valid_from:%d/%m/%Y}")  # dirty: dates reversed
    return Response(
        "\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ssc-rates.csv"},
    )
