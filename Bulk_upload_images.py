"""
Upload product pictures to Grande Auto Hut.

Put the images in a folder called product_images/ and name them after the SKU:
    BRK-001.jpg        -> main picture for BRK-001
    BRK-001_2.jpg      -> extra picture (shown after the main one)
    BRK-001_3.png      -> extra picture
Accepted: .jpg .jpeg .png .webp, max 5 MB each (the server's limit).
The SKU match is case-insensitive.

Usage:
    pip install requests
    python Bulk_upload_images.py --dry-run     # shows what would be uploaded; no login
    python Bulk_upload_images.py               # upload for real

Credentials / API address come from environment variables, a git-ignored
.env.bulk file, or a prompt. Never hardcode them here. See gah_client.py.

Safe to re-run: products that already have a picture are skipped (including
inactive products). To replace pictures, delete them in the Django admin first.
"""
import argparse
import os
import re
import sys

from Gah_client import Client, short

EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_BYTES = 5 * 1024 * 1024  # matches MAX_IMAGE_BYTES in catalog/serializers.py


def natural_key(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def group_by_sku(folder, known_skus):
    """{sku_lower: [filenames in upload order]}. 'BRK-001' is the main picture,
    'BRK-001_2', 'BRK-001_3' ... follow in numeric order. If the full file name
    is itself a real SKU (e.g. a SKU that ends in _2) it is treated as that SKU."""
    groups = {}
    for name in os.listdir(folder):
        base, ext = os.path.splitext(name)
        if ext.lower() not in EXTS or name.startswith("."):
            continue
        if base.lower() in known_skus:
            sku, order = base.lower(), 1
        else:
            m = re.match(r"^(.*?)_(\d+)$", base)
            sku, order = (m.group(1).lower(), int(m.group(2))) if m else (base.lower(), 1)
        groups.setdefault(sku, []).append((order, natural_key(name), name))
    return {sku: [n for _o, _k, n in sorted(items)] for sku, items in groups.items()}


def main():
    ap = argparse.ArgumentParser(description="Bulk-upload product images named after SKUs.")
    ap.add_argument("--folder", default=os.environ.get("GAH_IMAGE_FOLDER", "product_images"))
    ap.add_argument("--dry-run", action="store_true", help="list what would be uploaded; no login, nothing sent")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"Image folder not found: {args.folder}")

    if args.dry_run:
        groups = group_by_sku(args.folder, set())
        for sku, files in sorted(groups.items()):
            print(f"{sku}: {', '.join(files)}")
        print(f"\nDry run: {sum(len(f) for f in groups.values())} image(s) for {len(groups)} SKU(s). Nothing was sent.")
        return

    client = Client()
    ok = failed = skipped = 0
    try:
        client.login()
        products = {p["sku"].lower(): p for p in client.fetch_products()}  # includes inactive
        groups = group_by_sku(args.folder, set(products))

        for sku, files in sorted(groups.items()):
            product = products.get(sku)
            if not product:
                print(f"{sku}: no product with this SKU (import products first), skipped")
                skipped += 1
                continue
            if product.get("primary_image"):
                print(f"{product['sku']}: already has pictures, skipped")
                skipped += 1
                continue

            uploaded_here = 0
            for i, name in enumerate(files):
                path = os.path.join(args.folder, name)
                size = os.path.getsize(path)
                if size > MAX_BYTES:
                    print(f"{product['sku']}: FAILED {name} -> {size / 1048576:.1f} MB is over the 5 MB limit")
                    failed += 1
                    continue
                if size == 0:
                    print(f"{product['sku']}: FAILED {name} -> file is empty")
                    failed += 1
                    continue
                with open(path, "rb") as f:
                    content = f.read()  # bytes, so a retry can re-send it
                ext = os.path.splitext(name)[1].lower()
                r = client.post(
                    f"products/{product['slug']}/images",
                    data={
                        "alt_text": product["name"][:255],
                        "is_primary": "true" if uploaded_here == 0 else "false",
                        "sort_order": uploaded_here,
                    },
                    files={"image": (name, content, EXTS[ext])},
                    timeout=(15, 180),
                )
                if r.status_code == 201:
                    print(f"{product['sku']}: uploaded {name}")
                    ok += 1
                    uploaded_here += 1
                else:
                    print(f"{product['sku']}: FAILED {name} -> {r.status_code} {short(r)}")
                    failed += 1

        no_pictures = [p["sku"] for k, p in products.items() if not p.get("primary_image") and k not in groups]
        if no_pictures:
            shown = ", ".join(no_pictures[:15]) + (" ..." if len(no_pictures) > 15 else "")
            print(f"\nProducts with no image file in {args.folder}/: {shown}")
    finally:
        client.close()

    print(f"\nDone. Uploaded {ok}, skipped {skipped}, failed {failed}.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()