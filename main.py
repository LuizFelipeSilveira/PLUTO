from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from io import StringIO
import csv
from datetime import datetime

from database import SessionLocal, Transactions

app = FastAPI(title="PLUTO")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CSVPayload(BaseModel):
    csv_data: str
    user_id: int

class TransactionIOS(BaseModel):
    value: float
    establishment: Optional[str] = "Não informado"
    date: Optional[str] = None
    category_id: Optional[int] = None 
    user_id: int

CATEGORY_RULES = {
    1 : ["ifood", "padaria", "mercado", "prezunic", "carrefour",
          "assai", "assaí", "restaurante", "pizzaria", "churrascaria", 
          "casafruti", "hortifruti", "petisqueira", "boteco"],
    2 : ["uber", "99app", "posto", "autoposto", "ipiranga", 
        "petrobras", "shell", "metrô", "metrorio", "CCR",
        "99", "estacionamento", "estapar", "netpark"],
    3 : ["cinema", "cinemas", "kinoplex", "ingresso", "Shopee"],
    4 : ["principia", "drogaria", "drogarias", "venancio", "pacheco",
         "raia", "ilha animal", "versatil", "wellhub"],
    5 : ["spotify", "amazon prime", "apple", "microsoft", "dazn"],
    6 : ["claro", "light", "naturgy", "aguas do rio", "mobilize"]
}


def expenses_classification(establishment: str) -> Optional[int]:
    if not establishment:
        return None

    lower_name = establishment.lower()

    for category_id, key_words in CATEGORY_RULES.items():
        for item in key_words:
            if item == "":
                continue
            if item in lower_name:
                return category_id
    return None

@app.post("/webhook/csv")
def process_nubank_csv(payload:CSVPayload, db: Session = Depends(get_db)):
    f = StringIO(payload.csv_data)
    reader = csv.DictReader(f, delimiter=",")

    inserted_registries = 0
    uninserted_registries = 0

    for row in reader:
        date_str = row.get("date", "").strip()
        title = row.get("title", "").strip()
        value_str = row.get("amount", "").strip()

        if not date_str or not title or not value_str:
            continue

        if "pagamento recebido" in title.lower():
            continue

        clean_value = value_str.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            value_val = float(clean_value)
        except ValueError:
            continue

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        existing_transaction = db.query(Transactions).filter(Transactions.date == date_obj,
                                                             Transactions.establishment == title,
                                                             Transactions.value == value_val,
                                                             Transactions.user_id, payload.user_id).first()

        if existing_transaction:
            uninserted_registries += 1
            continue

        new_transaction = Transactions(user_id=payload.user_id,
                                       value=value_val,
                                       establishment=title,
                                       date=date_obj)
        db.add(new_transaction)
        inserted_registries += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}

    return {
        "status": "sucess",
        "inserted": inserted_registries,
        "skipped": uninserted_registries
    }

@app.post("/webhook/iphone")
def new_transaction(item:TransactionIOS, db: Session = Depends(get_db)):

    final_category = item.category_id

    if final_category is None and item.establishment != "Não informado":
        final_category = expenses_classification(item.establishment)

    new_transaction = Transactions(
        value = item.value,
        establishment = item.establishment,
        category_id = final_category,
        user_id = item.user_id 
    )

    db.add(new_transaction)
    try:
        db.commit()
        db.refresh(new_transaction)
    except Exception as e:
        db.rollback()
        return {"status": f"Erro interno no bando de dados. Detalhes: {e}"}
    
    return {
        "status": "Sucess",
        "message": "Transação registrada com sucesso.",
        "id_banco": new_transaction.id,
        "categoria_vinculada": new_transaction.category_id,
        "usuario_id" : new_transaction.user_id
    }
