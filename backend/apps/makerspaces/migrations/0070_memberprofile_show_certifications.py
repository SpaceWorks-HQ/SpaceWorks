from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0069_member_card_actions"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberprofile",
            name="show_certifications",
            field=models.BooleanField(
                default=False,
                help_text="Whether to publish held certifications on this member profile.",
            ),
        ),
    ]
