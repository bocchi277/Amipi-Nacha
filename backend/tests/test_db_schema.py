"""
Database schema & ORM CRUD tests for Phase 2.

Tests inserts, queries, unique constraints, foreign keys, and relationships.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    AccountType,
    AuditLog,
    NachaFileRecord,
    NachaFileStatus,
    Payment,
    PaymentStatus,
    User,
    UserRole,
    Vendor,
)


@pytest.mark.asyncio
async def test_create_and_query_user(db_session):
    """Test creating a User record and querying it back."""
    user = User(
        email="admin@amipi.com",
        username="admin",
        password_hash="hashed_secret_123",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.username == "admin"))
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.id is not None
    assert fetched.email == "admin@amipi.com"
    assert fetched.role == UserRole.ADMIN
    assert fetched.is_active is True


@pytest.mark.asyncio
async def test_user_unique_constraints(db_session):
    """Test unique email/username constraints on Users."""
    u1 = User(
        email="duplicate@amipi.com",
        username="user1",
        password_hash="pass",
    )
    db_session.add(u1)
    await db_session.commit()

    u2 = User(
        email="duplicate@amipi.com",  # Duplicate email
        username="user2",
        password_hash="pass",
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_and_query_vendor(db_session):
    """Test creating a Vendor record with banking details."""
    vendor = Vendor(
        name="VERONIQUE ORO CORP",
        routing_number="021213371",
        account_number="11070001554",
        account_type=AccountType.CHECKING,
        default_id_number="01554",
        is_active=True,
    )
    db_session.add(vendor)
    await db_session.commit()

    result = await db_session.execute(
        select(Vendor).where(Vendor.name == "VERONIQUE ORO CORP")
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.routing_number == "021213371"
    assert fetched.account_type == AccountType.CHECKING
    assert fetched.default_id_number == "01554"


@pytest.mark.asyncio
async def test_create_nacha_file_record(db_session):
    """Test creating a NACHA file tracking record."""
    user = User(
        email="operator@amipi.com",
        username="operator",
        password_hash="pass",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()

    nacha_file = NachaFileRecord(
        filename="AMIPIINC_transmit_07.09.2026.txt",
        file_creation_date="260709",
        file_creation_time="1737",
        file_id_modifier="A",
        total_credit_amount=Decimal("17517.45"),
        total_entry_count=6,
        total_batch_count=1,
        total_block_count=1,
        entry_hash="0013143686",
        raw_content="101 021000021...",
        status=NachaFileStatus.GENERATED,
        created_by_user_id=user.id,
    )
    db_session.add(nacha_file)
    await db_session.commit()

    result = await db_session.execute(
        select(NachaFileRecord).where(NachaFileRecord.id == nacha_file.id)
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.total_credit_amount == Decimal("17517.45")
    assert fetched.created_by_user.username == "operator"


@pytest.mark.asyncio
async def test_create_payment_with_relationships(db_session):
    """Test creating a Payment record linking Vendor, User, and NachaFileRecord."""
    # Setup User and Vendor
    user = User(email="paymaster@amipi.com", username="paymaster", password_hash="pass")
    vendor = Vendor(
        name="DRIESASSUR USA LLC",
        routing_number="021000322",
        account_number="483047158875",
    )
    db_session.add_all([user, vendor])
    await db_session.commit()

    # Create Payment
    payment = Payment(
        vendor_id=vendor.id,
        amount=Decimal("4675.00"),
        id_number="8875",
        effective_date=date(2026, 7, 10),
        status=PaymentStatus.PENDING,
        created_by_user_id=user.id,
    )
    db_session.add(payment)
    await db_session.commit()

    # Query back Payment
    result = await db_session.execute(select(Payment).where(Payment.id == payment.id))
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.amount == Decimal("4675.00")
    assert fetched.vendor.name == "DRIESASSUR USA LLC"
    assert fetched.created_by_user.username == "paymaster"
    assert fetched.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_create_audit_log(db_session):
    """Test creating AuditLog records with JSON details."""
    user = User(email="auditor@amipi.com", username="auditor", password_hash="pass")
    db_session.add(user)
    await db_session.commit()

    log = AuditLog(
        user_id=user.id,
        action="VENDOR_BANKING_UPDATED",
        entity_type="vendor",
        entity_id="v-12345",
        details={"field": "routing_number", "old": "021000021", "new": "021213371"},
        ip_address="192.168.1.100",
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.action == "VENDOR_BANKING_UPDATED"
    assert fetched.details["new"] == "021213371"
    assert fetched.user.username == "auditor"
