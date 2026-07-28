from enum import Enum
from pydantic import BaseModel, Field


class DimensionType(str, Enum):
    PRODUCT = "PRODUCT"
    TEAM = "TEAM"
    ENVIRONMENT = "ENVIRONMENT"
    ACCOUNT = "ACCOUNT"
    REGION = "REGION"


class ServiceCost(BaseModel):
    service: str
    amount: float
    unit: str = "USD"
    percentage: float


class MonthlyCost(BaseModel):
    month: str = Field(description="Month label in YYYY-MM format.")
    total_cost: float
    unit: str = "USD"


class TotalCostResponse(BaseModel):
    start: str
    end: str
    total_cost: float
    unit: str = "USD"


class ServiceBreakdownResponse(BaseModel):
    start: str
    end: str
    total_cost: float
    unit: str = "USD"
    services: list[ServiceCost]


class MonthlyCostResponse(BaseModel):
    months: list[MonthlyCost]
    change_amount: float
    change_percent: float


class CostByMonthResponse(BaseModel):
    month: str
    total_cost: float
    unit: str = "USD"


class HistoricalBootstrapResponse(BaseModel):
    months_downloaded: int
    months_skipped: int
    records_inserted: int
    status: str
