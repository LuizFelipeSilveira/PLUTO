from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from io import StringIO
import csv
from datetime import datetime
from database import EstablishmentCategoryMap
from database import SessionLocal, Transactions
import os
import base64
import requests

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

def get_learned_category(establishment: str, db: Session) -> Optional[int]:
    if not establishment or establishment == "Não informado":
        return None

    mapping = db.query(EstablishmentCategoryMap.category_id)\
                .filter(EstablishmentCategoryMap.establishment == establishment)\
                .first()

    return mapping.category_id if mapping else None


@app.post("/webhook/csv")
def process_nubank_csv(payload: CSVPayload, db: Session = Depends(get_db)):
    csv_text = payload.csv_data.lstrip('\ufeff')
    f = StringIO(csv_text)
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
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        existing_transaction = db.query(Transactions).filter(
            Transactions.date == date_str,
            Transactions.establishment == title,
            Transactions.value == value_val,
            Transactions.user_id == payload.user_id
        ).first()

        if existing_transaction:
            uninserted_registries += 1
            continue

        final_category = get_learned_category(title, db)

        new_transaction = Transactions(
            user_id=payload.user_id,
            value=value_val,
            establishment=title,
            date=date_str,
            category_id=final_category
        )
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
def new_transaction(item: TransactionIOS, db: Session = Depends(get_db)):

    final_category = item.category_id

    if final_category is None and item.establishment != "Não informado":
        final_category = get_learned_category(item.establishment, db)

    new_transaction = Transactions(
        value=item.value,
        establishment=item.establishment,
        date=item.date, 
        category_id=final_category,
        user_id=item.user_id 
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
        "usuario_id": new_transaction.user_id
    }

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_REFRESH_TOKEN = os.getenv("MS_REFRESH_TOKEN")
PLUTO_USER_ID = int(os.getenv("PLUTO_USER_ID", "1"))
CRON_SECRET = os.getenv("CRON_SECRET")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
CSV_WEBHOOK_URL = "https://pluto-nine-lime.vercel.app/webhook/csv"


def get_access_token() -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": MS_CLIENT_ID,
        "client_secret": MS_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": MS_REFRESH_TOKEN,
        "scope": "offline_access Mail.Read Mail.ReadWrite",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def find_extrato_email(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "$filter": "isRead eq false",
        "$orderby": "receivedDateTime desc",
        "$top": "10",
        "$select": "id,subject,hasAttachments",
    }
    resp = requests.get(f"{GRAPH_BASE}/me/mailFolders/inbox/messages", headers=headers, params=params)
    resp.raise_for_status()
    for msg in resp.json().get("value", []):
        if msg.get("hasAttachments") and "extrato" in msg.get("subject", "").lower():
            return msg
    return None


def get_csv_attachment(token: str, message_id: str):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{GRAPH_BASE}/me/messages/{message_id}/attachments", headers=headers)
    resp.raise_for_status()
    for att in resp.json().get("value", []):
        if att.get("name", "").lower().endswith(".csv"):
            content = base64.b64decode(att["contentBytes"])
            return content.decode("utf-8-sig")
    return None


def mark_as_read(token: str, message_id: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    requests.patch(f"{GRAPH_BASE}/me/messages/{message_id}", headers=headers, json={"isRead": True})


@app.get("/cron/check-extrato")
def check_extrato(authorization: str = Header(default="")):
    if not CRON_SECRET or authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Não autorizado")

    token = get_access_token()
    email = find_extrato_email(token)
    if not email:
        return {"status": "sem extrato novo"}

    csv_text = get_csv_attachment(token, email["id"])
    if not csv_text:
        return {"status": "e-mail encontrado mas sem CSV anexado"}

    resp = requests.post(CSV_WEBHOOK_URL, json={"csv_data": csv_text, "user_id": PLUTO_USER_ID})

    if resp.status_code == 200:
        mark_as_read(token, email["id"])
        return {"status": "processado", "resultado": resp.json()}

    return {"status": "erro ao enviar csv", "detalhe": resp.text}