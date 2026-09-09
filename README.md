# Análise Preditiva da Popularidade de Jogos na Steam Utilizando Redes Neurais

Pipeline de coleta, limpeza, análise exploratória e modelagem por trás do meu TCC do Bacharelado em
Estatística (UFRGS): prever a popularidade de jogos na Steam a partir de características do próprio
jogo (gênero, preço, plataformas, categorias, texto da descrição), usando `reviews_total` como proxy
de popularidade.

**Discente:** Davi Augusto Farinela da Silva
**Orientador:** Prof. Dr. João Henrique Ferreira Flores

## Status

Coleta, limpeza e análise exploratória estão fechadas (`steam-eda-v2.ipynb`). A modelagem está em
andamento em `steam-modelagem-v2.ipynb`: já rodei o modelo de barreira para tratar os jogos sem
avaliação, construí as variáveis de exposição e de histórico da desenvolvedora, e comparei GLM
Poisson com Binomial Negativa. A rede neural em si — uma TextCNN sobre as descrições dos jogos — é a
próxima etapa e ainda não foi construída.

O texto do TCC ainda descreve a versão antiga da coleta (V1); reescrever a metodologia para a V2
está pendente (ver [Coleta V1 vs. V2](#coleta-v1-vs-v2)).

## A base

| | |
|---|---|
| Apps coletados | 171.769 (99,998% `type == "game"`) |
| Jogos na base curada | 118.596 |
| Data da coleta | 10/08/2026 |
| Jogos com zero avaliação | 20,6% |
| `reviews_total` ausente | 0,3% (falhas de requisição) |

A diferença entre coletado e curado são, quase inteiramente, **jogos ainda não lançados**: dos 53.173
descartados, 52.802 (99,3%) estão marcados como `coming_soon`. Só 371 jogos já lançados se perdem,
por data ausente ou por não ter bloco de preço.

## Estrutura do repositório

```
.
├── scripts/                        # Todos os scripts do pipeline, num nível só
│   ├── api-atomica.py              # Coletor V1 (appdetails só) — referência histórica, não usar
│   ├── api-atomica-v2.py           # Coletor V2 (appdetails + appreviews) — versão em uso
│   ├── api-atomica-v3.py           # Coletor V3 (+ tags de jogador via SteamSpy)
│   ├── api-atomica-v4.py           # Coletor V4 (Linux/ProtonDB) — pronto, ainda não rodado
│   ├── steam-analise-v2.py         # Limpeza: pickle V2 -> CSV curado
│   ├── steam-analise.py            # Limpeza: pickle V1 -> CSV (referência histórica)
│   └── steam-features-modelagem.py # Features extras do checkpoint + textos das descrições
│
├── steam-pickle-csv.ipynb   # Versão documentada da limpeza V2
├── steam-eda-v2.ipynb       # Análise exploratória
├── steam-modelagem-v2.ipynb # Modelagem: barreira, exposição, GLM Poisson vs Binomial Negativa
│
├── legado/                 # Scripts originais do orientador — referência, não mexer
├── archive/                # Notebooks de EDA superados, mantidos só por histórico
├── requirements.txt
│
├── docs/                    # (gitignored) PDF do TCC e material de leitura
├── checkpoints/             # (gitignored) pickles brutos da coleta V1
├── checkpoints_v2/          # (gitignored) pickles brutos da coleta V2 — ≈2,2 GB
├── checkpoints_v3/          # (gitignored) tags de jogador do SteamSpy
├── checkpoints_v4/          # (gitignored) dados do ProtonDB, se/quando rodar
└── data/                    # (gitignored) CSVs curados: steam-dados-v2.csv, steam-jogos-v2.csv,
                             # steam-features-v2.csv e steam-textos-v2.csv (descrições, ≈275 MB)
```

**Sobre os caminhos.** Todo script em `scripts/` se ancora do mesmo jeito —
`BASE_DIR = Path(__file__).resolve().parent.parent`, que cai na raiz do repositório — então funciona
independente de onde você chamar. A regra é uma só justamente porque a versão anterior (scripts
espalhados entre a raiz e uma pasta `eda/`) já produziu três bugs de caminho silenciosos. Script novo
vai em `scripts/`, com essa mesma âncora; se algum dia virar subpasta, a profundidade da âncora muda
junto.

Os notebooks ficam na raiz de propósito: o working directory do Jupyter acompanha a localização do
próprio notebook, e eles leem `data/...` e `checkpoints_v2/...` assumindo que rodam a partir da raiz.

`checkpoints*/` e `data/` não vão pro Git: são grandes (a coleta V2 sozinha passa de 2 GB em pickle)
e 100% regeneráveis rodando o pipeline. Isso quer dizer que quem clonar o repositório precisa rodar
a coleta e a limpeza antes de ter os CSVs pra abrir os notebooks.

## Ambiente

Python 3.14, sem virtualenv (pacotes instalados globalmente). Para instalar as dependências:

```
python -m pip install -r requirements.txt
```

O coletor V2 precisa de uma chave da Steam Web API na variável de ambiente `STEAM_API_KEY` (usada só
para listar os app IDs via `IStoreService/GetAppList`) — sem ela, o script recusa a rodar em vez de
usar uma chave hardcoded.

## Rodando o pipeline

Cada etapa é um script ou notebook independente, executado manualmente e em ordem:

```
python scripts/api-atomica-v2.py          # coleta V2 -> checkpoints_v2/ (demorado: horas)
python scripts/api-atomica-v3.py          # enriquecimento com tags do SteamSpy -> checkpoints_v3/
python scripts/steam-analise-v2.py        # limpeza: pickle -> CSV -> data/
jupyter notebook steam-pickle-csv.ipynb   # versão documentada da limpeza
jupyter notebook steam-eda-v2.ipynb       # análise exploratória
python scripts/steam-features-modelagem.py # features extras -> data/steam-features-v2.csv + steam-textos-v2.csv
jupyter notebook steam-modelagem-v2.ipynb # modelagem: barreira + GLM Poisson vs Binomial Negativa
```

Os coletores (`api-atomica*.py`) demoram horas e são seguros de interromper: `CTRL+C` uma vez e
aguardar a mensagem de confirmação salva um checkpoint atômico; rodar o script de novo retoma de
onde parou, sem repetir trabalho.

`api-atomica.py` (V1) fica só como referência histórica. `api-atomica-v4.py` (ProtonDB) está pronto
e testado, mas decidi não rodar por enquanto — são ~118 mil consultas, mais de um dia de coleta —
fica como possível extensão futura, não como parte do pipeline atual.

## Onde a modelagem está

Tudo abaixo sai de `steam-modelagem-v2.ipynb`.

**Desenho experimental.** Divisão temporal, não aleatória: treino com jogos lançados até 08/2024
(80.788) e teste entre 08/2024 e 08/2025 (19.682). Sorteio aleatório colocaria jogos de 2025
prevendo jogos de 2019 e contaminaria a variável de histórico da desenvolvedora. Exijo 12 meses de
mercado: 86% dos jogos do último mês completo da coleta têm zero avaliação, e isso é censura, não
ausência de público.

**Modelo de barreira (*hurdle*).** Separa "o jogo recebe alguma avaliação?" de "recebendo, quantas?",
em vez de descartar os 20,6% de zeros.

| Parte 1 — recebe avaliação? | AUC |
|---|---|
| Regressão logística | 0,879 |
| Gradient boosting | 0,899 |

| Parte 2 — quantas, dado que recebeu | R² |
|---|---|
| Ridge | 0,42 |
| Random Forest | 0,53 |
| Gradient boosting | 0,56 |

**Poisson vs. Binomial Negativa.** A Poisson com offset de exposição dá Pearson χ²/gl = 36.737 (1,0
seria equidispersão) e 52 dos 53 coeficientes com p exatamente 0 — superdispersão grosseira. A
Binomial Negativa (α = 3,7136, estimado por máxima verossimilhança) rejeita a Poisson por teste de
razão de verossimilhanças, com erros-padrão cerca de 80× maiores; três variáveis que pareciam
altamente significativas deixam de ser.

**Dois resultados que valem registro.** Ser gratuito é desvantagem nas *duas* etapas do modelo de
barreira (coeficiente −0,83 e −0,61; mediana condicional de 7 avaliações contra 18 dos pagos) — eu
esperava sinais opostos e estava errado. E o histórico da desenvolvedora (`dev_log_rev_ant`,
construído só com lançamentos estritamente anteriores) é a 2ª variável mais importante do modelo: é
o que consegui usar como proxy do burburinho de streamer e rede social, que não observo.

**Duas perguntas ainda abertas**, que são as que levo pro orientador:

1. *A exposição entra como offset ou como coeficiente livre?* Estimado livremente, o coeficiente de
   log(exposição) é 0,7062 (IC 95% [0,677; 0,736]), o que rejeita a restrição de offset — a
   acumulação é sublinear. Só que a versão com offset prevê melhor fora da amostra (R² 0,17 contra
   0,03).
2. *`cat_steam_trading_cards` é pós-tratamento.* É a variável mais importante do modelo (0,235), mas
   a Valve concede cartas a jogos que já são populares, então ela está do lado errado da causalidade.

## Coleta V1 vs. V2

O principal ajuste da etapa de coleta. A versão original (V1) lia `recommendations.total` do endpoint
`appdetails`, campo que a Steam simplesmente omite abaixo de um limiar de reviews não documentado —
isso deixava 86,7% de `reviews_total` faltante, e **não** era falta de reviews de verdade, era a API
não informando o dado. A V2 corrige isso consultando o endpoint `/appreviews` diretamente, que
devolve um total real para todo app, inclusive `total_reviews: 0` explícito para quem realmente não
tem nenhuma avaliação. O dado faltante cai pra 0,3%. O detalhamento completo está no início do
`steam-eda-v2.ipynb`.

`recommendations_total` continua na CSV curada como coluna legada (82,1% ausente), mas não entra como
variável nem como contagem de referência — serve só como evidência de por que a coleta foi refeita.

## Um problema conhecido: preço

`api-atomica-v2.py` chama `appdetails` sem fixar `cc=BR`, então parte do catálogo voltou precificada
em outra moeda: 2.008 apps dos 101.072 com bloco de preço (2,0%), espalhados por 26 moedas. A limpeza
(`steam-analise-v2.py`) divide o valor por 100 e chama de `price_brl` sem olhar
`price_overview.currency`, então esses viram números errados na CSV — Atomic Heart aparece como
"R$ 5.490" porque o payload traz Rp 549.000.

Nada se perdeu na coleta (a moeda estava salva no checkpoint o tempo todo) e a correção é offline. A
seção 2 do `steam-modelagem-v2.ipynb` já corrige e trabalha só com os preços em BRL, e a diferença
não é cosmética: a correlação entre preço e `log_reviews` sai de 0,02 para 0,19 — o preço deixa de
ser o pior preditor numérico e passa a estar entre os melhores. O conserto na origem
(`steam-analise-v2.py` e `steam-pickle-csv.ipynb`) ainda não foi feito, então quem regerar a CSV do
zero volta a ter a coluna errada.
