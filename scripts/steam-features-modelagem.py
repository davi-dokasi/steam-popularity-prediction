# -*- coding: utf-8 -*-
"""
steam-features-modelagem.py
============================
Extrai do checkpoint V2 os campos que a limpeza original (steam-analise-v2.py)
não levou para o CSV, mas que já estavam coletados desde sempre no payload do
appdetails.

Motivação:
  O coletor V2 grava o payload inteiro do appdetails (apps_dict[appid] = details).
  O steam-analise-v2.py extraiu 51 colunas dele; o resto ficou no pickle. Como
  descrição, arte de capa, desenvolvedora e distribuidora já estão pagos em tempo
  de coleta, dá para montar uma base de modelagem bem mais rica sem nenhuma
  requisição nova à API.

Corrige também um bug de moeda:
  steam-analise-v2.py faz price.get("final") / 100 para todos os apps e chama a
  coluna de "price_brl". Mas nem todo app volta em BRL — parte veio em IDR, VND,
  USD, EUR e outras. Atomic Heart aparece na base a "R$ 549.000" porque o payload
  traz Rp 549 000 (rupias indonésias). A moeda está no próprio payload
  (price_overview.currency), então dá para separar sem recoletar nada.

Saídas (em data/):
  steam-features-v2.csv  — colunas numéricas/categóricas novas, uma linha por app
  steam-textos-v2.csv    — appid + descrições com HTML removido (base do TextCNN)

Uso:
  python scripts/steam-features-modelagem.py
"""

import re
import sys
import html
import pickle
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════

# Este script fica em scripts/, mas checkpoints_v2/ e data/ estão na raiz do repo —
# por isso parent.parent, e não parent.
BASE_DIR        = Path(__file__).resolve().parent.parent
CHECKPOINT_FILE = BASE_DIR / "checkpoints_v2" / "apps_dict-v2.p"
DATA_DIR        = BASE_DIR / "data"

# Descrição longa truncada para segurar o tamanho do CSV de texto.
# A mediana é ~2.065 caracteres, então 6.000 preserva a grande maioria inteira.
MAX_DETAILED = 6_000

TAG_RE = re.compile(r"<[^>]+>")
WS_RE  = re.compile(r"\s+")


# ══════════════════════════════════════════════════════════════
# FUNÇÕES
# ══════════════════════════════════════════════════════════════

def limpar_html(texto) -> str:
    """Remove tags HTML e normaliza espaços. As descrições da Steam vêm com
    <p>, <br>, <strong>, <img> e entidades escapadas no meio."""
    if not isinstance(texto, str) or not texto:
        return ""
    texto = TAG_RE.sub(" ", texto)
    texto = html.unescape(texto)
    return WS_RE.sub(" ", texto).strip()


def primeiro(lista):
    """Primeiro elemento não-vazio de uma lista de strings, ou None."""
    if not isinstance(lista, list):
        return None
    for item in lista:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def extrair_preco(d: dict) -> dict:
    """Preço com a moeda preservada. 'price_valor' fica na unidade menor da moeda
    (centavos em BRL/USD/EUR, unidade inteira em VND/IDR), exatamente como a API
    devolve — a conversão fica a cargo de quem for usar, agora sabendo a moeda."""
    p = d.get("price_overview") or {}
    if not p:
        return {"price_currency": None, "price_valor": None,
                "price_desconto_pct": None, "price_formatado": None}
    return {
        "price_currency":     p.get("currency"),
        "price_valor":        p.get("final"),
        "price_desconto_pct": p.get("discount_percent"),
        "price_formatado":    p.get("final_formatted") or None,
    }


def extrair_conteudo(d: dict) -> dict:
    """Descritores de conteúdo (violência, conteúdo adulto etc.) e classificação
    etária brasileira, quando a Steam expõe."""
    cd  = d.get("content_descriptors") or {}
    ids = cd.get("ids") or []
    ratings = d.get("ratings") or {}
    dejus   = ratings.get("dejus") or {}
    return {
        "n_descritores_conteudo": len(ids) if isinstance(ids, list) else 0,
        # id 1 e 3 = conteúdo sexual adulto na taxonomia da Steam
        "conteudo_adulto":        bool(set(ids) & {1, 3}) if isinstance(ids, list) else False,
        "dejus_idade":            dejus.get("required_age") or dejus.get("rating"),
        "n_sistemas_rating":      len(ratings) if isinstance(ratings, dict) else 0,
    }


def extrair_requisitos(d: dict) -> dict:
    """Tamanho do texto de requisitos de PC. Serve como proxy grosseiro de
    'quão elaborada é a ficha técnica' — jogos maiores costumam detalhar mais."""
    pc = d.get("pc_requirements") or {}
    if isinstance(pc, list):  # a Steam devolve [] quando não há requisitos
        pc = {}
    minimo = limpar_html(pc.get("minimum", "")) if isinstance(pc, dict) else ""
    recom  = limpar_html(pc.get("recommended", "")) if isinstance(pc, dict) else ""
    return {
        "req_min_chars":   len(minimo),
        "tem_req_recomendado": bool(recom),
    }


# ══════════════════════════════════════════════════════════════
# 1. CARREGAR O CHECKPOINT
# ══════════════════════════════════════════════════════════════

