# Controle de Produtos (Web) — Bonito + Pesquisa + Categorias + Alerta Estoque + Exportar Excel
# Postgres via DATABASE_URL (com fallback SQLite local)
# Flask 3.1.x compatível
#
# Rodar local:
#   pip install -r requirements.txt
#   python app.py
#
# Deploy (Render/Railway):
#   Start command: gunicorn app:app
#   Configure DATABASE_URL (Postgres) + APP_SECRET_KEY

from __future__ import annotations

import os
import io
from typing import Optional, List

from flask import (
    Flask,
    flash,
    redirect,
    render_template_string,
    request,
    url_for,
    send_file,
)

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    create_engine,
    select,
    text,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, Session

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


# ---------------- App/DB ----------------

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-secret-key-change-me")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Render às vezes usa postgres://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    ENGINE = create_engine(DATABASE_URL, pool_pre_ping=True)
    USING_POSTGRES = True
else:
    ENGINE = create_engine("sqlite:///produtos.db", future=True)
    USING_POSTGRES = False

Base = declarative_base()


class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(120), nullable=False, unique=True)

    produtos = relationship("Produto", back_populates="categoria")

    def __repr__(self) -> str:
        return f"Categoria(id={self.id}, nome={self.nome!r})"


class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(255), nullable=False)
    sku = Column(String(80), nullable=True, unique=True)  # código de barras / SKU (opcional)
    preco = Column(Numeric(12, 2), nullable=False)
    quantidade = Column(Integer, nullable=False)
    estoque_minimo = Column(Integer, nullable=False, default=0)

    categoria_id = Column(Integer, ForeignKey("categorias.id", ondelete="SET NULL"), nullable=True)
    categoria = relationship("Categoria", back_populates="produtos")

    def __repr__(self) -> str:
        return f"Produto(id={self.id}, nome={self.nome!r})"


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    with ENGINE.begin() as conn:
        # índices úteis (se suportado)
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_produtos_nome ON produtos (nome)"))
        except Exception:
            pass
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_produtos_qtd ON produtos (quantidade)"))
        except Exception:
            pass

    # Categoria padrão (para ajudar no primeiro uso)
    with Session(ENGINE) as s:
        any_cat = s.execute(select(Categoria).limit(1)).scalar_one_or_none()
        if not any_cat:
            s.add(Categoria(nome="Geral"))
            s.commit()


init_db()


# ---------------- Utilidades ----------------

def parse_float(s: str) -> Optional[float]:
    try:
        v = float((s or "").replace(",", "."))
        return v if v >= 0 else None
    except Exception:
        return None

def parse_int(s: str) -> Optional[int]:
    try:
        v = int(s)
        return v if v >= 0 else None
    except Exception:
        return None

def clean_name(s: str) -> str:
    return " ".join((s or "").strip().split())

def clean_sku(s: str) -> str:
    return (s or "").strip()

def get_categories(session: Session) -> List[Categoria]:
    return session.execute(select(Categoria).order_by(func.lower(Categoria.nome))).scalars().all()


# ---------------- UI (templates embutidos) ----------------

