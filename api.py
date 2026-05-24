import hashlib
import io
import pandas as pd
import schemas
from contextlib import asynccontextmanager
from database import SessionLocal, init_db, User, Category, Account, Transaction
from datetime import date
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_
from typing import List


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ProFinance API (Prototype)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/users", response_model=List[schemas.UserResponse], tags=["Пользователи"])
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@app.post("/users", response_model=schemas.UserResponse, tags=["Пользователи"])
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.name == user.name).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Пользователь существует")
    new_user = User(name=user.name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.get("/categories", response_model=List[schemas.CategoryResponse], tags=["Категории"])
def get_categories(user_id: int, db: Session = Depends(get_db)):
    return db.query(Category).filter(Category.user_id == user_id).all()


@app.post("/categories", response_model=schemas.CategoryResponse, tags=["Категории"])
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db)):
    if category.sort_order == 0:
        max_sort = db.query(func.max(Category.sort_order)).filter(Category.user_id == category.user_id).scalar() or 0
        category.sort_order = max_sort + 1

    new_category = Category(**category.model_dump())
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category


@app.get("/accounts", response_model=List[schemas.AccountResponse], tags=["Счета"])
def get_accounts(user_id: int, db: Session = Depends(get_db)):
    return db.query(Account).filter(Account.user_id == user_id).all()


@app.post("/accounts", response_model=schemas.AccountResponse, tags=["Счета"])
def create_account(account: schemas.AccountCreate, db: Session = Depends(get_db)):
    new_account = Account(**account.model_dump())
    new_account.initial_balance = account.balance
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    return new_account


@app.get("/transactions", response_model=List[schemas.TransactionResponse], tags=["Транзакции"])
def get_transactions(user_id: int, db: Session = Depends(get_db)):
    return db.query(Transaction).filter(Transaction.user_id == user_id).all()


@app.post("/transactions", response_model=schemas.TransactionResponse, tags=["Транзакции"])
def create_transaction(tx: schemas.TransactionCreate, db: Session = Depends(get_db)):
    new_tx = Transaction(**tx.model_dump())
    db.add(new_tx)

    if not tx.is_planned:
        account = db.query(Account).filter(Account.account_id == tx.account_id).first()
        if account:
            if tx.type == "expense":
                account.balance -= tx.amount
            elif tx.type == "income":
                account.balance += tx.amount

    db.commit()
    db.refresh(new_tx)
    return new_tx


@app.delete("/transactions/{transaction_id}", tags=["Транзакции"])
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    if not tx.is_planned:
        account = db.query(Account).filter(Account.account_id == tx.account_id).first()
        if account:
            if tx.type == "expense":
                account.balance += tx.amount
            elif tx.type == "income":
                account.balance -= tx.amount

    db.delete(tx)
    db.commit()
    return {"message": "Удалено и баланс пересчитан"}


