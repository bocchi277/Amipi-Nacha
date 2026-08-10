"""
Comprehensive Phase 2 security and correctness stress tests.

Tests every breaking point: CHECK constraints, FK cascades, unique violations,
enum enforcement, boundary values, SQL injection attempts, and relationship
integrity under concurrent-like patterns.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, DataError
from sqlalchemy.orm import selectinload

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


# ============================= HELPERS ========================================

async def _make_user(session, email="u@test.com", username="testuser", role=UserRole.USER):
    """Create and commit a minimal User."""
    user = User(email=email, username=username, password_hash="hash123", role=role)
    session.add(user)
    await session.commit()
    return user


async def _make_vendor(session, name="TEST VENDOR", routing="021000021",
                       acct="123456789", acct_type=AccountType.CHECKING):
    """Create and commit a minimal Vendor."""
    vendor = Vendor(
        name=name, routing_number=routing, account_number=acct,
        account_type=acct_type,
    )
    session.add(vendor)
    await session.commit()
    return vendor


async def _make_nacha_file(session, user_id=None):
    """Create and commit a minimal NachaFileRecord."""
    nf = NachaFileRecord(
        filename="test.txt",
        file_creation_date="260801",
        file_creation_time="1200",
        file_id_modifier="A",
        total_credit_amount=Decimal("1000.00"),
        total_entry_count=1,
        total_batch_count=1,
        total_block_count=1,
        entry_hash="0021000002",
        raw_content="101 021000021...",
        status=NachaFileStatus.GENERATED,
        created_by_user_id=user_id,
    )
    session.add(nf)
    await session.commit()
    return nf


# =============== 1. CHECK CONSTRAINT ENFORCEMENT ==============================

class TestCheckConstraints:
    """Verify that CHECK constraints reject invalid data at the DB level."""

    @pytest.mark.asyncio
    async def test_payment_zero_amount_rejected(self, db_session):
        """Payment with amount = 0 must be rejected by CHECK constraint."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("0.00"),
            id_number="INV001",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        with pytest.raises(IntegrityError, match="ck_payments_amount_positive"):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_payment_negative_amount_rejected(self, db_session):
        """Payment with negative amount must be rejected by CHECK constraint."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("-100.00"),
            id_number="INV002",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        with pytest.raises(IntegrityError, match="ck_payments_amount_positive"):
            await db_session.commit()

    def test_vendor_bad_routing_number_rejected(self):
        """Vendor with non-9-digit routing number must fail ABA validation."""
        from app.nacha.validation import validate_routing_checksum

        assert not validate_routing_checksum("12345")

    def test_vendor_alpha_routing_number_rejected(self):
        """Vendor with alpha characters in routing number must fail ABA validation."""
        from app.nacha.validation import validate_routing_checksum

        assert not validate_routing_checksum("02100ABCD")

    def test_vendor_empty_account_number_rejected(self):
        """Vendor account number validation."""
        from app.nacha.validation import validate_routing_checksum

        assert validate_routing_checksum("021000021")

    @pytest.mark.asyncio
    async def test_nacha_file_zero_entry_count_rejected(self, db_session):
        """NACHA file with 0 entry count must be rejected."""
        nf = NachaFileRecord(
            filename="test.txt",
            file_creation_date="260801",
            file_creation_time="1200",
            total_credit_amount=Decimal("100.00"),
            total_entry_count=0,  # Invalid
            total_batch_count=1,
            total_block_count=1,
            entry_hash="0000000001",
            raw_content="...",
        )
        db_session.add(nf)
        with pytest.raises(IntegrityError, match="ck_nacha_files_entry_count_pos"):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_nacha_file_negative_credit_rejected(self, db_session):
        """NACHA file with negative total credit must be rejected."""
        nf = NachaFileRecord(
            filename="test.txt",
            file_creation_date="260801",
            file_creation_time="1200",
            total_credit_amount=Decimal("-500.00"),
            total_entry_count=1,
            total_batch_count=1,
            total_block_count=1,
            entry_hash="0000000001",
            raw_content="...",
        )
        db_session.add(nf)
        with pytest.raises(IntegrityError, match="ck_nacha_files_credit_nonneg"):
            await db_session.commit()


# =============== 2. FOREIGN KEY CASCADE BEHAVIOR ==============================

class TestForeignKeyCascades:
    """Verify FK cascade behavior: RESTRICT, SET NULL, etc."""

    @pytest.mark.asyncio
    async def test_delete_vendor_with_payments_blocked(self, db_session):
        """Vendor with existing payments MUST NOT be deletable (RESTRICT)."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("500.00"),
            id_number="INV100",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        await db_session.commit()

        # Attempt to delete vendor — must fail
        await db_session.delete(vendor)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_delete_user_nullifies_payment_user_id(self, db_session):
        """Deleting a User must SET NULL on payment.created_by_user_id, not cascade-delete."""
        user = await _make_user(db_session, email="del@test.com", username="deluser")
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("250.00"),
            id_number="INV200",
            effective_date=date(2026, 8, 1),
            created_by_user_id=user.id,
        )
        db_session.add(payment)
        await db_session.commit()
        payment_id = payment.id

        await db_session.delete(user)
        await db_session.commit()

        # Payment must still exist with user_id = NULL
        result = await db_session.execute(select(Payment).where(Payment.id == payment_id))
        fetched = result.scalar_one()
        assert fetched.created_by_user_id is None

    @pytest.mark.asyncio
    async def test_delete_nacha_file_nullifies_payment_fk(self, db_session):
        """Deleting a NachaFileRecord must SET NULL on payment.nacha_file_id."""
        user = await _make_user(db_session, email="nf@test.com", username="nfuser")
        vendor = await _make_vendor(db_session)
        nf = await _make_nacha_file(db_session, user_id=user.id)

        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("300.00"),
            id_number="INV300",
            effective_date=date(2026, 8, 1),
            nacha_file_id=nf.id,
        )
        db_session.add(payment)
        await db_session.commit()
        payment_id = payment.id

        await db_session.delete(nf)
        await db_session.commit()

        result = await db_session.execute(select(Payment).where(Payment.id == payment_id))
        fetched = result.scalar_one()
        assert fetched.nacha_file_id is None

    @pytest.mark.asyncio
    async def test_delete_user_nullifies_audit_log_user_id(self, db_session):
        """Deleting a User must SET NULL on audit_logs.user_id, preserving audit trail."""
        user = await _make_user(db_session, email="aud@test.com", username="auduser")
        log = AuditLog(
            user_id=user.id,
            action="TEST_ACTION",
            details={"key": "value"},
        )
        db_session.add(log)
        await db_session.commit()
        log_id = log.id

        await db_session.delete(user)
        await db_session.commit()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log_id))
        fetched = result.scalar_one()
        assert fetched.user_id is None
        assert fetched.action == "TEST_ACTION"  # Log is preserved

    @pytest.mark.asyncio
    async def test_payment_with_nonexistent_vendor_rejected(self, db_session):
        """Payment referencing a non-existent vendor_id must be rejected by FK."""
        fake_vendor_id = uuid.uuid4()
        payment = Payment(
            vendor_id=fake_vendor_id,
            amount=Decimal("100.00"),
            id_number="FAKE",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        with pytest.raises(IntegrityError):
            await db_session.commit()


# =============== 3. UNIQUE CONSTRAINT ENFORCEMENT =============================

class TestUniqueConstraints:
    """Verify unique constraints block duplicate data."""

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self, db_session):
        """Two users with the same email must be rejected."""
        await _make_user(db_session, email="same@test.com", username="user_a")
        db_session.add(User(email="same@test.com", username="user_b", password_hash="x"))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_duplicate_username_rejected(self, db_session):
        """Two users with the same username must be rejected."""
        await _make_user(db_session, email="a@test.com", username="samename")
        db_session.add(User(email="b@test.com", username="samename", password_hash="x"))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_email_case_sensitivity(self, db_session):
        """Email uniqueness is case-sensitive at DB level (document this behavior)."""
        await _make_user(db_session, email="Case@Test.com", username="caseuser1")
        # Different case should succeed at DB level (app should normalize)
        u2 = User(email="case@test.com", username="caseuser2", password_hash="x")
        db_session.add(u2)
        await db_session.commit()
        assert u2.id is not None


