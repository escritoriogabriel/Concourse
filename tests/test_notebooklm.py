"""Testes de integração do fluxo NotebookLM -> prévia -> calendário."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ['EDITALOS_DATA'] = tempfile.mkdtemp(prefix='editalos-notebooklm-tests-')

from fastapi.testclient import TestClient
import app as app_module
from app import app

client = TestClient(app)


def plan(title='Plano de teste NotebookLM', start='2026-11-04', end='2026-11-10', session_dates=None):
    session_dates = session_dates or ['2026-11-04', '2026-11-05']
    schedule = []
    for i, day in enumerate(session_dates):
        is_q = i == 1
        schedule.append({
            'date': day, 'start_time': '08:00', 'minutes': 50,
            'exam_ref': 'concurso_teste', 'subject': 'Direito Administrativo',
            'topic': 'Atos administrativos', 'activity_type': 'questoes' if is_q else 'teoria',
            'objective': 'Resolver 20 questões e registrar erros.' if is_q else 'Estudar atributos dos atos administrativos.',
            'qconcursos': {
                'enabled': is_q, 'subject': 'Direito Administrativo', 'topic': 'Atos administrativos',
                'bank': 'FGV', 'institution': 'Órgão de teste', 'year_from': 2020, 'year_to': 2026,
                'difficulty': 'média', 'mode': 'múltipla escolha', 'quantity': 20 if is_q else 0,
                'filter_notes': 'Questões na conta pessoal do QConcursos.'
            },
            'source_reference': 'Edital de teste, p. 21'
        })
    return {
        'schema': 'editalos.notebooklm.v1',
        'metadata': {'title': title, 'generated_at': '2026-11-03', 'sources': [{'name': 'edital.pdf', 'reference': 'p. 1-30'}]},
        'planning_period': {'start_date': start, 'end_date': end},
        'exams': [{
            'ref': 'concurso_teste', 'name': 'Prefeitura de Teste — Concurso Público',
            'institution': 'Prefeitura de Teste', 'banca': 'FGV', 'cargo': 'Analista Administrativo',
            'priority': 3, 'exam_date': '2027-02-14', 'registration_start': '2026-11-01',
            'registration_end': '2026-11-20', 'exemption_start': '2026-11-01', 'exemption_end': '2026-11-03',
            'subjects': [{'name': 'Direito Administrativo', 'weight': 2, 'questions': 10,
                          'topics': ['Atos administrativos', 'Poderes administrativos']}]
        }],
        'schedule': schedule,
        'events': [{
            'title': 'Inscrições — Prefeitura de Teste', 'type': 'inscricao',
            'start_date': '2026-11-01', 'end_date': '2026-11-20', 'exam_ref': 'concurso_teste',
            'notes': 'Período conforme edital.', 'source_reference': 'Edital, p. 1'
        }]
    }


def upload_plan(data, filename='editalos_plano.json'):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    return client.post('/api/notebooklm/preview', files={'file': (filename, raw, 'application/json')})


class NotebookLMIntegrationTests(unittest.TestCase):
    def setUp(self):
        with app_module.db() as conn:
            for table in ('topic_progress', 'reviews', 'attempts', 'questions', 'sessions', 'events',
                          'exam_subjects', 'exams', 'notebooklm_imports', 'proposals', 'plan_versions'):
                conn.execute(f'DELETE FROM {table}')
        app_module.init_db()

    def test_legacy_database_migration_preserves_existing_data(self):
        old_path = app_module.DB_PATH
        with tempfile.TemporaryDirectory(prefix='editalos-legacy-') as folder:
            app_module.DB_PATH = Path(folder) / 'editalos.db'
            import sqlite3
            conn = sqlite3.connect(app_module.DB_PATH)
            conn.executescript("""
                CREATE TABLE subjects (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL);
                CREATE TABLE exams (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cargo TEXT NOT NULL,
                    banca TEXT DEFAULT '', exam_date TEXT, priority INTEGER DEFAULT 2, active INTEGER DEFAULT 1,
                    source TEXT DEFAULT 'manual', created TEXT NOT NULL);
                CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, title TEXT NOT NULL,
                    type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                    status TEXT DEFAULT 'pendente', origin TEXT DEFAULT 'manual', created TEXT NOT NULL);
                CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL,
                    subject_id TEXT NOT NULL, minutes INTEGER NOT NULL, completed INTEGER DEFAULT 0,
                    note TEXT DEFAULT '', created TEXT NOT NULL);
                INSERT INTO subjects VALUES ('portugues','Língua Portuguesa','Linguagens');
                INSERT INTO exams(name,cargo,banca,exam_date,priority,active,source,created)
                    VALUES ('Concurso legado','Analista','FGV','2027-02-01',3,1,'manual','2026-10-01T10:00:00');
                INSERT INTO events(exam_id,title,type,start_date,end_date,status,origin,created)
                    VALUES (1,'Inscrições','inscricao','2026-11-01','2026-11-15','pendente','manual','2026-10-01T10:00:00');
                INSERT INTO sessions(day,subject_id,minutes,completed,note,created)
                    VALUES ('2026-11-04','portugues',50,0,'Sessão antiga','2026-10-01T10:00:00');
            """)
            conn.commit()
            conn.close()
            try:
                app_module.init_db()
                with app_module.db() as migrated:
                    exam = migrated.execute('SELECT name,institution FROM exams WHERE id=1').fetchone()
                    event = migrated.execute('SELECT title,notes,source_reference FROM events WHERE id=1').fetchone()
                    session = migrated.execute('SELECT day,subject_id,minutes,start_time FROM sessions WHERE id=1').fetchone()
                self.assertEqual(exam['name'], 'Concurso legado')
                self.assertEqual(exam['institution'], '')
                self.assertEqual(event['title'], 'Inscrições')
                self.assertEqual(event['notes'], '')
                self.assertEqual(session['day'], '2026-11-04')
                self.assertEqual(session['subject_id'], 'portugues')
                self.assertEqual(session['minutes'], 50)
                self.assertEqual(session['start_time'], '')
            finally:
                app_module.DB_PATH = old_path

    def test_start_page_and_notebooklm_prompt(self):
        html = client.get('/').text
        js = client.get('/static/app.js').text
        self.assertIn('Minha agenda', html)
        self.assertIn("page:'calendar'", js)
        self.assertIn('renderNotebookLM', js)
        self.assertIn('renderQConcursos', js)
        self.assertNotIn('ollama', js.lower())
        self.assertNotIn('gemini', js.lower())
        self.assertNotIn('qwen', js.lower())
        prompt = client.get('/api/notebooklm/prompt')
        self.assertEqual(prompt.status_code, 200)
        self.assertIn('editalos.notebooklm.v1', prompt.text)
        self.assertIn('QConcursos', prompt.text)
        self.assertIn('não copie questões', prompt.text.lower())
        template = client.get('/api/notebooklm/template')
        self.assertEqual(template.status_code, 200)
        self.assertIn('application/json', template.headers['content-type'])

    def test_preview_confirm_and_qconcursos_filters(self):
        data = plan()
        preview = upload_plan(data)
        self.assertEqual(preview.status_code, 200, preview.text)
        p = preview.json()
        self.assertEqual(p['summary']['exams'], 1)
        self.assertEqual(p['summary']['sessions'], 2)
        self.assertEqual(p['summary']['qconcursos_sessions'], 1)
        self.assertEqual(p['exams'][0]['institution'], 'Prefeitura de Teste')
        self.assertEqual(p['first_session_date'], '2026-11-04')
        self.assertTrue(p['sample_sessions'][1]['qconcursos_filters']['enabled'])

        imported = client.post('/api/notebooklm/confirm', json={'token': p['token'], 'mode': 'append'})
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()['sessions'], 2)
        data = client.get('/api/bootstrap').json()
        exam = next(x for x in data['exams'] if x['source'] == 'notebooklm')
        self.assertEqual(exam['institution'], 'Prefeitura de Teste')
        self.assertIn('Direito Administrativo', [x['name'] for x in exam['subjects']])
        self.assertEqual(len([x for x in data['sessions'] if x.get('notebooklm_import_id')]), 2)
        qc = next(x for x in data['sessions'] if x['activity_type'] == 'questoes')
        self.assertEqual(qc['qconcursos_filters']['quantity'], 20)
        event = next(x for x in data['events'] if x['origin'] == 'notebooklm')
        self.assertEqual(event['source_reference'], 'Edital, p. 1')

        duplicate = upload_plan(data=plan())
        self.assertEqual(duplicate.status_code, 409)
        ics = client.get('/api/calendar/export.ics')
        self.assertEqual(ics.status_code, 200)
        self.assertIn('DTSTART;TZID=America/Sao_Paulo:20261104T080000', ics.text)

    def test_replace_mode_preserves_completed_and_manual_sessions(self):
        # The first import has one session on Nov 4 and one on Nov 5.
        first = upload_plan(plan(title='Plano inicial'))
        self.assertEqual(first.status_code, 200, first.text)
        token = first.json()['token']
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': token, 'mode': 'append'}).status_code, 200)
        sessions = client.get('/api/bootstrap').json()['sessions']
        notebook_sessions = [s for s in sessions if s.get('notebooklm_import_id')]
        nov4 = next(s for s in notebook_sessions if s['day'] == '2026-11-04')
        client.patch(f"/api/sessions/{nov4['id']}", json={'completed': True})
        client.post('/api/sessions', json={'day': '2026-11-05', 'subject_id': 'portugues', 'minutes': 30,
                                          'completed': False, 'topic': 'Sessão manual'})

        # A new revision of the plan is imported in replace mode.
        second_data = plan(title='Plano revisado', session_dates=['2026-11-06'])
        second_data['schedule'][0]['activity_type'] = 'revisao'
        second = upload_plan(second_data, 'editalos_plano_revisado.json')
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': second.json()['token'], 'mode': 'replace_notebooklm'}).status_code, 200)
        final = client.get('/api/bootstrap').json()['sessions']
        self.assertTrue(any(s['id'] == nov4['id'] and s['completed'] for s in final))
        self.assertTrue(any(s['subject_id'] == 'portugues' and s['topic'] == 'Sessão manual' for s in final))
        self.assertFalse(any(s.get('notebooklm_import_id') and s['day'] == '2026-11-05' and not s['completed'] for s in final))
        self.assertTrue(any(s.get('notebooklm_import_id') and s['day'] == '2026-11-06' for s in final))

    def test_replace_does_not_delete_overlapping_import_for_other_exam(self):
        first = upload_plan(plan(title='Plano A'), 'plano-a.json')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': first.json()['token'], 'mode': 'append'}).status_code, 200)

        other = plan(title='Plano B')
        other['exams'][0]['ref'] = 'concurso_b'
        other['exams'][0]['name'] = 'Outro Concurso de Teste'
        for item in other['schedule']:
            item['exam_ref'] = 'concurso_b'
        other['events'][0]['exam_ref'] = 'concurso_b'
        second = upload_plan(other, 'plano-b.json')
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': second.json()['token'], 'mode': 'append'}).status_code, 200)

        revised = upload_plan(plan(title='Plano A revisado', session_dates=['2026-11-06']), 'plano-a-revisado.json')
        self.assertEqual(revised.status_code, 200, revised.text)
        preview = revised.json()
        self.assertEqual(preview['will_delete_sessions'], 2)
        self.assertEqual(client.post('/api/notebooklm/confirm', json={'token': preview['token'], 'mode': 'replace_notebooklm'}).status_code, 200)
        sessions = client.get('/api/bootstrap').json()['sessions']
        self.assertTrue(any(s['exam_name'] == 'Outro Concurso de Teste' and s['day'] == '2026-11-04' for s in sessions))
        self.assertTrue(any(s.get('notebooklm_import_id') and s['day'] == '2026-11-06' for s in sessions))

    def test_preview_token_is_consumed_after_confirmation(self):
        response = upload_plan(plan(title='Token único'), 'token-unico.json')
        self.assertEqual(response.status_code, 200)
        payload = {'token': response.json()['token'], 'mode': 'append'}
        self.assertEqual(client.post('/api/notebooklm/confirm', json=payload).status_code, 200)
        self.assertEqual(client.post('/api/notebooklm/confirm', json=payload).status_code, 410)

    def test_invalid_update_ids_return_not_found(self):
        self.assertEqual(client.patch('/api/events/999999', json={'status': 'concluido'}).status_code, 404)
        self.assertEqual(client.patch('/api/reviews/999999', json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
