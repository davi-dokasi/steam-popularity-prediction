"""
steam-analise-v2.py
===================
Processamento e exportação dos dados coletados pelo api-atomica-v2.

Novidades em relação à v1:
  - Lê os checkpoints da pasta checkpoints_v2/
  - Extrai os campos de 'exact_reviews' (total_reviews, total_positive,
    total_negative, review_score, review_score_desc)
  - Trata dados faltantes com regras de negócio corretas (sem viés de seleção)
  - Exporta dois CSVs limpos:
      • steam-dados-v2.csv  → todos os apps coletados
      • steam-jogos-v2.csv  → apenas type == "game" (dataset de modelagem)

NOTA: a coleta (api-atomica.py e api-atomica-v2.py) usa o IStoreService/GetAppList
sem passar include_dlc/include_software/include_videos/include_hardware, e por
padrão esse endpoint só retorna type=="game" (documentado na Steamworks API).
Na prática isso faz de steam-dados-v2.csv e steam-jogos-v2.csv o mesmo conteúdo
hoje — não há DLC/soundtrack/software na base, nem na V1 nem na V2.
"""

import sys
import pickle
import numpy as np
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════

BASE_DIR        = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR  = BASE_DIR / "checkpoints_v2"
CHECKPOINT_FILE = CHECKPOINT_DIR / "apps_dict-v2.p"
OUTPUT_DIR      = BASE_DIR / "data"

# Gêneros da Steam que serão transformados em colunas binárias (one-hot)
TARGET_GENRES = [
    "Action", "Adventure", "Casual", "Indie",
    "Massively Multiplayer", "Racing", "RPG",
    "Simulation", "Sports", "Strategy",
    "Early Access",
    # NOTA: "Free to Play" NÃO aparece no campo 'genres' do appdetails.
    # Use a coluna 'is_free' (boolean) para capturar jogos gratuitos.
]

# Categorias importantes que viram colunas binárias
# (ex: suporte a controlador, co-op, multijogador etc.)
# ATENÇÃO: strings case-sensitive, devem ser idênticas ao retorno da API Steam.
TARGET_CATEGORIES = [
    "Single-player",
    "Multi-player",
    "Co-op",
    "Online Co-op",
    # "Local Co-op" foi renomeada pela Steam para:
    "Shared/Split Screen Co-op",
    "PvP",
    "Online PvP",
    "Steam Achievements",
    "Steam Cloud",
    "Steam Trading Cards",
    "Steam Workshop",
    "Full controller support",
    "Partial Controller Support",
    "VR Support",
    "Family Sharing",
    "Valve Anti-Cheat enabled",
]


# ══════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES
# ══════════════════════════════════════════════════════════════

def parse_release_date(entry: dict) -> datetime:
    """Converte a data de lançamento da Steam para datetime.
    Tenta múltiplos formatos pois a Steam não é consistente."""
    raw = entry.get("release_date", {}).get("date", "")
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%b %Y", "%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def extract_genres(entry: dict) -> set:
    """Retorna um set com as descrições dos gêneros do app."""
    return {g.get("description") for g in entry.get("genres", []) if g.get("description")}


def extract_categories(entry: dict) -> set:
    """Retorna um set com as descrições das categorias do app."""
    return {c.get("description") for c in entry.get("categories", []) if c.get("description")}


def extract_platforms(entry: dict) -> dict:
    """Retorna dict com suporte a plataformas (Windows, Mac, Linux)."""
    p = entry.get("platforms", {})
    return {
        "windows": bool(p.get("windows", False)),
        "mac":     bool(p.get("mac",     False)),
        "linux":   bool(p.get("linux",   False)),
    }


def extract_metacritic(entry: dict):
    """Retorna a nota do Metacritic, se disponível."""
    mc = entry.get("metacritic", {})
    if isinstance(mc, dict):
        return pd.to_numeric(mc.get("score"), errors="coerce")
    return np.nan