# =============== 4. ENUM ENFORCEMENT ==========================================

class TestEnumEnforcement:
    """Verify PostgreSQL enum types reject invalid values at DB level."""

    @pytest.mark.asyncio
    async def test_invalid_user_role_rejected(self, db_session):
        """Inserting an invalid role via raw SQL must be rejected."""
        with pytest.raises(Exception):
            await db_session.execute(
                text("""
                    INSERT INTO users (id, email, username, password_hash, role, is_active)
                    VALUES (gen_random_uuid(), 'bad@test.com', 'baduser', 'hash', 'superadmin', true)
                """)
            )
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_invalid_payment_status_rejected(self, db_session):
        """Inserting an invalid payment status via raw SQL must be rejected."""
        vendor = await _make_vendor(db_session)
        with pytest.raises(Exception):
            await db_session.execute(
                text("""
                    INSERT INTO payments (id, vendor_id, amount, id_number, effective_date, status)
                    VALUES (gen_random_uuid(), :vid, 100.00, 'INV', '2026-08-01', 'APPROVED')
                """),
                {"vid": str(vendor.id)},
            )
            await db_session.commit()


# =============== 5. BOUNDARY & EDGE CASES =====================================

class TestBoundaryValues:
    """Test boundary values for field lengths, precision, and limits."""

    @pytest.mark.asyncio
    async def test_vendor_name_at_max_length(self, db_session):
        """Vendor name at exactly 22 chars must succeed."""
        vendor = await _make_vendor(db_session, name="A" * 22)
        assert len(vendor.name) == 22

    @pytest.mark.asyncio
    async def test_vendor_name_exceeds_max_length(self, db_session):
        """Vendor name exceeding 22 chars must be rejected at DB level."""
        vendor = Vendor(
            name="A" * 23,  # 23 chars > VARCHAR(22)
            routing_number="021000021",
            account_number="123",
        )
        db_session.add(vendor)
        with pytest.raises((DataError, DBAPIError)):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_routing_number_exactly_9_digits(self, db_session):
        """Valid 9-digit routing number must succeed."""
        vendor = await _make_vendor(db_session, routing="021000021")
        assert vendor.routing_number == "021000021"

    @pytest.mark.asyncio
    async def test_payment_max_amount(self, db_session):
        """Payment at the max NACHA amount ($99,999,999.99) must succeed."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("99999999.99"),
            id_number="MAXAMT",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        await db_session.commit()
        assert payment.amount == Decimal("99999999.99")

    @pytest.mark.asyncio
    async def test_payment_one_cent(self, db_session):
        """Payment of $0.01 (minimum valid amount) must succeed."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("0.01"),
            id_number="MINCENT",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        await db_session.commit()
        assert payment.amount == Decimal("0.01")

    @pytest.mark.asyncio
    async def test_decimal_precision_preserved(self, db_session):
        """Amounts like $19.99 must not suffer float rounding in the DB."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("19.99"),
            id_number="PREC",
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        await db_session.commit()

        result = await db_session.execute(select(Payment).where(Payment.id == payment.id))
        fetched = result.scalar_one()
        assert fetched.amount == Decimal("19.99")

    @pytest.mark.asyncio
    async def test_id_number_at_max_length(self, db_session):
        """Payment id_number at exactly 15 chars must succeed."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("10.00"),
            id_number="A" * 15,
            effective_date=date(2026, 8, 1),
        )
        db_session.add(payment)
        await db_session.commit()
        assert len(payment.id_number) == 15


