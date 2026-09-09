'''
O objetivo aqui é extrair as informações que preciso
do arquivo JSON e criar um csv'
'''

'''
## mais testes
## Exemplinho de teste apenas
appdetails_req = requests.get(f"https://store.steampowered.com/api/appdetails?appids=2555430")
appdetails_req
if appdetails_req.status_code == 200:
    appdetails = appdetails_req.json()
    appdetails = appdetails[str(2555430)]

appdetails_data = appdetails['data']
## ENTENDI!!!!
## Exemplos
## isso só vale quando eu tenho as amostras internas, iid
## appdetails['sucess']
## appdetails['data']['recommendations']['total']
## e por aí vai...

'''

## carrega os pacotes necessários
#from collections import deque
from datetime import datetime
from pathlib import Path
import pandas as pd
import os
#import time
import requests
import json
import pickle
from itertools import islice
#import traceback

## VAMOS NESSA!
with open("/home/joao/R/steam/python/steam-checkpoints/apps_dict-ckpt-fin.p", "rb") as file:
    app_data = pickle.load(file)


len(app_data)
type(app_data)
#app_data[:1]

# indice das entradas, outer index, oid
oid = next(iter(app_data))
# indice interno, lista cada aplicativo, inter index, iid 
iid = app_data[oid]
print(iid)
type(iid)
print(iid.keys())
print(iid['name'])

oid = next(islice(app_data, 2900, None))
print(app_data[oid])

appdetails = app_data[oid]
appdetails['name']
appdetails['type']
appdetails['recommendations']['total']
appdetails['categories']
appdetails['genres']
appdetails['content_descriptors']
appdetails['is_free']
appdetails['price_overview']
appdetails['ratings']
appdetails['recommendations']
appdetails['required_age']
appdetails['platforms']
appdetails['achievements']
appdetails['release_date']
appdetails['content_descriptors']
appdetails['ratings']

print(sorted(appdetails.keys()))

#sample_inner_entries = {k: amostra[k] for k in list(amostra)[:5]}
#print(sample_inner_entries)

# Print the extracted data
#print(first_inner_entries)

# Extract 'name' values for each entry
#df = pd.DataFrame({"tipo": [inner_data["type"] for inner_data in app_data.values()]})

# Display DataFrame
#print(df)

# Collect all unique keys in inner dictionaries
#all_keys = {key for entry in app_data.values() for key in entry.keys()}

# Print the list of keys
#print(sorted(all_keys))  # Sorted for readability

# Extract 'name' values for each entry
#dados = pd.DataFrame({"name": [inner_data["name"] for inner_data in app_data.values()]})
#dados2 = pd.DataFrame({"appid": [inner_data["appid"] for inner_data in app_data.values()]})
#dados['appid'] = dados2['appid'].values
# Display DataFrame
#print(dados.head())
#dados.shape

### Outra tentativa
#dados = pd.DataFrame([
#    {
#        "name": d["name"],
#        "review": d.get("recommendations", {}).get("total")
#    }
#    for d in app_data.values()
#])

#print(dados.head())

# Extract just the genre descriptions
#def extract_genres(entry):
#    genres = entry.get("genres", [])
#    return [g.get("description") for g in genres if isinstance(g, dict)]

### LISTAR TODOS OS TIPOS DE CATEGORIAS
unique_cat = set()

for app_id, app_details in app_data.items():
    categ = app_details.get('categories', [])
    for categ in categ:
        description = categ.get('description')
        if description:
            unique_cat.add(description)


print(unique_cat)

categ_list = sorted(unique_cat)
print(categ_list)

### FILTRO
[word for word in categ_list if 'lan' in word.lower()]

# 'Steam Trading Cards'
# 'Steam Achievements'
# 'Full controller support'
# 'Steam Workshop'

### CONTAGEM
count = 0
for d in app_data.values():
    genres = d.get("categories", [])
    if any(g.get("description") == "Workshop Steam" for g in genres):
        count += 1

