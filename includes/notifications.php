<?php
declare(strict_types=1);
function unread_notifications_count(int $userId): int { $s=db()->prepare('SELECT COUNT(*) FROM notificacoes WHERE usuario_id=? AND lida_em IS NULL');$s->execute([$userId]);return (int)$s->fetchColumn(); }
function recent_notifications(int $userId, int $limit=6): array { $s=db()->prepare('SELECT * FROM notificacoes WHERE usuario_id=? ORDER BY created_at DESC LIMIT ?');$s->bindValue(1,$userId,PDO::PARAM_INT);$s->bindValue(2,$limit,PDO::PARAM_INT);$s->execute();return $s->fetchAll(); }
