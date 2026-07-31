-- Índices opcionais para a dashboard Print Fornece.
-- Antes de executar, confira os índices atuais no phpMyAdmin (aba Estrutura)
-- ou rode: SHOW INDEX FROM nome_da_tabela;
-- Execute cada comando apenas se o índice indicado ainda não existir.

-- Alertas por etapa/prazo e etapa/tempo sem movimentação.
CREATE INDEX idx_pedidos_etapa_previsao ON pedidos (etapa, previsao_entrega);
CREATE INDEX idx_pedidos_etapa_atualizada ON pedidos (etapa, etapa_atualizada_em);

-- Filtros e gráfico de despesas por status e intervalo de data.
CREATE INDEX idx_despesas_status_data ON despesas (status, data_despesa);

-- Lista global das últimas movimentações.
CREATE INDEX idx_historico_criado_id ON pedido_historico (created_at, id);
