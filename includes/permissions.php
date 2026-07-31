<?php
declare(strict_types=1);

function current_user(): ?array
{
    static $userLoaded = false, $user = null;
    if ($userLoaded) return $user; $userLoaded = true;
    if (empty($_SESSION['user_id'])) return null;
    $stmt = db()->prepare('SELECT id,nome,email,perfil,ativo,forcar_troca_senha,ultimo_acesso FROM usuarios WHERE id=? AND ativo=1');
    $stmt->execute([$_SESSION['user_id']]); $user=$stmt->fetch() ?: null;
    if (!$user) { $_SESSION=[]; session_destroy(); } return $user;
}
function is_admin(): bool { return (current_user()['perfil'] ?? '') === 'administrador'; }
function require_login(): void
{
    $user = current_user();
    if (!$user) { flash('error','Faça login para continuar.'); redirect('login.php'); }
    $path = request_path();
    if (!empty($user['forcar_troca_senha']) && !str_contains($path, '/perfil/') && !str_ends_with($path, '/logout.php')) {
        flash('error', 'Por segurança, defina uma nova senha antes de continuar.'); redirect('perfil/index.php');
    }
}
function require_admin(): void
{
    require_login();
    if (!is_admin()) {
        flash('error', 'Acesso restrito a administradores.');
        redirect('producao/index.php');
    }
}
