"""
Looks up broadband availability for each property using Ofcom's Connected Nations
2025 open data (postcode-level CSV). Downloads and caches the dataset on first run.

Run from repo root:
    python scripts/update_broadband.py

Options:
    --dry-run   Show what would change without writing files
    --force     Re-check postcodes that already have confirmed 3/3 scores
    --refresh   Re-download the Ofcom dataset even if cached
"""

import csv, io, json, sys, urllib.request, zipfile
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
FORCE   = "--force"   in sys.argv
REFRESH = "--refresh" in sys.argv

def find_repo_root():
    for c in [Path(__file__).parent, Path(__file__).parent.parent,
              Path.cwd(), Path.cwd().parent]:
        if (c / "data" / "properties.json").exists():
            return c
    print("ERROR: Cannot find repo root"); sys.exit(1)

REPO      = find_repo_root()
CACHE_DIR = REPO / ".broadband_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_CSV = CACHE_DIR / "ofcom_broadband_2025.csv"
PROPS_F   = REPO / "data" / "properties.json"
SC_F      = REPO / "data" / "scorecards.json"
NOTES_F   = REPO / "data" / "notes.json"

OFCOM_ZIP_URL = (
    "https://www.ofcom.org.uk/siteassets/resources/documents/research-and-data"
    "/multi-sector/infrastructure-research/connected-nations-2025"
    "/202507_fixed_broadband_coverage_r01.zip"
)

POSTCODES = {
    "166496951":     "BH9 3NQ",   # Plassey Cres, Bournemouth
    "88185459":      "SA6 5QL",   # Pantygyfelia Farm, Bonymaen
    "169862942":     "TA4 3BJ",   # Tithill, Bishops Lydeard
    "90443352":      "TA1 4AJ",   # Manor Road, Taunton
    "173348153":     "DT11 0NQ",  # Winterborne Stickland
    "89951784":      "NP4 8PH",   # Pentrepiod Rd, Pontypool
    "apex27_885144": "SA8 3AN",   # 60 Gwyn St, Alltwen
    "89061840":      "TA20 3HG",  # Oakfields, Ham
    "87791562":      "SN12 6JR",  # Halifax Rd, Melksham
    "90542934":      "BA14 8EP",  # Avonvale Road, Trowbridge
    "168359045":     "SA3 4TY",   # Highmead Ave, Newton Swansea
    "174472451":     "TA20 2NF",  # Arch View, Tatworth
    "173985596":     "TA6 5DH",   # Bridgwater 5-bed
    "172902734":     "BA14 0XZ",  # Halfway Close, Trowbridge
    "168243473":     "BH23 2NA",  # Stroud Park Ave, Christchurch
    "173546681":     "TA20 1NN",  # Kents Close, Chard (approx)
    "88996269":      "NP4 0BG",   # Penperlleni
    "172773251":     "DT11 7BU",  # White Cliff Gardens, Blandford
    "89491017":      "SA34 0DS",  # Cwmbach, Whitland
    "169598735":     "SA10 7DT",  # Hill Rd, Neath Abbey
    "88310844":      "TA7 0EB",   # Westonzoyland
    "89415939":      "NP20 3QH",  # Queens Hill, Newport
    "88156767":      "SN15 1AS",  # Bramble Drive, Chippenham
    "168382466":     "TA7 9AD",   # Brook Lane, Catcott
    "170605958":     "EX16 9LJ",  # Brook St, Bampton
    "90125946":      "BH8 9PQ",   # Damerham Rd, Throop
    "160507001":     "SA33 6JP",  # Llanpumsaint
    "87130665":      "BA22 8RR",  # Wraxhill Rd, Yeovil
    "89701968":      "DT6 3SA",   # Loders, Bridport
    "89444523":      "DT6 6JN",   # Chideock
    "89236248":      "BA14 8SP",  # St Thomas Rd, Trowbridge
    "88318344":      "SN6 6AU",   # Thames Close, Cricklade
}

