"""Seed mock DB per DESCRIPTION.md section 2.

Wipe and re-create by default; --keep adds missing rows. Deterministic
fixed seed, so a fresh run always yields the same dataset.
"""

# /// script
# requires-python = ">=3.14"
# dependencies = ["pymongo", "faker"]
# ///

from __future__ import annotations

import argparse
import os
import random
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from faker import Faker
from pymongo import ASCENDING, MongoClient

DB_NAME = "drone_detect_app"
N_DRONES = 50
N_OWNERS = 25
SEED = 20260609

# airframe/family feed the resolver; keep each model on its real airframe.
MODEL_CATALOG: list[dict[str, object]] = [
    {
        "mfr": "DJI",
        "model": "Mavic 3",
        "ver": "Classic",
        "family": "Mavic",
        "air": "quadcopter",
        "cat": "consumer",
        "w": 895,
    },
    {
        "mfr": "DJI",
        "model": "Mini 4 Pro",
        "ver": "",
        "family": "Mini",
        "air": "quadcopter",
        "cat": "consumer",
        "w": 249,
    },
    {
        "mfr": "DJI",
        "model": "Avata 2",
        "ver": "",
        "family": "Avata",
        "air": "quadcopter",
        "cat": "consumer",
        "w": 377,
    },
    {
        "mfr": "DJI",
        "model": "Matrice 350 RTK",
        "ver": "",
        "family": "Matrice",
        "air": "quadcopter",
        "cat": "industrial",
        "w": 6700,
    },
    {
        "mfr": "DJI",
        "model": "Inspire 3",
        "ver": "",
        "family": "Inspire",
        "air": "quadcopter",
        "cat": "professional",
        "w": 3995,
    },
    {
        "mfr": "DJI",
        "model": "Phantom 4",
        "ver": "Pro V2.0",
        "family": "Phantom",
        "air": "quadcopter",
        "cat": "consumer",
        "w": 1375,
    },
    {
        "mfr": "Autel",
        "model": "EVO II",
        "ver": "Pro V3",
        "family": "EVO",
        "air": "quadcopter",
        "cat": "professional",
        "w": 1191,
    },
    {
        "mfr": "Autel",
        "model": "EVO Max 4T",
        "ver": "",
        "family": "EVO",
        "air": "quadcopter",
        "cat": "industrial",
        "w": 1600,
    },
    {
        "mfr": "Parrot",
        "model": "Anafi",
        "ver": "Ai",
        "family": "Anafi",
        "air": "quadcopter",
        "cat": "professional",
        "w": 898,
    },
    {
        "mfr": "Parrot",
        "model": "Disco",
        "ver": "",
        "family": "Disco",
        "air": "fixed_wing",
        "cat": "consumer",
        "w": 750,
    },
    {
        "mfr": "Skydio",
        "model": "X10",
        "ver": "",
        "family": "X",
        "air": "quadcopter",
        "cat": "industrial",
        "w": 2100,
    },
    {
        "mfr": "Yuneec",
        "model": "Typhoon H",
        "ver": "Plus",
        "family": "Typhoon",
        "air": "hexacopter",
        "cat": "professional",
        "w": 1633,
    },
    {
        "mfr": "Freefly",
        "model": "Alta 8",
        "ver": "",
        "family": "Alta",
        "air": "octocopter",
        "cat": "industrial",
        "w": 6200,
    },
    {
        "mfr": "senseFly",
        "model": "eBee X",
        "ver": "",
        "family": "eBee",
        "air": "fixed_wing",
        "cat": "industrial",
        "w": 1400,
    },
    {
        "mfr": "Wingtra",
        "model": "WingtraOne",
        "ver": "GEN II",
        "family": "WingtraOne",
        "air": "vtol",
        "cat": "industrial",
        "w": 3700,
    },
    {
        "mfr": "Schiebel",
        "model": "Camcopter S-100",
        "ver": "",
        "family": "Camcopter",
        "air": "helicopter",
        "cat": "industrial",
        "w": 2000,
    },
    {
        "mfr": "iFlight",
        "model": "Nazgul",
        "ver": "Evoque F5",
        "family": "Nazgul",
        "air": "quadcopter",
        "cat": "racing",
        "w": 600,
    },
    {
        "mfr": "EMAX",
        "model": "Tinyhawk III",
        "ver": "",
        "family": "Tinyhawk",
        "air": "quadcopter",
        "cat": "racing",
        "w": 50,
    },
]

