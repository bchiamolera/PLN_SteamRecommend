# Agente de descoberta

O modo agente é opcional na página existente. A busca convencional continua sendo
o padrão, local e sem credenciais. Não há migrações, reimportação, retreinamento ou
reconstrução dos índices para adicionar o agente; os artefatos de busca v2 já devem
estar preparados para disponibilizar todos os métodos e filtros.

## Instalação e uso

Instale as dependências atualizadas com `.venv/Scripts/python.exe -m pip install -r requirements.txt`
e inicie Django e Vite como descrito em [web-demo.md](web-demo.md). Habilite **Agent mode**,
escolha OpenAI, Anthropic ou Google, informe uma chave desse provedor e clique em
**Load models**. Selecione explicitamente um modelo antes de **Find games**.
Uma assinatura de aplicativo de chat não implica acesso à API nem saldo disponível.

O seletor mostra a interseção do registro curado com a listagem do provedor.
Listagem não garante autorização, saldo ou compatibilidade em uma chamada posterior.
Não há troca automática de modelo ou provedor. O registro fica em
`discovery_api/agent/contracts.py`; ao alterar IDs, atualize os testes e confira
as capacidades de ferramentas nos documentos oficiais dos provedores.

O seletor prioriza modelos leves e mostra nomes legíveis. Google inclui
`gemini-3.1-flash-lite` (estável), `gemini-3.5-flash-lite` e `gemini-3.6-flash`
antes das opções anteriores. OpenAI inclui `gpt-5.4-mini` e `gpt-6.1-terra`,
além de Luna. Claude Haiku aparece antes de Sonnet e Opus. Modelos maiores
continuam disponíveis no fim da lista, quando autorizados pela chave.

`MODEL_SETTINGS` mantém os nomes e parâmetros de latência por modelo. Flash-Lite
3.1/3.5 e Flash 3.6 usam thinking `minimal`; os demais Gemini usam `low`.
Luna, Mini e Terra usam reasoning `none`; Sol e Astra usam `low`.
Claude usa effort `low`. Esses ajustes priorizam rapidez, com possível redução
na qualidade de interpretação. Não há garantia de tempo de resposta; continue
avaliando relevância e apoio das explicações nas evidências.

