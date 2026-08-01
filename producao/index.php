<?php
declare(strict_types=1);

$page_title = 'Produção';
require_once __DIR__ . '/../includes/header.php';

$filters = [
    'busca' => trim((string) ($_GET['busca'] ?? '')),
    'etapa' => (string) ($_GET['etapa'] ?? ''),
    'pagamento' => (string) ($_GET['pagamento'] ?? ''),
    'prioridade' => (string) ($_GET['prioridade'] ?? ''),
    'responsavel' => (int) ($_GET['responsavel'] ?? 0),
    'ordem' => (string) ($_GET['ordem'] ?? 'antigo'),
];

$columns = [
    'novo' => 'Pedido novo',
    'preparacao' => 'Preparação de arquivo',
    'producao' => 'Em produção',
    'pronto' => 'Pronto',
];
$where = ["p.etapa IN ('novo', 'preparacao', 'producao', 'pronto')"];
$params = [];
if ($filters['busca'] !== '') {
    $where[] = '(p.numero LIKE ? OR p.cliente_nome LIKE ? OR p.cliente_whatsapp LIKE ?)';
    $needle = '%' . $filters['busca'] . '%';
    array_push($params, $needle, $needle, $needle);
}
if (in_array($filters['etapa'], array_keys($columns), true)) { $where[] = 'p.etapa=?'; $params[] = $filters['etapa']; }
if (valid_enum($filters['pagamento'], payment_labels())) { $where[] = 'p.status_pagamento=?'; $params[] = $filters['pagamento']; }
if (in_array($filters['prioridade'], ['normal', 'urgente'], true)) { $where[] = 'p.prioridade=?'; $params[] = $filters['prioridade']; }
if ($filters['responsavel']) { $where[] = 'p.responsavel_id=?'; $params[] = $filters['responsavel']; }

$sql = 'SELECT p.id, p.numero, p.cliente_nome, p.descricao, p.valor_total, p.status_pagamento, p.previsao_entrega, p.prioridade, p.etapa, p.created_at, u.nome AS responsavel_nome,
        (SELECT COUNT(*) FROM pedido_arquivos a WHERE a.pedido_id=p.id AND a.removido_em IS NULL) AS anexos
        FROM pedidos p
        LEFT JOIN usuarios u ON u.id=p.responsavel_id
        WHERE ' . implode(' AND ', $where) . ' ORDER BY p.created_at ' . ($filters['ordem'] === 'recente' ? 'DESC' : 'ASC');
$stmt = db()->prepare($sql);
$stmt->execute($params);
$orders = $stmt->fetchAll();
$grouped = array_fill_keys(array_keys($columns), []);
foreach ($orders as $order) $grouped[$order['etapa']][] = $order;

$users = db()->query('SELECT id, nome FROM usuarios WHERE ativo=1 ORDER BY nome')->fetchAll();
$kpis = production_kpis();
?>
<div class="section-heading">
  <div><h2>Quadro de produção</h2><p>Arraste com mouse, toque ou caneta; pelo teclado, use “Mover para” em cada pedido.</p></div>
  <a class="btn btn-primary" href="<?= e(url('pedidos/novo.php')) ?>"><i class="fa-solid fa-plus"></i> Novo pedido</a>
</div>

<section class="kanban-kpis" aria-label="Indicadores gerais da produção">
  <article class="kanban-kpi"><span>Pedidos novos</span><strong data-kanban-kpi="novo"><?= $kpis['novo'] ?></strong></article>
  <article class="kanban-kpi"><span>Em preparação</span><strong data-kanban-kpi="preparacao"><?= $kpis['preparacao'] ?></strong></article>
  <article class="kanban-kpi"><span>Em produção</span><strong data-kanban-kpi="producao"><?= $kpis['producao'] ?></strong></article>
  <article class="kanban-kpi"><span>Prontos</span><strong data-kanban-kpi="pronto"><?= $kpis['pronto'] ?></strong></article>
  <article class="kanban-kpi"><span>Finalizados</span><strong data-kanban-kpi="finalizado"><?= $kpis['finalizado'] ?></strong></article>
  <article class="kanban-kpi kanban-kpi-alert"><span>Atrasados</span><strong data-kanban-kpi="atrasados"><?= $kpis['atrasados'] ?></strong></article>
</section>

