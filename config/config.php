<?php
declare(strict_types=1);

/**
 * Configurações seguras da aplicação. Copie este arquivo para config.local.php
 * e preencha os dados do banco antes de publicar. config.local.php não deve ir ao Git.
 */
date_default_timezone_set('America/Fortaleza');

$localConfig = __DIR__ . '/config.local.php';
if (is_file($localConfig)) {
    require $localConfig;
}

defined('APP_NAME') || define('APP_NAME', 'Print Fornece');
defined('APP_ENV') || define('APP_ENV', 'production');
ini_set('display_errors', APP_ENV === 'development' ? '1' : '0');
ini_set('log_errors', '1');
// Caso o sistema fique em uma subpasta, ex.: /print-fornece, informe-a aqui.
defined('APP_URL') || define('APP_URL', '');
defined('APP_ROOT') || define('APP_ROOT', dirname(__DIR__));
defined('UPLOAD_DIR') || define('UPLOAD_DIR', APP_ROOT . '/uploads/pedidos');
defined('MAX_UPLOAD_BYTES') || define('MAX_UPLOAD_BYTES', 25 * 1024 * 1024);

defined('DB_HOST') || define('DB_HOST', 'localhost');
defined('DB_NAME') || define('DB_NAME', 'seu_banco');
defined('DB_USER') || define('DB_USER', 'seu_usuario');
defined('DB_PASS') || define('DB_PASS', 'sua_senha');
