"""Supplier directory.

Only facts observed on a supplier's own site or in search results are recorded,
with the date. A supplier listed here is NOT a guarantee that it stocks any
particular item. ``url`` is None where the domain has not been verified.
"""

from __future__ import annotations

SUPPLIERS: list[dict] = [
    {"id": "optimusdigital", "name": "Optimus Digital", "url": "https://www.optimusdigital.ro/",
     "kind": "Romanian electronics retailer", "prices_include_vat": True,
     "verified": "2026-10-30",
     "note": "Raspberry Pi 5 4GB product page showed a 'Raspberry Pi Approved Reseller' logo and prices "
             "'with all taxes included'. Confirm reseller status on raspberrypi.com/resellers."},
    {"id": "soselectronic", "name": "SOS electronic (Romania storefront)", "url": "https://soselectronic.com/en-ro/",
     "kind": "Electronic components / industrial", "prices_include_vat": False, "verified": "2026-10-30",
     "note": "Storefront states 'Prices without VAT' in RON. Lists DIN-rail supplies from MEAN WELL and "
             "TRACOPOWER. Product page text did not show price or stock when fetched; check live."},
    {"id": "tme", "name": "TME (Transfer Multisort Elektronik)", "url": "https://www.tme.eu/",
     "kind": "Electronic and industrial components distributor", "prices_include_vat": None,
     "verified": "2026-10-30",
     "note": "A Romanian TME entity is listed on TME's group site. The Romanian storefront itself was "
             "not checked; open tme.eu and select Romania."},
    {"id": "ardushop", "name": "ArduShop", "url": "https://ardushop.ro/en", "kind": "Romanian electronics retailer",
     "prices_include_vat": None, "verified": "2026-10-30",
     "note": "Appeared in search results as a Romanian retailer (Arduino, Raspberry Pi). Not checked further."},
]

# Discovery targets named in the project brief. NOT verified, no URL claimed.
UNVERIFIED_TARGETS = ["Mivarom", "Robofun", "Optonica", "Dedeman", "Hornbach Romania",
                      "Leroy Merlin Romania", "Agricultural irrigation suppliers",
                      "Industrial automation suppliers", "Greenhouse equipment specialists"]

SEED_OFFERS: list[dict] = [
    {"item_id": "pi5_4gb", "supplier_id": "optimusdigital", "product_name": "Raspberry Pi 5/4GB",
     "manufacturer": "Raspberry Pi Ltd", "model": "Raspberry Pi 5 4GB (ref. 5056561803319)",
     "price_ron": 639.0, "includes_vat": True, "url": "https://www.optimusdigital.ro/12928-product.html",
     "availability": "in stock (160 pcs shown on 2026-10-30)", "delivery": "not checked",
     "status": "verified", "checked_ts": 1793318400,
     "note": "Read from the product page on 2026-10-30: '639,00 lei', all taxes included. "
             "Prices and stock change; re-check before ordering."},
]
