import django.db.models.deletion
from django.db import migrations, models


def move_weights(apps, schema_editor):
    ProgramOutcome = apps.get_model("grading", "ProgramOutcome")
    POComponent = apps.get_model("grading", "POComponent")
    LOPOWeight = apps.get_model("grading", "LOPOWeight")
    database = schema_editor.connection.alias

    for po in ProgramOutcome.objects.using(database).all().iterator():
        component = POComponent.objects.using(database).create(
            program_outcome_id=po.pk,
            code="a",
            description=po.description,
        )
        LOPOWeight.objects.using(database).filter(
            program_outcome_id=po.pk,
        ).update(component_id=component.pk)


DROP_VIEWS = """
DROP MATERIALIZED VIEW cross_course_po_scores;
DROP MATERIALIZED VIEW course_po_scores;
"""

CREATE_VIEWS = """
CREATE MATERIALIZED VIEW course_po_scores AS
WITH component_scores AS (
    SELECT
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id AS component_id,
        SUM(slo.score * lpw.weight) / SUM(lpw.weight) AS score
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw
        ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc
        ON pc.id = lpw.component_id
    GROUP BY
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id
    HAVING SUM(lpw.weight) > 0
)
SELECT
    student_id,
    offering_id,
    program_outcome_id,
    AVG(score) AS score
FROM component_scores
GROUP BY student_id, offering_id, program_outcome_id;

CREATE UNIQUE INDEX course_po_scores_unique
ON course_po_scores (
    student_id,
    offering_id,
    program_outcome_id
);

CREATE MATERIALIZED VIEW cross_course_po_scores AS
WITH component_scores AS (
    SELECT
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id AS component_id,
        SUM(slo.score * lpw.weight) / SUM(lpw.weight) AS score
    FROM student_lo_scores slo
    JOIN grading_lopoweight lpw
        ON lpw.learning_outcome_id = slo.learning_outcome_id
    JOIN grading_pocomponent pc
        ON pc.id = lpw.component_id
    GROUP BY
        slo.student_id,
        slo.offering_id,
        pc.program_outcome_id,
        pc.id
    HAVING SUM(lpw.weight) > 0
),
student_components AS (
    SELECT
        cs.student_id,
        cs.program_outcome_id,
        cs.component_id,
        SUM(cs.score * c.ects) / SUM(c.ects) AS score
    FROM component_scores cs
    JOIN grading_courseoffering o ON o.id = cs.offering_id
    JOIN grading_course c ON c.id = o.course_id
    GROUP BY
        cs.student_id,
        cs.program_outcome_id,
        cs.component_id
    HAVING SUM(c.ects) > 0
)
SELECT
    student_id,
    program_outcome_id,
    AVG(score) AS score
FROM student_components
GROUP BY student_id, program_outcome_id;

CREATE UNIQUE INDEX cross_course_po_scores_unique
ON cross_course_po_scores (student_id, program_outcome_id);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("grading", "0002_materialized_views"),
    ]

    operations = [
        migrations.CreateModel(
            name="POComponent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=10)),
                ("description", models.TextField(blank=True)),
                (
                    "program_outcome",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="grading.programoutcome",
                    ),
                ),
            ],
            options={
                "ordering": ("program_outcome__code", "code"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("program_outcome", "code"),
                        name="uniq_po_component",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="lopoweight",
            name="component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lo_weights",
                to="grading.pocomponent",
            ),
        ),
        migrations.RunPython(move_weights),
        migrations.RunSQL(DROP_VIEWS),
        migrations.RemoveConstraint(
            model_name="lopoweight",
            name="uniq_lo_po",
        ),
        migrations.RemoveField(
            model_name="lopoweight",
            name="program_outcome",
        ),
        migrations.AlterField(
            model_name="lopoweight",
            name="component",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lo_weights",
                to="grading.pocomponent",
            ),
        ),
        migrations.AddConstraint(
            model_name="lopoweight",
            constraint=models.UniqueConstraint(
                fields=("learning_outcome", "component"),
                name="uniq_lo_component",
            ),
        ),
        migrations.RunSQL(CREATE_VIEWS),
    ]