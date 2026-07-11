"""
Scraper for properties that need photos.
Run from ANYWHERE — it finds the repo root automatically by looking for data/properties.json.

Usage:
    python scrape_new_properties.py
    python scripts/scrape_new_properties.py   # if placed in scripts/
"""
import json, time, random, re, os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Find repo root ──────────────────────────────────────────────────────────
def find_repo_root():
    """Walk up from script location until we find data/properties.json"""
    candidates = [
        Path(__file__).parent,
        Path(__file__).parent.parent,
        Path.cwd(),
        Path.cwd().parent,
    ]
    for c in candidates:
        if (c / "data" / "properties.json").exists():
            return c
    print("ERROR: Could not find repo root (looking for data/properties.json)")
    print("Make sure you have the house repo checked out and run from within it.")
    sys.exit(1)

REPO = find_repo_root()
os.chdir(REPO)
print(f"Repo root: {REPO}")

IMAGES_DIR = REPO / "data" / "images"
MANIFEST   = IMAGES_DIR / "manifest.json"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ── Properties to scrape ────────────────────────────────────────────────────
# Add/remove refs here as needed
TARGETS = [
    {"ref": "90443352",  "url": "https://www.rightmove.co.uk/properties/90443352",
     "name": "Manor Road, Taunton",        "site": "rightmove"},
    {"ref": "173546681", "url": "https://www.rightmove.co.uk/properties/173546681",
     "name": "Kents Close, Chard",         "site": "rightmove"},
    {"ref": "160507001", "url": "https://www.rightmove.co.uk/properties/160507001",
     "name": "Llanpumsaint Farmstead",     "site": "rightmove"},
    {"ref": "167437883", "url": "https://www.rightmove.co.uk/properties/167437883",
     "name": "Panteg Uchaf, Narberth",     "site": "rightmove"},
    {"ref": "89491017",  "url": "https://www.rightmove.co.uk/properties/89491017",
     "name": "Cwmbach Farmhouse, Whitland","site": "rightmove"},
    {"ref": "90542934",  "url": "https://www.rightmove.co.uk/properties/90542934",
     "name": "Avonvale Road, Trowbridge",  "site": "rightmove"},
    {"ref": "apex27_885144",
     "url": "https://movingyou-property-details.apex27.co.uk/885144",
     "name": "60 Gwyn Street, Alltwen",    "site": "apex27"},
]

# Skip refs that already have downloaded files
def already_done(ref):
    d = IMAGES_DIR / ref
    if not d.exists(): return False
    files = list(d.glob("photo_*.j*")) + list(d.glob("photo_*.png"))
    return len(files) >= 3

# ── Image extraction ─────────────────────────────────────────────────────────
def get_rm_images(page):
    photos, floors = [], []
    try:
        page.wait_for_selector("img", timeout=10000)
        time.sleep(2.5)
        scripts = page.query_selector_all("script")
        for s in scripts:
            text = s.inner_text() or ""
            if '"images"' in text or "propertyData" in text:
                found = re.findall(
                    r'https://media\.rightmove\.co\.uk/[^\s\'"\\]+\.(?:jpg|jpeg|png|webp)',
                    text, re.I)
                for u in found:
                    u = u.rstrip(".,;)")
                    if any(x in u.lower() for x in ["flp","floorplan","_floor"]):
                        if u not in floors: floors.append(u)
                    elif u not in photos:
                        photos.append(u)
                if photos: break
        # Fallback: img tags
        if not photos:
            imgs = page.evaluate("""() =>
                [...document.querySelectorAll('img')]
                  .map(i=>i.src).filter(s=>s.includes('media.rightmove'))
            """)
            for u in imgs:
                u = re.sub(r'/dir/crop/[^/]+/', '/dir/', u)
                if u not in photos: photos.append(u)
    except Exception as e:
        print(f"    Warning extracting images: {e}")
    return photos, floors

