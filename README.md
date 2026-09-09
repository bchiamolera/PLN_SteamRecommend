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