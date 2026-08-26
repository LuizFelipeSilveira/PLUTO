import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, String, Integer, Float, DateTime, Column, ForeignKey
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship
from datetime import datetime, timezone

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("Variável não encontrada.")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_current_time_utc():
    return datetime.now(timezone.utc)

class Transactions(Base):
    __tablename__ = "transaction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    value = Column(Float, nullable=False)
    establishment = Column(String, nullable=False)
    date = Column(DateTime(timezone=True), default=get_current_time_utc)
    category_id = Column(Integer, ForeignKey("category.id"), nullable=True)
    category = relationship("Category", back_populates="transaction")
    user = relationship("User", back_populates="transaction")

class Category(Base):
    __tablename__ = "category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    transactions = relationship("Transaction", back_populates="category")

class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    transactions = relationship("Transaction", back_populates="user")

if __name__ == '__main__':
    try:
        Base.metadata.create_all(engine)
        print("Bancos criados com sucesso ou já existentes.")
    except Exception as e:
        print(f'Erro: {e}')