def get_apex27_images(page):
    photos, floors = [], []
    try:
        page.wait_for_selector("img", timeout=10000)
        time.sleep(2)
        # Follow redirects via page.request
        for i in range(50):
            try:
                r = page.request.get(
                    f"https://movingyou-property-details.apex27.co.uk/885144/images/{i}/large",
                    timeout=8000)
                if r.ok and r.url not in photos:
                    photos.append(r.url)
            except: pass
        # Grab images from page
        found = page.evaluate("""() =>
            [...document.querySelectorAll('img')]
              .map(i=>i.src)
              .filter(s=>s.includes('apex27') || s.includes('fs-0'))
        """)
        for u in found:
            if u not in photos and u not in floors:
                if "floor" in u.lower(): floors.append(u)
                elif "listing_885144" in u: photos.append(u)
    except Exception as e:
        print(f"    Warning: {e}")
    return photos, floors

def download(page, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = page.request.get(url, timeout=20000)
        if r.ok:
            dest.write_bytes(r.body())
            return True
    except Exception as e:
        print(f"    ✗ download error: {e}")
    return False

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    targets_to_run = [t for t in TARGETS if not already_done(t["ref"])]
    if not targets_to_run:
        print("All targets already have downloaded images.")
        print("Delete data/images/<ref>/ folders to re-scrape.")
        return

    print(f"Will scrape {len(targets_to_run)} of {len(TARGETS)} targets\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--no-sandbox","--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width":1366,"height":768},
            locale="en-GB", timezone_id="Europe/London",
            extra_http_headers={"Accept-Language":"en-GB,en;q=0.9"})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # Warm up Rightmove once
        rm_targets = [t for t in targets_to_run if t["site"]=="rightmove"]
        if rm_targets:
            print("Warming up Rightmove…")
            page.goto("https://www.rightmove.co.uk",
                      wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            try:
                btn = page.query_selector("#onetrust-accept-btn-handler")
                if btn: btn.click(); time.sleep(1)
            except: pass

        for t in targets_to_run:
            ref  = t["ref"]
            name = t["name"]
            ref_dir = IMAGES_DIR / ref
            ref_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n{'─'*55}")
            print(f"  {name}  ({ref})")
            print(f"  Saving to: {ref_dir}")

            try:
                page.goto(t["url"], wait_until="domcontentloaded", timeout=25000)
                time.sleep(random.uniform(2, 3.5))
            except Exception as e:
                print(f"  Navigation error: {e}"); continue

            if t["site"] == "apex27":
                photo_urls, floor_urls = get_apex27_images(page)
            else:
                photo_urls, floor_urls = get_rm_images(page)

            print(f"  Found {len(photo_urls)} photos, {len(floor_urls)} floorplans")

            saved_p, saved_f = [], []
            for j, url in enumerate(photo_urls, 1):
                ext  = Path(url.split("?")[0]).suffix or ".jpg"
                dest = ref_dir / f"photo_{j:02d}{ext}"
                if dest.exists():
                    saved_p.append(str(dest.relative_to(REPO))); continue
                print(f"  Photo {j}/{len(photo_urls)}…", end=" ", flush=True)
                if download(page, url, dest):
                    saved_p.append(str(dest.relative_to(REPO)).replace("\\","/"))
                    print("✓")
                else:
                    print("✗")
                time.sleep(random.uniform(0.3, 0.7))

            for j, url in enumerate(floor_urls[:3], 1):
                ext  = Path(url.split("?")[0]).suffix or ".jpg"
                dest = ref_dir / f"floorplan_{j:02d}{ext}"
                if dest.exists():
                    saved_f.append(str(dest.relative_to(REPO))); continue
                print(f"  Floorplan {j}…", end=" ", flush=True)
                if download(page, url, dest):
                    saved_f.append(str(dest.relative_to(REPO)).replace("\\","/"))
                    print("✓")
                else:
                    print("✗")

            manifest[ref] = {
                "name": name,
                "photos": saved_p,
                "floorplans": saved_f
            }
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            print(f"  ✓ Saved {len(saved_p)} photos, {len(saved_f)} floorplans")

            if t is not targets_to_run[-1]:
                d = random.uniform(4, 7)
                print(f"  Waiting {d:.1f}s…")
                time.sleep(d)

        browser.close()

    print(f"\n✓ Done. Images saved under: {IMAGES_DIR}")
    print("\nNext steps:")
    print("  git add data/images/")
    print("  git commit -m 'Add scraped photos'")
    print("  git push")

if __name__ == "__main__":
    main()
