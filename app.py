"""EditalOS — MVP local, auditable, single-user. Run: uvicorn app:app --reload"""
from __future__ import annotations
import csv
import copy
import io
import json
import os
import re
import sqlite3
import unicodedata
import uuid
import hashlib
import threading
import time
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, PlainTextResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = '/tmp/editalos' if os.getenv('VERCEL') == '1' else str(ROOT / 'data')
DATA_DIR = Path(os.getenv('EDITALOS_DATA', DEFAULT_DATA_DIR))
UPLOAD_DIR = DATA_DIR / 'uploads'
DB_PATH = DATA_DIR / 'editalos.db'
STATIC = ROOT / 'static'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='EditalOS · Agenda NotebookLM', version='3.0.0')
PREVIEW_TTL_SECONDS = 3600
PREVIEW_MAX_ENTRIES = 32
notebooklm_previews: dict[str, dict] = {}
preview_lock = threading.Lock()

SUBJECTS = [
 ('portugues', 'Língua Portuguesa', 'Linguagens'),
 ('constitucional', 'Direito Constitucional', 'Direito'),
 ('administrativo', 'Direito Administrativo', 'Direito'),
 ('penal', 'Direito Penal', 'Direito'),
 ('processual-penal', 'Direito Processual Penal', 'Direito'),
 ('civil', 'Direito Civil', 'Direito'),
 ('processual-civil', 'Direito Processual Civil', 'Direito'),
 ('informatica', 'Informática', 'Conhecimentos gerais'),
 ('logica', 'Raciocínio Lógico', 'Exatas'),
 ('matematica', 'Matemática', 'Exatas'),
 ('legislacao', 'Legislação Especial', 'Direito'),
 ('direitos-humanos', 'Direitos Humanos', 'Direito'),
 ('atualidades', 'Atualidades', 'Conhecimentos gerais'),
 ('redacao', 'Redação', 'Linguagens'),
 ('contabilidade', 'Contabilidade', 'Exatas'),
 ('administracao', 'Administração Geral', 'Conhecimentos específicos'),
]

@contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('PRAGMA synchronous=NORMAL')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

TZ = ZoneInfo('America/Sao_Paulo')
def local_today(): return datetime.now(TZ).date()
def now(): return datetime.now(TZ).isoformat(timespec='seconds')
def iso(d): return d.isoformat() if isinstance(d,date) else d

def j(x, default=None):
    try: return json.loads(x) if x is not None else default
    except (ValueError, TypeError): return default

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn')

def normalize(s):
    return norm(s)

