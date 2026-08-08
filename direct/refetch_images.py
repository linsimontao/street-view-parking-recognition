"""Re-download the benchmark images from their manifests.

The images themselves are deliberately not in this repository. Google Maps
Platform terms do not permit redistributing Street View imagery, so what is
committed is the provenance -- pano id, coordinates, capture date -- which is
enough for anyone with their own API key to reconstruct the exact benchmark.

Fetching by pano_id (not by coordinates) is what makes this reproducible: the
panorama at a given location changes when the car drives past again, but a
pano_id always resolves to the same photograph.

    export GOOGLE_MAPS_API_KEY=...
    python direct/refetch_images.py --dry-run     # count and cost first
    python direct/refetch_images.py
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SV_IMAGE = "https://maps.googleapis.com/maps/api/streetview"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", type=Path,
                        default=HERE / "data" / "testset_streetview.jsonl")
    parser.add_argument("--manifest-dir", type=Path, default=HERE / "data")
    parser.add_argument("--out-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--size", default="640x640")
    parser.add_argument("--fov", type=int, default=110)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wanted = [json.loads(l)["file"]
              for l in args.testset.read_text().splitlines() if l.strip()]
    meta = {}
    for m in sorted(args.manifest_dir.glob("manifest_*.jsonl")):
        for line in m.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                meta[r["file"]] = r

    missing_meta = [f for f in wanted if f not in meta]
    todo = [f for f in wanted if f in meta and not (args.out_root / f).exists()]

    print(f"benchmark: {len(wanted)} images")
    print(f"  already on disk: {len(wanted) - len(todo) - len(missing_meta)}")
    print(f"  to fetch:        {len(todo)}")
    if missing_meta:
        print(f"  NO PROVENANCE:   {len(missing_meta)} -> {missing_meta[:3]}")
    if args.dry_run:
        print("\ndry run: each fetch is one billed Street View Static request")
        return

    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise SystemExit("set GOOGLE_MAPS_API_KEY in the environment first")

    ok = failed = 0
    for i, f in enumerate(todo, 1):
        rec = meta[f]
        dest = args.out_root / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(SV_IMAGE, timeout=60, params={
            "pano": rec["pano_id"], "size": args.size, "fov": args.fov,
            "pitch": 0, "return_error_code": "true", "key": key,
        })
        if r.status_code == 200 and r.content.startswith(b"\xff\xd8"):
            dest.write_bytes(r.content)
            ok += 1
        else:
            failed += 1
            print(f"  [{i}/{len(todo)}] FAILED {f}: HTTP {r.status_code}")
        time.sleep(args.delay)
        if i % 25 == 0:
            print(f"  [{i}/{len(todo)}] ok={ok} failed={failed}", flush=True)

    print(f"\nfetched {ok}, failed {failed}")
    if failed:
        print("A pano can be withdrawn by Google; those images cannot be recovered "
              "and the affected rows should be dropped from the benchmark.")


if __name__ == "__main__":
    main()
