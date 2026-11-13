# Print Fornece — Guia de implantação dos ajustes A1 a A6

## 1. Depois do deploy (obrigatório)

1. Rode as migrações (o `entrypoint` do Docker já faz `python manage.py migrate`). Todas são **aditivas**:

   | Migração | O que faz |
   |---|---|
   | `business.0001_initial` | Cria a tabela de configurações do negócio (`pf_business_settings`, um único registro) |
   | `orders.0016_orderitem_shirt_discount` | Adiciona `discount_per_unit` e `discount_total` aos itens (padrão 0; pedidos antigos ficam com 0) |
   | `orders.0017_report_period_indexes` / `payments.0007_report_period_indexes` | Índices de data para os relatórios por período |
   | `business.0002_business_hours` | Dias e horário de funcionamento (padrão seg–sex, 8h–17h) |
   | `orders.0018_receipt_print` / `business.0003_receipt_print` | Campos de impressão da nota e tabela `pf_order_print_logs` |
   | `business.0004_cancellation_pin` / `production.0001_initial` | Hash da senha de cancelamento e tabela `pf_cancellation_attempts` |
   | `orders.0019_client_approval` | Data, IP e versão da aprovação do cliente |

2. Instale a nova dependência: `openpyxl` (já está no `requirements.txt`; o build da imagem instala).
3. **Defina a senha de cancelamento**: *Configurações → Senha de cancelamento*. **Enquanto ela não for definida, nenhum pedido pode ser cancelado.**
4. Defina o **valor do desconto por camisa** em *Configurações → Desconto em camisas* e marque "ativo". Ele vem **desativado**.
5. Confira o **horário de funcionamento** (vem seg–sex, 8h–17h).
6. Marque o **computador do balcão como estação de impressão** (seção 3).

## 2. Configurações (tela *Configurações*, só administradores)

| Seção | Campos | Padrão |
|---|---|---|
| Desconto em camisas | ativo, tipo (R$ fixo ou %), valor, quantidade mínima, modelos | desativado, R$ 0,00, mínimo 6, todos os modelos |
| Horário de funcionamento | dias, abre às, fecha às | seg–sex, 08:00–17:00 |
| Impressão da nota | impressão automática ativa, largura do papel | ativa, 80 mm |
| Senha de cancelamento | nova senha + confirmação | **não definida** |

## 3. Chrome em modo kiosk no PC do balcão (impressão sem confirmação)

1. No PC do balcão, instale a impressora térmica e deixe-a como **impressora padrão do Windows**
   (*Configurações → Bluetooth e dispositivos → Impressoras e scanners*; desligue
   "Permitir que o Windows gerencie minha impressora padrão").
2. Nas preferências da impressora, ajuste o papel para **80 mm** (ou 58 mm, igual ao configurado no sistema) e margens mínimas.
3. Crie um atalho na área de trabalho com o destino:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk-printing --user-data-dir="C:\PrintFornece\chrome-balcao" https://SEU-ENDERECO-DO-SISTEMA/production/
   ```
   - `--kiosk-printing`: imprime direto na impressora padrão, sem a janela de confirmação.
   - `--user-data-dir`: perfil separado, para não afetar o Chrome do dia a dia.
4. Feche **todas** as janelas do Chrome e abra pelo atalho novo (o parâmetro só vale se o Chrome for aberto por ele).
5. Entre no sistema, abra *Configurações → Impressão da nota* e marque **"Este computador é uma estação de impressão"**; dê um nome (ex.: "Balcão").
6. Teste: abra um pedido e clique em **Reimprimir nota**. A nota deve sair sem perguntar.
7. Deixe o sistema aberto (pode ser o Kanban). A estação confere a fila a cada 15 s.
8. Se aparecer a janela de impressão, o Chrome não foi aberto pelo atalho com `--kiosk-printing`: feche tudo e abra de novo pelo atalho.

## 4. Como testar cada função (computador e celular)

**A1. Desconto em camisas** (com o desconto ativo, ex.: R$ 3,00, mínimo 6)
1. *Novo pedido → 2. Camisas*: escolha Algodão, Preta, M, quantidade 5 → aparece só o atacado (R$ 25,00) e a dica "com mais 1 unidade… ganha desconto".
2. Adicione mais 1 camisa Preta M → a linha vira 6 un e o preço passa a R$ 22,00 (tabela R$ 28,00, atacado R$ 25,00, desconto −R$ 3,00).
3. Adicione 1 camisa Preta **G** → o desconto some (tamanhos misturados).
4. Salve o pedido e confira o desconto no card do Kanban, no detalhe, na página do cliente, na mensagem do WhatsApp, na nota e no relatório *Vendas por produto*.

Exemplos de conta (Algodão: tabela R$ 28,00, atacado R$ 25,00 a partir de 5 un; desconto R$ 3,00):

| Pedido | Preço por camisa | Total |
|---|---|---|
| 5 Pretas M | R$ 25,00 (só atacado) | R$ 125,00 |
| 8 Pretas, 5 M + 3 G | M: R$ 25,00 (atacado); G: R$ 28,00 (tabela) | R$ 125,00 + R$ 84,00 = R$ 209,00 |
| 8 Algodão, 4 Pretas M + 4 Brancas M | R$ 28,00 (cada linha tem só 4) | R$ 224,00 |
| 6 Pretas M | R$ 25,00 − R$ 3,00 = R$ 22,00 | R$ 132,00 (desconto R$ 18,00) |
| 8 Pretas M | R$ 22,00 | R$ 176,00 (desconto R$ 24,00) |

**A2. Relatórios**: abra *Relatórios*, clique nos atalhos (Hoje, Este mês…), escolha datas personalizadas, marque "Comparar com o período anterior" e exporte em CSV, Excel e PDF. Troque de aba: o período continua o mesmo. Copie o endereço da página e abra em outra aba: o mesmo período aparece. Coloque a data inicial depois da final: aparece o aviso de erro.

**A3. Horário**: confira a mensagem "Pronto para retirada" no detalhe do pedido (seg–sex, sábado e domingo fechado) e o rodapé da página do cliente. Mude o horário nas configurações e veja os dois textos mudarem.

**A4. Impressão**: com o PC do balcão configurado (seção 3), mova um card para *Pagamento confirmado*: a nota sai sozinha. Tire o card e devolva: o sistema pergunta antes de imprimir de novo. Use *Reimprimir nota* no card ou no detalhe. No celular nada é impresso sozinho.

**A5. Cancelamento**: no detalhe do pedido, *Cancelar pedido* → informe o motivo e uma senha errada (aparece "Senha de cancelamento incorreta. Restam N tentativa(s)"), depois a senha certa. Confira o histórico: quem cancelou, "autorizado com a senha de gerente" e o motivo.

**A6. Aprovação pelo link**: envie o orçamento pelo botão do WhatsApp, abra o link no celular (abrir não aprova) e toque em *Aprovar orçamento*. Com o Kanban aberto em outro computador, o card ganha o selo **APROVADO** com data e hora em até 15 s, sem recarregar. Tocar de novo mostra "já foi aprovado em…". A pessoa responsável pelo pedido recebe a notificação.
