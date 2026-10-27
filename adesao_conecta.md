# MINUTA — Roteiro de adesão do órgão ao Conecta gov.br (API Consulta CND)

> **MINUTA de roteiro interno.** Este texto resume as páginas oficiais consultadas em 27/10/2026.
> Os procedimentos podem mudar. Confira sempre as páginas oficiais listadas em `docs/fontes.md`.

## 1. O que é

A **API Consulta CND** é mantida pela Receita Federal e disponibilizada pelo Conecta gov.br, com operação técnica do SERPRO. Ela permite que um sistema do órgão consulte, sem intervenção humana, a Certidão de Débitos Relativos a Créditos Tributários Federais e à Dívida Ativa da União (RFB/PGFN) de pessoas jurídicas, pessoas físicas e imóveis rurais.

- Se o contribuinte tiver certidão válida, a API devolve essa certidão. Se não tiver e não houver impedimento, emite uma nova. A certidão vale 180 dias.
- Se for consultado o CNPJ de uma filial, a consulta é feita pelo CNPJ da matriz.
- A API pode devolver o PDF da certidão em base64.
- Página do catálogo: https://www.gov.br/conecta/catalogo/apis/consultar-certidao-negativa-de-debito

## 2. Quem pode aderir

- O catálogo indica a adesão **"Para órgão Público Federal e Estadual"**.
- Órgãos municipais e de outros Poderes devem **confirmar a elegibilidade** com o Conecta (conecta@gestao.gov.br) antes de iniciar.

## 3. Papéis no órgão

| Papel | Função |
|---|---|
| **Dirigente de TI** | Responsável pela gestão estratégica de TI. Assina a solicitação de adesão. |
| **Responsável técnico** (gestor da chave) | Servidor indicado pelo órgão para gerar as credenciais. Também assina a solicitação. |
| Área de contratos | Demandante. Redige a **finalidade do acesso**, que é o motivo mais comum de negativa. |

Requisitos do responsável técnico:
- conta gov.br de nível **Prata ou Ouro**;
- para assinar o Termo de Responsabilidade: Assinador gov.br (selo Prata ou Ouro) **ou** certificado digital ICP-Brasil **e-CPF**, em nome do gestor cadastrado;
- algumas APIs exigem **e-CPF** para gerar a credencial de produção. A página da API CND menciona autenticação com **certificado digital tipo A**, por isso convém providenciar um e-CPF A1 ou A3;
- o Assinador Digital do SERPRO instalado, quando se usa certificado: https://www.serpro.gov.br/links-fixos-superiores/assinador-digital/assinador-serpro

## 4. Passo a passo

1. **Preparar a justificativa.** Descreva a finalidade: "verificação da regularidade fiscal federal de contratadas, no acompanhamento da execução contratual, antes do atesto e pagamento (Lei nº 14.133/2021, art. 92, XVI)". Indique também o volume mensal estimado de consultas (número de contratos × 12).
2. **Fazer o autocadastro na Plataforma Conecta.** O Dirigente de TI e o responsável técnico se cadastram em https://gestor.conectagov.estaleiro.serpro.gov.br/
3. **Aguardar a validação** do cadastro, que chega por e-mail com instruções.
4. **Registrar a solicitação de adesão** à API "CND - Consulta Certidão Negativa de Débitos", seguindo o Manual do Módulo de Adesão: https://www.gov.br/governodigital/pt-br/infraestrutura-nacional-de-dados/interoperabilidade/conecta-gov.br/manual-modulo-de-adesoes-conecta-gov-br-docx.pdf . A solicitação precisa das assinaturas do Dirigente de TI e do responsável técnico.
5. **Acompanhar a análise** em https://gestor.conectagov.estaleiro.serpro.gov.br/solicitacao-adesao/list . Se houver negativa, o sistema mostra a justificativa, e o pedido pode ser corrigido e reenviado.
6. **Assinar o Termo de Responsabilidade** com o Assinador gov.br ou o e-CPF.
7. **Solicitar a liberação do IP** de saída do servidor que fará as chamadas, pela Plataforma. Sem essa liberação, a API responde HTTP 403.
8. **Homologação.** Envie e-mail aos contatos técnicos com o nome da API, o nome e CPF do responsável pela chave, o órgão e a sigla, e o nome da aplicação consumidora. Teste com `CONECTA_AMBIENTE=homologacao`.
   - Instruções: https://www.gov.br/governodigital/pt-br/infraestrutura-nacional-de-dados/interoperabilidade/conecta-gov.br/acessar-os-servicos-do-conecta
9. **Produção.** Depois da aprovação e dos testes, gere a credencial de produção pela Plataforma, que é a chave de acesso do órgão.
10. **Configurar o sistema** só por variáveis de ambiente, no servidor do órgão. Nunca grave essas variáveis em código ou no git:
    ```
    CONECTA_CLIENT_ID=...
    CONECTA_CLIENT_SECRET=...
    CONECTA_AMBIENTE=producao        # ou homologacao
    CONECTA_CPF_USUARIO=...          # somente se o gateway exigir (a confirmar)
    ```
11. **Acompanhar o consumo** em https://gestor.conectagov.estaleiro.serpro.gov.br/relatorio-consumo . Para incluir, substituir ou excluir um gestor, escreva para conecta@gestao.gov.br informando nome, CPF e e-mail institucional.

## 5. Dados técnicos (resumo — ver `certidoes/conecta.py`)

| Item | Valor |
|---|---|
| Consulta (produção) | `POST https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnd/v1/ConsultaCnd/certidao` |
| Base de homologação | `https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnd-hom` |
| Token (produção) | `https://apigateway.conectagov.estaleiro.serpro.gov.br/oauth2/jwt-token` |
| Token (homologação) | **A confirmar:** o catálogo cita duas URLs diferentes |
| Corpo da requisição | `TipoContribuinte` (1=PJ), `ContribuinteConsulta` (CNPJ), `CodigoIdentificacao` ("9201"=PJ), `GerarCertidaoPdf` (true/false), `Chave` (só após status 7) |
| Resposta | `Status`, `Mensagem`, `Chave`, `Certidao{TipoContribuinte, ContribuinteCertidao, TipoCertidao, CodigoControle, DataEmissao, DataValidade, DocumentoPdf}` |
| Status | 1 encontrada; 2 emitida; 3 não emitida; 4 situação cadastral impeditiva; 5/6 tentar de novo; 7 em processamento (repetir com a Chave, intervalo mínimo de 500 ms; a chave vale 1 h); 8–15 erros de parâmetro ou chave; 99 erro do servidor |
| Cobrança | Respostas HTTP 200 e 201 são tarifadas. Repetir uma consulta com status 7 **sem** a Chave gera nova cobrança. |

## 6. Contatos oficiais

- **Conecta gov.br:** conecta@gestao.gov.br. O catálogo da API ainda mostra conecta@economia.gov.br, (61) 2020-2405, das 9h às 18h.
- **Responsável técnico pela API CND (SERPRO / RFB):** divac.df.ascif@rfb.gov.br, (61) 2021-7857, das 9h às 18h.
- **Suporte técnico Conecta (SERPRO):** lista-sungd-gdtgd@grupos.serpro.gov.br
- **Relato de incidente:** pelo portal de serviços gov.br (link na página "Acessar os serviços do Conecta").
