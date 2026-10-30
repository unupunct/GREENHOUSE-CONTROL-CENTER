# Budget

The application builds the budget for you from the Planner and the Shopping page; this document explains how to read it and what it can honestly say. For the rules about prices and links see SHOPPING_LIST.md.

## What the budget is

- **Total of priced lines** in RON (VAT-inclusive; prices quoted without VAT are converted with the VAT rate in Planner options, default 21 %, **an assumption to verify**).
- Split into **verified** (read from a supplier page, dated) and **your own estimates**.
- Counts of **unpriced lines** and **lines whose quantity needs input**.
- **By subsystem**, **by tier** (low / recommended / professional) and a **supplier comparison** (how many items each supplier covers and what they cost).
- Exports: CSV, Excel, PDF (Shopping page).

## What it cannot say

A complete cost for the 200 m² greenhouse cannot be stated yet: at the time of writing **one item has a verified price** (Raspberry Pi 5 4GB, 639 RON including taxes, read from a Romanian retailer's page on 2026-10-30) and everything else is "no price recorded", because the application never invents prices. Several quantities (fans, pumps, drippers, heaters, lights) also stay open until you give the planner the inputs only you have: greenhouse height, target air changes, fan and pump datasheet values, drip line length, water demand, lighting targets, electrical loads.

## How to produce a real budget

1. Greenhouse page: fill in all engineering inputs (height, ridge, covering, orientation, heating need, water pressure, electricity supply, location).
2. Planner: enter the sizing inputs from the datasheets of the equipment you are considering. Quantities appear once their inputs exist.
3. Shopping: choose the tier, then for each line add one or more offers (supplier, price, VAT included or not, URL, availability). Mark an offer **verified** only if you read it on the live supplier page.
4. Re-check prices and stock before ordering: both change.
5. Use the tier totals to compare the three configurations, but only once most lines have prices (the page shows how many are missing).

## Not in the budget

Mains installation labour and materials designed by your electrician, groundwork, water supply connection, greenhouse structure and covering, crop inputs, running costs (electricity, water, nutrients), VAT-recoverable items, shipping and import duties. Heating is not sized by this application, so heating equipment appears as "needs heat-load calculation".
