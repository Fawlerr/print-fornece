# Changelog — Print Fornece

Todas as atualizações e correções notáveis do sistema Print Fornece são registradas neste documento.

---

## [21/09/2026] — Correção do Bug #27, Alertas de Pagamento Pendente na Retirada & Sincronização de Parcelas de Caixa

### 🐛 Correções de Bugs & Melhorias Operacionais
- **Bug #27 (Desacoplamento Visual e Destaque de Pagamento Pendente no Kanban):**
  - Removido código JavaScript legado que forçava a badge para "Pago" quando um card era movimentado no Kanban para etapas avançadas (Em Produção, Pronto pra Retirada, Entregue). O card agora reflete rigorosamente a situação financeira real do pedido.
  - Implementado destaque visual de alto contraste para pedidos não pagos e marcados com "Pagamento na Retirada".
  - Adicionada tarja de advertência destacada na coluna **Pronto pra Retirada** (`⚠️ COBRAR NA RETIRADA: R$ XX,XX`) para impedir a entrega de pedidos sem o devido acerto financeiro.
  - Inserido banner de alerta reforçado de cobrança no cabeçalho financeiro do detalhe da produção.
- **Sincronização e Ajuste de Parcelas de Pagamento no Caixa:**
  - Sincronização automática em `update_order`: ao editar a forma de pagamento de um pedido com parcela única (ex: de PIX para Dinheiro), a parcela em `OrderPayment` é atualizada automaticamente para refletir com exatidão na conciliação diária de caixa.
  - Adicionada ferramenta no detalhe do pedido para administradores e desenvolvedores corrigirem a forma de pagamento de parcelas registradas em caso de digitação incorreta pelo operador.

---

## [20/09/2026] — Módulo Financeiro Avançado, Relatórios Gerenciais, Fatura Agrupada & Planos de Volume

### ✨ Novas Funcionalidades
- **Relatório de Vendas por Produto (`/reports/produtos/`):**
  - Apuração consolidada de quantidades vendidas, métricas por material/camisa e ticket faturado por item no período selecionado, com exportação para planilha CSV.
- **Relatório de Consumo Diário (`/reports/consumo-diario/`):**
  - Visão diária detalhada da saída de metros de DTF Têxtil, DTF UV, camisetas confeccionadas, serviços prestados e faturamento gerado dia a dia.
- **Relatório de Consumo de Tintas (`/reports/tintas/`):**
  - Painel de controle de estoque de tintas têxteis e UV com saldos atuais, histórico de saídas e modal de baixa rápida manual integrada ao módulo de insumos.
- **Pagamento Múltiplo por Pedido:**
  - Possibilidade de lançar e ratear múltiplos meios de pagamento no mesmo pedido (ex.: parte no PIX e parte no Dinheiro ou Cartão), com registro individualizado por parcela em `OrderPayment` e conciliação exata no fechamento de caixa.
- **Cupom Térmico Não Fiscal de Fechamento de Caixa:**
  - Layout especializado de impressão para impressoras térmicas de 80mm e 58mm no fechamento diário de caixa, com detalhamento das formas de pagamento, despesas e conferência de gaveta.
- **Item e Serviço Avulso no Orçamento:**
  - Nova aba "Item / Serviço Avulso" na calculadora de pedidos para inserção de valores extras, taxas de entrega, acabamentos manuais ou produtos personalizados diretamente na proposta.
- **Justificativa de Desconto e Abatimento (`discount_reason`):**
  - Campo auditável para documentar o motivo de concessão de descontos e abatimentos em orçamentos e pedidos.
- **Fatura Agrupada de Pedidos (`/orders/fatura-agrupada/`):**
  - Seleção de múltiplos pedidos de um mesmo cliente através de checkboxes no cadastro para emissão de fatura consolidada em formato A4 ou cupom térmico.
- **Aba de Plano de Volume e Assinatura no Cliente:**
  - Nova aba organizada no perfil do cliente para acompanhamento do saldo de metros, condições comerciais contratadas e formulário de recarga de créditos.
- **Status do Plano no Orçamento Público:**
  - Exibição transparente no link do cliente (`public_quote.html`) com o saldo consumido e a metragem restante do pacote contratado.
- **Liberação Automática da Capacidade da Impressora:**
  - Atualização do algoritmo de cálculo de capacidade do dia: pedidos avançados para "Pronto para Retirada" ou "Entregue" liberam a capacidade nominal da máquina, com barra secundária indicando o volume já concluído.
