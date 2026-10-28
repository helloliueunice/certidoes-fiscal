# MINUTA — Como reduzir os captchas na conferência mensal de certidões

> **MINUTA de guia prático para o fiscal.** Não substitui norma interna nem parecer jurídico.
> A decisão sobre o atesto é sempre do fiscal e do gestor do contrato.
> Pesquisa feita em 27/10/2026. As fontes estão em `docs/fontes.md`.
>
> **Plano institucional completo:** `docs/plano_minimizacao_captcha.md`. Ele organiza estas medidas
> nas camadas C0 a C4, com o responsável e a conta de captchas por camada, e traz a base legal de
> desburocratização. O requerimento aos emissores e o memorando à chefia estão em
> `docs/requerimento_canal_sem_captcha.md`. Este guia continua sendo o resumo prático para o fiscal.

## 1. Por que não contornar o captcha

- **Origem do documento.** O fiscal atesta que conferiu a certidão no emissor. Um documento obtido por robô ou por serviço de terceiros chega por um caminho que o fiscal não controla nem consegue demonstrar no processo.
- **Termos de uso e responsabilidade.** O captcha é um controle técnico do emissor para limitar o acesso automatizado. Burlá-lo contraria a finalidade do serviço e pode expor o servidor a apuração de responsabilidade. Em caso de dúvida, consulte a assessoria jurídica, nunca a ferramenta.
- **Dados fora do órgão.** Os serviços de quebra de captcha e as APIs comerciais recebem CNPJ e documentos do órgão, o que cria um risco de LGPD e de sigilo.
- **Fragilidade.** O emissor muda o captcha e o robô para de funcionar. O emissor pode também bloquear o IP do órgão, e aí todos os servidores do órgão ficam sem acesso.

**O caminho legítimo:** usar canais oficiais sem captcha, transferir a emissão para a contratada e diminuir quantas vezes cada documento precisa ser conferido.

## 2. As seis medidas, em ordem de impacto no número de captchas

| # | Medida | Efeito |
|---|---|---|
| 1 | **Consultar o SICAF primeiro** | Federal, FGTS e CNDT marcadas como **"Automática"** foram obtidas pelo SICAF por integração direta com o emissor. Isso elimina 3 captchas por contratada cadastrada. A consulta a cada pagamento já é exigida dos órgãos do SISG (IN SEGES/MP nº 3/2018, art. 31). |
| 2 | **Conferir só o que é novo ou vence** | Certidão já conferida e ainda válida na data do pagamento não precisa ser emitida nem validada de novo. Basta ler a data de validade, que não tem captcha (ver a seção 4). |
| 3 | **A contratada envia as certidões com a NF** | A emissão passa para a contratada (`docs/oficio_contratadas.md` e `docs/clausula_contratual.md`). O fiscal só valida o código de controle, uma vez por documento novo. |
| 4 | **Ofícios aos emissores estaduais e municipais** | Potencial alto, porque estadual e municipal são o que sobra depois do SICAF, mas o resultado é incerto. Não localizei serviço oficial (`docs/oficio_orgaos_emissores.md`). Para o pedido formal, use `docs/requerimento_canal_sem_captcha.md`. |
| 5 | **API Consulta CND (Conecta gov.br)** | Certidão federal sem captcha e com registro auditável. O efeito sobre os captchas é pequeno, porque a certidão federal vale 180 dias. O ganho maior é de automação e de prova (`docs/adesao_conecta.md`). |
| 6 | **Mutirão mensal** | Não reduz o número de captchas. Reduz o tempo: uma sessão fixa por mês, com os portais agrupados (todas as certidões da SEFAZ-X em sequência), em vez de interrupções espalhadas. |

## 3. Estimativa de captchas por contratada/mês

**Premissas conservadoras (pior caso razoável):**
- cada emissão e cada validação de autenticidade custam 1 captcha;
- o Estado emite 1 certidão (em UFs com 2 certidões, como SP, some 1 ao estadual);
- validades: certidão federal 180 dias (catálogo da API CND); CNDT 180 dias (CLT, art. 642-A, § 4º); CRF **30 dias** (confirmar no próprio certificado); estadual e municipal **30 dias** (pior caso; o prazo real varia por ente e deve ser conferido em `data/portais.json`);
- validações por mês de cada certidão = 30 ÷ validade em dias.

**Antes (o fiscal emite tudo, todo mês):**
federal 1 + CRF 1 + CNDT 1 + estadual 1 + municipal 1 = **5 captchas** (6 em UF com 2 certidões).

**Depois, cenário A (contratada no SICAF, nível III "Automática"):**
federal 0 + CRF 0 + CNDT 0 (SICAF) + estadual 30/30 = 1 + municipal 30/30 = 1 → **2 captchas** no pior caso.
Com validades estadual e municipal de 60 e 90 dias: 30/60 + 30/90 = 0,5 + 0,33 → **cerca de 1**.

