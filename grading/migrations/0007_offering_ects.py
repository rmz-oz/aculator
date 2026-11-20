from django.db import migrations, models


def copy_course_ects(apps, schema_editor):
    Course = apps.get_model("grading", "Course")
    CourseOffering = apps.get_model("grading", "CourseOffering")
    db_alias = schema_editor.connection.alias

    course_ects = (
        Course.objects.using(db_alias)
        .filter(pk=models.OuterRef("course_id"))
        .values("ects")[:1]
    )
    CourseOffering.objects.using(db_alias).update(
        ects=models.Subquery(course_ects)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("grading", "0006_term_season_english"),
    ]

    operations = [
        migrations.AddField(
            model_name="courseoffering",
            name="ects",
            field=models.PositiveSmallIntegerField(null=True),
        ),
        migrations.RunPython(copy_course_ects, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="courseoffering",
            name="ects",
            field=models.PositiveSmallIntegerField(),
        ),
    ]
