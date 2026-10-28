# MINUTA — Plano de minimização de captchas na conferência mensal de certidões

> **MINUTA de plano técnico** (segurança da informação e desburocratização). Não substitui norma
> interna, parecer jurídico nem decisão da alta administração. A decisão sobre o atesto é sempre do
> fiscal e do gestor do contrato. Pesquisa feita em 27/10/2026. As fontes estão em `docs/fontes.md`,
> seção "Base legal — desburocratização".
>
> Documentos relacionados: guia do fiscal (`docs/estrategia_captcha.md`), requerimento aos emissores
> e memorando interno (`docs/requerimento_canal_sem_captcha.md`), ofícios de consulta
> (`docs/oficio_orgaos_emissores.md`), cláusula (`docs/clausula_contratual.md`) e adesão ao Conecta
> (`docs/adesao_conecta.md`).

## 1. Objetivo e limite

**Objetivo:** reduzir ao mínimo o número de captchas que o fiscal precisa resolver por contratada e por
mês, sem reduzir a segurança da verificação.

**Limite inegociável:** nenhuma medida deste plano contorna captcha. Onde houver captcha, um servidor
resolve. Só se reduz o número de captchas por **vias legítimas**: deixar de emitir, usar canais oficiais
que não têm captcha e obter canais institucionais junto aos emissores.

### 1.1 Por que não contornar o captcha (visão de segurança da informação)

| Risco | Explicação |
|---|---|
| **É um controle de segurança do emissor** | O captcha é um controle anti-automação: protege o serviço contra raspagem em massa, sobrecarga e uso abusivo. Contorná-lo é neutralizar um controle de segurança de outro órgão, e não um mero "atalho". |
| **Viola os termos de uso** | Os portais oferecem o serviço para uso humano, com o captcha como condição de acesso. Robôs, serviços de quebra de captcha e APIs comerciais que automatizam o portal usam o serviço fora da finalidade para a qual foi disponibilizado. |
| **Pode configurar acesso indevido** | Superar deliberadamente um mecanismo técnico de proteção pode, em tese, ser enquadrado como acesso indevido a sistema, com responsabilização administrativa, civil e até penal do servidor. A análise do enquadramento cabe à assessoria jurídica, e não à ferramenta. |
| **Bloqueio do IP do órgão** | O emissor detecta tráfego automatizado e bloqueia o endereço de origem. Como o órgão sai para a internet por poucos IPs, o bloqueio atinge **todos os servidores**, inclusive os que fazem consultas legítimas. |
| **Compromete a origem da prova** | O atesto pressupõe que o fiscal verificou a regularidade no emissor. Um documento obtido por robô ou por intermediário chega por um caminho que o fiscal não controla nem consegue demonstrar no processo. Isso fragiliza o atesto em auditoria. |
| **Dados fora do órgão (LGPD e sigilo)** | Os serviços de quebra de captcha e as APIs comerciais recebem do órgão a lista de CNPJs, os contratos e, às vezes, credenciais. É uma transferência de dados sem base contratual nem controle. |

## 2. Premissas da conta (conservadoras)

- Cada **emissão** e cada **validação de autenticidade** em portal com captcha custam **1 captcha**.
- Cinco certidões por contratada: federal (RFB/PGFN), CRF (FGTS), CNDT, estadual e municipal.
  Em UFs com duas certidões estaduais (por exemplo, SP: PGE e SEFAZ), some 1 ao estadual.
- Validades usadas na conta:
  - federal: **180 dias** (catálogo da API Consulta CND);
  - CNDT: **180 dias** (CLT, art. 642-A, § 4º; *conferir no Planalto*);
  - CRF: **30 dias** (conforme o próprio certificado; não localizei a norma da Caixa);
  - estadual e municipal: **30 dias** no pior caso. O prazo real varia por ente e deve ser conferido em `data/portais.json`.
