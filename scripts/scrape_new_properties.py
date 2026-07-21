"""
Full clean scrape of all active properties.

BEFORE RUNNING:
    1. Delete all existing images:
           rd /s /q data\\images          (Windows)
           rm -rf data/images             (Mac/Linux)
    2. Run this script:
           python scripts/scrape_new_properties.py
    3. Commit results:
           git add data/images/
           git commit -m "Fresh image scrape — all properties"
           git push

The script:
  - Reads properties.json to build the target list automatically
  - Skips rejected/duplicate properties
  - Skips any property whose folder already has ≥3 images (safe to re-run)
  - Extracts images from Rightmove's page JSON (most reliable method)
  - Falls back to img tag scanning if JSON extraction fails
  - Saves photo_01.jpg, photo_02.jpg... and floorplan_01.jpg...
  - Writes manifest.json on completion
  - Adds random delays to avoid rate limiting

Options:
    --only <ref>      Scrape only one property (e.g. --only 169862942)
    --resume          Skip properties that already have any images (default)
    --force           Re-scrape everything even if images exist
"""

import json, os, re, sys, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Find repo root ─────────────────────────────────────────────────────────────
def find_repo_root():
    for c in [Path(__file__).parent, Path(__file__).parent.parent,
              Path.cwd(), Path.cwd().parent]:
        if (c / "data" / "properties.json").exists():
            return c
    print("ERROR: Cannot find repo root"); sys.exit(1)

REPO      = find_repo_root()
DATA_DIR  = REPO / "data"
IMG_DIR   = DATA_DIR / "images"
MANIFEST  = IMG_DIR / "manifest.json"
IMG_DIR.mkdir(parents=True, exist_ok=True)

print(f"Repo root: {REPO}")

ONLY_REF = None
FORCE    = "--force" in sys.argv
for i, arg in enumerate(sys.argv):
    if arg == "--only" and i + 1 < len(sys.argv):
        ONLY_REF = sys.argv[i + 1]

# ── Load properties ────────────────────────────────────────────────────────────
props = json.loads((DATA_DIR / "properties.json").read_text(encoding="utf-8"))
prop_names = {p["ref"]: p["name"] for p in props}

TARGETS = []
for p in sorted(props, key=lambda x: x.get("rank", 99)):
    if p.get("status") == "rejected":      continue
    if p.get("caveat") == "duplicate":     continue
    if not p.get("rightmove_url", ""):     continue
    if ONLY_REF and p["ref"] != ONLY_REF: continue

    url  = p["rightmove_url"].split("#")[0].rstrip("/")
    site = "apex27" if "apex27" in p["ref"] else "rightmove"
    TARGETS.append({
        "ref":  p["ref"],
        "name": p["name"],
        "url":  url,
        "site": site,
        "rank": p.get("rank", 99),
    })

print(f"Properties to scrape: {len(TARGETS)}")

# ── Helpers ────────────────────────────────────────────────────────────────────
def already_done(ref):
    if FORCE: return False
    d     = IMG_DIR / ref
    files = list(d.glob("photo_*.j*")) + list(d.glob("photo_*.png")) if d.exists() else []
    return len(files) >= 3

