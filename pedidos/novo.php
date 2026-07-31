<?php
declare(strict_types=1);
$page_title='Novo pedido'; require_once __DIR__ . '/../includes/header.php';
$users=[]; if (is_admin()) $users=db()->query("SELECT id,nome FROM usuarios WHERE ativo=1 ORDER BY nome")->fetchAll();
?>
<div class="section-heading"><div><h2>Registrar pedido</h2><p>Os campos marcados são necessários para iniciar a produção.</p></div></div>
<form class="card form-card" method="post" action="<?= e(url('pedidos/salvar.php')) ?>" enctype="multipart/form-data" id="order-form" novalidate><?= csrf_input() ?>
  <div class="form-grid">
    <label>Nome do cliente<input name="cliente_nome" maxlength="150" required></label>
    <label>WhatsApp do cliente<input name="cliente_whatsapp" inputmode="numeric" data-whatsapp maxlength="25" placeholder="(84) 99999-9999" required></label>
    <label class="full">Descrição detalhada<textarea name="descricao" required maxlength="5000" placeholder="Ex.: quantidade, tamanhos, arte e observações do cliente"></textarea></label>
    <label>Valor total<input name="valor_total" data-money inputmode="decimal" placeholder="0,00" required></label>
    <label>Situação do pagamento<select name="status_pagamento" id="payment-status" required><option value="nao_pago">Não pago</option><option value="parcial">Parcialmente pago</option><option value="pago">Pago</option></select></label>
    <label>Valor pago<input name="valor_pago" data-money inputmode="decimal" placeholder="0,00" value="0,00"></label>
    <label>Forma de pagamento<select name="forma_pagamento"><option value="">Não definido</option><option value="pix">PIX</option><option value="cartao">Cartão</option><option value="dinheiro">Dinheiro</option><option value="transferencia">Transferência</option><option value="outro">Outro</option></select></label>
    <label>Data prevista para entrega<input name="previsao_entrega" type="datetime-local"></label>
    <label>Prioridade<select name="prioridade"><option value="normal">Normal</option><option value="urgente">Urgente</option></select></label>
    <?php if (is_admin()): ?><label>Responsável<select name="responsavel_id"><option value="">Definir depois</option><?php foreach($users as $u): ?><option value="<?= (int)$u['id'] ?>"><?= e($u['nome']) ?></option><?php endforeach; ?></select></label><?php endif; ?>
    <label class="full">Observações internas<textarea name="observacoes_internas" maxlength="5000" placeholder="Não aparecem para o cliente."></textarea></label>
    <label class="full">Arquivos da arte<input type="file" name="arquivos[]" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.svg,.cdr,.ai,.eps,.psd,.tiff,.zip"><span class="help">PDF, imagens, SVG, CDR, AI, EPS, PSD, TIFF ou ZIP. Máximo <?= (int)(MAX_UPLOAD_BYTES/1024/1024) ?> MB por arquivo.</span></label>
  </div><div class="form-actions"><a class="btn btn-secondary" href="<?= e(url('producao/index.php')) ?>">Cancelar</a><button class="btn btn-primary" type="submit"><i class="fa-solid fa-floppy-disk"></i> Salvar pedido</button></div>
</form>
<?php require_once __DIR__ . '/../includes/footer.php'; ?>
