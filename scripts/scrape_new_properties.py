"""
Scraper for 5 new properties that need photos:
  - 4 Rightmove properties (use Playwright browser session)
  - 1 Apex27 property (60 Gwyn St)

Run from repo root:
  python scripts/scrape_new_properties.py

Or copy to scripts/ and run:
  python scripts/scrape_new_properties.py
"""
import json, time, random, re, os
from pathlib import Path
from playwright.sync_api import sync_playwright

os.chdir(Path(__file__).parent.parent if Path(__file__).parent.name == "scripts"
         else Path(__file__).parent)

IMAGES_DIR = Path("data/images")
MANIFEST   = IMAGES_DIR / "manifest.json"

TARGETS = [
    {"ref": "160507001", "url": "https://www.rightmove.co.uk/properties/160507001",
     "name": "Llanpumsaint Farmstead", "site": "rightmove"},
    {"ref": "167437883", "url": "https://www.rightmove.co.uk/properties/167437883",
     "name": "Panteg Uchaf, Narberth",  "site": "rightmove"},
    {"ref": "89491017",  "url": "https://www.rightmove.co.uk/properties/89491017",
     "name": "Cwmbach Farmhouse, Whitland", "site": "rightmove"},
    {"ref": "90542934",  "url": "https://www.rightmove.co.uk/properties/90542934",
     "name": "Avonvale Road, Trowbridge",   "site": "rightmove"},
    {"ref": "apex27_885144", "url": "https://movingyou-property-details.apex27.co.uk/885144",
     "name": "60 Gwyn Street, Alltwen", "site": "apex27"},
]

def get_rm_images(page, ref):
    """Extract Rightmove listing image URLs via embedded JSON."""
    photos, floors = [], []
    try:
        page.wait_for_selector("img", timeout=8000)
        time.sleep(2)
        # Extract from embedded page data
        scripts = page.query_selector_all("script")
        for s in scripts:
            text = s.inner_text() or ""
            if "propertyData" in text or '"images"' in text:
                found = re.findall(
                    r'https://media\.rightmove\.co\.uk/[^\s\'"\\]+\.(?:jpg|jpeg|png|webp)',
                    text, re.I)
                for u in found:
                    u = u.rstrip('.,;)')
                    if any(x in u.lower() for x in ['flp','floorplan','_floor']):
                        floors.append(u)
                    else:
                        photos.append(u)
                break
        # Fallback: img tags
        if not photos:
            imgs = page.evaluate("""() =>
                Array.from(document.querySelectorAll('img'))
                    .map(i => i.src).filter(s => s.includes('media.rightmove'))
            """)
            for u in imgs:
                if any(x in u.lower() for x in ['flp','floorplan']):
                    floors.append(u)
                else:
                    full = re.sub(r'/dir/crop/[^/]+/', '/dir/', u)
                    photos.append(full)
    except Exception as e:
        print(f"    Warning: {e}")
    return list(dict.fromkeys(photos)), list(dict.fromkeys(floors))

def get_apex27_images(page):
    """Extract Apex27 image URLs."""
    photos, floors = [], []
    try:
        page.wait_for_selector("img", timeout=8000)
        time.sleep(2)
        imgs = page.evaluate("""() =>
            Array.from(document.querySelectorAll('img, a[href*="/images/"]'))
                .map(el => el.src || el.href).filter(Boolean)
        """)
        for u in imgs:
            if 'apex27.co.uk' in u or 'fs-0' in u:
                if 'floorplan' in u.lower() or '_0002_' in u:
                    floors.append(u)
                elif any(x in u for x in ['listing_885144', '/images/']):
                    photos.append(u)
        # Also try the /images/{n}/large redirect pattern via direct fetch
        for i in range(39):
            try:
                r = page.request.get(
                    f"https://movingyou-property-details.apex27.co.uk/885144/images/{i}/large",
                    timeout=8000)
                if r.ok:
                    final = r.url
                    if final not in photos:
                        photos.append(final)
            except: pass
        # Floorplan direct
        fp = "https://fs-05.apex27.co.uk/data_4f1b/listing_885144_0002_d3c1b3b6.jpg"
        try:
            r = page.request.get(fp, timeout=5000)
            if r.ok: floors = [fp]
        except: pass
    except Exception as e:
        print(f"    Warning: {e}")
    return list(dict.fromkeys(photos)), list(dict.fromkeys(floors))

def download(page, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = page.request.get(url, timeout=15000)
        if r.ok:
            dest.write_bytes(r.body())
            return True
    except Exception as e:
        print(f"    ✗ {e}")
    return False

def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width":1366,"height":768}, locale="en-GB",
            timezone_id="Europe/London",
            extra_http_headers={"Accept-Language":"en-GB,en;q=0.9"})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # Warm up Rightmove
        print("Warming up Rightmove…")
        page.goto("https://www.rightmove.co.uk", wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        try:
            btn = page.query_selector("#onetrust-accept-btn-handler")
            if btn: btn.click(); time.sleep(1)
        except: pass

        for t in TARGETS:
            ref  = t["ref"]
            name = t["name"]
            ref_dir = IMAGES_DIR / ref
            ref_dir.mkdir(parents=True, exist_ok=True)

            existing = manifest.get(ref, {})
            existing_photos = [p for p in existing.get("photos", [])
                               if (Path(p).exists() if not p.startswith("http") else False)]

            print(f"\n{'='*55}")
            print(f"  {name}  ({ref})")

            try:
                page.goto(t["url"], wait_until="domcontentloaded", timeout=25000)
                time.sleep(random.uniform(2, 3))
            except Exception as e:
                print(f"  Navigation error: {e}"); continue

            if t["site"] == "apex27":
                photo_urls, floor_urls = get_apex27_images(page)
            else:
                photo_urls, floor_urls = get_rm_images(page, ref)

            print(f"  Found {len(photo_urls)} photos, {len(floor_urls)} floorplans")

            saved_p, saved_f = [], []
            for j, url in enumerate(photo_urls, 1):
                ext  = Path(url.split('?')[0]).suffix or '.jpg'
                dest = ref_dir / f"photo_{j:02d}{ext}"
                if dest.exists():
                    saved_p.append(str(dest)); continue
                print(f"  Photo {j}/{len(photo_urls)}…", end=" ", flush=True)
                if download(page, url, dest):
                    saved_p.append(str(dest)); print("✓")
                else:
                    print("✗")
                time.sleep(random.uniform(0.3, 0.6))

            for j, url in enumerate(floor_urls[:3], 1):
                ext  = Path(url.split('?')[0]).suffix or '.jpg'
                dest = ref_dir / f"floorplan_{j:02d}{ext}"
                if dest.exists():
                    saved_f.append(str(dest)); continue
                print(f"  Floorplan {j}…", end=" ", flush=True)
                if download(page, url, dest):
                    saved_f.append(str(dest)); print("✓")
                else:
                    print("✗")

            manifest[ref] = {"name": name, "photos": saved_p, "floorplans": saved_f}
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            print(f"  Saved {len(saved_p)} photos, {len(saved_f)} floorplans")

            if t != TARGETS[-1]:
                d = random.uniform(3, 5)
                print(f"  Waiting {d:.1f}s…")
                time.sleep(d)

        browser.close()

    print("\n✓ Done. Now run:")
    print("  git add data/images/ && git commit -m 'Add photos for 5 new properties' && git push")

if __name__ == "__main__":
    main()