<form class="card filters no-print" method="get">
  <label>Buscar<input name="busca" value="<?= e($filters['busca']) ?>" placeholder="Cliente, WhatsApp ou número"></label>
  <label>Etapa<select name="etapa"><option value="">Todas</option><?php foreach ($columns as $key => $label): ?><option value="<?= e($key) ?>" <?= $filters['etapa'] === $key ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select></label>
  <label>Pagamento<select name="pagamento"><option value="">Todos</option><?php foreach (payment_labels() as $key => $label): ?><option value="<?= e($key) ?>" <?= $filters['pagamento'] === $key ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select></label>
  <label>Prioridade<select name="prioridade"><option value="">Todas</option><option value="normal" <?= $filters['prioridade'] === 'normal' ? 'selected' : '' ?>>Normal</option><option value="urgente" <?= $filters['prioridade'] === 'urgente' ? 'selected' : '' ?>>Urgente</option></select></label>
  <label>Responsável<select name="responsavel"><option value="">Todos</option><?php foreach ($users as $user): ?><option value="<?= (int) $user['id'] ?>" <?= $filters['responsavel'] == $user['id'] ? 'selected' : '' ?>><?= e($user['nome']) ?></option><?php endforeach; ?></select></label>
  <label>Ordem<select name="ordem"><option value="antigo" <?= $filters['ordem'] !== 'recente' ? 'selected' : '' ?>>Mais antigo</option><option value="recente" <?= $filters['ordem'] === 'recente' ? 'selected' : '' ?>>Mais recente</option></select></label>
  <button class="btn btn-secondary btn-small" type="submit">Filtrar</button>
</form>

<p class="filter-note"><i class="fa-solid fa-circle-info"></i> Os indicadores mostram todos os pedidos ativos; as colunas abaixo respeitam os filtros aplicados.</p>
<div class="kanban" aria-label="Etapas de produção" data-kanban-filter-stage="<?= e($filters['etapa']) ?>">
  <?php foreach ($columns as $stage => $title): ?>
    <section class="kanban-column" data-stage="<?= e($stage) ?>" aria-labelledby="column-<?= e($stage) ?>">
      <div class="kanban-title"><span id="column-<?= e($stage) ?>"><?= e($title) ?></span><span data-stage-count><?= count($grouped[$stage]) ?></span></div>
      <div class="kanban-cards" data-stage-cards>
        <?php foreach ($grouped[$stage] as $order): $late = $order['previsao_entrega'] && strtotime($order['previsao_entrega']) < time(); ?>
          <?php $destinations = allowed_stage_transitions($stage); ?>
          <article class="order-card <?= $late ? 'is-late' : '' ?>" draggable="true" data-order-id="<?= (int) $order['id'] ?>" data-stage="<?= e($stage) ?>" data-allowed-stages="<?= e(implode(',', $destinations)) ?>">
            <a class="order-card-link" href="<?= e(url('producao/detalhes.php?id=' . (int) $order['id'])) ?>" aria-label="Abrir pedido <?= e($order['numero']) ?>">
              <div class="order-number"><?= e($order['numero']) ?></div>
              <h3><?= e($order['cliente_nome']) ?></h3>
              <p><?= e($order['descricao']) ?></p>
              <div class="order-meta"><strong><?= money($order['valor_total']) ?></strong><?= status_badge($order['status_pagamento'], 'payment') ?></div>
              <div class="order-details"><span><i class="fa-regular fa-clock"></i> <?= date_br($order['created_at'], true) ?></span><?php if ($order['anexos']): ?><span title="Possui anexos"><i class="fa-solid fa-paperclip"></i> <?= (int) $order['anexos'] ?></span><?php endif; ?></div>
              <?php if ($order['prioridade'] === 'urgente'): ?><div class="priority"><i class="fa-solid fa-triangle-exclamation"></i> Urgente</div><?php endif; ?>
              <?php if ($late): ?><div class="late"><i class="fa-solid fa-clock"></i> Prazo ultrapassado</div><?php endif; ?>
              <p><?= e($order['responsavel_nome'] ?: 'Sem responsável') ?></p>
            </a>
            <div class="order-card-actions">
              <label class="sr-only" for="move-order-<?= (int) $order['id'] ?>">Mover pedido <?= e($order['numero']) ?></label>
              <select id="move-order-<?= (int) $order['id'] ?>" data-order-move-select data-order-id="<?= (int) $order['id'] ?>" aria-label="Mover pedido <?= e($order['numero']) ?>">
                <option value="" selected>Mover para…</option>
                <?php foreach ($destinations as $targetStage): ?><option value="<?= e($targetStage) ?>"><?= e($columns[$targetStage]) ?></option><?php endforeach; ?>
              </select>
            </div>
          </article>
        <?php endforeach; ?>
        <?php if (!$grouped[$stage]): ?><div class="empty-state" data-empty-state><i class="fa-regular fa-folder-open"></i>Nenhum pedido</div><?php endif; ?>
      </div>
    </section>
  <?php endforeach; ?>
</div>
<?php require_once __DIR__ . '/../includes/footer.php'; ?>
