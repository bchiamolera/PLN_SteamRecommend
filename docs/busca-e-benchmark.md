# Executar a busca comparativa e o benchmark

Use PowerShell na raiz do repositório. A interface permanece em inglês; esta
documentação está em português brasileiro. Consulte a explicação técnica em
[algoritmos-busca.md](algoritmos-busca.md).

## Atualização de uma instalação existente

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -u manage.py prepare_sentence_model
.venv/Scripts/python.exe -u manage.py build_search --reuse-word2vec
```

Somente o primeiro comando de preparação do modelo precisa de internet. O download
é público, sem chave Steam e sem token Hugging Face. Uma revisão imutável é salva
em `artifacts/model_cache/model.json`; os arquivos dessa revisão são incorporados
ao bundle. O comando `build_search` só usa arquivos locais. Não execute import_catalog,
import_reviews ou build_insights para essa atualização: isso não é necessário.

Para instalação nova, siga a configuração inicial e importação de dados de
[web-demo.md](web-demo.md), prepare o modelo e execute `build_search` sem
`--reuse-word2vec`. `--batch-size 64` é o padrão; lotes menores reduzem memória.
Em uma máquina com vários núcleos e memória disponível, `--workers 2` paraleliza
somente a preparação. O padrão é um processo; aceitamos até quatro. Cada processo
carrega seu próprio modelo, aumentando o consumo de RAM. As consultas continuam
usando um único codificador CPU protegido por lock.
Os métodos novos só ficam disponíveis quando a publicação do bundle v2 termina.

Durante a preparação, os textos são agrupados em blocos e ordenados internamente
por comprimento para reduzir padding; o encoder devolve os vetores na ordem original.
Cada bloco concluído salva `sentence_progress.json`. Se houver interrupção, localize
a pasta de preparação sem manifesto em `artifacts/` e use:

```powershell
.venv/Scripts/python.exe -u manage.py build_search --reuse-word2vec --resume-sentence-from artifacts/PREPARATION_ID
```

O comando valida fingerprint, revisão e IDs antes de aproveitar o checkpoint. O
bundle anterior permanece ativo durante a retomada. Mantenha a pasta de checkpoint
até a nova publicação terminar.

## Servir localmente

A interface organiza a busca e os filtros em um painel lateral no desktop, com
os resultados ao lado. Em telas menores, o painel passa para cima da lista. O
campo de consulta aceita múltiplas linhas, os cartões destacam posição e escala
do escore, e a página inicial apresenta instruções curtas de descoberta. O tema
azul utiliza contraste, estados de foco visíveis e respeito à preferência por
movimento reduzido. A apresentação não altera o ranking nem as regras de filtro.

Terminal 1, raiz do repositório:

```powershell
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Abra http://127.0.0.1:5173. Reinicie o backend após alterações no código; `--noreload`
evita carregar modelos duas vezes. Após publicar outro bundle, a chave do cache
muda automaticamente. Mantenha os arquivos e o banco no mesmo catálogo/fingerprint.
O primeiro acesso a BM25/MiniLM pode demorar mais por carregar índices e pesos.
A meta de dois segundos se aplica às consultas seguintes, com o processo aquecido.

## API

`GET /api/v1/search/` mantém `q` obrigatório (até 500 caracteres) e `limit` de 1 a 50.
O parâmetro `mode` aceita `word2vec` (padrão), `bm25`, `sentence`, `hybrid_word2vec`
e `hybrid_sentence`. Repita os parâmetros de filtro:

```text
/api/v1/search/?q=survive&mode=hybrid_sentence&required_tag=Co-op&required_tag=Survival&excluded_tag=Zombies&genre=Adventure&genre=Action
```

`GET /api/v1/filters/` fornece arrays `tags` e `genres`, com `label` e `count`.
Os filtros usam dropdowns pesquisáveis: digitar apenas pesquisa a lista; somente
clicar numa opção cadastrada ou selecioná-la com as setas e Enter adiciona um filtro.
Não é possível criar tags/gêneros pelo campo. Opções já selecionadas ficam fora da
lista, e Escape ou sair do campo fecha o dropdown. Os rótulos vêm do catálogo
preparado a partir dos dados importados; a API continua rejeitando rótulos desconhecidos.
Filtros obrigatórios usam AND, gêneros usam OR e exclusões removem qualquer
coincidência. Os rótulos precisam existir; contradições geram 400. Não há extração
automática de filtros a partir de frases como “without zombies”.

