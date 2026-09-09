from collections import deque
from datetime import datetime
from pathlib import Path
import os
import time
import requests
import pickle
import traceback

def print_log(*args):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ", end="")
    print(*args)

def get_all_app_id():
    # --- COLE A SUA CHAVE DA API DA STEAM AQUI DENTRO DAS ASPAS ---
    CHAVE_API = "79B27F6453DF41A0BD7B94CC8C56618A" 
    
    apps_ids = []
    last_appid = 0
    print_log("Baixando lista atualizada de jogos da Steam...")

    while True:
        url = f"https://api.steampowered.com/IStoreService/GetAppList/v1/?key={CHAVE_API}&max_results=50000&last_appid={last_appid}"
        
        try:
            req = requests.get(url, timeout=15)
            
            if req.status_code != 200:
                print_log(f"Falhou em pegar a listagem. Erro HTTP: {req.status_code}")
                break
            data = req.json()
            apps_data = data.get('response', {}).get('apps', [])
            
            if not apps_data:
                break
            
            for app in apps_data:
                if app.get('name'):
                    apps_ids.append(app['appid'])
            
            if data.get('response', {}).get('have_more_results'):
                last_appid = data['response']['last_appid']
            else:
                break
        except Exception as e:
            print_log(f"Erro ao buscar IDs: {e}. Tentando novamente em 10s...")
            time.sleep(10)
    return apps_ids

def save_pickle_atomic(final_path: Path, obj):
    """
    SALVAMENTO ATÔMICO: Previne corrupção de dados (EOFError).
    Salva primeiro em um arquivo temporário e depois renomeia.
    """
    temp_path = final_path.with_suffix('.tmp')
    try:
        with open(temp_path, 'wb') as handle:
            pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp_path, final_path)
    except Exception as e:
        print_log(f"Erro ao salvar arquivo {final_path}: {e}")

def load_pickle(path_to_load: Path) -> dict:
    with open(path_to_load, "rb") as handle:
        return pickle.load(handle)

def save_checkpoints(checkpoint_folder, apps_dict, excluded_apps, error_apps):
    if not checkpoint_folder.exists():
        checkpoint_folder.mkdir(parents=True)
    
    save_pickle_atomic(checkpoint_folder / 'apps_dict-ckpt.p', apps_dict)
    save_pickle_atomic(checkpoint_folder / 'excluded_apps_list-ckpt.p', excluded_apps)
    save_pickle_atomic(checkpoint_folder / 'error_apps_list-ckpt.p', error_apps)

def main():
    print_log(f"Iniciando coleta definitiva da Steam (PID: {os.getpid()})")
    
    apps_dict, excluded_apps_list, error_apps_list = {}, [], []
    all_app_ids = get_all_app_id()
    print_log(f'Total de apps listados na Steam: {len(all_app_ids)}')

    checkpoint_folder = Path(__file__).resolve().parent.parent / 'checkpoints'
    if not checkpoint_folder.exists():
        checkpoint_folder.mkdir(parents=True)

    dict_path = checkpoint_folder / 'apps_dict-ckpt.p'
    exc_path = checkpoint_folder / 'excluded_apps_list-ckpt.p'
    err_path = checkpoint_folder / 'error_apps_list-ckpt.p'

    if dict_path.exists():
        apps_dict = load_pickle(dict_path)
        print_log(f'Checkpoint carregado: {len(apps_dict)} jogos já coletados.')
    if exc_path.exists():
        excluded_apps_list = load_pickle(exc_path)
    if err_path.exists():
        error_apps_list = load_pickle(err_path)

    ids_processados = set(apps_dict.keys()) | set(excluded_apps_list) | set(error_apps_list)
    all_app_ids = set(all_app_ids) - ids_processados
    
    apps_remaining_deque = deque(all_app_ids)
    print_log('Número de apps restantes para coletar:', len(apps_remaining_deque))

    i = 0
    try:
        while len(apps_remaining_deque) > 0:
            appid = apps_remaining_deque.popleft()

            try:
                appdetails_req = requests.get(f"https://store.steampowered.com/api/appdetails?appids={appid}", timeout=10)

                if appdetails_req.status_code == 200:
                    appdetails = appdetails_req.json().get(str(appid), {})
                elif appdetails_req.status_code == 429:
                    print_log(f'Rate Limit. Pausa de 60 seg.')
                    apps_remaining_deque.appendleft(appid)
                    time.sleep(60)
                    continue
                else:
                    error_apps_list.append(appid)
                    continue
            except:
                error_apps_list.append(appid)
                time.sleep(5)
                continue

            if not appdetails.get('success', False):
                excluded_apps_list.append(appid)
                time.sleep(1.5)
                continue

            appdetails_data = appdetails.get('data', {})
            appdetails_data['appid'] = appid
            apps_dict[appid] = appdetails_data
            
            print_log(f"Sucesso App ID: {appid}")

            i += 1
            if i >= 100:
                save_checkpoints(checkpoint_folder, apps_dict, excluded_apps_list, error_apps_list)
                print_log(">>> Checkpoints salvos com segurança atômica! <<<")
                i = 0
            
            time.sleep(1.5)

    except KeyboardInterrupt:
        print_log("\nColeta interrompida manualmente! Salvando progresso...")
        save_checkpoints(checkpoint_folder, apps_dict, excluded_apps_list, error_apps_list)
        print_log("Progresso salvo. Saindo com segurança.")

if __name__ == '__main__':
    main()