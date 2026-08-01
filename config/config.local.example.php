<?php
// Alternativa legada para instalações sem Docker. Em Docker, use apenas .env.
// Renomeie para config.local.php e substitua pelos dados da sua infraestrutura.
define('DB_HOST', 'localhost');
define('DB_PORT', 3306);
define('DB_NAME', 'seu_banco');
define('DB_USER', 'seu_usuario');
define('DB_PASS', 'sua_senha');
define('APP_ENV', 'production');
define('APP_URL', 'https://print.exemplo.com');
define('SESSION_SECURE', true);
define('TIMEZONE', 'America/Fortaleza');
