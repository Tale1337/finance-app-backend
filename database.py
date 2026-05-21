import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Date, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
db_path = BASE_DIR / "database.sqlite"

engine = create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

class Setting(Base):
    __tablename__ = "settings"
    setting_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    key = Column(String, nullable=False)
    value = Column(JSON, nullable=True)

class Notification(Base):
    __tablename__ = "notifications"
    notification_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)

class Deposit(Base):
    __tablename__ = "deposits"
    deposit_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    name = Column(String, nullable=False)
    bank_name = Column(String, nullable=True)
    initial_amount = Column(Float, default=0.0)
    current_amount = Column(Float, default=0.0)
    interest_rate = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)

class Account(Base):
    __tablename__ = "accounts"
    account_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    balance = Column(Float, default=0.0)
    initial_balance = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

class Category(Base):
    __tablename__ = "categories"
    category_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    icon = Column(String, nullable=True)
    color = Column(String, nullable=True)
    budget_limit = Column(Float, nullable=True)
    sort_order = Column(Integer, default=0)

class Budget(Base):
    __tablename__ = "budgets"
    budget_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    category_id = Column(Integer, ForeignKey("categories.category_id"))
    period_type = Column(String, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    planned_amount = Column(Float, default=0.0)
    actual_amount = Column(Float, default=0.0)

class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"
    recurring_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    account_id = Column(Integer, ForeignKey("accounts.account_id"))
    category_id = Column(Integer, ForeignKey("categories.category_id"))
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)
    interval = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)

class Transaction(Base):
    __tablename__ = "transactions"
    transaction_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    account_id = Column(Integer, ForeignKey("accounts.account_id"))
    category_id = Column(Integer, ForeignKey("categories.category_id"))
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    description = Column(String, nullable=True)
    is_planned = Column(Boolean, default=False)
    is_recurring = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    hash = Column(String, unique=True, index=True, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        default_user = db.query(User).filter(User.name == "Основной").first()
        if not default_user:
            new_user = User(name="Основной")
            db.add(new_user)
            db.commit()
            print('База данных успешно инициализирована. Создан юзер "Основной".')
    finally:
        db.close()

if __name__ == "__main__":
    init_db()