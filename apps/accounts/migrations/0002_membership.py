from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def profiles_to_memberships(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    Membership = apps.get_model('accounts', 'Membership')
    for profile in UserProfile.objects.exclude(organization=None):
        Membership.objects.get_or_create(
            user_id=profile.user_id,
            organization_id=profile.organization_id,
            defaults={'role': profile.role},
        )


def memberships_to_profiles(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    Membership = apps.get_model('accounts', 'Membership')
    for membership in Membership.objects.order_by('organization__name'):
        UserProfile.objects.filter(user_id=membership.user_id, organization=None).update(
            organization_id=membership.organization_id, role=membership.role,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Membership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('admin', 'Admin'), ('leader', 'Team Leader'), ('member', 'Team Member')], default='member', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='accounts.organization')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Membership',
                'verbose_name_plural': 'Memberships',
                'ordering': ['organization__name'],
                'unique_together': {('user', 'organization')},
            },
        ),
        migrations.RunPython(profiles_to_memberships, memberships_to_profiles),
        migrations.RemoveField(
            model_name='userprofile',
            name='organization',
        ),
        migrations.RemoveField(
            model_name='userprofile',
            name='role',
        ),
    ]
