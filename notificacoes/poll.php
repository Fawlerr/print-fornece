<?php
declare(strict_types=1);
require_once __DIR__ . '/../includes/auth.php';require_once __DIR__ . '/../includes/notifications.php';require_login();header('Content-Type: application/json; charset=utf-8');echo json_encode(['unread'=>unread_notifications_count((int)current_user()['id'])]);
