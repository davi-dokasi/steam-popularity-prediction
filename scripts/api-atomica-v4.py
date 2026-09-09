"""
api-atomica-v4.py
=================
Coleta complementar de compatibilidade Linux via ProtonDB.

O que este script faz:
  - Lê os appids do dataset curado V2 (data/steam-jogos-v2.csv)
  - Para cada jogo, consulta a API (não-documentada) do ProtonDB e salva o
    resumo de compatibilidade via Proton (tier, confiança, nº de relatos)
  - Salva o resultado em checkpoints_v4/ com salvamento atômico

Por que ProtonDB?
  As colunas `windows`/`mac`/`linux` vêm do `appdetails` e refletem só suporte
  NATIVO. Muitos jogos marcados como Windows-only na verdade rodam bem no
  Linux via Proton (camada de compatibilidade da Valve/Steam Deck), e o
  ProtonDB é onde a comunidade registra isso. Sem esse dado, a análise de
  plataforma fica incompleta — foi o próprio orientador quem apontou isso.

Sobre a distinção "sem relato" vs. "falha na coleta" (mesma lição do V1→V2):
  A API retorna HTTP 404 pra jogos sem NENHUM relato registrado no ProtonDB —
  isso é uma ausência real, não uma falha de coleta, e por isso é tratado
  como um valor `None` explícito em `protondb_dict`, não como erro. Erros de
  verdade (timeout, status inesperado, JSON malformado) vão para `error_apps`
  e ficam de fora de `protondb_dict`, pra não repetir o erro do V1 (que
  tratava "API não retornou o campo" como se fosse "não tem review").

Sobre o endpoint:
  https://www.protondb.com/api/v1/reports/summaries/{appid}.json não é uma
  API pública documentada — é o endpoint que o próprio site protondb.com usa
  internamente, servido via CDN (Netlify) com cache de página estática, não
  um banco de dados sendo consultado ao vivo. Ainda assim, mantenho o mesmo
  intervalo de segurança usado no SteamSpy (V3) por precaução.

Escopo da coleta:
  Roda sobre TODOS os jogos de `steam-jogos-v2.csv` (não só os marcados como
  Windows-only) — a filtragem por "Windows-only vs. roda via Proton" fica
  pra etapa de análise, não pra coleta.

Como pausar com segurança:
  Pressione CTRL + C UMA VEZ e aguarde a mensagem de confirmação.

Como retomar:
  Execute o script novamente. Ele carregará o checkpoint do V4 e continuará
  de onde parou.
"""

import os
import sys
import time
import pickle
import requests
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════

BASE_DIR     = Path(__file__).resolve().parent.parent
JOGOS_CSV    = BASE_DIR / "data" / "steam-jogos-v2.csv"
CKPT_V4_DIR  = BASE_DIR / "checkpoints_v4"

# Endpoint é servido via CDN estático (não um banco ao vivo), mas mantemos o
# mesmo intervalo de segurança usado no SteamSpy (V3) por precaução.
DELAY_BETWEEN_REQUESTS = 0.35
DELAY_RATE_LIMIT       = 60      # segundos de pausa ao receber 429
CHECKPOINT_INTERVAL    = 500     # salvar a cada N apps processados


# ══════════════════════════════════════════════════════════════
# FUNÇÕES
# ══════════════════════════════════════════════════════════════

def print_log(*args):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ", end="")
    print(*args)


def save_pickle_atomic(final_path: Path, obj):
    """Salva atomicamente: escreve no .tmp e depois renomeia para evitar corrupção."""
    temp_path = final_path.with_suffix(".tmp")
    try:
        with open(temp_path, "wb") as handle:
            pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp_path, final_path)
    except Exception as e:
        print_log(f"❌ Erro ao salvar {final_path}: {e}")


