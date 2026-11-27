MERCH TNA TRACKER — DOCTYPE-READY ALL-YEARS IMPORT PACK
Source workbook: Orderbook- VA(2).xlsx
Schema basis: latest supplied Merch TNA Tracker DocType JSON/controllers (v9 package).

THIS PACK IS NOT A RAW-COLUMN DUMP. Import CSV headers below use exact DocType fieldnames and only include editable fields supported by the supplied schema. Read-only/calculated fields are intentionally omitted.

IMPORT FILES
1) 01A_Merch_Buyer_Parents_And_Standalone.csv — DocType: Merch Buyer; exact fields brand, order_currency, buyer_group. Contains parent/standalone buyers.
2) 01B_Merch_Buyer_Child_Brands.csv — DocType: Merch Buyer; import only after 01A because buyer_group links to Bootbarn. These are brand records from BOOTBARN's BRAND column.
3) 02_Buyer_PO.csv — DocType: Buyer PO; exact fields naming_series, buyer, season, po_number, po_date, price_term, remarks. Season is blank because its linked DocType schema/master list was not included. Currency and totals are system-derived; don't import them.
4) 04_Order_Destination.csv — DocType: Order Destination; exact field destination_name. Import before Order Lines.
5) 03_Order_Line_All_Tables_After_PO_Link.csv — DocType: Order Line with its Destinations child table. Parent fields use v9 Order Line fieldnames; child columns are destinations.name, destinations.destination, destinations.qty. Each parent document has one row per destination; continuation rows leave parent fields blank. The buyer_po column is intentionally blank until Buyer PO documents are imported. Export Buyer PO with exact columns name, buyer, po_number to buyer_po_export.csv in the pack root, then run python fill_buyer_po_links.py. It generates 03_Order_Line_All_Tables_READY.csv with actual Buyer PO document names in the required Link field. Use 03_Order_Line_PO_Link_Map.csv to identify each parent row and its CSV row range. Import the READY file using Order Line Data Import / All Tables.
6) 05_Order_Forecast_Projected.csv — DocType: Order Forecast; generated only from projected blocks in SUMMARY 2025/2026/2027. It uses exact editable fieldnames. Status, currency, value_usd, remaining and confirmed fields are read-only/calculated and omitted. Bootbarn group aggregate is excluded because Forecasts are per Brand and no allocation to child brands was supplied.

IMPORTANT MAPPINGS / CONTROLS
- Bootbarn child brands with no independent Euro flag inherit Bootbarn's USD order_currency for this import; child brands with conflicting own currency evidence are held in review. Buyer PO.currency is set by its controller from Merch Buyer.order_currency. If currency differs historically, a single Merch Buyer currency cannot represent all old POs; those records are excluded and flagged in 01_Merch_Buyer_Currency_Review.csv / 02_Buyer_PO_Review.csv.
- Buyer PO.po_date cannot be in the future relative to 2026-11-27. Future or conflicting source dates are left blank and recorded in PO remarks/review.
- Buyer PO.season is a Link to a separate Season DocType; that DocType JSON was not included in the supplied app. Season is left blank for safe import. Use 05_Season_Master_Values_To_Check.csv to verify/add Season masters before updating the Buyer PO links.
- Order Line.buyer_ex_factory_date is required by the controller. Buyer Delivery Date is deliberately not substituted. Rows without an explicit source Ex-Factory date are in 03_Order_Line_Review.csv.
- For DDP Buyer POs, every Order Line needs a positive unit_price_ddp. Lines without it are held in Order Line Review.
- Order Line.status is explicitly set to the DocType default, PO Received. The required buyer_po Link is populated by fill_buyer_po_links.py after Buyer PO import. Order Line.amount, fob_price, ddp_price, amount_usd, exchange_rate, extra_qty and Buyer PO totals are app-calculated/read-only and are not included in import CSVs.
- Order Line buyer, season and currency are copied from the selected Buyer PO; don't import these fields.
- Destination split source rows are grouped into one Order Line with nested destinations child rows wherever the source provides a reliable destination breakdown. Destination masters must exist before importing the Order Line CSV.
- Shipment dates/quantities and status logs are not imported; source shipment details are mostly free text or percentage-only and cannot be converted into reliable Order Shipment child rows without inventing data. New Order Lines use default status.
- Forecasts come from PROJECTED ORDERS only. 2025/2026 month dates use workbook dates. SUMMARY 2027 is arranged as fiscal Apr-Dec 2026 then Jan-Mar 2027; the Jan-Mar header serials in source are stale 2026 dates, so forecast months for those three columns are inferred as Jan-Mar 2027 and documented in 04_Forecast_2027_Fiscal_Date_Assumptions.csv. Review this assumption before import.
- Forecast records use confidence=Medium. If Order Book Settings.require_forecast is enabled, create/attach the forecasts before importing their associated Order Lines.
- Forecast duplicates (same buyer/month) are checked before export; conflicts are in 04_Order_Forecast_Review.csv.
- VA-CM is not mapped to standard Order Line because its Order/Contract fields are not verified Buyer PO numbers and it has no explicit Buyer Ex-Factory Date. Full rows are in 07_VA_CM_Not_Standard_Order_Line.csv.

RECOMMENDED IMPORT ORDER
A) 01A Merch Buyer Parents/Standalone
B) 01B Merch Buyer Child Brands
C) Confirm external Season master values (optional; otherwise keep Buyer PO season blank)
D) 02 Buyer PO
E) Export Buyer PO with columns name, buyer, po_number as buyer_po_export.csv, then run python fill_buyer_po_links.py. Check that it reports 300/300 Order Lines linked; do not put PO Number itself in buyer_po.
F) 04 Order Destination
G) 05 Order Forecast Projected (after confirming date assumptions and Buyer links)
H) 03_Order_Line_All_Tables_READY.csv generated by fill_buyer_po_links.py

REVIEW FILES
- 01_Merch_Buyer_Currency_Review.csv: buyers with missing/conflicting/changed currency flags.
- 02_Buyer_PO_Review.csv: invalid or date-related PO issues.
- 03_Order_Line_Review.csv: order rows blocked by required fields, missing DDP price, unclear PO, or date issues.
- 04_Order_Forecast_Review.csv: forecast rows with missing or mismatched buyer/currency mappings.
- 05_Season_Master_Values_To_Check.csv: Season Link values to verify.
- 06_All_Years_Normalized_Detail.csv: normalized source detail data for every supported detail row.
- 07_VA_CM_Not_Standard_Order_Line.csv: all VA-CM source rows held for separate mapping.
- 00_Source_Sheet_Manifest.csv and 04_Raw_Source_CSVs: traceability to the original workbook sheets.

This is an import-preparation package only. No records were inserted into your Frappe site. The CSVs were validated for headers, row shape and source mappings; live Data Import validation still needs to run against your site's actual existing Link masters and duplicate records.
