from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0005_stonelogintegracao_webhook_event_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='preco_especial_dtf_uv',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Preço diferenciado do metro de DTF UV (ex: R$ 75,00)',
                max_digits=10,
                null=True,
                verbose_name='preço especial DTF UV/metro',
            ),
        ),
        migrations.AlterField(
            model_name='cliente',
            name='preco_especial_metro',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Preço diferenciado do metro de DTF Têxtil (ex: R$ 35,00)',
                max_digits=10,
                null=True,
                verbose_name='preço especial DTF Têxtil/metro',
            ),
        ),
    ]
