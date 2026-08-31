import pandas as pd
from sqlalchemy import create_engine
import streamlit as st
import os
from dotenv import load_dotenv
import datetime
import plotly.express as px

st.set_page_config(page_title="PLUTO",
                   page_icon="🪐",
                   layout="wide")

@st.cache_resource
def init_connection():

    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_engine(DATABASE_URL)
    return engine

@st.cache_data(ttl=600)
def load_data():
    engine = init_connection()

    query = """
        SELECT *
        FROM transaction
        ORDER BY date DESC
        """

    df = pd.read_sql(query, engine)

    df['date'] = pd.to_datetime(df['date'])
    return df

try:
    df_transaction = load_data()
    st.write("Colunas que vieram do banco:", df_transaction.columns)

    today = datetime.date.today()
    month_num = today.month

    df_transaction["date"] = pd.to_datetime(df_transaction["date"])
    df_transaction["month"] = df_transaction["date"].dt.month
    df_transaction["year"] = df_transaction["date"].dt.year
    
    meses_pt = {1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
                5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
                9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"}
    month_name = meses_pt[month_num]

    st.header(f"{month_name}", divider=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        income = 15000 # mudar quando colocar opção de inputar o income
        income_str = f"{income:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        st.metric(label= f"RENDA", value=f":green[R$ {income_str}]", border=True, icon=":material/trending_up:")


    with col2:
        total_spent = df_transaction['value'].sum()
        total_spent_str = f"{total_spent:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        st.metric(label=f"TOTAL GASTO", value=f":red[R$ {total_spent_str}]", border=True, icon=":material/trending_down:")

    with col3:
        balance = income - total_spent
        balance_str = f"{balance:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if balance > 0:
            st.metric(label= f"SALDO", value= f":green[+ {balance_str}]", border=True, icon=":material/payments:")
        else:
            st.metric(label= f"SALDO", value= f":red[- {balance_str}]", border=True, icon=":material/payments:")

    month_now = today.month
    year_now = today.year

    df_now = df_transaction[((df_transaction["month"] == month_now) & (df_transaction["year"] == year_now))]
    categories_expenses = df_now.groupby("category_id",as_index=False)["value"].sum()

    category_names = {1: "Alimentação",
                      2: "Transporte",
                      3: "Lazer",
                      4: "Saúde",
                      5: "Assinaturas",
                      6: "Contas Fixas"}

    categories_expenses["category_name"] = categories_expenses["category_id"].map(category_names).fillna("Outros")

    fig = px.pie(
        categories_expenses, 
        values="value", 
        names="category_name", 
        color_discrete_sequence=px.colors.qualitative.Pastel  
    )

    fig.update_layout(
        showlegend=True,
        margin=dict(t=20, b=20, l=20, r=20)
    )

    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"Erro ao conectar com o banco de dados: {e}")
    st.info("Verifique se a DATABASE_URL foi inserida corretamente no código.")