"""
api-atomica-v2.py
==================
Coleta V2: metadados (appdetails) + avaliações exatas (appreviews).

O que este script faz:
  - Baixa a lista completa de app IDs cadastrados na Steam (IStoreService/GetAppList)
  - Para cada app, consulta o endpoint appdetails (mesmo endpoint usado na V1)
  - Para cada app com appdetails válido, consulta também o endpoint appreviews
    e anexa o resumo agregado das avaliações em 'exact_reviews'
  - Salva o resultado em checkpoints_v2/ com salvamento atômico

Por que appreviews?
  O campo 'recommendations.total' (appdetails, usado na V1) não é populado
  pela Steam para jogos abaixo de um limiar de avaliações não documentado
  publicamente. Na coleta V1 isso deixou 86,7% dos jogos sem esse campo —
  não porque não tivessem avaliações, mas porque ficaram abaixo do limiar de
  visibilidade da API (ver TCC, Seção 3.1 e Tabela 3.2). É um viés de seleção
  estrutural da API, não uma característica real dos dados.

  O endpoint appreviews (bloco 'query_summary') retorna o total real de
  avaliações para QUALQUER app, incluindo 0 de forma explícita quando o jogo
  realmente não tem nenhuma avaliação — sem o limiar de visibilidade do
  appdetails. É por isso que 'steam-analise-v2.py' usa 'exact_reviews' como
  fonte de verdade para 'reviews_total' e mantém 'recommendations.total'
  apenas como campo legado/fallback.

Como pausar com segurança:
  Pressione CTRL + C UMA VEZ e aguarde a mensagem de confirmação.

Como retomar:
  Execute o script novamente. Ele carregará o checkpoint do V2 e continuará
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

# Necessária apenas para listar os app IDs (IStoreService/GetAppList).
# Prefira definir via variável de ambiente a deixar a chave hardcoded no arquivo.
CHAVE_API_STEAM = os.environ.get("STEAM_API_KEY", "COLOQUE_SUA_CHAVE_AQUI")

DELAY_BETWEEN_REQUESTS = 1.5     # intervalo entre requisições de appdetails (mesmo ritmo da V1)
DELAY_APPREVIEWS       = 1.0     # intervalo entre o appdetails e o appreviews do mesmo app
DELAY_RATE_LIMIT       = 60      # segundos de pausa ao receber HTTP 429
CHECKPOINT_INTERVAL    = 100     # salvar a cada N apps processados


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


def save_checkpoints(apps_dict: dict, excluded_apps: set, error_apps: set):
    CKPT_V2_DIR.mkdir(parents=True, exist_ok=True)
    save_pickle_atomic(CKPT_V2_DIR / "apps_dict-v2.p",      apps_dict)
    save_pickle_atomic(CKPT_V2_DIR / "excluded_apps-v2.p",  excluded_apps)
    save_pickle_atomic(CKPT_V2_DIR / "error_apps-v2.p",     error_apps)


def get_all_app_id():
    """Baixa a lista completa de app IDs cadastrados na Steam (paginada)."""
    apps_ids = []
    last_appid = 0
    print_log("Baixando lista atualizada de jogos da Steam...")

    while True:
        url = (f"https://api.steampowered.com/IStoreService/GetAppList/v1/"
               f"?key={CHAVE_API_STEAM}&max_results=50000&last_appid={last_appid}")
        try:
            req = requests.get(url, timeout=15)
            if req.status_code != 200:
                print_log(f"Falhou em pegar a listagem. Erro HTTP: {req.status_code}")
                break
            data = req.json()
            apps_data = data.get("response", {}).get("apps", [])
            if not apps_data:
                break
            for app in apps_data:
                if app.get("name"):
                    apps_ids.append(app["appid"])
            if data.get("response", {}).get("have_more_results"):
                last_appid = data["response"]["last_appid"]
            else:
                break
        except Exception as e:
            print_log(f"Erro ao buscar IDs: {e}. Tentando novamente em 10s...")
            time.sleep(10)
    return apps_ids


def fetch_appdetails(appid: int):
    """
    Consulta o endpoint appdetails.

    Retorna:
        dict            → dados do app (appdetails['data'])
        None            → app inexistente/indisponível (success=False ou HTTP != 200/429)
        'RATE_LIMIT'    → recebeu HTTP 429
        'REQUEST_ERROR' → falha de rede, timeout ou JSON inválido
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        resp = requests.get(url, timeout=10)
    except Exception:
        return "REQUEST_ERROR"

    if resp.status_code == 429:
        return "RATE_LIMIT"
    if resp.status_code != 200:
        return None

    try:
        payload = resp.json().get(str(appid), {})
    except Exception:
        return "REQUEST_ERROR"

    if not payload.get("success", False):
        return None

    return payload.get("data", {})


