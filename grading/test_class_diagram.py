from django.test import SimpleTestCase

from grading.management.commands.class_diagram import DEFAULT_OUTPUT, render


class ClassDiagramTests(SimpleTestCase):
    def test_committed_diagram_matches_models(self):
        """Fails when a model changes and docs/classes.d2 was not regenerated."""
        self.assertEqual(
            DEFAULT_OUTPUT.read_text(encoding="utf-8"),
            render(),
            "Run `python manage.py class_diagram` and re-render docs/classes.png.",
        )
