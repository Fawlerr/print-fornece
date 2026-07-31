<?php
declare(strict_types=1);

require_once __DIR__ . '/functions.php';
if (session_status() !== PHP_SESSION_ACTIVE) {
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
    session_name('print_fornece_session');
    session_set_cookie_params(['lifetime'=>0,'path'=>rtrim(APP_URL, '/') ?: '/','secure'=>$secure,'httponly'=>true,'samesite'=>'Lax']);
    session_start();
}
require_once __DIR__ . '/permissions.php';