def fetch_exact_reviews(appid: int):
    """
    Consulta o endpoint appreviews e retorna o bloco 'query_summary'.

    'num_per_page=0' evita baixar o texto das avaliações — só precisamos do
    resumo agregado (total_reviews, total_positive, total_negative, etc.).
    'language=all' e 'purchase_type=all' garantem que o total reflete TODAS
    as avaliações do jogo, e não um subconjunto filtrado por idioma/origem.

    Retorna:
        dict          → query_summary (sempre presente, mesmo com 0 avaliações)
        None          → falha na consulta (rede, HTTP != 200, success != 1)
        'RATE_LIMIT'  → recebeu HTTP 429
    """
    url = (f"https://store.steampowered.com/appreviews/{appid}"
           f"?json=1&language=all&purchase_type=all&num_per_page=0")
    try:
        resp = requests.get(url, timeout=10)
    except Exception:
        return None

    if resp.status_code == 429:
        return "RATE_LIMIT"
    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    if data.get("success") != 1:
        return None

    return data.get("query_summary")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print_log("Iniciando coleta V2 — appdetails + appreviews (exact_reviews)")
    print_log("Para pausar com segurança: pressione CTRL+C UMA VEZ e aguarde.")

    if CHAVE_API_STEAM == "COLOQUE_SUA_CHAVE_AQUI":
        print_log("❌ Defina sua chave da Steam Web API na variável de ambiente STEAM_API_KEY.")
        return

    apps_dict, excluded_apps, error_apps = {}, set(), set()

    dict_path = CKPT_V2_DIR / "apps_dict-v2.p"
    exc_path  = CKPT_V2_DIR / "excluded_apps-v2.p"
    err_path  = CKPT_V2_DIR / "error_apps-v2.p"

    if dict_path.exists():
        print_log(f"Carregando checkpoint existente ({dict_path.name})... pode demorar alguns minutos.")
        apps_dict = load_pickle(dict_path)
        print_log(f"✔ Checkpoint carregado: {len(apps_dict):,} apps já coletados.")
    if exc_path.exists():
        excluded_apps = load_pickle(exc_path)
        print_log(f"  → {len(excluded_apps):,} apps marcados como excluídos anteriormente.")
    if err_path.exists():
        error_apps = load_pickle(err_path)
        print_log(f"  → {len(error_apps):,} apps marcados como erro anteriormente.")

    all_app_ids = get_all_app_id()
    print_log(f"Total de apps listados na Steam: {len(all_app_ids):,}")

    already_done = set(apps_dict.keys()) | excluded_apps | error_apps
    queue = deque(appid for appid in all_app_ids if appid not in already_done)
    print_log(f"Apps pendentes para coletar: {len(queue):,}")

    if not queue:
        print_log("✅ Todos os apps já foram processados! Nada a fazer.")
        return

    counter = 0
    try:
        while queue:
            appid = queue.popleft()

            details = fetch_appdetails(appid)

            if details == "RATE_LIMIT":
                print_log(f"⚠️ RATE LIMIT (appdetails). Pausando {DELAY_RATE_LIMIT}s...")
                queue.appendleft(appid)
                time.sleep(DELAY_RATE_LIMIT)
                continue

            if details == "REQUEST_ERROR":
                error_apps.add(appid)
                time.sleep(5)
                continue

            if details is None:
                excluded_apps.add(appid)
                time.sleep(DELAY_BETWEEN_REQUESTS)
                continue

            details["appid"] = appid
            time.sleep(DELAY_APPREVIEWS)

            reviews = fetch_exact_reviews(appid)
            if reviews == "RATE_LIMIT":
                print_log(f"⚠️ RATE LIMIT (appreviews). Pausando {DELAY_RATE_LIMIT}s e tentando 1x...")
                time.sleep(DELAY_RATE_LIMIT)
                reviews = fetch_exact_reviews(appid)
                if reviews == "RATE_LIMIT":
                    reviews = None

            details["exact_reviews"] = reviews if isinstance(reviews, dict) else None
            apps_dict[appid] = details

            print_log(f"✔ App ID {appid} — {details.get('name', '?')}")

            counter += 1
            if counter >= CHECKPOINT_INTERVAL:
                save_checkpoints(apps_dict, excluded_apps, error_apps)
                print_log(f"💾 Checkpoint V2 salvo! ({len(apps_dict):,} apps coletados)")
                counter = 0

            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        print_log("\n⚠️ COLETA INTERROMPIDA PELO USUÁRIO (Ctrl+C). SALVANDO DADOS...")
        save_checkpoints(apps_dict, excluded_apps, error_apps)
        print_log(f"✅ PROGRESSO SALVO: {len(apps_dict):,} apps coletados.")
        print_log("Pode fechar o terminal com segurança.")
        sys.exit(0)

    except Exception:
        print_log(f"\n❌ Erro inesperado:\n{traceback.format_exc()}")
        save_checkpoints(apps_dict, excluded_apps, error_apps)
        print_log("Dados salvos antes do crash.")
        return

    save_checkpoints(apps_dict, excluded_apps, error_apps)
    print_log("\n✅ Coleta V2 finalizada!")
    print_log(f"  Apps coletados: {len(apps_dict):,}")
    print_log(f"  Apps excluídos: {len(excluded_apps):,}")
    print_log(f"  Apps com erro:  {len(error_apps):,}")
    print_log("Próximo passo: execute steam-analise-v2.py para gerar os CSVs.")


if __name__ == "__main__":
    main()
