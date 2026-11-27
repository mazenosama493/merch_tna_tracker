#!/usr/bin/env python3
"""Fill Order Line.buyer_po links after importing Buyer PO into Frappe.

Steps:
1. Export Buyer PO from Frappe with exact columns: name, buyer, po_number.
2. Save the export as buyer_po_export.csv in this folder.
3. Run: python fill_buyer_po_links.py
4. It generates 03_Order_Line_All_Tables_READY.csv for Order Line / All Tables import.
"""
import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PO_EXPORT = ROOT / "buyer_po_export.csv"
LINK_MAP = ROOT / "02_Link_And_Reference_Mapping" / "01_Buyer_PO_Link_Map.csv"
LINE_MAP = ROOT / "02_Link_And_Reference_Mapping" / "03_Order_Line_PO_Link_Map.csv"
LINE_INPUT = ROOT / "01_Import_CSVs" / "03_Order_Line_All_Tables_After_PO_Link.csv"
MAP_OUTPUT = ROOT / "02_Link_And_Reference_Mapping" / "01_Buyer_PO_Link_Map_FILLED.csv"
LINE_OUTPUT = ROOT / "01_Import_CSVs" / "03_Order_Line_All_Tables_READY.csv"
MISSING_OUTPUT = ROOT / "03_Review_Required" / "08_Missing_PO_Link_Matches.csv"


def norm_po(value):
    value = " ".join(str(value or "").split()).upper()
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".")[0]
    elif re.fullmatch(r"\d+(\.\d+)?E\+?\d+", value):
        try:
            value = format(Decimal(value), "f")
        except InvalidOperation:
            pass
    return value


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

if not PO_EXPORT.exists():
    raise SystemExit("Missing buyer_po_export.csv. Export Buyer PO with name, buyer, po_number first.")

export_rows = read_csv(PO_EXPORT)
required = {"name", "buyer", "po_number"}
if not export_rows or not required.issubset(export_rows[0]):
    raise SystemExit("buyer_po_export.csv must contain exact columns: name, buyer, po_number")

lookup = {}
ambiguous = set()
for row in export_rows:
    key = (str(row.get("buyer", "")).strip().casefold(), norm_po(row.get("po_number")))
    name = str(row.get("name", "")).strip()
    if not all(key) or not name:
        continue
    if key in lookup and lookup[key] != name:
        ambiguous.add(key)
    lookup[key] = name

po_map = read_csv(LINK_MAP)
po_map_by_key = {}
missing = []
for row in po_map:
    key = (row["buyer"].strip().casefold(), norm_po(row["source_po_number"]))
    if key in ambiguous:
        row["buyer_po_name_after_import"] = ""
        missing.append({"buyer": row["buyer"], "po_number": row["source_po_number"], "issue": "More than one Buyer PO matched this Buyer + PO Number"})
    elif key not in lookup:
        row["buyer_po_name_after_import"] = ""
        missing.append({"buyer": row["buyer"], "po_number": row["source_po_number"], "issue": "No Buyer PO matched this Buyer + PO Number"})
    else:
        row["buyer_po_name_after_import"] = lookup[key]
    po_map_by_key[row["source_po_key"]] = row["buyer_po_name_after_import"]

line_map = read_csv(LINE_MAP)
line_map_by_no = {int(row["import_parent_record_no"]): row for row in line_map}
with LINE_INPUT.open("r", encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    headers = reader.fieldnames
    line_rows = list(reader)

parent_no = 0
for row in line_rows:
    if row.get("style_no", "").strip():
        parent_no += 1
        map_row = line_map_by_no.get(parent_no)
        if not map_row:
            row["buyer_po"] = ""
            missing.append({"buyer": "", "po_number": "", "issue": f"No Order Line mapping for import parent {parent_no}"})
            continue
        row["buyer_po"] = po_map_by_key.get(map_row["source_po_key"], "")
        if not row["buyer_po"]:
            missing.append({"buyer": map_row["buyer"], "po_number": map_row["source_po_number"], "issue": f"No Buyer PO Link for Order Line parent {parent_no}"})

write_csv(MAP_OUTPUT, list(po_map[0].keys()), po_map)
write_csv(LINE_OUTPUT, headers, line_rows)
write_csv(MISSING_OUTPUT, ["buyer", "po_number", "issue"], missing)

linked = sum(1 for row in line_rows if row.get("style_no", "").strip() and row.get("buyer_po", "").strip())
parents = sum(1 for row in line_rows if row.get("style_no", "").strip())
print(f"Buyer PO names matched: {sum(bool(r['buyer_po_name_after_import']) for r in po_map)} / {len(po_map)}")
print(f"Order Lines linked: {linked} / {parents}")
print(f"Ready Order Line file: {LINE_OUTPUT}")
if missing:
    print(f"Review unmatched links: {MISSING_OUTPUT} ({len(missing)} issue rows)")
else:
    print("All Buyer PO links matched. Order Line All Tables CSV is ready for import.")
