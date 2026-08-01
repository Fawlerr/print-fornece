<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

require_once __DIR__ . '/../config/database.php';

function prompt_value(string $label): string
{
    fwrite(STDOUT, $label);
    $value = fgets(STDIN);
    return trim($value === false ? '' : $value);
}

$options = getopt('', ['email::', 'name::']);
$email = filter_var($options['email'] ?? prompt_value('E-mail do administrador: '), FILTER_VALIDATE_EMAIL);
$name = trim((string) ($options['name'] ?? prompt_value('Nome do administrador: ')));
$password = prompt_value('Senha inicial (mínimo de 8 caracteres): ');
$confirmation = prompt_value('Confirme a senha: ');

if (!$email || mb_strlen($name) < 3 || strlen($password) < 8 || !hash_equals($password, $confirmation)) {
    fwrite(STDERR, "Dados inválidos; nenhum usuário foi criado.\n");
    exit(1);
}

try {
    $pdo = db();
    $pdo->beginTransaction();
    $exists = $pdo->prepare('SELECT id FROM usuarios WHERE email = ?');
    $exists->execute([$email]);
    if ($exists->fetch()) {
        throw new RuntimeException('Já existe um usuário com esse e-mail.');
    }

    $insert = $pdo->prepare('INSERT INTO usuarios (nome, email, senha, perfil, ativo, forcar_troca_senha) VALUES (?, ?, ?, "administrador", 1, 1)');
    $insert->execute([$name, $email, password_hash($password, PASSWORD_DEFAULT)]);
    $pdo->commit();
    fwrite(STDOUT, "Administrador criado. A troca da senha será exigida no primeiro login.\n");
} catch (Throwable $exception) {
    if (isset($pdo) && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    fwrite(STDERR, "Não foi possível criar o administrador. Verifique o banco e tente novamente.\n");
    error_log('Criar administrador: ' . $exception::class);
    exit(1);
}
