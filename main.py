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
import hashlib
from collections import defaultdict
import re
from database import User

app = FastAPI(title="PLUTO")

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_REFRESH_TOKEN = os.getenv("MS_REFRESH_TOKEN")
CRON_SECRET = os.getenv("CRON_SECRET")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
CSV_WEBHOOK_URL = "https://pluto-nine-lime.vercel.app/webhook/csv"
FATURA_WEBHOOK_URL = "https://pluto-nine-lime.vercel.app/webhook/fatura"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CSVPayload(BaseModel):
    csv_data: str
    recipient: str


USER_EMAIL_MAP = {}
for par in os.getenv("USER_EMAIL_MAP", "").split(","):
    if ":" in par:
        email, uid = par.rsplit(":", 1)
        USER_EMAIL_MAP[email.strip().lower()] = int(uid.strip())

PARCELA_RE = re.compile(r"\s*-\s*Parcela\s+(\d+)/(\d+)\s*$", re.IGNORECASE)


def split_parcela(title: str):
    m = PARCELA_RE.search(title)
    if m:
        return PARCELA_RE.sub("", title).strip(), int(m.group(1)), int(m.group(2))
    return title, None, None

def resolve_user_id(recipient: str) -> Optional[int]:
    return USER_EMAIL_MAP.get((recipient or "").strip().lower())

def get_learned_category(establishment: str, db: Session) -> Optional[int]:
    if not establishment or establishment == "Não informado":
        return None

    mapping = db.query(EstablishmentCategoryMap.category_id)\
                .filter(EstablishmentCategoryMap.establishment == establishment)\
                .first()

    return mapping.category_id if mapping else None


def classify_income(descricao: str, user_id: int, db: Session) -> int:
    texto = descricao.lower()

    eu = db.query(User).filter(User.id == user_id).first()

    if eu and eu.salary_bank and eu.full_name:
        if eu.salary_bank.lower() in texto and eu.full_name.lower() in texto:
            return 8

    if "resgate" in texto:
        return 10

    outros = db.query(User).filter(User.id != user_id).all()
    for outro in outros:
        if outro.full_name and outro.full_name.lower() in texto:
            return 10

    if eu and eu.full_name and eu.full_name.lower() in texto:
        return 10

    return 8

IGNORED_TRANSFER_NAMES = [
    n.strip().lower() for n in os.getenv("IGNORED_TRANSFER_NAMES", "").split(",") if n.strip()
]

def should_ignore_transaction(descricao: str) -> bool:
    texto = descricao.lower()
    if texto.strip() == "pagamento de fatura":
        return True
    return False


def extract_establishment(descricao: str) -> str:
    partes = [p.strip() for p in descricao.split(" - ")]
    texto = descricao.lower()

    if "transferência enviada pelo pix" in texto or "transferência recebida pelo pix" in texto:
        if len(partes) >= 2:
            return partes[1]
    elif "pagamento de boleto efetuado" in texto:
        if len(partes) >= 2:
            return partes[1]
    elif "compra no débito" in texto:
        if len(partes) >= 2:
            return partes[1]

    return descricao.strip()

def parse_valor_br(valor: str) -> Optional[float]:
    limpo = valor.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


@app.post("/webhook/fatura")
def process_nubank_fatura(payload: CSVPayload, db: Session = Depends(get_db)):
    user_id = resolve_user_id(payload.recipient)
    if user_id is None:
        raise HTTPException(status_code=400, detail=f"Destinatário não mapeado: {payload.recipient}")

    csv_text = payload.csv_data.lstrip('\ufeff')
    reader = csv.DictReader(StringIO(csv_text))

    inserted = 0
    skipped = 0
    ignored = 0
    ocorrencias = defaultdict(int)

    for row in reader:
        date_str = (row.get("date") or "").strip()
        title = (row.get("title") or "").strip()
        amount_str = (row.get("amount") or "").strip()

        if not date_str or not title or not amount_str:
            continue

        raw_value = parse_valor_br(amount_str)
        if raw_value is None:
            continue

        # valor negativo na fatura = pagamento da própria fatura
        if raw_value <= 0:
            ignored += 1
            continue

        if should_ignore_transaction(title):
            ignored += 1
            continue

        try:
            date_val = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        chave = f"{date_str}|{title}|{amount_str}"
        ocorrencias[chave] += 1
        base = f"fatura|{user_id}|{chave}|{ocorrencias[chave]}"
        external_id = hashlib.sha256(base.encode()).hexdigest()[:32]

        if db.query(Transactions).filter(Transactions.external_id == external_id).first():
            skipped += 1
            continue

        establishment, parcela_atual, parcela_total = split_parcela(title)

        db.add(Transactions(
            user_id=user_id,
            value=raw_value,
            establishment=establishment,
            date=date_val,
            category_id=get_learned_category(establishment, db),
            external_id=external_id,
            installment_current=parcela_atual,
            installment_total=parcela_total,
        ))
        inserted += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}

    return {"status": "sucess", "inserted": inserted, "skipped": skipped, "ignored": ignored}


