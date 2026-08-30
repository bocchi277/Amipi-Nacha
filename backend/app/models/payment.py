"""
Payment ORM model & PaymentStatus enum.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum as SQLEnum, ForeignKey, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Human-readable invoice reference, which may list several invoices with
    # separators (e.g. "UDI261954/65/55"). The 15-character value actually written to
    # the NACHA file is derived from this by app.nacha.id_field at generation time.
    id_number: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_breakdown: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="paymentstatus", create_type=True),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    nacha_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nacha_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    is_duplicate_override: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    vendor = relationship("Vendor", back_populates="payments")
    nacha_file = relationship("NachaFileRecord", back_populates="payments")
    batch = relationship("UploadBatch", back_populates="payments")
    created_by_user = relationship("User", back_populates="payments")