def extract_supported_languages(entry: dict) -> int:
    """Conta o número de idiomas suportados (aproximado via HTML)."""
    langs = entry.get("supported_languages", "")
    if not langs:
        return 0
    # A string vem com HTML; uma contagem simples de vírgulas+1 é boa aproximação
    import re
    clean = re.sub(r"<[^>]+>", "", langs)
    return len([l for l in clean.split(",") if l.strip()])


def extract_dlc_count(entry: dict) -> int:
    """Conta os DLCs listados no app."""
    dlc = entry.get("dlc", [])
    return len(dlc) if isinstance(dlc, list) else 0


# ══════════════════════════════════════════════════════════════
# 1. CARREGAR DADOS
# ══════════════════════════════════════════════════════════════

print("=" * 60)
print("STEAM ANALISE V2 — Processamento de Dados")
print("=" * 60)
print(f"\nCarregando {CHECKPOINT_FILE.name}...")
print("(Arquivo de ~2 GB, pode levar alguns minutos)")

with open(CHECKPOINT_FILE, "rb") as f:
    app_data = pickle.load(f)

print(f"✔ {len(app_data):,} aplicativos carregados.\n")


# ══════════════════════════════════════════════════════════════
# 2. CONSTRUIR O DATAFRAME
# ══════════════════════════════════════════════════════════════

print("Construindo DataFrame — extraindo todos os campos...")

rows = []

for app_id, d in app_data.items():
    genres     = extract_genres(d)
    categories = extract_categories(d)
    platforms  = extract_platforms(d)
    price      = d.get("price_overview") or {}

    # ── Bloco exact_reviews (novo — vem do endpoint appreviews) ──────────
    er = d.get("exact_reviews") or {}
    exact_total_reviews  = er.get("total_reviews",   None)
    exact_total_positive = er.get("total_positive",  None)
    exact_total_negative = er.get("total_negative",  None)
    review_score         = er.get("review_score",    None)   # 0–9 numérico
    review_score_desc    = er.get("review_score_desc", None) # texto (ex: "Very Positive")

    row = {
        # ── Identificação ──────────────────────────────────────────────
        "appid":                app_id,
        "name":                 d.get("name"),
        "type":                 d.get("type"),

        # ── Preço e monetização ────────────────────────────────────────
        "is_free":              bool(d.get("is_free", False)),
        "price_brl":            price.get("final", 0) / 100 if price else None,

        # ── Avaliações (NOVO — appreviews endpoint) ────────────────────
        # Atenção: exact_total_reviews é o ground truth. Jogos sem block
        # de reviews terão None aqui (tratado na curadoria abaixo).
        "reviews_total":        exact_total_reviews,
        "reviews_positive":     exact_total_positive,
        "reviews_negative":     exact_total_negative,
        "review_score":         review_score,
        "review_score_desc":    review_score_desc,

        # ── Dados legados (appdetails — ainda úteis como fallback) ──────
        "recommendations_total": (d.get("recommendations") or {}).get("total"),

        # ── Conquistas ─────────────────────────────────────────────────
        "achievements_total":   (d.get("achievements") or {}).get("total"),

        # ── Metadados do jogo ──────────────────────────────────────────
        "required_age":         pd.to_numeric(d.get("required_age", 0), errors="coerce"),
        "metacritic_score":     extract_metacritic(d),
        "supported_languages_count": extract_supported_languages(d),
        "dlc_count":            extract_dlc_count(d),
        "has_demos":            bool(d.get("demos")),

        # ── Plataformas ────────────────────────────────────────────────
        "windows":              platforms["windows"],
        "mac":                  platforms["mac"],
        "linux":                platforms["linux"],

        # ── Data de lançamento ─────────────────────────────────────────
        "release_date":         parse_release_date(d),
    }

    # ── Colunas binárias de GÊNERO ─────────────────────────────────────
    for genre in TARGET_GENRES:
        col = f"genre_{genre.lower().replace(' ', '_')}"
        row[col] = genre in genres

    # ── Colunas binárias de CATEGORIA ──────────────────────────────────
    for cat in TARGET_CATEGORIES:
        col = f"cat_{cat.lower().replace(' ', '_').replace('/', '_')}"
        row[col] = cat in categories

    rows.append(row)

