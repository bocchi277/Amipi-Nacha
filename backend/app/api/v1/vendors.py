"""
Vendor Management & Bank Detail Change Approval Router.

Standard users submit bank change requests; Admin users approve or reject.
Approvals update actual vendor banking details and log to AuditLog.
"""
import csv
import io
import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_async_db
from app.models import (
    AccountType,
    AuditLog,
    ChangeRequestStatus,
    Payment,
    User,
    UserRole,
    Vendor,
    VendorChangeRequest,
    VendorRemittance,
)
from app.nacha.validation import validate_routing_checksum

router = APIRouter(prefix="/vendors", tags=["Vendors"])


class CreateVendorSchema(BaseModel):
    name: str
    routing_number: str
    account_number: str
    account_type: AccountType = AccountType.CHECKING
    default_id_number: Optional[str] = None
    email: Optional[str] = None
    allow_update: Optional[bool] = False
    allow_bank_update: Optional[bool] = False


class BulkVendorUploadResponseSchema(BaseModel):
    total_rows: int
    imported_count: int
    skipped_count: int
    errors: list[dict[str, Any]]


class BulkVendorPreviewResponseSchema(BaseModel):
    total_rows: int
    new_count: int
    update_count: int
    unchanged_count: int
    error_count: int
    new_vendors: list[dict[str, Any]]
    updated_vendors: list[dict[str, Any]]
    unchanged_vendors: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class BulkVendorConfirmRequestSchema(BaseModel):
    new_vendors: list[dict[str, Any]] = []
    updated_vendors: list[dict[str, Any]] = []
    apply_updates: bool = True
    allow_bank_updates: bool = False


class BulkVendorConfirmResponseSchema(BaseModel):
    inserted_count: int
    updated_count: int
    skipped_count: int
    message: str
    # Rows rejected by validation (invalid routing number, over-long account, or a
    # bank change the caller was not authorised to make).
    rejected: list[dict[str, Any]] = []


class BulkDeleteVendorsSchema(BaseModel):
    vendor_ids: list[uuid.UUID]
    cascade_payments: Optional[bool] = False


class BulkDeleteVendorsResponseSchema(BaseModel):
    deleted_count: int
    message: str


