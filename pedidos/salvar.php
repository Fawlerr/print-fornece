<?php
declare(strict_types=1);
require_once __DIR__ . '/../includes/auth.php'; require_login();
if (!is_post()) redirect('pedidos/novo.php'); validate_csrf($_POST['csrf_token'] ?? null);
try {
    $nome=trim((string)($_POST['cliente_nome']??'')); $whats=preg_replace('/\D/','',(string)($_POST['cliente_whatsapp']??'')); $descricao=trim((string)($_POST['descricao']??''));
    $total=money_to_float((string)($_POST['valor_total']??'')); $status=(string)($_POST['status_pagamento']??'nao_pago'); $pago=money_to_float((string)($_POST['valor_pago']??''));
    $forma=(string)($_POST['forma_pagamento']??''); $prioridade=(string)($_POST['prioridade']??'normal'); $previsao=trim((string)($_POST['previsao_entrega']??''));
    if (mb_strlen($nome)<2 || strlen($whats)<10 || mb_strlen($descricao)<3 || $total<=0) throw new RuntimeException('Preencha cliente, WhatsApp, descrição e um valor total válido.');
    if (!valid_enum($status,payment_labels()) || !in_array($prioridade,['normal','urgente'],true) || !in_array($forma,['','pix','cartao','dinheiro','transferencia','outro'],true)) throw new RuntimeException('Dados de pagamento ou prioridade inválidos.');
    if ($status==='pago') $pago=$total; if ($status==='nao_pago') $pago=0;
    if (($status==='parcial' && ($pago<=0 || $pago >= $total)) || $pago>$total) throw new RuntimeException('O valor pago não condiz com a situação de pagamento.');
    $due=null; if ($previsao!=='') { $due=(new DateTime($previsao))->format('Y-m-d H:i:s'); }
    $responsavel=null; if (is_admin() && !empty($_POST['responsavel_id'])) { $responsavel=(int)$_POST['responsavel_id']; $s=db()->prepare("SELECT id FROM usuarios WHERE id=? AND ativo=1");$s->execute([$responsavel]);if(!$s->fetch())throw new RuntimeException('Responsável inválido.'); }
    $user=current_user(); $pdo=db(); $pdo->beginTransaction();
    $numero=generate_order_number();
    $stmt=$pdo->prepare('INSERT INTO pedidos (numero,cliente_nome,cliente_whatsapp,descricao,valor_total,status_pagamento,valor_pago,forma_pagamento,previsao_entrega,prioridade,observacoes_internas,etapa,responsavel_id,criado_por_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,"novo",?,?)');
    $stmt->execute([$numero,$nome,$whats,$descricao,$total,$status,$pago,$forma?:null,$due,$prioridade,trim((string)($_POST['observacoes_internas']??''))?:null,$responsavel,$user['id']]); $id=(int)$pdo->lastInsertId();
    $pdo->prepare('INSERT INTO pedido_historico (pedido_id,usuario_id,acao,descricao) VALUES (?, ?, "criacao", "Pedido criado.")')->execute([$id,$user['id']]);
    $pdo->prepare('INSERT INTO pedido_etapas_historico (pedido_id,etapa_anterior,etapa_nova,usuario_id) VALUES (?,NULL,"novo",?)')->execute([$id,$user['id']]);
    store_order_uploads($id,$_FILES['arquivos']??[],$user['id']); $pdo->commit();
    notify_role('administrador','Novo pedido',$numero.' foi criado por '.$user['nome'].'.','producao/detalhes.php?id='.$id);
    notify_role('funcionario','Novo pedido',$numero.' entrou na fila de produção.','producao/detalhes.php?id='.$id);
    if($responsavel) notify_user($responsavel,'Pedido atribuído',$numero.' foi atribuído a você.','producao/detalhes.php?id='.$id);
    audit('criacao','pedido',$id,null,['numero'=>$numero,'valor_total'=>$total]); flash('success','Pedido '.$numero.' criado com sucesso.'); redirect('producao/index.php');
} catch (Throwable $e) { if (isset($pdo) && $pdo->inTransaction()) $pdo->rollBack(); error_log('Pedido salvar: '.$e->getMessage()); flash('error',$e instanceof RuntimeException ? $e->getMessage() : 'Não foi possível salvar o pedido.'); redirect('pedidos/novo.php'); }
