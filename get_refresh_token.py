"""
Rode este script UMA VEZ, na sua máquina local, para obter o refresh_token
que o cron vai usar depois para se autenticar sozinho no Microsoft Graph.

Antes de rodar:
1. Preencha CLIENT_ID e CLIENT_SECRET com os valores do App Registration
   criado no Azure Portal (passos 1 e 2 do guia).
2. Rode: python get_refresh_token.py
3. O navegador vai abrir e pedir login + autorização.
4. Depois de autorizar, o navegador tentará carregar
   http://localhost:8080/callback?code=... e provavelmente vai dar erro de
   conexão (isso é esperado — não existe nada rodando nessa porta). Não feche
   a aba: copie a URL COMPLETA que aparece na barra de endereço.
5. Cole essa URL completa quando o script pedir.
6. O script imprime o refresh_token — copie e guarde num lugar seguro
   (você vai colar como variável de ambiente no Vercel no próximo passo).

Depois de concluir, pode apagar este arquivo e, se quiser, revogar o
client secret usado aqui e gerar um novo para o ambiente de produção.
"""

import requests
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "offline_access Mail.Read Mail.ReadWrite"

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("MS_CLIENT_ID ou MS_CLIENT_SECRET não encontrados no .env")
        return

    auth_url = f"{AUTH_URL}?" + urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPES,
    })

    print("Abrindo o navegador para login da Microsoft...")
    print("Se não abrir sozinho, acesse manualmente:\n")
    print(auth_url, "\n")
    webbrowser.open(auth_url)

    redirected_url = input(
        "Depois de autorizar, cole aqui a URL completa para onde você foi "
        "redirecionado (começa com http://localhost:8080/callback?...):\n> "
    ).strip()

    parsed = urlparse(redirected_url)
    code = parse_qs(parsed.query).get("code", [None])[0]

    if not code:
        print("Não encontrei o parâmetro 'code' nessa URL. Confira e tente de novo.")
        return

    token_resp = requests.post(TOKEN_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })

    if token_resp.status_code != 200:
        print("Erro ao trocar o código pelo token:")
        print(token_resp.status_code, token_resp.text)
        return

    tokens = token_resp.json()
    print("\n✅ Sucesso! Guarde este refresh_token com segurança:\n")
    print(tokens["refresh_token"])
    print(
        "\nEsse é o valor que vai virar a variável de ambiente "
        "MS_REFRESH_TOKEN no Vercel."
    )


if __name__ == "__main__":
    main()
