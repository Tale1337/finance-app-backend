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
    budget_limit: Optional[float] = None
    sort_order: Optional[int] = 0

class CategoryResponse(BaseModel):
    category_id: int
    user_id: int
    name: str
    type: str
    icon: Optional[str] = None
    color: Optional[str] = None
    budget_limit: Optional[float] = None
    sort_order: Optional[int] = None

    class Config:
        from_attributes = True

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

class TransactionCreate(BaseModel):
    user_id: int
    account_id: int
    category_id: int
    amount: float
    type: str
    date: date
    description: Optional[str] = None
    is_planned: bool = False

class TransactionResponse(BaseModel):
    transaction_id: int
    user_id: int
    account_id: int
    category_id: int
    amount: float
    type: str
    date: date
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