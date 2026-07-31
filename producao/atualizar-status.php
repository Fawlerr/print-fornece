<?php
declare(strict_types=1);

require_once __DIR__ . '/../includes/auth.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, private');

function stage_response(int $status, array $payload): never
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

if (!is_post()) stage_response(405, ['success' => false, 'message' => 'Método inválido.']);

$user = current_user();
if (!$user) stage_response(401, ['success' => false, 'message' => 'Sua sessão expirou. Entre novamente para continuar.']);
if (!empty($user['forcar_troca_senha'])) stage_response(403, ['success' => false, 'message' => 'Altere sua senha antes de movimentar pedidos.']);

$rawBody = file_get_contents('php://input');
if ($rawBody !== '') {
    $data = json_decode($rawBody, true);
    if (!is_array($data)) stage_response(400, ['success' => false, 'message' => 'Dados inválidos para movimentação.']);
} else {
    $data = $_POST;
}

if (!is_string($data['csrf_token'] ?? null) || !hash_equals($_SESSION['csrf_token'] ?? '', $data['csrf_token'])) {
    stage_response(419, ['success' => false, 'message' => 'Solicitação expirada. Atualize a página e tente novamente.']);
}

$orderId = filter_var($data['pedido_id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
$newStage = is_string($data['etapa'] ?? null) ? $data['etapa'] : '';
if ($orderId === false || !in_array($newStage, active_production_stages(), true)) {
    stage_response(422, ['success' => false, 'message' => 'Pedido ou etapa inválidos.']);
}

try {
    $order = order_by_id((int) $orderId);
    if (!can_access_order($order)) stage_response(404, ['success' => false, 'message' => 'Pedido não encontrado.']);

    $movement = change_order_stage((int) $orderId, $newStage, (int) $user['id']);
    stage_response(200, [
        'success' => true,
        'message' => 'Pedido movimentado com sucesso.',
        'pedido_id' => $movement['pedido_id'],
        'etapa_anterior' => $movement['etapa_anterior'],
        'nova_etapa' => $movement['nova_etapa'],
        'kpis' => production_kpis(),
    ]);
} catch (RuntimeException $exception) {
    stage_response(422, ['success' => false, 'message' => $exception->getMessage()]);
} catch (Throwable $exception) {
    error_log('Alterar etapa: ' . $exception::class);
    stage_response(500, ['success' => false, 'message' => 'Não foi possível movimentar o pedido agora. Tente novamente.']);
}
