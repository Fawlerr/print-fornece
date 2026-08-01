<?php
declare(strict_types=1);

require_once __DIR__ . '/../includes/functions.php';

function assert_same(mixed $expected, mixed $actual, string $label): void
{
    if ($expected !== $actual) {
        fwrite(STDERR, "Falhou: {$label}\nEsperado: " . var_export($expected, true) . "\nObtido: " . var_export($actual, true) . "\n");
        exit(1);
    }
}

assert_same(['preparacao'], allowed_stage_transitions('novo'), 'Novo somente avança para preparação');
assert_same(['novo', 'producao'], allowed_stage_transitions('preparacao'), 'Preparação permite retorno ou avanço');
assert_same(true, can_transition_stage('producao', 'pronto'), 'Produção avança para pronto');
assert_same(false, can_transition_stage('novo', 'pronto'), 'Novo não pula etapas');
assert_same(false, can_transition_stage('pronto', 'novo'), 'Pronto não retorna duas etapas');
assert_same(1234.56, money_to_float('R$ 1.234,56'), 'Conversão de moeda brasileira');
assert_same(true, valid_enum('pago', payment_labels()), 'Enum de pagamento válido');
assert_same(false, valid_enum('desconhecido', payment_labels()), 'Enum de pagamento inválido');

fwrite(STDOUT, "OK: regras de produção e validações puras.\n");
