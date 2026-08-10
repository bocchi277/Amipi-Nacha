"""
NACHA File Record ORM model.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, Enum as SQLEnum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NachaFileStatus(str, enum.Enum):
    GENERATED = "generated"
    TRANSMITTED = "transmitted"
    ARCHIVED = "archived"


class NachaFileRecord(Base):
    __tablename__ = "nacha_files"
    __table_args__ = (
        CheckConstraint("total_credit_amount >= 0", name="ck_nacha_files_credit_nonneg"),
        CheckConstraint("total_entry_count >= 1", name="ck_nacha_files_entry_count_pos"),
        CheckConstraint("total_batch_count >= 1", name="ck_nacha_files_batch_count_pos"),
        CheckConstraint("total_block_count >= 1", name="ck_nacha_files_block_count_pos"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_creation_date: Mapped[str] = mapped_column(String(6), nullable=False)  # YYMMDD
    file_creation_time: Mapped[str] = mapped_column(String(4), nullable=False)  # HHMM
    file_id_modifier: Mapped[str] = mapped_column(String(1), nullable=False, default="A")
    total_credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_batch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(10), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NachaFileStatus] = mapped_column(
        SQLEnum(NachaFileStatus, name="nachafilestatus", create_type=True),
        nullable=False,
        default=NachaFileStatus.GENERATED,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    created_by_user = relationship("User", back_populates="nacha_files")
    payments = relationship("Payment", back_populates="nacha_file")