def squeeze(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS subjects (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exams (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cargo TEXT NOT NULL,
          institution TEXT DEFAULT '', banca TEXT DEFAULT '', exam_date TEXT, priority INTEGER DEFAULT 2, active INTEGER DEFAULT 1,
          source TEXT DEFAULT 'manual', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exam_subjects (exam_id INTEGER, subject_id TEXT, weight REAL DEFAULT 1,
          questions INTEGER DEFAULT 10, topics TEXT DEFAULT '[]', PRIMARY KEY(exam_id, subject_id),
          FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER,
          title TEXT NOT NULL, type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
          status TEXT DEFAULT 'pendente', origin TEXT DEFAULT 'manual', notes TEXT DEFAULT '',
          source_reference TEXT DEFAULT '', created TEXT NOT NULL,
          FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS plan_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, allocations TEXT NOT NULL,
          note TEXT, restored_from INTEGER, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, old_plan TEXT NOT NULL,
          new_plan TEXT NOT NULL, rationale TEXT NOT NULL, status TEXT DEFAULT 'pendente',
          selected TEXT DEFAULT '[]', trigger TEXT, created TEXT NOT NULL, resolved TEXT);
        CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
          day TEXT NOT NULL, subject_id TEXT NOT NULL, minutes INTEGER NOT NULL, completed INTEGER DEFAULT 0,
          note TEXT DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id TEXT NOT NULL,
          topic TEXT DEFAULT '', statement TEXT NOT NULL, options TEXT NOT NULL,
          answer TEXT NOT NULL, banca TEXT DEFAULT '', year INTEGER,
          source TEXT DEFAULT '', source_url TEXT DEFAULT '', difficulty TEXT DEFAULT 'média',
          origin TEXT DEFAULT 'importada', rights_note TEXT DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, question_ids TEXT NOT NULL, answers TEXT NOT NULL,
          correct_count INTEGER NOT NULL, total INTEGER NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT,
          subject_id TEXT, question_id INTEGER, due TEXT, status TEXT DEFAULT 'pendente',
          created TEXT NOT NULL, FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS editals (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER,
          filename TEXT NOT NULL, path TEXT NOT NULL, text_preview TEXT, created TEXT NOT NULL,
          FOREIGN KEY(exam_id) REFERENCES exams(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS topic_progress (exam_id INTEGER, subject_id TEXT, topic TEXT,
          done INTEGER DEFAULT 0, PRIMARY KEY(exam_id,subject_id,topic));
        CREATE TABLE IF NOT EXISTS notebooklm_imports (id TEXT PRIMARY KEY, filename TEXT NOT NULL,
          sha256 TEXT NOT NULL UNIQUE, plan_title TEXT NOT NULL, exam_count INTEGER DEFAULT 0,
          session_count INTEGER DEFAULT 0, event_count INTEGER DEFAULT 0, period_start TEXT,
          period_end TEXT, plan_json TEXT DEFAULT '{}', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS study_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER NOT NULL, actual_minutes INTEGER NOT NULL, questions_done INTEGER DEFAULT 0,
          questions_correct INTEGER DEFAULT 0, difficulty TEXT DEFAULT 'adequada', confidence INTEGER DEFAULT 3,
          interruptions INTEGER DEFAULT 0, notes TEXT DEFAULT '', created TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS error_notebook (id INTEGER PRIMARY KEY AUTOINCREMENT,
          subject_id TEXT NOT NULL, topic TEXT DEFAULT '', source TEXT DEFAULT '', error_type TEXT DEFAULT 'conteúdo',
          note TEXT NOT NULL, status TEXT DEFAULT 'aberto', next_review TEXT, created TEXT NOT NULL,
          resolved TEXT);
        CREATE TABLE IF NOT EXISTS spaced_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT,
          subject_id TEXT NOT NULL, exam_id INTEGER, topic TEXT DEFAULT '', due TEXT NOT NULL,
          interval_days INTEGER DEFAULT 1, ease REAL DEFAULT 2.5, status TEXT DEFAULT 'pendente',
          last_score REAL, created TEXT NOT NULL, completed TEXT);
        ''')
        # Migração aditiva: preserva banco anterior e amplia apenas metadados.
        exam_columns={row['name'] for row in c.execute('PRAGMA table_info(exams)')}
        if 'institution' not in exam_columns:
            c.execute("ALTER TABLE exams ADD COLUMN institution TEXT DEFAULT ''")
        event_columns={row['name'] for row in c.execute('PRAGMA table_info(events)')}
        for col in ('notes','source_reference'):
            if col not in event_columns:
                c.execute("ALTER TABLE events ADD COLUMN " + col + " TEXT DEFAULT ''")
        if 'notebooklm_import_id' not in event_columns:
            c.execute("ALTER TABLE events ADD COLUMN notebooklm_import_id TEXT DEFAULT ''")
        import_columns={row['name'] for row in c.execute('PRAGMA table_info(notebooklm_imports)')}
        if 'plan_json' not in import_columns:
            c.execute("ALTER TABLE notebooklm_imports ADD COLUMN plan_json TEXT DEFAULT '{}'")
        existing_columns={row['name'] for row in c.execute('PRAGMA table_info(sessions)')}
        additions={
          'exam_id':'INTEGER', 'start_time':"TEXT DEFAULT ''", 'topic':"TEXT DEFAULT ''",
          'activity_type':"TEXT DEFAULT 'estudo'", 'objective':"TEXT DEFAULT ''",
          'qconcursos_filters':"TEXT DEFAULT '{}'", 'source_reference':"TEXT DEFAULT ''",
          'notebooklm_import_id':"TEXT DEFAULT ''"
        }
        for col, declaration in additions.items():
            if col not in existing_columns:
                c.execute(f'ALTER TABLE sessions ADD COLUMN {col} {declaration}')
        for key, name, category in SUBJECTS:
            c.execute('INSERT OR IGNORE INTO subjects VALUES (?,?,?)',(key,name,category))
        defaults = {'weekly_hours':20,'buffer_pct':10,'strategy':'equilibrado',
          'study_days':[0,1,2,3,4,5], 'auto_review':True}
        for k,v in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,json.dumps(v)))
        # Instalações novas começam vazias; bancos existentes são preservados sem limpeza.

def seed(c):
    today = local_today()
    examples = [
        ('Concurso Alfa · Área policial','Agente','Banca demonstrativa',today+timedelta(days=29),3,
         [('portugues',2,10),('constitucional',2,10),('administrativo',2,10),('penal',2,10)]),
        ('Concurso Beta · Área administrativa','Analista','Banca demonstrativa',today+timedelta(days=54),2,
         [('portugues',2,12),('constitucional',1,8),('administrativo',3,15),('informatica',2,10),('logica',1,5)]),
        ('Concurso Gama · Área jurídica','Técnico','Banca demonstrativa',today+timedelta(days=84),1,
         [('portugues',1,10),('administrativo',2,10),('penal',2,10),('processual-penal',2,10)])
    ]
    for name,cargo,banca,d,priority,subs in examples:
        cur=c.execute('INSERT INTO exams (name,cargo,banca,exam_date,priority,source,created) VALUES (?,?,?,?,?,?,?)',
                      (name,cargo,banca,iso(d),priority,'exemplo',now()))
        exam_id=cur.lastrowid
        seed_topics={'portugues':['Interpretação de textos','Concordância verbal e nominal','Pontuação e ortografia'],
          'constitucional':['Direitos e garantias fundamentais','Organização dos poderes','Administração pública'],
          'administrativo':['Atos administrativos','Poderes administrativos','Licitações e contratos'],
          'penal':['Teoria do crime','Penas e aplicação','Crimes em espécie'],
          'informatica':['Segurança da informação','Sistemas operacionais','Planilhas eletrônicas'],
          'logica':['Proposições e conectivos','Equivalências e negações'],
          'processual-penal':['Inquérito policial','Provas','Ação penal']}
        for subject,weight,q in subs:
            c.execute('INSERT INTO exam_subjects (exam_id,subject_id,weight,questions,topics) VALUES (?,?,?,?,?)',
                      (exam_id,subject,weight,q,json.dumps(seed_topics.get(subject,[]),ensure_ascii=False)))
        c.execute('INSERT INTO events (exam_id,title,type,start_date,end_date,origin,created) VALUES (?,?,?,?,?,?,?)',
                  (exam_id,'Prova — '+name,'prova',iso(d),iso(d),'exemplo',now()))
    dates = [('Inscrições · Concurso Alfa','inscricao',today+timedelta(days=1),today+timedelta(days=17)),
             ('Isenção · Concurso Beta','isencao',today+timedelta(days=3),today+timedelta(days=7)),
             ('Pagamento · Concurso Alfa','pagamento',today+timedelta(days=20),today+timedelta(days=20))]
    for title,kind,d1,d2 in dates:
        c.execute('INSERT INTO events (title,type,start_date,end_date,origin,created) VALUES (?,?,?,?,?,?)',
                  (title,kind,iso(d1),iso(d2),'exemplo',now()))
    base = {'portugues':4,'constitucional':4,'administrativo':4,'penal':3,'informatica':2,'logica':1}
    c.execute('INSERT INTO plan_versions (allocations,note,created) VALUES (?,?,?)',
              (json.dumps(base),'Plano inicial de demonstração',now()))
    # Only fictitious exercises; never misrepresent as past official exam questions.
    samples = [
      ('portugues','Interpretação','Na frase “Embora estivesse cansada, continuou estudando”, a oração iniciada por “embora” expressa:',
       ['Causa','Concessão','Finalidade','Condição'],'B'),
      ('portugues','Concordância','Assinale a alternativa com concordância verbal adequada:',
       ['Fazem dois anos que estudo.','Houveram muitos candidatos.','Existem diferentes possibilidades.','Deve haverem recursos.'],'C'),
      ('portugues','Pontuação','Em qual alternativa a vírgula separa corretamente um vocativo?',
       ['Vamos estudar amanhã, cedo.','Ana, revise este tema.','O concurso, foi adiado.','Os alunos, fizeram a prova.'],'B'),
      ('portugues','Ortografia','Qual palavra está grafada corretamente?',
       ['Exceção','Excessão','Ecessão','ExceçãO'],'A'),
      ('constitucional','Direitos fundamentais','Segundo a Constituição, são Poderes da União, independentes e harmônicos entre si:',
       ['Executivo, Legislativo e Judiciário','Federal, Estadual e Municipal','Ministério Público e Tribunais','República, Federação e União'],'A'),
      ('constitucional','Administração pública','Qual princípio aparece expressamente no caput do art. 37 da Constituição?',
       ['Razoabilidade','Proporcionalidade','Eficiência','Autotutela'],'C'),
      ('constitucional','Direitos fundamentais','A garantia do habeas corpus protege diretamente:',
       ['A propriedade','A liberdade de locomoção','O direito à herança','A liberdade de empresa'],'B'),
      ('administrativo','Atos administrativos','Um dos atributos usualmente apontados para certos atos administrativos é:',
       ['Presunção de legitimidade','Irrevogabilidade universal','Impossibilidade de controle','Ausência de motivação obrigatória em qualquer caso'],'A'),
      ('administrativo','Poderes administrativos','O poder de apurar infrações e aplicar sanções funcionais está ligado ao poder:',
       ['Hierárquico exclusivamente','Disciplinar','De polícia judiciária','Constituinte'],'B'),
      ('administrativo','Licitações','A Lei nº 14.133/2021 regula, em termos gerais:',
       ['Direito eleitoral','Licitações e contratos administrativos','Direito das sucessões','Processo penal militar'],'B'),
      ('penal','Teoria do crime','Na teoria tripartida usualmente adotada, o crime compreende:',
       ['Fato típico, ilicitude e culpabilidade','Conduta, pena e recurso','Dolo, culpa e resultado','Ação, sentença e execução'],'A'),
      ('penal','Penas','Qual destas é uma pena restritiva de direitos prevista no Código Penal?',
       ['Prisão preventiva','Prestação de serviços à comunidade','Multa administrativa','Advertência policial'],'B'),
      ('informatica','Segurança','Qual prática fortalece a segurança das contas digitais?',
       ['Reutilizar senha em todos os serviços','Ativar autenticação em dois fatores','Compartilhar códigos de acesso','Desabilitar atualizações'],'B'),
      ('informatica','Sistemas','Qual extensão é usualmente associada a arquivos de planilhas do Excel?',
       ['.jpg','.mp3','.xlsx','.exe'],'C'),
      ('logica','Proposições','A negação de “Todos os candidatos passaram” é:',
       ['Nenhum candidato passou','Pelo menos um candidato não passou','Todos faltaram','Alguém passou'],'B'),
      ('logica','Proposições','Se P é verdadeiro e Q é falso, a conjunção P ∧ Q é:',
       ['Verdadeira','Indeterminada','Falsa','Contraditória apenas se P for falsa'],'C'),
      ('processual-penal','Inquérito','Em termos gerais, o inquérito policial destina-se a:',
       ['Executar a pena','Investigar infração penal e autoria','Julgar o acusado','Substituir a denúncia'],'B'),
      ('processual-penal','Provas','Qual princípio é central para a atuação defensiva no processo penal?',
       ['Contraditório','Confisco obrigatório','Censura prévia','Irrecorribilidade absoluta'],'A'),
    ]
    for sub,topic,statement,opts,answer in samples:
        c.execute('''INSERT INTO questions (subject_id,topic,statement,options,answer,banca,year,source,difficulty,origin,rights_note,created)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (sub,topic,statement,json.dumps(opts),answer,
        'Questões de demonstração',None,'Elaborada para demonstrar a aplicação','média','demonstracao',
        'Exemplo original; não é questão de concurso real',now()))

init_db()

class NewExam(BaseModel):
    name: str = Field(min_length=3, max_length=150)
    cargo: str = Field(min_length=2, max_length=150)
    institution: str = ''
    banca: str = ''
    exam_date: str | None = None
    priority: int = Field(default=2, ge=1, le=3)
    subjects: list[str] = []

class EventIn(BaseModel):
    title: str
    type: str
    start_date: str
    end_date: str
    exam_id: int | None = None
    status: str = 'pendente'
    notes: str = ''
    source_reference: str = ''

class SessionIn(BaseModel):
    day: str
    subject_id: str
    minutes: int = Field(ge=5, le=1440)
    completed: bool = False
    exam_id: int | None = None
    start_time: str | None = None
    topic: str = ''
    activity_type: str = 'estudo'
    objective: str = ''
    qconcursos_filters: dict = Field(default_factory=dict)
    source_reference: str = ''

class SettingIn(BaseModel):
    weekly_hours: int = Field(ge=1, le=84)
    buffer_pct: int = Field(ge=0, le=50)
    strategy: str = Field(default='equilibrado', pattern='^(equilibrado|proxima|desempenho|pesos)$')
    study_days: list[int] = [0,1,2,3,4,5]
    auto_review: bool = True

class ProposalChoice(BaseModel):
    subject_ids: list[str]

class QuizSettings(BaseModel):
    amount: int = Field(default=10, ge=1, le=100)
    subject_ids: list[str] = []
    banca: str = ''
    difficulty: str = ''
    mode: str = 'todas'
    year_min: int | None = None
    year_max: int | None = None
    exam_id: int | None = None

class QuizSubmit(BaseModel):
    name: str = 'Simulado personalizado'
    question_ids: list[int]
    answers: dict[str,str]

class StudySchedule(BaseModel):
    start_day: str | None = None

class StudyLogIn(BaseModel):
    session_id: int
    actual_minutes: int = Field(ge=0, le=1440)
    questions_done: int = Field(default=0, ge=0, le=10000)
    questions_correct: int = Field(default=0, ge=0, le=10000)
    difficulty: str = Field(default='adequada', pattern='^(muito fácil|adequada|difícil|não concluída)$')
    confidence: int = Field(default=3, ge=1, le=5)
    interruptions: int = Field(default=0, ge=0, le=100)
    notes: str = Field(default='', max_length=2000)

class ErrorIn(BaseModel):
    subject_id: str
    topic: str = Field(default='', max_length=300)
    source: str = Field(default='', max_length=500)
    error_type: str = Field(default='conteúdo', pattern='^(conteúdo|interpretação|desatenção|cálculo|memória|pegadinha|outro)$')
    note: str = Field(min_length=1, max_length=2000)
    next_review: str | None = None

class ErrorUpdate(BaseModel):
    status: str = Field(pattern='^(aberto|resolvido)$')

class ReviewResult(BaseModel):
    score: float = Field(ge=0, le=1)

class ReplanIn(BaseModel):
    from_day: str | None = None
    strategy: str = Field(default='distribuir', pattern='^(distribuir|priorizar|revisar)$')

class PromptOptions(BaseModel):
    weekly_hours: int = Field(default=20, ge=1, le=84)
    buffer_pct: int = Field(default=10, ge=0, le=50)
    study_days: list[int] = Field(default_factory=lambda: [0,1,2,3,4,5])
    strategy: str = Field(default='equilibrado', pattern='^(equilibrado|proxima|desempenho|pesos)$')
    distribution_mode: str = Field(default='balanceada', pattern='^(balanceada|prioridade|ciclo)$')
    sequence_mode: str = Field(default='intercalada', pattern='^(intercalada|sequencial)$')
    subjects_per_day: int = Field(default=2, ge=1, le=7)
    fixed_subjects: list[str] = Field(default_factory=list)
    priority_subjects: list[str] = Field(default_factory=list)
    theory_pct: int = Field(default=45, ge=0, le=100)
    questions_pct: int = Field(default=30, ge=0, le=100)
    review_pct: int = Field(default=25, ge=0, le=100)
    include_simulados: bool = True
    max_session_minutes: int = Field(default=90, ge=15, le=240)
    custom_instructions: str = Field(default='', max_length=3000)

class ImportPreferences(BaseModel):
    weekly_hours: int = Field(default=20, ge=1, le=84)
    buffer_pct: int = Field(default=10, ge=0, le=50)
    subjects_per_day: int = Field(default=2, ge=1, le=7)
    sequence_mode: str = Field(default='intercalada', pattern='^(intercalada|sequencial)$')
    distribution_mode: str = Field(default='preservar', pattern='^(preservar|balancear|prioridade)$')
    fixed_subjects: list[str] = Field(default_factory=list)
    priority_overrides: dict[str, int] = Field(default_factory=dict)

def normalize_preference_list(values):
    return [squeeze(x) for x in (values or []) if squeeze(x)]

def apply_import_preferences(plan, raw_preferences):
    if not raw_preferences:
        return plan
    prefs=ImportPreferences.model_validate(raw_preferences).model_dump()
    out=copy.deepcopy(plan)
    schedule=out['schedule']
    if not schedule:
        return out
    priorities={norm(k):int(v) for k,v in prefs['priority_overrides'].items() if str(v).isdigit()}
    fixed={norm(x) for x in normalize_preference_list(prefs['fixed_subjects'])}
    dates=sorted({x['date'] for x in schedule})
    def score(item):
        return priorities.get(norm(item['subject']), 3)
    groups=defaultdict(list)
    for item in schedule:
        groups[norm(item['subject'])].append(item)
    ordered_groups=sorted(groups.items(), key=lambda pair:(-priorities.get(pair[0],3), pair[0]))
    if prefs['distribution_mode'] in ('balancear','prioridade') or prefs['sequence_mode']=='sequencial':
        reordered=[]
        if prefs['sequence_mode']=='sequencial':
            for _,items in ordered_groups:
                reordered.extend(items)
        else:
            for index in range(max(len(items) for _,items in ordered_groups)):
                for _,items in ordered_groups:
                    if index<len(items): reordered.append(items[index])
        # Reassign only the date, retaining each session's content, duration and time.
        for index,item in enumerate(reordered):
            item['date']=dates[index % len(dates)]
        schedule=reordered
    # Fixed subjects are placed first on each day, making their daily contact predictable
    # without duplicating or deleting sessions from the NotebookLM plan.
    schedule.sort(key=lambda item:(item['date'], 0 if norm(item['subject']) in fixed else 1,
                                   -score(item), item.get('start_time') or '99:99'))
    out['schedule']=schedule
    out['warnings']=list(out.get('warnings',[]))
    weekly=defaultdict(int)
    for item in schedule:
        monday=date.fromisoformat(item['date'])-timedelta(days=date.fromisoformat(item['date']).weekday())
        weekly[monday.isoformat()]+=int(item['minutes'])
    ceiling=prefs['weekly_hours']*60*(1-prefs['buffer_pct']/100)
    if any(minutes>ceiling for minutes in weekly.values()):
        out['warnings'].append(f"A distribuição selecionada excede a capacidade efetiva de {ceiling/60:.1f}h em pelo menos uma semana; revise a prévia antes de confirmar.")
    if prefs['distribution_mode']!='preservar' or fixed or prefs['priority_overrides']:
        out['warnings'].append('Preferências locais de distribuição aplicadas na prévia: '+
                               f"{prefs['subjects_per_day']} matéria(s) por dia, modo {prefs['distribution_mode']}, sequência {prefs['sequence_mode']}.")
    out['_preferences']=prefs
    return out

def settings(c):
    return {r['key']:j(r['value']) for r in c.execute('SELECT * FROM settings')}

def current(c):
    row=c.execute('SELECT * FROM plan_versions ORDER BY id DESC LIMIT 1').fetchone()
    return {'id':row['id'],'allocations':j(row['allocations'],{}),'note':row['note'],
            'created':row['created']} if row else None

def exams_all(c):
    out=[]
    for r in c.execute('SELECT * FROM exams ORDER BY active DESC, exam_date ASC'):
        x=dict(r); x['subjects']=[dict(s) for s in c.execute('''SELECT es.subject_id, s.name, es.weight, es.questions, es.topics FROM exam_subjects es JOIN subjects s ON s.id=es.subject_id WHERE es.exam_id=?''',(r['id'],))]
        for sub in x['subjects']: sub['topics']=j(sub['topics'],[])
        out.append(x)
    return out

def get_events(c): return [dict(r) for r in c.execute('SELECT * FROM events ORDER BY start_date ASC')]
def get_sessions(c):
    rows=c.execute('''SELECT ss.*, s.name AS subject_name, e.name AS exam_name, e.cargo AS exam_cargo
      FROM sessions ss LEFT JOIN subjects s ON s.id=ss.subject_id
      LEFT JOIN exams e ON e.id=ss.exam_id ORDER BY ss.day ASC, COALESCE(ss.start_time,'') ASC, ss.id ASC''')
    out=[]
    for row in rows:
        item=dict(row); item['qconcursos_filters']=j(item.get('qconcursos_filters'),{})
        out.append(item)
    return out

def attempt_stats(c):
    details=defaultdict(lambda:{'right':0,'total':0})
    attempts=[]
    lookup={r['id']:dict(r) for r in c.execute('SELECT id,subject_id,answer FROM questions')}
    for row in c.execute('SELECT * FROM attempts ORDER BY id DESC'):
        a=dict(row); ids=j(a['question_ids'],[]); answers=j(a['answers'],{})
        attempts.append({'id':a['id'],'name':a['name'],'correct':a['correct_count'],
                         'total':a['total'],'created':a['created']})
        for qid in ids:
            q=lookup.get(qid)
            if not q: continue
            key=q['subject_id']; details[key]['total']+=1
            if answers.get(str(qid),'').upper()==q['answer'].upper(): details[key]['right']+=1
    return dict(details), attempts

@app.get('/')
def home(): return FileResponse(STATIC/'index.html')

@app.get('/static/{filename}')
def static_file(filename:str):
    if filename not in ['styles.css','features.css','app.js','modelo_notebooklm.json']: raise HTTPException(404)
    return FileResponse(STATIC/filename)

@app.get('/api/bootstrap')
def bootstrap():
    with db() as c:
        details,attempts=attempt_stats(c)
        qs=c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        demo=c.execute("SELECT COUNT(*) FROM questions WHERE origin='demonstracao'").fetchone()[0]
        return {'today':iso(local_today()),'subjects':[dict(r) for r in c.execute('SELECT * FROM subjects')],
                'exams':exams_all(c),'events':get_events(c),'sessions':get_sessions(c),
                'settings':settings(c),'plan':current(c),'proposals':[dict(r) | {'old_plan':j(r['old_plan'],{}),'new_plan':j(r['new_plan'],{}),'selected':j(r['selected'],[])} for r in c.execute('SELECT * FROM proposals ORDER BY id DESC LIMIT 15')],
                'versions':[dict(r) | {'allocations':j(r['allocations'],{})} for r in c.execute('SELECT * FROM plan_versions ORDER BY id DESC LIMIT 20')],
                'questions_count':qs,'demo_questions_count':demo,'attempts':attempts[:20],
                'performance':details,'reviews':[dict(r) for r in c.execute('SELECT * FROM reviews ORDER BY due ASC')],
                'topic_progress':[dict(r) for r in c.execute('SELECT * FROM topic_progress')],
                'errors':[dict(r) for r in c.execute("SELECT * FROM error_notebook WHERE status='aberto' ORDER BY COALESCE(next_review,created) LIMIT 100")],
                'spaced_reviews':[dict(r) for r in c.execute("SELECT * FROM spaced_reviews WHERE status='pendente' ORDER BY due LIMIT 100")],
                'editals':[dict(r) for r in c.execute('SELECT id, exam_id, filename, created FROM editals ORDER BY id DESC')],
                'notebooklm_imports':[dict(r) for r in c.execute('SELECT id,filename,plan_title,exam_count,session_count,event_count,period_start,period_end,created FROM notebooklm_imports ORDER BY created DESC LIMIT 12')],
                'dashboard':dashboard_stats(c)}

def dashboard_stats(c):
    total=int(c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0])
    completed=int(c.execute('SELECT COUNT(*) FROM sessions WHERE completed=1').fetchone()[0])
    planned_minutes=int(c.execute('SELECT COALESCE(SUM(minutes),0) FROM sessions').fetchone()[0])
    logs=[dict(r) for r in c.execute('SELECT * FROM study_logs')]
    actual_minutes=sum(int(x['actual_minutes']) for x in logs)
    questions_done=sum(int(x['questions_done']) for x in logs)
    questions_correct=sum(int(x['questions_correct']) for x in logs)
    topics=[dict(r) for r in c.execute('SELECT exam_id,subject_id,topics FROM exam_subjects')]
    total_topics=sum(len(j(x['topics'],[])) for x in topics)
    done_topics=int(c.execute('SELECT COUNT(*) FROM topic_progress WHERE done=1').fetchone()[0])
    today=local_today()
    overdue=int(c.execute('SELECT COUNT(*) FROM spaced_reviews WHERE status=? AND due<?',('pendente',iso(today))).fetchone()[0])
    open_errors=int(c.execute("SELECT COUNT(*) FROM error_notebook WHERE status='aberto'").fetchone()[0])
    risk=[]
    for row in c.execute('''SELECT s.id,s.name,COUNT(ss.id) planned,COALESCE(SUM(ss.completed),0) completed,
          COALESCE(SUM(sl.questions_done),0) questions,COALESCE(SUM(sl.questions_correct),0) correct
          FROM subjects s LEFT JOIN sessions ss ON ss.subject_id=s.id LEFT JOIN study_logs sl ON sl.session_id=ss.id GROUP BY s.id,s.name'''):
        accuracy=(row['correct']/row['questions']) if row['questions'] else .5
        adherence=(row['completed']/row['planned']) if row['planned'] else 1
        score=round((1-accuracy)*60+(1-adherence)*40)
        risk.append({'subject_id':row['id'],'subject_name':row['name'],'score':score,'level':'alto' if score>=60 else 'médio' if score>=30 else 'baixo','accuracy_pct':round(accuracy*100,1),'adherence_pct':round(adherence*100,1)})
    risk.sort(key=lambda x:x['score'],reverse=True)
    return {'planned_sessions':total,'completed_sessions':completed,'adherence_pct':round(completed/total*100,1) if total else 0,
            'planned_minutes':planned_minutes,'actual_minutes':actual_minutes,
            'questions_done':questions_done,'questions_correct':questions_correct,
            'accuracy_pct':round(questions_correct/questions_done*100,1) if questions_done else 0,
            'topic_coverage_pct':round(done_topics/total_topics*100,1) if total_topics else 0,
            'topics_done':done_topics,'topics_total':total_topics,'overdue_reviews':overdue,'open_errors':open_errors,
            'risk':risk[:8]}

@app.get('/api/dashboard')
def dashboard():
    with db() as c:
        return dashboard_stats(c)

@app.get('/api/daily-summary')
def daily_summary(day:str|None=None):
    target=validate_date(day) if day else local_today()
    with db() as c:
        planned=c.execute('SELECT COUNT(*) FROM sessions WHERE day=?',(iso(target),)).fetchone()[0]
        completed=c.execute('SELECT COUNT(*) FROM sessions WHERE day=? AND completed=1',(iso(target),)).fetchone()[0]
        actual=c.execute('''SELECT COALESCE(SUM(sl.actual_minutes),0) FROM study_logs sl JOIN sessions ss ON ss.id=sl.session_id WHERE ss.day=?''',(iso(target),)).fetchone()[0]
        questions=c.execute('''SELECT COALESCE(SUM(sl.questions_done),0),COALESCE(SUM(sl.questions_correct),0) FROM study_logs sl JOIN sessions ss ON ss.id=sl.session_id WHERE ss.day=?''',(iso(target),)).fetchone()
        return {'day':iso(target),'planned':planned,'completed':completed,'actual_minutes':actual,'questions_done':questions[0],'questions_correct':questions[1],
                'adherence_pct':round(completed/planned*100,1) if planned else 0,'message':'Consistência importa mais que perfeição.' if completed==planned else 'Escolha um bloco curto para fechar o dia.'}

@app.get('/api/sessions/{session_id}/focus')
def focus_session(session_id:int):
    with db() as c:
        row=c.execute('''SELECT ss.*,s.name AS subject_name,e.name AS exam_name,e.cargo AS exam_cargo
          FROM sessions ss LEFT JOIN subjects s ON s.id=ss.subject_id LEFT JOIN exams e ON e.id=ss.exam_id WHERE ss.id=?''',(session_id,)).fetchone()
        if not row: raise HTTPException(404,'Sessão não encontrada')
        item=dict(row); item['qconcursos_filters']=j(item.get('qconcursos_filters'),{})
        item['logs']=[dict(x) for x in c.execute('SELECT * FROM study_logs WHERE session_id=? ORDER BY id DESC',(session_id,))]
        return item

@app.post('/api/study-logs')
def create_study_log(p:StudyLogIn):
    with db() as c:
        session=c.execute('SELECT id,subject_id,exam_id,topic FROM sessions WHERE id=?',(p.session_id,)).fetchone()
        if not session: raise HTTPException(404,'Sessão não encontrada')
        if p.questions_correct>p.questions_done: raise HTTPException(422,'Acertos não podem superar questões realizadas')
        cur=c.execute('''INSERT INTO study_logs(session_id,actual_minutes,questions_done,questions_correct,difficulty,confidence,interruptions,notes,created)
          VALUES(?,?,?,?,?,?,?,?,?)''',(p.session_id,p.actual_minutes,p.questions_done,p.questions_correct,p.difficulty,p.confidence,p.interruptions,p.notes,now()))
        c.execute('UPDATE sessions SET completed=1 WHERE id=?',(p.session_id,))
        due=local_today()+timedelta(days=1 if p.confidence<=2 or (p.questions_done and p.questions_correct/p.questions_done<.7) else 7)
        c.execute('''INSERT INTO spaced_reviews(subject_id,exam_id,topic,due,interval_days,ease,last_score,created)
          VALUES(?,?,?,?,?,?,?,?)''',(session['subject_id'],session['exam_id'],session['topic'] or '',iso(due),1 if p.confidence<=2 else 7,2.5,(p.questions_correct/p.questions_done if p.questions_done else None),now()))
        return {'ok':True,'id':cur.lastrowid,'review_due':iso(due)}

@app.get('/api/errors')
def list_errors(status:str='aberto'):
    with db() as c:
        if status not in ('aberto','resolvido','todos'): raise HTTPException(422,'Status inválido')
        query='SELECT * FROM error_notebook ORDER BY CASE WHEN status=\'aberto\' THEN 0 ELSE 1 END, COALESCE(next_review,created)'
        if status!='todos': query='SELECT * FROM error_notebook WHERE status=? ORDER BY COALESCE(next_review,created)'
        rows=c.execute(query,(status,) if status!='todos' else ()).fetchall()
        return [dict(r) for r in rows]

@app.post('/api/errors')
def create_error(p:ErrorIn):
    validate_date(p.next_review) if p.next_review else None
    with db() as c:
        if not c.execute('SELECT id FROM subjects WHERE id=?',(p.subject_id,)).fetchone(): raise HTTPException(422,'Matéria inválida')
        cur=c.execute('''INSERT INTO error_notebook(subject_id,topic,source,error_type,note,next_review,created)
          VALUES(?,?,?,?,?,?,?)''',(p.subject_id,p.topic,p.source,p.error_type,p.note,p.next_review,now()))
        return {'ok':True,'id':cur.lastrowid}

@app.patch('/api/errors/{error_id}')
def update_error(error_id:int,p:ErrorUpdate):
    with db() as c:
        if not c.execute('SELECT id FROM error_notebook WHERE id=?',(error_id,)).fetchone(): raise HTTPException(404,'Erro não encontrado')
        c.execute('UPDATE error_notebook SET status=?,resolved=? WHERE id=?',(p.status,now() if p.status=='resolvido' else None,error_id))
    return {'ok':True}

@app.get('/api/reviews')
def list_reviews():
    with db() as c:
        return [dict(r) for r in c.execute('''SELECT sr.*,s.name AS subject_name,e.name AS exam_name FROM spaced_reviews sr
          LEFT JOIN subjects s ON s.id=sr.subject_id LEFT JOIN exams e ON e.id=sr.exam_id
          WHERE sr.status='pendente' ORDER BY sr.due,sr.id''')]

@app.patch('/api/reviews/{review_id}/complete')
def complete_spaced_review(review_id:int,p:ReviewResult):
    with db() as c:
        row=c.execute('SELECT * FROM spaced_reviews WHERE id=? AND status=\'pendente\'',(review_id,)).fetchone()
        if not row: raise HTTPException(404,'Revisão não encontrada')
        interval=max(1,round((row['interval_days'] or 1)*(2.0 if p.score>=.85 else 1.0 if p.score>=.6 else .5)))
        c.execute('UPDATE spaced_reviews SET status=\'concluida\',last_score=?,completed=? WHERE id=?',(p.score,now(),review_id))
        if p.score<.7:
            c.execute('''INSERT INTO spaced_reviews(subject_id,exam_id,topic,due,interval_days,ease,last_score,created)
              VALUES(?,?,?,?,?,?,?,?)''',(row['subject_id'],row['exam_id'],row['topic'],iso(local_today()+timedelta(days=interval)),interval,row['ease'],p.score,now()))
        return {'ok':True,'next_interval_days':interval}

@app.post('/api/replan')
def replan(p:ReplanIn):
    start=validate_date(p.from_day) if p.from_day else local_today()
    with db() as c:
        pending=[dict(r) for r in c.execute('''SELECT * FROM sessions WHERE completed=0 AND day<? ORDER BY day,id''',(iso(start),))]
        if not pending: return {'ok':True,'moved':0,'message':'Nenhuma sessão atrasada.'}
        days=settings(c).get('study_days',[0,1,2,3,4,5]) or [0]
        cursor=start; moved=0
        for item in pending:
            while cursor.weekday() not in days: cursor+=timedelta(days=1)
            c.execute('UPDATE sessions SET day=? WHERE id=?',(iso(cursor),item['id']))
            moved+=1; cursor+=timedelta(days=1)
        return {'ok':True,'moved':moved,'from_day':iso(start),'strategy':p.strategy}

@app.post('/api/exams')
def create_exam(payload:NewExam):
    if payload.exam_date: validate_date(payload.exam_date)
    with db() as c:
        ids={r['id'] for r in c.execute('SELECT id FROM subjects')}
        if not set(payload.subjects)<=ids: raise HTTPException(422,'Matéria desconhecida')
        cur=c.execute('INSERT INTO exams(name,cargo,institution,banca,exam_date,priority,source,created) VALUES(?,?,?,?,?,?,?,?)',
                      (payload.name,payload.cargo,payload.institution,payload.banca,payload.exam_date,payload.priority,'manual',now()))
        eid=cur.lastrowid
        for sub in set(payload.subjects):
            c.execute('INSERT INTO exam_subjects(exam_id,subject_id) VALUES(?,?)',(eid,sub))
        if payload.exam_date:
            c.execute('INSERT INTO events(exam_id,title,type,start_date,end_date,created) VALUES(?,?,?,?,?,?)',
                      (eid,'Prova — '+payload.name,'prova',payload.exam_date,payload.exam_date,now()))
    return {'ok':True,'id':eid}

@app.patch('/api/exams/{exam_id}')
def patch_exam(exam_id:int, data:dict):
    allow={'priority','active','exam_date','name','cargo','banca'}
    fields={k:v for k,v in data.items() if k in allow}
    if not fields: raise HTTPException(422,'Sem dados válidos')
    if 'exam_date' in fields and fields['exam_date']: validate_date(fields['exam_date'])
    for key in ('name','cargo','banca'):
        if key in fields and not isinstance(fields[key], str):
            raise HTTPException(422, f'{key} deve ser texto')
        if key in fields and len(fields[key]) > 150:
            raise HTTPException(422, f'{key} muito longo')
    with db() as c:
        if not c.execute('SELECT id FROM exams WHERE id=?',(exam_id,)).fetchone(): raise HTTPException(404)
        c.execute('UPDATE exams SET '+', '.join(f'{k}=?' for k in fields)+' WHERE id=?',list(fields.values())+[exam_id])
        if 'exam_date' in fields:
            c.execute('UPDATE events SET start_date=?,end_date=? WHERE exam_id=? AND type=?',
                      (fields['exam_date'],fields['exam_date'],exam_id,'prova'))
    return {'ok':True}

def validate_date(x):
    try: return date.fromisoformat(x)
    except Exception: raise HTTPException(422,'Data deve estar em AAAA-MM-DD')


class TopicUpdate(BaseModel):
    topics: list[str] = []
    weight: float = Field(default=1, ge=0.1, le=20)
    questions: int = Field(default=10, ge=1, le=300)

class TopicProgressUpdate(BaseModel):
    exam_id: int
    subject_id: str
    topic: str
    done: bool = True

class SubjectCreate(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    category: str = 'Personalizada'

@app.post('/api/subjects')
def create_subject(p:SubjectCreate):
    slug=norm(p.name).strip().replace(' ','-')
    slug=re.sub(r'[^a-z0-9-]','',slug)
    if not slug:raise HTTPException(422,'Nome inválido')
    with db() as c:
        existing=c.execute('SELECT id FROM subjects WHERE id=?',(slug,)).fetchone()
        if existing:raise HTTPException(409,'Disciplina já cadastrada')
        c.execute('INSERT INTO subjects VALUES (?,?,?)',(slug,p.name.strip(),p.category.strip()[:80]))
    return {'ok':True,'id':slug}

@app.post('/api/exams/{exam_id}/subjects/{subject_id}')
def add_exam_subject(exam_id:int,subject_id:str):
    with db() as c:
        if not c.execute('SELECT id FROM exams WHERE id=?',(exam_id,)).fetchone():raise HTTPException(404,'Concurso inexistente')
        if not c.execute('SELECT id FROM subjects WHERE id=?',(subject_id,)).fetchone():raise HTTPException(404,'Disciplina inexistente')
        c.execute('INSERT OR IGNORE INTO exam_subjects(exam_id,subject_id) VALUES (?,?)',(exam_id,subject_id))
    return {'ok':True}

@app.put('/api/exams/{exam_id}/subjects/{subject_id}')
def update_exam_subject(exam_id:int,subject_id:str,p:TopicUpdate):
    topics=list(dict.fromkeys(t.strip() for t in p.topics if t.strip()))[:300]
    if any(len(t)>500 for t in topics):raise HTTPException(422,'Tópico muito longo')
    with db() as c:
        r=c.execute('UPDATE exam_subjects SET topics=?,weight=?,questions=? WHERE exam_id=? AND subject_id=?',
                  (json.dumps(topics,ensure_ascii=False),p.weight,p.questions,exam_id,subject_id))
        if not r.rowcount:raise HTTPException(404,'Matéria não vinculada ao concurso')
        # Clear progress of deleted topics; keep progress matching exact text.
        if topics:
            ph=','.join('?'*len(topics))
            c.execute(f'DELETE FROM topic_progress WHERE exam_id=? AND subject_id=? AND topic NOT IN ({ph})',
                      [exam_id,subject_id,*topics])
        else:c.execute('DELETE FROM topic_progress WHERE exam_id=? AND subject_id=?',(exam_id,subject_id))
    return {'ok':True,'topics':topics}

@app.post('/api/topics/progress')
def mark_topic(p:TopicProgressUpdate):
    with db() as c:
        sub=c.execute('SELECT topics FROM exam_subjects WHERE exam_id=? AND subject_id=?',
                   (p.exam_id,p.subject_id)).fetchone()
        if not sub or p.topic not in j(sub['topics'],[]):raise HTTPException(422,'Tópico não vinculado ao edital')
        c.execute('INSERT INTO topic_progress(exam_id,subject_id,topic,done) VALUES (?,?,?,?) ON CONFLICT(exam_id,subject_id,topic) DO UPDATE SET done=excluded.done',
                  (p.exam_id,p.subject_id,p.topic,int(p.done)))
    return {'ok':True}

@app.post('/api/events')
def create_event(p:EventIn):
    d1=validate_date(p.start_date);d2=validate_date(p.end_date)
    if d2<d1: raise HTTPException(422,'Fim do período anterior ao início')
    if p.type not in {'inscricao','isencao','prova','pagamento','recurso','resultado','convocacao','taf','outro'}: raise HTTPException(422,'Tipo inválido')
    with db() as c:
        if p.exam_id and not c.execute('SELECT id FROM exams WHERE id=?',(p.exam_id,)).fetchone():
            raise HTTPException(404,'Concurso vinculado não encontrado')
        cur=c.execute('INSERT INTO events(exam_id,title,type,start_date,end_date,status,notes,source_reference,created) VALUES(?,?,?,?,?,?,?,?,?)',
                      (p.exam_id,p.title,p.type,p.start_date,p.end_date,p.status,p.notes,p.source_reference,now()))
        return {'ok':True,'id':cur.lastrowid}

@app.patch('/api/events/{event_id}')
def event_update(event_id:int, data:dict):
    if data.get('status') not in ['pendente','concluido'] : raise HTTPException(422,'Status inválido')
    with db() as c:
        if not c.execute('SELECT id FROM events WHERE id=?',(event_id,)).fetchone(): raise HTTPException(404,'Prazo não encontrado')
        c.execute('UPDATE events SET status=? WHERE id=?',(data['status'],event_id))
    return {'ok':True}

@app.post('/api/settings')
def save_settings(p:SettingIn):
    if not p.study_days or any(x not in range(7) for x in p.study_days): raise HTTPException(422,'Selecione dias válidos')
    with db() as c:
        for k,v in p.model_dump().items():
            c.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v)))
    return {'ok':True}

def allocate(c):
    st=settings(c);weekly=st.get('weekly_hours',20); buffer=st.get('buffer_pct',10)
    total=max(0.5, round(weekly*(1-buffer/100)*2)/2)
    exams=[e for e in exams_all(c) if e['active']]
    if not exams: return {}
    score=defaultdict(float)
    details,_=attempt_stats(c)
    today=local_today()
    for exam in exams:
        days=max(1,(date.fromisoformat(exam['exam_date'])-today).days) if exam['exam_date'] else 90
        if days<0: continue
        urgency=1+min(2,60/max(14,days))
        priority={1:0.8,2:1.0,3:1.45}[exam['priority']]
        for sub in exam['subjects']:
            weight=float(sub['weight']) * max(5,int(sub['questions']))**0.5
            score[sub['subject_id']]+=weight*priority*urgency
    if not score:return {}
    for sid in score:
        p=details.get(sid)
        if p and p['total']>=3:
            accuracy=p['right']/p['total']
            score[sid]*=(1+0.45*(1-accuracy))
    if st.get('strategy')=='proxima':
        nearest=next((e for e in sorted(exams,key=lambda e:e['exam_date'] or '9999') if e['exam_date']),None)
        if nearest:
            for s in nearest['subjects']:score[s['subject_id']]*=1.6
    if st.get('strategy')=='desempenho':
        for sid in score:
            p=details.get(sid)
            if p and p['total']>=3:score[sid]*=(1+1.2*(1-p['right']/p['total']))
    if st.get('strategy')=='pesos':
        for sid in score:score[sid]**=1.3
    # Round half-hours by largest remainder. If the available capacity is smaller
    # than the number of subjects, prioritize instead of exceeding the weekly cap.
    total_units=max(1,round(total*2))
    if total_units < len(score):
        score=dict(sorted(score.items(),key=lambda item:item[1],reverse=True)[:total_units])
    units=total_units
    total_units=units
    total_score=sum(score.values())
    shares={k:score[k]/total_score*total_units for k in score}
    allocations={k:1 for k in shares}
    remaining=total_units-len(shares)
    if remaining:
        extra_shares={k:max(0,shares[k]-1) for k in shares}
        divisor=sum(extra_shares.values())
        if not divisor:extra_shares={k:1 for k in shares};divisor=len(shares)
        exact={k:remaining*extra_shares[k]/divisor for k in shares}
        for k in shares:allocations[k]+=int(exact[k])
        leftover=total_units-sum(allocations.values())
        for k in sorted(shares,key=lambda k:exact[k]-int(exact[k]),reverse=True)[:leftover]:allocations[k]+=1
    return {k:v/2 for k,v in allocations.items()}

@app.post('/api/proposals/generate')
def propose(data:dict | None = None):
    reason=(data or {}).get('reason','Reavaliação de prioridades')
    with db() as c:
        existing=current(c)
        old=existing['allocations'] if existing else {}
        new=allocate(c)
        if not new: raise HTTPException(422,'Cadastre matérias em um concurso ativo')
        keys=set(old)|set(new)
        delta=[{'subject_id':k,'old':old.get(k,0),'new':new.get(k,0),'delta':round(new.get(k,0)-old.get(k,0),2)} for k in keys if old.get(k,0)!=new.get(k,0)]
        added=sum(1 for x in delta if x['old']==0)
        removed=sum(1 for x in delta if x['new']==0)
        rationale=f'Plano recalculado a partir das prioridades, pesos, proximidade das provas e desempenho registrado. {added} disciplina(s) incluída(s), {removed} retirada(s); {len(delta)} alteração(ões). A mudança não será aplicada sem aprovação.'
        cur=c.execute('INSERT INTO proposals(old_plan,new_plan,rationale,trigger,created) VALUES(?,?,?,?,?)',
                      (json.dumps(old),json.dumps(new),rationale,str(reason)[:240],now()))
        return {'id':cur.lastrowid,'old_plan':old,'new_plan':new,'changes':delta,'rationale':rationale,'status':'pendente'}

@app.post('/api/proposals/{proposal_id}/accept')
def accept_proposal(proposal_id:int,p:ProposalChoice):
    with db() as c:
        r=c.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone()
        if not r:raise HTTPException(404)
        if r['status']!='pendente':raise HTTPException(409,'Proposta já resolvida')
        old=j(r['old_plan'],{});new=j(r['new_plan'],{})
        changed={s for s in set(old)|set(new) if old.get(s,0)!=new.get(s,0)}
        selected=set(p.subject_ids)&changed
        if not selected:raise HTTPException(422,'Selecione pelo menos uma alteração')
        latest=current(c)['allocations']
        if latest!=old:raise HTTPException(409,'O plano mudou após esta proposta. Gere uma nova comparação.')
        final=dict(old)
        for key in selected:
            if new.get(key,0)>0:final[key]=new[key]
            else:final.pop(key,None)
        ceiling=settings(c)['weekly_hours']
        if sum(final.values())>ceiling+0.001:
            raise HTTPException(422, f'A seleção exige {sum(final.values()):g}h, ultrapassando as {ceiling}h disponíveis. Inclua reduções ou aumente sua meta semanal.')
        c.execute('INSERT INTO plan_versions(allocations,note,created) VALUES(?,?,?)',
                  (json.dumps(final),f'Alterações aprovadas da proposta #{proposal_id}',now()))
        c.execute('UPDATE proposals SET status=?,selected=?,resolved=? WHERE id=?',
                  ('aceita',json.dumps(sorted(selected)),now(),proposal_id))
        return {'ok':True,'plan':final,'selected':sorted(selected)}

@app.post('/api/proposals/{proposal_id}/reject')
def reject_proposal(proposal_id:int):
    with db() as c:
        r=c.execute('UPDATE proposals SET status=?,resolved=? WHERE id=? AND status=?',
                    ('rejeitada',now(),proposal_id,'pendente'))
        if r.rowcount==0:raise HTTPException(409,'Proposta indisponível ou já resolvida')
    return {'ok':True}

@app.post('/api/versions/{version_id}/restore')
def restore_version(version_id:int):
    with db() as c:
        r=c.execute('SELECT * FROM plan_versions WHERE id=?',(version_id,)).fetchone()
        if not r:raise HTTPException(404)
        c.execute('INSERT INTO plan_versions(allocations,note,restored_from,created) VALUES(?,?,?,?)',
                  (r['allocations'],f'Plano restaurado a partir da versão #{version_id}',version_id,now()))
    return {'ok':True}

@app.post('/api/sessions')
def add_session(p:SessionIn):
    validate_date(p.day)
    if p.start_time and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',p.start_time):
        raise HTTPException(422,'Horário deve estar em HH:MM')
    if p.activity_type not in {'estudo','teoria','questoes','revisao','simulado','lei_seca','resumo','redacao','outro'}:
        raise HTTPException(422,'Tipo de atividade inválido')
    with db() as c:
        if not c.execute('SELECT id FROM subjects WHERE id=?',(p.subject_id,)).fetchone():raise HTTPException(422,'Matéria inválida')
        if p.exam_id and not c.execute('SELECT id FROM exams WHERE id=?',(p.exam_id,)).fetchone():
            raise HTTPException(422,'Concurso vinculado não encontrado')
        cur=c.execute('''INSERT INTO sessions(day,subject_id,minutes,completed,created,exam_id,start_time,topic,activity_type,objective,qconcursos_filters,source_reference)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
          (p.day,p.subject_id,p.minutes,int(p.completed),now(),p.exam_id,p.start_time or '',p.topic,p.activity_type,
           p.objective,json.dumps(p.qconcursos_filters,ensure_ascii=False),p.source_reference))
        return {'ok':True,'id':cur.lastrowid}

@app.patch('/api/sessions/{session_id}')
def patch_session(session_id:int, d:dict):
    with db() as c:
        r=c.execute('SELECT id FROM sessions WHERE id=?',(session_id,)).fetchone()
        if not r:raise HTTPException(404)
        if 'completed' in d:
            c.execute('UPDATE sessions SET completed=? WHERE id=?',(int(bool(d['completed'])),session_id))
    return {'ok':True}

@app.post('/api/schedule/week')
def schedule_week(req:StudySchedule):
    start=validate_date(req.start_day) if req.start_day else local_today()
    monday=start-timedelta(days=start.weekday())
    with db() as c:
        active_plan=current(c)
        if not active_plan: raise HTTPException(422,'Gere ou importe um plano antes de criar a semana')
        plan=active_plan['allocations'];st=settings(c)
        days=sorted(set(st['study_days']))
        if not days:raise HTTPException(422,'Nenhum dia de estudo')
        # Exclude exam days; do not silently cancel already completed sessions.
        exams={r['start_date'] for r in c.execute("SELECT start_date FROM events WHERE type='prova'")}
        free=[monday+timedelta(days=i) for i in days if iso(monday+timedelta(days=i)) not in exams]
        if not free:raise HTTPException(422,'Nenhum dia livre para estudo nesta semana')
        c.execute('DELETE FROM sessions WHERE day>=? AND day<=? AND completed=0',
                  (iso(monday),iso(monday+timedelta(days=6))))
        time_by_day={iso(d):0 for d in free};created=[]
        chunks=[]
        for sid,hours_ in plan.items():
            minutes=int(round(hours_*60));
            while minutes:
                chunk=min(60,minutes)
                chunks.append((sid,chunk));minutes-=chunk
        # Distribute moderate blocks, preferring least-loaded days.
        for sid,minutes in sorted(chunks,key=lambda x:-x[1]):
            d=min(free,key=lambda day:time_by_day[iso(day)])
            key=iso(d)
            c.execute('INSERT INTO sessions(day,subject_id,minutes,completed,created) VALUES(?,?,?,0,?)',
                      (key,sid,minutes,now()))
            time_by_day[key]+=minutes
            created.append({'day':key,'subject_id':sid,'minutes':minutes})
        return {'ok':True,'created':len(created),'schedule':created}

@app.post('/api/questions/import')
async def import_questions(file:UploadFile=File(...)):
    data=await file.read(2_000_001)
    if len(data)>2_000_000:raise HTTPException(413,'Limite de 2 MB para CSV')
    try:
        text=data.decode('utf-8-sig'); sample=text[:2048]
        dialect=csv.Sniffer().sniff(sample,delimiters=',;')
        rows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
    except Exception as e:raise HTTPException(422,f'CSV inválido: {e}')
    required={'subject_id','statement','option_a','option_b','option_c','option_d','answer','source'}
    if not rows or not required<=set(rows[0]): raise HTTPException(422,'Cabeçalhos obrigatórios: '+', '.join(sorted(required)))

    with db() as c: subjects={r['id'] for r in c.execute('SELECT id FROM subjects')}
    good=[];errors=[]
    for i,r in enumerate(rows[:5000],2):
        try:
            sid=(r.get('subject_id') or '').strip()
            answer=(r.get('answer') or '').strip().upper()
            source=(r.get('source') or '').strip()
            if sid not in subjects or answer not in 'ABCD' or len(answer)!=1 or not source or not r['statement'].strip():
                raise ValueError('Matéria, gabarito, enunciado ou fonte inválidos')
            year=int(r['year']) if (r.get('year') or '').strip() else None
            options=[r[f'option_{k}'].strip() for k in 'abcd']
            if not all(options):raise ValueError('Alternativa vazia')
            good.append((sid,(r.get('topic') or '').strip(),r['statement'].strip(),json.dumps(options),answer,
                        (r.get('banca') or '').strip(),year,source,(r.get('source_url') or '').strip(),
                        (r.get('difficulty') or 'média').strip(),'importada',
                        (r.get('rights_note') or 'Responsabilidade do importador quanto aos direitos de utilização').strip(),now()))
        except (ValueError,KeyError,TypeError) as e: errors.append(f'Linha {i}: {e}')
    if errors:raise HTTPException(422,'; '.join(errors[:8]))
    with db() as c:
        c.executemany('''INSERT INTO questions(subject_id,topic,statement,options,answer,banca,year,source,source_url,difficulty,origin,rights_note,created)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',good)
    return {'ok':True,'imported':len(good)}

@app.get('/api/questions')
def list_questions():
    with db() as c:
        return [{'id':r['id'],'subject_id':r['subject_id'],'topic':r['topic'],
          'banca':r['banca'],'year':r['year'],'origin':r['origin'],'source':r['source']} for r in c.execute('SELECT * FROM questions ORDER BY id DESC LIMIT 500')]

@app.post('/api/quizzes/create')
def create_quiz(p:QuizSettings):
    with db() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM questions')]
        if p.exam_id:
            valid={r['subject_id'] for r in c.execute('SELECT subject_id FROM exam_subjects WHERE exam_id=?',(p.exam_id,))}
            rows=[r for r in rows if r['subject_id'] in valid]
        if p.subject_ids:rows=[r for r in rows if r['subject_id'] in p.subject_ids]
        if p.banca:rows=[r for r in rows if p.banca.lower() in r['banca'].lower()]
        if p.difficulty:rows=[r for r in rows if r['difficulty']==p.difficulty]
        if p.year_min:rows=[r for r in rows if r['year'] and r['year']>=p.year_min]
        if p.year_max:rows=[r for r in rows if r['year'] and r['year']<=p.year_max]
        if p.mode in ('erradas','ineditas'):
            attempts=[dict(r) for r in c.execute('SELECT question_ids,answers FROM attempts')]
            seen=set();wrong=set()
            answers_lookup={r['id']:r['answer'] for r in rows}
            for a in attempts:
                for qid in j(a['question_ids'],[]):
                    seen.add(qid)
                    if qid in answers_lookup and j(a['answers'],{}).get(str(qid),'')!=answers_lookup[qid]:wrong.add(qid)
            rows=[r for r in rows if r['id'] in wrong] if p.mode=='erradas' else [r for r in rows if r['id'] not in seen]
        # Stable but diversified order via SQLite? random query through random module seeded each call.
        import random
        random.shuffle(rows)
        selected=rows[:p.amount]
        return {'questions':[{'id':r['id'],'subject_id':r['subject_id'],'topic':r['topic'],
          'statement':r['statement'],'options':j(r['options'],[]),'source':r['source'],
          'banca':r['banca'],'year':r['year'],'origin':r['origin']} for r in selected],
          'available':len(rows),'asked':p.amount}

@app.post('/api/quizzes/submit')
def submit_quiz(p:QuizSubmit):
    ids=list(dict.fromkeys(p.question_ids))
    if not ids:raise HTTPException(422,'Simulado vazio')
    with db() as c:
        ph=','.join('?'*len(ids))
        q={r['id']:dict(r) for r in c.execute('SELECT * FROM questions WHERE id IN ('+ph+')',ids)}
        if len(q)!=len(ids):raise HTTPException(422,'Questão inválida')
        results=[];correct=0
        for qid in ids:
            question=q[qid];given=p.answers.get(str(qid),'').upper()
            good=given==question['answer'].upper();correct+=int(good)
            results.append({'question_id':qid,'given':given,'answer':question['answer'],'correct':good,
                            'subject_id':question['subject_id'],'topic':question['topic']})
            if not good and settings(c)['auto_review']:
                c.execute('INSERT INTO reviews(subject_id,question_id,due,created) VALUES(?,?,?,?)',
                          (question['subject_id'],qid,iso(local_today()+timedelta(days=1)),now()))
        cur=c.execute('INSERT INTO attempts(name,question_ids,answers,correct_count,total,created) VALUES(?,?,?,?,?,?)',
                      (p.name,json.dumps(ids),json.dumps(p.answers),correct,len(ids),now()))
        return {'ok':True,'id':cur.lastrowid,'correct':correct,'total':len(ids),'results':results}

@app.patch('/api/reviews/{review_id}')
def review_done(review_id:int):
    with db() as c:
        if not c.execute('SELECT id FROM reviews WHERE id=?',(review_id,)).fetchone(): raise HTTPException(404,'Revisão não encontrada')
        c.execute("UPDATE reviews SET status='concluida' WHERE id=?",(review_id,))
    return {'ok':True}

# Importação estruturada do NotebookLM. O EditalOS não executa modelos de IA.
QCONCURSOS_URL = 'https://www.qconcursos.com/questoes-de-concursos/questoes'
NOTEBOOKLM_SCHEMA = 'editalos.notebooklm.v1'
NOTEBOOKLM_MAX_BYTES = 8_000_000


def imported_subject_id(c, name):
    title=squeeze(name)
    if not title:
        raise HTTPException(422,'Disciplina sem nome no arquivo.')
    existing=c.execute('SELECT id,name FROM subjects').fetchall()
    for item in existing:
        if norm(item['name'])==norm(title):
            return item['id']
    aliases={'lingua portuguesa':'portugues','portugues':'portugues',
             'nocoes de informatica':'informatica','nocões de informatica':'informatica',
             'legislacao institucional':'legislacao','redacao oficial':'redacao',
             'raciocinio logico matematico':'logica','raciocinio logico':'logica'}
    alias=aliases.get(norm(title))
    if alias and any(item['id']==alias for item in existing):
        return alias
    slug=re.sub(r'[^a-z0-9]+','-',norm(title)).strip('-')[:52] or 'disciplina'
    if any(item['id']==slug for item in existing):
        slug=slug[:42]+'-'+hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]
    c.execute('INSERT INTO subjects(id,name,category) VALUES(?,?,?)',(slug,title,'Planejamento NotebookLM'))
    return slug


def iso_required(value, label, nullable=False):
    if value in (None,'') and nullable:
        return None
    if not isinstance(value,str):
        raise HTTPException(422,f'{label}: informe data no formato AAAA-MM-DD.')
    try:
        parsed=date.fromisoformat(value)
    except Exception:
        raise HTTPException(422,f'{label}: data inválida. Use AAAA-MM-DD.')
    if parsed.isoformat()!=value:
        raise HTTPException(422,f'{label}: use AAAA-MM-DD.')
    return value


def normalize_notebook_plan(data):
    if not isinstance(data,dict):
        raise HTTPException(422,'O arquivo precisa conter um objeto JSON na raiz.')
    if data.get('schema') != NOTEBOOKLM_SCHEMA:
        raise HTTPException(422,f"Modelo de arquivo incompatível. O campo 'schema' deve ser '{NOTEBOOKLM_SCHEMA}'. Baixe o prompt e o modelo dentro do EditalOS.")
    metadata=data.get('metadata') or {}
    if not isinstance(metadata,dict):
        raise HTTPException(422, 'O campo metadata deve ser um objeto JSON.')
    period=data.get('planning_period') or {}
    if not isinstance(period,dict):
        raise HTTPException(422, 'O campo planning_period deve ser um objeto JSON.')
    exams=data.get('exams') or []
    schedule=data.get('schedule') or []
    events=data.get('events') or []
    if not isinstance(exams,list) or not exams or len(exams)>20:
        raise HTTPException(422,'O arquivo deve conter de 1 a 20 concursos/cargos em "exams".')
    if not isinstance(schedule,list) or not schedule or len(schedule)>2000:
        raise HTTPException(422,'O arquivo deve conter de 1 a 2.000 sessões datadas em "schedule".')
    if not isinstance(events,list) or len(events)>300:
        raise HTTPException(422,'A lista "events" deve conter até 300 prazos.')
    refs={}; warnings=[]; out_exams=[]
    for index, raw in enumerate(exams,1):
        if not isinstance(raw,dict):
            raise HTTPException(422,f'Concurso/cargo #{index} precisa ser um objeto.')
        ref=squeeze(raw.get('ref') or f'concurso_{index}')
        name=squeeze(raw.get('name'))
        cargo=squeeze(raw.get('cargo'))
        if not name or not cargo:
            raise HTTPException(422,f'Concurso/cargo #{index}: informe name e cargo.')
        if ref in refs:
            raise HTTPException(422,f'Referência de concurso repetida: {ref}.')
        exam_date=iso_required(raw.get('exam_date'),'Data da prova',True)
        try: priority=int(raw.get('priority') or 2)
        except (ValueError,TypeError): priority=2
        if priority not in (1,2,3): priority=2
        subjects=raw.get('subjects') or []
        if not isinstance(subjects,list) or len(subjects)>100:
            raise HTTPException(422,f'{name}: subjects deve ser uma lista com até 100 matérias.')
        clean_subjects=[]; seen_subjects=set()
        for si, sub in enumerate(subjects,1):
            if not isinstance(sub,dict) or not squeeze(sub.get('name')):
                raise HTTPException(422,f'{name}: matéria #{si} sem nome.')
            subname=squeeze(sub.get('name'))
            if norm(subname) in seen_subjects: continue
            seen_subjects.add(norm(subname))
            topics=sub.get('topics') or []
            if not isinstance(topics,list): topics=[]
            topics=list(dict.fromkeys(squeeze(t)[:300] for t in topics if squeeze(t)))[:300]
            try: weight=float(sub.get('weight') or 1)
            except (ValueError,TypeError): weight=1
            try: questions=int(sub.get('questions') or 0)
            except (ValueError,TypeError): questions=0
            clean_subjects.append({'name':subname,'weight':max(.1,min(weight,20)),
                                   'questions':max(0,min(questions,1000)),'topics':topics})
        refs[ref]=len(out_exams)
        out_exams.append({'ref':ref,'name':name,'cargo':cargo,'institution':squeeze(raw.get('institution')),
          'banca':squeeze(raw.get('banca')),'exam_date':exam_date,'priority':priority,
          'registration_start':iso_required(raw.get('registration_start'),'Início das inscrições',True),
          'registration_end':iso_required(raw.get('registration_end'),'Fim das inscrições',True),
          'exemption_start':iso_required(raw.get('exemption_start'),'Início da isenção',True),
          'exemption_end':iso_required(raw.get('exemption_end'),'Fim da isenção',True),
          'subjects':clean_subjects})
    clean_schedule=[]; counts_by_day={}; total_minutes=0
    valid_types={'teoria','questoes','revisao','simulado','lei_seca','resumo','redacao','outro'}
    for i, raw in enumerate(schedule,1):
        if not isinstance(raw,dict): raise HTTPException(422,f'Sessão #{i} precisa ser um objeto.')
        day=iso_required(raw.get('date'),'Data da sessão')
        subject=squeeze(raw.get('subject'))
        if not subject: raise HTTPException(422,f'Sessão #{i}: informe a matéria em "subject".')
        ref=squeeze(raw.get('exam_ref')) or None
        if ref and ref not in refs: raise HTTPException(422,f'Sessão #{i}: exam_ref "{ref}" não existe em exams.')
        try: minutes=int(raw.get('minutes') or 50)
        except (ValueError,TypeError): minutes=50
        if minutes<5 or minutes>720: raise HTTPException(422,f'Sessão #{i}: duração deve ser entre 5 e 720 minutos.')
        st=squeeze(raw.get('start_time'))
        if st and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',st):
            raise HTTPException(422,f'Sessão #{i}: start_time deve estar no formato HH:MM.')
        activity=squeeze(raw.get('activity_type') or 'estudo').lower()
        if activity not in valid_types: activity='outro'
        qc=raw.get('qconcursos') or {}
        if not isinstance(qc,dict): qc={}
        try: quantity=int(qc.get('quantity') or 0)
        except (ValueError,TypeError): quantity=0
        filters={
            'enabled':bool(qc.get('enabled',activity=='questoes')),
            'subject':squeeze(qc.get('subject') or subject),
            'topic':squeeze(qc.get('topic') or raw.get('topic')),
            'bank':squeeze(qc.get('bank') or qc.get('banca')),
            'institution':squeeze(qc.get('institution')),
            'year_from':qc.get('year_from'),'year_to':qc.get('year_to'),
            'difficulty':squeeze(qc.get('difficulty')),
            'mode':squeeze(qc.get('mode')),
            'quantity':max(0,min(quantity,300)),
            'filter_notes':squeeze(qc.get('filter_notes') or qc.get('notes'))
        }
        clean_schedule.append({'date':day,'start_time':st,'exam_ref':ref,'subject':subject,
          'topic':squeeze(raw.get('topic')),'minutes':minutes,'activity_type':activity,
          'objective':squeeze(raw.get('objective')),'qconcursos_filters':filters,
          'source_reference':squeeze(raw.get('source_reference'))})
        counts_by_day[day]=counts_by_day.get(day,0)+1; total_minutes+=minutes
    clean_events=[]
    allowed_event_types={'inscricao','isencao','prova','pagamento','recurso','resultado','convocacao','taf','outro'}
    for i, raw in enumerate(events,1):
        if not isinstance(raw,dict): continue
        title=squeeze(raw.get('title'))
        start=iso_required(raw.get('start_date'),'Início do prazo')
        end=iso_required(raw.get('end_date') or start,'Fim do prazo')
        if end<start: raise HTTPException(422,f'Prazo #{i}: fim anterior ao início.')
        ref=squeeze(raw.get('exam_ref')) or None
        if ref and ref not in refs: raise HTTPException(422,f'Prazo #{i}: exam_ref "{ref}" não existe em exams.')
        typ=squeeze(raw.get('type') or 'outro').lower()
        if typ not in allowed_event_types: typ='outro'
        if title: clean_events.append({'title':title,'type':typ,'start_date':start,'end_date':end,
                                       'exam_ref':ref,'notes':squeeze(raw.get('notes')),
                                       'source_reference':squeeze(raw.get('source_reference'))})
    # Datas de prova/inscrição/isenção também viram prazos, caso não estejam repetidas em events.
    for exam in out_exams:
        auto=[('prova',exam['exam_date'],exam['exam_date']),
              ('inscricao',exam['registration_start'],exam['registration_end']),
              ('isencao',exam['exemption_start'],exam['exemption_end'])]
        for typ,start,end in auto:
            if not start: continue
            title={'prova':'Prova','inscricao':'Inscrições','isencao':'Pedido de isenção'}[typ]+' — '+exam['name']+' / '+exam['cargo']
            if not any(e['type']==typ and e['start_date']==start and e['end_date']==(end or start) and e['exam_ref']==exam['ref'] for e in clean_events):
                clean_events.append({'title':title,'type':typ,'start_date':start,'end_date':end or start,
                                     'exam_ref':exam['ref'],'notes':'Data informada nos metadados do concurso.','source_reference':''})
    dates=[x['date'] for x in clean_schedule]
    title=squeeze(metadata.get('title') or metadata.get('plan_title') or 'Planejamento NotebookLM')
    plan_start=iso_required(period.get('start_date') or min(dates),'Início do planejamento')
    plan_end=iso_required(period.get('end_date') or max(dates),'Fim do planejamento')
    if plan_end<plan_start: raise HTTPException(422,'Período do planejamento inválido.')
    if any(x<plan_start or x>plan_end for x in dates): warnings.append('Há sessões fora do período geral informado; confira as datas.')
    no_topic=sum(1 for s in clean_schedule if not s['topic'])
    no_source=sum(1 for s in clean_schedule if not s['source_reference'])
    if no_topic: warnings.append(f'{no_topic} sessão(ões) sem tópico específico. Confira se a divisão do conteúdo ficou adequada.')
    if no_source: warnings.append(f'{no_source} sessão(ões) sem referência de origem/página. Isso não impede a importação, mas reduz a rastreabilidade.')
    subjects_by_ref={x['ref']:{norm(s['name']) for s in x['subjects']} for x in out_exams}
    unknown_subjects=sorted({s['subject'] for s in clean_schedule if s['exam_ref'] and norm(s['subject']) not in subjects_by_ref.get(s['exam_ref'],set())})
    if unknown_subjects:
        warnings.append('Há sessões para matérias que não aparecem no conteúdo do respectivo concurso: '+', '.join(unknown_subjects[:8])+'.')
    minutes_by_subject=defaultdict(int)
    for item in clean_schedule: minutes_by_subject[norm(item['subject'])]+=item['minutes']
    for exam in out_exams:
        weighted=sum(max(.1,float(s['weight'])) for s in exam['subjects'])
        if not weighted: continue
        for subject in exam['subjects']:
            expected=subject['weight']/weighted
            actual=minutes_by_subject.get(norm(subject['name']),0)/max(1,total_minutes)
            if expected>=.2 and actual<expected*.25:
                warnings.append(f"A matéria {subject['name']} tem peso relevante, mas recebeu pouca carga no cronograma.")
    # Confere o volume semanal com a disponibilidade cadastrada no EditalOS.
    weekly_minutes=defaultdict(int)
    for item in clean_schedule:
        monday=date.fromisoformat(item['date'])-timedelta(days=date.fromisoformat(item['date']).weekday())
        weekly_minutes[monday.isoformat()]+=item['minutes']
    with db() as conn:
        available=int(settings(conn).get('weekly_hours',20))*60
    overloaded=[(week,mins) for week,mins in weekly_minutes.items() if mins>available]
    if overloaded:
        week,mins=max(overloaded,key=lambda x:x[1])
        warnings.append(f'A semana iniciada em {week} soma {mins/60:.1f}h, acima das {available/60:.1f}h semanais configuradas. Revise antes de importar.')
    # Detecta sobreposição apenas quando o arquivo informa horários explícitos.
    by_day=defaultdict(list)
    for item in clean_schedule:
        if item['start_time']:
            hh,mm=map(int,item['start_time'].split(':'))
            start=hh*60+mm
            by_day[item['date']].append((start,start+item['minutes'],item['subject']))
    for day, blocks in by_day.items():
        blocks.sort()
        for previous,current_block in zip(blocks,blocks[1:]):
            if current_block[0]<previous[1]:
                warnings.append(f'Possível conflito de horário em {day}: {previous[2]} e {current_block[2]}.')
                break
    return {'schema':NOTEBOOKLM_SCHEMA,'title':title,'metadata':metadata,'planning_period':{'start_date':plan_start,'end_date':plan_end},
      'exams':out_exams,'schedule':clean_schedule,'events':clean_events,'warnings':warnings,
      'summary':{'exams':len(out_exams),'subjects':sum(len(e['subjects']) for e in out_exams),
                 'sessions':len(clean_schedule),'events':len(clean_events),'days':len(counts_by_day),
                 'total_minutes':total_minutes,'qconcursos_sessions':sum(1 for s in clean_schedule if s['qconcursos_filters']['enabled'])}}


def build_notebooklm_prompt(options=None):
    with db() as c:
        st=settings(c)
        current_exams=[{'name':r['name'],'institution':r['institution'],'cargo':r['cargo'],'banca':r['banca'],'exam_date':r['exam_date'],
                        'priority':r['priority'],'subjects':[s['name'] for s in c.execute('''SELECT sj.name FROM exam_subjects es
                        JOIN subjects sj ON sj.id=es.subject_id WHERE es.exam_id=?''',(r['id'],))]}
                       for r in c.execute('SELECT * FROM exams WHERE active=1 ORDER BY priority DESC, exam_date ASC')]
    weekdays=['segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado','domingo']
    chosen=PromptOptions.model_validate(options or {'weekly_hours':st.get('weekly_hours',20),'buffer_pct':st.get('buffer_pct',10),
        'study_days':st.get('study_days',[0,1,2,3,4,5]),'strategy':st.get('strategy','equilibrado'),
        'review_pct':25 if st.get('auto_review',True) else 0}).model_dump()
    selected=[weekdays[i] for i in chosen['study_days'] if isinstance(i,int) and 0<=i<=6]
    profile={'data_atual':iso(local_today()),'horas_semanais':chosen['weekly_hours'],'dias_disponiveis':selected,
             'margem_imprevistos_percentual':chosen['buffer_pct'],'estrategia':chosen['strategy'],'fuso':'America/Sao_Paulo',
             'incluir_revisoes':chosen['review_pct']>0,
             'modo_distribuicao':chosen['distribution_mode'],'sequencia':chosen['sequence_mode'],
             'materias_por_dia':chosen['subjects_per_day'],'materias_todos_os_dias':chosen['fixed_subjects'],
             'materias_prioritarias':chosen['priority_subjects'],'duracao_maxima_bloco_minutos':chosen['max_session_minutes'],
             'proporcoes':{'teoria':chosen['theory_pct'],'questoes':chosen['questions_pct'],'revisao':chosen['review_pct']},
             'incluir_simulados':chosen['include_simulados']}
    priority_text=', '.join(chosen['priority_subjects']) or 'Nenhuma preferência nominal; use peso e proximidade da prova.'
    fixed_text=', '.join(chosen['fixed_subjects']) or 'Nenhuma matéria fixa.'
    custom=chosen['custom_instructions'].strip() or 'Nenhuma instrução adicional.'
    return f'''PROMPT OFICIAL — EDITALOS / NOTEBOOKLM\n\nPAPEL\nVocê é um planejador experiente de concursos públicos brasileiros. Analise exclusivamente os editais e documentos adicionados como fontes neste NotebookLM. Produza um planejamento executável, realista, detalhado por dia, matéria e tópico. Não invente informações de edital nem datas.\n\nPERFIL DO ESTUDANTE (configuração atual do EditalOS)\n{json.dumps(profile,ensure_ascii=False,indent=2)}\n\nCONTROLES EXPLÍCITOS\n- Matérias prioritárias: {priority_text}\n- Matérias para contato diário, quando houver sessões suficientes: {fixed_text}\n- Use aproximadamente {chosen['subjects_per_day']} matéria(s) por dia.\n- Sequência {chosen['sequence_mode']}: {'termine um bloco antes de alternar.' if chosen['sequence_mode']=='sequencial' else 'intercale matérias para contato recorrente.'}\n- Proporções aproximadas: teoria {chosen['theory_pct']}%, questões {chosen['questions_pct']}%, revisão {chosen['review_pct']}%.\n- Cada bloco deve ter no máximo {chosen['max_session_minutes']} minutos, salvo simulado necessário.\n- Instruções adicionais: {custom}\n\nCONCURSOS JÁ CADASTRADOS NO EDITALOS (considere para evitar duplicação e identificar matérias comuns; não recrie concursos que não estejam nas fontes deste notebook, salvo se o usuário pedir):\n{json.dumps(current_exams,ensure_ascii=False,indent=2)}\n\nOBJETIVO\n1. Identifique cada concurso, órgão/instituição, banca, cargo, datas confirmadas e conteúdo programático. Diferencie dados expressos no edital de dados ausentes.\n2. Se houver mais de um edital/cargo, consolide as matérias comuns sem perder a vinculação dos tópicos aos concursos e cargos corretos.\n3. A data de referência de hoje é {profile['data_atual']}. Planeje a partir do próximo dia disponível, até a prova mais próxima. Se não houver data de prova confirmada, proponha um ciclo de 8 semanas e sinalize que é provisório. Use o fuso America/Sao_Paulo.\n4. Respeite o limite de {profile['horas_semanais']} horas semanais e distribua os estudos preferencialmente em: {', '.join(selected) if selected else 'dias a definir pelo usuário'}. Não crie carga incompatível com essa disponibilidade. Reserve a margem de {profile['margem_imprevistos_percentual']}% para revisão/ajustes e imprevistos.\n5. Priorize conforme proximidade da prova, peso/número de questões e conteúdo ainda não estudado, mas distribua as matérias para manter retenção e contato recorrente. Inclua teoria, leitura de lei quando pertinente, questões, revisão espaçada e simulados. {('Inclua revisões espaçadas automaticamente.' if profile['incluir_revisoes'] else 'Não acrescente revisão espaçada automática, mas mantenha as revisões obrigatórias exigidas pela sua estratégia.')}\n6. Para sessões de questões, use o QConcursos apenas como destino externo de prática: indique filtros de busca (disciplina, assunto, banca, instituição, período/ano, dificuldade e quantidade). NÃO copie questões, enunciados, alternativas, comentários ou gabaritos proprietários do QConcursos.\n7. Para cada sessão, informe data ISO (AAAA-MM-DD), horário se for relevante, duração em minutos, matéria, tópico específico, tipo de atividade e objetivo mensurável. Evite descrições genéricas como apenas “estudar Direito Administrativo”.\n8. Inclua inscrição, pedido de isenção, pagamento, prova, recursos, resultados e demais datas relevantes como eventos de calendário apenas quando comprovadas nas fontes. Para datas não encontradas, use null ou omita; nunca estime datas oficiais.\n9. Inclua referência à fonte e página para cada matéria/tópico/sessão sempre que disponível, por exemplo “Edital de abertura, p. 32”. Se a página não puder ser identificada, use string vazia.\n10. Faça uma revisão de consistência antes de entregar: datas válidas, cargas compatíveis, cada exam_ref existente, matérias realmente previstas no edital, sem sessões duplicadas na mesma faixa horária.\n\nFORMATO DE ENTREGA OBRIGATÓRIO\nDevolva UM ÚNICO ARQUIVO JSON chamado editalos_plano.json, com o objeto abaixo. Não entregue PDF ou texto corrido como arquivo principal. O EditalOS importa JSON estruturado. Se a opção de baixar JSON não estiver disponível, mostre o JSON completo na conversa, sem comentários antes/depois, para que o usuário copie para um arquivo de texto e salve com a extensão .json. Não envolva o conteúdo em explicações.\n\nESQUEMA OBRIGATÓRIO (preserve os nomes das propriedades):\n{{\n  "schema": "editalos.notebooklm.v1",\n  "metadata": {{ "title": "Plano ...", "generated_at": "AAAA-MM-DD", "sources": [{{"name":"arquivo do edital", "reference":"páginas/fontes utilizadas"}}] }},\n  "planning_period": {{"start_date":"AAAA-MM-DD", "end_date":"AAAA-MM-DD"}},\n  "exams": [{{\n    "ref":"concurso_1", "name":"Nome do concurso", "institution":"Órgão", "banca":"Banca", "cargo":"Cargo",\n    "priority":3, "exam_date":null, "registration_start":null, "registration_end":null,\n    "exemption_start":null, "exemption_end":null,\n    "subjects":[{{"name":"Direito Constitucional", "weight":1, "questions":0, "topics":["Tema 1", "Tema 2"]}}]\n  }}],\n  "schedule": [{{\n    "date":"AAAA-MM-DD", "start_time":"08:00", "minutes":50, "exam_ref":"concurso_1",\n    "subject":"Direito Constitucional", "topic":"Direitos e garantias fundamentais",\n    "activity_type":"teoria", "objective":"Ler o tópico e produzir resumo de 5 linhas",\n    "qconcursos":{{"enabled":false,"subject":"Direito Constitucional","topic":"Direitos e garantias fundamentais",\n      "bank":"","institution":"","year_from":2020,"year_to":{profile['data_atual'][:4]},"difficulty":"média",\n      "mode":"múltipla escolha","quantity":0,"filter_notes":""}},\n    "source_reference":"Edital, p. 22"\n  }}],\n  "events": [{{"title":"Período de inscrição", "type":"inscricao", "start_date":"AAAA-MM-DD",\n    "end_date":"AAAA-MM-DD", "exam_ref":"concurso_1", "notes":"", "source_reference":"Edital, p. 1"}}]\n}}\n\nVALORES PERMITIDOS\n- priority: 1 (secundário), 2 (importante), 3 (prioritário).\n- activity_type: teoria, questoes, revisao, simulado, lei_seca, resumo, redacao ou outro.\n- events.type: inscricao, isencao, prova, pagamento, recurso, resultado, convocacao, taf ou outro.\n- Para datas oficiais não encontradas, use null. Para exam_ref use exatamente o ref do concurso correspondente.\n- Para sessões de questões, qconcursos.enabled=true e quantity deve indicar a meta de questões. Para as demais, enabled=false.\n- Não adicione chaves extras; não use comentários JSON; não use trailing commas.\n\nIMPORTANTE: o EditalOS apenas valida o arquivo e coloca os blocos no calendário. Ele não executa IA, não acessa o NotebookLM e não busca nem copia questões do QConcursos.'''


@app.get('/api/notebooklm/prompt')
def notebooklm_prompt():
    return PlainTextResponse(build_notebooklm_prompt(),media_type='text/plain; charset=utf-8')

@app.post('/api/notebooklm/prompt')
def notebooklm_prompt_custom(options:PromptOptions):
    return PlainTextResponse(build_notebooklm_prompt(options.model_dump()),media_type='text/plain; charset=utf-8')


@app.get('/api/notebooklm/template')
def notebooklm_template():
    return FileResponse(STATIC/'modelo_notebooklm.json',media_type='application/json',filename='editalos_modelo_notebooklm.json')


def cleanup_previews():
    cutoff=time.monotonic()-PREVIEW_TTL_SECONDS
    for key,item in list(notebooklm_previews.items()):
        if item.get('created_monotonic',0)<cutoff:
            notebooklm_previews.pop(key,None)


def store_preview(token, item):
    with preview_lock:
        cleanup_previews()
        while len(notebooklm_previews)>=PREVIEW_MAX_ENTRIES:
            oldest=min(notebooklm_previews,key=lambda key:notebooklm_previews[key].get('created_monotonic',0))
            notebooklm_previews.pop(oldest,None)
        notebooklm_previews[token]=item


def consume_preview(token):
    with preview_lock:
        cleanup_previews()
        item=notebooklm_previews.pop(token,None)
        if not item: raise HTTPException(410,'Prévia expirada. Envie o JSON novamente.')
        return item


@app.post('/api/notebooklm/preview')
async def notebooklm_preview(file: UploadFile=File(...)):
    raw=await file.read(NOTEBOOKLM_MAX_BYTES+1)
    if len(raw)>NOTEBOOKLM_MAX_BYTES: raise HTTPException(413,'Arquivo acima de 8 MB.')
    filename=Path(file.filename or 'editalos_plano.json').name
    if Path(filename).suffix.lower() not in ('.json','.txt','.md'):
        raise HTTPException(415,'Envie JSON (.json) ou TXT/Markdown contendo somente o objeto JSON.')
    digest=hashlib.sha256(raw).hexdigest()
    with db() as c:
        old=c.execute('SELECT id,plan_title,created FROM notebooklm_imports WHERE sha256=?',(digest,)).fetchone()
    if old: raise HTTPException(409,f'Este mesmo arquivo já foi importado em {old["created"]}: {old["plan_title"]}. Gere uma nova versão ou importe outro arquivo.')
    try:
        text=raw.decode('utf-8-sig').strip()
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I)
        text=re.sub(r'\s*```$','',text)
        data=json.loads(text)
    except Exception as e:
        raise HTTPException(422,f'JSON inválido. Salve apenas o objeto JSON, sem texto fora dele. Detalhe: {str(e)[:150]}')
    plan=normalize_notebook_plan(data)
    token=uuid.uuid4().hex
    store_preview(token,{'plan':plan,'filename':filename,'sha256':digest,'created':now(),
                         'created_monotonic':time.monotonic()})
    current_sessions=[]
    with db() as c:
        current_sessions=[dict(r) for r in c.execute('SELECT day,exam_id,completed,notebooklm_import_id FROM sessions WHERE day BETWEEN ? AND ?',
            (plan['planning_period']['start_date'],plan['planning_period']['end_date']))]
        existing_exam_ids={r['id'] for exam in plan['exams'] for r in c.execute(
            "SELECT id FROM exams WHERE source='notebooklm' AND lower(name)=lower(?) AND lower(cargo)=lower(?)",
            (exam['name'],exam['cargo']))}
    current_sessions=[x for x in current_sessions if x['exam_id'] in existing_exam_ids]
    existing_pending=sum(1 for x in current_sessions if not x['completed'])
    old_import_ids={x['notebooklm_import_id'] for x in current_sessions if not x['completed'] and x['notebooklm_import_id']}
    old_events=0
    if old_import_ids:
        placeholders=','.join('?'*len(old_import_ids))
        with db() as c:
            old_events=c.execute(f'SELECT COUNT(*) FROM events WHERE notebooklm_import_id IN ({placeholders})',tuple(old_import_ids)).fetchone()[0]
    return {'token':token,'filename':filename,'sha256':digest,'title':plan['title'],
       'planning_period':plan['planning_period'],'exams':plan['exams'],'warnings':plan['warnings'],
       'summary':plan['summary'],'existing_pending_sessions':existing_pending,
       'will_delete_sessions':len([x for x in current_sessions if not x['completed'] and x['notebooklm_import_id']]),
       'will_delete_events':old_events,
       'first_session_date':min((x['date'] for x in plan['schedule']),default=plan['planning_period']['start_date']),
       'sample_sessions':plan['schedule'][:12]}