df = pd.DataFrame(rows)

# Derivar ano e mês de lançamento a partir da data
df["release_year"]  = df["release_date"].dt.year
df["release_month"] = df["release_date"].dt.month

print(f"✔ DataFrame criado: {df.shape[0]:,} linhas × {df.shape[1]} colunas.\n")


# ══════════════════════════════════════════════════════════════
# 3. CURADORIA / TRATAMENTO DE DADOS
#    Aplicar regras de negócio para eliminar viés de seleção
# ══════════════════════════════════════════════════════════════

print("=" * 60)
print("CURADORIA DE DADOS")
print("=" * 60)

print(f"\nTotal antes da curadoria: {len(df):,} apps\n")

# 3.1 Remover apps sem data de lançamento
df = df.dropna(subset=["release_date"])
print(f"  Após remover sem data de lançamento:     {len(df):,} apps")

# 3.2 Remover jogos ainda não lançados (datas futuras)
df = df[df["release_date"] <= pd.Timestamp.now()]
print(f"  Após remover não lançados (futuros):     {len(df):,} apps")

# 3.3 Imputar reviews com 0 onde não há dados
# JUSTIFICATIVA: Ausência do bloco "exact_reviews" na API significa 0 avaliações.
n_reviews_missing = df["reviews_total"].isna().sum()
df["reviews_total"]    = df["reviews_total"].fillna(0)
df["reviews_positive"] = df["reviews_positive"].fillna(0)
df["reviews_negative"] = df["reviews_negative"].fillna(0)
print(f"  Reviews imputadas com 0:                 {n_reviews_missing:,} apps")

# 3.4 Imputar conquistas com 0
n_ach_missing = df["achievements_total"].isna().sum()
df["achievements_total"] = df["achievements_total"].fillna(0)
print(f"  Conquistas imputadas com 0:              {n_ach_missing:,} apps")

# 3.5 Tratamento do preço
# - Jogos gratuitos: forçar preço = 0
df.loc[df["is_free"], "price_brl"] = 0.0
# - Jogos pagos sem preço listado: provavelmente fora de catálogo → remover
n_price_missing = df[~df["is_free"] & df["price_brl"].isna()].shape[0]
df = df.dropna(subset=["price_brl"])
print(f"  Jogos pagos sem preço removidos:         {n_price_missing:,} apps")

# 3.6 Imputar idade mínima com 0 (jogos sem classificação = sem restrição)
df["required_age"] = df["required_age"].fillna(0)

# 3.7 DLC count e outros numéricos
df["dlc_count"] = df["dlc_count"].fillna(0)
df["supported_languages_count"] = df["supported_languages_count"].fillna(0)

print(f"\n✔ Total após curadoria: {len(df):,} apps\n")

# ── Criar variável derivada: review_ratio (taxa de avaliações positivas) ──
# Apenas onde há avaliações suficientes (> 0)
df["review_ratio"] = np.where(
    df["reviews_total"] > 0,
    df["reviews_positive"] / df["reviews_total"],
    np.nan
)

# ── Padronizar review_score_desc ──────────────────────────────────────────
# A API retorna strings como "1 user reviews", "2 user reviews" para jogos
# com poucas avaliações. Mapeamos para categorias canônicas da Steam.
CANONICAL_SCORES = {
    "Overwhelmingly Positive",
    "Very Positive",
    "Mostly Positive",
    "Positive",
    "Mixed",
    "Mostly Negative",
    "Negative",
    "Overwhelmingly Negative",
}

def standardize_score_desc(val):
    if pd.isna(val):
        return "No user reviews"
    if val in CANONICAL_SCORES:
        return val
    # Strings como "1 user reviews", "2 user reviews" etc.
    return "No user reviews"

df["review_score_desc"] = df["review_score_desc"].apply(standardize_score_desc)


# ══════════════════════════════════════════════════════════════
# 4. DIAGNÓSTICO FINAL
# ══════════════════════════════════════════════════════════════