class UpdateVendorSchema(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    default_id_number: Optional[str] = None
    is_active: Optional[bool] = None


class VendorResponseSchema(BaseModel):
    id: str
    name: str
    routing_number: str
    account_number: str
    account_type: str
    default_id_number: Optional[str] = None
    email: Optional[str] = None
    is_active: bool
    # True when the caller is not an administrator and the bank fields above are
    # masked, so the UI can label them rather than appear to show real values.
    bank_details_masked: bool = False



class CreateChangeRequestSchema(BaseModel):
    requested_routing_number: str
    requested_account_number: str
    requested_account_type: AccountType = AccountType.CHECKING
    reason: Optional[str] = None


class ChangeRequestResponseSchema(BaseModel):
    id: str
    vendor_id: str
    vendor_name: str
    requested_routing_number: str
    requested_account_number: str
    requested_account_type: str
    reason: Optional[str] = None
    status: str
    requested_by_user_id: Optional[str] = None
    reviewed_by_user_id: Optional[str] = None


def _val(x):
    if x is None:
        return ""
    return x.value if hasattr(x, "value") else str(x)


# ---------------------------------------------------------------------------
# Reference vendor data
# ---------------------------------------------------------------------------
# DERIVED FROM AMIPI's ACTUAL CHASE TRANSMIT FILES (ACH Thru Treasury Soft/*.txt)
# by decoding the routing/account fields of each type-6 Entry Detail record.
#
# WHY THIS IS ANNOTATED: the previous hardcoded values were mis-transcribed from the
# wrong spreadsheet columns -- 13 of 33 entries carried the WRONG routing and/or
# account number, several of them built out of digits taken from the invoice
# reference field. Every one of those wrong routing numbers still passed ABA
# check-digit validation, so no validation in this system could ever have caught it.
# Seeding that data and generating a file would have sent money to wrong accounts.
#
# Two entries were REMOVED rather than guessed, because they cannot be verified
# against any transmit file:
#   * "KIRA JEWELS INC"  - the files contain a payee named "KIRA" (026013356 /
#     ...8846). Whether these are the same legal entity needs AMIPI confirmation.
#   * "TWINKLEDIAM INC."  - the files contain "TWINKELEDIAM, INC.", a different
#     spelling; the mapping needs AMIPI confirmation.
# Add them through the reviewed bulk-import flow once confirmed.
#
# NOTE: "LAB GROWN DIAMOND USA" appears with two different accounts across the
# files; the most recent (07.16.2026) is used here.
#
# This list is locked to the transmit files by
# tests/test_vendor_master_data.py, so it cannot silently drift again.
# It is REFERENCE data for setup convenience -- always confirm against AMIPI's bank
# records before generating a live payment file.
SAMPLE_VENDORS = [
    {"name": "ARTN DESIGN INC", "routing": "021000021", "account": "918025393"},  # corrected from transmit file 07.30.2026
    {"name": "B. H. C. DIAMONDS", "routing": "021000021", "account": "182810850"},  # corrected from transmit file 07.30.2026
    {"name": "BRINKS GLOBLE SERVICES", "routing": "011900254", "account": "385016029033"},  # corrected from transmit file 07.16.2026
    {"name": "BELGIUM DIA LLC", "routing": "021000322", "account": "483110589481"},
    {"name": "BELGIUM NEW YORK LLC", "routing": "026009768", "account": "1330546"},
    {"name": "BRILLIANT ART LTD.", "routing": "021000089", "account": "6881733008"},  # corrected from transmit file 07.02.2026
    {"name": "DHARM INTERNATIONAL LLC", "routing": "026009768", "account": "1355284"},
    {"name": "DIAMEX INC", "routing": "026013673", "account": "4424759954"},  # corrected from transmit file 07.30.2026
    {"name": "DIAMOND DAYS PROMOTION", "routing": "021000021", "account": "756311460"},  # corrected from transmit file 07.30.2026
    {"name": "DISONS GEMS INC", "routing": "026013576", "account": "1504846772"},
    {"name": "FENIX DIAMONDS LLC", "routing": "021000089", "account": "6795192196"},  # corrected from transmit file 07.30.2026
    {"name": "FOREVER GROWN DIAMONDS", "routing": "021000322", "account": "483107296800"},
    {"name": "KGK DIAMONDS USA", "routing": "026013356", "account": "0399027203"},
    {"name": "KGS JEWELS", "routing": "021000322", "account": "483059162859"},
    {"name": "KIRAN GEMS USA INC", "routing": "026013356", "account": "0399016945"},
    {"name": "LAB GROWN DIAMOND USA", "routing": "021000021", "account": "785019693"},  # corrected from transmit file 07.16.2026
    {"name": "MC PRODUCTION US LLC", "routing": "021202337", "account": "706312066"},
    {"name": "MR. F JEWELRY INC.", "routing": "021000021", "account": "582725381"},  # corrected from transmit file 07.30.2026
    {"name": "SHIVAM JEWELS INC", "routing": "021000021", "account": "590399997"},  # corrected from transmit file 07.30.2026
    {"name": "SIGNOVA INC", "routing": "081000032", "account": "355014730231"},  # corrected from transmit file 07.30.2026
    {"name": "SUNSHINE DIAMOND CUTTER", "routing": "021000322", "account": "483028574148"},
    {"name": "UNITED COLOR GEMS INC", "routing": "021000322", "account": "483095583405"},  # corrected from transmit file 07.30.2026
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


@router.post("/seed-sample-vendors", status_code=status.HTTP_201_CREATED)
async def seed_sample_vendors(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),  # ADMIN ONLY!
):

    """Seed company reference vendors into database."""
    added = 0
    skipped: list[dict[str, str]] = []
    for v_data in SAMPLE_VENDORS:
        name_clean = v_data["name"].strip()
        acc = v_data["account"]
        rt = v_data["routing"]

        # Validate before writing. The seed endpoint previously performed NO
        # validation at all (unlike create_vendor), so a bad routing number in this
        # list would land straight in the database and produce a bank-rejected file.
        if len(rt) != 9 or not validate_routing_checksum(rt):
            skipped.append({"name": name_clean,
                            "error": f"invalid ABA routing number '{rt}'"})
            continue
        if not acc or len(acc) > 17:
            skipped.append({"name": name_clean,
                            "error": f"invalid account number length {len(acc)}"})
            continue

        def_id = acc[-5:] if len(acc) >= 5 else acc
        res = await db.execute(select(Vendor).where(Vendor.name == name_clean))
        existing_v = res.scalars().first()
        if existing_v:
            if not existing_v.default_id_number or existing_v.default_id_number == "ABC":
                existing_v.default_id_number = def_id
            continue
        vendor = Vendor(
            name=name_clean[:22],
            routing_number=rt,
            account_number=acc,
            account_type=AccountType.CHECKING,
            default_id_number=def_id,
            is_active=True,
        )
        db.add(vendor)
        added += 1

    db.add(
        AuditLog(
            user_id=admin_user.id,
            action="VENDOR_REFERENCE_DATA_SEEDED",
            entity_type="Vendor",
            details={"added": added, "skipped": skipped,
                     "seeded_by": admin_user.username},
        )
    )
    await db.commit()
    return {
        "message": f"Successfully seeded {added} reference vendors.",
        "added": added,
        "skipped": skipped,
    }


def _mask_account(value: Optional[str]) -> str:
    """Return only the last 4 digits, e.g. '••••7465'."""
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return "•" * max(0, len(value) - len(tail)) + tail


def _mask_routing(value: Optional[str]) -> str:
    """
    Routing numbers identify the BANK, not the account, and the UI needs enough to
    be useful, so show only the last 4. Combined with a masked account this is not
    sufficient to originate a payment.
    """
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return "•" * max(0, len(value) - len(tail)) + tail


@router.get("", response_model=list[VendorResponseSchema])
async def list_vendors(
    include_inactive: bool = Query(True, description="Include inactive vendors in the list"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all vendors.

    Bank details are MASKED unless the caller is an administrator. Previously this
    returned every vendor's full decrypted routing and account number to any
    authenticated user, so a single standard account was enough to exfiltrate the
    entire vendor bank book.
    """
    is_admin = (current_user.role == UserRole.ADMIN)
    query = select(Vendor)
    if not include_inactive:
        query = query.where(Vendor.is_active == True)
    query = query.order_by(Vendor.name)
    res = await db.execute(query)
    vendors = res.scalars().all()
    return [
        VendorResponseSchema(
            id=str(v.id),
            name=v.name,
            routing_number=v.routing_number if is_admin else _mask_routing(v.routing_number),
            account_number=v.account_number if is_admin else _mask_account(v.account_number),
            account_type=_val(v.account_type),
            default_id_number=v.default_id_number or (v.account_number[-5:] if v.account_number and len(v.account_number) >= 5 else v.account_number),
            email=v.email,
            is_active=v.is_active,
            bank_details_masked=not is_admin,
        )
        for v in vendors
    ]


@router.post("", response_model=VendorResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: CreateVendorSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new Vendor or update existing vendor upon confirmation.
    
    If duplicate detected:
    - If exact match: returns 409 Conflict with exact_match=True
    - If differences: returns 409 Conflict with diff details if allow_update=False
    - If allow_update=True: updates existing vendor (admin permission required for bank details).
    """
    name_clean = " ".join(payload.name.strip().split())[:22]
    rt = "".join(filter(str.isdigit, payload.routing_number.strip()))
    acc = payload.account_number.strip()

    if len(rt) != 9 or not validate_routing_checksum(rt):
        raise HTTPException(status_code=400, detail=f"Invalid 9-digit ABA routing number '{payload.routing_number}'.")

    if not acc:
        raise HTTPException(status_code=400, detail="Account number is required.")

    # Look for an existing vendor by name (safe to do in SQL) ...
    res = await db.execute(
        select(Vendor).where(func.upper(func.trim(Vendor.name)) == name_clean.upper())
    )
    existing = res.scalars().first()

    # ... then by bank details, which CANNOT be matched in SQL. routing_number and
    # account_number are stored as Fernet ciphertext with a random IV, so a freshly
    # encrypted bind parameter never equals the stored ciphertext and the old
    # `WHERE routing_number = :rt` silently matched nothing. Compare the decrypted
    # values in Python instead (the TypeDecorator decrypts on load).
    if existing is None:
        res_all = await db.execute(select(Vendor))
        for v in res_all.scalars().all():
            if (v.routing_number or "").strip() == rt and (v.account_number or "").strip() == acc:
                existing = v
                break

    if existing:
        new_email = payload.email.strip() if payload.email and payload.email.strip() else None
        new_ref = payload.default_id_number.strip() if payload.default_id_number and payload.default_id_number.strip() else None
        new_type = payload.account_type.value if hasattr(payload.account_type, "value") else str(payload.account_type)
        existing_type = existing.account_type.value if hasattr(existing.account_type, "value") else str(existing.account_type)

        changes = {}
        if (existing.email or None) != new_email:
            changes["email"] = {"old": existing.email or "None", "new": new_email or "None"}
        if (existing.default_id_number or None) != new_ref:
            changes["default_id_number"] = {"old": existing.default_id_number or "None", "new": new_ref or "None"}
        if existing.name.upper() != name_clean.upper():
            changes["name"] = {"old": existing.name, "new": name_clean}

        has_bank_change = False
        if existing.routing_number != rt:
            changes["routing_number"] = {"old": existing.routing_number, "new": rt}
            has_bank_change = True
        if existing.account_number != acc:
            changes["account_number"] = {"old": existing.account_number, "new": acc}
            has_bank_change = True
        if existing_type.lower() != new_type.lower():
            changes["account_type"] = {"old": existing_type, "new": new_type}
            has_bank_change = True

        if not changes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"Vendor '{existing.name}' already exists with identical details.",
                    "duplicate": True,
                    "exact_match": True,
                    "vendor_id": str(existing.id),
                    "vendor_name": existing.name,
                },
            )

        is_same_bank = (existing.routing_number == rt and existing.account_number == acc)
        is_diff_name = (existing.name.strip().upper() != name_clean.upper())
        same_bank_diff_name = is_same_bank and is_diff_name

        if not payload.allow_update:
            masked_acc = f"•••• {acc[-5:] if len(acc) >= 5 else acc}"
            conflict_msg = (
                f"A vendor with this bank account already exists: '{existing.name}' (Routing: {rt}, Account: {masked_acc}). "
                f"Would you like to update the existing vendor's details to '{name_clean}'?"
                if same_bank_diff_name
                else f"Existing vendor '{existing.name}' detected with modified details."
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": conflict_msg,
                    "duplicate": True,
                    "exact_match": False,
                    "same_bank_different_name": same_bank_diff_name,
                    "vendor_id": str(existing.id),
                    "vendor_name": existing.name,
                    "existing_vendor_name": existing.name,
                    "new_vendor_name": name_clean,
                    "has_bank_change": has_bank_change,
                    "changes": changes,
                },
            )

        # Apply updates
        is_admin = (current_user.role == UserRole.ADMIN)
        if has_bank_change:
            if not is_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only Administrators can directly update vendor banking details. Standard users must submit a Bank Change Request.",
                )
            if not payload.allow_bank_update:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Explicit bank change authorization (allow_bank_update=True) is required to overwrite banking details.",
                )
            existing.routing_number = rt
            existing.account_number = acc
            existing.account_type = payload.account_type

        if "name" in changes:
            existing.name = name_clean
        if "email" in changes:
            existing.email = new_email
        if "default_id_number" in changes:
            existing.default_id_number = new_ref

        action_type = "VENDOR_DIRECT_BANK_AND_PROFILE_UPDATE" if has_bank_change else "VENDOR_PROFILE_UPDATED"
        audit = AuditLog(
            user_id=current_user.id,
            action=action_type,
            entity_type="Vendor",
            entity_id=str(existing.id),
            details={
                "vendor_name": existing.name,
                "changes": changes,
                "updated_by": current_user.username,
                "is_admin": is_admin,
            },
        )
        db.add(audit)
        await db.commit()
        await db.refresh(existing)

        return VendorResponseSchema(
            id=str(existing.id),
            name=existing.name,
            routing_number=existing.routing_number,
            account_number=existing.account_number,
            account_type=_val(existing.account_type),
            default_id_number=existing.default_id_number,
            email=existing.email,
            is_active=existing.is_active,
        )

    # New Vendor
    def_id = payload.default_id_number.strip() if payload.default_id_number and payload.default_id_number.strip() else (acc[-5:] if len(acc) >= 5 else acc)
    vendor = Vendor(
        name=name_clean,
        routing_number=rt,
        account_number=acc,
        account_type=payload.account_type,
        default_id_number=def_id,
        email=payload.email.strip() if payload.email and payload.email.strip() else None,
        is_active=True,
    )
    db.add(vendor)
    await db.flush()

    # Creating a vendor establishes where money will be sent, so it must be
    # attributable. Only vendor UPDATES were audited previously, leaving the initial
    # creation of a bank account completely untracked.
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="VENDOR_CREATED",
            entity_type="Vendor",
            entity_id=str(vendor.id),
            details={
                "vendor_name": vendor.name,
                "created_by": current_user.username,
                "routing_number": rt,
                # Account number is masked: the audit trail is broadly readable by
                # admins and should not become a second copy of full bank details.
                "account_number_last4": acc[-4:] if len(acc) >= 4 else acc,
                "account_type": _val(vendor.account_type),
            },
        )
    )

    await db.commit()
    await db.refresh(vendor)

    return VendorResponseSchema(
        id=str(vendor.id),
        name=vendor.name,
        routing_number=vendor.routing_number,
        account_number=vendor.account_number,
        account_type=_val(vendor.account_type),
        default_id_number=vendor.default_id_number,
        email=vendor.email,
        is_active=vendor.is_active,
    )


