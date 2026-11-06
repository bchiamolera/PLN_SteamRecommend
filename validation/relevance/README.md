# Benchmark de busca comparativa

Este experimento utiliza 60 consultas fixas (40 de desenvolvimento e 20 de teste)
sobre o catálogo de 179.464 jogos. O pool contém **1.912 pares consulta/jogo**,
deduplicados a partir dos dez primeiros resultados de cada um dos cinco métodos.
O arquivo de candidatos não contém método, posição ou escore de origem.

## Arquivos e proveniência

- `queries.json`: consultas, filtros, categorias, divisão e fingerprint do catálogo.
- `pool.jsonl`: metadados originais para julgamento cego quanto ao método.
- `rankings.json`: rankings, tempos, violações de filtros, memória e hashes.
- `judgments.jsonl`: rascunhos por regras e leitura do agente; nunca equivalem
  automaticamente a julgamentos humanos.
- `agent_reviews.jsonl`: os 68 pares de desenvolvimento lidos pelo agente nas
  consultas q001 (35 candidatos) e q002 (33 candidatos). As notas continuam com
  status agent_draft e método manual_agent; as justificativas são em inglês.
- `freeze.json`: configuração congelada antes de gerar as métricas de teste.
- `report_dev_agent_draft.json` e `report_test_agent_draft.json`: relatórios
  exploratórios, incluindo cobertura e categorias efetivamente avaliadas.

Os demais rascunhos usam regras explícitas de título, tags e consulta sem intenção
interpretável. Não foi feita uma avaliação por LLM de todos os pares. Ausência de
julgamento permanece null, sem ser convertida em irrelevância. Nenhum registro foi
marcado human_reviewed pelo agente.

Há 657 pares com nota preliminar e 1.255 ainda não julgados. Os 1.912 registros
mantêm a proveniência agent_draft, inclusive os revisados por leitura do agente.

## Resultados operacionais

As medições usam os handlers HTTP locais, após aquecimento, em todas as 60 consultas.
O teste bloqueou conexões de rede e removeu STEAM_API_KEY durante sua execução.

| Método | p95 aquecido | Violações de filtros |
|---|---:|---:|
| Word2Vec | 95,1 ms | 0 |
| BM25 | 32,6 ms | 0 |
| MiniLM | 139,5 ms | 0 |
| BM25 + Word2Vec | 90,5 ms | 0 |
| BM25 + MiniLM | 135,2 ms | 0 |

O processo com todos os métodos carregados consumiu aproximadamente 1.525,2 MB de
memória residente. O bundle ativo ocupa 631,7 MB. Os checksums confirmaram que os
arquivos do Word2Vec foram reutilizados byte a byte. A revisão MiniLM é
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Nenhuma descrição deste catálogo excedeu
o limite de 256 tokens; a última preparação retomada levou cerca de 645,5 segundos,
partindo de 82.304 jogos já codificados. Isso não inclui o tempo das etapas anteriores.

## Limites da avaliação de relevância

O desenvolvimento tem dez consultas completamente julgadas: duas descritivas,
seis de título, uma de mecânica e uma consulta sintética sem intenção. A última
tem IDCG zero e não entra nas médias de relevância. A cobertura dos pares de
desenvolvimento é de aproximadamente 35,8%.

O teste tem somente cinco consultas completamente julgadas: quatro de título e
uma de mecânica, com cobertura de aproximadamente 31,6% dos pares. Isso favorece
uma avaliação de correspondência de títulos e não representa a diversidade de
consultas descritivas. Os resultados não fundamentam uma afirmação geral de melhoria.

MiniLM e seu híbrido retornaram vizinhos para a consulta sintética sem sentido.
Esse comportamento está registrado, sem aplicar um limiar arbitrário para ocultá-lo.
Um limiar útil exigiria validação com consultas e julgamentos adicionais.

Word2Vec permanece como padrão. Para concluir a comparação, revise os pares não
julgados e obtenha avaliação humana independente, principalmente para consultas
descritivas, filtros e casos de negação. Não ajuste algoritmos usando o conjunto de teste.

## Preservação e testes

A auditoria continuou válida após a atualização: 395.256 reviews analisadas,
29.625 jogos com insights e 28.686 trechos conferidos, sem erros. A versão atual
passou em 24 testes de backend, seis de frontend e 13 de coleta, além da compilação
de produção e verificações de dependências/migrações. Os comandos e o procedimento
de revisão estão em [busca-e-benchmark.md](../../docs/busca-e-benchmark.md).

A verificação no navegador confirmou a troca de método, inclusão de tags e gênero,
exclusão de tag e preservação dos parâmetros ao voltar dos detalhes de um jogo.
Em viewport de 390 pixels, a página não apresentou estouro horizontal. As capturas
[desktop](demo-desktop.jpg) e [mobile](demo-mobile.jpg) registram essa conferência.
