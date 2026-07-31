<?php
declare(strict_types=1);

require_once __DIR__ . '/../includes/auth.php';
require_admin();

/**
 * Dashboard administrativa. Todas as datas usam America/Fortaleza, definido em
 * config/config.php. As consultas foram mantidas compatíveis com MySQL/MariaDB.
 */
$now = new DateTimeImmutable('now');
$todayStart = $now->setTime(0, 0);
$tomorrowStart = $todayStart->modify('+1 day');
$monthStart = $now->modify('first day of this month')->setTime(0, 0);
$nextMonthStart = $monthStart->modify('+1 month');
$trendStart = $todayStart->modify('-6 days');
$idleCutoff = $now->modify('-48 hours');

$stats = [
    'revenue_today' => 0.0,
    'revenue_month' => 0.0,
    'orders_today' => 0,
    'in_progress' => 0,
    'ready' => 0,
    'awaiting_payment' => 0,
    'stage_new' => 0,
    'stage_preparation' => 0,
    'stage_production' => 0,
    'stage_ready' => 0,
];
$expensesMonth = 0.0;
$recent = [];
$late = [];
$movements = [];
$trendRevenueByDay = [];
$trendExpensesByDay = [];
$dashboardError = false;

try {
    $pdo = db();
    $dateParams = [
        // Com ATTR_EMULATE_PREPARES=false, cada marcador recebe um nome próprio.
        ':today_revenue_start' => $todayStart->format('Y-m-d H:i:s'),
        ':today_revenue_end' => $tomorrowStart->format('Y-m-d H:i:s'),
        ':month_revenue_start' => $monthStart->format('Y-m-d H:i:s'),
        ':month_revenue_end' => $nextMonthStart->format('Y-m-d H:i:s'),
        ':orders_today_start' => $todayStart->format('Y-m-d H:i:s'),
        ':orders_today_end' => $tomorrowStart->format('Y-m-d H:i:s'),
    ];

    // Uma única varredura dos pedidos substitui os cards e o resumo por etapa.
    $statsStmt = $pdo->prepare(
        "SELECT
            COALESCE(SUM(CASE
                WHEN status_pagamento = 'pago' AND etapa <> 'cancelado'
                    AND created_at >= :today_revenue_start AND created_at < :today_revenue_end
                THEN valor_total ELSE 0 END), 0) AS revenue_today,
            COALESCE(SUM(CASE
                WHEN status_pagamento = 'pago' AND etapa <> 'cancelado'
                    AND created_at >= :month_revenue_start AND created_at < :month_revenue_end
                THEN valor_total ELSE 0 END), 0) AS revenue_month,
            COALESCE(SUM(CASE
                WHEN created_at >= :orders_today_start AND created_at < :orders_today_end
                THEN 1 ELSE 0 END), 0) AS orders_today,
            COALESCE(SUM(CASE WHEN etapa IN ('preparacao', 'producao') THEN 1 ELSE 0 END), 0) AS in_progress,
            COALESCE(SUM(CASE WHEN etapa = 'pronto' THEN 1 ELSE 0 END), 0) AS ready,
            COALESCE(SUM(CASE
                WHEN status_pagamento <> 'pago' AND etapa NOT IN ('cancelado', 'finalizado')
                THEN 1 ELSE 0 END), 0) AS awaiting_payment,
            COALESCE(SUM(CASE WHEN etapa = 'novo' THEN 1 ELSE 0 END), 0) AS stage_new,
            COALESCE(SUM(CASE WHEN etapa = 'preparacao' THEN 1 ELSE 0 END), 0) AS stage_preparation,
            COALESCE(SUM(CASE WHEN etapa = 'producao' THEN 1 ELSE 0 END), 0) AS stage_production,
            COALESCE(SUM(CASE WHEN etapa = 'pronto' THEN 1 ELSE 0 END), 0) AS stage_ready
         FROM pedidos"
    );
    $statsStmt->execute($dateParams);
    $stats = array_replace($stats, $statsStmt->fetch() ?: []);

    $expensesStmt = $pdo->prepare(
        "SELECT COALESCE(SUM(valor), 0)
         FROM despesas
         WHERE status = 'ativa'
           AND data_despesa >= :month_start
           AND data_despesa < :next_month_start"
    );
    $expensesStmt->execute([
        ':month_start' => $monthStart->format('Y-m-d'),
        ':next_month_start' => $nextMonthStart->format('Y-m-d'),
    ]);
    $expensesMonth = (float) $expensesStmt->fetchColumn();

    // O filtro por intervalo preserva o uso de idx_pedidos_criado; DATE só é usado no agrupamento.
    $revenueTrendStmt = $pdo->prepare(
        "SELECT DATE(created_at) AS day_key,
                COALESCE(SUM(CASE
                    WHEN status_pagamento = 'pago' AND etapa <> 'cancelado' THEN valor_total
                    ELSE 0 END), 0) AS total
         FROM pedidos
         WHERE created_at >= :trend_start AND created_at < :trend_end
         GROUP BY DATE(created_at)"
    );
    $revenueTrendStmt->execute([
        ':trend_start' => $trendStart->format('Y-m-d H:i:s'),
        ':trend_end' => $tomorrowStart->format('Y-m-d H:i:s'),
    ]);
    foreach ($revenueTrendStmt->fetchAll() as $row) {
        $trendRevenueByDay[$row['day_key']] = (float) $row['total'];
    }

    $expensesTrendStmt = $pdo->prepare(
        "SELECT data_despesa AS day_key, COALESCE(SUM(valor), 0) AS total
         FROM despesas
         WHERE status = 'ativa'
           AND data_despesa >= :trend_start AND data_despesa < :trend_end
         GROUP BY data_despesa"
    );
    $expensesTrendStmt->execute([
        ':trend_start' => $trendStart->format('Y-m-d'),
        ':trend_end' => $tomorrowStart->format('Y-m-d'),
    ]);
    foreach ($expensesTrendStmt->fetchAll() as $row) {
        $trendExpensesByDay[$row['day_key']] = (float) $row['total'];
    }

    $recent = $pdo->query(
        'SELECT id, numero, cliente_nome, valor_total, etapa
         FROM pedidos
         ORDER BY created_at DESC, id DESC
         LIMIT 7'
    )->fetchAll();

    $lateStmt = $pdo->prepare(
        "SELECT id, numero, cliente_nome, previsao_entrega, etapa
         FROM pedidos
         WHERE etapa IN ('novo', 'preparacao', 'producao')
           AND (
               (previsao_entrega IS NOT NULL AND previsao_entrega < :now)
               OR etapa_atualizada_em < :idle_cutoff
           )
         ORDER BY previsao_entrega IS NULL ASC, previsao_entrega ASC, etapa_atualizada_em ASC
         LIMIT 8"
    );
    $lateStmt->execute([
        ':now' => $now->format('Y-m-d H:i:s'),
        ':idle_cutoff' => $idleCutoff->format('Y-m-d H:i:s'),
    ]);
    $late = $lateStmt->fetchAll();

    $movements = $pdo->query(
        'SELECT h.descricao, h.created_at, p.numero, u.nome
         FROM pedido_historico h
         INNER JOIN pedidos p ON p.id = h.pedido_id
         LEFT JOIN usuarios u ON u.id = h.usuario_id
         ORDER BY h.created_at DESC, h.id DESC
         LIMIT 7'
    )->fetchAll();
} catch (PDOException $exception) {
    // Não registrar DSN, credenciais, cookies ou o texto da query em produção.
    error_log('Dashboard: falha de banco ao carregar indicadores. SQLSTATE: ' . (string) $exception->getCode());
    $dashboardError = true;
} catch (Throwable $exception) {
    error_log('Dashboard: falha inesperada ao carregar indicadores. Tipo: ' . $exception::class);
    $dashboardError = true;
}

