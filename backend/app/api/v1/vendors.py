"""
Vendor Management & Bank Detail Change Approval Router.

Standard users submit bank change requests; Admin users approve or reject.
Approvals update actual vendor banking details and log to AuditLog.
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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


class VendorResponseSchema(BaseModel):
    id: str
    name: str
    routing_number: str
    account_number: str
    account_type: str
    default_id_number: Optional[str] = None
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
            account_type=v.account_type.value,
            default_id_number=v.default_id_number,
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
        account_type=vendor.account_type.value,
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
        account_type=vendor.account_type.value,
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
