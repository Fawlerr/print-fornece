<?php
declare(strict_types=1);

require_once __DIR__ . '/../config/database.php';

function e(?string $value): string { return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function app_base_path(): string
{
    $parts = parse_url(APP_URL);
    $path = is_array($parts) ? ($parts['path'] ?? '') : APP_URL;
    $path = trim((string) $path, '/');
    return $path === '' ? '' : '/' . $path;
}
function url(string $path = ''): string { return rtrim(APP_URL, '/') . '/' . ltrim($path, '/'); }
function is_https_request(): bool
{
    if (SESSION_SECURE) {
        return true;
    }

    if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
        return true;
    }

    return strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
}
function asset_url(string $path): string
{
    $file = APP_ROOT . '/' . ltrim($path, '/');
    $version = is_file($file) ? (string) filemtime($file) : '';
    return url($path) . ($version !== '' ? '?v=' . rawurlencode($version) : '');
}
function redirect(string $path): never { header('Location: ' . url($path)); exit; }

function csrf_token(): string
{
    if (empty($_SESSION['csrf_token'])) $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    return $_SESSION['csrf_token'];
}
function csrf_input(): string { return '<input type="hidden" name="csrf_token" value="' . e(csrf_token()) . '">'; }
function validate_csrf(?string $token): void
{
    if (!is_string($token) || !hash_equals($_SESSION['csrf_token'] ?? '', $token)) {
        http_response_code(419); exit('Solicitação expirada ou inválida. Atualize a página e tente novamente.');
    }
}
function is_post(): bool { return ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST'; }
function flash(string $key, ?string $message = null): ?string
{
    if ($message !== null) { $_SESSION['flash'][$key] = $message; return null; }
    $value = $_SESSION['flash'][$key] ?? null; unset($_SESSION['flash'][$key]); return $value;
}
function money(float|int|string|null $value): string { return 'R$ ' . number_format((float) $value, 2, ',', '.'); }
function date_br(?string $date, bool $time = false): string
{
    if (!$date) return '—';
    try { return (new DateTime($date))->format($time ? 'd/m/Y H:i' : 'd/m/Y'); } catch (Throwable) { return '—'; }
}
function money_to_float(string $value): float
{
    $value = preg_replace('/[^0-9,.-]/', '', $value) ?? '';
    if (str_contains($value, ',')) $value = str_replace('.', '', $value);
    return (float) str_replace(',', '.', $value);
}
function client_ip(): ?string { return $_SERVER['REMOTE_ADDR'] ?? null; }
function request_path(): string { return strtok($_SERVER['REQUEST_URI'] ?? '', '?') ?: ''; }

function audit(string $action, string $entity, ?int $entityId = null, mixed $before = null, mixed $after = null): void
{
    $userId = $_SESSION['user_id'] ?? null;
    $stmt = db()->prepare('INSERT INTO auditoria (usuario_id, acao, entidade, entidade_id, dados_anteriores, dados_posteriores, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
    $stmt->execute([$userId, $action, $entity, $entityId,
        $before === null ? null : json_encode($before, JSON_UNESCAPED_UNICODE),
        $after === null ? null : json_encode($after, JSON_UNESCAPED_UNICODE),
        client_ip(), substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 500)]);
}
function notify_user(int $userId, string $title, string $message, ?string $link = null, string $type = 'pedido'): void
{
    $stmt = db()->prepare('INSERT INTO notificacoes (usuario_id, titulo, mensagem, link, tipo) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$userId, $title, $message, $link, $type]);
}
function notify_role(string $role, string $title, string $message, ?string $link = null, string $type = 'pedido'): void
{
    $stmt = db()->prepare('SELECT id FROM usuarios WHERE perfil = ? AND ativo = 1'); $stmt->execute([$role]);
    foreach ($stmt->fetchAll() as $user) notify_user((int) $user['id'], $title, $message, $link, $type);
}
function production_labels(): array { return ['novo'=>'Pedido novo','preparacao'=>'Preparação de arquivo','producao'=>'Em produção','pronto'=>'Pronto','finalizado'=>'Finalizado','cancelado'=>'Cancelado']; }
function active_production_stages(): array { return ['novo', 'preparacao', 'producao', 'pronto']; }
function allowed_stage_transitions(string $stage): array
{
    return [
        'novo' => ['preparacao'],
        'preparacao' => ['novo', 'producao'],
        'producao' => ['preparacao', 'pronto'],
        'pronto' => ['producao'],
    ][$stage] ?? [];
}
function can_transition_stage(string $from, string $to): bool
{
    return in_array($to, allowed_stage_transitions($from), true);
}
function payment_labels(): array { return ['nao_pago'=>'Não pago','parcial'=>'Parcialmente pago','pago'=>'Pago']; }
function valid_enum(string $value, array $allowed): bool { return array_key_exists($value, $allowed); }
function generate_order_number(): string
{
    return 'PF-' . date('Ymd-His') . '-' . random_int(1000, 9999);
}
function order_by_id(int $id): ?array
{
    $stmt = db()->prepare('SELECT p.*, r.nome AS responsavel_nome, c.nome AS criado_por_nome FROM pedidos p LEFT JOIN usuarios r ON r.id=p.responsavel_id LEFT JOIN usuarios c ON c.id=p.criado_por_id WHERE p.id=?');
    $stmt->execute([$id]); return $stmt->fetch() ?: null;
}
function can_access_order(?array $order): bool
{
    // A política atual concede a todos os usuários ativos acesso operacional aos
    // pedidos. A consulta do usuário atual e a verificação do pedido continuam
    // sendo obrigatórias: IDs enviados pelo navegador jamais autorizam acesso.
    return $order !== null && current_user() !== null;
}

function production_kpis(): array
{
    $stmt = db()->query(
        "SELECT
            COALESCE(SUM(CASE WHEN etapa = 'novo' THEN 1 ELSE 0 END), 0) AS novo,
            COALESCE(SUM(CASE WHEN etapa = 'preparacao' THEN 1 ELSE 0 END), 0) AS preparacao,
            COALESCE(SUM(CASE WHEN etapa = 'producao' THEN 1 ELSE 0 END), 0) AS producao,
            COALESCE(SUM(CASE WHEN etapa = 'pronto' THEN 1 ELSE 0 END), 0) AS pronto,
            COALESCE(SUM(CASE WHEN etapa = 'finalizado' THEN 1 ELSE 0 END), 0) AS finalizado,
            COALESCE(SUM(CASE WHEN etapa = 'cancelado' THEN 1 ELSE 0 END), 0) AS cancelado,
            COALESCE(SUM(CASE WHEN etapa IN ('preparacao', 'producao') THEN 1 ELSE 0 END), 0) AS em_andamento,
            COALESCE(SUM(CASE
                WHEN etapa IN ('novo', 'preparacao', 'producao', 'pronto')
                 AND previsao_entrega IS NOT NULL
                 AND previsao_entrega < NOW()
                THEN 1 ELSE 0 END), 0) AS atrasados
         FROM pedidos"
    );
    $kpis = $stmt->fetch() ?: [];
    foreach (['novo', 'preparacao', 'producao', 'pronto', 'finalizado', 'cancelado', 'em_andamento', 'atrasados'] as $key) {
        $kpis[$key] = (int) ($kpis[$key] ?? 0);
    }
    return $kpis;
}

function change_order_stage(int $orderId, string $newStage, array $user): array
{
    if ($orderId < 1 || !in_array($newStage, active_production_stages(), true)) {
        throw new RuntimeException('Etapa inválida para movimentação.');
    }

    $labels = production_labels();
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $stmt = $pdo->prepare('SELECT * FROM pedidos WHERE id=? FOR UPDATE');
        $stmt->execute([$orderId]);
        $order = $stmt->fetch();
        if (!$order || in_array($order['etapa'], ['finalizado', 'cancelado'], true)) {
            throw new RuntimeException('Pedido indisponível para movimentação.');
        }

        if (!can_access_order($order)) {
            throw new RuntimeException('Você não tem permissão para movimentar este pedido.');
        }

        $old = $order['etapa'];
        if (!in_array($old, active_production_stages(), true)) {
            throw new RuntimeException('O pedido não pode ser movimentado nesta etapa.');
        }
        if (!can_transition_stage($old, $newStage)) {
            throw new RuntimeException('Essa transição não é permitida para o pedido.');
        }

        $update = $pdo->prepare('UPDATE pedidos SET etapa=?, etapa_atualizada_em=NOW() WHERE id=? AND etapa=?');
        $update->execute([$newStage, $orderId, $old]);
        if ($update->rowCount() !== 1) {
            throw new RuntimeException('O pedido foi atualizado por outra operação. Atualize a página e tente novamente.');
        }

        $pdo->prepare('INSERT INTO pedido_etapas_historico (pedido_id, etapa_anterior, etapa_nova, usuario_id) VALUES (?, ?, ?, ?)')->execute([$orderId, $old, $newStage, $user['id']]);
        $message = 'Movido de ' . $labels[$old] . ' para ' . $labels[$newStage];
        $pdo->prepare('INSERT INTO pedido_historico (pedido_id, usuario_id, acao, descricao) VALUES (?, ?, "mudanca_etapa", ?)')->execute([$orderId, $user['id'], $message]);
        audit('mudanca_etapa', 'pedido', $orderId, ['etapa' => $old], ['etapa' => $newStage]);
        $pdo->commit();

        try {
            $link = 'producao/detalhes.php?id=' . $orderId;
            notify_role('administrador', 'Pedido atualizado', $order['numero'] . ': ' . $message, $link);
            if ($order['responsavel_id']) notify_user((int) $order['responsavel_id'], 'Etapa atualizada', $order['numero'] . ': ' . $message, $link);
        } catch (Throwable $notificationError) {
            error_log('Notificação de movimentação: ' . $notificationError->getMessage());
        }

        return ['pedido_id' => $orderId, 'etapa_anterior' => $old, 'nova_etapa' => $newStage, 'destinos_permitidos' => allowed_stage_transitions($newStage)];
    } catch (Throwable $exception) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $exception;
    }
}

