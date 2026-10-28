# MINUTA — Ofícios aos órgãos emissores: consulta institucional à regularidade de fornecedores

> **MINUTA.** Preencher os campos entre colchetes e submeter à chefia antes de enviar.
> Os ofícios **perguntam** se há canal institucional. Não pedem acesso privilegiado, não pedem
> dispensa de captcha em portal público e não propõem nenhuma forma de contorná-lo.
> Pesquisa prévia feita em 27/10/2026. As fontes estão em `docs/fontes.md`.
>
> **Fundamentação de desburocratização e interoperabilidade** (Lei nº 14.129/2021, Lei nº 13.726/2018,
> Decreto nº 10.046/2019 e Decreto nº 9.094/2017), com o alcance de cada norma: ver
> `docs/plano_minimizacao_captcha.md`, seção 5. Para **pedir formalmente** o canal, e não apenas
> perguntar se ele existe, use o requerimento em `docs/requerimento_canal_sem_captcha.md`, Parte A.
> Se quiser reforçar estes ofícios, acrescente ao item 1 a frase opcional: "O pedido se alinha aos
> princípios de atuação integrada e de interoperabilidade da Lei nº 14.129/2021 (art. 3º, incisos IX
> e XIV)." Em ofícios a Estados e Municípios, verifique antes se o ente adotou a lei por ato próprio
> (art. 2º, inciso III).

## Resultado da pesquisa prévia (não integra os ofícios)

| Emissor | Canal oficial para órgão público consultar sem captcha | Situação em 27/10/2026 |
|---|---|---|
| Receita Federal/PGFN (certidão federal) | API Consulta CND, pelo Conecta gov.br | **Existe.** Ver `docs/adesao_conecta.md`. Não é preciso oficiar. |
| Caixa (CRF/FGTS) | — | **Não localizei** API, webservice ou convênio público para órgãos. O SICAF já obtém o CRF por integração direta com o emissor (a declaração do SICAF marca o item como "Automática"). |
| TST/CSJT (CNDT) | — | **Não localizei** webservice público para órgãos. O SICAF já obtém a CNDT por integração direta (item "Automática"). |
| Fazenda estadual | — | **Não localizei** integração das SEFAZ com o SICAF. No nível IV do SICAF (estadual e municipal), o próprio fornecedor faz o upload do documento. |
| Fazenda municipal | — | **Não localizei** integração com o SICAF nem serviço de consulta em lote. |

Rechecagem do catálogo do Conecta gov.br em 27/10/2026: não há API de CRF/FGTS, de CNDT nem de certidões estaduais ou municipais. Há APIs de CNPJ, Dívida Ativa da União e CADIN, que não substituem certidão.

Também existem APIs **comerciais** que consultam esses portais (uma delas oferece consulta de CRF e de CNDT). Elas **não são canais oficiais** e podem funcionar automatizando portais protegidos. Por isso **não devem ser usadas** (CLAUDE.md, princípios 1 e 2).

**Consequência prática:** quem usa o SICAF já tem federal, FGTS e CNDT sem captcha. Os ofícios (a) e (b) só fazem sentido para:
- órgãos que não usam o Compras.gov.br;
- contratadas não cadastradas no SICAF;
- quem quer integrar o CRF e a CNDT ao próprio sistema.

Os ofícios (c) e (d) são os de maior potencial, porque cobrem as certidões que hoje continuam dependendo de captcha.

---

## (a) Ofício à Caixa Econômica Federal — Certificado de Regularidade do FGTS (CRF)

**[NOME DO ÓRGÃO / UNIDADE]**
[Endereço] — [Cidade/UF] — [CEP]

Ofício nº [__]/[ANO]/[SIGLA DA UNIDADE]

[Cidade], [dia] de [mês] de [ano].

À
**Caixa Econômica Federal**
[Vice-Presidência / Superintendência responsável pelo FGTS — confirmar a unidade competente]
[Endereço ou e-mail institucional]

**Assunto:** Consulta sobre canal institucional para que órgãos públicos verifiquem o Certificado de Regularidade do FGTS (CRF) de seus contratados.

Senhor(a) [Cargo],

1. Este órgão acompanha, a cada pagamento, a manutenção das condições de habilitação de [__] empresas contratadas, entre elas a regularidade perante o FGTS. O fundamento são a Lei nº 14.133/2021 (art. 68, inciso IV, e art. 92, inciso XVI) e o regulamento federal que manda verificar essas condições antes de cada pagamento.

2. A verificação é feita hoje pela página pública "Consulta Regularidade do Empregador" (https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf). Essa página exige verificação humana (captcha) a cada consulta, o que representa cerca de [__] consultas manuais por mês nesta unidade. Reconhecemos que esse mecanismo protege o serviço público e não pretendemos contorná-lo.

