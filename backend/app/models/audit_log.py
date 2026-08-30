"""
Audit Log ORM model.
"""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, event, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="audit_logs")


@event.listens_for(AuditLog, "before_insert")
def _stamp_client_ip(mapper, connection, target: "AuditLog") -> None:
    """
    Fill ip_address from the current request context.

    Applied as a mapper event so every AuditLog call site is covered by one change
    rather than requiring a Request to be threaded through each service function.
    An explicitly supplied value is respected.
    """
    if target.ip_address is None:
        from app.core.request_context import get_client_ip

        target.ip_address = get_client_ip()
