"""
Vendor Remittance Email ORM model & RemittanceStatus enum.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Enum as SQLEnum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RemittanceStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class VendorRemittance(Base):
    __tablename__ = "vendor_remittances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nacha_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nacha_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RemittanceStatus] = mapped_column(
        SQLEnum(RemittanceStatus, name="remittancestatus", create_type=True),
        nullable=False,
        default=RemittanceStatus.PENDING,
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resend_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    vendor = relationship("Vendor", back_populates="remittances", lazy="selectin")
    nacha_file = relationship("NachaFileRecord", lazy="select")
    payment = relationship("Payment", lazy="select")
