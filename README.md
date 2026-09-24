# PLN_SteamRecommend

## Dicionário

### Classe Jogo

| Campo               | Descrição                            | Tipo             |
| ------------------- | ------------------------------------ | ---------------- |
| appid               | ID único do jogo                     | int              |
| name                | Nome do jogo                         | string           |
| last_modified       | Última modificação na página do jogo | timestamp (Unix) |
| price_change_number | Última modificação no preço do jogo  | int              |
| description         | Descrição do jogo                    | string           |
| genres              | Gêneros principais do jogo           | string           |
| user_tags           | Gêneros inseridos pelos usuários     | string           |

---

### Classe Review

| Campo             | Descrição                                  | Tipo                     |
| ------------------| ------------------------------------------ | ------------------------ |
| appid             | ID único do jogo                           | int                      |
| game_name         | Nome do jogo                               | string                   | 
| review_type       | Tipo de avaliação                          | `positive` ou `negative` |
| voted_up          | Avaliação positiva                         | bool                     |
| review            | Descrição da avaliação feita por usuário   | string                   |
| timestamp_created | Data de quando a avaliação foi feita       | timestamp (Unix)         |
| votes_up          | Quantas pessoas gostaram da review         | int                      |
| votes_funny       | Quantas pessoas acharam a review engraçada | int                      |
| weighted_score    | Peso de utilidade da review                | double                   |
| playtime_forever  | Tempo de jogo de quando a review foi feita | int                      |


---

### Justificativa e explicação da escolha

A base da Steam foi escolhida porque possui avaliações textuais de usuários e informações sobre os jogos. Esses dados são adequados para o objetivo do projeto, que é utilizar as opiniões de outros jogadores para recomendar jogos.

### Adequação dos dados às tarefas de PLN

A base apresenta um bom volume de avaliações e abrange diferentes jogos e gêneros. Também possui variedade de informações, como avaliações positivas e negativas, textos escritos livremente pelos usuários, gêneros, tags, tempo jogado e utilidade das avaliações.

Essa variedade permite utilizar técnicas de PLN para analisar os textos, identificar características e opiniões sobre os jogos e utilizar essas informações no sistema de recomendação.

### Organização e interpretabilidade da base de dados

Os dados estão divididos principalmente em duas estruturas:

* **Jogo:** possui informações como identificador, nome, descrição, gêneros e tags.
* **Review:** possui o jogo avaliado, o texto da avaliação, se ela é positiva ou negativa, número de votos, tempo jogado e outras informações.

As duas estruturas são relacionadas pelo `appid`, que identifica cada jogo. Essa organização facilita a compreensão e o processamento dos dados durante o desenvolvimento do sistema.


### Formato das exportacoes

Os notebooks exportam DataFrames como pickle comprimido com gzip (`.pkl.gz`, protocolo 5, nivel 1): catalogo e reviews em `_DadosBrutos/`, dados preparados em `_DadosLimpos/` e alternativas nas pastas `stemming/` e `lematizacao/`. Para ler, use `pd.read_pickle(caminho)`; as colunas de tokens continuam sendo listas Python.

Os arquivos JSON de controle (retomada, limite de requisicoes e cache de popularidade) mantem seu formato. O checkpoint de reviews acompanha `steam_reviews.pkl.gz` como `steam_reviews.pkl.gz.state.json`.

Comparacao no catalogo limpo atual: CSV 276.647.478 bytes; pickle 222.260.830 bytes; pickle com gzip 109.902.712 bytes (60,3% menor que o CSV). A economia depende dos dados. Os CSVs anteriores foram preservados; novas execucoes exportam pickle.
