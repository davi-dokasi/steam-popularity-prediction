"""
api-atomica-v3.py
=================
Coleta complementar de Tags de Jogadores via SteamSpy.

O que este script faz:
  - Lê os checkpoints do V2 (checkpoints_v2/apps_dict-v2.p) como base
  - Para cada jogo, consulta a API do SteamSpy e salva as tags de jogadores
  - Salva o resultado enriquecido em checkpoints_v3/ com salvamento atômico

Por que SteamSpy?
  A API oficial da Steam (appdetails) não retorna as tags atribuídas pelos
  jogadores. O SteamSpy coleta essas tags diretamente da loja e as disponibiliza
  gratuitamente, com limite de 4 requisições/segundo (sem chave de API).

Como pausar com segurança:
  Pressione CTRL + C UMA VEZ e aguarde a mensagem de confirmação.

Como retomar:
  Execute o script novamente. Ele carregará o checkpoint do V3 e continuará
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

sys.stdout.reconfigure(encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════

BASE_DIR    = Path(__file__).resolve().parent.parent
CKPT_V2_DIR = BASE_DIR / "checkpoints_v2"
CKPT_V3_DIR = BASE_DIR / "checkpoints_v3"

# SteamSpy permite ~4 req/s sem autenticação. Usamos 0.35s de intervalo por segurança.
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


def save_checkpoints(tags_dict: dict, error_set: set):
    CKPT_V3_DIR.mkdir(parents=True, exist_ok=True)
    save_pickle_atomic(CKPT_V3_DIR / "tags_dict-v3.p",   tags_dict)
    save_pickle_atomic(CKPT_V3_DIR / "error_apps-v3.p",  error_set)


def fetch_steamspy_tags(appid: int):
    """
    Consulta a API do SteamSpy e retorna o dict de tags.

    Retorna:
        dict  → {'Action': 1500, 'Indie': 900, ...}
        None  → app não encontrado ou sem tags
        'RATE_LIMIT' → recebeu HTTP 429
    """
    url = f"https://steamspy.com/api.php?request=appdetails&appid={appid}"
    try:
        resp = requests.get(url, timeout=15)

        if resp.status_code == 429:
            return "RATE_LIMIT"

        if resp.status_code != 200:
            return None

        data = resp.json()

        # SteamSpy retorna {} ou {"appid": 999999} para apps inexistentes
        if not data or data.get("appid") != appid:
            return None

        tags = data.get("tags", {})
        return tags if isinstance(tags, dict) and tags else None

    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print_log("Iniciando coleta V3 — Tags de Jogadores via SteamSpy")
    print_log("Para pausar com segurança: pressione CTRL+C UMA VEZ e aguarde.")

    # ── Carregar base V2 ──────────────────────────────────────
    v2_path = CKPT_V2_DIR / "apps_dict-v2.p"
    if not v2_path.exists():
        print_log(f"❌ Arquivo V2 não encontrado em: {v2_path}")
        print_log("Execute o api-atomica-v2.py primeiro.")
        return

    print_log(f"Carregando base V2 ({v2_path.name})... pode demorar alguns minutos.")
    app_data_v2 = load_pickle(v2_path)
    print_log(f"✔ {len(app_data_v2):,} apps carregados do V2.")

    # Pegar apenas os jogos (type == 'game') — não precisamos de tags de DLCs
    game_ids = [appid for appid, d in app_data_v2.items() if d.get("type") == "game"]
    print_log(f"  → {len(game_ids):,} são do tipo 'game' (foco da coleta).")

    # ── Carregar progresso V3 (se existir) ────────────────────
    tags_dict  = {}
    error_apps = set()

    tags_path = CKPT_V3_DIR / "tags_dict-v3.p"
    err_path  = CKPT_V3_DIR / "error_apps-v3.p"

    if tags_path.exists():
        tags_dict = load_pickle(tags_path)
        print_log(f"✔ Progresso V3 carregado: {len(tags_dict):,} apps já têm tags.")
    if err_path.exists():
        error_apps = load_pickle(err_path)
        print_log(f"  → {len(error_apps):,} apps marcados como erro anteriormente.")

    # ── Montar fila de pendentes ──────────────────────────────
    already_done = set(tags_dict.keys()) | error_apps
    to_process   = [appid for appid in game_ids if appid not in already_done]
    queue        = deque(to_process)

    print_log(f"Apps pendentes para coletar tags: {len(queue):,}")

    if not queue:
        print_log("✅ Todos os apps já foram processados! Nada a fazer.")
        return

    # ── Estimativa de tempo ───────────────────────────────────
    est_hours = (len(queue) * DELAY_BETWEEN_REQUESTS) / 3600
    print_log(f"Estimativa de tempo (aprox.): {est_hours:.1f} horas")

    # ── Loop de coleta ────────────────────────────────────────
    counter      = 0
    total_done   = len(already_done)

    try:
        while queue:
            appid = queue.popleft()

            result = fetch_steamspy_tags(appid)

            if result == "RATE_LIMIT":
                print_log(f"⚠️ RATE LIMIT do SteamSpy. Pausando {DELAY_RATE_LIMIT}s...")
                queue.appendleft(appid)
                time.sleep(DELAY_RATE_LIMIT)
                continue

            if result is None:
                # App não encontrado no SteamSpy — salva como sem tags (dict vazio)
                tags_dict[appid] = {}
                error_apps.add(appid)
            else:
                tags_dict[appid] = result

            total_done += 1
            counter    += 1

            # Log de progresso a cada 50 apps
            if counter % 50 == 0:
                pct = total_done / len(game_ids) * 100
                print_log(f"  Progresso: {total_done:,}/{len(game_ids):,} ({pct:.1f}%) "
                          f"| Último App ID: {appid}")

            # Salvar checkpoint a cada N apps
            if counter >= CHECKPOINT_INTERVAL:
                save_checkpoints(tags_dict, error_apps)
                print_log(f"💾 Checkpoint V3 salvo! ({len(tags_dict):,} apps com tags)")
                counter = 0

            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        print_log("\n⚠️ COLETA INTERROMPIDA PELO USUÁRIO (Ctrl+C). SALVANDO DADOS...")
        save_checkpoints(tags_dict, error_apps)
        print_log(f"✅ PROGRESSO SALVO: {len(tags_dict):,} apps com tags.")
        print_log("Pode fechar o terminal com segurança.")
        sys.exit(0)

    except Exception:
        print_log(f"\n❌ Erro inesperado:\n{traceback.format_exc()}")
        save_checkpoints(tags_dict, error_apps)
        print_log("Dados salvos antes do crash.")

    # ── Salvamento final ──────────────────────────────────────
    save_checkpoints(tags_dict, error_apps)
    print_log(f"\n✅ Coleta V3 finalizada!")
    print_log(f"  Apps com tags coletadas:  {len(tags_dict):,}")
    print_log(f"  Apps sem tags (SteamSpy): {len(error_apps):,}")
    print_log(f"  Checkpoints salvos em:    {CKPT_V3_DIR}")
    print_log("Próximo passo: execute steam-analise-v3.py para mesclar tags ao CSV.")


if __name__ == "__main__":
    main()