BASE_HTML = """
<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "Controle de Produtos" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { background: radial-gradient(1200px 800px at 20% -10%, #e9f2ff 0%, transparent 55%),
                       radial-gradient(1200px 800px at 95% 0%, #f4e9ff 0%, transparent 60%),
                       #f7f7fb; }
      .card { border: 0; box-shadow: 0 10px 30px rgba(0,0,0,.08); border-radius: 18px; }
      .brand { letter-spacing: .2px; }
      .table td, .table th { vertical-align: middle; }
      .pill { background: rgba(13,110,253,.12); color:#0d6efd; border-radius: 999px; padding:.3rem .6rem; font-weight: 800; }
      .pill-warn { background: rgba(255,193,7,.20); color:#8a6d00; }
      .btn { border-radius: 12px; }
      .form-control, .form-select, .input-group-text { border-radius: 12px; }
      .muted { color: rgba(0,0,0,.55); }
      .hint { background: rgba(25,135,84,.10); color:#198754; border-radius: 12px; padding:.35rem .6rem; font-weight: 600; }
      .badge-soft { background: rgba(13,110,253,.10); color:#0d6efd; border-radius:999px; padding:.25rem .55rem; }
      .mono { font-variant-numeric: tabular-nums; }
      .small2 { font-size: .92rem; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg bg-white border-bottom sticky-top">
      <div class="container py-2">
        <a class="navbar-brand fw-semibold brand" href="{{ url_for('home') }}">📦 Controle de Produtos</a>
        <div class="d-flex gap-2 align-items-center flex-wrap justify-content-end">
          <span class="badge-soft small">{{ 'Postgres' if using_postgres else 'SQLite (local)' }}</span>
          <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('export_excel') }}">Exportar Excel</a>
          <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#catsModal">Categorias</button>
          <a class="btn btn-sm btn-primary" href="{{ url_for('home') }}#novo">+ Novo</a>
        </div>
      </div>
    </nav>

    <main class="container py-4">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
              {{ message }}
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}

      {{ body|safe }}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

HOME_BODY = """
<div class="row g-3">
  <div class="col-12">
    <div class="card">
      <div class="card-body">
        <div class="d-flex flex-wrap gap-3 align-items-center justify-content-between">
          <div>
            <h1 class="h4 mb-1">Produtos</h1>
            <div class="muted small">Pesquise antes de cadastrar e evite duplicidade (nome ou SKU).</div>
          </div>

          <form class="d-flex gap-2 flex-wrap" method="get" action="{{ url_for('home') }}">
            <input class="form-control" style="min-width:220px" name="q" placeholder="Pesquisar por nome ou SKU..." value="{{ q }}" />
            <select class="form-select" name="cat" style="min-width:200px">
              <option value="">Todas as categorias</option>
              {% for c in categorias %}
                <option value="{{ c.id }}" {% if cat_id and c.id==cat_id %}selected{% endif %}>{{ c.nome }}</option>
              {% endfor %}
            </select>
            <div class="form-check align-self-center">
              <input class="form-check-input" type="checkbox" name="low" value="1" id="low" {% if low_only %}checked{% endif %}>
              <label class="form-check-label small2" for="low">Somente estoque baixo</label>
            </div>
            <button class="btn btn-primary" type="submit">Pesquisar</button>
            <a class="btn btn-outline-secondary" href="{{ url_for('home') }}">Limpar</a>
          </form>
        </div>
      </div>

      <div class="card-body pt-0" id="novo">
        <div class="border rounded-4 p-3 bg-white">
          <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
            <div class="fw-semibold">Adicionar produto</div>
            <div class="d-flex flex-wrap gap-2 align-items-center">
              <span class="hint small">Dica: pesquise antes 😉</span>
              <span class="muted small">Preço aceita vírgula (10,50).</span>
            </div>
          </div>

          <form method="post" action="{{ url_for('add') }}" class="row g-2 mt-2">
            <div class="col-12 col-lg-4">
              <input class="form-control" name="nome" placeholder="Nome do produto" required>
            </div>
            <div class="col-12 col-lg-2">
              <input class="form-control" name="sku" placeholder="SKU/Código (opcional)">
            </div>
            <div class="col-6 col-lg-2">
              <div class="input-group">
                <span class="input-group-text">R$</span>
                <input class="form-control" name="preco" placeholder="199.90" required>
              </div>
            </div>
            <div class="col-6 col-lg-1">
              <input class="form-control" name="quantidade" placeholder="Qtd" required>
            </div>
            <div class="col-6 col-lg-1">
              <input class="form-control" name="minimo" placeholder="Mín" value="0" required>
            </div>
            <div class="col-6 col-lg-2">
              <select class="form-select" name="categoria_id">
                <option value="">Sem categoria</option>
                {% for c in categorias %}
                  <option value="{{ c.id }}">{{ c.nome }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-12 col-lg-12 d-grid mt-1">
              <button class="btn btn-success" type="submit">Salvar</button>
            </div>
          </form>
          <div class="form-text mt-2">
            <b>Estoque baixo</b> quando <span class="mono">Qtd ≤ Mín</span>. Você pode filtrar por isso no topo.
          </div>
        </div>
      </div>

      <div class="table-responsive px-3 pb-3">
        <table class="table table-hover bg-white rounded-4 overflow-hidden">
          <thead class="table-light">
            <tr>
              <th style="width:90px">ID</th>
              <th>Produto</th>
              <th style="width:160px">Categoria</th>
              <th style="width:160px">SKU</th>
              <th style="width:140px">Preço</th>
              <th style="width:140px">Estoque</th>
              <th style="width:320px" class="text-end">Ações</th>
            </tr>
          </thead>
          <tbody>
            {% if not produtos %}
              <tr>
                <td colspan="7" class="text-center text-secondary py-5">
                  Nenhum produto encontrado.
                  <div class="mt-2">Tente pesquisar outro termo ou cadastre acima.</div>
                </td>
              </tr>
            {% endif %}

            {% for p in produtos %}
              {% set low = (p.quantidade <= p.estoque_minimo) %}
              <tr>
                <td class="text-secondary">#{{ p.id }}</td>
                <td>
                  <div class="fw-semibold">{{ p.nome }}</div>
                  <div class="muted small">Mín: <span class="mono">{{ p.estoque_minimo }}</span></div>
                </td>
                <td class="muted">{{ p.categoria.nome if p.categoria else '—' }}</td>
                <td class="mono">{{ p.sku if p.sku else '—' }}</td>
                <td class="mono">R$ {{ '%.2f'|format(p.preco) }}</td>
                <td>
                  <span class="pill mono {% if low %}pill-warn{% endif %}">
                    {{ p.quantidade }}
                    {% if low %} • baixo{% endif %}
                  </span>
                </td>
                <td class="text-end">
                  <div class="d-inline-flex flex-wrap gap-2 justify-content-end">
                    <form method="post" action="{{ url_for('stock', pid=p.id) }}">
                      <input type="hidden" name="delta" value="1">
                      <button class="btn btn-sm btn-outline-success" type="submit">+1</button>
                    </form>
                    <form method="post" action="{{ url_for('stock', pid=p.id) }}">
                      <input type="hidden" name="delta" value="-1">
                      <button class="btn btn-sm btn-outline-warning" type="submit">-1</button>
                    </form>

                    <button class="btn btn-sm btn-outline-primary"
                            data-bs-toggle="modal"
                            data-bs-target="#editModal"
                            data-id="{{ p.id }}"
                            data-nome="{{ p.nome|e }}"
                            data-sku="{{ p.sku|e if p.sku else '' }}"
                            data-preco="{{ '%.2f'|format(p.preco) }}"
                            data-quantidade="{{ p.quantidade }}"
                            data-minimo="{{ p.estoque_minimo }}"
                            data-categoria="{{ p.categoria_id if p.categoria_id else '' }}">
                      Editar
                    </button>

                    <form method="post" action="{{ url_for('delete', pid=p.id) }}"
                          onsubmit="return confirm('Excluir o produto: {{ p.nome }} ?');">
                      <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
                    </form>
                  </div>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>

        <div class="d-flex justify-content-between align-items-center mt-2">
          <div class="muted small">Total no banco: <b>{{ total }}</b> • Mostrando: <b>{{ produtos|length }}</b></div>
          <div class="d-flex gap-2">
            <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('export_excel') }}">Exportar Excel</a>
            <a class="btn btn-sm btn-primary" href="#novo">+ Novo</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Modal Editar Produto -->
