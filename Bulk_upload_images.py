"""
Upload product pictures to Grande Auto Hut.

Put the images in a folder called product_images/ and name them after the SKU:
    BRK-001.jpg        -> main picture for BRK-001
    BRK-001_2.jpg      -> extra picture
    BRK-001_3.png      -> extra picture
Run:  python bulk_upload_images.py
Products that already have pictures are skipped, so it is safe to re-run.
"""
import getpass
import os
import re
import sys
import requests

API = "https://grande-auto-hut-backend.onrender.com/api"
EMAIL = input("Jason@gmail.com").strip()
PASSWORD = getpass.getpass("Jason@123")
FOLDER = "product_images"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

s = requests.Session()


def login():
    r = s.post(f"{API}/auth/login/", json={"email": EMAIL, "password": PASSWORD}, timeout=90)
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['access']}"


def sku_to_slug():
    out, url = {}, f"{API}/products/"
    while url:
        r = s.get(url, timeout=90)
        r.raise_for_status()
        data = r.json()
        for p in data["results"]:
            out[p["sku"]] = p["slug"]
        url = data.get("next")
    return out


def main():
    login()
    slugs = sku_to_slug()

    # group files by SKU: BRK-001.jpg and BRK-001_2.jpg both belong to BRK-001
    groups = {}
    for name in sorted(os.listdir(FOLDER)):
        base, ext = os.path.splitext(name)
        if ext.lower() not in EXTS:
            continue
        sku = re.sub(r"_\d+$", "", base)
        groups.setdefault(sku, []).append(name)

    ok = failed = skipped = 0
    for sku, files in groups.items():
        slug = slugs.get(sku)
        if not slug:
            print(f"{sku}: no product with this SKU, skipped")
            skipped += 1
            continue
        detail = s.get(f"{API}/products/{slug}/", timeout=90).json()
        if detail.get("images"):
            print(f"{sku}: already has pictures, skipped")
            skipped += 1
            continue
        for i, name in enumerate(files):
            with open(os.path.join(FOLDER, name), "rb") as f:
                r = s.post(
                    f"{API}/products/{slug}/images/",
                    data={"alt_text": detail["name"], "is_primary": "true" if i == 0 else "false", "sort_order": i},
                    files={"image": f},
                    timeout=120,
                )
            if r.status_code == 201:
                print(f"{sku}: uploaded {name}")
                ok += 1
            else:
                print(f"{sku}: FAILED {name} -> {r.status_code} {r.text[:200]}")
                failed += 1
    print(f"\nDone. Uploaded {ok}, skipped {skipped}, failed {failed}.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()