print("=" * 62)
print("STEAM — EXTRAÇÃO DE FEATURES PARA MODELAGEM")
print("=" * 62)

if not CHECKPOINT_FILE.exists():
    print(f"\n✖ Checkpoint não encontrado: {CHECKPOINT_FILE}")
    sys.exit(1)

print(f"\nCarregando {CHECKPOINT_FILE.name}...")
print("(Arquivo de ~2,3 GB, pode levar alguns minutos)")

with open(CHECKPOINT_FILE, "rb") as f:
    app_data = pickle.load(f)

print(f"✔ {len(app_data):,} aplicativos carregados.\n")


# ══════════════════════════════════════════════════════════════
# 2. EXTRAIR
# ══════════════════════════════════════════════════════════════

print("Extraindo campos do payload...")

linhas, textos = [], []

for app_id, d in app_data.items():
    if not isinstance(d, dict):
        continue

    devs = d.get("developers") or []
    pubs = d.get("publishers") or []
    shots = d.get("screenshots") or []
    movs  = d.get("movies") or []
    rd    = d.get("release_date") or {}

    curto   = limpar_html(d.get("short_description"))
    longo   = limpar_html(d.get("detailed_description"))

    linha = {
        "appid":              app_id,
        "coming_soon":        bool(rd.get("coming_soon", False)),

        # Estúdio — base para o histórico de lançamentos anteriores
        "desenvolvedora":     primeiro(devs),
        "n_desenvolvedoras":  len(devs) if isinstance(devs, list) else 0,
        "distribuidora":      primeiro(pubs),
        "n_distribuidoras":   len(pubs) if isinstance(pubs, list) else 0,
        "auto_publicado":     bool(devs and pubs and set(devs) == set(pubs)),

        # Material da página da loja
        "n_screenshots":      len(shots) if isinstance(shots, list) else 0,
        "n_videos":           len(movs) if isinstance(movs, list) else 0,
        "tem_trailer":        bool(movs),
        "tem_site":           bool(d.get("website")),
        "suporte_controle":   d.get("controller_support") or "nenhum",
        "n_pacotes":          len(d.get("packages") or []),

        # Texto — tamanho como feature; o conteúdo vai no CSV separado
        "desc_curta_chars":   len(curto),
        "desc_longa_chars":   len(longo),
        "desc_curta_palavras": len(curto.split()) if curto else 0,

        # URL da capa (guardada por completude; sem os pixels não dá para usar
        # em CNN visual, mas fica registrado de onde viria)
        "header_image":       d.get("header_image"),
    }
    linha.update(extrair_preco(d))
    linha.update(extrair_conteudo(d))
    linha.update(extrair_requisitos(d))

    linhas.append(linha)
    textos.append({
        "appid":                app_id,
        "short_description":    curto,
        "detailed_description": longo[:MAX_DETAILED],
    })

feat = pd.DataFrame(linhas)
txt  = pd.DataFrame(textos)

print(f"✔ {len(feat):,} linhas extraídas, {feat.shape[1]} colunas.\n")


# ══════════════════════════════════════════════════════════════
# 3. DIAGNÓSTICO DA MOEDA
# ══════════════════════════════════════════════════════════════

print("-" * 62)
print("MOEDA — o bug que o price_brl atual esconde")
print("-" * 62)

com_preco = feat[feat["price_currency"].notna()]
contagem  = com_preco["price_currency"].value_counts()
n_nao_brl = int((com_preco["price_currency"] != "BRL").sum())

print(f"\nApps com bloco de preço: {len(com_preco):,}")
print(f"Em BRL:                  {int(contagem.get('BRL', 0)):,}")
print(f"Em outra moeda:          {n_nao_brl:,} "
      f"({100 * n_nao_brl / len(com_preco):.2f}%)\n")
print(contagem.head(12).to_string())

print("\nExemplos do que virou preço absurdo na base atual:")
fora = com_preco[com_preco["price_currency"] != "BRL"].nlargest(5, "price_valor")
for _, r in fora.iterrows():
    convertido = r["price_valor"] / 100
    print(f"  appid {r['appid']:>8} | {r['price_currency']} "
          f"{r['price_formatado']:>14} → viraria R$ {convertido:,.2f}")


# ══════════════════════════════════════════════════════════════
# 4. SALVAR
# ══════════════════════════════════════════════════════════════

DATA_DIR.mkdir(exist_ok=True)
saida_feat = DATA_DIR / "steam-features-v2.csv"
saida_txt  = DATA_DIR / "steam-textos-v2.csv"

feat.to_csv(saida_feat, index=False, encoding="utf-8-sig")
txt.to_csv(saida_txt, index=False, encoding="utf-8-sig")

print("\n" + "-" * 62)
print("ARQUIVOS GERADOS")
print("-" * 62)
for p in (saida_feat, saida_txt):
    print(f"  {p.relative_to(BASE_DIR)}  —  {p.stat().st_size / 1024**2:,.1f} MB")

print("\nColunas em steam-features-v2.csv:")
print("  " + ", ".join(feat.columns))

print("\n✔ Concluído. Junte com data/steam-jogos-v2.csv pela coluna 'appid'.")
