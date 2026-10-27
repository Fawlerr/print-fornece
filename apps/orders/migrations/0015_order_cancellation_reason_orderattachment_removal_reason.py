from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0014_orderpayment_stone_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cancellation_reason',
            field=models.TextField(blank=True, default='', verbose_name='motivo do cancelamento'),
        ),
        migrations.AddField(
            model_name='orderattachment',
            name='removal_reason',
            field=models.TextField(blank=True, default='', verbose_name='motivo da remoção / cancelamento'),
        ),
    ]
