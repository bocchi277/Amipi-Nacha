"""
Vendor Change Request ORM Model & ChangeRequestStatus Enum.
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedBankDetailType
from app.db.base import Base
from app.models.vendor import AccountType


class ChangeRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VendorChangeRequest(Base):
    __tablename__ = "vendor_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requested_routing_number: Mapped[str] = mapped_column(EncryptedBankDetailType, nullable=False)
    requested_account_number: Mapped[str] = mapped_column(EncryptedBankDetailType, nullable=False)
    requested_account_type: Mapped[AccountType] = mapped_column(
        PGEnum(AccountType, name="accounttype", create_type=False),
        nullable=False,
        default=AccountType.CHECKING,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        SQLEnum(ChangeRequestStatus, name="changerequeststatus", create_type=True),
        nullable=False,
        default=ChangeRequestStatus.PENDING,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    vendor = relationship("Vendor", back_populates="change_requests", lazy="selectin")
    requested_by_user = relationship("User", foreign_keys=[requested_by_user_id], lazy="select")
    reviewed_by_user = relationship("User", foreign_keys=[reviewed_by_user_id], lazy="select")
