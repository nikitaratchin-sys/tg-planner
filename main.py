import datetime
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, relationship, declarative_base

# --- CONFIG ---
# Если переменная DATABASE_URL есть (в облаке), берем её. Если нет — создаем локальный файл.
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./tasks.db"

RESET_PASSWORD = "1234"

# --- DB SETUP ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    tasks = relationship("Task", back_populates="category", cascade="all, delete")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    date = Column(Date, default=datetime.date.today)
    status = Column(String, default="pending") 
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="tasks")

Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def update_expired_tasks(db: Session):
    today = datetime.date.today()
    expired_tasks = db.query(Task).filter(Task.date < today, Task.status == "pending").all()
    for task in expired_tasks: task.status = "expired"
    if expired_tasks: db.commit()

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    update_expired_tasks(db)
    today = datetime.date.today()
    tasks = db.query(Task).filter(Task.date == today, Task.status == "pending").all()
    categories = db.query(Category).all()
    
    if not categories:
        db.add(Category(name="Общее"))
        db.commit()
        categories = db.query(Category).all()

    return templates.TemplateResponse("index.html", {
        "request": request, "tasks": tasks, "categories": categories, "today": today
    })

@app.post("/add")
async def add_task(title: str = Form(...), category_id: int = Form(...), db: Session = Depends(get_db)):
    db.add(Task(title=title, category_id=category_id, date=datetime.date.today()))
    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/complete/{task_id}")
async def complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if task and task.date >= datetime.date.today():
        task.status = "completed"
        db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/category/add")
async def add_category(name: str = Form(...), db: Session = Depends(get_db)):
    if not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name))
        db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/category/delete/{cat_id}")
async def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if cat:
        db.delete(cat)
        db.commit()
    return RedirectResponse(url="/", status_code=303)

# --- НОВАЯ СТАТИСТИКА И НАСТРОЙКИ ---

@app.get("/stats", response_class=HTMLResponse)
async def stats(
    request: Request, 
    period: str = "all",      # 'week', 'month', 'all'
    cat_filter: str = "all",  # ID категории или 'all'
    db: Session = Depends(get_db)
):
    update_expired_tasks(db)
    
    # Базовый запрос: берем только завершенные или сгоревшие (активные в статистику не идут)
    base_query = db.query(Task).filter(Task.status.in_(["completed", "expired"]))

    # 1. Фильтр по времени
    today = datetime.date.today()
    if period == "week":
        start_date = today - timedelta(days=7)
        base_query = base_query.filter(Task.date >= start_date)
    elif period == "month":
        start_date = today - timedelta(days=30)
        base_query = base_query.filter(Task.date >= start_date)

    # 2. Фильтр по категории
    selected_cat_name = "Все блоки"
    if cat_filter != "all":
        base_query = base_query.filter(Task.category_id == int(cat_filter))
        cat_obj = db.query(Category).filter(Category.id == int(cat_filter)).first()
        if cat_obj: selected_cat_name = cat_obj.name

    # Выполняем запрос
    tasks = base_query.all()
    
    # Считаем метрики
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == "completed")
    expired = sum(1 for t in tasks if t.status == "expired")
    
    efficiency = int((completed / total) * 100) if total > 0 else 0

    # Для выпадающего списка
    all_categories = db.query(Category).all()

    return templates.TemplateResponse("stats.html", {
        "request": request,
        "total": total,
        "completed": completed,
        "expired": expired,
        "efficiency": efficiency,
        "period": period,
        "cat_filter": cat_filter,
        "categories": all_categories,
        "selected_cat_name": selected_cat_name
    })

@app.post("/reset-data")
async def reset_data(password: str = Form(...), db: Session = Depends(get_db)):
    if password == RESET_PASSWORD:
        # Удаляем все задачи, но оставляем категории
        db.query(Task).delete()
        db.commit()
        return RedirectResponse(url="/stats?reset=success", status_code=303)
    else:
        return RedirectResponse(url="/stats?reset=error", status_code=303)