print("=" * 60)
print("DIAGNÓSTICO FINAL")
print("=" * 60)

# Filtrar apenas jogos
games = df[df["type"] == "game"].copy()

print(f"\n  Total de apps no dataset: {len(df):,}")
print(f"  Total de jogos (type=game): {len(games):,}")

print("\n── Tipos de app ──")
print(df["type"].value_counts().to_string())

print("\n── Jogos gratuitos vs pagos ──")
print(games["is_free"].value_counts().rename({True: "Gratuito", False: "Pago"}).to_string())

print("\n── Distribuição de reviews_total (jogos) ──")
print(games["reviews_total"].describe().round(2).to_string())
pct_zero = (games["reviews_total"] == 0).mean() * 100
print(f"  Jogos com 0 reviews: {pct_zero:.1f}%")

print("\n── Review Score Desc (top categorias) ──")
print(games["review_score_desc"].value_counts().head(10).to_string())

print("\n── Dados faltantes restantes (colunas principais) ──")
cols_check = ["reviews_total", "reviews_positive", "reviews_negative",
              "achievements_total", "price_brl", "required_age",
              "metacritic_score", "review_score_desc"]
missing = df[cols_check].isnull().sum()
missing_pct = (missing / len(df) * 100).round(1)
miss_df = pd.DataFrame({"Faltantes": missing, "% Total": missing_pct})
print(miss_df.to_string())

print("\n── Plataformas (jogos) ──")
for plat in ["windows", "mac", "linux"]:
    n   = games[plat].sum()
    pct = n / len(games) * 100
    print(f"  {plat.capitalize():>10}: {n:>7,} ({pct:.1f}%)")

print("\n── Gêneros mais comuns (jogos) ──")
genre_cols  = [c for c in games.columns if c.startswith("genre_")]
genre_counts = games[genre_cols].sum().sort_values(ascending=False)
genre_counts.index = (genre_counts.index
                      .str.replace("genre_", "")
                      .str.replace("_", " ")
                      .str.title())
print(genre_counts.to_string())

print("\n── Categorias mais comuns (jogos) ──")
cat_cols   = [c for c in games.columns if c.startswith("cat_")]
cat_counts = games[cat_cols].sum().sort_values(ascending=False)
cat_counts.index = (cat_counts.index
                    .str.replace("cat_", "")
                    .str.replace("_", " ")
                    .str.title())
print(cat_counts.to_string())

print("\n── Lançamentos por ano (top 10) ──")
valid_years = games[games["release_year"].between(1995, 2026)]
print(valid_years["release_year"].value_counts()
      .sort_index(ascending=False).head(10).to_string())


# ══════════════════════════════════════════════════════════════
# 5. EXPORTAR CSVs
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("EXPORTANDO CSVs")
print("=" * 60)

# Todos os apps
csv_all = OUTPUT_DIR / "steam-dados-v2.csv"
df.to_csv(csv_all, index=False, encoding="utf-8-sig")
print(f"\n✔ Dataset completo exportado: {csv_all}")
print(f"  ({len(df):,} apps × {df.shape[1]} colunas)")

# Apenas jogos (dataset de modelagem)
csv_games = OUTPUT_DIR / "steam-jogos-v2.csv"
games.to_csv(csv_games, index=False, encoding="utf-8-sig")
print(f"\n✔ Dataset de jogos exportado: {csv_games}")
print(f"  ({len(games):,} jogos × {games.shape[1]} colunas)")

print("\nProcessamento concluído! ✅")
print(f"\nArquivos gerados:")
print(f"  • steam-dados-v2.csv  → todos os apps coletados")
print(f"  • steam-jogos-v2.csv  → apenas jogos (use este para treinar a rede neural)")
print(f"\n  Nota: o GetAppList (IStoreService) só retorna type=='game' por padrão")
print(f"  (include_dlc/include_software não são passados) — na prática os dois")
print(f"  CSVs acima saem idênticos, não há DLC/soundtrack/software na coleta.")
