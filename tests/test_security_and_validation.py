import os
import tempfile
import unittest

os.environ['EDITALOS_DATA'] = tempfile.mkdtemp(prefix='editalos-security-tests-')

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


class SecurityAndValidationTests(unittest.TestCase):
    def setUp(self):
        import app as app_module
        with app_module.db() as conn:
            for table in ('topic_progress', 'reviews', 'attempts', 'questions', 'sessions', 'events',
                          'exam_subjects', 'exams', 'notebooklm_imports', 'proposals', 'plan_versions'):
                conn.execute(f'DELETE FROM {table}')
        app_module.init_db()

    def test_invalid_event_exam_returns_not_found(self):
        response = client.post('/api/events', json={
            'title': 'Prazo', 'type': 'outro', 'start_date': '2026-11-04',
            'end_date': '2026-11-04', 'exam_id': 999999,
        })
        self.assertEqual(response.status_code, 404)

    def test_invalid_session_time_and_activity_are_rejected(self):
        response = client.post('/api/sessions', json={
            'day': '2026-11-04', 'subject_id': 'portugues', 'minutes': 50,
            'start_time': '25:99', 'activity_type': 'javascript',
        })
        self.assertEqual(response.status_code, 422)

    def test_frontend_escapes_dynamic_values(self):
        javascript = client.get('/static/app.js').text
        self.assertIn("replace(/[&<>\"']/g", javascript)
        self.assertIn("textContent=message", javascript)

    def test_settings_reject_unknown_strategy(self):
        response = client.post('/api/settings', json={
            'weekly_hours': 20, 'buffer_pct': 10, 'strategy': 'unsafe',
            'study_days': [0], 'auto_review': True,
        })
        self.assertEqual(response.status_code, 422)

    def test_allocation_never_exceeds_weekly_capacity(self):
        import app as app_module
        created = client.post('/api/exams', json={
            'name': 'Concurso de capacidade', 'cargo': 'Analista',
            'exam_date': '2027-12-01', 'subjects': ['portugues', 'constitucional', 'administrativo'],
        })
        self.assertEqual(created.status_code, 200)
        client.post('/api/settings', json={
            'weekly_hours': 1, 'buffer_pct': 0, 'strategy': 'equilibrado',
            'study_days': [0], 'auto_review': True,
        })
        with app_module.db() as conn:
            allocation = app_module.allocate(conn)
        self.assertLessEqual(sum(allocation.values()), 1.0)


if __name__ == '__main__':
    unittest.main()
