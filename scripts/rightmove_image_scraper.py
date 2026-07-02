"""
Rightmove image & floorplan scraper
Downloads all listing photos and floorplans for every property in
data/properties.json and saves them to data/images/<ref>/.

Run from the root of your cloned house repo:
    python rightmove_image_scraper.py

REQUIREMENTS (already installed if you ran the description scraper):
    pip install playwright
    playwright install chromium

OUTPUT:
    data/images/<ref>/photo_01.jpg  … photo_N.jpg
    data/images/<ref>/floorplan_01.jpg … (if available)
    data/images/manifest.json       — ref → list of local paths

After running, commit everything:
    git add data/images/
    git commit -m "Add property images"
    git push
"""

import json
import time
import random
import re
import base64
from pathlib import Path
from playwright.sync_api import sync_playwright

PROPS_FILE   = Path("data/properties.json")
IMAGES_DIR   = Path("data/images")
MANIFEST     = IMAGES_DIR / "manifest.json"

# Max photos per property (set to None for no limit)
MAX_PHOTOS    = None
MAX_FLOORPLANS = 3


def get_image_urls(page, ref):
    """Extract all listing photo and floorplan URLs from a Rightmove property page."""
    photos, floorplans = [], []

    try:
        # Wait for images to appear
        page.wait_for_selector("img", timeout=8000)
        time.sleep(1.5)

        # Get all img src and srcset attributes
        imgs = page.evaluate("""() => {
            const imgs = [];
            document.querySelectorAll('img').forEach(img => {
                const src = img.src || '';
                const srcset = img.srcset || img.getAttribute('srcset') || '';
                imgs.push({ src, srcset });
            });
            return imgs;
        }""")

        seen = set()
        for img in imgs:
            # Collect all candidate URLs from src and srcset
            candidates = [img['src']]
            if img['srcset']:
                for part in img['srcset'].split(','):
                    url = part.strip().split(' ')[0]
                    if url:
                        candidates.append(url)

            for url in candidates:
                if not url or url in seen:
                    continue
                seen.add(url)

                # Rightmove photo pattern
                if 'media.rightmove.co.uk' in url:
                    if any(x in url.lower() for x in ['flp', 'floorplan', '_floor']):
                        floorplans.append(url)
                    elif any(x in url for x in ['_img_', '/crop/', 'images/']):
                        # Prefer highest resolution: swap crop variants for full size
                        full_url = re.sub(r'/dir/crop/[^/]+/', '/dir/', url)
                        photos.append(full_url)
                    elif ref in url and url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        photos.append(url)

        # Dedupe preserving order
        photos    = list(dict.fromkeys(photos))
        floorplans = list(dict.fromkeys(floorplans))

        # Also try the JSON data embedded in the page (more reliable)
        json_data = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                const t = s.textContent || '';
                if (t.includes('propertyData') || t.includes('images')) {
                    return t.substring(0, 50000);
                }
            }
            return '';
        }""")

        if json_data:
            # Extract all rightmove media URLs from embedded JSON
            found = re.findall(
                r'https://media\.rightmove\.co\.uk/[^\s\'"\\]+\.(?:jpg|jpeg|png|webp)',
                json_data, re.IGNORECASE
            )
            for url in found:
                url = url.rstrip('.,;)')
                if url in seen:
                    continue
                seen.add(url)
                if any(x in url.lower() for x in ['flp', 'floorplan', '_floor']):
                    floorplans.append(url)
                else:
                    photos.append(url)

        # Final dedup
        photos     = list(dict.fromkeys(photos))
        floorplans = list(dict.fromkeys(floorplans))

    except Exception as e:
        print(f"    Warning: image URL extraction error: {e}")

    return photos, floorplans


def download_image(page, url, dest_path):
    """Download a single image via the browser (inherits cookies/session)."""
    try:
        response = page.request.get(url, timeout=15000)
        if response.ok:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(response.body())
            return True
        else:
            print(f"    HTTP {response.status} for {url}")
            return False
    except Exception as e:
        print(f"    Download error: {e}")
        return False


def main():
    if not PROPS_FILE.exists():
        print("ERROR: data/properties.json not found. Run from repo root.")
        return

    props = json.load(open(PROPS_FILE, encoding="utf-8"))
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing manifest
    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            manifest = {}

    # Filter to properties not yet downloaded (or with empty manifest entry)
    to_process = []
    for p in props:
        ref = p["ref"]
        ref_dir = IMAGES_DIR / ref
        existing = manifest.get(ref, {})
        n_photos = len(existing.get("photos", []))
        n_floors = len(existing.get("floorplans", []))
        if n_photos == 0:
            to_process.append(p)
        else:
            print(f"  SKIP {ref} ({p['name'][:40]}) — already have {n_photos} photos, {n_floors} floorplans")

    if not to_process:
        print("All properties already downloaded.")
        return

    print(f"\nWill download images for {len(to_process)} properties.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-GB",
            timezone_id="Europe/London",
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "Referer": "https://www.rightmove.co.uk/",
            },
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = context.new_page()

        # Warm up with homepage + cookie accept
        print("Warming up with Rightmove homepage…")
        page.goto("https://www.rightmove.co.uk", wait_until="domcontentloaded", timeout=15000)
        time.sleep(random.uniform(2, 3))
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler, button[id*='accept-all']")
            if btn:
                btn.click()
                print("Cookies accepted.")
                time.sleep(1)
        except Exception:
            pass

        total = len(to_process)
        for i, prop in enumerate(to_process, 1):
            ref  = prop["ref"]
            name = prop["name"][:50]
            url  = f"https://www.rightmove.co.uk/properties/{ref}"
            ref_dir = IMAGES_DIR / ref
            ref_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n[{i}/{total}] {name} (ref {ref})")
            print(f"  URL: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                time.sleep(random.uniform(2, 3))
            except Exception as e:
                print(f"  Navigation error: {e}")
                continue

            photo_urls, floor_urls = get_image_urls(page, ref)
            print(f"  Found {len(photo_urls)} photos, {len(floor_urls)} floorplans")

            # Limit if configured
            if MAX_PHOTOS:
                photo_urls = photo_urls[:MAX_PHOTOS]
            if MAX_FLOORPLANS:
                floor_urls = floor_urls[:MAX_FLOORPLANS]

            saved_photos, saved_floors = [], []

            # Download photos
            for j, img_url in enumerate(photo_urls, 1):
                ext = Path(img_url.split('?')[0]).suffix or '.jpg'
                dest = ref_dir / f"photo_{j:02d}{ext}"
                if dest.exists():
                    saved_photos.append(str(dest.relative_to(Path("."))))
                    continue
                print(f"  Photo {j}/{len(photo_urls)}…", end=" ", flush=True)
                ok = download_image(page, img_url, dest)
                if ok:
                    saved_photos.append(str(dest.relative_to(Path("."))))
                    print("✓")
                else:
                    print("✗")
                time.sleep(random.uniform(0.3, 0.7))

            # Download floorplans
            for j, img_url in enumerate(floor_urls, 1):
                ext = Path(img_url.split('?')[0]).suffix or '.jpg'
                dest = ref_dir / f"floorplan_{j:02d}{ext}"
                if dest.exists():
                    saved_floors.append(str(dest.relative_to(Path("."))))
                    continue
                print(f"  Floorplan {j}/{len(floor_urls)}…", end=" ", flush=True)
                ok = download_image(page, img_url, dest)
                if ok:
                    saved_floors.append(str(dest.relative_to(Path("."))))
                    print("✓")
                else:
                    print("✗")
                time.sleep(random.uniform(0.3, 0.7))

            manifest[ref] = {
                "name": prop["name"],
                "photos": saved_photos,
                "floorplans": saved_floors,
            }

            # Save manifest after each property so progress isn't lost
            with open(MANIFEST, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            print(f"  Saved {len(saved_photos)} photos, {len(saved_floors)} floorplans")

            # Polite delay between properties
            if i < total:
                delay = random.uniform(3, 6)
                print(f"  Waiting {delay:.1f}s…")
                time.sleep(delay)

        browser.close()

    print(f"\n{'='*60}")
    print(f"Done. Images saved to data/images/")
    print(f"Manifest: {MANIFEST}")
    print(f"\nNext steps:")
    print(f"  git add data/images/ data/properties.json")
    print(f"  git commit -m 'Add property images'")
    print(f"  git push")


if __name__ == "__main__":
    main()
