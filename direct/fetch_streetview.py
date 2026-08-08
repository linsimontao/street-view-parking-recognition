"""Fetch real Google Street View captures of Japanese parking lots.

Why this exists: japanese_coin_parkings/ is web-scraped promotional photography --
clean framing, sign facing the lens, good light. Street View is the actual
deployment domain: oblique angles, distance, motion blur, occlusion by cars and
poles. A model scoring 100% on the scraped set says nothing about this one.

Pipeline per location:
  Places searchText  -> coordinates of a real parking lot
  Street View metadata (FREE) -> does a panorama exist near it?
  Street View image (BILLED)  -> only for locations that passed the check

Heading is deliberately left unset: the API then aims the camera at the requested
coordinates from wherever the nearest panorama was shot, which is exactly the
"drive past and look at it" framing we want.

    export GOOGLE_MAPS_API_KEY=...
    python direct/fetch_streetview.py --query コインパーキング --label coin_parking --max-images 5
"""

import argparse
import json
import math
import os
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
SV_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
SV_IMAGE = "https://maps.googleapis.com/maps/api/streetview"

# Street View Static is billed per image. Nothing here may exceed this without an
# explicit decision -- the cap is a hard stop, not a default.
HARD_CAP = 500

CITIES = [
    "東京", "大阪", "名古屋", "横浜", "福岡", "札幌", "京都", "神戸", "仙台",
    "広島", "さいたま", "千葉", "川崎", "北九州", "静岡", "岡山", "熊本",
    "新潟", "浜松", "金沢", "松山", "鹿児島", "宇都宮", "松本", "長崎",
]


def search_places(key, query, city, want):
    body = {"textQuery": f"{query} {city}", "maxResultCount": min(want, 20),
            "languageCode": "ja"}
    r = requests.post(
        PLACES_URL, json=body, timeout=30,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                 "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress"},
    )
    if r.status_code != 200:
        print(f"  places '{city}' failed [{r.status_code}]: {r.text[:160]}")
        return []
    return r.json().get("places", [])


