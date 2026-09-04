from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import InvoiceStatus
from app.schemas.company import CompanyOut


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_number: str
    amount_total: Decimal
    amount_paid: Decimal
    currency: str
    issue_date: date
    due_date: date
    status: InvoiceStatus
    company: CompanyOut
    created_at: datetime
    updated_at: datetime
