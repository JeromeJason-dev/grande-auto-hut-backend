"""
Bulk-assign vehicle fitment (which vehicles each part fits) from a CSV file.

CSV columns (header row required, case-insensitive):
    required : sku, make, model, and either  year  OR  year_from [+ year_to]
    optional : notes   (e.g. "Front only")
Examples:
    FLT-001,Toyota,Hilux,2015,2020,
    SPK-001,Toyota,Hilux,2016,2018,Set of 4
    BAT-001,Nissan,X-Trail,2014,2019,
  (header: sku,make,model,year_from,year_to,notes)   a single year: leave year_to blank.

Makes, models and years that don't exist yet are created automatically.
Products must already exist (run Bulk_import_products.py first).

Usage:
    pip install requests
    python Bulk_import_fitment.py --dry-run
    python Bulk_import_fitment.py

Credentials / API address come from environment variables, a git-ignored
.env.bulk file, or a prompt. See gah_client.py.
Safe to re-run: fitments that already exist are skipped by the server.
"""
import argparse
import csv
import os
import sys

from Gah_client import Client, short

REQUIRED = ["sku", "make", "model"]
MAX_SPAN = 60


class RowError(Exception):
    pass


def parse_year(raw, field):
    raw = (raw or "").strip()
    try:
        year = int(raw)
    except ValueError:
        raise RowError(f"{field} '{raw}' is not a year")
    if not 1900 <= year <= 2100:
        raise RowError(f"{field} {year} must be between 1900 and 2100")
    return year


def read_csv(path):
    rows, failures = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            sys.exit(f"{path} is empty.")
        reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
        header = reader.fieldnames
        missing = [c for c in REQUIRED if c not in header]
        if missing or not ({"year", "year_from"} & set(header)):
            sys.exit(f"{path} needs columns: sku, make, model, and year (or year_from/year_to). Found: {', '.join(header)}")
        for line_no, row in enumerate(reader, start=2):
            if not any(v.strip() for v in row.values() if isinstance(v, str)):
                continue
            try:
                sku = (row.get("sku") or "").strip()
                make = (row.get("make") or "").strip()
                model = (row.get("model") or "").strip()
                if not (sku and make and model):
                    raise RowError("sku, make and model are all required")
                if len(make) > 100 or len(model) > 100:
                    raise RowError("make/model name is longer than 100 characters")
                start_raw = (row.get("year_from") or row.get("year") or "").strip()
                end_raw = (row.get("year_to") or "").strip()
                start = parse_year(start_raw, "year_from")
                end = parse_year(end_raw, "year_to") if end_raw else start
                if end < start:
                    raise RowError(f"year_to {end} is before year_from {start}")
                if end - start > MAX_SPAN:
                    raise RowError(f"year range is longer than {MAX_SPAN} years")
                notes = (row.get("notes") or "").strip()
                if len(notes) > 255:
                    raise RowError("notes are longer than 255 characters")
                rows.append((line_no, sku, make, model, list(range(start, end + 1)), notes))
            except RowError as e:
                failures.append((line_no, row, str(e)))
    return header, rows, failures


class Vehicles:
    """Looks up / creates makes, models and years, caching everything."""

    def __init__(self, client):
        self.c = client
        self.makes = {m["name"].lower(): m for m in client.fetch_all("vehicles/makes")}
        self.models = {}  # make_slug -> {name_lower: model}
        self.years = {}   # (make_slug, model_slug) -> {year: id}

    def make(self, name):
        key = name.lower()
        if key not in self.makes:
            r = self.c.post("vehicles/makes", json={"name": name})
            if r.status_code != 201:
                raise RowError(f"could not create make '{name}': {short(r)}")
            self.makes[key] = r.json()
        return self.makes[key]

    def model(self, make, name):
        slug = make["slug"]
        if slug not in self.models:
            self.models[slug] = {m["name"].lower(): m for m in self.c.fetch_all(f"vehicles/{slug}/models")}
        key = name.lower()
        if key not in self.models[slug]:
            r = self.c.post(f"vehicles/{slug}/models", json={"name": name})
            if r.status_code != 201:
                raise RowError(f"could not create model '{name}' for {make['name']}: {short(r)}")
            self.models[slug][key] = r.json()
        return self.models[slug][key]

    def year_ids(self, make, model, years):
        key = (make["slug"], model["slug"])
        if key not in self.years:
            listed = self.c.fetch_all(f"vehicles/{key[0]}/{key[1]}/years")
            self.years[key] = {y["year"]: y["id"] for y in listed}
        ids = []
        for year in years:
            if year not in self.years[key]:
                r = self.c.post(f"vehicles/{key[0]}/{key[1]}/years", json={"year": year})
                if r.status_code != 201:
                    raise RowError(f"could not create year {year} for {make['name']} {model['name']}: {short(r)}")
                self.years[key][year] = r.json()["id"]
            ids.append(self.years[key][year])
        return ids


def main():
    ap = argparse.ArgumentParser(description="Bulk-assign vehicle fitment from a CSV file.")
    ap.add_argument("--csv", default=os.environ.get("GAH_FITMENT_FILE", "fitment.csv"))
    ap.add_argument("--dry-run", action="store_true", help="validate the CSV only; no login, nothing sent")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit(f"CSV file not found: {args.csv}")
    header, rows, failures = read_csv(args.csv)
    for line_no, _row, error in failures:
        print(f"line {line_no}: INVALID -> {error}")
    print(f"\n{len(rows)} valid row(s), {len(failures)} invalid row(s) in {args.csv}.")
    if args.dry_run:
        print("Dry run: nothing was sent.")
        sys.exit(1 if failures else 0)
    if not rows:
        sys.exit(1 if failures else 0)

    client = Client()
    created = skipped = 0
    failed = len(failures)
    try:
        client.login()
        products = {p["sku"].lower(): p["id"] for p in client.fetch_products()}
        vehicles = Vehicles(client)

        # One bulk request per (product, notes): {key: set of vehicle_year ids}
        batches = {}
        for line_no, sku, make_name, model_name, years, notes in rows:
            try:
                product_id = products.get(sku.lower())
                if not product_id:
                    raise RowError(f"no product with sku '{sku}' (import products first)")
                make = vehicles.make(make_name)
                model = vehicles.model(make, model_name)
                ids = vehicles.year_ids(make, model, years)
                batches.setdefault((product_id, sku, notes), set()).update(ids)
            except RowError as e:
                print(f"line {line_no}: FAILED {sku} {make_name} {model_name} -> {e}")
                failed += 1

        for (product_id, sku, notes), ids in batches.items():
            r = client.post("fitments/bulk", json={"product": product_id, "vehicle_years": sorted(ids), "notes": notes})
            if r.status_code in (200, 201):
                data = r.json()
                created += data["created"]
                skipped += data["skipped"]
                print(f"{sku}: {data['created']} added, {data['skipped']} already existed")
            else:
                failed += 1
                print(f"{sku}: FAILED -> {r.status_code} {short(r)}")
    finally:
        client.close()

    print(f"\nDone. Fitments added {created}, already existed {skipped}, failed rows/batches {failed}.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()