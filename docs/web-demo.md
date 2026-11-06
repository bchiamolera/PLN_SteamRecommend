# Steam Atlas: demonstração web local

A API Django fornece dados preparados para uma interface React. O sistema oferece
Word2Vec como referência e quatro métodos experimentais de comparação, além de
pontos positivos e negativos extraídos de reviews.

Toda a documentação explicativa está em pt-BR. Comandos, opções, prompts, mensagens
do programa e exemplos de código usam en-US. Nomes técnicos e trechos originais do
catálogo/reviews são preservados para manter a rastreabilidade dos experimentos.

Consulte também [algoritmos e justificativas](algoritmos-busca.md) e
[busca comparativa e benchmark](busca-e-benchmark.md).

## Instalação no Windows

Execute na raiz do repositório, com Python 3.12 e Node.js instalados:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m nltk.downloader stopwords
.venv/Scripts/python.exe manage.py migrate
```

`requirements.txt` contém as dependências de execução e fixa o modelo spaCy inglês
3.8.0 com checksum; `requirements-dev.txt` acrescenta as dependências de testes.
Downloads são etapas explícitas de instalação/preparação. Nenhum modelo é baixado
durante requisições web. Os arquivos pickle devem ser exportações locais confiáveis
porque sua desserialização executa código Python. Dados e artefatos são ignorados
pelo Git; copie-os separadamente ao transferir a demonstração para outro computador.

## Preparar uma instalação nova

```powershell
.venv/Scripts/python.exe manage.py import_catalog
.venv/Scripts/python.exe manage.py import_reviews
.venv/Scripts/python.exe -u manage.py prepare_sentence_model
.venv/Scripts/python.exe -u manage.py build_search
.venv/Scripts/python.exe -u manage.py build_insights --resume
```

Os arquivos padrão são `_DadosLimpos/jogos_steam.pkl.gz` e
`_DadosLimpos/steam_reviews.pkl.gz`. Use `--catalog PATH` consistentemente em
import_catalog/build_search e `--reviews PATH` em import_reviews para outros
arquivos com o mesmo esquema de dados limpos em inglês.

`import_catalog` substitui o catálogo e remove reviews/insights associados;
execute as etapas seguintes novamente. `import_reviews` substitui as reviews e
invalida seus insights. As importações são transacionais. Os IDs estáveis de review
usam um hash de appid, timestamp e texto; registros exatamente repetidos são
eliminados. As contagens descrevem apenas a amostra coletada em inglês.

**Para atualizar uma instalação já preparada**, não reimporte dados. Execute:

```powershell
.venv/Scripts/python.exe -u manage.py prepare_sentence_model
.venv/Scripts/python.exe -u manage.py build_search --reuse-word2vec
```

Isso preserva o Word2Vec treinado, as reviews e seus insights. O treinamento
original usa 190 dimensões, janela 5, min_count 1, Skip-gram, semente 42, um worker
e dez épocas. Os novos índices são construídos offline e publicados em bundle v2.

`build_insights --resume` ignora jogos já preparados com a versão atual da análise.
Processa todas as reviews importadas e salva a cada lote de 100 jogos. Para preparar
jogos específicos primeiro, use `--appid 10 --appid 20`; a interface identifica os
demais como pendentes. Não execute importações ao mesmo tempo que a preparação.

## Executar a demonstração

Terminal 1, na raiz do repositório:

```powershell
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Abra http://127.0.0.1:5173. O Vite encaminha `/api` para a porta 8000; não é preciso
configurar CORS. Ambos os servidores aceitam conexões apenas em localhost.
Mantenha os terminais abertos e use Ctrl+C para encerrá-los. Reinicie o backend
após alterações no código, pois `--noreload` desativa a recarga automática.

`npm run build` verifica TypeScript e gera o pacote de produção. `npm run preview`
permite verificá-lo com o mesmo proxy. Os servidores utilizados aqui são locais;
publicação pública não faz parte desta versão. O primeiro acesso a um método pode
ser mais lento devido ao carregamento do índice/modelo.

## Artefatos e cache

Cada preparação cria uma pasta nova antes de trocar atomicamente `artifacts/current`.
O manifesto valida SHA-256 dos arquivos, fingerprint do catálogo, versões,
configurações e IDs ordenados. O bundle v2 também registra a revisão MiniLM,
truncamentos e custos de preparação. Bundles v1 continuam atendendo Word2Vec sem
filtros; métodos novos e filtros exigem atualização.

Cada processo do backend mantém seu índice em cache. Alterar o bundle ou fingerprint
muda a chave desse cache. Índices BM25, vetores MiniLM e codificador são carregados
sob demanda. Pastas anteriores podem ser mantidas para diagnóstico; no Windows,
encerre o servidor antes de remover manualmente bundles não utilizados, pois há
arquivos mapeados em memória. Para retomada e paralelismo de preparação, consulte
[busca-e-benchmark.md](busca-e-benchmark.md).

## Chave da API Steam

A navegação e a busca nos dados preparados não precisam de chave. Operações offline
de coleta que usam endpoints autenticados exigem a chave do próprio operador em
`STEAM_API_KEY`, configurada no ambiente ou em uma cópia local de `.env.example`
chamada `.env`. A coleta também aceita `1_Coleta_Dados/.env`. A precedência é:
variáveis do ambiente, `.env` da raiz e `.env` da coleta.

