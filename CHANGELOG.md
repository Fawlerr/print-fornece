# Changelog — Print Fornece

Todas as atualizações e correções notáveis do sistema Print Fornece são registradas neste documento.

---

## [26/08/2026] — Inventário Geral de Estoque & Baixa Inteligente por Cor

### ✨ Atualizações de Estoque e Insumos
- **Inventário Geral de Estoque:**
  - Ajuste aditivo e auditado de todos os saldos de insumos em produção conforme contagem física oficial.
  - **DTF Têxtil:** Padronização das tintas com siglas de cor (M, C, BK, Y, WT em unidades), Pó TPU (21 kg) e Filme Têxtil (130 m).
  - **DTF UV:** Ajuste de tintas UV e verniz em unidades, e filmes DTF UV (A e B em 400 m).
  - **Grade Completa de Camisetas por Cor:** Reestruturação da grade de camisetas separando rigorosamente **100% Algodão** (Branca e Preta, do P ao XG) e **Dry Fit** (Branca e Preta, do P ao GG).
- **Baixa Automática Inteligente por Cor (`deduct_order_stock`):**
  - O algoritmo de baixa automática de estoque agora identifica automaticamente a cor selecionada no pedido (`Branca` ou `Preta`) além do tipo de malha e tamanho, debitando do insumo exato em estoque.
- **Histórico e Auditoria:**
  - Todos os saldos foram atualizados gerando registros formais de `Ajuste / Inventário` com rastreabilidade completa.

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