<div class="modal fade" id="editModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content" style="border-radius: 18px;">
      <div class="modal-header">
        <h5 class="modal-title">Editar produto</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <form method="post" action="{{ url_for('edit') }}">
        <div class="modal-body">
          <input type="hidden" name="id" id="edit-id">
          <div class="row g-2">
            <div class="col-12 col-lg-5">
              <label class="form-label">Nome</label>
              <input class="form-control" name="nome" id="edit-nome" required>
            </div>
            <div class="col-12 col-lg-3">
              <label class="form-label">SKU/Código</label>
              <input class="form-control" name="sku" id="edit-sku" placeholder="Opcional">
            </div>
            <div class="col-6 col-lg-2">
              <label class="form-label">Preço</label>
              <div class="input-group">
                <span class="input-group-text">R$</span>
                <input class="form-control" name="preco" id="edit-preco" required>
              </div>
            </div>
            <div class="col-6 col-lg-2">
              <label class="form-label">Categoria</label>
              <select class="form-select" name="categoria_id" id="edit-categoria">
                <option value="">Sem categoria</option>
                {% for c in categorias %}
                  <option value="{{ c.id }}">{{ c.nome }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-6 col-lg-2">
              <label class="form-label">Qtd</label>
              <input class="form-control" name="quantidade" id="edit-quantidade" required>
            </div>
            <div class="col-6 col-lg-2">
              <label class="form-label">Mín</label>
              <input class="form-control" name="minimo" id="edit-minimo" required>
            </div>
          </div>
          <div class="form-text mt-2">Se SKU estiver preenchido, ele deve ser único (não pode repetir).</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary">Salvar</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- Modal Categorias -->
<div class="modal fade" id="catsModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content" style="border-radius: 18px;">
      <div class="modal-header">
        <h5 class="modal-title">Categorias</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <form class="d-flex gap-2" method="post" action="{{ url_for('add_category') }}">
          <input class="form-control" name="nome" placeholder="Nova categoria (ex.: Periféricos)" required>
          <button class="btn btn-primary" type="submit">Adicionar</button>
        </form>

        <hr>

        <div class="muted small mb-2">Categorias existentes</div>
        <ul class="list-group">
          {% for c in categorias %}
            <li class="list-group-item d-flex justify-content-between align-items-center">
              <span>{{ c.nome }}</span>
              <form method="post" action="{{ url_for('delete_category', cid=c.id) }}"
                    onsubmit="return confirm('Excluir a categoria {{ c.nome }}? Produtos ficarão sem categoria.');">
                <button class="btn btn-sm btn-outline-danger" type="submit">Excluir</button>
              </form>
            </li>
          {% endfor %}
        </ul>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Fechar</button>
      </div>
    </div>
  </div>
</div>

<script>
  const editModal = document.getElementById('editModal');
  editModal?.addEventListener('show.bs.modal', event => {
    const btn = event.relatedTarget;
    document.getElementById('edit-id').value = btn.getAttribute('data-id');
    document.getElementById('edit-nome').value = btn.getAttribute('data-nome');
    document.getElementById('edit-sku').value = btn.getAttribute('data-sku');
    document.getElementById('edit-preco').value = btn.getAttribute('data-preco');
    document.getElementById('edit-quantidade').value = btn.getAttribute('data-quantidade');
    document.getElementById('edit-minimo').value = btn.getAttribute('data-minimo');
    const cat = btn.getAttribute('data-categoria') || '';
    document.getElementById('edit-categoria').value = cat;
  });
</script>
"""

def render_page(body: str, **ctx):
    return render_template_string(BASE_HTML, body=render_template_string(body, **ctx), **ctx)


# ---------------- Rotas ----------------

@app.get("/")
def home():
    q = (request.args.get("q") or "").strip()
    cat = (request.args.get("cat") or "").strip()
    low_only = (request.args.get("low") or "").strip() == "1"

    cat_id = None
    if cat:
        try:
            cat_id = int(cat)
        except Exception:
            cat_id = None

    with Session(ENGINE) as session:
        categorias = get_categories(session)
        total = session.execute(select(func.count(Produto.id))).scalar_one()

        stmt = select(Produto).order_by(Produto.id.desc())

        if q:
            ql = q.lower()
            stmt = stmt.where(
                func.lower(Produto.nome).like(f"%{ql}%")
                | func.lower(func.coalesce(Produto.sku, "")).like(f"%{ql}%")
            )

        if cat_id:
            stmt = stmt.where(Produto.categoria_id == cat_id)

        if low_only:
            stmt = stmt.where(Produto.quantidade <= Produto.estoque_minimo)

        produtos = session.execute(stmt).scalars().all()

        # eager load categoria (acesso simples no template)
        for p in produtos:
            _ = p.categoria

    return render_page(
        HOME_BODY,
        title="Produtos",
        produtos=produtos,
        categorias=categorias,
        q=q,
        cat_id=cat_id,
        low_only=low_only,
        total=total,
        using_postgres=USING_POSTGRES,
    )


@app.post("/add")
def add():
    nome = clean_name(request.form.get("nome", ""))
    sku = clean_sku(request.form.get("sku", ""))
    preco = parse_float(request.form.get("preco", ""))
    qtd = parse_int(request.form.get("quantidade", ""))
    minimo = parse_int(request.form.get("minimo", "0"))
    cat_raw = (request.form.get("categoria_id") or "").strip()

    cat_id = None
    if cat_raw:
        try:
            cat_id = int(cat_raw)
        except Exception:
            cat_id = None

    if not nome:
        flash("Informe um nome de produto.", "danger")
        return redirect(url_for("home") + "#novo")
    if preco is None:
        flash("Preço inválido. Ex.: 10,50", "danger")
        return redirect(url_for("home") + "#novo")
    if qtd is None:
        flash("Quantidade inválida. Use inteiro >= 0.", "danger")
        return redirect(url_for("home") + "#novo")
    if minimo is None:
        flash("Estoque mínimo inválido. Use inteiro >= 0.", "danger")
        return redirect(url_for("home") + "#novo")

    with Session(ENGINE) as session:
        # Se SKU existir, impede duplicidade por SKU
        if sku:
            dup_sku = session.execute(select(Produto).where(func.lower(Produto.sku) == sku.lower()).limit(1)).scalar_one_or_none()
            if dup_sku:
                flash(f"Já existe um produto com esse SKU (ID #{dup_sku.id}).", "warning")
                return redirect(url_for("home") + f"?q={sku}")

        # Também alerta por nome (case-insensitive)
        dup_nome = session.execute(select(Produto).where(func.lower(Produto.nome) == nome.lower()).limit(1)).scalar_one_or_none()
        if dup_nome:
            flash(f"Já existe um produto com esse nome (ID #{dup_nome.id}). Use a pesquisa para encontrá-lo.", "warning")
            return redirect(url_for("home") + f"?q={nome}")

        session.add(Produto(nome=nome, sku=sku or None, preco=preco, quantidade=qtd, estoque_minimo=minimo, categoria_id=cat_id))
        session.commit()

    flash("Produto cadastrado com sucesso!", "success")
    return redirect(url_for("home"))


@app.post("/edit")
def edit():
    pid = request.form.get("id", "")
    nome = clean_name(request.form.get("nome", ""))
    sku = clean_sku(request.form.get("sku", ""))
    preco = parse_float(request.form.get("preco", ""))
    qtd = parse_int(request.form.get("quantidade", ""))
    minimo = parse_int(request.form.get("minimo", "0"))
    cat_raw = (request.form.get("categoria_id") or "").strip()

    try:
        pid_int = int(pid)
    except Exception:
        flash("ID inválido.", "danger")
        return redirect(url_for("home"))

    cat_id = None
    if cat_raw:
        try:
            cat_id = int(cat_raw)
        except Exception:
            cat_id = None

    if not nome:
        flash("Informe um nome de produto.", "danger")
        return redirect(url_for("home"))
    if preco is None:
        flash("Preço inválido. Ex.: 10,50", "danger")
        return redirect(url_for("home"))
    if qtd is None:
        flash("Quantidade inválida. Use inteiro >= 0.", "danger")
        return redirect(url_for("home"))
    if minimo is None:
        flash("Estoque mínimo inválido. Use inteiro >= 0.", "danger")
        return redirect(url_for("home"))

    with Session(ENGINE) as session:
        p = session.get(Produto, pid_int)
        if not p:
            flash("Produto não encontrado.", "warning")
            return redirect(url_for("home"))

        # SKU único
        if sku:
            dup_sku = session.execute(
                select(Produto).where(func.lower(Produto.sku) == sku.lower(), Produto.id != pid_int).limit(1)
            ).scalar_one_or_none()
            if dup_sku:
                flash(f"Já existe outro produto com esse SKU (ID #{dup_sku.id}).", "warning")
                return redirect(url_for("home") + f"?q={sku}")

        # Nome duplicado (alerta)
        dup_nome = session.execute(
            select(Produto).where(func.lower(Produto.nome) == nome.lower(), Produto.id != pid_int).limit(1)
        ).scalar_one_or_none()
        if dup_nome:
            flash(f"Já existe outro produto com esse nome (ID #{dup_nome.id}).", "warning")
            return redirect(url_for("home") + f"?q={nome}")

        p.nome = nome
        p.sku = sku or None
        p.preco = preco
        p.quantidade = qtd
        p.estoque_minimo = minimo
        p.categoria_id = cat_id
        session.commit()

    flash("Produto atualizado!", "success")
    return redirect(url_for("home"))


@app.post("/delete/<int:pid>")
def delete(pid: int):
    with Session(ENGINE) as session:
        p = session.get(Produto, pid)
        if not p:
            flash("Produto não encontrado.", "warning")
            return redirect(url_for("home"))
        session.delete(p)
        session.commit()

    flash("Produto excluído.", "success")
    return redirect(url_for("home"))


@app.post("/stock/<int:pid>")
def stock(pid: int):
    delta = request.form.get("delta", "0")
    try:
        d = int(delta)
    except Exception:
        flash("Ação inválida.", "danger")
        return redirect(url_for("home"))

    with Session(ENGINE) as session:
        p = session.get(Produto, pid)
        if not p:
            flash("Produto não encontrado.", "warning")
            return redirect(url_for("home"))

        novo = int(p.quantidade) + d
        if novo < 0:
            flash("Estoque não pode ficar negativo.", "warning")
            return redirect(url_for("home"))

        p.quantidade = novo
        session.commit()

    return redirect(url_for("home"))


# -------- Categorias --------

@app.post("/categorias/add")
def add_category():
    nome = clean_name(request.form.get("nome", ""))
    if not nome:
        flash("Informe o nome da categoria.", "danger")
        return redirect(url_for("home"))

    with Session(ENGINE) as session:
        dup = session.execute(select(Categoria).where(func.lower(Categoria.nome) == nome.lower()).limit(1)).scalar_one_or_none()
        if dup:
            flash("Essa categoria já existe.", "warning")
            return redirect(url_for("home"))
        session.add(Categoria(nome=nome))
        session.commit()

    flash("Categoria criada!", "success")
    return redirect(url_for("home"))


@app.post("/categorias/delete/<int:cid>")
def delete_category(cid: int):
    with Session(ENGINE) as session:
        c = session.get(Categoria, cid)
        if not c:
            flash("Categoria não encontrada.", "warning")
            return redirect(url_for("home"))
        # Desvincula produtos
        for p in session.execute(select(Produto).where(Produto.categoria_id == cid)).scalars().all():
            p.categoria_id = None
        session.delete(c)
        session.commit()

    flash("Categoria excluída. Produtos ficaram sem categoria.", "success")
    return redirect(url_for("home"))


# -------- Export Excel --------

@app.get("/export.xlsx")
def export_excel():
    with Session(ENGINE) as session:
        produtos = session.execute(
            select(Produto).order_by(Produto.id.asc())
        ).scalars().all()
        # carrega categorias
        for p in produtos:
            _ = p.categoria

    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos"

    headers = ["ID", "Nome", "Categoria", "SKU", "Preço", "Quantidade", "Estoque mínimo", "Estoque baixo?"]
    ws.append(headers)

    for p in produtos:
        low = int(p.quantidade) <= int(p.estoque_minimo)
        ws.append([
            p.id,
            p.nome,
            (p.categoria.nome if p.categoria else ""),
            (p.sku or ""),
            float(p.preco),
            int(p.quantidade),
            int(p.estoque_minimo),
            "SIM" if low else "NÃO",
        ])

    # Ajuste simples de largura
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)

    return send_file(
        bio,
        as_attachment=True,
        download_name="produtos.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