def metres_between(lat1, lng1, lat2, lng2):
    """Rough great-circle distance; at these scales the approximation is fine."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pano_at(key, lat, lng, radius):
    """Free metadata lookup. Returns the pano record or None."""
    r = requests.get(SV_META, timeout=30,
                     params={"location": f"{lat},{lng}", "radius": radius, "key": key})
    if r.status_code != 200:
        return None
    d = r.json()
    return d if d.get("status") == "OK" else None


def fetch_image(key, lat, lng, size, fov, pitch, radius, dest):
    r = requests.get(SV_IMAGE, timeout=60, params={
        "location": f"{lat},{lng}", "size": size, "fov": fov, "pitch": pitch,
        "radius": radius, "source": "outdoor", "return_error_code": "true", "key": key,
    })
    if r.status_code != 200 or not r.content.startswith(b"\xff\xd8"):
        return f"HTTP {r.status_code}: {r.text[:120]}"
    dest.write_bytes(r.content)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="コインパーキング")
    parser.add_argument("--label", default="coin_parking",
                        help="output subdirectory and filename prefix")
    parser.add_argument("--out-dir", type=Path,
                        default=PROJECT_ROOT / "streetview")
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--per-city", type=int, default=20)
    parser.add_argument("--size", default="640x640")
    parser.add_argument("--fov", type=int, default=110,
                        help="wider than the 80 default keeps the lot in frame when "
                             "the camera is close to it")
    parser.add_argument("--max-pano-distance", type=float, default=25,
                        help="drop locations whose nearest panorama is further than "
                             "this many metres away")
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--radius", type=int, default=40,
                        help="metres to search for a panorama near the coordinates")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="seconds between requests -- keep concurrency at one")
    parser.add_argument("--cities", nargs="*", default=CITIES)
    parser.add_argument("--exclude-manifest", nargs="*", type=Path, default=[],
                        help="manifests from earlier runs; their place ids and "
                             "pano ids are skipped so a second batch does not "
                             "re-buy images we already have")
    parser.add_argument("--start-index", type=int, default=1,
                        help="first filename number, to append to an existing set")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="override the manifest path so a second batch does "
                             "not overwrite the first one's record")
    parser.add_argument("--dry-run", action="store_true",
                        help="do the free steps only; report how many images WOULD be billed")
    args = parser.parse_args()

    if args.max_images > HARD_CAP:
        raise SystemExit(f"--max-images {args.max_images} exceeds the {HARD_CAP} cap")

    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise SystemExit("set GOOGLE_MAPS_API_KEY in the environment first")

    out = args.out_dir / args.label
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or args.out_dir / f"{args.label}_manifest.jsonl"

    seen_place, seen_pano = set(), set()
    for m in args.exclude_manifest:
        for line in m.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                seen_pano.add(r.get("pano_id"))
                if r.get("place_id"):
                    seen_place.add(r["place_id"])
    if seen_pano:
        print(f"excluding {len(seen_pano)} panoramas from earlier runs")

    records, billed, skipped = [], 0, 0

    for city in args.cities:
        if billed >= args.max_images:
            break
        places = search_places(key, args.query, city, args.per_city)
        time.sleep(args.delay)
        print(f"[{city}] {len(places)} places", flush=True)

        for p in places:
            if billed >= args.max_images:
                break
            pid = p.get("id")
            if not pid or pid in seen_place:
                continue
            seen_place.add(pid)
            loc = p.get("location") or {}
            lat, lng = loc.get("latitude"), loc.get("longitude")
            if lat is None:
                continue

            meta = pano_at(key, lat, lng, args.radius)
            time.sleep(args.delay)
            if not meta:
                skipped += 1
                continue
            # Two nearby lots can resolve to the same panorama; that would be the
            # same photograph filed twice under different names.
            pano = meta.get("pano_id")
            if pano in seen_pano:
                skipped += 1
                continue

            # The camera aims at the coordinates from wherever the nearest
            # panorama sits. When that panorama is far away the lot ends up
            # behind a building or off the edge of the frame -- the first probe
            # produced exactly that failure. Reject it before paying for the image.
            ploc = meta.get("location") or {}
            dist = metres_between(lat, lng, ploc.get("lat", lat), ploc.get("lng", lng))
            if dist > args.max_pano_distance:
                skipped += 1
                continue
            seen_pano.add(pano)

            idx = args.start_index + billed
            name = f"{args.label}_sv_{idx:03d}.jpg"
            rec = {
                "file": str((out / name).relative_to(PROJECT_ROOT)),
                "label": args.label,
                "query": args.query, "city": city,
                "place_id": pid,
                "place_name": (p.get("displayName") or {}).get("text"),
                "address": p.get("formattedAddress"),
                "place_lat": lat, "place_lng": lng,
                "pano_id": pano, "pano_date": meta.get("date"),
                "pano_distance_m": round(dist, 1),
                "copyright": meta.get("copyright"),
            }

            if args.dry_run:
                billed += 1
                records.append(rec)
                continue

            err = fetch_image(key, lat, lng, args.size, args.fov, args.pitch,
                              args.radius, out / name)
            time.sleep(args.delay)
            if err:
                print(f"  image failed: {err}", flush=True)
                skipped += 1
                continue
            billed += 1
            records.append(rec)
            print(f"  [{billed}/{args.max_images}] {name}  {rec['place_name']}  "
                  f"({rec['pano_date']})", flush=True)

    manifest_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))

    verb = "would fetch" if args.dry_run else "fetched"
    print(f"\n{verb} {billed} images, skipped {skipped} "
          f"(no panorama / duplicate pano / error)")
    print(f"manifest -> {manifest_path}")
    if not args.dry_run:
        print(f"images   -> {out}")


if __name__ == "__main__":
    main()