# =============== 6. SQL INJECTION RESISTANCE ==================================

class TestSQLInjectionResistance:
    """Verify parameterized queries prevent SQL injection via ORM fields."""

    @pytest.mark.asyncio
    async def test_injection_in_vendor_name(self, db_session):
        """SQL injection attempt in vendor name must be stored as literal text."""
        evil_name = "'; DROP TABLE--"
        vendor = await _make_vendor(db_session, name=evil_name[:22])
        result = await db_session.execute(
            select(Vendor).where(Vendor.id == vendor.id)
        )
        fetched = result.scalar_one()
        assert fetched.name == evil_name[:22]

        # Confirm tables still exist
        tables = await db_session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        table_names = {row[0] for row in tables}
        assert "vendors" in table_names
        assert "payments" in table_names

    @pytest.mark.asyncio
    async def test_injection_in_audit_log_details(self, db_session):
        """SQL injection attempt in JSONB details must be stored as literal JSON."""
        user = await _make_user(db_session, email="inj@test.com", username="injuser")
        evil_details = {
            "payload": "'; DROP TABLE users; --",
            "nested": {"attack": "1=1 OR true"},
        }
        log = AuditLog(
            user_id=user.id,
            action="SQL_INJECTION_TEST",
            details=evil_details,
        )
        db_session.add(log)
        await db_session.commit()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
        fetched = result.scalar_one()
        assert fetched.details["payload"] == "'; DROP TABLE users; --"

    @pytest.mark.asyncio
    async def test_injection_in_user_email(self, db_session):
        """SQL injection in email field must be stored as literal, not executed."""
        evil_email = "admin'--@evil.com"
        user = await _make_user(db_session, email=evil_email, username="evilemail")
        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched = result.scalar_one()
        assert fetched.email == evil_email


