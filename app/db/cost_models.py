from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import synonym

from app.db.database import Base


class AccountMaster(Base):
    __tablename__ = "account_master"

    account_id = Column(String(50), primary_key=True)
    account_name = Column(String(255), nullable=False)
    product = Column(String(255), nullable=True)
    team = Column(String(255), nullable=True)
    environment = Column(String(50), nullable=False)
    developer_type = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MonthlyCost(Base):
    __tablename__ = "monthly_costs"

    id = Column(Integer, primary_key=True)
    billing_period = Column(String(7), nullable=False, unique=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_cost = Column(Numeric(12, 4), nullable=False, default=Decimal("0.00"))
    currency = Column(String(10), nullable=False, default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)


class ServiceCost(Base):
    __tablename__ = "service_costs"

    id = Column(Integer, primary_key=True)
    billing_period = Column(String(7), nullable=False)
    account_id = Column(String(50), nullable=True)
    account_name = Column(String(255), nullable=True)
    product = Column(String(255), nullable=True)
    team = Column(String(255), nullable=True)
    environment = Column(String(50), nullable=True)
    developer_type = Column(String(50), nullable=True)
    raw_service_name = Column(String(255), nullable=False, default="")
    business_service_name = Column(String(255), nullable=False, default="")
    region = Column(String(100), nullable=False, default="us-east-1")
    cost = Column(Numeric(12, 4), nullable=False, default=Decimal("0.00"))
    currency = Column(String(10), nullable=False, default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Alias / synonym for backward compatibility
    service_name = synonym("business_service_name")

    __table_args__ = (
        UniqueConstraint(
            "billing_period",
            "account_id",
            "raw_service_name",
            "region",
            "currency",
            name="uq_service_costs_billing_account_service_region_currency"
        ),
    )


class CostSyncHistory(Base):
    __tablename__ = "cost_sync_history"

    id = Column(Integer, primary_key=True)
    billing_period = Column(String(7), nullable=False)
    sync_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), nullable=False)
    records_inserted = Column(Integer, nullable=False, default=0)
    duration_seconds = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImportHistory(Base):
    __tablename__ = "import_history"

    id = Column(Integer, primary_key=True)
    file_name = Column(String(255), nullable=False)
    billing_period = Column(String(7), nullable=False)
    rows_read = Column(Integer, nullable=False, default=0)
    rows_inserted = Column(Integer, nullable=False, default=0)
    rows_updated = Column(Integer, nullable=False, default=0)
    duplicates = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False)