- Certidões novas por mês = 30 ÷ validade em dias. Por exemplo, federal: 30 ÷ 180 ≈ 0,17.
- **Linha de base** (o fiscal emite tudo, todo mês): 1 + 1 + 1 + 1 + 1 = **5 captchas por contratada/mês** (6 em UF com 2 certidões estaduais).
- O login gov.br do servidor pode ter verificação própria. Ela conta **por sessão** e não por contratada, por isso fica fora do indicador.
- Reemissões por certidão positiva ou recusada não entram na conta.

## 3. As camadas, do maior impacto ao menor

Os números são **cumulativos**: cada camada parte do resultado da anterior.

### C0 — Não emitir (contratada envia e o fiscal só reconfere o que vence)

| Medida | Responsável |
|---|---|
| Cláusula contratual que obriga a contratada a enviar as certidões com a NF e a repor as que vencem antes do próximo pagamento (`docs/clausula_contratual.md`, itens [__].2, [__].3.2 e [__].5). Nos contratos vigentes, ofício às contratadas (`docs/oficio_contratadas.md`). | Unidade de contratos (minuta); assessoria jurídica (validação); gestor (ofício) |
| Aceitar a certidão **válida na data do pagamento**, sem exigir emissão no mês. A regra federal exige verificar a regularidade antes do pagamento (IN SEGES/ME nº 77/2022, art. 8º), e não localizei norma federal que exija certidão emitida no mês (ver `docs/estrategia_captcha.md`, seção 4). | Fiscal; gestor; norma interna, se houver |
| Validar a autenticidade pelo código de controle **uma vez por documento novo**. Nos meses seguintes, conferir apenas a data de validade, o que não exige captcha. | Fiscal (o sistema registra o código e a validade) |

**Conta:** o fiscal deixa de emitir e só valida o documento novo.
Federal 0,17 + CRF 1 + CNDT 0,17 + estadual 1 + municipal 1 = **3,33**.
**C0 elimina cerca de 1,7 captcha por contratada/mês** (de 5 para 3,3).

### C1 — Rotas oficiais sem captcha já disponíveis

| Medida | Responsável |
|---|---|
| **SICAF consultado pelo próprio fiscal.** Os itens federal, FGTS e CNDT marcados como **"Automática"** foram obtidos por integração direta com o emissor. A consulta exige o login do servidor, mas não tem captcha por contratada. Para os órgãos do SISG, a consulta a cada pagamento já é obrigatória (IN SEGES/MP nº 3/2018, art. 31). Juntar o resultado ao processo, e não apenas a declaração enviada pela contratada, que diz ser "simples consulta". | Fiscal |
| **Portais com login gov.br do servidor.** Onde o portal estadual ou municipal oferecer acesso autenticado pelo gov.br sem captcha, usar esse acesso, com a conta pessoal do servidor. A existência dessa rota por portal é levantada pelo agente `integrador-oficial` em `data/portais.json`. Não afirmo aqui quais portais a oferecem. | Fiscal; `integrador-oficial` (catálogo) |
| **Abrangência pela raiz do CNPJ.** A certidão federal vale para a matriz e as filiais. Uma única certidão (ou uma consulta) atende todos os contratos da mesma empresa no órgão. O sistema já trata a abrangência e marca a certidão de filial em amarelo. | Fiscal; sistema |

**Conta (contratada no SICAF com nível III "Automática"):** federal, CRF e CNDT saem da conta (−0,17 − 1 − 0,17).
Restam estadual 1 + municipal 1 = **2,0**.
**C1 elimina mais cerca de 1,3 captcha por contratada/mês** (de 3,3 para 2,0).
- Em cada ente cujo portal ofereça login gov.br sem captcha: −1 adicional por certidão desse ente. **No pior caso, 0**, até o levantamento ser confirmado.
- Raiz do CNPJ: elimina 0,17 por estabelecimento adicional da mesma empresa. **Na conta por contratada, 0.** O ganho aparece quando a mesma empresa tem vários contratos ou CNPJs no órgão.
- **Contratada fora do SICAF:** C1 não altera a conta, e o valor continua em **3,3**.

