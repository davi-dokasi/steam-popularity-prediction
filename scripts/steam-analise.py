"""
steam-analise.py
================
Análise exploratória dos dados de jogos da Steam.
Carrega o dicionário de apps (pickle) e constrói um DataFrame
com as variáveis de interesse para análise.
"""

import sys
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Configurações ──────────────────────────────────────────────
# Corrige encoding do terminal Windows (cp1252 → UTF-8)
sys.stdout.reconfigure(encoding="utf-8")

# Este script fica em scripts/, mas checkpoints/ e data/ estão na raiz do repo —
# por isso parent.parent, e não parent.
BASE_DIR = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = BASE_DIR / "checkpoints"
CHECKPOINT_FILE = CHECKPOINT_DIR / "apps_dict-ckpt.p"

# Gêneros de interesse para colunas binárias (adicione/remova conforme necessário)
TARGET_GENRES = [
    "Action", "Adventure", "Casual", "Indie",
    "Massively Multiplayer", "Racing", "RPG",
    "Simulation", "Sports", "Strategy",
    "Early Access", "Free to Play",
]

# ── 1. Carregar dados ─────────────────────────────────────────
print("Carregando checkpoint... (isso pode demorar, o arquivo tem ~2 GB)")
with open(CHECKPOINT_FILE, "rb") as f:
    app_data = pickle.load(f)

print(f"✔ {len(app_data):,} aplicativos carregados.\n")


# ── 2. Funções auxiliares ──────────────────────────────────────
def parse_release_date(entry):
    """Converte a data de lançamento da Steam para datetime."""
    raw = entry.get("release_date", {}).get("date", "")
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%b %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def extract_genres(entry):
    """Retorna um set com as descrições dos gêneros do app."""
    return {g.get("description") for g in entry.get("genres", []) if g.get("description")}


def extract_categories(entry):
    """Retorna um set com as descrições das categorias do app."""
    return {c.get("description") for c in entry.get("categories", []) if c.get("description")}


def extract_platforms(entry):
    """Retorna dict com plataformas suportadas."""
    platforms = entry.get("platforms", {})
    return {
        "windows": platforms.get("windows", False),
        "mac": platforms.get("mac", False),
        "linux": platforms.get("linux", False),
    }


# ── 3. Construir o DataFrame ──────────────────────────────────
print("Construindo DataFrame...")

rows = []
for app_id, d in app_data.items():
    genres = extract_genres(d)
    platforms = extract_platforms(d)
    price = d.get("price_overview", {})

    row = {
        "appid": app_id,
        "name": d.get("name"),
        "type": d.get("type"),
        "is_free": d.get("is_free", False),
        "price_brl": price.get("final", 0) / 100 if price else None,
        "required_age": pd.to_numeric(d.get("required_age", 0), errors="coerce"),
        "reviews_total": d.get("recommendations", {}).get("total") if d.get("recommendations") else None,
        "achievements_total": d.get("achievements", {}).get("total") if d.get("achievements") else None,
        "release_date": parse_release_date(d),
        "windows": platforms["windows"],
        "mac": platforms["mac"],
        "linux": platforms["linux"],
    }

    # Colunas binárias de gênero
    for genre in TARGET_GENRES:
        row[f"genre_{genre.lower().replace(' ', '_')}"] = genre in genres

    rows.append(row)

df = pd.DataFrame(rows)

# Derivar ano e mês de lançamento
df["release_year"] = df["release_date"].dt.year
df["release_month"] = df["release_date"].dt.month

print(f"✔ DataFrame criado: {df.shape[0]:,} linhas × {df.shape[1]} colunas.\n")


# ── 4. Análise Exploratória (EDA) ─────────────────────────────
print("=" * 60)
print("ANÁLISE EXPLORATÓRIA DOS DADOS DA STEAM")
print("=" * 60)

# 4.1 Tipos de app
print("\n── Tipos de aplicativo ──")
print(df["type"].value_counts().to_string())

# 4.2 Filtrar apenas jogos para análises seguintes
games = df[df["type"] == "game"].copy()
print(f"\n📎 Total de jogos: {len(games):,}")

# 4.3 Jogos gratuitos vs pagos
print("\n── Jogos gratuitos vs pagos ──")
print(games["is_free"].value_counts().rename({True: "Gratuito", False: "Pago"}).to_string())

# 4.4 Preço (apenas jogos pagos)
paid = games[games["is_free"] == False]  # noqa: E712
if "price_brl" in paid.columns and paid["price_brl"].notna().any():
    print("\n── Estatísticas de preço (R$) - jogos pagos ──")
    print(paid["price_brl"].describe().to_string())

# 4.5 Reviews
print("\n── Estatísticas de reviews ──")
print(games["reviews_total"].describe().to_string())

# 4.6 Gêneros mais comuns
genre_cols = [c for c in df.columns if c.startswith("genre_")]
print("\n── Gêneros mais comuns (jogos) ──")
genre_counts = games[genre_cols].sum().sort_values(ascending=False)
genre_counts.index = genre_counts.index.str.replace("genre_", "").str.replace("_", " ").str.title()
print(genre_counts.to_string())

# 4.7 Plataformas
print("\n── Suporte por plataforma (jogos) ──")
for plat in ["windows", "mac", "linux"]:
    count = games[plat].sum()
    pct = count / len(games) * 100
    print(f"  {plat.capitalize():>10}: {count:>6,} ({pct:.1f}%)")

# 4.8 Lançamentos por ano
print("\n── Lançamentos por ano (top 10 anos reais) ──")
valid_years = games[games["release_year"].between(1990, 2026, inclusive="both")]
year_counts = valid_years["release_year"].value_counts().sort_index(ascending=False).head(10)
print(year_counts.to_string())

# 4.9 Idade mínima requerida
print("\n── Idade mínima requerida (distribuição) ──")
age_counts = games["required_age"].value_counts().sort_index()
print(age_counts.to_string())


# ── 5. Exportar CSV ───────────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)
csv_path = OUTPUT_DIR / "steam-dados.csv"
df.to_csv(csv_path, index=False, encoding="utf-8-sig")
print(f"\n✔ CSV exportado em: {csv_path}")

# Exportar também só os jogos
csv_games_path = OUTPUT_DIR / "steam-jogos.csv"
games.to_csv(csv_games_path, index=False, encoding="utf-8-sig")
print(f"✔ CSV (apenas jogos) exportado em: {csv_games_path}")

print("\n── Primeiras 10 linhas do dataset ──")
print(games[["appid", "name", "type", "is_free", "price_brl", "reviews_total", "release_year"]].head(10).to_string())

print("\nAnálise concluída! ✅")
