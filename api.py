import hashlib
import io
import pandas as pd
import schemas
import shutil
from contextlib import asynccontextmanager
from database import SessionLocal, SandboxSessionLocal, db_path, sandbox_path, init_db, User, Category, Account, Transaction, Budget, RecurringTransaction
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List
from dateutil.relativedelta import relativedelta


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    db = SessionLocal()
    try:
        process_recurring_transactions(db)
    except Exception as e:
        print(f"Ошибка при синхронизации подписок: {e}")
    finally:
        db.close()

    yield


app = FastAPI(title="ProFinance API (Prototype)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SANDBOX_MODE = False


def get_db():
    """Отдает правильную базу в зависимости от режима"""
    global SANDBOX_MODE

    if SANDBOX_MODE:
        db = SandboxSessionLocal()
    else:
        db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_week_info(target_date):
    """Превращает любую дату в данные о неделе"""
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    week_number = start_of_week.strftime('%Y-%W')
    return week_number, start_of_week, end_of_week


def add_one_week(week_str: str) -> str:
    """Прибавляет 1 неделю к строке вида '2026-21'"""
    dt = datetime.strptime(week_str + '-1', "%Y-%W-%w")
    next_dt = dt + timedelta(days=7)
    return next_dt.strftime('%Y-%W')


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
    """icon, color, sort_order - опционально
    * type: {expense, income}"""
    if category.sort_order == 0:
        max_sort = db.query(func.max(Category.sort_order)).filter(Category.user_id == category.user_id).scalar() or 0
        category.sort_order = max_sort + 1

    new_category = Category(**category.model_dump())
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category

@app.put("/categories/{category_id}", response_model=schemas.CategoryResponse, tags=["Категории"])
def update_category(category_id: int, cat_update: schemas.CategoryUpdate, db: Session = Depends(get_db)):
    db_cat = db.query(Category).filter(Category.category_id == category_id).first()
    if not db_cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    update_data = cat_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_cat, key, value)

    db.commit()
    db.refresh(db_cat)
    return db_cat

@app.delete("/categories/{category_id}", tags=["Категории"])
def delete_category(category_id: int, user_id: int, db: Session = Depends(get_db)):
    db_cat = db.query(Category).filter(Category.category_id == category_id).first()
    if not db_cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    default_cat = db.query(Category).filter(Category.name == "Прочее", Category.user_id == user_id).first()
    if not default_cat:
        default_cat = Category(user_id=user_id, name="Прочее", type="expense")
        db.add(default_cat)
        db.commit()
        db.refresh(default_cat)

    db.query(Transaction).filter(Transaction.category_id == category_id).update({"category_id": default_cat.category_id})

    db.delete(db_cat)
    db.commit()
    return {"message": "Категория удалена, старые транзакции перенесены в 'Прочее'"}


@app.get("/accounts", response_model=List[schemas.AccountResponse], tags=["Счета"])
def get_accounts(user_id: int, db: Session = Depends(get_db)):
    return db.query(Account).filter(Account.user_id == user_id).all()


@app.post("/accounts", response_model=schemas.AccountResponse, tags=["Счета"])
def create_account(account: schemas.AccountCreate, db: Session = Depends(get_db)):
    """type: {card, credit, deposit}"""
    new_account = Account(**account.model_dump())
    new_account.initial_balance = account.balance
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    return new_account


@app.put("/accounts/{account_id}", response_model=schemas.AccountResponse, tags=["Счета"])
def update_account(account_id: int, account_update: schemas.AccountUpdate, db: Session = Depends(get_db)):
    db_account = db.query(Account).filter(Account.account_id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Счет не найден")

    update_data = account_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_account, key, value)

    db.commit()
    db.refresh(db_account)
    return db_account