3. Sabemos que o Sistema de Cadastramento Unificado de Fornecedores (SICAF) obtém o CRF por integração direta com a Caixa. Por isso, solicitamos informar:

   a) se a Caixa oferece a órgãos e entidades da Administração Pública **serviço, API, webservice ou convênio** para consultar a regularidade de empregadores perante o FGTS **sem captcha**, inclusive consulta por lote de CNPJ;
   b) se houver: os requisitos de adesão (instrumento jurídico, certificado digital, liberação de IP, custo por consulta) e a unidade de contato;
   c) se não houver: se existe **canal de atendimento específico para a Administração Pública** ou previsão de oferecê-lo;
   d) se o CRF obtido por meio do SICAF ou de outro sistema integrado tem o mesmo valor do certificado emitido na página pública, para fins de comprovação perante a Administração.

4. As informações serão usadas exclusivamente para a fiscalização de contratos administrativos. Os dados serão tratados conforme a Lei nº 13.709/2018 (LGPD).

5. Contato da unidade: [nome], [cargo], [telefone], [e-mail institucional].

Atenciosamente,

_____________________________________
**[Nome da autoridade signatária]**
[Cargo] — [Unidade]

---

## (b) Ofício ao Tribunal Superior do Trabalho / Conselho Superior da Justiça do Trabalho — CNDT

**[NOME DO ÓRGÃO / UNIDADE]**
[Endereço] — [Cidade/UF] — [CEP]

Ofício nº [__]/[ANO]/[SIGLA DA UNIDADE]

[Cidade], [dia] de [mês] de [ano].

Ao
**Tribunal Superior do Trabalho**
[Secretaria-Geral / Secretaria de Tecnologia da Informação — confirmar a unidade gestora do BNDT/CNDT]
[Com cópia ao Conselho Superior da Justiça do Trabalho, se cabível]
[Endereço ou e-mail institucional]

**Assunto:** Consulta sobre canal institucional para que órgãos públicos verifiquem a Certidão Negativa de Débitos Trabalhistas (CNDT) de seus contratados.

Senhor(a) [Cargo],

1. Este órgão acompanha, a cada pagamento, a manutenção das condições de habilitação de [__] empresas contratadas, entre elas a regularidade perante a Justiça do Trabalho. O fundamento é a Lei nº 14.133/2021 (art. 68, inciso V, e art. 92, inciso XVI).

2. A emissão e a validação da CNDT são feitas hoje pela página pública do TST, que exige verificação humana (captcha). Isso representa cerca de [__] consultas manuais por mês nesta unidade. Reconhecemos que esse mecanismo protege o serviço público e não pretendemos contorná-lo.

3. Sabemos que o SICAF obtém a CNDT por integração direta com o emissor. Por isso, solicitamos informar:

   a) se o TST ou o CSJT oferece a órgãos e entidades da Administração Pública **webservice, API, acordo de cooperação técnica ou outro serviço** para consultar a situação de pessoas jurídicas no Banco Nacional de Devedores Trabalhistas (BNDT), ou para emitir e validar a CNDT, **sem captcha**, inclusive por lote de CNPJ;
   b) se houver: os requisitos de adesão (instrumento, certificado digital, liberação de IP, limites de uso) e a unidade de contato;
   c) se não houver: se existe **canal específico para a Administração Pública** ou previsão de oferecê-lo.

4. As informações serão usadas exclusivamente para a fiscalização de contratos administrativos, conforme a Lei nº 13.709/2018 (LGPD).

5. Contato da unidade: [nome], [cargo], [telefone], [e-mail institucional].

Atenciosamente,

_____________________________________
**[Nome da autoridade signatária]**
[Cargo] — [Unidade]

---

## (c) Ofício à Secretaria de Estado da Fazenda / Economia — certidão estadual

> Enviar um ofício por UF de sede das contratadas. Quando o Estado emitir separadamente a certidão
> de débitos inscritos em dívida ativa (por exemplo, pela PGE), enviar cópia à Procuradoria-Geral do Estado.

**[NOME DO ÓRGÃO / UNIDADE]**
[Endereço] — [Cidade/UF] — [CEP]

Ofício nº [__]/[ANO]/[SIGLA DA UNIDADE]

[Cidade], [dia] de [mês] de [ano].

À
**Secretaria de Estado da Fazenda [ou: da Economia] de [UF]**
[Unidade responsável pela emissão de certidões / Receita Estadual]
[Com cópia à Procuradoria-Geral do Estado de [UF], se a certidão de dívida ativa for emitida separadamente]
[Endereço ou e-mail institucional]

**Assunto:** Consulta sobre serviço institucional para que órgãos públicos verifiquem a regularidade fiscal estadual de seus contratados.