def download(page, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    try:
        r = page.request.get(url, timeout=25000)
        if r.ok:
            body = r.body()
            if len(body) > 500:
                dest.write_bytes(body)
                return True
    except Exception as e:
        print(f"      ✗ {dest.name}: {e}")
    return False

def extract_rm_images(page):
    """Extract photo and floorplan URLs from Rightmove page JSON data."""
    photos, floors = [], []
    try:
        # Method 1: parse window.PAGE_MODEL from page scripts
        scripts = page.query_selector_all("script:not([src])")
        for s in scripts:
            try:
                text = s.inner_text()
            except Exception:
                continue
            if "PAGE_MODEL" not in text and '"images"' not in text:
                continue

            # Extract all Rightmove media URLs
            found = re.findall(
                r'https://media\.rightmove\.co\.uk/[^\s\'"\\<>]+?\.(?:jpg|jpeg|png|webp)',
                text, re.IGNORECASE
            )
            for u in found:
                u = u.rstrip(".,;)\"'")
                # Normalise: strip crop paths to get full-size image
                u_clean = re.sub(r'/dir/crop/[^/]+/', '/dir/', u)
                u_clean = re.sub(r'_max_\d+x\d+', '', u_clean)
                # Classify
                lower = u_clean.lower()
                if any(x in lower for x in ["flp", "floorplan", "_floor", "floor_"]):
                    if u_clean not in floors:
                        floors.append(u_clean)
                elif "/partner" not in lower and "/assets/" not in lower:
                    if u_clean not in photos:
                        photos.append(u_clean)

        if photos:
            return photos, floors

        # Method 2: img tag fallback
        imgs = page.evaluate("""() => {
            return [...document.querySelectorAll('img[src*="media.rightmove"]')]
                .map(i => i.src)
                .filter(s => s.includes('/dir/') || s.includes('/property-photo/'));
        }""")
        for u in imgs:
            u_clean = re.sub(r'/dir/crop/[^/]+/', '/dir/', u)
            u_clean = re.sub(r'_max_\d+x\d+', '', u_clean)
            lower   = u_clean.lower()
            if any(x in lower for x in ["flp", "floorplan", "_floor"]):
                if u_clean not in floors:
                    floors.append(u_clean)
            elif u_clean not in photos:
                photos.append(u_clean)

    except Exception as e:
        print(f"      ⚠ Image extraction error: {e}")

    return photos, floors


def extract_apex27_images(page, ref_num):
    """Extract images from Apex27 property portal."""
    photos, floors = [], []
    try:
        time.sleep(2)
        # Try fetching image URLs sequentially
        for i in range(60):
            try:
                url = f"https://movingyou-property-details.apex27.co.uk/{ref_num}/images/{i}/large"
                r   = page.request.get(url, timeout=8000)
                if r.ok and r.url not in photos:
                    photos.append(r.url)
                elif not r.ok:
                    if i > 5:  # allow a few misses before stopping
                        break
            except Exception:
                if i > 5:
                    break

        # Fallback: scan img tags
        if not photos:
            found = page.evaluate("""() =>
                [...document.querySelectorAll('img')]
                    .map(i => i.src)
                    .filter(s => s && s.includes('apex27') && s.length > 30)
            """)
            for u in found:
                if "listing_" in u and u not in photos:
                    photos.append(u)

    except Exception as e:
        print(f"      ⚠ Apex27 extraction error: {e}")
    return photos, floors

# ── Main scrape loop ───────────────────────────────────────────────────────────
def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}

    todo = [t for t in TARGETS if not already_done(t["ref"])]
    done = [t for t in TARGETS if     already_done(t["ref"])]

    print(f"Already complete: {len(done)}")
    print(f"To scrape:        {len(todo)}")
    if not todo:
        print("\nAll properties already have images. Use --force to re-scrape.")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox",
                  "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-GB",
            timezone_id="Europe/London",
            extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        # ── Warm up Rightmove ──────────────────────────────────────────────────
        if any(t["site"] == "rightmove" for t in todo):
            print("\nWarming up Rightmove...")
            try:
                page.goto("https://www.rightmove.co.uk",
                          wait_until="domcontentloaded", timeout=20000)
                time.sleep(random.uniform(2, 3))
                # Accept cookies if present
                for sel in ["#onetrust-accept-btn-handler",
                            "button[id*='accept']",
                            "button[class*='accept']"]:
                    try:
                        btn = page.query_selector(sel)
                        if btn:
                            btn.click()
                            time.sleep(0.8)
                            break
                    except Exception:
                        pass
                print("  Rightmove ready")
            except Exception as e:
                print(f"  Warmup warning: {e}")

        errors = []

        for idx, target in enumerate(todo, 1):
            ref  = target["ref"]
            name = target["name"]
            url  = target["url"]
            site = target["site"]
            rank = target["rank"]
            ref_dir = IMG_DIR / ref

            print(f"\n{'─'*62}")
            print(f"  [{idx}/{len(todo)}] #{rank} {name}")
            print(f"  {url}")

            ref_dir.mkdir(parents=True, exist_ok=True)

            # ── Navigate ───────────────────────────────────────────────────────
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.5, 4.0))
            except Exception as e:
                print(f"  ✗ Navigation failed: {e}")
                errors.append(f"#{rank} {name}: navigation failed")
                continue

            # ── Extract image URLs ─────────────────────────────────────────────
            if site == "apex27":
                ref_num = re.search(r'/(\d+)$', url)
                ref_num = ref_num.group(1) if ref_num else "885144"
                photo_urls, floor_urls = extract_apex27_images(page, ref_num)
            else:
                photo_urls, floor_urls = extract_rm_images(page)

            print(f"  Found: {len(photo_urls)} photos, {len(floor_urls)} floorplans")

            if not photo_urls and not floor_urls:
                print(f"  ⚠ No images found — check URL manually")
                errors.append(f"#{rank} {name}: no images found")
                continue

            # ── Download photos ────────────────────────────────────────────────
            saved_p, saved_f = [], []

            for j, img_url in enumerate(photo_urls, 1):
                ext  = Path(img_url.split("?")[0]).suffix.lower() or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                    ext = ".jpg"
                dest = ref_dir / f"photo_{j:02d}{ext}"
                print(f"    photo {j:>2}/{len(photo_urls)}", end=" ", flush=True)
                ok = download(page, img_url, dest)
                print("✓" if ok else "✗")
                if ok:
                    saved_p.append(str(dest.relative_to(REPO)).replace("\\", "/"))
                time.sleep(random.uniform(0.2, 0.5))

            for j, img_url in enumerate(floor_urls[:4], 1):
                ext  = Path(img_url.split("?")[0]).suffix.lower() or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                    ext = ".jpg"
                dest = ref_dir / f"floorplan_{j:02d}{ext}"
                print(f"    floorplan {j}", end=" ", flush=True)
                ok = download(page, img_url, dest)
                print("✓" if ok else "✗")
                if ok:
                    saved_f.append(str(dest.relative_to(REPO)).replace("\\", "/"))

            # ── Update manifest ────────────────────────────────────────────────
            manifest[ref] = {
                "name":      prop_names.get(ref, name),
                "photos":    saved_p,
                "floorplans": saved_f,
            }
            MANIFEST.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"  ✓ Saved {len(saved_p)} photos, {len(saved_f)} floorplans")

            # ── Pause between properties ───────────────────────────────────────
            if idx < len(todo):
                delay = random.uniform(5, 10)
                print(f"  Waiting {delay:.1f}s...")
                time.sleep(delay)

        browser.close()

    # ── Final report ──────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"Scrape complete.")
    print(f"  Scraped:  {len(todo)} properties")
    print(f"  Skipped:  {len(done)} (already had images)")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for e in errors:
            print(f"    ⚠ {e}")
    print(f"\nManifest: {MANIFEST}")
    print(f"\nNext steps:")
    print(f"  git add data/images/")
    print(f"  git commit -m 'Fresh image scrape — all properties'")
    print(f"  git push")

if __name__ == "__main__":
    main()
