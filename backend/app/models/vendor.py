"""
Vendor ORM model & AccountType enum.
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SQLEnum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedBankDetailType
from app.db.base import Base


class AccountType(str, enum.Enum):
    CHECKING = "checking"
    SAVINGS = "savings"


class Vendor(Base):
    __tablename__ = "vendors"

    # CHECK constraints for valid data
    __table_args__ = (
        CheckConstraint("length(name) >= 1", name="ck_vendor_name_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(22), nullable=False, index=True)
    routing_number: Mapped[str] = mapped_column(EncryptedBankDetailType, nullable=False)
    account_number: Mapped[str] = mapped_column(EncryptedBankDetailType, nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SQLEnum(AccountType, name="accounttype", create_type=True),
        nullable=False,
        default=AccountType.CHECKING,
    )
    default_id_number: Mapped[str | None] = mapped_column(String(15), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    payments = relationship("Payment", back_populates="vendor", lazy="selectin")