@app.post('/api/notebooklm/confirm')
def notebooklm_confirm(payload:dict):
    token=squeeze(payload.get('token'))
    mode=squeeze(payload.get('mode') or 'append')
    if mode not in ('append','replace_notebooklm'):
        raise HTTPException(422,'Modo de importação inválido.')
    pending=consume_preview(token)
    raw_preferences=payload.get('preferences') or {}
    try:
        plan=apply_import_preferences(pending['plan'],raw_preferences)
    except Exception as exc:
        raise HTTPException(422,f'Preferências de distribuição inválidas: {exc}')
    batch_id=uuid.uuid4().hex
    exam_ids={}
    with db() as c:
        # Prevent duplicates even if two previews were open concurrently.
        if c.execute('SELECT 1 FROM notebooklm_imports WHERE sha256=?',(pending['sha256'],)).fetchone():
            raise HTTPException(409,'Este arquivo já foi importado.')
        for exam in plan['exams']:
            existing=c.execute('''SELECT id FROM exams WHERE source='notebooklm' AND lower(name)=lower(?)
              AND lower(cargo)=lower(?) ORDER BY id DESC LIMIT 1''',(exam['name'],exam['cargo'])).fetchone()
            if existing:
                exam_id=existing['id']
                c.execute('UPDATE exams SET institution=?,banca=?,exam_date=?,priority=?,active=1 WHERE id=?',
                          (exam['institution'],exam['banca'],exam['exam_date'],exam['priority'],exam_id))
                c.execute('DELETE FROM exam_subjects WHERE exam_id=?',(exam_id,))
            else:
                cur=c.execute('''INSERT INTO exams(name,cargo,institution,banca,exam_date,priority,active,source,created)
                  VALUES(?,?,?,?,?,?,?, 'notebooklm',?)''',
                  (exam['name'],exam['cargo'],exam['institution'],exam['banca'],exam['exam_date'],exam['priority'],1,now()))
                exam_id=cur.lastrowid
            exam_ids[exam['ref']]=exam_id
            for subject in exam['subjects']:
                sid=imported_subject_id(c,subject['name'])
                c.execute('''INSERT INTO exam_subjects(exam_id,subject_id,weight,questions,topics)
                  VALUES(?,?,?,?,?)''',(exam_id,sid,subject['weight'],subject['questions'],json.dumps(subject['topics'],ensure_ascii=False)))
        if mode=='replace_notebooklm':
            # Substitui somente sessões pendentes que vieram do NotebookLM no período informado.
            # Sessões concluídas e sessões criadas manualmente permanecem intactas.
            exam_placeholders=','.join('?'*len(exam_ids))
            old_ids=[r['notebooklm_import_id'] for r in c.execute(f'''SELECT DISTINCT notebooklm_import_id FROM sessions
              WHERE completed=0 AND COALESCE(notebooklm_import_id,'')<>'' AND exam_id IN ({exam_placeholders})
              AND day BETWEEN ? AND ?''',
              list(exam_ids.values())+[plan['planning_period']['start_date'],plan['planning_period']['end_date']])]
            if old_ids:
                placeholders=','.join('?'*len(old_ids))
                c.execute(f'''DELETE FROM sessions WHERE completed=0 AND notebooklm_import_id IN ({placeholders})
                  AND day BETWEEN ? AND ?''',old_ids+[plan['planning_period']['start_date'],plan['planning_period']['end_date']])
                c.execute(f'DELETE FROM events WHERE notebooklm_import_id IN ({placeholders})',old_ids)
        for item in plan['schedule']:
            exam_id=exam_ids.get(item['exam_ref']) if item['exam_ref'] else None
            sid=imported_subject_id(c,item['subject'])
            if exam_id and not c.execute('SELECT 1 FROM exam_subjects WHERE exam_id=? AND subject_id=?',(exam_id,sid)).fetchone():
                c.execute('INSERT INTO exam_subjects(exam_id,subject_id,weight,questions,topics) VALUES(?,?,?,?,?)',
                  (exam_id,sid,1,0,json.dumps([item['topic']] if item['topic'] else [],ensure_ascii=False)))
            c.execute('''INSERT INTO sessions(day,subject_id,minutes,completed,created,exam_id,start_time,topic,
              activity_type,objective,qconcursos_filters,source_reference,notebooklm_import_id)
              VALUES(?,?,?,0,?,?,?,?,?,?,?,?,?)''',
              (item['date'],sid,item['minutes'],now(),exam_id,item['start_time'],item['topic'],item['activity_type'],
               item['objective'],json.dumps(item['qconcursos_filters'],ensure_ascii=False),item['source_reference'],batch_id))
        for event in plan['events']:
            exam_id=exam_ids.get(event['exam_ref']) if event['exam_ref'] else None
            title=event['title']
            already=c.execute('''SELECT id FROM events WHERE origin='notebooklm' AND title=? AND type=?
              AND start_date=? AND end_date=? LIMIT 1''',(title,event['type'],event['start_date'],event['end_date'])).fetchone()
            if not already:
                c.execute('''INSERT INTO events(exam_id,title,type,start_date,end_date,status,origin,notes,source_reference,notebooklm_import_id,created)
                  VALUES(?,?,?,?,?,'pendente','notebooklm',?,?,?,?)''',
                  (exam_id,title,event['type'],event['start_date'],event['end_date'],event['notes'],event['source_reference'],batch_id,now()))
        c.execute('''INSERT INTO notebooklm_imports(id,filename,sha256,plan_title,exam_count,session_count,event_count,period_start,period_end,plan_json,created)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
          (batch_id,pending['filename'],pending['sha256'],plan['title'],len(plan['exams']),len(plan['schedule']),
           len(plan['events']),plan['planning_period']['start_date'],plan['planning_period']['end_date'],json.dumps(plan,ensure_ascii=False),now()))
    return {'ok':True,'import_id':batch_id,'exams':len(plan['exams']),'sessions':len(plan['schedule']),
            'events':len(plan['events']),'first_session_date':min((x['date'] for x in plan['schedule']),default=plan['planning_period']['start_date']),
            'message':'Planejamento importado para o calendário.'}

@app.get('/api/notebooklm/imports/{import_id}/compare')
def compare_import(import_id:str):
    with db() as c:
        current=c.execute('SELECT * FROM notebooklm_imports WHERE id=?',(import_id,)).fetchone()
        if not current: raise HTTPException(404,'Importação não encontrada')
        previous=c.execute('SELECT * FROM notebooklm_imports WHERE created<? ORDER BY created DESC LIMIT 1',(current['created'],)).fetchone()
        if not previous: return {'current':current['id'],'previous':None,'added_sessions':current['session_count'],'removed_sessions':0,'changed_sessions':0,'added_events':current['event_count'],'removed_events':0}
        new=j(current['plan_json'],{}); old=j(previous['plan_json'],{})
        def session_key(x): return '|'.join(str(x.get(k,'')) for k in ('date','exam_ref','subject','topic','activity_type','minutes'))
        def event_key(x): return '|'.join(str(x.get(k,'')) for k in ('title','type','start_date','end_date','exam_ref'))
        ns={session_key(x) for x in new.get('schedule',[])}; os={session_key(x) for x in old.get('schedule',[])}
        ne={event_key(x) for x in new.get('events',[])}; oe={event_key(x) for x in old.get('events',[])}
        return {'current':current['id'],'previous':previous['id'],'added_sessions':len(ns-os),'removed_sessions':len(os-ns),
                'changed_sessions':abs(len(new.get('schedule',[]))-len(old.get('schedule',[]))),
                'added_events':len(ne-oe),'removed_events':len(oe-ne),
                'current_minutes':sum(int(x.get('minutes',0)) for x in new.get('schedule',[])),
                'previous_minutes':sum(int(x.get('minutes',0)) for x in old.get('schedule',[]))}

@app.get('/api/export/study.csv')
def export_study_csv():
    import csv as csv_module
    output=io.StringIO(); writer=csv_module.writer(output)
    writer.writerow(['data','materia','topico','minutos_planejados','concluida','minutos_realizados','questoes','acertos','observacoes'])
    with db() as c:
        rows=c.execute('''SELECT ss.*,s.name AS subject_name,COALESCE(SUM(sl.actual_minutes),0) AS actual_minutes,
          COALESCE(SUM(sl.questions_done),0) AS questions_done,COALESCE(SUM(sl.questions_correct),0) AS questions_correct,
          GROUP_CONCAT(sl.notes,' | ') AS notes FROM sessions ss LEFT JOIN subjects s ON s.id=ss.subject_id
          LEFT JOIN study_logs sl ON sl.session_id=ss.id GROUP BY ss.id ORDER BY ss.day,ss.id''')
        for r in rows:
            writer.writerow([r['day'],r['subject_name'],r['topic'],r['minutes'],int(r['completed']),r['actual_minutes'],r['questions_done'],r['questions_correct'],r['notes'] or ''])
    return Response(output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="editalos_estudos.csv"'})

@app.get('/api/export/backup.json')
def export_backup():
    tables=('subjects','exams','exam_subjects','events','sessions','study_logs','error_notebook','spaced_reviews',
            'settings','notebooklm_imports','topic_progress','plan_versions','proposals','questions','attempts','reviews','editals')
    with db() as c:
        payload={table:[dict(r) for r in c.execute(f'SELECT * FROM {table}')] for table in tables}
    payload['_meta']={'format':'editalos.backup.v1','created_at':now(),'database':'SQLite','data_dir':str(DATA_DIR)}
    return payload

@app.get('/api/export/backup.zip')
def export_backup_zip():
    payload=export_backup()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('editalos-backup.json',json.dumps(payload,ensure_ascii=False,indent=2))
        if UPLOAD_DIR.exists():
            for path in UPLOAD_DIR.rglob('*'):
                if path.is_file(): archive.write(path,path.relative_to(DATA_DIR).as_posix())
    buffer.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(buffer,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="editalos-backup.zip"'})

@app.get('/api/storage/status')
def storage_status():
    tables=('exams','sessions','events','study_logs','notebooklm_imports','spaced_reviews','error_notebook')
    with db() as c:
        counts={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables}
    return {'persistent':os.getenv('VERCEL')!='1',
            'ephemeral_environment':os.getenv('VERCEL')=='1',
            'data_dir':str(DATA_DIR),'database_exists':DB_PATH.exists(),'database_bytes':DB_PATH.stat().st_size if DB_PATH.exists() else 0,
            'last_saved':datetime.fromtimestamp(DB_PATH.stat().st_mtime,TZ).isoformat(timespec='seconds') if DB_PATH.exists() else None,
            'counts':counts}

@app.post('/api/import/backup.json')
async def import_backup(file:UploadFile=File(...)):
    raw=await file.read(25*1024*1024)
    upload_entries=[]
    if Path(file.filename or '').suffix.lower()=='.zip':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                raw=archive.read('editalos-backup.json')
                for name in archive.namelist():
                    if name.startswith('data/uploads/') and not name.endswith('/'):
                        relative=Path(name).relative_to('data/uploads')
                        if '..' in relative.parts: raise ValueError('caminho de upload inválido')
                        upload_entries.append((relative,archive.read(name)))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise HTTPException(422,f'Backup ZIP inválido: {str(exc)[:160]}')
    try:
        payload=json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422,f'Backup inválido: {str(exc)[:160]}')
    if payload.get('_meta',{}).get('format')!='editalos.backup.v1':
        raise HTTPException(422,'Formato de backup incompatível.')
    tables=('subjects','exams','exam_subjects','events','sessions','study_logs','error_notebook','spaced_reviews',
            'settings','notebooklm_imports','topic_progress','plan_versions','proposals','questions','attempts','reviews','editals')
    with db() as c:
        c.execute('PRAGMA foreign_keys=OFF')
        for table in reversed(tables): c.execute(f'DELETE FROM {table}')
        for table in tables:
            rows=payload.get(table,[])
            if not isinstance(rows,list): raise HTTPException(422,f'Tabela inválida no backup: {table}')
            columns={row['name'] for row in c.execute(f'PRAGMA table_info({table})')}
            for row in rows:
                if not isinstance(row,dict): raise HTTPException(422,f'Registro inválido na tabela {table}')
                values={key:value for key,value in row.items() if key in columns}
                if not values: continue
                keys=','.join(values); marks=','.join('?' for _ in values)
                c.execute(f'INSERT INTO {table} ({keys}) VALUES ({marks})',tuple(values.values()))
        c.execute('PRAGMA foreign_keys=ON')
    if upload_entries:
        for path in UPLOAD_DIR.rglob('*'):
            if path.is_file(): path.unlink()
        for relative,content in upload_entries:
            destination=UPLOAD_DIR/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(content)
    return {'ok':True,'message':'Backup restaurado. A aplicação voltou a usar os dados salvos no arquivo.'}


@app.get('/api/editals/{edital_id}/pdf')
def download_edital(edital_id:int):
    # Compatibilidade com PDFs guardados por versões antigas; novos editais são enviados ao NotebookLM.
    with db() as c:
        r=c.execute('SELECT * FROM editals WHERE id=?',(edital_id,)).fetchone()
        if not r:raise HTTPException(404)
        path=Path(r['path'])
        if not path.exists():raise HTTPException(404)
        return FileResponse(path,media_type='application/pdf',filename=r['filename'])


@app.get('/api/calendar/export.ics')
def export_ics():
    from fastapi.responses import Response
    def clean(value):
        return str(value or '').replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//EditalOS//Calendario Pessoal//PT-BR','CALSCALE:GREGORIAN','METHOD:PUBLISH']
    with db() as c:
        event_rows=list(c.execute('SELECT * FROM events ORDER BY start_date'))
        session_rows=list(c.execute("SELECT ss.*, s.name AS subject_name, e.name AS exam_name FROM sessions ss LEFT JOIN subjects s ON s.id=ss.subject_id LEFT JOIN exams e ON e.id=ss.exam_id ORDER BY ss.day, ss.start_time"))
    for e in event_rows:
        detail=' · '.join(x for x in ['Prazo de concurso: '+e['type'],e['notes'] if 'notes' in e.keys() else '',e['source_reference'] if 'source_reference' in e.keys() else ''] if x)
        start_dt=date.fromisoformat(e['start_date']);end_dt=date.fromisoformat(e['end_date'])+timedelta(days=1)
        lines.extend(['BEGIN:VEVENT',f"UID:prazo-{e['id']}@editalos.local",f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",'DTSTART;VALUE=DATE:'+start_dt.strftime('%Y%m%d'),'DTEND;VALUE=DATE:'+end_dt.strftime('%Y%m%d'),'SUMMARY:'+clean(e['title']),'DESCRIPTION:'+clean(detail),'END:VEVENT'])
    for s in session_rows:
        subject=s['subject_name'] or s['subject_id'];title='Estudar '+subject
        detail=' · '.join(x for x in [s['exam_name'] or '',s['topic'] or '',s['activity_type'] or '',f"{s['minutes']} minutos",s['objective'] or '',s['source_reference'] or ''] if x)
        lines.extend(['BEGIN:VEVENT',f"UID:sessao-{s['id']}@editalos.local",f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"])
        if s['start_time']:
            start_dt=datetime.strptime(s['day']+' '+s['start_time'],'%Y-%m-%d %H:%M');end_dt=start_dt+timedelta(minutes=s['minutes'])
            lines.extend(['DTSTART;TZID=America/Sao_Paulo:'+start_dt.strftime('%Y%m%dT%H%M%S'),'DTEND;TZID=America/Sao_Paulo:'+end_dt.strftime('%Y%m%dT%H%M%S')])
        else:
            start_dt=date.fromisoformat(s['day']);end_dt=start_dt+timedelta(days=1)
            lines.extend(['DTSTART;VALUE=DATE:'+start_dt.strftime('%Y%m%d'),'DTEND;VALUE=DATE:'+end_dt.strftime('%Y%m%d')])
        lines.extend(['SUMMARY:'+clean(title),'DESCRIPTION:'+clean(detail),'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return Response('\r\n'.join(lines)+'\r\n',media_type='text/calendar',headers={'Content-Disposition':'attachment; filename="editalos_calendario.ics"'})

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000)
