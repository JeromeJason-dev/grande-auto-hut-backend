"""
Bulk-import products into Grande Auto Hut from a CSV file.

CSV columns (header row required, any order, case-insensitive):
    required : sku, name, category, brand, price
    optional : description, condition, stock_quantity, low_stock_threshold, is_active
      condition           genuine | aftermarket | refurbished   (default: aftermarket; "oem" = genuine)
      stock_quantity      whole number                          (default: 0)
      low_stock_threshold whole number                          (default: 5)
      is_active           yes/no/true/false/1/0                 (default: yes = visible in the store)

Usage:
    pip install requests
    python Bulk_import_products.py --dry-run     # check the CSV only, no login, nothing sent
    python Bulk_import_products.py               # import for real

Credentials / API address (never put them in this file or on the command line):
    environment variables GAH_API_URL, GAH_EMAIL, GAH_PASSWORD, or a git-ignored
    .env.bulk file (see .env.bulk.example), or you are prompted. See gah_client.py.

Safe to re-run: SKUs that already exist (even inactive ones) are skipped.
Rows that fail are written to failed_products.csv with the reason, so you can
fix them and run again.
"""
import argparse
import csv
import os
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from Gah_client import Client, short

REQUIRED = ["sku", "name", "category", "brand", "price"]
OPTIONAL = ["description", "condition", "stock_quantity", "low_stock_threshold", "is_active"]
CONDITIONS = {"genuine": "genuine", "oem": "genuine", "aftermarket": "aftermarket", "refurbished": "refurbished"}
TRUE = {"1", "true", "yes", "y", "t"}
FALSE = {"0", "false", "no", "n", "f"}
FAILED_FILE = "failed_products.csv"


class RowError(Exception):
    pass


def parse_price(raw):
    cleaned = re.sub(r"[^\d.,-]", "", raw or "").replace(",", "")  # drops "KES", "Ksh", spaces, commas
    if not cleaned:
        raise RowError(f"price '{raw}' is not a number")
    try:
        value = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise RowError(f"price '{raw}' is not a number")
    if value < 0:
        raise RowError("price cannot be negative")
    if value >= Decimal("100000000"):
        raise RowError("price is too large")
    return str(value)


def parse_whole(raw, field, default):
    raw = (raw or "").strip()
    if raw == "":
        return default
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        raise RowError(f"{field} '{raw}' is not a whole number")
    if value != value.to_integral_value() or value < 0:
        raise RowError(f"{field} '{raw}' must be a whole number, 0 or more")
    return int(value)


def parse_row(row, force_inactive):
    sku = (row.get("sku") or "").strip()
    name = (row.get("name") or "").strip()
    category = (row.get("category") or "").strip()
    brand = (row.get("brand") or "").strip()
    if not sku:
        raise RowError("sku is empty")
    if len(sku) > 64:
        raise RowError("sku is longer than 64 characters")
    if not name:
        raise RowError("name is empty")
    if len(name) > 255:
        raise RowError("name is longer than 255 characters")
    if not category:
        raise RowError("category is empty")
    if not brand:
        raise RowError("brand is empty")
    if len(category) > 120 or len(brand) > 120:
        raise RowError("category/brand name is longer than 120 characters")

    condition_raw = (row.get("condition") or "").strip().lower()
    if condition_raw == "":
        condition = "aftermarket"
    elif condition_raw in CONDITIONS:
        condition = CONDITIONS[condition_raw]
    else:
        raise RowError(f"condition '{condition_raw}' must be genuine, aftermarket or refurbished")

    active_raw = (row.get("is_active") or "").strip().lower()
    if active_raw == "" or active_raw in TRUE:
        is_active = True
    elif active_raw in FALSE:
        is_active = False
    else:
        raise RowError(f"is_active '{active_raw}' must be yes or no")

    return {
        "sku": sku,
        "name": name,
        "category": category,
        "brand": brand,
        "description": (row.get("description") or "").strip(),
        "condition": condition,
        "price": parse_price(row.get("price")),
        "stock_quantity": parse_whole(row.get("stock_quantity"), "stock_quantity", 0),
        "low_stock_threshold": parse_whole(row.get("low_stock_threshold"), "low_stock_threshold", 5),
        "is_active": False if force_inactive else is_active,
    }


