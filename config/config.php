<?php
declare(strict_types=1);

/**
 * Configurações da aplicação.
 *
 * Em Docker, os valores são recebidos por variáveis de ambiente. O arquivo
 * config.local.php continua sendo suportado apenas para instalações legadas e
 * nunca deve ser versionado.
 */

function config_env(string $name, ?string $default = null): ?string
{
    $value = getenv($name);
    return $value === false || $value === '' ? $default : $value;
}

function config_bool(string $name, bool $default): bool
{
    $value = config_env($name);
    if ($value === null) {
        return $default;
    }

    return filter_var($value, FILTER_VALIDATE_BOOL, FILTER_NULL_ON_FAILURE) ?? $default;
}

$localConfig = __DIR__ . '/config.local.php';
if (is_file($localConfig)) {
    require $localConfig;
}

defined('APP_NAME') || define('APP_NAME', 'Print Fornece');
defined('APP_ENV') || define('APP_ENV', config_env('APP_ENV', 'production'));
defined('APP_DEBUG') || define('APP_DEBUG', config_bool('APP_DEBUG', false));
defined('APP_URL') || define('APP_URL', rtrim((string) config_env('APP_URL', ''), '/'));
defined('APP_ROOT') || define('APP_ROOT', dirname(__DIR__));
defined('TIMEZONE') || define('TIMEZONE', config_env('TIMEZONE', 'America/Fortaleza'));
date_default_timezone_set(TIMEZONE);

ini_set('display_errors', APP_ENV === 'development' && APP_DEBUG ? '1' : '0');
ini_set('log_errors', '1');
defined('UPLOAD_DIR') || define('UPLOAD_DIR', APP_ROOT . '/uploads/pedidos');
defined('MAX_UPLOAD_BYTES') || define('MAX_UPLOAD_BYTES', (int) config_env('MAX_UPLOAD_BYTES', (string) (25 * 1024 * 1024)));
defined('SESSION_SECURE') || define('SESSION_SECURE', config_bool('SESSION_SECURE', APP_ENV === 'production'));

defined('DB_HOST') || define('DB_HOST', config_env('DB_HOST', 'localhost'));
defined('DB_PORT') || define('DB_PORT', (int) config_env('DB_PORT', '3306'));
defined('DB_NAME') || define('DB_NAME', config_env('DB_NAME', 'print_fornece'));
defined('DB_USER') || define('DB_USER', config_env('DB_USER', 'print_fornece'));
defined('DB_PASS') || define('DB_PASS', config_env('DB_PASSWORD', ''));
