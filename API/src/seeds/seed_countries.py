import csv
import os

from sqlalchemy import select

from src.core.db import async_session
from src.models.location import Country, State

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


async def seed_countries():
    csv_path = os.path.join(DATA_DIR, "countries.csv")
    if not os.path.exists(csv_path):
        print(f"Countries CSV not found at {csv_path}, skipping.")
        return

    async with async_session() as db:
        created = 0
        skipped = 0
        seen_iso2 = set()
        seen_iso3 = set()

        # Also load existing codes from DB to skip
        existing_rows = (await db.execute(select(Country.iso2, Country.iso3))).all()
        for row in existing_rows:
            seen_iso2.add(row[0])
            seen_iso3.add(row[1])

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                iso2 = row["iso2"].strip()
                iso3 = row["iso3"].strip()

                # Skip entries without valid ISO codes or duplicates
                if iso2 == "--" or iso3 == "--":
                    skipped += 1
                    continue
                if iso2 in seen_iso2 or iso3 in seen_iso3:
                    skipped += 1
                    continue

                seen_iso2.add(iso2)
                seen_iso3.add(iso3)

                db.add(
                    Country(
                        id=int(row["id"]),
                        name=row["name"].strip(),
                        iso2=iso2,
                        iso3=iso3,
                        calling_code=row["calling_code"].strip()
                        if row.get("calling_code")
                        else None,
                        currency=row["currency"].strip() if row.get("currency") else None,
                        currency_code=row["currency_code"].strip()
                        if row.get("currency_code")
                        else None,
                        capital=row["capital"].strip() if row.get("capital") else None,
                        is_active=row.get("is_active", "true").strip().lower() == "true",
                    )
                )
                created += 1

        await db.commit()
        print(f"Countries seeded: {created} new, {skipped} skipped.")


async def seed_states():
    csv_path = os.path.join(DATA_DIR, "states.csv")
    if not os.path.exists(csv_path):
        print(f"States CSV not found at {csv_path}, skipping.")
        return

    async with async_session() as db:
        created = 0
        skipped = 0
        seen = set()

        # Load valid country IDs from DB
        valid_country_ids = set(row[0] for row in (await db.execute(select(Country.id))).all())

        # Load existing states from DB
        existing_rows = (await db.execute(select(State.country_id, State.name))).all()
        for row in existing_rows:
            seen.add((row[0], row[1]))

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                country_id = int(row["country_id"])
                name = row["name"].strip()

                # Skip states whose country was not seeded
                if country_id not in valid_country_ids:
                    skipped += 1
                    continue

                if (country_id, name) in seen:
                    continue
                seen.add((country_id, name))

                db.add(
                    State(
                        id=int(row["srno"]),
                        country_id=country_id,
                        name=name,
                        code=row["code"].strip() if row.get("code") else None,
                        adm1_code=row["adm1_code"].strip() if row.get("adm1_code") else None,
                        is_active=row.get("is_active", "true").strip().lower() == "true",
                    )
                )
                created += 1

        await db.commit()
        print(f"States seeded: {created} new, {skipped} skipped (missing country).")