**Depois, cenário B (contratada fora do SICAF, órgão com Conecta):**
federal 0 (API) + CRF 30/30 = 1 + CNDT 30/180 ≈ 0,17 + estadual 1 + municipal 1 → **cerca de 3,2** no pior caso.
Sem Conecta, a certidão federal soma 30/180 ≈ 0,17, e o total fica em **cerca de 3,3**.

**Ressalvas:**
- O acesso ao SICAF e ao Conecta exige login gov.br e credencial, que contam por sessão e não por contratada.
- Esta conta não inclui reemissões por certidão positiva ou recusada.
- Meça a linha de base real na Fase 0 do `docs/roadmap.md`. O indicador é **captchas por contratada/mês**.

## 4. "Posso aceitar certidão emitida antes, mas ainda dentro da validade?"

**O que é seguro afirmar (confirmado em fonte oficial):**
1. **Antes de cada pagamento, a Administração deve verificar se o contratado mantém as condições de habilitação.** A regra está na IN SEGES/ME nº 77/2022, art. 8º, caput, conforme o Portal de Compras. Se houver irregularidade, a Administração notifica o contratado (§ 2º). A perda das condições, por si só, não autoriza reter o pagamento (§ 1º). A retenção só cabe até o limite dos prejuízos e das multas (§ 4º, que remete ao art. 139, IV, da Lei nº 14.133/2021).
2. **Órgãos do SISG devem consultar o SICAF a cada pagamento.** A regra está na IN SEGES/MP nº 3/2018, art. 31. Havendo irregularidade, a Administração notifica o contratado para regularizar ou apresentar defesa em 5 dias úteis, prorrogáveis uma vez (incisos I e II). Os pagamentos seguem até a decisão sobre a rescisão (inciso V). A IN consta como vigente no Portal de Compras, e não localizei ato que a revogue.
3. A Lei nº 14.133/2021 impõe ao contratado o dever de manter as condições de habilitação durante toda a execução (art. 92, XVI). Ela também manda verificar a regularidade fiscal antes de formalizar ou prorrogar o contrato (art. 91, § 4º). **Não localizei na Lei** um dispositivo que exija certidão **nova** a cada pagamento.
4. **Não localizei norma federal que exija certidão emitida no mês do pagamento.** A exigência é de regularidade verificada na data do pagamento, e a certidão dentro do prazo de validade fixado pelo emissor é o meio usual de prova. A orientação do TJBA que consultei pede a conferência da validade e da autenticidade, sem exigir emissão no mês.
5. Ao usar o SICAF para federal, FGTS e CNDT ("Automática"), o fiscal vê a situação mantida pelo próprio sistema por integração. **Atenção:** a declaração impressa do SICAF diz que é "simples consulta e não tem efeito legal". O fiscal deve consultar o SICAF diretamente e juntar o resultado ao processo, e não se apoiar apenas no PDF enviado pela contratada.

**Cuidados:**
- A certidão retrata a situação **na data da emissão**. Se o fiscal souber de certidão mais recente com resultado diferente, por exemplo positiva no SICAF ou no emissor, prevalece a mais recente. Esse entendimento aparece em orientação da antiga SLTI de 2012 sobre a CNDT na habilitação, que só encontrei em fontes secundárias (TRT12, Zênite). **Não confirmei o texto original.**
- Para estadual e municipal, o SICAF mostra apenas a validade do documento que o fornecedor enviou ("Manual"). Por isso, a autenticidade deve ser validada uma vez, pelo código de controle, quando o documento for novo.

**O que depende de norma interna ou do contrato:**
- Exigir certidão emitida há no máximo X dias, ou validar de novo a cada pagamento.
- O prazo de regularização para órgãos fora do SISG e para entes estaduais e municipais. A IN 3/2018 e a IN 77/2022 vinculam a Administração federal. Outros entes seguem o próprio regulamento.
- As exigências adicionais nos contratos com dedicação exclusiva de mão de obra (Lei nº 14.133/2021, art. 121, § 3º).

**O que não confirmei:**
- O texto literal do **Anexo XI da IN SEGES/MP nº 5/2017** (processo de pagamento). O portal do TCU o cita como exigindo a comprovação da regularidade fiscal junto com a nota fiscal, em regra por consulta ao SICAF. A IN SEGES/ME nº 98/2022, art. 1º, autoriza aplicar a IN 5/2017, "no que couber", aos serviços contratados pela Lei nº 14.133/2021.
- **Orientação específica da AGU ou da CGU** sobre aceitar certidão emitida em mês anterior. Não localizei.
- O prazo de validade do CRF em norma da Caixa (uso o que consta no certificado).