def load_pickle(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


def save_checkpoints(protondb_dict: dict, error_set: set):
    CKPT_V4_DIR.mkdir(parents=True, exist_ok=True)
    save_pickle_atomic(CKPT_V4_DIR / "protondb_dict-v4.p", protondb_dict)
    save_pickle_atomic(CKPT_V4_DIR / "error_apps-v4.p",    error_set)


def fetch_protondb_summary(appid: int):
    """
    Consulta o endpoint de resumo do ProtonDB.

    Retorna:
        dict         → relatório real, ex.: {'tier': 'gold', 'confidence': 'strong',
                        'score': 0.79, 'total': 2086, 'bestReportedTier': 'platinum',
                        'trendingTier': 'platinum'}
        'NO_REPORT'  → HTTP 404: jogo existe mas não tem NENHUM relato no ProtonDB
                        (ausência real, não falha de coleta)
        'RATE_LIMIT' → recebeu HTTP 429
        None         → falha de coleta de verdade (timeout, status inesperado, JSON inválido)
    """
    url = f"https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
    try:
        resp = requests.get(url, timeout=15)

        if resp.status_code == 429:
            return "RATE_LIMIT"

        if resp.status_code == 404:
            return "NO_REPORT"

        if resp.status_code != 200:
            return None

        data = resp.json()
        return data if isinstance(data, dict) and data else None

    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print_log("Iniciando coleta V4 — Compatibilidade Linux via ProtonDB")
    print_log("Para pausar com segurança: pressione CTRL+C UMA VEZ e aguarde.")

    # ── Carregar appids do dataset curado ─────────────────────
    if not JOGOS_CSV.exists():
        print_log(f"❌ Arquivo não encontrado em: {JOGOS_CSV}")
        print_log("Execute a etapa de limpeza (steam-analise-v2.py) primeiro.")
        return

    print_log(f"Carregando appids de {JOGOS_CSV.name}...")
    jogos_df = pd.read_csv(JOGOS_CSV, encoding="utf-8-sig", usecols=["appid"], low_memory=False)
    game_ids = jogos_df["appid"].astype(int).tolist()
    print_log(f"✔ {len(game_ids):,} jogos carregados.")

    # ── Carregar progresso V4 (se existir) ────────────────────
    protondb_dict = {}
    error_apps    = set()

    pdb_path = CKPT_V4_DIR / "protondb_dict-v4.p"
    err_path = CKPT_V4_DIR / "error_apps-v4.p"

    if pdb_path.exists():
        protondb_dict = load_pickle(pdb_path)
        print_log(f"✔ Progresso V4 carregado: {len(protondb_dict):,} apps já processados.")
    if err_path.exists():
        error_apps = load_pickle(err_path)
        print_log(f"  → {len(error_apps):,} apps marcados como erro anteriormente.")

    # ── Montar fila de pendentes ──────────────────────────────
    already_done = set(protondb_dict.keys()) | error_apps
    to_process   = [appid for appid in game_ids if appid not in already_done]
    queue        = deque(to_process)

    print_log(f"Apps pendentes para consultar no ProtonDB: {len(queue):,}")

    if not queue:
        print_log("✅ Todos os apps já foram processados! Nada a fazer.")
        return

    # ── Estimativa de tempo ───────────────────────────────────
    est_hours = (len(queue) * DELAY_BETWEEN_REQUESTS) / 3600
    print_log(f"Estimativa de tempo (aprox.): {est_hours:.1f} horas")

    # ── Loop de coleta ────────────────────────────────────────
    counter    = 0
    total_done = len(already_done)
    n_com_report = sum(1 for v in protondb_dict.values() if v is not None)

    try:
        while queue:
            appid = queue.popleft()

            result = fetch_protondb_summary(appid)

            if result == "RATE_LIMIT":
                print_log(f"⚠️ RATE LIMIT do ProtonDB. Pausando {DELAY_RATE_LIMIT}s...")
                queue.appendleft(appid)
                time.sleep(DELAY_RATE_LIMIT)
                continue

            if result is None:
                # Falha de coleta de verdade — não confundir com "sem relato"
                error_apps.add(appid)
            elif result == "NO_REPORT":
                # Ausência real e confirmada (HTTP 404) — não é falha de coleta
                protondb_dict[appid] = None
            else:
                protondb_dict[appid] = result
                n_com_report += 1

            total_done += 1
            counter    += 1

            # Log de progresso a cada 50 apps
            if counter % 50 == 0:
                pct = total_done / len(game_ids) * 100
                print_log(f"  Progresso: {total_done:,}/{len(game_ids):,} ({pct:.1f}%) "
                          f"| Com relato: {n_com_report:,} | Último App ID: {appid}")

            # Salvar checkpoint a cada N apps
            if counter >= CHECKPOINT_INTERVAL:
                save_checkpoints(protondb_dict, error_apps)
                print_log(f"💾 Checkpoint V4 salvo! ({len(protondb_dict):,} apps processados)")
                counter = 0

            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        print_log("\n⚠️ COLETA INTERROMPIDA PELO USUÁRIO (Ctrl+C). SALVANDO DADOS...")
        save_checkpoints(protondb_dict, error_apps)
        print_log(f"✅ PROGRESSO SALVO: {len(protondb_dict):,} apps processados.")
        print_log("Pode fechar o terminal com segurança.")
        sys.exit(0)

    except Exception:
        print_log(f"\n❌ Erro inesperado:\n{traceback.format_exc()}")
        save_checkpoints(protondb_dict, error_apps)
        print_log("Dados salvos antes do crash.")

    # ── Salvamento final ──────────────────────────────────────
    save_checkpoints(protondb_dict, error_apps)
    print_log(f"\n✅ Coleta V4 finalizada!")
    print_log(f"  Apps processados:       {len(protondb_dict):,}")
    print_log(f"  ...com relato real:     {n_com_report:,}")
    print_log(f"  ...sem relato (404):    {len(protondb_dict) - n_com_report:,}")
    print_log(f"  Apps com falha real:    {len(error_apps):,}")
    print_log(f"  Checkpoints salvos em:  {CKPT_V4_DIR}")
    print_log("Próximo passo: mesclar checkpoints_v4/protondb_dict-v4.p na análise de plataforma do notebook.")


if __name__ == "__main__":
    main()