def download_ofcom():
    if CACHE_CSV.exists() and not REFRESH:
        print(f"Using cached Ofcom data ({CACHE_CSV.stat().st_size//1024//1024}MB)")
        return True
    print(f"Downloading Ofcom Connected Nations 2025 data...")
    try:
        req = urllib.request.Request(OFCOM_ZIP_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        print(f"  Downloaded {len(data)//1024//1024}MB")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            print(f"  ZIP contents: {names}")
            # The postcode file is 202507_fixed_pc_coverage_r01.zip (nested ZIP)
            # 'pc' = postcode level; 'pcon' = parliamentary constituency — avoid pcon
            pc_zip = next(
                (n for n in names if n.endswith(".zip")
                 and "_pc_" in n and "pcon" not in n), None)
            if pc_zip:
                print(f"  Found nested postcode ZIP: {pc_zip}")
                inner_zip_bytes = z.read(pc_zip)
                with zipfile.ZipFile(io.BytesIO(inner_zip_bytes)) as z2:
                    inner_names = z2.namelist()
                    print(f"  Inner ZIP contents: {inner_names}")
                    target = next(
                        (n for n in inner_names if n.endswith(".csv")), inner_names[0])
                    print(f"  Extracting: {target}")
                    CACHE_CSV.write_bytes(z2.read(target))
            else:
                # Fallback: look for a postcode CSV directly (not pcon)
                target = next(
                    (n for n in names if "_pc_" in n and n.endswith(".csv")
                     and "pcon" not in n),
                    next((n for n in names if n.endswith(".csv")), names[0])
                )
                print(f"  Extracting: {target}")
                CACHE_CSV.write_bytes(z.read(target))
        print(f"  Cached: {CACHE_CSV} ({CACHE_CSV.stat().st_size//1024//1024}MB)")
        return True
    except Exception as e:
        print(f"\nERROR downloading: {e}")
        print(f"Download manually from Ofcom Connected Nations 2025 page")
        print(f"and save the postcode CSV as:\n  {CACHE_CSV}")
        return False

def load_index():
    print("Loading Ofcom index...")
    idx = {}
    with open(CACHE_CSV, encoding="cp1252", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        print(f"  Columns: {cols[:10]}")
        for row in reader:
            pc = (row.get("postcode") or row.get("Postcode") or
                  row.get("POSTCODE") or row.get("pcds") or
                  row.get("pcd") or "").replace(" ", "").upper()
            if pc:
                idx[pc] = row
    print(f"  {len(idx):,} postcodes loaded\n")
    return idx

def lookup(idx, postcode):
    key = postcode.replace(" ", "").upper()
    row = idx.get(key)
    sfx = ""
    if not row:
        district = key[:4]
        cands = [v for k, v in idx.items() if k.startswith(district)]
        if cands:
            row = cands[0]
            sfx = f" (district estimate — exact postcode not found)"
        else:
            return 0, f"Postcode {postcode} not in Ofcom dataset", False

    def f(keys):
        for k in keys:
            for var in [k, k.lower(), k.upper(),
                        k.replace("_"," "), k.lower().replace("_"," ")]:
                v = row.get(var)
                if v not in (None, "", "N/A", "n/a", "-"):
                    try:
                        return float(str(v).replace(",","").replace("%","").strip())
                    except ValueError:
                        pass
        return 0.0

    # Ofcom postcode CSV 2025 column names (lowercase with underscores)
    fttp = f(["fttp_availability","FTTP_availability","FTTP","fttp",
               "full_fibre_availability","Full Fibre availability (% premises)",
               "full fibre availability (% premises)"])
    ufbb = f(["ufbb_availability","UFBB_availability","UFBB","ufbb",
               "ultrafast_availability","ufbb (100mbit/s) availability (% premises)",
               "UFBB (100Mbit/s) availability (% premises)",
               "ufbb availability (% premises)",
               "UFBB availability (% premises)",
               "Gigabit availability (% premises)","gigabit_availability"])
    sfbb = f(["sfbb_availability","SFBB_availability","SFBB","sfbb",
               "superfast_availability",
               "SFBB availability (% premises)","sfbb availability (% premises)"])
    down = f(["max_download_speed","MaxBBDown","maxbbdown","max_download",
               "max_down","average_download_speed","avg_download"])
    up   = f(["max_upload_speed","MaxBBUp","maxbbup","max_upload",
               "max_up","average_upload_speed","avg_upload"])

    spd = ""
    if down: spd += f"{int(down)}Mb↓"
    if up:   spd += f" {int(up)}Mb↑"
    if not spd: spd = "speed data unavailable"

    if fttp >= 50 or down >= 900:
        return 3, f"Full fibre (FTTP) available — {spd} ✓{sfx}", True
    elif ufbb >= 50 or down >= 300:
        return 3, f"Ultrafast ({int(ufbb)}% coverage) — {spd} ✓{sfx}", True
    elif fttp > 0 or ufbb > 0:
        return 2, f"Partial FTTP/ultrafast ({int(max(fttp,ufbb))}%) — {spd}{sfx}", True
    elif sfbb >= 90:
        return 2, f"Superfast ({int(sfbb)}% coverage) — {spd}{sfx}", True
    elif sfbb > 0:
        return 1, f"Superfast partial ({int(sfbb)}%) — {spd}{sfx}", True
    elif down > 0:
        return 1, f"Basic broadband — {spd}{sfx}", True
    else:
        return 0, f"No coverage data for {postcode}{sfx}", False

def main():
    props  = json.loads(PROPS_F.read_text(encoding="utf-8"))
    sc_all = json.loads(SC_F.read_text(encoding="utf-8"))
    try:
        notes = json.loads(NOTES_F.read_text(encoding="utf-8"))
    except Exception:
        notes = {}

    chain_status = notes.get("chainStatus", {})
    PENALTIES = {"flood":-15,"flood-check":-8,"ferry":-20,"prc":-12,
                 "logistics":-10,"duplicate":-50,"bungalow":-5,
                 "knotweed":-10,"project":-15}
    CHAIN_BONUS = {"no_chain":10,"chain_breaker":8,"park_home":8,
                   "new_build":3,"chain":0,"unknown":0}

    active = {p["ref"] for p in props
              if p.get("status") not in ("rejected",)
              and p.get("caveat") not in ("duplicate",)}

    if not download_ofcom():
        sys.exit(1)

    idx = load_index()

    print(f"{'DRY RUN — ' if DRY_RUN else ''}Checking {len(POSTCODES)} postcodes\n")
    print(f"  {'#':>3}  {'Property':<36}  {'Postcode':<9}  {'Scr'}  Note")
    print(f"  {'─'*3}  {'─'*36}  {'─'*9}  {'─'*3}  {'─'*45}")

    changes, skipped = [], []

    by_rank = sorted(
        POSTCODES.items(),
        key=lambda x: next(
            (p.get("rank", 99) for p in props if p["ref"] == x[0]), 99)
    )

    for ref, postcode in by_rank:
        p = next((x for x in props if x["ref"] == ref), None)
        if not p:
            continue
        name = p.get("name", ref)
        rank = p.get("rank", "?")

        sc = sc_all.get(ref)
        if not sc:
            print(f"  {str(rank):>3}  {name[:36]:<36}  {postcode:<9}  ⚠   no scorecard")
            continue

        existing = next(
            (s for s in sc.get("scores", []) if s["label"] == "Broadband"), None)

        if (existing and existing.get("resolved")
                and existing.get("score", 0) >= 3
                and not FORCE and ref in active):
            skipped.append(name)
            print(f"  {str(rank):>3}  {name[:36]:<36}  {postcode:<9}  —   skip (already 3/3)")
            continue

        score, note, resolved = lookup(idx, postcode)
        old_score = existing.get("score", -1) if existing else -1

        sym = "✓" if score >= 3 else "~" if score >= 2 else "✗"
        chg = "  ← CHANGED" if score != old_score else ""
        print(f"  {str(rank):>3}  {name[:36]:<36}  {postcode:<9}  {sym}{score}  {note[:45]}{chg}")

        if existing:
            existing.update({"score": score, "note": note, "resolved": resolved})
        else:
            sc.setdefault("scores", []).append({
                "cat": "Connectivity", "label": "Broadband",
                "score": score, "note": note, "resolved": resolved,
            })

        mx = len(sc["scores"]) * 3
        sc["overall_pct"] = round(
            sum(s["score"] for s in sc["scores"]) / mx * 100) if mx else 0
        sc_all[ref] = sc

        if score != old_score:
            changes.append((rank, name, old_score, score, note))

    # Rerank
    scored = sorted(
        [(sc_all.get(p["ref"], {}).get("overall_pct", 0)
          + PENALTIES.get(p.get("caveat"), 0)
          + CHAIN_BONUS.get(chain_status.get(p["ref"], "unknown"), 0),
          p["ref"]) for p in props],
        reverse=True
    )
    for i, (_, r) in enumerate(scored, 1):
        next(p for p in props if p["ref"] == r)["rank"] = i

    if not DRY_RUN:
        SC_F.write_text(json.dumps(sc_all, indent=2, ensure_ascii=False), encoding="utf-8")
        PROPS_F.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ Saved scorecards.json and properties.json")

    print(f"\n{'='*65}")
    print(f"Changed:  {len(changes)}")
    print(f"Skipped:  {len(skipped)} already confirmed (use --force to recheck)")
    if changes:
        print("\nChanges made:")
        for rank, name, old, new, note in changes:
            arrow = f"{old}→{new}" if old >= 0 else f"new:{new}"
            print(f"  #{rank:>2}  {name[:42]}  {arrow}/3  {note[:55]}")
    if changes and not DRY_RUN:
        print("\nNext:")
        print("  git add data/scorecards.json data/properties.json")
        print("  git commit -m 'Update broadband scores from Ofcom 2025'")
        print("  git push")

if __name__ == "__main__":
    main()
