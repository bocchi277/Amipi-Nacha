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

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_async_db
from app.models import AccountType, AuditLog, ChangeRequestStatus, User, Vendor, VendorChangeRequest
from app.nacha.validation import validate_routing_checksum

router = APIRouter(prefix="/vendors", tags=["Vendors"])


class CreateVendorSchema(BaseModel):
    name: str
    routing_number: str
    account_number: str
    account_type: AccountType = AccountType.CHECKING
    default_id_number: Optional[str] = None
    email: Optional[str] = None


class BulkVendorUploadResponseSchema(BaseModel):
    total_rows: int
    imported_count: int
    skipped_count: int
    errors: list[dict[str, Any]]


class BulkDeleteVendorsSchema(BaseModel):
    vendor_ids: list[uuid.UUID]


class BulkDeleteVendorsResponseSchema(BaseModel):
    deleted_count: int
    message: str


class UpdateVendorSchema(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    default_id_number: Optional[str] = None


class VendorResponseSchema(BaseModel):
    id: str
    name: str
    routing_number: str
    account_number: str
    account_type: str
    default_id_number: Optional[str] = None
    email: Optional[str] = None
    is_active: bool



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


@router.post("/seed-sample-vendors", status_code=status.HTTP_201_CREATED)
async def seed_sample_vendors(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),  # ADMIN ONLY!
):

    """Seed company sample vendors into database."""
    added = 0
    for v_data in SAMPLE_VENDORS:
        name_clean = v_data["name"].strip()
        res = await db.execute(select(Vendor).where(Vendor.name == name_clean))
        if res.scalar_one_or_none():
            continue
        vendor = Vendor(
            name=name_clean[:22],
            routing_number=v_data["routing"],
            account_number=v_data["account"],
            account_type=AccountType.CHECKING,
            is_active=True,
        )
        db.add(vendor)
        added += 1
    await db.commit()
    return {"message": f"Successfully seeded {added} sample vendors.", "added": added}


@router.get("", response_model=list[VendorResponseSchema])
async def list_vendors(db: AsyncSession = Depends(get_async_db)):
    """List all active vendors."""
    res = await db.execute(select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name))
    vendors = res.scalars().all()
    return [
        VendorResponseSchema(
            id=str(v.id),
            name=v.name,
            routing_number=v.routing_number,
            account_number=v.account_number,
            account_type=_val(v.account_type),
            default_id_number=v.default_id_number,
            email=v.email,
            is_active=v.is_active,
        )
        for v in vendors
    ]


@router.post("", response_model=VendorResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: CreateVendorSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new Vendor."""
    rt = payload.routing_number.strip()
    if len(rt) != 9 or not validate_routing_checksum(rt):
        raise HTTPException(status_code=400, detail=f"Invalid 9-digit routing number '{rt}'.")

    vendor = Vendor(
        name=payload.name.strip()[:22],
        routing_number=rt,
        account_number=payload.account_number.strip(),
        account_type=payload.account_type,
        default_id_number=payload.default_id_number,
        email=payload.email.strip() if payload.email and payload.email.strip() else None,
    )
    db.add(vendor)
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


@router.post("/bulk-upload", response_model=BulkVendorUploadResponseSchema, status_code=status.HTTP_201_CREATED)
async def bulk_upload_vendors(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk import vendors from a CSV or Excel (.xlsx) file.
    Validates mandatory fields, ABA routing checksums, and filters out duplicates.
    """
    import openpyxl
    filename = file.filename or ""
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    rows_to_process = []

    if filename.lower().endswith((".xlsx", ".xls")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                raise HTTPException(status_code=400, detail="Excel sheet contains no data.")

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
            raise HTTPException(status_code=400, detail=f"Error reading Excel file: {str(e)}")
    else:
        # CSV parsing
        try:
            text_data = content_bytes.decode("utf-8-sig", errors="ignore")
            reader = csv.DictReader(io.StringIO(text_data))
            for row_idx, row in enumerate(reader, start=2):
                if not any(row.values()):
                    continue
                clean_row = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items() if k}
                rows_to_process.append((row_idx, clean_row))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error reading CSV file: {str(e)}")

    if not rows_to_process:
        raise HTTPException(status_code=400, detail="No vendor data rows found in uploaded file.")

    # Fetch existing vendors for duplicate checking
    res = await db.execute(select(Vendor))
    existing_vendors = res.scalars().all()
    existing_names = {v.name.strip().upper() for v in existing_vendors}
    existing_routing_acct = {(v.routing_number.strip(), v.account_number.strip()) for v in existing_vendors}

    imported_count = 0
    skipped_count = 0
    errors = []

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

    # Audit Log
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="VENDOR_PROFILE_UPDATED",
        entity_type="Vendor",
        entity_id=str(vendor.id),
        details={
            "vendor_name": vendor.name,
            "updated_email": vendor.email,
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






@router.post("", response_model=VendorResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: CreateVendorSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new Vendor."""
    rt = payload.routing_number.strip()
    if len(rt) != 9 or not validate_routing_checksum(rt):
        raise HTTPException(status_code=400, detail=f"Invalid 9-digit routing number '{rt}'.")

    vendor = Vendor(
        name=payload.name.strip(),
        routing_number=rt,
        account_number=payload.account_number.strip(),
        account_type=payload.account_type,
        default_id_number=payload.default_id_number,
    )
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)

    return VendorResponseSchema(
        id=str(vendor.id),
        name=vendor.name,
        routing_number=vendor.routing_number,
        account_number=vendor.account_number,
        account_type=_val(vendor.account_type),
        default_id_number=vendor.default_id_number,
        is_active=vendor.is_active,
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
    """Delete a single vendor by ID (ADMIN ONLY)."""
    try:
        v_uuid = uuid.UUID(vendor_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid vendor_id format.")

    res = await db.execute(select(Vendor).where(Vendor.id == v_uuid))
    vendor = res.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    v_name = vendor.name

    await db.delete(vendor)

    audit = AuditLog(
        user_id=admin_user.id,
        action="DELETE_VENDOR",
        entity_type="Vendor",
        entity_id=str(v_uuid),
        details={"vendor_name": v_name, "deleted_by": admin_user.username},
    )
    db.add(audit)
    await db.commit()

    return {"message": f"Vendor '{v_name}' successfully deleted.", "vendor_id": str(v_uuid)}


@router.post("/bulk-delete", response_model=BulkDeleteVendorsResponseSchema, status_code=status.HTTP_200_OK)
async def bulk_delete_vendors(
    payload: BulkDeleteVendorsSchema,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """Delete multiple selected vendors by ID array (ADMIN ONLY)."""
    if not payload.vendor_ids:
        raise HTTPException(status_code=400, detail="No vendor IDs provided for bulk deletion.")

    deleted_count = 0
    deleted_names = []

    for v_id in payload.vendor_ids:
        res = await db.execute(select(Vendor).where(Vendor.id == v_id))
        vendor = res.scalar_one_or_none()
        if vendor:
            deleted_names.append(vendor.name)
            await db.delete(vendor)
            deleted_count += 1

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
        message=f"Successfully deleted {deleted_count} vendor(s) from database.",
    )