- **Bloqueio de Segurança Pós-Pagamento:**
  - Trava operacional que impede alteração indevida de pedidos com pagamento já confirmado ou em etapas avançadas, liberando a edição apenas com senha de Administrador/Gerente.
- **Navegação Segura e Botão Voltar:**
  - Botão de voltar e salvamento contínuo de rascunho em `sessionStorage` para não perder dados digitados na formulação de novos pedidos.
- **Mensagem Enxuta de WhatsApp para Orçamentos:**
  - Template minimalista e direto com medidas (cm e metros), total financeiro, prazo estimado e link de aprovação online.

---

## [29/08/2026] — Módulo de Fechamento de Caixa, Uploads em Tempo Real & Monitoramento de Usuários Online

### ✨ Novas Funcionalidades
- **Sistema de Fechamento e Conciliação de Caixa Diário (`/reports/caixa/`):**
  - Módulo completo de fechamento financeiro com apuração de faturamento bruto, entradas e saídas/despesas operacionais.
  - Discriminação detalhada por métodos de pagamento: Dinheiro, PIX, Cartão de Crédito, Cartão de Débito, Boleto e Faturado / A Prazo.
  - Conferência de gaveta (dinheiro físico), apuração automática de sobras ou quebras de caixa e emissão de termo de conferência de fechamento diário.
  - Integração de rotas diretas com ícone de Caixa no menu lateral, atalhos na visão geral de relatórios e botão de acesso rápido na tela de Produção Kanban.
- **Upload Inteligente de Arquivos com Barra de Progresso e Pré-visualização:**
  - Barra de progresso animada com indicador de porcentagem em tempo real durante o envio de arquivos de artes e comprovantes.
  - Pré-visualização instantânea (preview) no navegador de arquivos de imagem e PDFs antes e após a gravação do pedido.
  - Suporte otimizado a requisições assíncronas via AJAX para anexos adicionais sem recarregar a página.
- **Monitoramento de Usuários Online & Sessões em Tempo Real:**
  - Ferramenta interativa de monitoramento de colaboradores conectados posicionada na barra lateral diretamente acima do botão de Sair.
  - **Cronômetro ao Vivo (Stopwatch):** Contagem progressiva segundo a segundo do tempo que cada usuário está ativo na sessão atual.
  - **Desconexão Instantânea ao Fechar Aba:** Disparo de Web Beacon para encerrar imediatamente a sessão online no banco ao fechar a aba/navegador.
  - **Modo Stealth para Desenvolvedores:** Usuários com perfil Dev são 100% invisíveis na contagem e na listagem de usuários online para funcionários e administradores, ficando visíveis apenas para o próprio Dev.
  - **Histórico de Atividade:** Registro da última ação realizada com tempo decorrido ("Há 15 segundos", "Hoje às 21:30"), tela em que o operador se encontra e tipo de dispositivo (Desktop / Mobile).
  - Cronômetro pessoal na barra lateral inferior exibindo a duração da sessão do próprio usuário logado.

### 🐛 Correções de Bugs & Melhorias
- **Compatibilidade de Métodos de Pagamento:**
  - Aplicação de migration `0012_alter_order_payment_method` expandindo as escolhas de pagamento para total compatibilidade com o relatório de caixa.
- **Ajuste de Permissões em Despesas:**
  - Refinamento das regras de acesso ao módulo de despesas vinculadas ao fechamento diário.

---

## [26/08/2026] — Inventário Geral de Estoque, Correções Operacionais & Baixa Inteligente por Cor

### ✨ Correções e Atualizações de Estoque
- **Inventário Geral e Correção de Saldos:**
  - Ajuste aditivo e auditado de todos os 31 itens de insumos em produção conforme a contagem física oficial.
  - **DTF Têxtil:** Padronização e ajuste das tintas em unidades com siglas de cor (Magenta M: 6 un, Ciano C: 6 un, Black BK: 5 un, Yellow Y: 4 un, White WT: 94 un), Pó TPU (21 kg) e Bobina de Filme Têxtil (130 m).
  - **DTF UV:** Ajuste de tintas UV e verniz em unidades (Magenta M: 6 un, Ciano C: 6 un, Yellow Y: 6 un, Verniz V: 7 un, White WT: 8 un, Black BK: 6 un) e Filmes DTF UV A e B ajustados para 400 metros.
  - **Grade Completa de Camisetas por Cor e Tamanho:** Reestruturação da grade de camisetas separando rigorosamente **Camisa 100% Algodão** (Branca: P, M, G, GG, XG e Preta: P, M, G, GG) e **Camisa Dry Fit** (Branca: P, M, G, GG e Preta: P, M, G, GG), eliminando cadastros legados genéricos sem separação de cor.
