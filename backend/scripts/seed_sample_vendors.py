"""
Utility CLI Script: Seed & Update Sample Vendors into PostgreSQL Database.

Populates initial sample vendors and updates any invalid routing numbers with valid ABA check digits.

Usage:
  python3 backend/scripts/seed_sample_vendors.py
"""
import asyncio
import sys
from pathlib import Path

# Ensure app package is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models import AccountType, Vendor
from app.nacha.validation import validate_routing_checksum

SAMPLE_VENDORS = [
    {"name": "ARTN DESIGN INC", "routing": "021000021", "account": "11391039"},
    {"name": "B. H. C. DIAMONDS", "routing": "021000322", "account": "3761810589"},
    {"name": "BRINKS GLOBLE SERVICES", "routing": "021000021", "account": "85016029033"},
    {"name": "BELGIUM DIA LLC", "routing": "021000322", "account": "483110589481"},
    {"name": "BELGIUM NEW YORK LLC", "routing": "026009768", "account": "1330546"},
    {"name": "BRILLIANT ART LTD.", "routing": "021000021", "account": "881733008"},
    {"name": "DHARM INTERNATIONAL LLC", "routing": "026009768", "account": "1355284"},
    {"name": "DIAMEX INC", "routing": "026013356", "account": "106920399"},
    {"name": "DIAMOND DAYS PROMOTION", "routing": "021000322", "account": "25789107"},
    {"name": "DISONS GEMS INC", "routing": "026013576", "account": "1504846772"},
    {"name": "FENIX DIAMONDS LLC", "routing": "021000021", "account": "795192196"},
    {"name": "FOREVER GROWN DIAMONDS", "routing": "021000322", "account": "483107296800"},
    {"name": "KGK DIAMONDS USA", "routing": "026013356", "account": "0399027203"},
    {"name": "KGS JEWELS", "routing": "021000322", "account": "483059162859"},
    {"name": "KIRA JEWELS INC", "routing": "026013356", "account": "3231970399"},
    {"name": "KIRAN GEMS USA INC", "routing": "026013356", "account": "0399016945"},
    {"name": "LAB GROWN DIAMOND USA", "routing": "021000322", "account": "483110589436"},
    {"name": "MC PRODUCTION US LLC", "routing": "021202337", "account": "706312066"},
    {"name": "MR. F JEWELRY INC.", "routing": "021000021", "account": "008212026"},
    {"name": "SHIVAM JEWELS INC", "routing": "026013356", "account": "265206440399"},
    {"name": "SIGNOVA INC", "routing": "021000322", "account": "55014730231"},
    {"name": "SUNSHINE DIAMOND CUTTER", "routing": "021000322", "account": "483028574148"},
    {"name": "TWINKLEDIAM INC.", "routing": "026013356", "account": "26012320399"},
    {"name": "UNITED COLOR GEMS INC", "routing": "021000021", "account": "439617311"},
    {"name": "TRUEARTH JEWELS INC", "routing": "021000021", "account": "731135862"},
    {"name": "UNICORN JEWELS USA INC", "routing": "021000322", "account": "483107642250"},
    {"name": "UNIVERSE JEWELRY INC", "routing": "021000021", "account": "731138338"},
    {"name": "V360 STUDIO NYC", "routing": "021000021", "account": "381227567"},
    {"name": "VERONIQUE ORO CORP", "routing": "021213371", "account": "11070001554"},
    {"name": "DRIESASSUR USA LLC", "routing": "021000322", "account": "483047158875"},
    {"name": "KEZIAH THERESEE LLC", "routing": "021000021", "account": "2909555312"},
    {"name": "VIANELLO ORO CORP", "routing": "021213371", "account": "11070002214"},
    {"name": "IDD USA LLC", "routing": "026009768", "account": "1000059966"},
    {"name": "MALCA-AMIT CUSTOM HOUS", "routing": "021000021", "account": "782953613"},
]


async def seed_vendors():
    async with AsyncSessionLocal() as db:
        added_count = 0
        updated_count = 0

        print("\n==========================================================================================")
        print("                AMIPI ACH SYSTEM — SEEDING & UPDATING VALID VENDORS                        ")
        print("==========================================================================================")

        for v_data in SAMPLE_VENDORS:
            name_clean = v_data["name"].strip()
            rt = v_data["routing"].strip()
            acct = v_data["account"].strip()

            # Check if vendor exists
            res = await db.execute(select(Vendor).where(Vendor.name == name_clean))
            existing = res.scalar_one_or_none()

            if existing:
                if not validate_routing_checksum(existing.routing_number) or existing.routing_number != rt:
                    existing.routing_number = rt
                    updated_count += 1
                continue

            vendor = Vendor(
                name=name_clean[:22],
                routing_number=rt,
                account_number=acct,
                account_type=AccountType.CHECKING,
                is_active=True,
            )
            db.add(vendor)
            added_count += 1

        await db.commit()
        print(f"Seeding completed: {added_count} new vendors added, {updated_count} routing numbers updated to valid ABA.")
        print("==========================================================================================\n")


if __name__ == "__main__":
    asyncio.run(seed_vendors())
