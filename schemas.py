from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

class UserCreate(BaseModel):
    name: str


class UserResponse(BaseModel):
    user_id: int
    name: str
    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    user_id: int
    name: str
    type: str
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = 0


class CategoryResponse(BaseModel):
    category_id: int
    user_id: int
    name: str
    type: str
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None

    class Config:
        from_attributes = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class AccountCreate(BaseModel):
    user_id: int
    name: str
    type: str
    balance: float = 0.0


class AccountResponse(BaseModel):
    account_id: int
    user_id: int
    name: str
    type: str
    balance: float
    class Config:
        from_attributes = True


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    balance: Optional[float] = None
    is_active: Optional[bool] = None


class TransactionCreate(BaseModel):
    user_id: int
    account_id: int
    category_id: int
    amount: float
    week: str
    description: Optional[str] = None
    is_planned: bool = False


class TransactionUpdate(BaseModel):
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    amount: Optional[float] = None
    week: Optional[str] = None
    description: Optional[str] = None
    is_planned: Optional[bool] = None


class TransactionResponse(BaseModel):
    transaction_id: int
    user_id: int
    account_id: int
    category_id: int
    amount: float
    week: str
    description: Optional[str]
    is_planned: bool
    created_at: datetime
    class Config:
        from_attributes = True


class WeeklyReportResponse(BaseModel):
    week: str
    category_name: str
    expense: float
    income: float


class RecurringCreate(BaseModel):
    user_id: int
    account_id: int
    category_id: int
    amount: float
    start_week: str
    end_week: Optional[str] = None
    is_planned: bool = False


class RecurringUpdate(BaseModel):
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    amount: Optional[float] = None
    end_week: Optional[str] = None
    is_planned: Optional[bool] = None


class RecurringResponse(RecurringCreate):
    recurring_id: int
    next_sync_week: Optional[str] = None

    class Config:
        from_attributes = True


class TransferCreate(BaseModel):
    user_id: int
    from_account_id: int
    to_account_id: int
    amount: float
    week: str
    description: Optional[str] = "Перевод между счетами"