A resposta acrescenta `mode` e `filters` normalizados. Cada resultado possui `rank`,
`score`, `score_type` e os dados do jogo. `score_type` é `cosine`, `bm25` ou `rrf`.
`similarity` mantém o cosseno para Word2Vec/MiniLM e vale `null` para BM25/RRF.
`known_terms` e `unknown_terms` são diagnósticos do Word2Vec, não do MiniLM.
Artefatos ausentes/incompatíveis retornam 503, filtros inválidos retornam 400 e
combinações válidas sem resultados retornam 200 com lista vazia e mensagem.

## Benchmark reproduzível

```powershell
.venv/Scripts/python.exe manage.py relevance_benchmark init
.venv/Scripts/python.exe -u manage.py relevance_benchmark export
.venv/Scripts/python.exe manage.py relevance_benchmark draft
.venv/Scripts/python.exe manage.py relevance_benchmark evaluate --split dev
.venv/Scripts/python.exe manage.py relevance_benchmark freeze
.venv/Scripts/python.exe manage.py relevance_benchmark evaluate --split test
```

As consultas e a divisão 40/20 são fixadas antes dos resultados. Os arquivos ficam
em `validation/relevance/`: `queries.json`, `pool.jsonl` (cego quanto ao método),
`rankings.json` (resultados técnicos), `judgments.jsonl`, `freeze.json` e relatórios.
Não sobrescrevemos consultas, pools ou julgamentos existentes automaticamente;
use `--directory validation/relevance_novo` para outra experiência.

O comando `draft` produz rascunhos por regras, não julgamentos humanos e não leitura
semântica de todos os candidatos. Revise os pares com `grade=null`; nenhuma nota
é inventada para completar a métrica. Exemplo de registro revisável:

```json
{"query_id":"q021","appid":620,"grade":2,"status":"agent_draft","draft_method":"manual_agent","reason":"The title matches the query.","evidence":{"field":"name","quote":"Portal 2"}}
```

Os campos de evidência aceitos são `name`, `description`, `genres` e `user_tags`.
O trecho deve ser literal; para arrays, use um rótulo completo. Após revisão humana
real, a pessoa altera o status dos registros revisados para `human_reviewed` e
executa explicitamente:

```powershell
.venv/Scripts/python.exe manage.py relevance_benchmark import --input path/reviewed.jsonl --confirm-human-review
.venv/Scripts/python.exe manage.py relevance_benchmark evaluate --split dev --label-source human_reviewed
```

O arquivo de importação substitui os julgamentos daquele experimento; mantenha uma
cópia antes de editar. `freeze` libera avaliação de teste somente se consultas,
bundle e configuração ainda coincidirem com a exportação. Ajuste algoritmos apenas
com desenvolvimento. Também registramos o hash do código de recuperação e do pool;
alterações nesses arquivos invalidam o experimento, em vez de misturar versões.
Para configurações diferentes, crie outro experimento.

Leia cobertura e categorias avaliadas junto com Precision@5 e NDCG@10. Um relatório
baseado sobretudo em títulos exatos não mede bem relevância de consultas descritivas.
Com cobertura insuficiente, uma métrica pode ser `null`; isso não significa zero.
Não há alegação automática de melhoria nem promoção automática de outro método.

## Verificação

```powershell
.venv/Scripts/python.exe manage.py test discovery_api
.venv/Scripts/python.exe manage.py audit_insights
.venv/Scripts/python.exe manage.py check
cd frontend
npm test
npm run build
```

A atualização preserva os insights existentes. A auditoria confirma isso e verifica
evidências; os testes de busca verificam cálculos, alinhamento, filtros anteriores
ao corte de candidatos, empates e comportamento sem rede. O benchmark registra
latência aquecida e memória com os cinco métodos no catálogo completo.