### C2 — Integração institucional com os emissores

| Medida | Responsável |
|---|---|
| **Adesão ao Conecta gov.br (API Consulta CND)** para a certidão federal, sem captcha, com registro auditável (`docs/adesao_conecta.md`, `certidoes/conecta.py`). Elegibilidade indicada no catálogo: órgãos federais e estaduais. Os demais devem confirmar com o Conecta. | Alta administração (decisão); TI (dirigente e responsável técnico); unidade de contratos (finalidade) |
| **Outras APIs oficiais.** No catálogo do Conecta consultado em 27/10/2026, **não localizei API de CRF/FGTS nem de CNDT**. Também não há API de certidões estaduais ou municipais. Há APIs correlatas (CNPJ, Dívida Ativa da União, CADIN) que **não substituem certidão** e não foram avaliadas para este fim. | `integrador-oficial` (acompanhar o catálogo) |
| **Requerimento fundamentado** às SEFAZ, às prefeituras, à Caixa, ao TST e à SGD/Conecta, pedindo canal sem captcha para órgãos públicos: consulta por login gov.br do servidor, API ou lote de CNPJs (`docs/requerimento_canal_sem_captcha.md`). A fundamentação está na Lei nº 14.129/2021, no Decreto nº 10.046/2019, no Decreto nº 9.094/2017 e na Lei nº 13.726/2018, com as ressalvas de alcance da seção 5. | Alta administração (assina); unidade de contratos (minuta e acompanhamento) |

**Conta:**
- **No SICAF:** o Conecta não altera a conta, porque a federal já saiu em C1. Cada SEFAZ ou prefeitura que atender ao requerimento elimina 1. **No pior caso (nenhuma resposta positiva), 0**, e a conta continua em **2,0**. No melhor caso, **0**.
- **Fora do SICAF:** Conecta −0,17, e a conta vai para **3,17**. Se a Caixa e o TST atenderem: −1 e −0,17. Se a SEFAZ e a prefeitura atenderem: −2.

### C3 — Organização do trabalho

| Medida | Responsável |
|---|---|
| **Mutirão mensal** em data fixa, com os portais agrupados (todas as certidões da SEFAZ-X em sequência). | Gestor; chefia da unidade |
| **Uma pessoa centraliza** a validação de autenticidade das certidões estaduais e municipais da unidade. Um documento que serve a vários contratos da mesma empresa é validado uma só vez. | Chefia da unidade de contratos |
| **Calendário de vencimentos** gerado pelo sistema, para pedir à contratada a reposição antes do vencimento (C0). | Sistema; fiscal |

**Conta:** **0 captcha** por contratada/mês no pior caso. O ganho é de **tempo**, porque as interrupções espalhadas viram uma sessão por mês. A centralização elimina validações duplicadas quando a mesma empresa tem vários contratos, mas esse ganho não entra no indicador por contratada.

### C4 — Segurança e trilha de auditoria (condição para todas as camadas)

| Regra | Responsável |
|---|---|
| **A conta gov.br é pessoal e intransferível.** Nunca compartilhar a senha nem usar a conta de outro servidor. Nunca automatizar a sessão gov.br (robô, extensão ou script que reaproveite cookies ou tokens). Cada servidor consulta com a própria conta. | Fiscal; chefia (orientação) |
| **Certificado digital do órgão** (e-CNPJ ou certificado de aplicação) só conforme a política de segurança do órgão e para a finalidade autorizada. O certificado de equipamento do Conecta fica sob guarda da TI, e as credenciais ficam em variáveis de ambiente, nunca no código. | TI; alta administração (política) |
| **LGPD.** As certidões de pessoa jurídica são documentos de acesso público. Mesmo assim, o processo trata dados pessoais: nome, CPF e login do fiscal e, às vezes, dados de sócios no PDF. Por isso, guardar o mínimo necessário, manter os dados no órgão e não enviar a terceiros (a IA vem desligada por padrão). | Fiscal; encarregado de dados; TI |
| **Trilha de auditoria.** Juntar ao processo, para cada certidão, o **código de controle**, a **data da verificação**, o canal (portal, SICAF, Conecta) e o servidor que verificou. O sistema registra esses campos no checklist. | Fiscal; sistema |