@app.get("/analytics/dashboard", tags=["Аналитика"])
def get_dashboard_data(
        user_id: int,
        start_date: date,
        end_date: date,
        db: Session = Depends(get_db)
):
    """
    Возвращает полностью готовые данные для отрисовки сетки 'Бюджет на год'.
    """
    current_week = date.today().strftime('%Y-%W')

    initial_balances = db.query(func.sum(Account.initial_balance)).filter(Account.user_id == user_id).scalar() or 0.0

    past_incomes = db.query(func.sum(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.date < start_date,
        Transaction.type == 'income',
        Transaction.is_planned == False
    ).scalar() or 0.0

    past_expenses = db.query(func.sum(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.date < start_date,
        Transaction.type == 'expense',
        Transaction.is_planned == False
    ).scalar() or 0.0

    starting_balance = initial_balances + past_incomes - past_expenses

    week_expr = func.strftime('%Y-%W', Transaction.date).label('week')

    fact_exp = func.sum(case((Transaction.is_planned == False, Transaction.amount), else_=0)).label('fact_exp')
    plan_exp = func.sum(case((Transaction.is_planned == True, Transaction.amount), else_=0)).label('plan_exp')

    query = (
        db.query(
            week_expr,
            Category.name.label('cat_name'),
            Category.type.label('cat_type'),
            Category.color.label('cat_color'),
            Category.icon.label('cat_icon'),
            Category.sort_order.label('cat_sort'),
            fact_exp,
            plan_exp
        )
        .join(Category, Transaction.category_id == Category.category_id)
        .filter(
            Transaction.user_id == user_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date
        )
        .group_by(week_expr, Category.name, Category.type)
        .all()
    )

    categories_data = {}
    weekly_totals = {}

    for row in query:
        w = row.week
        cat = row.cat_name
        c_type = row.cat_type

        if w not in weekly_totals:
            weekly_totals[w] = {"total_income": 0, "total_expense": 0, "balance": 0}

        if cat not in categories_data:
            categories_data[cat] = {
                "type": row.cat_type,
                "color": row.cat_color,
                "icon": row.cat_icon,
                "sort_order": row.cat_sort,
                "weeks": {}
            }

        categories_data[cat]["weeks"][w] = {
            "plan": row.plan_exp,
            "fact": row.fact_exp
        }

        if c_type == 'income':
            weekly_totals[w]["total_income"] += row.fact_exp
        else:
            weekly_totals[w]["total_expense"] += row.fact_exp

    sorted_weeks = sorted(weekly_totals.keys())
    current_running_balance = starting_balance

    for w in sorted_weeks:
        inc = weekly_totals[w]["total_income"]
        exp = weekly_totals[w]["total_expense"]

        weekly_totals[w]["net_total"] = inc - exp

        current_running_balance += inc
        current_running_balance -= exp
        weekly_totals[w]["balance"] = current_running_balance

    return {
        "current_week": current_week,
        # "starting_balance": starting_balance,
        "categories": categories_data,
        "weekly_totals": weekly_totals
    }

@app.post("/import", tags=["Импорт и Экспорт"])
async def import_transactions(
        user_id: int,
        account_id: int,
        file: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    """
    Загрузка выписки из банка в формате Excel.
    """
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="Ошибка чтения Excel файла")

    user_categories = db.query(Category).filter(Category.user_id == user_id).all()


    default_cat = next((cat for cat in user_categories if cat.name == "Прочее"), None)
    if not default_cat:
        default_cat = Category(user_id=user_id, name="Прочее", type="expense")
        db.add(default_cat)
        db.commit()
        db.refresh(default_cat)

    added_count = 0
    skipped_count = 0

    for index, row in df.iterrows():
        try:
            date_val = pd.to_datetime(row['Дата'], dayfirst=True).date()
            amount_val = float(row['Сумма'])
            desc_val = str(row['Описание'])
        except (KeyError, ValueError):
            continue

        raw_str = f"{date_val}{amount_val}{desc_val}"
        tx_hash = hashlib.md5(raw_str.encode('utf-8')).hexdigest()

        if db.query(Transaction).filter(Transaction.hash == tx_hash).first():
            skipped_count += 1
            continue

        assigned_category_id = default_cat.category_id
        desc_lower = desc_val.lower()

        for category in user_categories:
            if category.name.lower() in desc_lower:
                assigned_category_id = category.category_id
                break


        tx_type = "expense" if amount_val < 0 else "income"

        new_tx = Transaction(
            user_id=user_id,
            account_id=account_id,
            category_id=assigned_category_id,
            amount=abs(amount_val),
            type=tx_type,
            date=date_val,
            description=desc_val,
            is_planned=False,
            hash=tx_hash
        )
        db.add(new_tx)
        added_count += 1

    db.commit()
    return {"message": "Успешно", "added": added_count, "skipped": skipped_count}


@app.get("/export/excel", tags=["Импорт и Экспорт"])
def export_budget_to_excel(user_id: int, start_date: date, end_date: date, db: Session = Depends(get_db)):
    week_expr = func.strftime('%Y-%W', Transaction.date).label('week')
    fact_sum = func.sum(case((Transaction.is_planned == False, Transaction.amount), else_=0)).label('fact_amount')
    plan_sum = func.sum(case((Transaction.is_planned == True, Transaction.amount), else_=0)).label('plan_amount')

    query = (
        db.query(week_expr, Category.name.label('category_name'), fact_sum, plan_sum)
        .join(Category, Transaction.category_id == Category.category_id)
        .filter(
            Transaction.user_id == user_id, Transaction.date >= start_date, Transaction.date <= end_date
        )
        .group_by(week_expr, Category.name).all()
    )

    if not query:
        raise HTTPException(status_code=404, detail="Нет данных для экспорта")

    data = [{"Категория": row.category_name, "Неделя": f"Неделя {row.week.split('-')[1]}", "Факт": row.fact_amount,
             "План": row.plan_amount} for row in query]

    df = pd.DataFrame(data)
    pivot_df = df.pivot_table(index='Категория', columns='Неделя', values=['План', 'Факт'], aggfunc='sum').fillna(0)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pivot_df.to_excel(writer, sheet_name='Бюджет')
    output.seek(0)

    return StreamingResponse(
        output,
        headers={'Content-Disposition': f'attachment; filename="budget_{start_date}_{end_date}.xlsx"'},
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )