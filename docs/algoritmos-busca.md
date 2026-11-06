# Algoritmos de busca e recomendação — Steam Atlas

## Objetivo e limites

O sistema recupera jogos a partir de uma consulta em inglês. Nesta versão, ele não
aprende preferências individuais, não prevê se uma pessoa gostará de um jogo e não
utiliza o percentual de reviews positivas para ordenar resultados. Os métodos novos
são experimentais; Word2Vec continua sendo o padrão para manter uma referência.

Há cinco opções: Word2Vec, BM25, MiniLM, BM25 + Word2Vec e BM25 + MiniLM. Cada método
responde a uma necessidade diferente. A comparação deve considerar relevância,
respeito aos filtros, custo computacional e tempo de resposta, não apenas o escore.

## 1. Word2Vec: referência semântica do projeto

**Por que foi escolhido:** já fazia parte dos experimentos acadêmicos e permite
preservar a comparação com os notebooks. É relativamente leve e aprende associações
do vocabulário específico do catálogo Steam.

**Onde:** `steam_discovery/search.py` implementa o treinamento, a média dos vetores
e a normalização; `steam_discovery/artifacts.py` carrega os artefatos e atende a busca.
O notebook de busca continua reutilizando as funções compartilhadas.

**Quando:** durante a preparação, o modelo é treinado sobre as descrições limpas em
inglês e gera um vetor por jogo. Em cada busca, somente a consulta passa por
tokenização, normalização Unicode, minúsculas e remoção de stopwords, preservando
negações. Calcula-se a média dos vetores das palavras conhecidas e a similaridade
cosseno com as descrições.

Mantivemos 190 dimensões, janela 5, `min_count=1`, Skip-gram, semente 42, um worker
e dez épocas. `--reuse-word2vec` copia o modelo e os vetores existentes, sem novo
treinamento. A média perde ordem e contexto: preservar “not” no texto não significa
compreender uma restrição como “not horror”. Palavras desconhecidas não contribuem
para o vetor. Vetores nulos ficam fora do ranking.

## 2. BM25: correspondência lexical

**Por que foi escolhido:** complementa a busca semântica com correspondências de
nomes, termos específicos, mecânicas e tags. Uma palavra presente apenas no nome ou
nas tags pode ser encontrada mesmo quando está fora do vocabulário Word2Vec.

**Onde:** `steam_discovery/lexical.py`. A implementação usa NumPy e matrizes esparsas
SciPy, aproveitando a estrutura local sem exigir Elasticsearch ou outro servidor.

**Quando:** na preparação, concatenamos nome, gêneros, tags e descrição de cada jogo,
aplicamos o pré-processamento lexical e calculamos frequências, comprimentos e IDF.
Os pesos ficam em uma matriz esparsa por documento/termo. Na consulta, somamos
somente as colunas dos termos presentes no índice; termos repetidos da consulta
contam uma vez. Resultados com escore zero são omitidos.

Para cada termo, usamos:

```text
IDF(t) = ln(1 + (N - df(t) + 0,5) / (df(t) + 0,5))
contribuição(t,d) = IDF(t) × tf(t,d) × (k1 + 1)
                   / [tf(t,d) + k1 × (1 - b + b × |d| / média_comprimentos)]
```

O fator `k1=1,5` controla a saturação de frequência; `b=0,75` normaliza pelo tamanho
do documento. A forma de IDF adotada é positiva. Não há pesos distintos por campo
nesta primeira comparação. Como o documento inclui metadados, a comparação com
Word2Vec não isola apenas uma troca de modelo: também compara fontes de informação.
BM25 não entende sinônimos ou negação por si só.

## 3. MiniLM: embeddings de sentenças

**Por que foi escolhido:** `sentence-transformers/all-MiniLM-L6-v2` oferece uma
referência compacta para comparar o significado de frases completas. Seus vetores
têm 384 dimensões; o modelo foi ajustado para similaridade de sentenças, ao contrário
de simplesmente usar BERT base sem esse ajuste. Isso é uma hipótese de melhoria,
não uma garantia de ranking melhor para jogos.

**Onde:** `steam_discovery/sentence.py`; preparação em `build_search` e carregamento
do modelo em `prepare_sentence_model`.

**Quando:** `prepare_sentence_model` baixa explicitamente os arquivos públicos e
registra o SHA da revisão. As execuções seguintes reutilizam essa revisão, salvo
solicitação explícita de outra. `build_search` codifica as descrições em lotes,
normaliza os vetores e salva a matriz. Durante uma busca, codificamos somente a
consulta completa, sem remover stopwords, e usamos cosseno.

O modelo roda em CPU, com até quatro threads, e é carregado sob demanda por processo.
A inferência é protegida por lock. O carregamento usa somente arquivos locais,
`trust_remote_code=False` e `token=False`; não precisa de chave Steam ou Hugging Face.
Não há download durante requisições. O limite é 256 tokens do tokenizador, incluindo
tokens especiais; descrições maiores são truncadas, e a quantidade é registrada no
manifesto. Não implementamos chunking, fine-tuning ou reranking nesta etapa.

Referências: [model card do MiniLM](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
e [API SentenceTransformer](https://sbert.net/docs/package_reference/sentence_transformer/model.html).

## 4. RRF: combinação dos rankings

**Por que foi escolhido:** o BM25 e o cosseno têm distribuições e escalas diferentes.
Reciprocal Rank Fusion combina posições e evita somar escores incompatíveis.

**Onde:** `steam_discovery/retrieval.py`; orquestração em `SearchIndex.retrieve`.

**Quando:** a cada busca híbrida, selecionamos até 200 candidatos elegíveis por
método: BM25 + Word2Vec ou BM25 + MiniLM. Para cada jogo:

```text
RRF(jogo) = soma de 1 / (60 + posição_no_método)
```

As posições começam em 1 e os métodos têm pesos iguais. Um jogo ausente de uma
lista não recebe contribuição dela. Empates na fusão são resolvidos por `appid`.
Mantemos o desempate original do Word2Vec isolado para preservar a referência do
notebook. Se uma perna não recuperar candidatos, a outra pode contribuir sozinha,
mas um artefato ausente gera erro: não há troca silenciosa de algoritmo.

O escore RRF não é probabilidade, porcentagem de satisfação ou cosseno.
Referência: [documentação do RRF](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).

## 5. Filtros: requisitos explícitos sobre metadados

**Por que foram escolhidos:** embeddings e palavras-chave não garantem o cumprimento
de preferências obrigatórias. Os seletores permitem que a pessoa especifique essas
restrições de forma verificável.

**Onde:** `steam_discovery/filters.py`; validação da requisição em
`discovery_api/serializers.py`; seletores em `frontend/src/App.tsx`.

**Quando:** os rótulos e suas posições são preparados offline. Durante a busca,
calculamos a máscara de jogos elegíveis **antes** de selecionar os melhores
candidatos de cada método. Todas as tags obrigatórias precisam estar presentes;
qualquer tag excluída remove o jogo; basta um dos gêneros selecionados coincidir.

A comparação usa Unicode NFKC, remoção de espaços nas pontas e `casefold`. Rótulos
desconhecidos e a mesma tag obrigatória/excluída geram HTTP 400. Combinações válidas
sem jogos retornam lista vazia. Não interpretamos automaticamente filtros no texto
livre. “Excluir Zombies” remove jogos marcados com essa tag; não prova que os demais
não tenham zumbis. As contagens nos seletores representam todo o catálogo, não uma
faceta recalculada para cada consulta.

## 6. Fluxo completo e compatibilidade

```text
Preparação explícita: download MiniLM → reutilizar/treinar Word2Vec → BM25
                      → embeddings MiniLM → validação e publicação do bundle v2

Requisição: validar consulta/método/filtros → máscara de elegibilidade
           → ranking(s) → fusão opcional → dados dos jogos → resposta JSON
```

O manifesto contém revisão do modelo, pré-processamento, configurações, fingerprint
do catálogo, IDs ordenados, checksums, truncamentos, duração e memória de preparação.
Cada bundle é publicado em uma pasta nova; somente ao concluir ocorre a troca
atômica de `artifacts/current`. Uma interrupção preserva o bundle anterior.

Bundles v1 continuam atendendo Word2Vec sem filtros. Filtros e métodos novos exigem
v2, com instrução de atualização em caso de ausência. A atualização não reimporta o
catálogo nem modifica reviews ou insights. Os índices são carregados uma vez por
processo; BM25, matriz MiniLM e codificador são carregados sob demanda.

## 7. Benchmark, julgamentos e o significado das métricas

O benchmark fixa 60 consultas antes da comparação: 40 de desenvolvimento e 20 de
teste, abrangendo descrições, títulos, mecânicas, filtros, termos raros e casos
difíceis. O fingerprint vincula as consultas ao catálogo. Cada método fornece seus
dez primeiros resultados; a união deduplicada forma um pool por consulta. O arquivo
para julgamento não revela método, posição ou escore de origem.

Os rascunhos `agent_draft` têm justificativa e evidência literal do catálogo.
O comando `draft` usa regras transparentes para títulos exatos, cobertura explícita
de tags e uma consulta sintética sem intenção interpretável. Ele **não executa uma
avaliação semântica por LLM de todos os pares**. Os demais pares ficam com `grade=null`.
Isso fornece uma semente revisável, sem fingir que ausência de palavra indica
irrelevância. Leitura manual pelo agente pode complementar o arquivo com
`draft_method=manual_agent`, mantendo a mesma proveniência de rascunho.

As notas são 0 (irrelevante), 1 (parcialmente relevante) e 2 (muito relevante).
Uma pessoa pode corrigir notas e marcar `human_reviewed`; a importação exige
`--confirm-human-review`. Nenhum comando converte rascunhos automaticamente em
avaliação humana. Evidências inexistentes, duplicações e notas inválidas são rejeitadas.

**Precision@5** mede a fração das cinco posições com nota maior que zero.
**NDCG@10** usa ganhos `2^nota - 1`, desconta posições por `log2(posição+1)` e normaliza
pelo ranking ideal dos candidatos julgados. Todos os métodos são comparados no mesmo
subconjunto de consultas cujo pool inteiro está julgado na proveniência escolhida.
Não julgados não viram zero. Consultas sem julgamento relevante têm IDCG zero e ficam
fora das médias de relevância, com registro separado. Não calculamos Recall@k, pois
o pool não identifica todos os jogos relevantes do catálogo.

Também reportamos cobertura de julgamento, categorias efetivamente avaliadas,
violações dos filtros, p95 de latência aquecida e memória. A meta operacional é p95
abaixo de dois segundos e zero violação de filtros; isso não comprova relevância.
O cronômetro usa os handlers HTTP locais do Django, sem tempo de rede/navegador.

Ajustes devem usar apenas desenvolvimento. `freeze` registra bundle, consultas e
configuração antes de liberar métricas de teste. Resultados com rascunhos são
exploratórios e não fundamentam a afirmação de que um método é melhor. Mesmo após
revisão humana, o benchmark precisa ser interpretado conforme sua cobertura; esta
versão nunca troca automaticamente o método padrão com base em métricas.

## O que não participa do ranking

### Explicações das reviews: spaCy + VADER

Escolhemos spaCy para identificar aspectos e vínculos gramaticais explícitos com
opiniões, e VADER para classificar a polaridade dessas cláusulas em inglês. A
combinação é local, leve, rastreável e dispensa API de linguagem. Não equivale a
uma compreensão completa de sarcasmo ou contexto.

O código está em `steam_discovery/insights.py`; `build_insights` executa a análise
**offline**, agrega reviews distintas e grava os resultados no SQLite. Cláusulas
ambíguas, comparações e hipóteses são descartadas; os limiares VADER são ±0,05.
Um ponto precisa de duas reviews de suporte, com até cinco aspectos por polaridade
e até três trechos por ponto. Repetir uma opinião na mesma review não infla o suporte.
Durante uma requisição, a API lê os insights preparados e `summarize_points` gera
uma frase por aspecto/polaridade usando um modelo de frase determinístico.
Escolhemos esse método porque os dados agregados sustentam o aspecto e a polaridade,
mas não uma descrição detalhada de mecânicas ou defeitos específicos. A frase indica
uma força ou desvantagem recorrente, sem acrescentar atributos não extraídos.
O frontend apresenta essas frases em listas de pontos positivos e negativos;
os trechos literais e a contagem de suporte ficam numa seção expansível por ponto.
O método preserva opiniões conflitantes, ordenação, limite e suporte mínimo da análise.
Ele funciona com os registros já preparados, sem alterar sua versão ou conteúdo.
spaCy/VADER não são executados em cada busca, e não há chamada a modelo generativo.

O classificador TF-IDF, BERT e os demais experimentos dos notebooks continuam
disponíveis para estudo, mas não fazem parte dos cinco métodos desta implementação.

Os pontos positivos/negativos de reviews permanecem como explicações na página do
jogo. Baixa cobertura de extração não penaliza jogos. A coleta amostrou reviews
positivas e negativas separadamente; sua proporção não representa aprovação global
na Steam. Personalização, popularidade, filtros de preço, modelo multilíngue e
cross-encoder ficam para etapas futuras.