$chartLabels = [];
$chartRevenue = [];
$chartExpenses = [];
for ($day = $trendStart; $day < $tomorrowStart; $day = $day->modify('+1 day')) {
    $key = $day->format('Y-m-d');
    $chartLabels[] = $day->format('d/m');
    $chartRevenue[] = $trendRevenueByDay[$key] ?? 0;
    $chartExpenses[] = $trendExpensesByDay[$key] ?? 0;
}

$stageStats = [
    (int) $stats['stage_new'],
    (int) $stats['stage_preparation'],
    (int) $stats['stage_production'],
    (int) $stats['stage_ready'],
];

$page_title = 'Visão geral';
require_once __DIR__ . '/../includes/header.php';

if ($dashboardError):
    http_response_code(500);
?>
<section class="card card-pad">
  <div class="empty-state">
    <i class="fa-solid fa-triangle-exclamation"></i>
    Não foi possível carregar os indicadores neste momento. Tente novamente em instantes.
  </div>
</section>
<?php
    require_once __DIR__ . '/../includes/footer.php';
    exit;
endif;
?>
<div class="section-heading"><div><h2>Resumo do negócio</h2><p>Dados atualizados diretamente do banco.</p></div><div class="button-row no-print"><a class="btn btn-secondary" href="<?= e(url('admin/despesas.php')) ?>"><i class="fa-solid fa-plus"></i> Adicionar despesa</a><a class="btn btn-primary" href="<?= e(url('pedidos/novo.php')) ?>"><i class="fa-solid fa-plus"></i> Novo pedido</a></div></div>

