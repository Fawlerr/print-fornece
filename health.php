<?php
declare(strict_types=1);

require_once __DIR__ . '/config/database.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, private');

try {
    db()->query('SELECT 1');
    http_response_code(200);
    echo json_encode(['status' => 'ok']);
} catch (Throwable $exception) {
    error_log('Health check: ' . $exception::class);
    http_response_code(503);
    echo json_encode(['status' => 'unavailable']);
}
