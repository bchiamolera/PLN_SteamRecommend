# Validação de desenvolvimento

A documentação explicativa usa pt-BR. Código, comandos, prompts e mensagens do
programa usam en-US; trechos originais de reviews/consultas são dados em inglês.
Para os cinco métodos novos, consulte [execução e benchmark](../docs/busca-e-benchmark.md)
e [algoritmos e justificativas](../docs/algoritmos-busca.md).

## Histórico da análise de reviews

`insight_annotations.json` contém 50 cláusulas originais: dez por jogo, em cinco
jogos, amostradas com semente 42 antes de inspecionar previsões. O Codex atribuiu
expected por leitura manual, com abstenções para casos neutros, ambíguos e menções
a outros títulos. **Não são anotações humanas independentes.** A amostra foi gerada
com o filtro lexical v2, que incluía FPS; uma nova exportação v3 pode selecionar
cláusulas diferentes devido à remoção desse termo ambíguo.

A extração inicial por distância na árvore sintática emitiu 15 pontos, dos quais
oito estavam corretos: precisão de 53,3%. Os erros incluíam ambiguidade de FPS,
sentimento de outra expressão e elogio a outro jogo. A regra final exige vínculos
gramaticais explícitos e descarta comparações/hipóteses. Na mesma amostra, emitiu
cinco pontos corretos, sem falsos positivos, com 10% de cobertura e 18,5% de recall
de pontos. A precisão supera a meta de desenvolvimento, mas a cobertura é baixa.
Como essas cláusulas foram usadas no ajuste, o resultado não demonstra precisão de
100% em dados inéditos. São necessários novos julgamentos humanos independentes.

```powershell
.venv/Scripts/python.exe manage.py evaluate_insights --annotations validation/insight_annotations.json --output validation/insight_metrics.json
.venv/Scripts/python.exe manage.py benchmark_demo
.venv/Scripts/python.exe manage.py audit_insights
```

## Medições históricas da primeira versão web

Os números desta seção descrevem a primeira versão Word2Vec, preparada em outubro
de 2026; não representam automaticamente os custos da busca híbrida/MiniLM atual.
`benchmark.json` registra o tempo do handler HTTP pelo cliente de testes Django,
memória residente, tamanho dos artefatos e contagens. A medição proíbe conexões de
rede e remove STEAM_API_KEY do ambiente. Não inclui latência do navegador/rede.

O treinamento Word2Vec original sobre 179.464 descrições levou 345,4 segundos.
Alterar o corpus ou a semente de hash do interpretador pode alterar vetores novos;
a verificação de paridade compara o mesmo modelo treinado.

A preparação inicial contém 179.464 jogos, 395.256 reviews em inglês e 29.625 jogos
com insights. A última retomada processou os 26.930 jogos restantes em 1.352,4
segundos; 2.695 já estavam preparados. Esse tempo é de uma execução retomada, não
de um processamento integral ininterrupto.

A auditoria inicial conferiu 28.686 trechos sem erros de propriedade ou fidelidade
ao texto e confirmou que todas as reviews importadas foram analisadas. O benchmark
original mediu 85,1 ms de mediana e 92,5 ms de máximo aquecido; 1,6844 s no primeiro
handler; 348,3 MB de RSS; e 206,8 MB de artefatos ativos. Os JSON preservam os valores
originais para rastreabilidade.

A primeira versão passou em 15 testes de backend, 13 de coleta e quatro de frontend,
além de compilação TypeScript/produção, verificações Django, consistência de migrações
e dependências. As capturas desktop e mobile de 390 pixels dessa versão estão
nesta pasta. A captura mobile não apresentou rolagem horizontal.

## Benchmark de relevância da atualização

Os dados e relatórios novos ficam em `relevance/`. Os rascunhos registram sua
proveniência e não são promovidos automaticamente a revisão humana. Pares sem
julgamento permanecem null e não recebem nota zero implícita. Consulte cobertura
e categorias avaliadas antes de interpretar Precision@5 ou NDCG@10.

Os testes de recuperação verificam fórmulas, fusão, filtros anteriores ao corte,
alinhamento dos índices, leitura offline e preservação de reviews/insights. Os
testes da interface verificam navegação, filtros, método e apresentação das escalas
de escore. A atualização não usa as proporções amostradas de reviews para ranquear jogos.
