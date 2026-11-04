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
            conn.execute('DELETE FROM settings')
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

    def test_import_button_opens_file_picker_and_completed_events_are_hidden(self):
        javascript = client.get('/static/app.js').text
        html = client.get('/').text
        self.assertIn("case 'open-import'", javascript)
        self.assertIn("$('#notebookPlanUpload')?.click()", javascript)
        self.assertIn("e.status!=='concluido'", javascript)
        self.assertIn('data-action="open-import"', html)

    def test_storage_status_and_full_backup_restore(self):
        client.post('/api/sessions', json={'day': '2026-11-04', 'subject_id': 'portugues', 'minutes': 50})
        status = client.get('/api/storage/status')
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()['database_exists'])
        self.assertEqual(status.json()['counts']['sessions'], 1)
        backup = client.get('/api/export/backup.json')
        self.assertEqual(backup.status_code, 200)
        self.assertEqual(backup.json()['_meta']['format'], 'editalos.backup.v1')
        self.assertIn('topic_progress', backup.json())
        restored = client.post('/api/import/backup.json', files={
            'file': ('backup.json', backup.content, 'application/json'),
        })
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(client.get('/api/storage/status').json()['counts']['sessions'], 1)
        zipped = client.get('/api/export/backup.zip')
        restored_zip = client.post('/api/import/backup.json', files={
            'file': ('backup.zip', zipped.content, 'application/zip'),
        })
        self.assertEqual(restored_zip.status_code, 200, restored_zip.text)

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

    def test_study_log_updates_dashboard_and_creates_review(self):
        import json
        plan = {
            'schema': 'editalos.notebooklm.v1',
            'metadata': {'title': 'Plano adaptativo'},
            'planning_period': {'start_date': '2026-11-04', 'end_date': '2026-11-10'},
            'exams': [{'ref': 'x', 'name': 'Concurso X', 'cargo': 'Analista', 'subjects': [{'name': 'Língua Portuguesa', 'topics': ['Interpretação']}]}],
            'schedule': [{'date': '2026-11-04', 'minutes': 50, 'exam_ref': 'x', 'subject': 'Língua Portuguesa', 'topic': 'Interpretação', 'activity_type': 'teoria'}],
            'events': [],
        }
        preview = client.post('/api/notebooklm/preview', files={'file': ('adaptive.json', json.dumps(plan).encode(), 'application/json')})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': preview.json()['token'], 'mode': 'append'}).status_code, 200)
        session_id = client.get('/api/bootstrap').json()['sessions'][0]['id']
        logged = client.post('/api/study-logs', json={'session_id': session_id, 'actual_minutes': 40, 'questions_done': 10, 'questions_correct': 6, 'confidence': 2})
        self.assertEqual(logged.status_code, 200, logged.text)
        dashboard = client.get('/api/dashboard').json()
        self.assertEqual(dashboard['actual_minutes'], 40)
        self.assertEqual(dashboard['questions_done'], 10)
        self.assertEqual(len(client.get('/api/reviews').json()), 1)

    def test_replan_moves_only_pending_past_sessions(self):
        import app as app_module
        with app_module.db() as conn:
            conn.execute("INSERT INTO sessions(day,subject_id,minutes,completed,created) VALUES('2020-01-01','portugues',50,0,'2020-01-01')")
            conn.execute("INSERT INTO sessions(day,subject_id,minutes,completed,created) VALUES('2020-01-02','portugues',50,1,'2020-01-01')")
        response = client.post('/api/replan', json={'from_day': '2026-11-04', 'strategy': 'distribuir'})
        self.assertEqual(response.status_code, 200)
        sessions = client.get('/api/bootstrap').json()['sessions']
        self.assertTrue(any(s['day'] == '2026-11-04' and not s['completed'] for s in sessions))
        self.assertTrue(any(s['day'] == '2020-01-02' and s['completed'] for s in sessions))

    def test_study_csv_export_is_available(self):
        response = client.get('/api/export/study.csv')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data,materia,topico', response.text)


if __name__ == '__main__':
    unittest.main()