Senhor(a) [Cargo],

1. Este órgão acompanha, a cada pagamento, a manutenção das condições de habilitação das empresas contratadas, entre elas a regularidade perante a Fazenda Estadual (Lei nº 14.133/2021, art. 68, inciso III, e art. 92, inciso XVI). Atualmente, [__] contratadas têm sede neste Estado.

2. A emissão e a validação das certidões são feitas hoje pela página pública [URL do portal — ver `data/portais.json`], que exige verificação humana (captcha). Reconhecemos que esse mecanismo protege o serviço e não pretendemos contorná-lo.

3. As certidões federais, do FGTS e trabalhistas já são obtidas pelo SICAF por integração com os emissores. As certidões estaduais, porém, continuam sendo inseridas manualmente no SICAF pelos fornecedores. Por isso, solicitamos informar:

   a) se a Secretaria oferece a órgãos e entidades da Administração Pública, inclusive de outros entes federativos, **webservice, API, convênio ou serviço** para consultar a situação fiscal de contribuintes **sem captcha**, inclusive por lote de CNPJ;
   b) se a Secretaria tem ou planeja **integração com o SICAF (Compras.gov.br)** ou com o cadastro de fornecedores do próprio Estado [nome do cadastro estadual, se houver], para que a certidão estadual seja obtida automaticamente;
   c) se houver serviço: os requisitos de adesão e a unidade de contato;
   d) se não houver: se existe **canal específico para a Administração Pública**, como acesso autenticado de servidor ou envio periódico de relação de CNPJ.

4. As informações serão usadas exclusivamente para a fiscalização de contratos administrativos, com observância do sigilo fiscal e da Lei nº 13.709/2018 (LGPD). Interessa a este órgão apenas a **situação de regularidade** que já é objeto de certidão pública, e não informações protegidas por sigilo.

5. Contato da unidade: [nome], [cargo], [telefone], [e-mail institucional].

Atenciosamente,

_____________________________________
**[Nome da autoridade signatária]**
[Cargo] — [Unidade]

---

## (d) Ofício à Secretaria Municipal de Fazenda / Finanças — certidão municipal

> Enviar um ofício por município de sede das contratadas, priorizando os municípios que concentram mais contratadas.

**[NOME DO ÓRGÃO / UNIDADE]**
[Endereço] — [Cidade/UF] — [CEP]

Ofício nº [__]/[ANO]/[SIGLA DA UNIDADE]

[Cidade], [dia] de [mês] de [ano].

À
**Secretaria Municipal de Fazenda [ou: Finanças] de [MUNICÍPIO/UF]**
[Unidade responsável pela emissão de certidões de tributos mobiliários]
[Endereço ou e-mail institucional]

**Assunto:** Consulta sobre serviço institucional para que órgãos públicos verifiquem a regularidade fiscal municipal de seus contratados.

Senhor(a) [Cargo],

1. Este órgão acompanha, a cada pagamento, a manutenção das condições de habilitação das empresas contratadas, entre elas a regularidade perante a Fazenda Municipal relativa aos tributos mobiliários (Lei nº 14.133/2021, art. 68, inciso III, e art. 92, inciso XVI). Atualmente, [__] contratadas têm sede neste Município.

2. A emissão e a validação das certidões são feitas hoje pela página pública [URL do portal — ver `data/portais.json`], que exige verificação humana (captcha). Reconhecemos que esse mecanismo protege o serviço e não pretendemos contorná-lo.

3. Solicitamos informar:

   a) se o Município oferece a órgãos públicos **webservice, API, convênio ou serviço** para consultar a situação fiscal de contribuintes **sem captcha**, inclusive por lote de CNPJ;
   b) se há integração, atual ou planejada, com o SICAF (Compras.gov.br) ou com cadastro estadual de fornecedores;
   c) se houver serviço: os requisitos de adesão e a unidade de contato;
   d) se não houver: se existe **canal específico para a Administração Pública**;
   e) o **prazo de validade** das certidões emitidas pelo Município e se a validação da autenticidade pelo código de controle exige captcha.

4. As informações serão usadas exclusivamente para a fiscalização de contratos administrativos, com observância do sigilo fiscal e da Lei nº 13.709/2018 (LGPD).

5. Contato da unidade: [nome], [cargo], [telefone], [e-mail institucional].

Atenciosamente,

_____________________________________
**[Nome da autoridade signatária]**
[Cargo] — [Unidade]

---

**Controle interno (não integra os ofícios):** registre cada ofício enviado, a data e a resposta em
uma planilha ou no processo SEI. Se a resposta indicar serviço oficial, atualize `data/portais.json`
e `docs/fontes.md` por meio do agente `integrador-oficial`.
