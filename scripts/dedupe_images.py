"""
Deduplicates photos in data/images/ by content hash.
Run from the repo root:
    python scripts/dedupe_images.py

What it does:
  1. For each property's image folder, hashes every file (MD5)
  2. Keeps the FIRST occurrence of each unique image, deletes the rest
  3. Rebuilds manifest.json with only the unique files, in correct order
  4. Prints a summary of how many files were removed

Safe to run multiple times (idempotent).
"""

import hashlib, json, os, sys
from pathlib import Path

def find_repo_root():
    for c in [Path(__file__).parent, Path(__file__).parent.parent, Path.cwd(), Path.cwd().parent]:
        if (c / "data" / "properties.json").exists():
            return c
    print("ERROR: Could not find repo root (looking for data/properties.json)")
    sys.exit(1)

REPO      = find_repo_root()
IMG_DIR   = REPO / "data" / "images"
MANIFEST  = IMG_DIR / "manifest.json"
PROPS     = json.loads((REPO / "data" / "properties.json").read_text(encoding="utf-8"))

def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
prop_names = {p["ref"]: p["name"] for p in PROPS}

total_before = total_after = total_deleted = 0

for ref_dir in sorted(IMG_DIR.iterdir()):
    if not ref_dir.is_dir() or ref_dir.name.startswith("_"):
        continue
    ref = ref_dir.name

    # Collect all image files
    all_files = sorted(
        [f for f in ref_dir.iterdir()
         if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
        key=lambda f: f.name
    )
    if not all_files:
        continue

    total_before += len(all_files)

    # Hash every file and build dedup map
    seen_hashes = {}   # hash -> first Path that had it
    unique_photos    = []
    unique_floorplans = []
    deleted = []

    for f in all_files:
        try:
            h = md5(f)
        except Exception as e:
            print(f"  Warning: could not hash {f}: {e}")
            continue

        if h in seen_hashes:
            # Duplicate — delete it
            f.unlink()
            deleted.append(f.name)
        else:
            seen_hashes[h] = f
            fname = f.name.lower()
            if "floorplan" in fname:
                unique_floorplans.append(str(f.relative_to(REPO)).replace("\\", "/"))
            else:
                unique_photos.append(str(f.relative_to(REPO)).replace("\\", "/"))

    total_after   += len(unique_photos) + len(unique_floorplans)
    total_deleted += len(deleted)

    name = prop_names.get(ref, ref)
    before = len(all_files)
    after  = len(unique_photos) + len(unique_floorplans)
    if deleted:
        print(f"  {ref} ({name[:35]}): {before} → {after} photos  (-{len(deleted)} duplicates)")
    else:
        print(f"  {ref} ({name[:35]}): {before} photos  (no duplicates)")

    # Update manifest
    manifest[ref] = {
        "name":       name,
        "photos":     unique_photos,
        "floorplans": unique_floorplans,
    }

MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n{'='*55}")
print(f"Total before: {total_before} files")
print(f"Total after:  {total_after} files")
print(f"Deleted:      {total_deleted} duplicate files")
print(f"Manifest updated: {MANIFEST}")
print(f"\nNext steps:")
print(f"  git add data/images/ data/images/manifest.json")
print(f"  git commit -m 'Deduplicate property photos'")
print(f"  git push")
