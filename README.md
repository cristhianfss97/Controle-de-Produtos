# 📦 Controle de Produtos (Web) — Todas as opções

Inclui:
- 🔎 Pesquisa por nome ou SKU (evita cadastro duplicado)
- 🏷️ SKU / Código de barras (opcional, mas único se preenchido)
- 🗂️ Categorias (criar/excluir)
- ⚠️ Alerta de estoque baixo (Qtd ≤ Mín) + filtro
- 📤 Exportar Excel (produtos.xlsx)

## ✅ Rodar no PC (sem Postgres)
1) Abra o terminal na pasta
2) Instale:
   pip install -r requirements.txt
3) Rode:
   python app.py
4) Abra:
   http://127.0.0.1:5000

> Sem DATABASE_URL, ele roda com SQLite local (produtos.db).

## 🐘 Rodar com Postgres (local)
DATABASE_URL exemplo:
  postgresql://usuario:senha@localhost:5432/nome_do_banco

Windows PowerShell:
  $env:DATABASE_URL="postgresql://usuario:senha@localhost:5432/nome_do_banco"
  python app.py

Linux/Mac:
  export DATABASE_URL="postgresql://usuario:senha@localhost:5432/nome_do_banco"
  python app.py

## 🌍 Colocar online com Postgres (Render)
1) Suba a pasta no GitHub
2) No Render: crie um PostgreSQL (New → PostgreSQL)
3) Crie o Web Service (New → Web Service) e conecte o repo
4) Em Environment Variables do Web Service:
   - DATABASE_URL = Internal Database URL do Postgres
   - APP_SECRET_KEY = uma_chave_forte
5) Configure:
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app

URL pública sai automaticamente no Render.

## 🔁 Exportar Excel
Clique em "Exportar Excel" no topo ou acesse:
  /export.xlsx