- **Correção na Baixa Automática de Estoque (`deduct_order_stock`):**
  - O algoritmo de baixa automática de estoque agora identifica com precisão a cor do produto (`product_color`), tipo de malha e tamanho (com suporte a XG), debitando o insumo exato no estoque ao lançar pedidos.
- **Correção na Renderização de Movimentações de Sistema:**
  - Tratada a renderização de logs de auditoria quando o responsável é o próprio sistema (`mov.user` nulo), assegurando exibição limpa e estável.
- **Histórico e Auditoria de Inventário:**
  - Todas as correções foram aplicadas com criação de registros formais de `Ajuste / Inventário` com rastreabilidade completa.

---

## [25/08/2026] — Módulo de Backups & Correção de Bugs #23 e #24

### ✨ Novas Funcionalidades
- **Módulo de Gestão de Backups (`/backups/`):**
  - Geração manual de backup do banco de dados (`.sql.gz`) ou completo com mídias (`.zip`) através do painel administrativo com 1 clique.
  - **Download Imediato para o Desktop:** Botão de download direto no navegador para salvar cópias de segurança locais na máquina do operador.
  - **Comando Django CLI:** Implementado comando `python manage.py backup [--include-media] [--trigger=manual|automatic]` para execução em terminal e rotinas de agendamento.
  - **Rotina Automática na Madrugada:** Configurado para execução diária às 03:00 AM (Horário de Fortaleza) via Cron no servidor.
  - **Política de Retenção:** Expurgo automático de backups locais com mais de 30 dias para evitar o esgotamento de disco.
  - **Arquitetura Modular para Nuvem:** Provedor `GoogleDriveBackupProvider` estruturado e pronto para envio automático à pasta do Google Drive assim que as credenciais da Service Account forem preenchidas no `.env`.

### 🐛 Correções de Bugs
- **Bug #23 (Desacoplamento do Status de Pagamento no Fluxo Kanban):**
  - Desacoplada a movimentação física dos cards entre etapas de produção em relação ao status financeiro do pedido.
  - Pedidos com pagamentos parciais (ex: entrada de 50%) ou marcados com pagamento pendente na retirada agora mantêm rigorosamente seus saldos devedores sem quitação antecipada indevida.
- **Bug #24 (Discriminação de Entrada/Saldo Restante e Lançamento Rápido):**
  - Formatados os templates de mensagens do WhatsApp (*Orçamento*, *Pronto para Retirada* e *Entregue*) e a impressão térmica de 80mm com discriminação explícita de **Entrada Paga** e **Saldo Restante a Pagar na Retirada**.
  - Adicionado botão/modal no detalhe do pedido na produção para lançamento e alteração de pagamentos parciais ou totais antes da entrega.

---

## [24/08/2026] — Relatório de Produção, Baixa de Estoque e Abatimento de Pacotes
- **Relatório de Produção Diária (Metros/Dia):** Visão detalhada de metros rodados em DTF Têxtil e UV por colaborador e mês.
- **Baixa Automática de Estoque:** Abatimento automático de insumos (filmes DTF e camisetas) ao registrar novos pedidos.
- **Abatimento do Pacote do Cliente:** Débito automático do saldo de metros contratados no plano de volume.
- **Controle Manual de Pedido Pago:** Opção de 1 clique para alterar o status para "Pedido Pago".
- **Comprovante de Correção / Defeito:** Ajuste na impressão térmica da nota para reposições com valor R$ 0,00.
- **Central de Changelog na Barra Superior:** Modal com histórico de novidades exibido automaticamente no primeiro acesso diário.

---

## [22/08/2026] — Módulo de Insumos & Relato de Bugs
- **Central de Relatos de Bugs:** Módulo interno para registro e acompanhamento de bugs com upload de screenshots.
- **Estoque de Insumos:** Controle de saldos de tintas, pós e filmes para DTF Têxtil e DTF UV.
- **Comprovante Térmico de 80mm:** Emissão de recibos rápidos com snapshots imutáveis.