@app.delete("/accounts/{account_id}", tags=["Счета"])
def delete_account(account_id: int, db: Session = Depends(get_db)):
    db_account = db.query(Account).filter(Account.account_id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Счет не найден")

    db_account.is_active = False
    db.commit()
    return {"message": "Счет перенесен в архив"}


@app.get("/transactions", response_model=List[schemas.TransactionResponse], tags=["Транзакции"])
def get_transactions(user_id: int, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return db.query(Transaction).filter(Transaction.user_id == user_id).offset(offset).limit(limit).all()


@app.post("/transactions", response_model=schemas.TransactionResponse, tags=["Транзакции"])
def create_transaction(tx: schemas.TransactionCreate, db: Session = Depends(get_db)):
    """
    **Создание новой транзакции (План или Факт)**.

    * Если `is_planned = False` (Факт): Бэкенд автоматически пересчитает баланс указанного счета.
    * Если `is_planned = True` (План): Транзакция сохранится, но реальный баланс счета не изменится.
    Неделю передавать в формате `YYYY-WW` (например, `2026-21`).
    """
    account = db.query(Account).filter(Account.account_id == tx.account_id).first()
    category = db.query(Category).filter(Category.category_id == tx.category_id).first()

    if not account or not category:
        raise HTTPException(status_code=404, detail="Счет или категория не найдены")

    new_tx = Transaction(**tx.model_dump())
    db.add(new_tx)

    if not tx.is_planned:
        if category.type == "expense":
            account.balance -= tx.amount
        elif category.type == "income":
            account.balance += tx.amount

    db.commit()
    db.refresh(new_tx)
    return new_tx


@app.put("/transactions/{transaction_id}", response_model=schemas.TransactionResponse, tags=["Транзакции"])
def update_transaction(transaction_id: int, tx_update: schemas.TransactionUpdate, db: Session = Depends(get_db)):
    """
    **Редактирование ячейки (транзакции)**.

    Используется, когда пользователь меняет сумму прямо в таблице.
    Бэкенд сам откатит старый баланс счета и применит новый.
    """
    tx = db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
    if not tx: raise HTTPException(status_code=404, detail="Транзакция не найдена")

    account = db.query(Account).filter(Account.account_id == tx.account_id).first()
    old_category = db.query(Category).filter(Category.category_id == tx.category_id).first()

    if not tx.is_planned and account and old_category:
        if old_category.type == "expense":
            account.balance += tx.amount
        elif old_category.type == "income":
            account.balance -= tx.amount

    update_data = tx_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tx, key, value)

    new_category = db.query(Category).filter(Category.category_id == tx.category_id).first()
    if not tx.is_planned and account and new_category:
        if new_category.type == "expense":
            account.balance -= tx.amount
        elif new_category.type == "income":
            account.balance += tx.amount

    db.commit()
    db.refresh(tx)
    return tx


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
def get_dashboard_data(user_id: int, start_week: str, end_week: str, db: Session = Depends(get_db)):
    """
    **Генерация данных для таблицы "Бюджет на год"**.

    Главный эндпоинт приложения. Отдает готовую сетку:
    * Считает `starting_balance` (накопительный баланс на начало `start_week`).
    * Раскладывает транзакции по категориям и неделям (ячейкам).
    * Выводит `transaction_id` в каждой ячейке.
    * Выводит итоги по каждой неделе.
    """
    current_week = date.today().strftime('%Y-%W')
    initial_balances = db.query(func.sum(Account.initial_balance)).filter(Account.user_id == user_id).scalar() or 0.0

    past_incomes = db.query(func.sum(Transaction.amount)).join(Category).filter(
        Transaction.user_id == user_id,
        Transaction.week < start_week,
        Category.type == 'income',
        Transaction.is_planned.is_(False)
    ).scalar() or 0.0

    past_expenses = db.query(func.sum(Transaction.amount)).join(Category).filter(
        Transaction.user_id == user_id,
        Transaction.week < start_week,
        Category.type == 'expense',
        Transaction.is_planned.is_(False)
    ).scalar() or 0.0

    starting_balance = initial_balances + past_incomes - past_expenses

    transactions = (
        db.query(Transaction, Category)
        .join(Category, Transaction.category_id == Category.category_id)
        .filter(
            Transaction.user_id == user_id,
            Transaction.week >= start_week,
            Transaction.week <= end_week,
            Category.type != 'transfer'
        )
        .all()
    )

    categories_data = {}
    weekly_totals = {}

    for tx, cat in transactions:
        w = tx.week

        if w not in weekly_totals:
            weekly_totals[w] = {
                "fact": {"income": 0, "expense": 0, "net": 0, "balance": 0},
                "plan": {"income": 0, "expense": 0, "net": 0, "balance": 0}
            }

        if cat.name not in categories_data:
            categories_data[cat.name] = {
                "category_id": cat.category_id,
                "type": cat.type,
                "color": cat.color,
                "icon": cat.icon,
                "sort_order": cat.sort_order,
                "weeks": {}
            }

        if w not in categories_data[cat.name]["weeks"]:
            categories_data[cat.name]["weeks"][w] = {"plan": None, "fact": None}

        cell_data = {
            "transaction_id": tx.transaction_id,
            "amount": tx.amount
        }

        if tx.is_planned:
            categories_data[cat.name]["weeks"][w]["plan"] = cell_data
            if cat.type == 'income':
                weekly_totals[w]["plan"]["income"] += tx.amount
            else:
                weekly_totals[w]["plan"]["expense"] += tx.amount
        else:
            categories_data[cat.name]["weeks"][w]["fact"] = cell_data
            if cat.type == 'income':
                weekly_totals[w]["fact"]["income"] += tx.amount
            else:
                weekly_totals[w]["fact"]["expense"] += tx.amount

    sorted_weeks = sorted(weekly_totals.keys())

    current_fact_balance = starting_balance
    current_plan_balance = starting_balance

    for w in sorted_weeks:
        f_net = weekly_totals[w]["fact"]["income"] - weekly_totals[w]["fact"]["expense"]
        weekly_totals[w]["fact"]["net"] = f_net
        current_fact_balance += f_net
        weekly_totals[w]["fact"]["balance"] = current_fact_balance

        p_net = weekly_totals[w]["plan"]["income"] - weekly_totals[w]["plan"]["expense"]
        weekly_totals[w]["plan"]["net"] = p_net
        current_plan_balance += p_net
        weekly_totals[w]["plan"]["balance"] = current_plan_balance

    return {
        "current_week": current_week,
        "starting_balance": starting_balance,
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
    **Умный импорт из Excel (Агрегация по неделям)**.
    1. Читает файл (Дата, Сумма, Описание).
    2. Распределяет по категориям, ища их названия в Описании.
    3. Складывает все чеки одной категории внутри одной недели в единую ячейку.
    """
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="Ошибка чтения Excel файла")

    user_categories = db.query(Category).filter(Category.user_id == user_id).all()

    max_sort = db.query(func.max(Category.sort_order)).filter(Category.user_id == user_id).scalar() or 0

    default_expense = next((cat for cat in user_categories if cat.name == "Прочие расходы"), None)
    if not default_expense:
        max_sort += 1
        default_expense = Category(user_id=user_id, name="Прочие расходы", type="expense", sort_order=max_sort)
        db.add(default_expense)

    default_income = next((cat for cat in user_categories if cat.name == "Прочие доходы"), None)
    if not default_income:
        max_sort += 1
        default_income = Category(user_id=user_id, name="Прочие доходы", type="income", sort_order=max_sort)
        db.add(default_income)

    db.commit()
    user_categories = db.query(Category).filter(Category.user_id == user_id).all()

    added_count = 0
    skipped_count = 0

    for index, row in df.iterrows():
        try:
            date_val = pd.to_datetime(row['Дата'], dayfirst=True).date()
            amount_val = float(row['Сумма'])
            desc_val = str(row['Описание'])
        except (KeyError, ValueError):
            continue

        week_str = date_val.strftime('%Y-%W')

        raw_str = f"{date_val}{amount_val}{desc_val}"
        tx_hash = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

        if db.query(Transaction).filter(Transaction.hash.contains(tx_hash)).first():
            skipped_count += 1
            continue

        abs_amount = abs(amount_val)
        is_expense = amount_val < 0

        assigned_category_id = None
        desc_lower = desc_val.lower()

        for cat in user_categories:
            if cat.name.lower() in desc_lower:
                if (is_expense and cat.type == "expense") or (not is_expense and cat.type == "income"):
                    assigned_category_id = cat.category_id
                    break

        if not assigned_category_id:
            assigned_category_id = default_expense.category_id if is_expense else default_income.category_id

        existing_tx = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.category_id == assigned_category_id,
            Transaction.week == week_str,
            Transaction.is_planned.is_(False)
        ).first()

        if existing_tx:
            existing_tx.amount += abs_amount
            existing_tx.hash += f",{tx_hash}" if existing_tx.hash else tx_hash
        else:
            new_tx = Transaction(
                user_id=user_id,
                account_id=account_id,
                category_id=assigned_category_id,
                amount=abs_amount,
                week=week_str,
                description=f"Сводка за {week_str}",
                is_planned=False,
                hash=tx_hash
            )
            db.add(new_tx)

        account = db.query(Account).filter(Account.account_id == account_id).first()
        if account:
            if is_expense:
                account.balance -= abs_amount
            else:
                account.balance += abs_amount

        added_count += 1

    db.commit()
    return {"message": "Успешно", "added": added_count, "skipped": skipped_count}


@app.get("/export/excel", tags=["Импорт и Экспорт"])
def export_budget_to_excel(user_id: int, start_week: str, end_week: str, db: Session = Depends(get_db)):
    """
    **Экспорт бюджета в XLSX**.

    Генерирует Excel-файл со сводной таблицей (Pivot Table).
    Ряды: Категории, Колонки: Недели. Разделяет суммы на План и Факт.
    Файл сразу отдается на скачивание.
    """
    week_expr = Transaction.week.label('week')
    fact_sum = func.sum(case((Transaction.is_planned.is_(False), Transaction.amount), else_=0)).label('fact_amount')
    plan_sum = func.sum(case((Transaction.is_planned.is_(True), Transaction.amount), else_=0)).label('plan_amount')

    query = (
        db.query(week_expr, Category.name.label('category_name'), fact_sum, plan_sum)
        .join(Category, Transaction.category_id == Category.category_id)
        .filter(
            Transaction.user_id == user_id,
            Transaction.week >= start_week,
            Transaction.week <= end_week
        )
        .group_by(Transaction.week, Category.name).all()
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
        headers={'Content-Disposition': f'attachment; filename="budget_{start_week}_{end_week}.xlsx"'},
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.get("/recurring", response_model=List[schemas.RecurringResponse], tags=["Повторяющиеся транзакции"])
def get_recurring(user_id: int, db: Session = Depends(get_db)):
    """Получить все подписки пользователя"""
    return db.query(RecurringTransaction).filter(RecurringTransaction.user_id == user_id).all()


@app.post("/recurring", response_model=schemas.RecurringResponse, tags=["Повторяющиеся транзакции"])
def create_recurring(recurring: schemas.RecurringCreate, db: Session = Depends(get_db)):
    """
    **Создание еженедельного автоплатежа**.

    Создает шаблон. Деньги сразу не списываются.
    Бэкенд сам будет проверять этот шаблон при каждом запуске приложения
    и генерировать транзакции на нужные недели.
    **end_week** - опционально
    """
    new_rec = RecurringTransaction(**recurring.model_dump())
    new_rec.next_sync_week = new_rec.start_week
    db.add(new_rec)
    db.commit()
    db.refresh(new_rec)
    process_recurring_transactions(db)
    return new_rec


@app.put("/recurring/{recurring_id}", response_model=schemas.RecurringResponse, tags=["Повторяющиеся транзакции"])
def update_recurring(recurring_id: int, rec_update: schemas.RecurringUpdate, db: Session = Depends(get_db)):
    """Изменение автоплатежа"""
    db_rec = db.query(RecurringTransaction).filter(RecurringTransaction.recurring_id == recurring_id).first()
    if not db_rec:
        raise HTTPException(status_code=404, detail="Шаблон не найден")

    update_data = rec_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_rec, key, value)

    db.commit()
    db.refresh(db_rec)

    process_recurring_transactions(db)
    return db_rec


@app.delete("/recurring/{recurring_id}", tags=["Повторяющиеся транзакции"])
def delete_recurring(recurring_id: int, db: Session = Depends(get_db)):
    """Удалить подписку"""
    db_rec = db.query(RecurringTransaction).filter(RecurringTransaction.recurring_id == recurring_id).first()
    if not db_rec:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    db.delete(db_rec)
    db.commit()
    return {"message": "Подписка удалена"}


def process_recurring_transactions(db: Session):
    """
    Проверяет даты и списывает деньги за прошедшие периоды.
    """
    current_week = date.today().strftime('%Y-%W')

    active_subs = db.query(RecurringTransaction).filter(
        RecurringTransaction.next_sync_week <= current_week
    ).all()

    generated_count = 0
    for sub in active_subs:
        while sub.next_sync_week <= current_week:

            if sub.end_week and sub.next_sync_week > sub.end_week:
                db.delete(sub)
                break

            new_tx = Transaction(
                user_id=sub.user_id,
                account_id=sub.account_id,
                category_id=sub.category_id,
                amount=sub.amount,
                week=sub.next_sync_week,
                description="Автоплатеж",
                is_planned=sub.is_planned,
                is_recurring=True
            )
            db.add(new_tx)

            if not sub.is_planned:
                account = db.query(Account).filter(Account.account_id == sub.account_id).first()
                cat = db.query(Category).filter(Category.category_id == sub.category_id).first()
                if account and cat:
                    if cat.type == "expense": account.balance -= sub.amount
                    elif cat.type == "income": account.balance += sub.amount

            sub.next_sync_week = add_one_week(sub.next_sync_week)
            generated_count += 1

    db.commit()
    return generated_count


@app.post("/sandbox/start", tags=["Моделирование"])
def start_sandbox():
    """Активирует режим моделирования: создает точную копию БД"""
    global SANDBOX_MODE
    shutil.copy2(db_path, sandbox_path)
    SANDBOX_MODE = True
    return {"message": "Режим моделирования включен. Теперь вы работаете с копией."}


@app.post("/sandbox/discard", tags=["Моделирование"])
def discard_sandbox():
    """Отменяет все изменения и возвращает к реальной БД"""
    global SANDBOX_MODE
    SANDBOX_MODE = False
    return {"message": "Изменения сброшены. Возврат к основной базе."}


@app.post("/sandbox/apply", tags=["Моделирование"])
def apply_sandbox():
    """Сохраняет смоделированный сценарий в основную бд"""
    global SANDBOX_MODE
    if not SANDBOX_MODE:
        raise HTTPException(status_code=400, detail="Песочница не запущена")

    shutil.copy2(sandbox_path, db_path)
    SANDBOX_MODE = False
    return {"message": "Сценарий успешно применен и сохранен в основную базу!"}


@app.post("/transfer", tags=["Транзакции"])
def create_transfer(transfer: schemas.TransferCreate, db: Session = Depends(get_db)):
    """
    **Перевод между счетами (Погашение кредиток, Копилки)**.

    Списывает деньги с `from_account_id` и зачисляет на `to_account_id`.
    """

    if transfer.from_account_id == transfer.to_account_id:
        raise HTTPException(status_code=400, detail="Нельзя перевести на тот же самый счет")

    from_account = db.query(Account).filter(Account.account_id == transfer.from_account_id).first()
    to_account = db.query(Account).filter(Account.account_id == transfer.to_account_id).first()

    if not from_account or not to_account:
        raise HTTPException(status_code=404, detail="Один из счетов не найден")

    sys_cat = db.query(Category).filter(Category.name == "Переводы").first()
    if not sys_cat:
        max_sort = db.query(func.max(Category.sort_order)).filter(Category.user_id == transfer.user_id).scalar() or 0
        sys_cat = Category(user_id=transfer.user_id, name="Переводы", type="transfer", sort_order=max_sort + 1)
        db.add(sys_cat)
        db.commit()
        db.refresh(sys_cat)

    tx_out = Transaction(
        user_id=transfer.user_id,
        account_id=transfer.from_account_id,
        category_id=sys_cat.category_id,
        amount=transfer.amount,
        week=transfer.week,
        description=transfer.description,
        is_planned=False
    )
    from_account.balance -= transfer.amount

    tx_in = Transaction(
        user_id=transfer.user_id,
        account_id=transfer.to_account_id,
        category_id=sys_cat.category_id,
        amount=transfer.amount,
        week=transfer.week,
        description=transfer.description,
        is_planned=False
    )
    to_account.balance += transfer.amount

    db.add(tx_out)
    db.add(tx_in)
    db.commit()

    return {"message": "Перевод успешно выполнен"}