@router.get("/sample-template")
async def download_vendor_sample_template():
    """Download a standardized CSV template for bulk vendor import."""
    content = "Vendor Name,Routing Number,Account Number,Account Type,Invoice Ref,Email\nACME SUPPLIES INC,021000021,11391039,checking,INV-1001,ap@acme.com\nBELGIUM DIA LLC,021000322,483110589481,checking,INV-1002,ap@belgium.com\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vendor_import_template.csv"},
    )


def _parse_vendor_file_bytes(filename: str, content_bytes: bytes) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Helper to parse Excel or CSV bytes into normalized dictionary rows."""
    import openpyxl
    rows_to_process = []
    errors = []

    if filename.lower().endswith((".xlsx", ".xls")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                errors.append({"row": 0, "error": "Excel sheet contains no data."})
                return [], errors

            headers = [str(cell or "").strip().lower() for cell in rows[0]]
            for row_idx, row in enumerate(rows[1:], start=2):
                if not any(row):
                    continue
                row_dict = {}
                for col_idx, h in enumerate(headers):
                    val = str(row[col_idx] or "").strip() if col_idx < len(row) else ""
                    row_dict[h] = val
                rows_to_process.append((row_idx, row_dict))
        except Exception as e:
            errors.append({"row": 0, "error": f"Error reading Excel file: {str(e)}"})
            return [], errors
    else:
        try:
            text_data = content_bytes.decode("utf-8-sig", errors="ignore")
            reader = csv.DictReader(io.StringIO(text_data))
            for row_idx, row in enumerate(reader, start=2):
                if not any(row.values()):
                    continue
                clean_row = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items() if k}
                rows_to_process.append((row_idx, clean_row))
        except Exception as e:
            errors.append({"row": 0, "error": f"Error reading CSV file: {str(e)}"})
            return [], errors

    return rows_to_process, errors


@router.post("/bulk-preview", response_model=BulkVendorPreviewResponseSchema)
async def bulk_preview_vendors(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dry-run analysis of a bulk vendor file (.csv, .xlsx).
    Returns classified new vendors, updated vendors with field diffs, unchanged vendors, and errors.
    """
    filename = file.filename or ""
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    rows_to_process, parse_errors = _parse_vendor_file_bytes(filename, content_bytes)
    if parse_errors:
        return BulkVendorPreviewResponseSchema(
            total_rows=0,
            new_count=0,
            update_count=0,
            unchanged_count=0,
            error_count=len(parse_errors),
            new_vendors=[],
            updated_vendors=[],
            unchanged_vendors=[],
            errors=parse_errors,
        )

    # Fetch existing vendors
    res = await db.execute(select(Vendor))
    existing_vendors = res.scalars().all()
    existing_by_name = {" ".join(v.name.strip().upper().split()): v for v in existing_vendors}
    existing_by_bank = {(v.routing_number.strip(), v.account_number.strip()): v for v in existing_vendors}

    new_vendors = []
    updated_vendors = []
    unchanged_vendors = []
    errors = []

    seen_in_batch = set()

    for row_idx, r in rows_to_process:
        name = r.get("vendor name") or r.get("name") or r.get("vendor_name") or r.get("vendor") or ""
        routing = r.get("routing number") or r.get("routing_number") or r.get("routing") or r.get("aba") or ""
        account = r.get("account number") or r.get("account_number") or r.get("account") or r.get("acct") or ""
        acct_type_str = r.get("account type") or r.get("account_type") or r.get("type") or "checking"
        default_ref = r.get("invoice ref") or r.get("invoice_ref") or r.get("default_id_number") or r.get("ref") or None
        email = r.get("email") or r.get("vendor email") or r.get("vendor_email") or None

        name_clean = " ".join(name.strip().split())[:22]
        routing_clean = "".join(filter(str.isdigit, routing.strip()))
        account_clean = account.strip()

        if not name_clean:
            errors.append({"row": row_idx, "error": "Vendor name is required."})
            continue

        if not routing_clean or len(routing_clean) != 9 or not validate_routing_checksum(routing_clean):
            errors.append({"row": row_idx, "error": f"Invalid 9-digit ABA routing number '{routing}' for '{name_clean}'."})
            continue

        if not account_clean:
            errors.append({"row": row_idx, "error": f"Account number is required for '{name_clean}'."})
            continue

        batch_key = name_clean.upper()
        if batch_key in seen_in_batch:
            # Duplicate inside same upload batch
            continue
        seen_in_batch.add(batch_key)

        acct_type = AccountType.SAVINGS if "sav" in acct_type_str.lower() else AccountType.CHECKING
        acct_type_val = acct_type.value

        existing = existing_by_name.get(name_clean.upper()) or existing_by_bank.get((routing_clean, account_clean))

        if existing:
            # Check differences
            changes = {}
            new_email_clean = email.strip() if email and email.strip() else None
            new_ref_clean = default_ref.strip() if default_ref and default_ref.strip() else None
            existing_type_val = existing.account_type.value if hasattr(existing.account_type, "value") else str(existing.account_type)

            if (existing.email or None) != new_email_clean:
                changes["email"] = {"old": existing.email or "None", "new": new_email_clean or "None"}
            if (existing.default_id_number or None) != new_ref_clean:
                changes["default_id_number"] = {"old": existing.default_id_number or "None", "new": new_ref_clean or "None"}
            if existing.name.upper() != name_clean.upper():
                changes["name"] = {"old": existing.name, "new": name_clean}

            has_bank_change = False
            if existing.routing_number != routing_clean:
                changes["routing_number"] = {"old": existing.routing_number, "new": routing_clean}
                has_bank_change = True
            if existing.account_number != account_clean:
                changes["account_number"] = {"old": existing.account_number, "new": account_clean}
                has_bank_change = True
            if existing_type_val.lower() != acct_type_val.lower():
                changes["account_type"] = {"old": existing_type_val, "new": acct_type_val}
                has_bank_change = True

            same_bank_diff_name = (
                existing.routing_number == routing_clean
                and existing.account_number == account_clean
                and existing.name.strip().upper() != name_clean.upper()
            )

            if changes:
                updated_vendors.append({
                    "vendor_id": str(existing.id),
                    "vendor_name": existing.name,
                    "same_bank_different_name": same_bank_diff_name,
                    "has_bank_change": has_bank_change,
                    "changes": changes,
                    "new_data": {
                        "name": name_clean,
                        "routing_number": routing_clean,
                        "account_number": account_clean,
                        "account_type": acct_type_val,
                        "default_id_number": new_ref_clean,
                        "email": new_email_clean,
                    },
                })
            else:
                unchanged_vendors.append({
                    "vendor_id": str(existing.id),
                    "vendor_name": existing.name,
                    "routing_number": existing.routing_number,
                    "account_number": existing.account_number,
                })
        else:
            def_ref_clean = default_ref.strip() if default_ref and default_ref.strip() else (account_clean[-5:] if len(account_clean) >= 5 else account_clean)
            new_vendors.append({
                "name": name_clean,
                "routing_number": routing_clean,
                "account_number": account_clean,
                "account_type": acct_type_val,
                "default_id_number": def_ref_clean,
                "email": email.strip() if email and email.strip() else None,
            })

    return BulkVendorPreviewResponseSchema(
        total_rows=len(rows_to_process),
        new_count=len(new_vendors),
        update_count=len(updated_vendors),
        unchanged_count=len(unchanged_vendors),
        error_count=len(errors),
        new_vendors=new_vendors,
        updated_vendors=updated_vendors,
        unchanged_vendors=unchanged_vendors,
        errors=errors,
    )


@router.post("/bulk-confirm", response_model=BulkVendorConfirmResponseSchema)
async def bulk_confirm_vendors(
    payload: BulkVendorConfirmRequestSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Execute batch vendor insertions and updates after user review in the diff modal.
    """
    is_admin = (current_user.role == UserRole.ADMIN)
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    # Rows refused by validation, surfaced to the caller instead of failing silently.
    rejected: list[dict[str, Any]] = []

    # Fetch all existing vendors from database to prevent duplicate inserts
    res = await db.execute(select(Vendor))
    db_vendors = list(res.scalars().all())
    existing_by_name = {" ".join(v.name.strip().upper().split()): v for v in db_vendors}
    existing_by_bank = {(v.routing_number.strip(), v.account_number.strip()): v for v in db_vendors}

    seen_in_batch = set()
    seen_in_batch_bank = set()

    # 1. Insert or safely update new vendors
    for nv in payload.new_vendors:
        rt = "".join(filter(str.isdigit, str(nv.get("routing_number", "")).strip()))
        acc = str(nv.get("account_number", "")).strip()
        name_clean = " ".join(str(nv.get("name", "")).strip().split())[:22]
        if not name_clean or not rt or not acc:
            rejected.append({
                "name": name_clean or str(nv.get("name", "")),
                "error": "Vendor name, routing number and account number are all required.",
            })
            skipped_count += 1
            continue

        # This endpoint accepts a client-supplied payload, so it must re-validate
        # everything /bulk-preview validated. Without this an invalid routing number
        # (e.g. "123") could be written straight to the database, producing a
        # malformed entry-detail record that the bank rejects.
        if len(rt) != 9 or not validate_routing_checksum(rt):
            rejected.append({
                "name": name_clean,
                "error": f"Invalid 9-digit ABA routing number '{nv.get('routing_number')}' "
                         f"(failed check-digit validation).",
            })
            skipped_count += 1
            continue

        if len(acc) > 17:
            rejected.append({
                "name": name_clean,
                "error": f"Account number exceeds the NACHA 17-character limit ({len(acc)} chars).",
            })
            skipped_count += 1
            continue

        norm_key = name_clean.upper()
        if norm_key in seen_in_batch or (rt, acc) in seen_in_batch_bank:
            # Intra-batch duplicate in payload: skip to prevent duplicate insert/count
            skipped_count += 1
            continue
        seen_in_batch.add(norm_key)
        seen_in_batch_bank.add((rt, acc))

        existing = existing_by_name.get(norm_key) or existing_by_bank.get((rt, acc))
        if existing:
            # If vendor already exists in DB, update non-bank details if allowed or skip
            if payload.apply_updates:
                if nv.get("email") and str(nv["email"]).strip():
                    existing.email = str(nv["email"]).strip()
                if nv.get("default_id_number") and str(nv["default_id_number"]).strip():
                    existing.default_id_number = str(nv["default_id_number"]).strip()
                updated_count += 1
            else:
                skipped_count += 1
            continue

        acct_type = AccountType.SAVINGS if "sav" in str(nv.get("account_type", "")).lower() else AccountType.CHECKING
        def_id = str(nv.get("default_id_number", "")).strip() or (acc[-5:] if len(acc) >= 5 else acc)
        v = Vendor(
            name=name_clean,
            routing_number=rt,
            account_number=acc,
            account_type=acct_type,
            default_id_number=def_id,
            email=nv.get("email") or None,
            is_active=True,
        )
        db.add(v)
        inserted_count += 1
        # Track in memory so subsequent rows in same batch don't insert a second time!
        existing_by_name[norm_key] = v
        existing_by_bank[(rt, acc)] = v

    # 2. Update existing vendors if apply_updates is True
    if payload.apply_updates:
        for uv in payload.updated_vendors:
            v_id_str = uv.get("vendor_id")
            if not v_id_str:
                continue
            try:
                v_uuid = uuid.UUID(str(v_id_str).strip())
            except ValueError:
                continue

            res = await db.execute(select(Vendor).where(Vendor.id == v_uuid))
            vendor = res.scalar_one_or_none()
            if not vendor:
                continue

            changes = uv.get("changes", {})
            has_bank_change = uv.get("has_bank_change", False)
            new_data = uv.get("new_data", {})

            if "name" in changes and new_data.get("name"):
                vendor.name = " ".join(str(new_data["name"]).strip().split())[:22]
            if "email" in changes:
                vendor.email = str(new_data["email"]).strip() if new_data.get("email") else None
            if "default_id_number" in changes:
                vendor.default_id_number = str(new_data["default_id_number"]).strip() if new_data.get("default_id_number") else None

            if has_bank_change:
                if not (payload.allow_bank_updates and is_admin):
                    # Previously this silently dropped the bank change but still counted
                    # the row as updated, so the UI reported success for a change that
                    # never happened. Report it instead.
                    rejected.append({
                        "name": vendor.name,
                        "error": (
                            "Bank detail change was NOT applied: requires an administrator "
                            "and allow_bank_updates=true."
                        ),
                    })
                else:
                    new_rt = "".join(filter(str.isdigit, str(new_data.get("routing_number", "") or "")))
                    new_acc = str(new_data.get("account_number", "") or "").strip()
                    if "routing_number" in changes:
                        if len(new_rt) != 9 or not validate_routing_checksum(new_rt):
                            rejected.append({
                                "name": vendor.name,
                                "error": f"Invalid ABA routing number '{new_data.get('routing_number')}' "
                                         f"- bank details left unchanged.",
                            })
                            continue
                        vendor.routing_number = new_rt
                    if "account_number" in changes and new_acc:
                        if len(new_acc) > 17:
                            rejected.append({
                                "name": vendor.name,
                                "error": f"Account number exceeds 17 characters "
                                         f"- bank details left unchanged.",
                            })
                            continue
                        vendor.account_number = new_acc
                    if "account_type" in changes and new_data.get("account_type"):
                        vendor.account_type = (
                            AccountType.SAVINGS
                            if "sav" in str(new_data["account_type"]).lower()
                            else AccountType.CHECKING
                        )

            updated_count += 1
    else:
        skipped_count += len(payload.updated_vendors)

    if inserted_count > 0 or updated_count > 0:
        audit = AuditLog(
            user_id=current_user.id,
            action="BULK_IMPORT_AND_UPDATE_VENDORS",
            entity_type="Vendor",
            details={
                "inserted_count": inserted_count,
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "rejected_count": len(rejected),
                "bank_updates_applied": bool(payload.allow_bank_updates and is_admin),
                "admin_username": current_user.username,
            },
        )
        db.add(audit)
    await db.commit()

    msg = f"Successfully added {inserted_count} new vendor(s) and updated {updated_count} existing vendor(s)."
    if rejected:
        msg += f" {len(rejected)} row(s) were rejected by validation."

    return BulkVendorConfirmResponseSchema(
        inserted_count=inserted_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        message=msg,
        rejected=rejected,
    )


class DeduplicateVendorsResponseSchema(BaseModel):
    message: str
    merged_count: int
    primary_vendors_count: int
    purged_duplicate_ids: list[str]


@router.post("/deduplicate", response_model=DeduplicateVendorsResponseSchema)
async def deduplicate_vendors(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_admin),
):
    """
    Find duplicate vendors by normalized name (UPPER(TRIM(name))) or identical bank details,
    re-link all dependent records (payments, change requests, remittances) to the primary record,
    and safely delete duplicate vendor entries.
    """
    res = await db.execute(select(Vendor).order_by(Vendor.created_at.asc()))
    all_vendors = list(res.scalars().all())

    # Group vendors that are the same real-world payee. Two vendors belong together if
    # they share a normalized name OR identical bank details. The previous version only
    # grouped by name, so same-account/different-name duplicates -- exactly the case
    # create_vendor warns about -- were never merged despite the docstring.
    #
    # Union-find so that A~B by name and B~C by bank collapses into one group.
    parent: dict[uuid.UUID, uuid.UUID] = {v.id: v.id for v in all_vendors}

    def find(x: uuid.UUID) -> uuid.UUID:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: uuid.UUID, b: uuid.UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_name: dict[str, uuid.UUID] = {}
    by_bank: dict[tuple[str, str], uuid.UUID] = {}
    for v in all_vendors:
        name_key = " ".join((v.name or "").strip().upper().split())
        if name_key:
            if name_key in by_name:
                union(by_name[name_key], v.id)
            else:
                by_name[name_key] = v.id

        # Comparison happens on DECRYPTED values held in memory; an equality query in
        # SQL would never match because the columns hold randomized Fernet ciphertext.
        bank_key = ((v.routing_number or "").strip(), (v.account_number or "").strip())
        if all(bank_key):
            if bank_key in by_bank:
                union(by_bank[bank_key], v.id)
            else:
                by_bank[bank_key] = v.id

    vendor_by_id = {v.id: v for v in all_vendors}
    grouped: dict[uuid.UUID, list[Vendor]] = {}
    for v in all_vendors:
        grouped.setdefault(find(v.id), []).append(v)

    # Preserve creation order within each group so the oldest record wins as primary.
    groups: dict[str, list[Vendor]] = {
        str(root): sorted(members, key=lambda x: x.created_at)
        for root, members in grouped.items()
    }

    merged_count = 0
    purged_ids: list[str] = []
    audit_details: list[dict[str, Any]] = []

    for name_key, v_list in groups.items():
        if len(v_list) <= 1:
            continue

        # Choose primary vendor: prioritize active, having email, having custom default_id_number, or earliest created
        primary = v_list[0]
        for other in v_list[1:]:
            if not primary.email and other.email:
                primary.email = other.email
            if (not primary.default_id_number or primary.default_id_number == primary.account_number[-5:]) and other.default_id_number:
                primary.default_id_number = other.default_id_number

        duplicates = v_list[1:]
        for dup in duplicates:
            # 1. Re-link payments in DB
            res_p = await db.execute(
                update(Payment).where(Payment.vendor_id == dup.id).values(vendor_id=primary.id)
            )
            payments_count = res_p.rowcount

            # 2. Re-link change requests in DB
            res_cr = await db.execute(
                update(VendorChangeRequest).where(VendorChangeRequest.vendor_id == dup.id).values(vendor_id=primary.id)
            )
            change_reqs_count = res_cr.rowcount

            # 3. Re-link remittances in DB
            res_rem = await db.execute(
                update(VendorRemittance).where(VendorRemittance.vendor_id == dup.id).values(
                    vendor_id=primary.id, vendor_name=primary.name
                )
            )
            remittances_count = res_rem.rowcount

            # 4. Delete duplicate vendor row from DB
            await db.execute(delete(Vendor).where(Vendor.id == dup.id))

            purged_ids.append(str(dup.id))
            audit_details.append({
                "duplicate_id": str(dup.id),
                "duplicate_name": dup.name,
                "primary_id": str(primary.id),
                "primary_name": primary.name,
                "payments_relinked": payments_count,
                "remittances_relinked": remittances_count,
            })
            merged_count += 1

    if merged_count > 0:
        audit = AuditLog(
            user_id=current_user.id,
            action="DEDUPLICATE_VENDORS",
            entity_type="Vendor",
            details={
                "merged_count": merged_count,
                "admin_username": current_user.username,
                "records": audit_details,
            },
        )
        db.add(audit)
        await db.commit()

    return DeduplicateVendorsResponseSchema(
        message=f"Successfully identified and merged {merged_count} duplicate vendor record(s). All payment histories and remittances are safely preserved under unified profiles.",
        merged_count=merged_count,
        primary_vendors_count=len(groups),
        purged_duplicate_ids=purged_ids,
    )


@router.post("/bulk-upload", response_model=BulkVendorUploadResponseSchema, status_code=status.HTTP_201_CREATED)
async def bulk_upload_vendors(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk import vendors from a CSV or Excel (.xlsx) file (legacy direct upload endpoint).
    """
    filename = file.filename or ""
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    rows_to_process, errors = _parse_vendor_file_bytes(filename, content_bytes)
    if not rows_to_process and not errors:
        raise HTTPException(status_code=400, detail="No vendor data rows found in uploaded file.")

    res = await db.execute(select(Vendor))
    existing_vendors = res.scalars().all()
    existing_names = {v.name.strip().upper() for v in existing_vendors}
    existing_routing_acct = {(v.routing_number.strip(), v.account_number.strip()) for v in existing_vendors}

    imported_count = 0
    skipped_count = 0

    for row_idx, r in rows_to_process:
        name = r.get("vendor name") or r.get("name") or r.get("vendor_name") or r.get("vendor") or ""
        routing = r.get("routing number") or r.get("routing_number") or r.get("routing") or r.get("aba") or ""
        account = r.get("account number") or r.get("account_number") or r.get("account") or r.get("acct") or ""
        acct_type_str = r.get("account type") or r.get("account_type") or r.get("type") or "checking"
        default_ref = r.get("invoice ref") or r.get("invoice_ref") or r.get("default_id_number") or r.get("ref") or None
        email = r.get("email") or r.get("vendor email") or r.get("vendor_email") or None

        name_clean = name.strip()[:22]
        routing_clean = "".join(filter(str.isdigit, routing.strip()))
        account_clean = account.strip()

        if not name_clean:
            errors.append({"row": row_idx, "error": "Vendor name is required."})
            continue

        if not routing_clean or len(routing_clean) != 9 or not validate_routing_checksum(routing_clean):
            errors.append({"row": row_idx, "error": f"Invalid 9-digit ABA routing number '{routing}' for '{name_clean}'."})
            continue

        if not account_clean:
            errors.append({"row": row_idx, "error": f"Account number is required for '{name_clean}'."})
            continue

        if name_clean.upper() in existing_names or (routing_clean, account_clean) in existing_routing_acct:
            skipped_count += 1
            continue

        acct_type = AccountType.SAVINGS if "sav" in acct_type_str.lower() else AccountType.CHECKING

        vendor = Vendor(
            name=name_clean,
            routing_number=routing_clean,
            account_number=account_clean,
            account_type=acct_type,
            default_id_number=default_ref.strip() if default_ref and default_ref.strip() else None,
            email=email.strip() if email and email.strip() else None,
            is_active=True,
        )
        db.add(vendor)
        existing_names.add(name_clean.upper())
        existing_routing_acct.add((routing_clean, account_clean))
        imported_count += 1

    if imported_count > 0:
        audit = AuditLog(
            user_id=current_user.id,
            action="BULK_IMPORT_VENDORS",
            entity_type="Vendor",
            details={
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "error_count": len(errors),
                "filename": filename,
            },
        )
        db.add(audit)
        await db.commit()

    return BulkVendorUploadResponseSchema(
        total_rows=len(rows_to_process),
        imported_count=imported_count,
        skipped_count=skipped_count,
        errors=errors,
    )


@router.get("/{vendor_id}", response_model=VendorResponseSchema)
async def get_vendor(vendor_id: str, db: AsyncSession = Depends(get_async_db)):
    """Fetch vendor by ID."""
    try:
        v_uuid = uuid.UUID(vendor_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid vendor_id format.")

    res = await db.execute(select(Vendor).where(Vendor.id == v_uuid))
    vendor = res.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    return VendorResponseSchema(
        id=str(vendor.id),
        name=vendor.name,
        routing_number=vendor.routing_number,
        account_number=vendor.account_number,
        account_type=_val(vendor.account_type),
        default_id_number=vendor.default_id_number,
        email=vendor.email,
        is_active=vendor.is_active,
    )


@router.put("/{vendor_id}", response_model=VendorResponseSchema)
async def update_vendor(
    vendor_id: str,
    payload: UpdateVendorSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update vendor details (email address, vendor name, default reference ID).
    """
    try:
        v_uuid = uuid.UUID(vendor_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid vendor_id format.")

    res = await db.execute(select(Vendor).where(Vendor.id == v_uuid))
    vendor = res.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    if payload.name is not None and payload.name.strip():
        vendor.name = payload.name.strip()[:22]
    if payload.email is not None:
        vendor.email = payload.email.strip() if payload.email.strip() else None
    if payload.default_id_number is not None:
        vendor.default_id_number = payload.default_id_number.strip() if payload.default_id_number.strip() else None
    if payload.is_active is not None:
        vendor.is_active = payload.is_active

    # Audit Log
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="VENDOR_PROFILE_UPDATED",
        entity_type="Vendor",
        entity_id=str(vendor.id),
        details={
            "vendor_name": vendor.name,
            "updated_email": vendor.email,
            "is_active": vendor.is_active,
            "updated_by_user": current_user.username,
        },
    )
    db.add(audit_entry)

    await db.commit()
    await db.refresh(vendor)

    return VendorResponseSchema(
        id=str(vendor.id),
        name=vendor.name,
        routing_number=vendor.routing_number,
        account_number=vendor.account_number,
        account_type=_val(vendor.account_type),
        default_id_number=vendor.default_id_number,
        email=vendor.email,
        is_active=vendor.is_active,
    )






@router.post("/{vendor_id}/change-requests", response_model=ChangeRequestResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_vendor_change_request(
    vendor_id: str,
    payload: CreateChangeRequestSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Request bank detail changes for a vendor.

    Stores a pending request for Admin review. The vendor's bank details remain UNCHANGED until approved.
    """
    try:
        v_uuid = uuid.UUID(vendor_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid vendor_id format.")

    res = await db.execute(select(Vendor).where(Vendor.id == v_uuid))
    vendor = res.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    rt = payload.requested_routing_number.strip()
    if len(rt) != 9 or not validate_routing_checksum(rt):
        raise HTTPException(status_code=400, detail=f"Invalid 9-digit routing number '{rt}'.")

    req = VendorChangeRequest(
        vendor_id=vendor.id,
        requested_routing_number=rt,
        requested_account_number=payload.requested_account_number.strip(),
        requested_account_type=payload.requested_account_type,
        reason=payload.reason,
        status=ChangeRequestStatus.PENDING,
        requested_by_user_id=current_user.id,
    )
    db.add(req)

    # Audit Logging
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="VENDOR_BANK_CHANGE_REQUESTED",
        entity_type="Vendor",
        entity_id=str(vendor.id),
        details={
            "request_id": str(req.id),
            "vendor_name": vendor.name,
            "requested_routing_number": req.requested_routing_number,
            "requested_account_number": req.requested_account_number,
            "requested_account_type": req.requested_account_type.value,
            "reason": req.reason,
            "requested_by_user": current_user.username,
        },
    )
    db.add(audit_entry)

    await db.commit()
    await db.refresh(req)

    return ChangeRequestResponseSchema(
        id=str(req.id),
        vendor_id=str(vendor.id),
        vendor_name=vendor.name,
        requested_routing_number=req.requested_routing_number,
        requested_account_number=req.requested_account_number,
        requested_account_type=req.requested_account_type.value,
        reason=req.reason,
        status=req.status.value,
        requested_by_user_id=str(req.requested_by_user_id) if req.requested_by_user_id else None,
        reviewed_by_user_id=str(req.reviewed_by_user_id) if req.reviewed_by_user_id else None,
    )


@router.get("/change-requests/all", response_model=list[ChangeRequestResponseSchema])
async def list_vendor_change_requests(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """List all vendor bank change requests."""
    res = await db.execute(select(VendorChangeRequest))
    reqs = res.scalars().all()
    return [
        ChangeRequestResponseSchema(
            id=str(r.id),
            vendor_id=str(r.vendor_id),
            vendor_name=r.vendor.name if r.vendor else "Unknown",
            requested_routing_number=r.requested_routing_number,
            requested_account_number=r.requested_account_number,
            requested_account_type=r.requested_account_type.value,
            reason=r.reason,
            status=r.status.value,
            requested_by_user_id=str(r.requested_by_user_id) if r.requested_by_user_id else None,
            reviewed_by_user_id=str(r.reviewed_by_user_id) if r.reviewed_by_user_id else None,
        )
        for r in reqs
    ]


@router.post("/change-requests/{request_id}/approve", response_model=ChangeRequestResponseSchema)
async def approve_vendor_change_request(
    request_id: str,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),  # Admin ONLY! Standard user gets 403
):
    """
    Approve vendor bank detail change request (ADMIN ONLY).

    Mutates the Vendor's actual bank details in PostgreSQL and creates an AuditLog record.
    """
    try:
        r_uuid = uuid.UUID(request_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid request_id format.")

    res = await db.execute(select(VendorChangeRequest).where(VendorChangeRequest.id == r_uuid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Change request not found.")

    if req.status != ChangeRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Change request is already {req.status.value}.")

    res_v = await db.execute(select(Vendor).where(Vendor.id == req.vendor_id))
    vendor = res_v.scalar_one()

    # Capture old details for audit log
    old_details = {
        "routing_number": vendor.routing_number,
        "account_number": vendor.account_number,
        "account_type": vendor.account_type.value,
    }

    new_details = {
        "routing_number": req.requested_routing_number,
        "account_number": req.requested_account_number,
        "account_type": req.requested_account_type.value,
    }

    # Mutate Vendor bank details
    vendor.routing_number = req.requested_routing_number
    vendor.account_number = req.requested_account_number
    vendor.account_type = req.requested_account_type

    # Update request state
    req.status = ChangeRequestStatus.APPROVED
    req.reviewed_by_user_id = admin_user.id

    # Audit Logging
    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="VENDOR_BANK_UPDATE_APPROVED",
        entity_type="Vendor",
        entity_id=str(vendor.id),
        details={
            "request_id": str(req.id),
            "vendor_name": vendor.name,
            "old_bank_details": old_details,
            "new_bank_details": new_details,
            "approved_by_admin": admin_user.username,
        },
    )
    db.add(audit_entry)

    await db.commit()
    await db.refresh(req)

    return ChangeRequestResponseSchema(
        id=str(req.id),
        vendor_id=str(vendor.id),
        vendor_name=vendor.name,
        requested_routing_number=req.requested_routing_number,
        requested_account_number=req.requested_account_number,
        requested_account_type=req.requested_account_type.value,
        reason=req.reason,
        status=req.status.value,
        requested_by_user_id=str(req.requested_by_user_id) if req.requested_by_user_id else None,
        reviewed_by_user_id=str(req.reviewed_by_user_id) if req.reviewed_by_user_id else None,
    )


@router.post("/change-requests/{request_id}/reject", response_model=ChangeRequestResponseSchema)
async def reject_vendor_change_request(
    request_id: str,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),  # Admin ONLY!
):
    """Reject vendor bank detail change request (ADMIN ONLY)."""
    try:
        r_uuid = uuid.UUID(request_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid request_id format.")

    res = await db.execute(select(VendorChangeRequest).where(VendorChangeRequest.id == r_uuid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Change request not found.")

    if req.status != ChangeRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Change request is already {req.status.value}.")

    res_v = await db.execute(select(Vendor).where(Vendor.id == req.vendor_id))
    vendor = res_v.scalar_one()

    req.status = ChangeRequestStatus.REJECTED
    req.reviewed_by_user_id = admin_user.id

    # Audit Logging
    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="VENDOR_BANK_UPDATE_REJECTED",
        entity_type="Vendor",
        entity_id=str(vendor.id),
        details={
            "request_id": str(req.id),
            "vendor_name": vendor.name,
            "rejected_by_admin": admin_user.username,
        },
    )
    db.add(audit_entry)

    await db.commit()
    await db.refresh(req)

    return ChangeRequestResponseSchema(
        id=str(req.id),
        vendor_id=str(vendor.id),
        vendor_name=vendor.name,
        requested_routing_number=req.requested_routing_number,
        requested_account_number=req.requested_account_number,
        requested_account_type=req.requested_account_type.value,
        reason=req.reason,
        status=req.status.value,
        requested_by_user_id=str(req.requested_by_user_id) if req.requested_by_user_id else None,
        reviewed_by_user_id=str(req.reviewed_by_user_id) if req.reviewed_by_user_id else None,
    )


@router.delete("/{vendor_id}", status_code=status.HTTP_200_OK)
async def delete_single_vendor(
    vendor_id: str,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """Delete a single vendor by ID (ADMIN ONLY). Payment history is safely preserved."""
    try:
        v_uuid = uuid.UUID(vendor_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid vendor_id format.")

    res = await db.execute(delete(Vendor).where(Vendor.id == v_uuid).returning(Vendor.name))
    v_name = res.scalar_one_or_none()
    if not v_name:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    audit = AuditLog(
        user_id=admin_user.id,
        action="DELETE_VENDOR",
        entity_type="Vendor",
        entity_id=str(v_uuid),
        details={"vendor_name": v_name, "deleted_by": admin_user.username},
    )
    db.add(audit)
    await db.commit()

    return {
        "message": f"Vendor '{v_name}' successfully deleted. Transaction and remittance history is preserved.",
        "vendor_id": str(v_uuid),
    }


@router.post("/bulk-delete", response_model=BulkDeleteVendorsResponseSchema, status_code=status.HTTP_200_OK)
async def bulk_delete_vendors(
    payload: BulkDeleteVendorsSchema,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """Delete multiple selected vendors by ID array (ADMIN ONLY). Payment history is safely preserved."""
    if not payload.vendor_ids:
        raise HTTPException(status_code=400, detail="No vendor IDs provided for bulk deletion.")

    deleted_names = []
    v_uuids = []
    for v_id in payload.vendor_ids:
        try:
            v_uuids.append(uuid.UUID(str(v_id).strip()))
        except (ValueError, AttributeError):
            continue

    if v_uuids:
        res = await db.execute(delete(Vendor).where(Vendor.id.in_(v_uuids)).returning(Vendor.name))
        deleted_names = [r[0] for r in res.all()]

    deleted_count = len(deleted_names)

    if deleted_count > 0:
        audit = AuditLog(
            user_id=admin_user.id,
            action="BULK_DELETE_VENDORS",
            entity_type="Vendor",
            details={
                "deleted_count": deleted_count,
                "deleted_names": deleted_names,
                "deleted_by": admin_user.username,
            },
        )
        db.add(audit)
        await db.commit()

    return BulkDeleteVendorsResponseSchema(
        deleted_count=deleted_count,
        deleted_vendors=deleted_names,
        message=f"Successfully deleted {deleted_count} vendor(s) from directory. All transaction and remittance history is safely preserved.",
    )
