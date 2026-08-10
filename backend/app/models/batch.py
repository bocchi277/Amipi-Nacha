"""
UploadBatch ORM model & BatchStatus enum.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BatchStatus(str, enum.Enum):
    PARSED = "parsed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    PROCESSED = "processed"


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, default="excel")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    status: Mapped[BatchStatus] = mapped_column(
        SQLEnum(BatchStatus, name="batchstatus", create_type=True),
        nullable=False,
        default=BatchStatus.PARSED,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    payments = relationship("Payment", back_populates="batch", lazy="selectin")
    created_by_user = relationship("User", lazy="select")
