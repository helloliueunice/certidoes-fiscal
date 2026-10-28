# Esquema do catálogo de portais (data/portais.json) — versão 2

Cada item de portal (em `federais`, `estaduais[UF]` e `municipais["UF/Município"]`) tem:

| Campo | Tipo | Significado |
|---|---|---|
| `id`, `nome`, `tipo`, `orgao`, `url`, `url_verificacao`, `observacao`, `verificado_em`, `fonte` | — | como na versão 1 |
| `acesso` | `"captcha"` \| `"govbr"` \| `"certificado"` \| `"livre"` \| `"desconhecido"` | Como o **fiscal** chega à certidão de **terceiro** (a contratada) nesse portal. `govbr` = login com a conta gov.br do próprio servidor, sem captcha. `livre` = sem login e sem captcha. |
| `captcha` | `bool \| null` | Mantido por compatibilidade: `true` se `acesso == "captcha"`, `false` se `acesso` for `govbr`/`certificado`/`livre`, `null` se desconhecido. |
| `nivel_govbr` | `"bronze"` \| `"prata"` \| `"ouro"` \| `null` | Nível mínimo da conta gov.br, quando `acesso == "govbr"`. |
| `abrange_filiais` | `bool \| null` | A certidão emitida vale pela raiz do CNPJ (matriz + filiais). |
| `certidao_unica` | `bool \| null` | Só estaduais: uma certidão cobre débitos inscritos e não inscritos em dívida ativa (dispensa a segunda certidão). |
| `validade_tipica_dias` | `int \| null` | Validade usual da certidão emitida. |
| `prioridade` | `int` | Ordem de preferência dentro do mesmo tipo (1 = melhor rota; prefere sem captcha). |

Regras:
- Item sem confirmação em fonte oficial fica com `acesso: "desconhecido"` e `verificado_em: null`.
- O código deve tolerar itens antigos sem os campos novos (deduzir `acesso` de `captcha`).
- Contagem de "captchas a resolver" usa `acesso == "captcha"` (desconhecido conta como possível captcha, separado).
