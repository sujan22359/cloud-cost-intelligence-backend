from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db.cost_models import AccountMaster, CostSyncHistory, ImportHistory, MonthlyCost, ServiceCost
from app.db.knowledge_models import OrganizationKnowledge
from app.db.database import Base


class SystemHealth(Base):
    __tablename__ = "system_health"

    id = Column(Integer, primary_key=True)
    service_name = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
