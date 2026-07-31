<?php
declare(strict_types=1);
// Estrutura reservada: não confirma pagamentos e não chama serviços externos.
http_response_code(503);header('Content-Type: application/json; charset=utf-8');echo json_encode(['error'=>'Integração Stone ainda não habilitada.']);
