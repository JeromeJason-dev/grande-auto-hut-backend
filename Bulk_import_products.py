"""
Bulk-import products into Grande Auto Hut from a CSV file.

Usage:
    pip install requests
    python bulk_import_products.py

Edit the SETTINGS block first. Run it against a local backend before production.
"""
import csv
import sys
import requests

# ---------------- SETTINGS ----------------
API = "https://grande-auto-hut-backend.onrender.com/api"      
EMAIL = "Jason@gmail.com"            
PASSWORD = "Jason@123"
CSV_FILE = "products.csv"
# ------------------------------------------

session = requests.Session()


def login():
    r = session.post(f"{API}/auth/login/", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    session.headers["Authorization"] = f"Bearer {r.json()['access']}"


def fetch_all(path):
    """Return every row of a paginated list endpoint."""
    rows, url = [], f"{API}/{path}/"
    while url:
        r = session.get(url)
        r.raise_for_status()
        data = r.json()
        rows += data["results"] if isinstance(data, dict) and "results" in data else data
        url = data.get("next") if isinstance(data, dict) else None
    return rows


def get_or_create(path, name, cache):
    """Look up a Category or Brand by name; create it if missing. Returns its id."""
    key = name.strip().lower()
    if key not in cache:
        r = session.post(f"{API}/{path}/", json={"name": name.strip()})
        r.raise_for_status()
        cache[key] = r.json()["id"]
    return cache[key]


def main():
    login()
    categories = {c["name"].lower(): c["id"] for c in fetch_all("categories")}
    brands = {b["name"].lower(): b["id"] for b in fetch_all("brands")}
    existing_skus = {p["sku"] for p in fetch_all("products")}

    created, skipped, failed = 0, 0, 0
    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            sku = row["sku"].strip()
            if sku in existing_skus:
                print(f"line {line_no}: {sku} already exists, skipped")
                skipped += 1
                continue

            payload = {
                "sku": sku,
                "name": row["name"].strip(),
                "category": get_or_create("categories", row["category"], categories),
                "brand": get_or_create("brands", row["brand"], brands),
                "description": row["description"].strip(),
                "condition": row["condition"].strip().lower(),  # genuine | aftermarket | refurbished
                "price": row["price"].strip(),
                "stock_quantity": int(row["stock_quantity"]),
                "low_stock_threshold": int(row["low_stock_threshold"] or 5),
                "is_active": True,  # makes it visible to the public
            }
            r = session.post(f"{API}/products/", json=payload)
            if r.status_code == 201:
                print(f"line {line_no}: created {sku}")
                created += 1
            else:
                print(f"line {line_no}: FAILED {sku} -> {r.status_code} {r.text}")
                failed += 1

    print(f"\nDone. Created {created}, skipped {skipped}, failed {failed}.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()