ZONES: list[dict[str, object]] = [
    {
        "_id": "north-gate",
        "name": "North Gate",
        "desc": "Entrance area, camera cam-01",
        "level": "low",
        "cams": ["cam-01"],
    },
    {
        "_id": "warehouse-yard",
        "name": "Warehouse Yard",
        "desc": "Logistics yard, camera cam-02",
        "level": "medium",
        "cams": ["cam-02"],
    },
    {
        "_id": "fuel-depot",
        "name": "Fuel Depot",
        "desc": "Restricted fuel storage, camera cam-03",
        "level": "high",
        "cams": ["cam-03"],
    },
    {
        "_id": "airport-approach",
        "name": "Airport Approach",
        "desc": "No-fly corridor, camera cam-04",
        "level": "no-fly",
        "cams": ["cam-04"],
    },
]

FLYABLE_ZONES = ["north-gate", "warehouse-yard", "fuel-depot"]
COLORS = ["grey", "black", "white", "orange", "blue", "green", "red"]
PURPOSES = ["survey", "inspection", "filming", "delivery", "security"]
SERIAL_PREFIX = {
    "DJI": "158",
    "Autel": "174",
    "Parrot": "PF7",
    "Skydio": "SKX",
    "Yuneec": "YUN",
    "Freefly": "FFA",
    "senseFly": "SFE",
    "Wingtra": "WTR",
    "Schiebel": "SCH",
    "iFlight": "IFN",
    "EMAX": "EMX",
}

# Positions with bad status or no Remote ID.
STOLEN_IDX = {31, 32}
REVOKED_STATUS_IDX = {33, 34}
DECOMMISSIONED_IDX = {46}
NO_REMOTE_ID_IDX = {5, 20, 33, 38, 39, 46}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed the drone_detect_app MongoDB database.")
    p.add_argument("--keep", action="store_true", help="keep existing data, only add missing rows")
    p.add_argument(
        "--drop-only",
        action="store_true",
        help="drop the database and exit without seeding (clean slate)",
    )
    p.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    p.add_argument("--db", default=os.getenv("MONGO_DB", DB_NAME))
    return p.parse_args()


def make_serial(rng: random.Random, mfr: str, used: set[str]) -> str:
    """Plausible per-manufacturer serial, unique within the run."""
    while True:
        s = f"{SERIAL_PREFIX[mfr]}1F{rng.randint(10, 99)}JC{rng.randint(100, 999)}Q{rng.randint(100000, 999999):06d}"
        if s not in used:
            used.add(s)
            return s


