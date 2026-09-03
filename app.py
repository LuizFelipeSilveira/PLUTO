import pandas as pd
from sqlalchemy import create_engine, text
import streamlit as st
import os
from dotenv import load_dotenv
import datetime
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="PLUTO", page_icon="🪐", layout="wide")

@st.cache_resource
def init_connection():
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_engine(DATABASE_URL)
    return engine

@st.cache_data(ttl=600)
def load_data():
    engine = init_connection()
    query = "SELECT * FROM transaction ORDER BY date DESC"
    df = pd.read_sql(query, engine)
    df['date'] = pd.to_datetime(df['date'])
    return df

try:
    df_transaction = load_data()
    today = datetime.date.today()
    month_now = today.month
    year_now = today.year

    category_names = {
        1: "Alimentação", 2: "Transporte", 3: "Lazer e Compras", 
        4: "Saúde e Bem-Estar", 5: "Assinaturas", 6: "Contas Residenciais",
        7: "Outros", 8: "Renda", 9:"Investimento"
    }
    
    meses_pt = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"
    }

    df_transaction["date"] = pd.to_datetime(df_transaction["date"])
    df_transaction["day"] = df_transaction["date"].dt.day
    df_transaction["month"] = df_transaction["date"].dt.month
    df_transaction["year"] = df_transaction["date"].dt.year
    
    month_name = meses_pt[month_now]
    df_month = df_transaction[(df_transaction["month"] == month_now) & (df_transaction["year"] == year_now)]

    tab_dashboard, tab_treinamento = st.tabs(["Dashboard", "Treinamento"])

    with tab_dashboard:
        st.header(f"{month_name}", divider=True)

        income = 15000
        df_gastos = df_month[~df_month['category_id'].isin([8, 9])]
        total_spent = df_gastos['value'].sum()

        total_invested = df_month[df_month['category_id'] == 9]['value'].sum()

        balance = income - total_spent

        days_in_month = pd.Period(f'{year_now}-{month_now}').days_in_month
        current_day = today.day if (month_now == today.month and year_now == today.year) else days_in_month
        
        run_rate = (total_spent / current_day) * days_in_month if current_day > 0 else 0
        burn_rate = total_spent / current_day if current_day > 0 else 0

        if not df_gastos.empty:
            biggest_expense_row = df_gastos.loc[df_gastos['value'].idxmax()]
            biggest_name = biggest_expense_row['establishment']
            biggest_val = biggest_expense_row['value']
            biggest_expense_str = f"{biggest_name} (R$ {biggest_val:,.2f})".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            biggest_expense_str = "Nenhuma despesa"

        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            income_str = f"{income:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric(label="RENDA", value=f":green[R$ {income_str}]", border=True, icon=":material/trending_up:")

        with col2:
            total_spent_str = f"{total_spent:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric(label="TOTAL GASTO", value=f":red[R$ {total_spent_str}]", border=True, icon=":material/trending_down:")

        with col3:
            balance_str = f"{balance:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if balance > 0:
                st.metric(label="SALDO", value=f":green[+ {balance_str}]", border=True, icon=":material/payments:")
            else:
                st.metric(label="SALDO", value=f":red[- {balance_str}]", border=True, icon=":material/payments:")

        with col4:
            invested_str = f"{total_invested:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric(label="INVESTIDO NO MÊS", value=f":blue[R$ {invested_str}]", border=True, icon=":material/savings:")

        col4, col5, col6 = st.columns(3)
        
        with col4:
            run_rate_str = f"{run_rate:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric(label="PROJEÇÃO FINAL DO MÊS", value=f"R$ {run_rate_str}", border=True, icon=":material/event:")
            
        with col5:
            burn_rate_str = f"{burn_rate:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric(label="MÉDIA DE GASTO DIÁRIO", value=f"R$ {burn_rate_str}", border=True, icon=":material/today:")
            
        with col6:
            st.metric(label="MAIOR DESPESA", value=biggest_expense_str, border=True, icon=":material/warning:")

        st.markdown("<br>", unsafe_allow_html=True)

        st.subheader("Evolução Diária de Gastos")

        daily_expenses = df_month.groupby("day", as_index=False)["value"].sum()
        all_days = pd.DataFrame({"day": range(1, days_in_month + 1)})
        
        daily_data = pd.merge(all_days, daily_expenses, on="day", how="left").fillna(0)
        daily_data["acumulado"] = daily_data["value"].cumsum()

        if month_now == today.month and year_now == today.year:
            daily_data.loc[daily_data["day"] > today.day, "acumulado"] = None

        fig_timeline = make_subplots(specs=[[{"secondary_y": True}]])

        fig_timeline.add_trace(
            go.Bar(x=daily_data["day"], y=daily_data["value"], name="Gasto Diário", marker_color="#3b82f6"),
            secondary_y=False
        )

        fig_timeline.add_trace(
            go.Scatter(
                x=daily_data["day"], y=daily_data["acumulado"], name="Acumulado", 
                mode="lines+markers", line=dict(color="rgba(239, 68, 68, 0.5)", width=3),
                marker=dict(color="rgba(239, 68, 68, 0.5)")
            ),
            secondary_y=True
        )

        fig_timeline.update_layout(
            xaxis=dict(tickmode='linear', tick0=1, dtick=1, range=[0.5, days_in_month + 0.5]),
            margin=dict(t=20, b=20, l=20, r=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        fig_timeline.update_yaxes(title_text="Gasto Diário (R$)", tickprefix="R$ ", secondary_y=False)
        fig_timeline.update_yaxes(title_text="Acumulado (R$)", tickprefix="R$ ", showgrid=False, secondary_y=True)

        st.plotly_chart(fig_timeline, use_container_width=True)

        categories_expenses = df_month.groupby("category_id", as_index=False)["value"].sum()
        categories_expenses["category_name"] = categories_expenses["category_id"].map(category_names).fillna("Outros")

        st.markdown("<br>", unsafe_allow_html=True)

        col8, col9 = st.columns([1, 2])

        with col8:
            fig_pie = px.pie(
                categories_expenses, values="value", names="category_name", 
                hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie.update_layout(showlegend=True, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col9:
            st.subheader("Gastos por categoria")
            category_data = categories_expenses.groupby("category_name", as_index=False)["value"].sum()
            category_data["income_pct"] = (categories_expenses["value"]/income) * 100
            category_data = category_data.rename(columns={
                "category_name": "Categoria", "value": "Gasto", "income_pct": "Porcentagem da renda"
            })
            category_data["Porcentagem da renda"] = category_data["Porcentagem da renda"].apply(lambda x: f"{x:.2f}%")
            category_data["Gasto"] = category_data["Gasto"].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            st.dataframe(category_data, hide_index=True, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        st.subheader("Comportamento: Média de Gastos por Dia da Semana")
        limit_day = today.day if (month_now == today.month and year_now == today.year) else days_in_month
        
        past_dates = pd.date_range(start=f"{year_now}-{month_now}-01", periods=limit_day)
        past_dates_df = pd.DataFrame({"date": past_dates})
        past_dates_df["weekday"] = past_dates_df["date"].dt.dayofweek

        weekday_counts = past_dates_df.groupby("weekday").size().reset_index(name="counts")
        df_month_copy = df_month.copy()
        df_month_copy["weekday"] = df_month_copy["date"].dt.dayofweek
        weekday_expenses = df_month_copy.groupby("weekday", as_index=False)["value"].sum()

        all_weekdays = pd.DataFrame({"weekday": range(7)})
        weekday_data = pd.merge(all_weekdays, weekday_counts, on="weekday", how="left").fillna({"counts": 0})
        weekday_data = pd.merge(weekday_data, weekday_expenses, on="weekday", how="left").fillna({"value": 0})
        
        def safe_divide(val, count):
            return val / count if count > 0 else 0
        
        weekday_data["average"] = weekday_data.apply(lambda row: safe_divide(row["value"], row["counts"]), axis=1)
        weekday_map = {
            0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
            3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
        }
        weekday_data["Dia da Semana"] = weekday_data["weekday"].map(weekday_map)
        
        weekday_data["text_label"] = weekday_data["average"].apply(
            lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        fig_weekday = px.bar(
            weekday_data, 
            x="Dia da Semana", 
            y="average",
            text="text_label",
            color_discrete_sequence=["#8b5cf6"]
        )
        fig_weekday.update_traces(
            textposition='outside'
        )
        fig_weekday.update_layout(
            xaxis_title="",
            yaxis_title="Média de Gasto (R$)",
            yaxis=dict(tickprefix="R$ ", showgrid=True),
            margin=dict(t=20, b=20, l=20, r=20),
            hovermode="x unified"
        )
        st.plotly_chart(fig_weekday, use_container_width=True)

        with st.expander("Visualizar Histórico Detalhado (Dados Brutos)"):
            df_show = df_month[["date", "establishment", "value", "category_id"]].copy()
            df_show["date"] = df_show["date"].dt.strftime("%d/%m/%Y")
            st.dataframe(df_show, hide_index=True, use_container_width=True)

    with tab_treinamento:
        st.header("Categorizar Novas Despesas")

        df_pendentes = df_transaction[df_transaction['category_id'].isna() | (df_transaction['category_id'] == 0)]

        if df_pendentes.empty:
            st.success("Não há despesas pendentes de categorização.")
        else:
            estabelecimentos_pendentes = df_pendentes['establishment'].unique()

            with st.form("form_categorizacao"):
                escolhas = {}
                
                for est in estabelecimentos_pendentes:
                    escolhas[est] = st.selectbox(
                        f"{est}", 
                        options=["Selecione..."] + list(category_names.values()),
                        key=f"sel_{est}"
                    )
                
                submit = st.form_submit_button("Salvar Categorias", type="primary")

                if submit:
                    nome_para_id = {v: k for k, v in category_names.items()}
                    engine = init_connection()
                    
                    with engine.begin() as conn:
                        sucesso = 0

                        sql_recount = text("""
                            SELECT category_id, COUNT(*) as freq
                            FROM transaction
                            WHERE establishment = :est AND category_id IS NOT NULL
                            GROUP BY category_id
                            ORDER BY freq DESC, category_id ASC
                            LIMIT 1
                        """)

                        for est, cat_nome in escolhas.items():
                            if cat_nome != "Selecione...":
                                cat_id = nome_para_id[cat_nome]
                                
                                df_pendentes_est = df_pendentes[df_pendentes['establishment'] == est]
                                
                                for _, row in df_pendentes_est.iterrows():
                                    conn.execute(text("""
                                        UPDATE transaction SET category_id = :cat_id WHERE id = :t_id
                                    """), {"cat_id": cat_id, "t_id": row['id']})

                                resultado = conn.execute(sql_recount, {"est": est}).first()
                                cat_mais_frequente = resultado.category_id if resultado else cat_id

                                conn.execute(text("""
                                    INSERT INTO establishment_category_map (establishment, category_id)
                                    VALUES (:est, :cat_id)
                                    ON CONFLICT (establishment) DO UPDATE SET category_id = :cat_id
                                """), {"est": est, "cat_id": cat_mais_frequente})

                                sucesso += 1
                        
                    if sucesso > 0:
                        st.success(f"{sucesso} estabelecimentos categorizados com sucesso!")
                        st.cache_data.clear()
                        st.rerun()

except Exception as e:
    st.error(f"Erro ao conectar com o banco de dados: {e}")
    st.info("Verifique se a DATABASE_URL foi inserida corretamente no código.")