<?php
declare(strict_types=1);

require_once __DIR__ . '/functions.php';
if (session_status() !== PHP_SESSION_ACTIVE) {
    ini_set('session.use_only_cookies', '1');
    ini_set('session.use_strict_mode', '1');
    $secure = is_https_request();
    session_name('print_fornece_session');
    session_set_cookie_params(['lifetime'=>0,'path'=>app_base_path() ?: '/','secure'=>$secure,'httponly'=>true,'samesite'=>'Lax']);
    session_start();
}
require_once __DIR__ . '/permissions.php';
