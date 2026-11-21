"""Store each grade's term, the first of two steps to partition grades by it (#33).

The column may be empty: the version still running during the deploy does
not set it. 0012 partitions the table once this version is live, and fills
in anything left empty first.
"""

import django.db.models.deletion
from django.db import migrations, models

# Filling in the term is not a grade change: the history trigger (#35) stays
# off meanwhile, or every grade would get an "updated" row with no author.
# The foreign key checks run before it is turned back on; PostgreSQL does not
# allow that with checks still pending.
FILL = """
ALTER TABLE grading_grade DISABLE TRIGGER grading_grade_change_history;
UPDATE grading_grade AS g SET term_id = o.term_id
FROM grading_enrollment AS e
JOIN grading_courseoffering AS o ON o.id = e.offering_id
WHERE e.id = g.enrollment_id;
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE grading_grade ENABLE TRIGGER grading_grade_change_history;
"""


class Migration(migrations.Migration):
    dependencies = [("grading", "0010_record_grade_changes")]

    operations = [
        migrations.AddField(
            model_name="grade",
            name="term",
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="grades",
                to="grading.term",
            ),
        ),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