Documentação dos modelos: [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite),
[níveis de thinking do Gemini](https://ai.google.dev/gemini-api/docs/thinking),
[modelos OpenAI](https://developers.openai.com/api/docs/models/all) e
[effort do Claude](https://platform.claude.com/docs/en/build-with-claude/effort).
Referências: [OpenAI](https://developers.openai.com/api/docs/guides/function-calling),
[Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
e [Google](https://ai.google.dev/gemini-api/docs/function-calling).

Buscas e refinamentos são ações explícitas e podem gerar cobrança. Digitar, alterar
filtros ou navegar pelos detalhes não dispara uma chamada de geração. **More exploration**,
**Less combat** e o campo de refinamento preservam preferências da descoberta.
Uma nova busca pelo campo principal começa uma nova intenção, mantendo os filtros
visíveis. Filtros removidos pelo usuário podem ser discutidos novamente se a intenção
textual ainda os exigir. **Reset discovery** apaga resultados, contexto e filtros;
mantém provedor, chave e modelo. **Disable agent mode** também apaga a conexão.

## Chaves e contexto

### Chat de recomendações

Abra **Chat** na navegação (rota `/chat`), escolha o provedor, informe sua chave,
carregue os modelos e selecione um deles. A conversa funciona em inglês. Exemplos:

1. `Recommend a cozy farming game with exploration.`
2. `Less combat, please.`
3. `Why did you suggest the first game?`
4. `Compare the first two games.`
5. `Actually, I want single-player instead.`

As respostas mostram jogos com links para os detalhes e evidências expansíveis.
Perguntas e comparações recarregam os dados locais dos jogos discutidos; mensagens
anteriores não são fontes de evidência. Preço, plataformas e idiomas continuam
indisponíveis. As preferências permanecem até serem alteradas explicitamente.

Conexão e modelo são compartilhados com a página Discover. Histórico, resultados
e preferências do chat são independentes da descoberta. Navegar para detalhes e
voltar por **Back to chat** preserva a conversa. **New chat** apaga a conversa e
mantém a conexão; trocar o provedor, editar a chave ou **Disconnect** também
limpa a conversa. Trocar o modelo mantém as mensagens concluídas. Recarregar ou
fechar a aba apaga tudo; não há contas ou armazenamento persistente.

Cada envio é uma ação explícita, com os mesmos limites de quatro respostas do
modelo e seis ferramentas. Não há streaming. Falhas temporárias do provedor têm até cinco retentativas automáticas. Uma falha
oferece **Retry message**; **Stop waiting** cancela a espera e ignora respostas
atrasadas, sem garantir cancelamento no provedor. Digitar ou escolher exemplos
não dispara geração.

`POST /api/v1/agent/chat/` recebe `provider`, `model`, `message` (até 500
caracteres), `context` resumido e `history` com até seis pares completos de
mensagens. Cada item tem `role` (`user` ou `assistant`), `content` (até 500
caracteres para usuário e 700 para assistente) e `appids` (até cinco IDs para
assistente; vazio para usuário). O histórico visível completo permanece no React;
apenas os seis pares mais recentes seguem ao backend, incluindo `games` com até cinco pares `appid`/`explanation` (700 caracteres cada). Esse contexto é não confiável e não substitui inspeção das fontes. O corpo tem limite de
200.000 bytes e a chave segue exclusivamente por `X-Agent-API-Key`.

A resposta inclui `reply`, `kind` (`recommendations`, `answer`,
`needs_clarification` ou `no_matches`), `results` com explicações e referências
validadas, `context`, preferências, limitações e metadados de execução. Recomendações
mantêm a ordem da busca; perguntas e comparações podem citar jogos anteriores
após inspeção nesta requisição. O endpoint de descoberta existente mantém seu
contrato. Os testes usam provedores simulados e não geram cobranças.

A chave fica somente na memória do React acima das rotas e é enviada ao backend
local pelo cabeçalho `X-Agent-API-Key`. Não é salva em cookies, localStorage,
sessionStorage, banco, arquivos, URLs ou contexto do modelo. Recarregar ou fechar
a aba exige informá-la novamente. Trocar de provedor também apaga a chave.
Abas diferentes não compartilham estado. O backend cria um cliente por requisição,
fecha-o ao terminar e não registra corpos/cabeçalhos nem exceções brutas do provedor.
Não habilite logs HTTP de depuração no ambiente em que inserir chaves reais.

O provedor recebe a consulta, preferências resumidas, definições das ferramentas e
trechos relevantes do catálogo/reviews. Isso exige internet e está sujeito às regras
e à cobrança do provedor. A chave da Steam permanece exclusiva da coleta offline;
ela não é usada no agente. Os endpoints de agente retornam `Cache-Control: no-store`
e as operações POST verificam Origin contra a origem do backend e as origens locais
Vite configuradas em `AGENT_ALLOWED_ORIGINS`. A aplicação continua exclusiva de localhost.

## Execução e contrato

`GET /api/v1/agent/providers/` lista provedores. `POST /api/v1/agent/models/` recebe
`provider`; `POST /api/v1/agent/discover/` recebe `provider`, `model`, `query`,
`filters` (`required_tag`, `excluded_tag`, `genre`) e `context` opcional
(`preferences`, `latest_query`, `previous_appids`). As duas operações POST recebem
a chave apenas pelo cabeçalho e exigem Origin autorizado.

Discovery retorna status `ready`, `needs_clarification` ou `no_matches`, resultados
com os campos tradicionais e `explanation`, `references`, `insight_status`, filtros
efetivos, preferências, contexto resumido, limitações, ações executadas, provedor,
modelo, tempo e uso de tokens quando disponível. Não retorna raciocínio interno.

Cada ação permite até quatro respostas de modelo e seis execuções de ferramentas
(incluindo finalização). Cada tentativa de provedor tem timeout padrão de 45
segundos, com orçamento total de 180 segundos compartilhado entre rodadas,
retentativas e pausas. Configure `AGENT_ATTEMPT_TIMEOUT` e `AGENT_REQUEST_TIMEOUT`
no ambiente do backend (segundos, valores positivos). O tempo restante reduz o
timeout da próxima chamada. Etapas locais verificam o prazo antes/depois de
executar, mas operações locais bloqueantes não são interrompidas à força.
O proxy Vite não impõe outro timeout.
A última resposta/ferramenta fica reservada para finalizar. Cada resposta admite
até 4.096 tokens de saída; isso não equivale a um limite monetário fixo.
**Reset discovery** e **Disable agent mode** cancelam a espera no navegador e
ignoram respostas antigas. Isso não garante cancelamento de uma chamada já aceita
pelo provedor ou da execução em andamento no backend. Falhas temporárias do provedor têm até cinco retentativas automáticas.

Os adaptadores usam SDKs oficiais, com retentativas controladas pela aplicação e sem execução automática
de funções. Preservam os blocos de continuação exigidos pelos provedores. Somente
`get_filters`, `search_games`, `inspect_games` e `finish_discovery` são executáveis.
Claude usa seleção automática com schemas estritos, pois Sonnet/Opus 5.5 rejeitam
seleção forçada; a última rodada oferece somente a ferramenta de finalização.
Filtros obrigatórios são conferidos em cada busca, inclusive a semântica OR de gêneros.
Recomendações pertencem à última busca, preservam ordem e escores e têm suas fontes
conferidas por jogo. Reviews só podem ser citadas após inspeção. IDs e trechos são
validados; essa verificação não prova que toda paráfrase do modelo é semanticamente
correta. Avaliação humana continua necessária.

Preço, plataforma e idiomas não existem no catálogo atual. Tags ausentes não provam
ausência de características; insights representam opiniões da amostra inglesa e
podem estar ausentes, pendentes ou conflitantes. Não há coleta online nem execução
de código arbitrário pelo agente.

Locais e países, como um cenário no Brasil, permanecem na consulta textual; o
agente não deve inventar tags para representá-los. Se as fontes recuperadas não
comprovarem um requisito obrigatório, deve perguntar se o usuário aceita ampliá-lo.
Erros de validação retornam orientações específicas ao modelo sobre filtros,
fontes, ordem dos jogos ou formato, dentro do mesmo limite de chamadas. Os schemas
das ferramentas incluem limites de tamanho e citações preservam espaços e quebras
de linha dos trechos originais. Se a finalização continuar inválida, a interface
recebe uma descrição segura do tipo de falha, sem expor os argumentos do modelo.

Erros incluem `invalid_input` (400), `origin_rejected` (403), `authentication` (401),
`rate_limit` (429, incluindo quota), `model_unavailable` (400), `provider_failure`
(502), `artifacts_unavailable` (503), `deadline` (504), `budget_exceeded` e
`invalid_model_output` (502). O usuário decide quando repetir uma ação paga.

## Verificação e avaliação

Execute `.venv/Scripts/python.exe manage.py test discovery_api --noinput`,
`npm --prefix frontend test` e `npm --prefix frontend run build`.
Os testes comuns simulam os provedores e não usam chaves nem chamadas pagas.
`validation/agent/cases.json` contém casos separados de descrição, exclusões,
refinamento, ambiguidade, requisitos indisponíveis, falta de evidências e injeção em
fontes. Seus julgamentos são `agent_draft`, não avaliação humana nem demonstração
de melhoria geral sobre a busca. Os julgamentos do benchmark existente são preservados.

Para um teste real opcional, defina uma variável exclusiva com sua chave de
desenvolvimento e execute, substituindo provedor/modelo quando necessário:

```powershell
.venv/Scripts/python.exe manage.py agent_smoke --provider openai --model gpt-6-luna --key-env STEAM_ATLAS_DEV_KEY --allow-charges
```

O comando faz uma descoberta e um refinamento, imprime resultados sem a chave e
recusa executar sem `--allow-charges`. Cada ação tem seu próprio orçamento.
Revise relevância, preservação de preferências, apoio semântico das explicações,
latência e uso antes de declarar um modelo adequado. Não ajuste usando o conjunto
de teste de relevância existente.

As retentativas cobrem falhas de conexão, timeout por tentativa, indisponibilidade
temporária e rate limit temporário: uma tentativa inicial e até cinco adicionais,
sempre dentro do prazo total. `Retry-After` válido tem preferência; na ausência dele,
as pausas são 1, 2, 4, 8 e 8 segundos. Quota explicitamente esgotada, autenticação,
modelo indisponível, resposta inválida e erros internos não são repetidos. O histórico
é restaurado antes de repetir; os SDKs mantêm suas retentativas internas desativadas.
As ferramentas locais não são executadas novamente por uma retentativa de transporte.

Respostas incluem `request_id`. Logs do logger `steam_atlas.agent` contêm somente
ID, resultado, tempo, tentativas, retentativas, quantidade de ferramentas e categoria
de validação. Não incluem consultas, reviews, argumentos ou exceções do provedor.
A interface preserva os códigos e mostra instruções adequadas; mensagens interrompidas
podem ser restauradas para edição. Parar a espera no navegador não cancela uma
chamada já aceita; o backend continua sujeito ao seu prazo.

## Avaliação reproduzível do chat

Os cenários fixos ficam em `validation/agent/chat_cases.json`. O modo offline mede
somente recuperação local por mensagem isolada; não simula interpretação do modelo.

```powershell
.venv/Scripts/python.exe manage.py agent_evaluate --output validation/local_agent_evaluation.json
```

Para chamadas reais, escolha explicitamente modelo, provedor e variável da chave:

```powershell
.venv/Scripts/python.exe manage.py agent_smoke --chat --provider google --model gemini-3.1-flash-lite --key-env STEAM_ATLAS_DEV_KEY --max-turns 20 --allow-charges
```

Alternativamente use `agent_evaluate --live` com os mesmos argumentos e `--output`.
O limite de turnos é verificado antes de iniciar cada turno; as retentativas de cada
turno continuam sujeitas aos limites descritos acima. Nenhuma troca automática de
modelo ocorre. Os cenários cobrem refinamentos, mudanças de preferência, comparação,
clarificação, dados ausentes, exclusões, referência histórica e DOOM/Brasil.

O relatório separa candidatos recuperados, jogos selecionados, citações exatas,
latência, retentativas e erros. Os artefatos de revisão incluem resposta completa e
buscas realizadas; são arquivos locais solicitados pelo operador, não logs HTTP.
Não há afirmação automática de melhoria nem promoção de rascunhos a julgamentos humanos.

Use `--judgments PATH` com um array JSON independente. Um julgamento de jogo tem
`case_id`, `turn` (índice iniciado em zero), `appid`, `relevant` e `supported` booleanos,
`reviewer` não vazio e `source: "human_reviewed"`. Para julgar o turno, omita `appid`
e use `constraint_preservation` e `clarification_appropriate` booleanos. `supported`
avalia se as evidências justificam a explicação; uma citação exata não prova isso.
Itens não revisados ficam `null`, com contagem de cobertura explícita. Preserve os
splits e rótulos de relevância existentes; não ajuste o sistema pelo conjunto de teste.

O seletor de provedor inclui OpenAI, Anthropic e Google mesmo quando o backend
está indisponível. Um aviso indica a falha e oferece **Retry provider connection**.
Selecionar o provedor não faz chamadas pagas; carregar modelos e conversar exigem
o backend Django em execução no endereço configurado pelo proxy Vite. O padrão é a porta 8000; `frontend/.env.local` pode definir `STEAM_ATLAS_API_TARGET=http://127.0.0.1:8001` para outra porta local.