function accepted_uploads(): array
{
    return ['pdf'=>['application/pdf'], 'png'=>['image/png'], 'jpg'=>['image/jpeg'], 'jpeg'=>['image/jpeg'], 'webp'=>['image/webp'], 'svg'=>['image/svg+xml','text/plain'], 'tiff'=>['image/tiff'], 'zip'=>['application/zip','application/x-zip-compressed'], 'cdr'=>['application/octet-stream','application/cdr','application/x-cdr','application/x-coreldraw','image/x-cdr'], 'ai'=>['application/pdf','application/postscript','application/illustrator'], 'eps'=>['application/postscript','application/eps','application/octet-stream'], 'psd'=>['image/vnd.adobe.photoshop','image/x-photoshop','application/octet-stream']];
}
function store_order_uploads(int $orderId, array $files, int $userId): int
{
    if (empty($files['name']) || !is_array($files['name'])) return 0;
    if (!is_dir(UPLOAD_DIR) && !mkdir(UPLOAD_DIR, 0775, true) && !is_dir(UPLOAD_DIR)) throw new RuntimeException('O armazenamento de anexos não está disponível no momento.');
    if (!is_dir(UPLOAD_DIR) || !is_writable(UPLOAD_DIR)) throw new RuntimeException('O armazenamento de anexos não está disponível no momento.');
    $finfo = new finfo(FILEINFO_MIME_TYPE); $allowed = accepted_uploads(); $count=0;
    foreach ($files['name'] as $i => $original) {
        $error=$files['error'][$i] ?? UPLOAD_ERR_NO_FILE; if ($error===UPLOAD_ERR_NO_FILE) continue;
        if ($error!==UPLOAD_ERR_OK) throw new RuntimeException('Falha no envio de um anexo.');
        $tmp=$files['tmp_name'][$i] ?? ''; $size=(int)($files['size'][$i] ?? 0); $ext=strtolower(pathinfo((string)$original, PATHINFO_EXTENSION));
        if (!$tmp || !isset($allowed[$ext]) || $size<1 || $size>MAX_UPLOAD_BYTES) throw new RuntimeException('Arquivo inválido ou maior que o limite permitido.');
        $mime=$finfo->file($tmp) ?: 'application/octet-stream'; if (!in_array($mime,$allowed[$ext],true)) throw new RuntimeException('Tipo de arquivo não permitido: '.e((string)$original));
        $stored=bin2hex(random_bytes(24)).'.'.$ext; if (!move_uploaded_file($tmp,UPLOAD_DIR.'/'.$stored)) throw new RuntimeException('Não foi possível armazenar o anexo.');
        @chmod(UPLOAD_DIR . '/' . $stored, 0664);
        db()->prepare('INSERT INTO pedido_arquivos (pedido_id,nome_original,nome_armazenado,mime_type,tamanho,criado_por_id) VALUES (?,?,?,?,?,?)')->execute([$orderId,basename((string)$original),$stored,$mime,$size,$userId]); $count++;
    }
    if ($count) audit('adicionou_anexo','pedido',$orderId,null,['quantidade'=>$count]); return $count;
}
function status_badge(string $status, string $kind = 'stage'): string { return '<span class="badge badge-' . e($status) . '">' . e(($kind==='payment'?payment_labels():production_labels())[$status] ?? $status) . '</span>'; }
