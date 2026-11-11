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

    def test_every_relation_is_drawn(self):
        """Foreign keys and many to many fields all show up as links."""
        from django.apps import apps

        diagram = render()
        for model in apps.get_app_config("grading").get_models():
            for field in model._meta.get_fields():
                if field.concrete and (field.many_to_one or field.many_to_many):
                    self.assertIn(f'{model.__name__} -> {field.related_model.__name__}: "{field.name}', diagram)