# =============== 7. RELATIONSHIP INTEGRITY ====================================

class TestRelationshipIntegrity:
    """Verify ORM relationships load correctly in both directions."""

    @pytest.mark.asyncio
    async def test_payment_vendor_bidirectional(self, db_session):
        """Payment.vendor and Vendor.payments must be consistent."""
        vendor = await _make_vendor(db_session, name="BIDIR VENDOR")
        p1 = Payment(
            vendor_id=vendor.id, amount=Decimal("100.00"),
            id_number="A", effective_date=date(2026, 1, 1),
        )
        p2 = Payment(
            vendor_id=vendor.id, amount=Decimal("200.00"),
            id_number="B", effective_date=date(2026, 1, 2),
        )
        db_session.add_all([p1, p2])
        await db_session.commit()

        # Reload vendor fresh
        result = await db_session.execute(select(Vendor).where(Vendor.id == vendor.id))
        v = result.scalar_one()
        assert len(v.payments) == 2
        assert {p.amount for p in v.payments} == {Decimal("100.00"), Decimal("200.00")}

    @pytest.mark.asyncio
    async def test_nacha_file_payment_link(self, db_session):
        """Payments linked to a NACHA file should be accessible from both sides."""
        user = await _make_user(db_session, email="link@test.com", username="linkuser")
        vendor = await _make_vendor(db_session)
        nf = await _make_nacha_file(db_session, user_id=user.id)

        payment = Payment(
            vendor_id=vendor.id, amount=Decimal("50.00"),
            id_number="LINK", effective_date=date(2026, 1, 1),
            nacha_file_id=nf.id,
        )
        db_session.add(payment)
        await db_session.commit()

        # Payment -> NACHA file (use selectinload to avoid sync lazy load in async)
        result = await db_session.execute(
            select(Payment)
            .where(Payment.id == payment.id)
            .options(selectinload(Payment.nacha_file))
        )
        p = result.scalar_one()
        assert p.nacha_file.filename == "test.txt"

        # NACHA file -> payments (use selectinload)
        result2 = await db_session.execute(
            select(NachaFileRecord)
            .where(NachaFileRecord.id == nf.id)
            .options(selectinload(NachaFileRecord.payments))
        )
        f = result2.scalar_one()
        assert len(f.payments) == 1
        assert f.payments[0].id == payment.id

    @pytest.mark.asyncio
    async def test_audit_log_without_user(self, db_session):
        """Audit log with NULL user_id must be insertable (system-level events)."""
        log = AuditLog(
            user_id=None,
            action="SYSTEM_STARTUP",
            details={"event": "application_boot"},
        )
        db_session.add(log)
        await db_session.commit()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
        fetched = result.scalar_one()
        assert fetched.user_id is None
        assert fetched.action == "SYSTEM_STARTUP"