<div class="grid stats-grid"><div class="stat-card"><small>Faturamento de hoje</small><strong><?= money($stats['revenue_today']) ?></strong></div><div class="stat-card"><small>Faturamento do mês</small><strong><?= money($stats['revenue_month']) ?></strong></div><div class="stat-card danger"><small>Despesas do mês</small><strong><?= money($expensesMonth) ?></strong></div><div class="stat-card"><small>Lucro líquido do mês</small><strong><?= money((float) $stats['revenue_month'] - $expensesMonth) ?></strong></div><div class="stat-card"><small>Pedidos recebidos hoje</small><strong><?= (int) $stats['orders_today'] ?></strong></div><div class="stat-card"><small>Em andamento</small><strong><?= (int) $stats['in_progress'] ?></strong></div><div class="stat-card"><small>Prontos</small><strong><?= (int) $stats['ready'] ?></strong></div><div class="stat-card alert"><small>Aguardando pagamento</small><strong><?= (int) $stats['awaiting_payment'] ?></strong></div></div>

<div class="grid two-col"><section class="card chart-card"><h2>Faturamento e despesas · últimos 7 dias</h2><canvas id="financeChart"></canvas></section><section class="card chart-card"><h2>Pedidos por etapa</h2><canvas id="stageChart"></canvas></section></div>

<div class="grid two-col"><section class="card card-pad"><div class="section-heading"><h2>Pedidos recentes</h2><a class="text-green" href="<?= e(url('producao/index.php')) ?>">Ver produção</a></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Pedido</th><th>Cliente</th><th>Valor</th><th>Etapa</th></tr></thead><tbody><?php foreach ($recent as $order): ?><tr><td><a class="text-green" href="<?= e(url('producao/detalhes.php?id=' . (int) $order['id'])) ?>"><?= e($order['numero']) ?></a></td><td><?= e($order['cliente_nome']) ?></td><td><?= money($order['valor_total']) ?></td><td><?= status_badge($order['etapa']) ?></td></tr><?php endforeach; ?><?php if (!$recent): ?><tr><td colspan="4"><div class="empty-state">Nenhum pedido cadastrado.</div></td></tr><?php endif; ?></tbody></table></div></section><section class="card card-pad"><div class="section-heading"><h2>Últimas movimentações</h2></div><div class="timeline"><?php foreach ($movements as $movement): ?><div class="timeline-item"><strong><?= e($movement['numero']) ?> · <?= e($movement['descricao']) ?></strong><p><?= e($movement['nome'] ?: 'Sistema') ?> · <?= date_br($movement['created_at'], true) ?></p></div><?php endforeach; ?><?php if (!$movements): ?><div class="empty-state">Nenhuma movimentação registrada.</div><?php endif; ?></div></section></div>