def read_csv(path, force_inactive):
    """Returns (header, valid_rows, failures). valid_rows = [(line_no, parsed, original_row)]."""
    valid, failures, seen = [], [], set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            sys.exit(f"{path} is empty.")
        reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
        header = list(reader.fieldnames)
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            sys.exit(f"{path} is missing required column(s): {', '.join(missing)}\n"
                     f"Found: {', '.join(header)}")
        unknown = [c for c in header if c and c not in REQUIRED + OPTIONAL]
        if unknown:
            print(f"Note: ignoring unknown column(s): {', '.join(unknown)}")
        for line_no, row in enumerate(reader, start=2):
            if not any(v.strip() for v in row.values() if isinstance(v, str)):
                continue  # blank line
            try:
                parsed = parse_row(row, force_inactive)
                key = parsed["sku"].lower()
                if key in seen:
                    raise RowError(f"duplicate sku '{parsed['sku']}' earlier in this file")
                seen.add(key)
                valid.append((line_no, parsed, row))
            except RowError as e:
                failures.append((line_no, row, str(e)))
    return header, valid, failures


def get_or_create(client, path, name, cache):
    """Find a Category/Brand by name (case-insensitive) or create it. Returns its id."""
    key = name.lower()
    if key in cache:
        return cache[key]
    r = client.post(path, json={"name": name})
    if r.status_code == 201:
        cache[key] = r.json()["id"]
        return cache[key]
    raise RowError(
        f"could not create {path[:-1]} '{name}': {short(r)}. If it exists but was deactivated, "
        f"re-activate it in the Django admin first."
    )


def write_failures(failures, header):
    if not failures:
        if os.path.exists(FAILED_FILE):
            os.remove(FAILED_FILE)  # don't leave a stale file from an earlier run
        return
    with open(FAILED_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(header) + ["error"])
        for _line, row, error in failures:
            w.writerow([row.get(c, "") for c in header] + [error])
    print(f"Failed rows saved to {FAILED_FILE} (fix them and run again).")


def main():
    ap = argparse.ArgumentParser(description="Bulk-import products from a CSV file.")
    ap.add_argument("--csv", default=os.environ.get("GAH_CSV_FILE", "products.csv"), help="CSV path (default products.csv)")
    ap.add_argument("--dry-run", action="store_true", help="validate the CSV only; no login, nothing is sent")
    ap.add_argument("--inactive", action="store_true", help="create every product hidden (is_active=false)")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit(f"CSV file not found: {args.csv}")

    header, valid, failures = read_csv(args.csv, args.inactive)
    for line_no, _row, error in failures:
        print(f"line {line_no}: INVALID -> {error}")
    print(f"\n{len(valid)} valid row(s), {len(failures)} invalid row(s) in {args.csv}.")

    if args.dry_run:
        print("Dry run: nothing was sent.")
        sys.exit(1 if failures else 0)
    if not valid:
        write_failures(failures, header)
        sys.exit(1 if failures else 0)

    client = Client()
    created = skipped = 0
    api_failures = []
    try:
        client.login()
        categories = {c["name"].lower(): c["id"] for c in client.fetch_all("categories")}
        brands = {b["name"].lower(): b["id"] for b in client.fetch_all("brands")}
        existing = {p["sku"].lower() for p in client.fetch_products()}

        for line_no, p, row in valid:
            if p["sku"].lower() in existing:
                print(f"line {line_no}: {p['sku']} already exists, skipped")
                skipped += 1
                continue
            try:
                payload = dict(p)
                payload["category"] = get_or_create(client, "categories", p["category"], categories)
                payload["brand"] = get_or_create(client, "brands", p["brand"], brands)
                r = client.post("products", json=payload)
                if r.status_code != 201:
                    raise RowError(f"{r.status_code} {short(r)}")
            except RowError as e:
                print(f"line {line_no}: FAILED {p['sku']} -> {e}")
                api_failures.append((line_no, row, str(e)))
                continue
            existing.add(p["sku"].lower())
            print(f"line {line_no}: created {p['sku']}")
            created += 1
    finally:
        client.close()

    all_failures = failures + api_failures
    write_failures(all_failures, header)
    print(f"\nDone. Created {created}, skipped {skipped}, failed {len(all_failures)}.")
    if created:
        print("Next: python Bulk_upload_images.py   (then Bulk_import_fitment.py for vehicle compatibility)")
    sys.exit(1 if all_failures else 0)


if __name__ == "__main__":
    main()