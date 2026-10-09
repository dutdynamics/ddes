"""Role formatting must agree across publishing and independent PDF export."""
import unittest
from manager_store import validate_event as validate_manager
from report_builder import validate_event as validate_report
from seminar_roles import normalize_role


class SeminarRoleTests(unittest.TestCase):
    def test_existing_student_labels_and_completed_degrees(self):
        for value, expected in [('Associate professor@DUT', 'Associate Professor@DUT'),
                                ('PhD@DUT', 'PhD Student@DUT'), ('PhD Student @ DUT', 'PhD Student @ DUT'),
                                ('PhD student', 'PhD Student'), ('Visiting PhD student', 'Visiting PhD Student'),
                                ('PhD in Mathematics', 'PhD in Mathematics'), ('PhD (Mathematics)', 'PhD (Mathematics)'),
                                ('PhD/MSc', 'PhD/MSc'), ('Custom position', 'Custom position')]:
            with self.subTest(value=value):
                self.assertEqual(normalize_role(value), expected)
                self.assertEqual(normalize_role(normalize_role(value)), expected)

    def test_manager_and_pdf_apply_only_to_role_fields(self):
        event = {'id': 'role-test', 'date': '2030-10-10', 'speakerName': 'Speaker',
                 'speakerAffiliation': 'PhD@DUT', 'title': 'PhD', 'abstract': 'Associate professor',
                 'experiences': [{'position': 'Associate professor'}, {'position': 'PhD in Mathematics'}]}
        for validate in (validate_manager, validate_report):
            result = validate(event)
            self.assertEqual(result['speakerAffiliation'], 'PhD Student@DUT')
            self.assertEqual([row['position'] for row in result['experiences']], ['Associate Professor', 'PhD in Mathematics'])
            self.assertEqual((result['title'], result['abstract']), ('PhD', 'Associate professor'))
        self.assertEqual(event['speakerAffiliation'], 'PhD@DUT')

    def test_expansion_keeps_existing_length_and_type_checks(self):
        event = {'id': 'role-test', 'date': '2030-10-10', 'speakerName': 'Speaker',
                 'speakerAffiliation': 'x' * 346 + ' PhD'}
        for validate in (validate_manager, validate_report):
            with self.assertRaises(ValueError):
                validate(event)
            with self.assertRaises(ValueError):
                validate(dict(event, speakerAffiliation=7))


if __name__ == '__main__':
    unittest.main()
