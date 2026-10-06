from django.db import migrations, models
import django.core.validators

class Migration(migrations.Migration):
    dependencies = [('automation_api', '0008_gmailmailbox')]
    operations = [
        migrations.AddField(model_name='birreceiptcheck', name='confirmation_pdf', field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name='birreceiptcheck', name='final_package', field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name='birreceiptcheck', name='final_package_sha256', field=models.CharField(blank=True, max_length=64, validators=[django.core.validators.RegexValidator('\\A[0-9a-f]{64}\\Z', 'Enter a lowercase SHA-256 digest.')])),
        migrations.AddField(model_name='birreceiptcheck', name='finalized_at', field=models.DateTimeField(blank=True, null=True)),
    ]
