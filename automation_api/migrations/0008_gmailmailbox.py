from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('automation_api', '0007_bir_receipt_check')]
    operations = [migrations.CreateModel(name='GmailMailbox', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('address', models.EmailField(blank=True, max_length=254)),
        ('app_password_ciphertext', models.TextField(blank=True)),
        ('updated_at', models.DateTimeField(auto_now=True)),
    ])]
