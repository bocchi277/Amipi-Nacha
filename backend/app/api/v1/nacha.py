"""
NACHA File Generation FastAPI Router.

Combines multiple upload/manual batches into a Chase-compliant NACHA flat file.
"""
import logging
import re
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_async_db
from app.models import User
from app.services.nacha_service import BatchAlreadyProcessedError, combine_batches_and_generate_nacha

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nacha", tags=["NACHA Generation"])


class GenerateNachaRequest(BaseModel):
    batch_ids: list[uuid.UUID]
    company_name: str = "AMIPI INC"
    company_account: str = "785957066"
    effective_entry_date: Optional[str] = None
    file_id_modifier: str = "A"
    trace_sequence_start: Optional[int] = None
    entry_description: str = "EPAYMNT"


class NachaFileResponse(BaseModel):
    id: str
    filename: str
    file_id_modifier: str
    file_creation_date: str
    file_creation_time: str
    total_entry_count: int
    total_batch_count: int
    total_block_count: int
    total_credit_amount: str
    entry_hash: str
    raw_content: str


@router.get("/next-trace-sequence", status_code=status.HTTP_200_OK)
async def get_next_trace_sequence_endpoint(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """Fetch the next auto-incremented starting trace sequence number."""
    from app.services.nacha_service import get_next_trace_sequence
    seq = await get_next_trace_sequence(db)
    return {"next_trace_sequence": seq}


@router.get("/latest", response_model=NachaFileResponse, status_code=status.HTTP_200_OK)
async def get_latest_nacha_file_endpoint(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """
    Fetch the most recently generated NACHA file record.

    Admin-only: the response includes ``raw_content``, i.e. the complete ACH file
    containing every vendor's routing and account number.
    """
    from sqlalchemy import select
    from app.models import NachaFileRecord

    stmt = select(NachaFileRecord).order_by(NachaFileRecord.created_at.desc()).limit(1)
    res = await db.execute(stmt)
    latest = res.scalar_one_or_none()

    if not latest:
        raise HTTPException(status_code=404, detail="No NACHA files have been generated yet.")

    return NachaFileResponse(
        id=str(latest.id),
        filename=latest.filename,
        file_id_modifier=latest.file_id_modifier,
        file_creation_date=latest.file_creation_date,
        file_creation_time=latest.file_creation_time,
        total_entry_count=latest.total_entry_count,
        total_batch_count=latest.total_batch_count,
        total_block_count=latest.total_block_count,
        total_credit_amount=str(latest.total_credit_amount),
        entry_hash=latest.entry_hash,
        raw_content=latest.raw_content,
    )


@router.post("/generate", response_model=NachaFileResponse, status_code=status.HTTP_201_CREATED)

async def generate_nacha_file_endpoint(
    payload: GenerateNachaRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Combine multiple payment batches (e.g., Batch 1 + Batch 2) into one NACHA file.

    Generates Chase-compliant 94-character flat file, updates control totals,
    links Payments in DB to NachaFileRecord, and returns raw content.
    """
    try:
        nacha_record, gen_result = await combine_batches_and_generate_nacha(
            db_session=db,
            batch_ids=payload.batch_ids,
            company_name=payload.company_name,
            company_account=payload.company_account,
            effective_entry_date=payload.effective_entry_date,
            file_id_modifier=payload.file_id_modifier,
            trace_sequence_start=payload.trace_sequence_start,
            entry_description=payload.entry_description,
            created_by_user_id=current_user.id,
        )
    except BatchAlreadyProcessedError as bae:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(bae))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except HTTPException:
        raise
    except Exception:
        # Never surface raw exception text to clients: it leaks schema and internals.
        logger.exception("NACHA generation failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NACHA file generation failed due to an internal error.",
        )

    return NachaFileResponse(
        id=str(nacha_record.id),
        filename=nacha_record.filename,
        file_id_modifier=nacha_record.file_id_modifier,
        file_creation_date=nacha_record.file_creation_date,
        file_creation_time=nacha_record.file_creation_time,
        total_entry_count=nacha_record.total_entry_count,
        total_batch_count=nacha_record.total_batch_count,
        total_block_count=nacha_record.total_block_count,
        total_credit_amount=str(nacha_record.total_credit_amount),
        entry_hash=nacha_record.entry_hash,
        raw_content=nacha_record.raw_content,
    )


@router.get("/{file_id}/download")
async def download_nacha_file(
    file_id: str,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """
    Download generated NACHA file as a .txt attachment.

    Admin-only: the file contains full bank details for every payee in the batch.
    """
    from fastapi.responses import Response
    from sqlalchemy import select
    from app.models import NachaFileRecord

    try:
        f_uuid = uuid.UUID(file_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid file_id format.")

    res = await db.execute(select(NachaFileRecord).where(NachaFileRecord.id == f_uuid))
    record = res.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="NACHA file record not found.")

    # Strip anything that could break out of the quoted header value or inject
    # additional response headers (the filename embeds user-supplied input).
    safe_name = re.sub(r'[^A-Za-z0-9._-]', "_", record.filename or "nacha_file.ach")

    return Response(
        content=record.raw_content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