print(f"Entries with 'Workshop Steam': {count}")


### LISTAR OS TIPOS DE GENEROS QUE EXISTEM
unique_genres = set()

for app_id, app_details in app_data.items():
    genres = app_details.get('genres', [])
    for genre in genres:
        description = genre.get('description')
        if description:
            unique_genres.add(description)


print(unique_genres)

### LISTAR OS TIPOS DE APP QUE EXISTEM
all_types = set()

for app_details in app_data.values():
    app_type = app_details.get('type')
    if app_type:
        all_types.add(app_type)

# Optional: sort
type_list = sorted(all_types)
print(type_list)

### LISTAR TODOS OS GENEROS APENAS QUANDO EH JOGO
genres_for_games = set()

for app_details in app_data.values():
    if app_details.get('type') == 'game':
        for genre in app_details.get('genres', []):
            description = genre.get('description')
            if description:
                genres_for_games.add(description)

# Optional: sort
genres_list = sorted(genres_for_games)
print(genres_list)

# extrair apenas os gêneros que me interessam
#def has_genre(genre_list, genre_name):
#    return int(any(g.get('description') == genre_name for g in genre_list))

# Example: Check for 'Indie'
#dados['indie'] = app_data['genres'].apply(lambda g: has_genre(g, 'Indie'))


# GENEROS EM COLUNAS BINARIAS
target_genres = {'Indie', 'Simulation', 'Early Access'}

# Build rows for a DataFrame
rows = []

for app_id, app_details in app_data.items():
    row = {
        'appid': app_id,
        'type': app_details.get('type')
    }
    genres = {g.get('description') for g in app_details.get('genres', [])}
    
    # Add binary values for each target genre
    for genre in target_genres:
        row[f'genre_{genre}'] = genre in genres
    
    rows.append(row)

# Create DataFrame
df = pd.DataFrame(rows)

# Optional: see the result
print(df.head())


############## TESTE QUASE FINAL
# Selected genres for binary flags
target_genres = {'Indie', 'Simulation', 'Early Access'}

# Build the full dataset
df = pd.DataFrame([
    {
        "id": app_id,
        "type": d.get("type"),
        "review": d.get("recommendations", {}).get("total"),
        **{
            f"genre_{genre}": any(g.get("description") == genre for g in d.get("genres", []))
            for genre in target_genres
        },
        "name": d.get("name")
    }
    for app_id, d in app_data.items()
])

# Optional: see the result
print(df.head())

#### QUESTAO DAS DATAS
from datetime import datetime

def parse_release_date(d):
    raw_date = d.get("release_date", {}).get("date", "")
    try:
        # Try parsing the raw Steam-like format, e.g. '24 Oct, 2023'
        dt = datetime.strptime(raw_date, "%d %b, %Y")
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return None  # Or you could return raw_date if you prefer fallback

# Add to your DataFrame build
df = pd.DataFrame([
    {
        "id": app_id,
        "type": d.get("type"),
        "review": d.get("recommendations", {}).get("total"),
        **{
            f"genre_{genre}": any(g.get("description") == genre for g in d.get("genres", []))
            for genre in {'Indie', 'Simulation', 'Early Access'}
        },
        "release_date": parse_release_date(d),  # Add formatted date here
        "name": d.get("name")  # Keep 'name' last
    }
    for app_id, d in app_data.items()
])

# Optional: see the result
print(df.head())

## CASO SEJA NECESSARIO EXTRAIR O ANO/MES
#df['release_date'] = pd.to_datetime(df['release_date'], errors='coerce')
# Extract parts
#df['release_year'] = df['release_date'].dt.year
#df['release_month'] = df['release_date'].dt.month
#df['release_day'] = df['release_date'].dt.day
teste = pd.to_datetime(df['release_date'][32], errors='coerce')
teste.year
teste.month
teste.day