def seed(mongo_uri: str, db_name: str, keep: bool) -> dict[str, int]:
    rng = random.Random(SEED)
    fake = Faker()
    Faker.seed(SEED)
    now = datetime.now(UTC)

    client: MongoClient = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")  # fail fast when MongoDB is down.
    db = client[db_name]
    if not keep:
        client.drop_database(db_name)

    # --- owners ---
    owners_coll = db["owners"]
    owner_ids: list[ObjectId] = []
    owner_types = ["individual", "company", "government"]
    for i in range(N_OWNERS):
        email = f"owner{i:02d}@example.com"
        if keep and owners_coll.find_one({"email": email}):
            owner_ids.append(owners_coll.find_one({"email": email})["_id"])
            continue
        org = fake.company() if i % 3 else ""
        doc = {
            "name": fake.name(),
            "type": owner_types[i % 3],
            "organization": org,
            "email": email,
            "phone": f"+216 {rng.randint(20, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
            "country": "TN" if i % 4 else fake.country_code(),
            "created_at": now - timedelta(days=rng.randint(200, 900)),
        }
        owner_ids.append(owners_coll.insert_one(doc).inserted_id)

    # --- zones ---
    zones_coll = db["zones"]
    for z in ZONES:
        zones_coll.update_one(
            {"_id": z["_id"]},
            {
                "$setOnInsert": {
                    "name": z["name"],
                    "description": z["desc"],
                    "restriction_level": z["level"],
                    "camera_ids": z["cams"],
                }
            },
            upsert=True,
        )

    # --- drones + authorizations: one range per decision branch ---
    drones_coll = db["drones"]
    authz_coll = db["authorizations"]
    used_serials = (
        {d["serial_number"] for d in drones_coll.find({}, {"serial_number": 1})} if keep else set()
    )
    new_drone_ids: list[ObjectId] = []
    n_authz = 0

    def add_auth(drone_id: ObjectId, zone_id: str, valid_from, valid_to, status: str) -> None:
        nonlocal n_authz
        authz_coll.insert_one(
            {
                "drone_id": drone_id,
                "zone_id": zone_id,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "purpose": rng.choice(PURPOSES),
                "issued_by": "Security Office",
                "status": status,
            }
        )
        n_authz += 1

    active_from, active_to = now - timedelta(days=180), now + timedelta(days=180)
    expired_from, expired_to = now - timedelta(days=400), now - timedelta(days=200)

    for i in range(N_DRONES):
        spec = MODEL_CATALOG[i % len(MODEL_CATALOG)]
        serial = f"SEED{i:03d}{SERIAL_PREFIX[str(spec['mfr'])]}Q{(100000 + i * 7919) % 900000:06d}"
        if serial in used_serials:
            continue
        used_serials.add(serial)
        owner_id = owner_ids[i % len(owner_ids)]
        year_made = rng.randint(2019, 2025)
        year_sold = min(2026, year_made + rng.randint(0, 2))
        if i in STOLEN_IDX:
            status = "stolen"
        elif i in REVOKED_STATUS_IDX:
            status = "revoked"
        elif i in DECOMMISSIONED_IDX:
            status = "decommissioned"
        else:
            status = "active"
        drone_id = drones_coll.insert_one(
            {
                "serial_number": serial,
                "manufacturer": spec["mfr"],
                "model": spec["model"],
                "model_version": spec["ver"],
                "model_family": spec["family"],
                "airframe_type": spec["air"],
                "category": spec["cat"],
                "weight_g": spec["w"],
                "color": rng.choice(COLORS),
                "owner_id": owner_id,
                "year_manufactured": year_made,
                "year_sold": year_sold,
                "sale_history": [{"year": year_sold, "from": "Dealer X", "to_owner_id": owner_id}],
                "status": status,
                "remote_id_enabled": i not in NO_REMOTE_ID_IDX,
                "notes": "",
                "created_at": now - timedelta(days=rng.randint(30, 700)),
            }
        ).inserted_id
        new_drone_ids.append(drone_id)

        if i <= 9:  # active auth in every flyable zone
            for z in FLYABLE_ZONES:
                add_auth(drone_id, z, active_from, active_to, "active")
        elif 10 <= i <= 19:  # north-gate only
            add_auth(drone_id, "north-gate", active_from, active_to, "active")
        elif 20 <= i <= 25:  # expired
            add_auth(drone_id, "north-gate", expired_from, expired_to, "active")
        elif 26 <= i <= 30:  # revoked
            add_auth(drone_id, "north-gate", active_from, active_to, "revoked")
        elif 31 <= i <= 34:  # stolen/revoked drone, auth otherwise valid
            add_auth(drone_id, "north-gate", active_from, active_to, "active")
        elif 35 <= i <= 37:  # other zone only
            add_auth(drone_id, "warehouse-yard", active_from, active_to, "active")
        # 38-49: no authorizations.

    # --- indexes per DESCRIPTION.md section 2 ---
    drones_coll.create_index("serial_number", unique=True)
    drones_coll.create_index("owner_id")
    drones_coll.create_index("status")
    drones_coll.create_index([("airframe_type", ASCENDING), ("model_family", ASCENDING)])
    authz_coll.create_index([("drone_id", ASCENDING), ("zone_id", ASCENDING)])
    det_coll = db["detections"]
    det_coll.create_index("event_id", unique=True)
    det_coll.create_index("detected_at")
    det_coll.create_index("decision")
    det_coll.create_index("export_status")

    return {
        "owners": owners_coll.count_documents({}),
        "zones": zones_coll.count_documents({}),
        "drones": drones_coll.count_documents({}),
        "authorizations": authz_coll.count_documents({}),
        "new_drones": len(new_drone_ids),
        "new_authz": n_authz,
    }


def drop_database(mongo_uri: str, db_name: str) -> None:
    """Drop only the app database (never anything else); used by `make clean-db`."""
    client: MongoClient = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")  # fail fast when MongoDB is down.
    client.drop_database(db_name)


def main() -> None:
    args = parse_args()
    if args.drop_only:
        try:
            drop_database(args.mongo_uri, args.db)
        except Exception as exc:  # fail fast, never pretend
            raise SystemExit(f"clean failed: {exc}") from exc
        print(f"database '{args.db}' dropped (clean slate — run `make seed` to re-create mock data)")
        return
    try:
        counts = seed(args.mongo_uri, args.db, args.keep)
    except Exception as exc:  # fail fast, never pretend
        raise SystemExit(f"seed failed: {exc}") from exc
    mode = "kept existing data, added missing rows" if args.keep else "wiped and re-created"
    print(f"seed complete ({mode}) — database '{args.db}'")
    print(f"  owners:         {counts['owners']}")
    print(f"  zones:          {counts['zones']} (airport-approach is no-fly)")
    print(f"  drones:         {counts['drones']} (new this run: {counts['new_drones']})")
    print(f"  authorizations: {counts['authorizations']} (new this run: {counts['new_authz']})")


if __name__ == "__main__":
    main()