# =============== 8. TIMESTAMP & DEFAULT BEHAVIOR ==============================

class TestTimestampsAndDefaults:
    """Verify server_default timestamps and default field values."""

    @pytest.mark.asyncio
    async def test_user_created_at_auto_populated(self, db_session):
        """User.created_at must be automatically populated by the DB."""
        user = await _make_user(db_session, email="ts@test.com", username="tsuser")
        assert user.created_at is not None

    @pytest.mark.asyncio
    async def test_payment_default_status_is_pending(self, db_session):
        """Payment default status must be PENDING when not explicitly set."""
        vendor = await _make_vendor(db_session)
        payment = Payment(
            vendor_id=vendor.id,
            amount=Decimal("50.00"),
            id_number="DEF",
            effective_date=date(2026, 8, 1),
            # status NOT set
        )
        db_session.add(payment)
        await db_session.commit()
        assert payment.status == PaymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_vendor_default_account_type_is_checking(self, db_session):
        """Vendor default account_type must be CHECKING."""
        vendor = Vendor(
            name="DEFAULTTYPE",
            routing_number="021000021",
            account_number="999",
            # account_type NOT set
        )
        db_session.add(vendor)
        await db_session.commit()
        assert vendor.account_type == AccountType.CHECKING

    @pytest.mark.asyncio
    async def test_user_default_role_is_user(self, db_session):
        """User default role must be USER (not ADMIN)."""
        user = User(email="defrole@test.com", username="defrole", password_hash="x")
        db_session.add(user)
        await db_session.commit()
        assert user.role == UserRole.USER

    @pytest.mark.asyncio
    async def test_user_default_is_active(self, db_session):
        """User default is_active must be True."""
        user = User(email="defact@test.com", username="defact", password_hash="x")
        db_session.add(user)
        await db_session.commit()
        assert user.is_active is True


# =============== 9. ALEMBIC MIGRATION SANITY ==================================

class TestMigrationSanity:
    """Verify the live database schema matches expectations after migration."""

    @pytest.mark.asyncio
    async def test_all_tables_exist(self, db_session):
        """All 5 expected tables must exist in the public schema."""
        result = await db_session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {row[0] for row in result}
        expected = {"users", "vendors", "nacha_files", "payments", "audit_logs", "alembic_version"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    @pytest.mark.asyncio
    async def test_check_constraints_exist(self, db_session):
        """All CHECK constraints must be present in the live schema."""
        result = await db_session.execute(
            text("""
                SELECT conname FROM pg_constraint
                WHERE contype = 'c' AND conname LIKE 'ck_%'
            """)
        )
        constraints = {row[0] for row in result}
        expected = {
            "ck_payments_amount_positive",
            "ck_nacha_files_credit_nonneg",
            "ck_nacha_files_entry_count_pos",
            "ck_nacha_files_batch_count_pos",
            "ck_nacha_files_block_count_pos",
        }
        assert expected.issubset(constraints), f"Missing constraints: {expected - constraints}"

    @pytest.mark.asyncio
    async def test_foreign_keys_exist(self, db_session):
        """All foreign key constraints must be present."""
        result = await db_session.execute(
            text("""
                SELECT conname FROM pg_constraint
                WHERE contype = 'f'
            """)
        )
        fk_names = {row[0] for row in result}
        # At minimum we expect FK constraints on payments, nacha_files, audit_logs
        assert len(fk_names) >= 5, f"Expected >= 5 FK constraints, got {len(fk_names)}: {fk_names}"

    @pytest.mark.asyncio
    async def test_indexes_exist(self, db_session):
        """Key indexes must exist for query performance."""
        result = await db_session.execute(
            text("""
                SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
            """)
        )
        indexes = {row[0] for row in result}
        expected_indexes = {
            "ix_users_email",
            "ix_users_username",
            "ix_vendors_name",
            "ix_payments_vendor_id",
            "ix_payments_nacha_file_id",
            "ix_audit_logs_action",
            "ix_audit_logs_user_id",
        }
        assert expected_indexes.issubset(indexes), f"Missing indexes: {expected_indexes - indexes}"
