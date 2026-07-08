"""
Rebuild data/images/manifest.json from whatever image files
actually exist in data/images/ in your repo.

Run from the repo root:
    python scripts/rebuild_manifest.py

This fixes the problem where photos don't show in the app.
"""
import json, os
from pathlib import Path

os.chdir(Path(__file__).parent.parent if Path(__file__).parent.name == "scripts"
         else Path(__file__).parent)

IMAGES_DIR = Path("data/images")
MANIFEST   = IMAGES_DIR / "manifest.json"
PROPS_FILE = Path("data/properties.json")

props = json.load(open(PROPS_FILE, encoding="utf-8"))
prop_names = {p["ref"]: p["name"] for p in props}

manifest = {}
rebuilt = 0

for ref_dir in sorted(IMAGES_DIR.iterdir()):
    if not ref_dir.is_dir():
        continue
    ref = ref_dir.name
    
    photos    = sorted([f for f in ref_dir.iterdir()
                        if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')
                        and 'photo_' in f.name],
                       key=lambda x: x.name)
    floorplans = sorted([f for f in ref_dir.iterdir()
                         if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')
                         and 'floorplan_' in f.name],
                        key=lambda x: x.name)
    
    if not photos and not floorplans:
        continue
    
    # Always use forward slashes
    manifest[ref] = {
        "name": prop_names.get(ref, ref),
        "photos":     [str(p).replace("\\", "/") for p in photos],
        "floorplans": [str(f).replace("\\", "/") for f in floorplans],
    }
    rebuilt += 1
    print(f"  {ref}: {len(photos)} photos, {len(floorplans)} floorplans")

with open(MANIFEST, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

print(f"\n✓ Rebuilt manifest: {rebuilt} properties")
print(f"  Saved to {MANIFEST}")
print(f"\nNext: git add data/images/manifest.json && git commit -m 'Rebuild image manifest' && git push")