Registre a chave em https://steamcommunity.com/dev/apikey. Ela nunca deve entrar em
variáveis `VITE_*`, armazenamento do navegador, respostas da API ou arquivos
versionados. Não há formulário web para receber a chave. O coletor verifica sua
presença antes de listar jogos, e o helper HTTP remove URLs de exceções que poderiam
expor credenciais. Evite ativar logs de depuração HTTP ao fazer coleta autenticada.

Antes de executar coletas futuras, confira os endpoints e requisitos atuais na
[documentação Steam](https://partner.steamgames.com/doc/webapi/IUserReviewsService).
Uma chave comum não garante acesso a operações exclusivas de publicadores. Os
notebooks históricos foram preservados; esta atualização não migra seus endpoints
de reviews nem afirma que endpoints antigos permanecem disponíveis.

As variáveis opcionais do backend são `DJANGO_SECRET_KEY`, `DISCOVERY_DATABASE` e
`DISCOVERY_ARTIFACTS`. A chave Django de desenvolvimento é destinada apenas ao uso local.

## Contrato da API

Os endpoints são anônimos, de leitura, com respostas JSON. A busca comparativa e os
parâmetros repetidos de filtro estão detalhados em [busca-e-benchmark.md](busca-e-benchmark.md).

- `GET /api/v1/search/?q=...&limit=10`: retorna consulta, método, filtros normalizados,
  resultados, diagnósticos Word2Vec e mensagem. A consulta é obrigatória, limitada a
  500 caracteres; limit vai de 1 a 50. Cada resultado possui rank, score, score_type,
  similarity e os campos do jogo. Similarity é cosseno apenas nos métodos semânticos;
  nos métodos BM25/RRF vale null. Nenhum escore é probabilidade de recomendação.
- `GET /api/v1/filters/`: rótulos e contagens de tags/gêneros disponíveis.
- `GET /api/v1/games/{appid}/`: appid, name, description, genres, user_tags,
  steam_url, review_count e recommended_count. As contagens são da amostra em inglês;
  preços e imagens indisponíveis não são inventados.
- `GET /api/v1/games/{appid}/insights/`: versão, status, contagens coletadas/analisadas,
  positive, negative e note. Cada ponto contém aspect, summary, support_count e evidence com
  review_id e excerpt. Os status são ready, not_prepared, no_reviews e
  insufficient_evidence. Insights ausentes retornam 200 com arrays vazios.
- `GET /api/v1/health/`: prontidão do banco, catálogo e busca, reviews importadas,
  quantidade de jogos com insights e instruções em detail quando necessário.

Entradas inválidas retornam 400; jogos inexistentes, 404; busca indisponível ou
artefatos incompatíveis, 503. Consultas válidas sem correspondência retornam 200.
No Word2Vec, nenhuma palavra conhecida produz resultado vazio; MiniLM pode retornar
vizinhos mesmo para consultas ruins. Os tipos TypeScript ficam em `frontend/src/api.ts`.

## Qualidade dos insights e verificações

A extração utiliza aspectos explícitos, dependências spaCy e sentimento VADER por
cláusula. Descarta comparações, hipóteses, múltiplos aspectos não resolvidos e
sentimentos concorrentes. Os limiares são ±0,05. A prioridade é precisão sobre
cobertura; sarcasmo e contexto além da cláusula permanecem limitações.

Exibimos até cinco aspectos por lado, com duas reviews distintas de suporte no
mínimo e até três trechos por ponto. Repetições não inflam a contagem. O voto de
recomendação Steam permanece separado do sentimento do aspecto.

A página apresenta listas de pontos positivos e negativos em frases curtas, em inglês.
O campo `summary` é produzido por um modelo de frase determinístico: rótulo do aspecto
e indicação de força ou desvantagem recorrente. Por exemplo, `Visual presentation is
a recurring strength.` Os trechos originais ficam recolhidos em **View evidence**, com
a contagem de suporte. Um mesmo aspecto pode aparecer nos dois lados.
Esse resumo expressa somente o aspecto e a polaridade identificados, sem inferir detalhes
como taxa de quadros, duração ou preço. Não constitui fato verificado sobre o jogo.
Os dados existentes funcionam sem nova preparação, migração ou acesso à internet.

```powershell
.venv/Scripts/python.exe manage.py test discovery_api
.venv/Scripts/python.exe -m unittest discover -s 1_Coleta_Dados -p test_steam_scraper.py
.venv/Scripts/python.exe manage.py benchmark_demo
.venv/Scripts/python.exe manage.py audit_insights
cd frontend
npm test
npm run build
```

`evaluate_insights --export PATH` amostra 50 cláusulas, dez de cada um de cinco jogos,
com semente 42. Preencha expected com pares aspect/polarity ou array vazio para
abstenção e execute `evaluate_insights --annotations PATH`. A meta de desenvolvimento
é 80% de precisão; o conjunto usado para ajustar regras não equivale a avaliação
humana independente. Consulte os detalhes e limitações em `validation/README.md`.

`audit_insights` confere que cada trecho é literal e pertence ao jogo correto,
além de verificar cobertura, limites e contagens. Execute após concluir a preparação.