**Conta:** **0 captcha**. C4 não reduz captchas, mas é o que torna as camadas C0 a C2 defensáveis em auditoria.

## 4. Resumo do indicador (captchas por contratada/mês)

| Situação | Linha de base | Após C0 | Após C1 | Após C2 (pior caso) | Após C2 (melhor caso) |
|---|---|---|---|---|---|
| Contratada **no SICAF** ("Automática") | 5 | 3,3 | **2,0** | 2,0 | 0 |
| Contratada **fora do SICAF** | 5 | 3,3 | 3,3 | **3,2** (Conecta) | 0 |
| Validades estadual e municipal de 60 e 90 dias, no SICAF | 5 | 2,2 | **0,8** | 0,8 | 0 |

Em UF com duas certidões estaduais, some 1 à linha de base e 30 ÷ validade às demais colunas.

**Indicador oficial do projeto:** captchas resolvidos por contratada/mês, medidos pelo fiscal em cada
ciclo (Fase 0 do `docs/roadmap.md`). **Meta indicativa:** ≤ 2 no SICAF e ≤ 3,5 fora dele após C0 e C1,
com revisão após as respostas a C2.

## 5. Base legal e alcance (o que cada norma garante e o que não garante)

| Norma | Dispositivo confirmado | Alcance para este plano |
|---|---|---|
| Lei nº 13.726/2018 | Art. 1º (racionalização nos Poderes da União, dos Estados, do DF e dos Municípios, suprimindo exigências cujo custo supere o risco de fraude); art. 3º, § 1º (vedação de exigir prova de fato já comprovado); art. 3º, § 3º (órgão não exige do cidadão certidão expedida por outro órgão do mesmo Poder) | **Princípio de racionalização.** Atenção: o § 3º trata da relação com o **cidadão**, vale dentro do **mesmo Poder** e **excetua as informações sobre pessoa jurídica** (inciso II). Por isso **não obriga** o órgão a dispensar a certidão da contratada nem obriga o emissor a abrir canal. |
| Lei nº 14.129/2021 | Art. 3º, IX (atuação integrada e compartilhamento de dados em ambiente seguro), XIII (vedação de exigir prova de fato já comprovado) e XIV (interoperabilidade de sistemas); art. 38 (bases de dados devem considerar a interoperabilidade); art. 40 (publicidade dos registros de referência e dos mecanismos de interoperabilidade) | Fundamento principal do requerimento. Atenção: o art. 2º, III, só sujeita Estados, DF e Municípios que **adotarem a lei por ato normativo próprio**. Perante entes que não a adotaram, o argumento é de boa prática, e não de dever. A lei **não menciona API** expressamente. |
| Decreto nº 10.046/2019 | Art. 3º, I (a informação do Estado será compartilhada da forma mais ampla possível); art. 4º (níveis amplo, restrito e específico; o amplo abrange dados públicos sem restrição de acesso); art. 5º (dispensa convênio entre os órgãos do art. 1º). Alterado pelos Decretos nº 10.403/2020, nº 11.266/2022 e nº 11.574/2023, sem revogação localizada. | Alcança a administração federal direta, autárquica e fundacional e os demais Poderes da União, o que **inclui o TST**. **Não alcança** a Caixa (empresa pública), as SEFAZ nem as prefeituras. Reforça o pedido ao TST e à SGD/Conecta. |
| Decreto nº 9.094/2017 | Art. 1º, III (atuação integrada na expedição de certidões e documentos de regularidade); art. 2º, na redação do Decreto nº 10.279/2020 (o Executivo federal obtém diretamente da base oficial federal, e não exige do usuário, os documentos de regularidade que já constem dessa base); art. 7º (vedação de exigir prova de fato já comprovado). Vigente, com alterações. | Vincula o **Poder Executivo federal** e as bases **federais**. É argumento para que órgãos federais usem SICAF e Conecta em vez de exigir a certidão federal. Atenção: a contratada, na execução do contrato, não é propriamente "usuária de serviço público", e o dever contratual de manter a regularidade (Lei nº 14.133/2021, art. 92, XVI) continua com ela. |
| Lei nº 14.133/2021 | Art. 68, III a V (regularidade fiscal, social e trabalhista); art. 91, § 4º (verificar a regularidade antes de formalizar ou prorrogar); art. 92, XVI (manter a habilitação durante a execução); art. 87, caput (registro cadastral unificado no PNCP; nova redação atribuída à Lei nº 15.266/2025 por fonte secundária, *conferir no Planalto*); art. 88, § 2º (certificado de registro cadastral) | O registro cadastral é o caminho legal para concentrar a prova de regularidade. O caput do art. 70 ("A documentação referida neste Capítulo poderá ser: […]") foi confirmado no portal do TCU. O inciso que admite a substituição por registro cadastral **não foi lido em fonte oficial nesta sessão**. Confirmar antes de citar o número do inciso. |
| IN SEGES/ME nº 77/2022 | Art. 8º (verificar a manutenção das condições de habilitação antes de cada pagamento) | Base de C0 (validade na data do pagamento). |
| IN SEGES/MP nº 3/2018 | Art. 31 (consulta ao SICAF a cada pagamento, para o SISG) | Base de C1 (SICAF). |

