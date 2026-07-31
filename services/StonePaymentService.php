<?php
declare(strict_types=1);

/**
 * Ponto único para a futura integração Stone. Esta classe não faz chamadas HTTP
 * e não deve receber credenciais até que a integração real seja aprovada.
 */
final class StonePaymentService
{
    /** Preparará uma cobrança PIX vinculada a um pedido. */
    public function createPixCharge(int $pedidoId, float $valor): never { throw new LogicException('Integração Stone ainda não ativada.'); }
    /** Preparará um checkout de cartão vinculado a um pedido. */
    public function createCardCheckout(int $pedidoId, float $valor): never { throw new LogicException('Integração Stone ainda não ativada.'); }
    /** Consultará o status de uma cobrança Stone no futuro. */
    public function getPaymentStatus(string $externalId): never { throw new LogicException('Integração Stone ainda não ativada.'); }
    /** Validará e processará um webhook assinado quando a integração existir. */
    public function processWebhook(array $payload, array $headers): never { throw new LogicException('Webhook Stone desativado.'); }
}