def find_all_documents(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "$filter": "isRead eq false",
        "$orderby": "receivedDateTime desc",
        "$top": "25",
        "$select": "id,subject,hasAttachments,toRecipients",
    }
    resp = requests.get(f"{GRAPH_BASE}/me/mailFolders/inbox/messages", headers=headers, params=params)
    resp.raise_for_status()

    encontrados = []
    for msg in resp.json().get("value", []):
        if not msg.get("hasAttachments"):
            continue
        assunto = (msg.get("subject") or "").lower()
        if "fatura" in assunto:
            tipo = "fatura"
        elif "extrato" in assunto:
            tipo = "extrato"
        else:
            continue
        destinatarios = [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])]
        encontrados.append({
            "id": msg["id"],
            "tipo": tipo,
            "recipient": destinatarios[0] if destinatarios else "",
        })
    return encontrados


@app.get("/cron/check-extrato")
def check_extrato(authorization: str = Header(default="")):
    if not CRON_SECRET or authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Não autorizado")

    token = get_access_token()
    documentos = find_all_documents(token)
    if not documentos:
        return {"status": "nenhum documento novo"}

    resultados = []
    for doc in documentos:
        if resolve_user_id(doc["recipient"]) is None:
            resultados.append({"tipo": doc["tipo"], "status": "destinatário não mapeado", "recipient": doc["recipient"]})
            continue

        csv_text = get_csv_attachment(token, doc["id"])
        if not csv_text:
            resultados.append({"tipo": doc["tipo"], "status": "sem CSV anexado"})
            continue

        url = CSV_WEBHOOK_URL if doc["tipo"] == "extrato" else FATURA_WEBHOOK_URL
        resp = requests.post(url, json={"csv_data": csv_text, "recipient": doc["recipient"]})

        if resp.status_code == 200:
            mark_as_read(token, doc["id"])
            resultados.append({"tipo": doc["tipo"], "status": "processado", "resultado": resp.json()})
        else:
            resultados.append({"tipo": doc["tipo"], "status": "erro", "detalhe": resp.text})

    return {"status": "concluído", "documentos": resultados}

@app.post("/webhook/csv")
def process_nubank_csv(payload: CSVPayload, db: Session = Depends(get_db)):

    user_id = resolve_user_id(payload.recipient)
    if user_id is None:
        raise HTTPException(status_code=400, detail=f"Destinatário não mapeado: {payload.recipient}")

    csv_text = payload.csv_data.lstrip('\ufeff')

    sample = "\n".join(csv_text.splitlines()[:5])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(StringIO(csv_text), dialect=dialect)

    inserted_registries = 0
    uninserted_registries = 0
    ignored_registries = 0

    for row in reader:
        date_str = (row.get("Data") or "").strip()
        value_str = (row.get("Valor") or "").strip()
        identifier = (row.get("Identificador") or "").strip()
        descricao = (row.get("Descrição") or "").strip()

        if should_ignore_transaction(descricao):
            ignored_registries += 1
            continue

        if not date_str or not value_str or not identifier:
            continue

        try:
            raw_value = float(value_str)
        except ValueError:
            continue

        value_val = abs(raw_value)
        is_income = raw_value > 0

        try:
            date_val = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue

        existing_transaction = db.query(Transactions).filter(
            Transactions.external_id == identifier
        ).first()

        if existing_transaction:
            uninserted_registries += 1
            continue

        establishment = extract_establishment(descricao)

        if is_income:
            final_category = classify_income(descricao, user_id, db)
        else:
            final_category = get_learned_category(establishment, db)

        new_transaction = Transactions(
            user_id=user_id,
            value=value_val,
            establishment=establishment,
            date=date_val,
            category_id=final_category,
            external_id=identifier,
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
        "skipped": uninserted_registries,
        "ignored": ignored_registries,
    }


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