<section class="card card-pad"><div class="section-heading"><h2>Alertas de produção</h2><p>Prazo ultrapassado ou mais de 48 h sem movimentação.</p></div><?php if ($late): ?><div class="table-wrap"><table class="data-table"><thead><tr><th>Pedido</th><th>Cliente</th><th>Etapa</th><th>Entrega prevista</th></tr></thead><tbody><?php foreach ($late as $order): ?><tr><td><a class="text-green" href="<?= e(url('producao/detalhes.php?id=' . (int) $order['id'])) ?>"><?= e($order['numero']) ?></a></td><td><?= e($order['cliente_nome']) ?></td><td><?= status_badge($order['etapa']) ?></td><td class="text-danger"><?= date_br($order['previsao_entrega'], true) ?></td></tr><?php endforeach; ?></tbody></table></div><?php else: ?><div class="empty-state"><i class="fa-solid fa-circle-check"></i>Nenhum pedido parado ou atrasado.</div><?php endif; ?></section>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
function dashboardChartPalette() {
  const styles = getComputedStyle(document.documentElement);
  return {text: styles.getPropertyValue('--text').trim(), muted: styles.getPropertyValue('--muted').trim(), line: styles.getPropertyValue('--line').trim(), green: styles.getPropertyValue('--green').trim(), red: styles.getPropertyValue('--red').trim(), blue: styles.getPropertyValue('--blue').trim(), yellow: styles.getPropertyValue('--yellow').trim()};
}
const chartPalette = dashboardChartPalette();
const financeChart = new Chart(document.getElementById('financeChart'), {type: 'line', data: {labels: <?= json_encode($chartLabels, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>, datasets: [{label: 'Faturamento', data: <?= json_encode($chartRevenue, JSON_PRESERVE_ZERO_FRACTION) ?>, borderColor: chartPalette.green, backgroundColor: 'rgba(15,157,87,.14)', fill: true, tension: .35}, {label: 'Despesas', data: <?= json_encode($chartExpenses, JSON_PRESERVE_ZERO_FRACTION) ?>, borderColor: chartPalette.red, backgroundColor: 'rgba(217,56,56,.12)', fill: true, tension: .35}]}, options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {labels: {color: chartPalette.text}}}, scales: {x: {ticks: {color: chartPalette.muted}, grid: {color: chartPalette.line}}, y: {ticks: {color: chartPalette.muted}, grid: {color: chartPalette.line}}}}});
const stageChart = new Chart(document.getElementById('stageChart'), {type: 'doughnut', data: {labels: ['Pedido novo', 'Preparação de arquivo', 'Em produção', 'Pronto'], datasets: [{data: <?= json_encode($stageStats) ?>, backgroundColor: [chartPalette.muted, chartPalette.yellow, chartPalette.blue, chartPalette.green]}]}, options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'bottom', labels: {color: chartPalette.text}}}}});
document.addEventListener('app:themechange', () => {
  const palette = dashboardChartPalette();
  financeChart.data.datasets[0].borderColor = palette.green;
  financeChart.data.datasets[1].borderColor = palette.red;
  financeChart.options.plugins.legend.labels.color = palette.text;
  financeChart.options.scales.x.ticks.color = financeChart.options.scales.y.ticks.color = palette.muted;
  financeChart.options.scales.x.grid.color = financeChart.options.scales.y.grid.color = palette.line;
  stageChart.data.datasets[0].backgroundColor = [palette.muted, palette.yellow, palette.blue, palette.green];
  stageChart.options.plugins.legend.labels.color = palette.text;
  financeChart.update(); stageChart.update();
});
</script>
<?php require_once __DIR__ . '/../includes/footer.php'; ?>