## 6. O que o sistema já faz e o que depende de decisão do órgão

| O sistema já faz | Depende de decisão do órgão |
|---|---|
| Lê os PDFs das certidões por regras determinísticas, sem rede e sem captcha. | Incluir a cláusula nos contratos novos e oficiar as contratadas atuais (C0). Responsáveis: unidade de contratos e assessoria jurídica. |
| Aponta a validade e o vencimento em até 15 dias (amarelo), base do calendário de reposição (C0 e C3). | Adotar formalmente a regra "válida na data do pagamento" e "autenticidade uma vez por documento". Responsáveis: chefia e norma interna. |
| Trata a abrangência pela raiz do CNPJ e marca a certidão de filial (C1). | Orientar os fiscais a consultar o SICAF diretamente e juntar o resultado (C1). Responsável: chefia. |
| Lista os links oficiais de emissão e validação por contratada, com a indicação de captcha (`data/portais.json`). | Aderir ao Conecta: dirigente de TI, responsável técnico, e-CPF, liberação de IP e custo por consulta (C2). Responsáveis: alta administração e TI. |
| Traz o cliente da API Consulta CND pronto (`certidoes/conecta.py`), que só funciona depois da adesão. | Assinar e enviar o requerimento aos emissores e acompanhar as respostas (C2). Responsáveis: alta administração e unidade de contratos. |
| Gera o checklist e a minuta de atesto, com campos para o código de controle e a data de verificação (C4). | Designar o responsável pela centralização e a data do mutirão (C3). Responsável: chefia. |
| Mantém os dados no órgão, com a IA desligada por padrão (C4). | Aprovar a política de certificado digital e de guarda de credenciais (C4). Responsáveis: TI e alta administração. |
| **Não** resolve, contorna nem automatiza captcha, e **não** usa a sessão gov.br do servidor. | Medir o indicador a cada ciclo. Responsáveis: fiscal e gestor. |

## 7. Ordem de implantação sugerida

1. **Mês 1:** C0 e C1 (custo zero, sem depender de terceiros) e as regras de C4.
2. **Mês 1 e 2:** envio do requerimento (C2) e início da adesão ao Conecta.
3. **Contínuo:** C3 e medição do indicador. Atualizar este plano a cada resposta dos emissores, por meio do agente `integrador-oficial` (`data/portais.json`, `docs/fontes.md`).
