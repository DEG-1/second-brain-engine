-- =====================================================================
-- 0001_initial.sql - Migracion inicial del esquema (spec seccion 20).
-- =====================================================================
--
-- REGLA DE REGENERABILIDAD (spec 20): todo archivo activo del vault
-- (LATEST_SNAPSHOT.json, ACTIVE_TASKS.json, ACTIVE_DECISIONS.json,
-- HANDOFF.json, SUMMARY_INDEX.json, TOKEN_USAGE.json, CHECKPOINT.json,
-- USER_RULES.md) debe poder reconstruirse SOLO con consultas sobre
-- estas tablas. Cada bloque indica que archivo alimenta.
--
-- CONVENCIONES
--   * Un proyecto = una base autocontenida: la tabla projects tiene UNA
--     sola fila (trigger de guardia mas abajo).
--   * Los alias humanos (TASK-001, DEC-014...) son unicos dentro del
--     proyecto; como la base es por proyecto, sirven de PRIMARY KEY.
--   * Timestamps: TEXT en UTC ISO-8601 con sufijo Z (spec seccion 10).
--   * Los campos que en models.py son list[...] o dict[...] se guardan
--     como TEXT con JSON serializado por database.py.
--   * Los enums se guardan por su valor en minusculas (spec 10).
--   * Todo es CREATE ... IF NOT EXISTS: la migracion es idempotente.
--
-- NOTA SOBRE aiosqlite/executescript: este archivo se aplica dentro de
-- una unica transaccion gestionada por el runner de database.py.
-- =====================================================================


-- ---------------------------------------------------------------------
-- schema_version: numero de migracion aplicado (spec seccion 20).
-- El runner la crea antes de aplicar nada; se repite aqui por si la
-- migracion se ejecuta con herramientas externas.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);


-- ---------------------------------------------------------------------
-- projects: modelo Project. UNA SOLA FILA por base (spec seccion 20).
-- path_key = os.path.normcase(ruta resuelta); deduplica en Windows.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    path       TEXT NOT NULL,
    path_key   TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

-- Guardia de "una sola fila": si alguien intenta registrar un segundo
-- proyecto en la misma base, el fallo es ruidoso (spec 16.1, "fallar
-- ruidosamente") en vez de mezclar dos repositorios en una memoria.
CREATE TRIGGER IF NOT EXISTS projects_single_row
BEFORE INSERT ON projects
WHEN (SELECT COUNT(*) FROM projects) >= 1
     AND NEW.id NOT IN (SELECT id FROM projects)
BEGIN
    SELECT RAISE(ABORT, 'la base es de un solo proyecto (spec 20)');
END;


-- ---------------------------------------------------------------------
-- objectives: modelo Objective. Raiz del trabajo.
-- Alimenta LATEST_SNAPSHOT.objective.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS objectives (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    closed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_objectives_status ON objectives(status);


-- ---------------------------------------------------------------------
-- plans: modelo Plan completo (spec seccion 10).
-- Alimenta LATEST_SNAPSHOT.plan_id y la vista de aprobacion.
-- assignments es dict[str, Coordinator] serializado como objeto JSON.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    id                       TEXT PRIMARY KEY,
    objective_id             TEXT NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    summary                  TEXT NOT NULL DEFAULT '',
    tasks                    TEXT NOT NULL DEFAULT '[]',
    assignments              TEXT NOT NULL DEFAULT '{}',
    contracts                TEXT NOT NULL DEFAULT '[]',
    risks                    TEXT NOT NULL DEFAULT '[]',
    unresolved_disagreements TEXT NOT NULL DEFAULT '[]',
    acceptance_criteria      TEXT NOT NULL DEFAULT '[]',
    status                   TEXT NOT NULL DEFAULT 'draft',
    approved_by              TEXT,
    superseded_by            TEXT REFERENCES plans(id) ON DELETE SET NULL,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_objective ON plans(objective_id, status);


-- ---------------------------------------------------------------------
-- sessions: modelo Session. Una sesion por fase (spec seccion 13).
-- provider_session_id es el identificador de la CLI para --resume; es
-- lo que la reconciliacion de la seccion 25 necesita para continuar.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    objective_id        TEXT REFERENCES objectives(id) ON DELETE SET NULL,
    coordinator         TEXT,
    phase               TEXT NOT NULL,
    provider_session_id TEXT,
    started_at          TEXT NOT NULL,
    ended_at            TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_open
    ON sessions(coordinator, ended_at, started_at);


-- ---------------------------------------------------------------------
-- agents: estado vivo de cada COORDINADOR (fable, sol).
-- Alimenta el encabezado de la UI y coordinator_sessions del checkpoint.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    coordinator        TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL,
    model              TEXT,
    state              TEXT NOT NULL DEFAULT 'offline',
    permission_mode    TEXT NOT NULL DEFAULT 'read_only',
    current_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    current_task_id    TEXT,
    worktree_path      TEXT,
    last_active_at     TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);


-- ---------------------------------------------------------------------
-- tasks: modelo Task. Alimenta ACTIVE_TASKS.json (status pending |
-- in_progress | blocked, orden priority desc + created_at asc) y
-- LATEST_SNAPSHOT.open_tasks.
-- priority_rank materializa el orden del enum Priority para que el
-- ORDER BY sea determinista sin CASE en cada consulta.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT PRIMARY KEY,
    objective_id        TEXT NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending',
    priority            TEXT NOT NULL DEFAULT 'normal',
    priority_rank       INTEGER NOT NULL DEFAULT 1,
    coordinator         TEXT,
    worker              TEXT,
    dependencies        TEXT NOT NULL DEFAULT '[]',
    allowed_paths       TEXT NOT NULL DEFAULT '[]',
    forbidden_paths     TEXT NOT NULL DEFAULT '[]',
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',
    required_tests      TEXT NOT NULL DEFAULT '[]',
    risk_level          TEXT NOT NULL DEFAULT 'medium',
    requires_approval   INTEGER NOT NULL DEFAULT 0,
    error               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- Consulta real: "tareas activas por prioridad" en cada regeneracion
-- de ACTIVE_TASKS.json y en cada turno de EXECUTING.
CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks(status, priority_rank DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_tasks_objective ON tasks(objective_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_worker ON tasks(worker);


-- ---------------------------------------------------------------------
-- decisions: modelo Decision. Alimenta ACTIVE_DECISIONS.json (solo
-- proposed | accepted) y LATEST_SNAPSHOT.recent_decisions.
-- superseded_by conserva el linaje: es justo lo que un segundo cerebro
-- debe recordar (spec seccion 10).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decisions (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    objective_id        TEXT REFERENCES objectives(id) ON DELETE SET NULL,
    topic               TEXT NOT NULL,
    decision            TEXT NOT NULL,
    reason              TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'proposed',
    superseded_by       TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    proposed_by         TEXT NOT NULL,
    accepted_by         TEXT NOT NULL DEFAULT '[]',
    source_summary      TEXT,
    source_conversation TEXT,
    source_messages     TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_objective ON decisions(objective_id, status);


-- ---------------------------------------------------------------------
-- messages: modelo Message (spec seccion 13). Conversacion archivada.
-- Los resumenes referencian estos ids para poder volver del resumen a
-- la fuente exacta.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent            TEXT NOT NULL,
    round            INTEGER NOT NULL DEFAULT 1,
    phase            TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    message          TEXT NOT NULL,
    tokens_estimated INTEGER NOT NULL DEFAULT 0
);

-- Consulta real: reconstruir la conversacion de una sesion en orden.
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);


-- ---------------------------------------------------------------------
-- summaries: modelo SummaryEntry mas el cuerpo del resumen.
-- Fuente unica de SUMMARY_INDEX.json y de LATEST_SNAPSHOT.recent_summaries.
-- content guarda el markdown para que summaries_fts pueda buscarlo sin
-- abrir los .md de summaries/ (spec seccion 11).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS summaries (
    file         TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    objective_id TEXT REFERENCES objectives(id) ON DELETE SET NULL,
    session_id   TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    phase        TEXT,
    topic        TEXT NOT NULL,
    keywords     TEXT NOT NULL DEFAULT '[]',
    decisions    TEXT NOT NULL DEFAULT '[]',
    tasks        TEXT NOT NULL DEFAULT '[]',
    content      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summaries_created ON summaries(created_at DESC);


-- ---------------------------------------------------------------------
-- events: ESQUEMA CANONICO de la seccion 24. Identico al del bus en
-- memoria: no existen dos formatos de evento.
--
-- DECISION DELIBERADA: session_id y project_id NO llevan FOREIGN KEY.
-- events es un registro de auditoria append-only alimentado por lotes
-- desde el writer; una violacion de orden de insercion (un evento con
-- session_started que llega antes del INSERT de la sesion) no puede
-- costar la perdida del lote entero. El resto del esquema si declara
-- sus claves foraneas.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_id         TEXT PRIMARY KEY,
    timestamp        TEXT NOT NULL,
    project_id       TEXT,
    session_id       TEXT,
    actor            TEXT NOT NULL,
    type             TEXT NOT NULL,
    severity         TEXT NOT NULL DEFAULT 'info',
    message          TEXT NOT NULL DEFAULT '',
    progress         REAL,
    tokens_estimated INTEGER,
    payload          TEXT NOT NULL DEFAULT '{}'
);

-- Consultas reales: timeline de la UI, "eventos posteriores a
-- last_event_id" de la reconciliacion (spec 25.5) y purga por retencion.
CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity, timestamp);


-- ---------------------------------------------------------------------
-- approvals: modelo ApprovalRequest (spec 4.5 y 10).
-- Alimenta pending_approvals del checkpoint y la cola de /approve.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approvals (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id     TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    requested_by   TEXT NOT NULL,
    action         TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    risk           TEXT NOT NULL DEFAULT 'medium',
    command        TEXT,
    affected_paths TEXT NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'pending',
    resolved_by    TEXT,
    resolved_at    TEXT,
    response_note  TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at);


-- ---------------------------------------------------------------------
-- token_usage: registro por turno (spec seccion 14).
-- Fuente unica de TOKEN_USAGE.json: los cuatro agregados (by_agent,
-- by_phase, by_objective, by_project) son GROUP BY sobre esta tabla.
--   is_estimate = 1 -> valor estimado (longitud/4); contains_estimates
--   del JSON es EXISTS(SELECT 1 ... WHERE is_estimate = 1).
--   cache_read_tokens va aparte y pondera 0.1 en el computo: no se
--   suma a total_tokens aqui, lo pondera core/budgets.py.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    objective_id      TEXT REFERENCES objectives(id) ON DELETE SET NULL,
    session_id        TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    agent             TEXT NOT NULL,
    phase             TEXT NOT NULL,
    input_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    is_estimate       INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_usage_phase ON token_usage(phase);
CREATE INDEX IF NOT EXISTS idx_token_usage_agent ON token_usage(agent);
CREATE INDEX IF NOT EXISTS idx_token_usage_objective ON token_usage(objective_id);


-- ---------------------------------------------------------------------
-- files: el MAPA REAL del repositorio (spec seccion 11). REPO_MAP.json
-- no se materializa completo: la "seccion relevante" se genera al vuelo
-- con una consulta sobre files/symbols.
-- content guarda el texto solo para archivos versionados de texto y
-- < 1 MB; los binarios llevan is_binary = 1 y content = ''.
-- Se usa el rowid implicito como content_rowid de files_fts.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS files (
    path       TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    language   TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    hash       TEXT NOT NULL DEFAULT '',
    mtime      TEXT,
    is_binary  INTEGER NOT NULL DEFAULT 0,
    imports    TEXT NOT NULL DEFAULT '[]',
    exports    TEXT NOT NULL DEFAULT '[]',
    endpoints  TEXT NOT NULL DEFAULT '[]',
    db_tables  TEXT NOT NULL DEFAULT '[]',
    models     TEXT NOT NULL DEFAULT '[]',
    tests      TEXT NOT NULL DEFAULT '[]',
    relations  TEXT NOT NULL DEFAULT '[]',
    tags       TEXT NOT NULL DEFAULT '[]',
    summary    TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_language ON files(language);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);


-- ---------------------------------------------------------------------
-- symbols: clases, funciones y metodos por archivo (spec seccion 11).
-- ON DELETE CASCADE: al borrar un archivo del indice desaparecen sus
-- simbolos en la misma transaccion.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS symbols (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path  TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE ON UPDATE CASCADE,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    signature  TEXT NOT NULL DEFAULT '',
    parent     TEXT,
    methods    TEXT NOT NULL DEFAULT '[]',
    line_start INTEGER,
    line_end   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);


-- ---------------------------------------------------------------------
-- checkpoints: modelo Checkpoint (spec 10.1 y 25).
-- La reanudacion lee EXCLUSIVAMENTE esta tabla; CHECKPOINT.json es un
-- espejo humano regenerable a partir de la fila mas reciente.
--   reason distingue los checkpoints por mensaje (solo tabla, rotan)
--   de los de cambio de fase y cierre, que ademas se copian a
--   archive/checkpoints/ (spec 25, rotacion).
--   archived_path queda NULL mientras no se archive en disco.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS checkpoints (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id           TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at           TEXT NOT NULL,
    schema_version       INTEGER NOT NULL DEFAULT 1,
    global_state         TEXT NOT NULL,
    phase                TEXT NOT NULL,
    objective_id         TEXT REFERENCES objectives(id) ON DELETE SET NULL,
    plan_id              TEXT REFERENCES plans(id) ON DELETE SET NULL,
    coordinator_sessions TEXT NOT NULL DEFAULT '{}',
    active_workers       TEXT NOT NULL DEFAULT '[]',
    open_worktrees       TEXT NOT NULL DEFAULT '[]',
    pending_approvals    TEXT NOT NULL DEFAULT '[]',
    last_event_id        TEXT,
    reason               TEXT NOT NULL DEFAULT 'message',
    archived_path        TEXT
);

-- Consulta real: "ultimo checkpoint" al arrancar, y la rotacion por
-- retention.checkpoints_keep.
CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at DESC, id DESC);


-- ---------------------------------------------------------------------
-- worker_agents: trabajadores desplegados (spec seccion 15).
-- Alimenta active_workers del checkpoint. pid se guarda para el paso 1
-- de la reconciliacion (seccion 25): ningun PID se reutiliza, todo
-- worker vivo en el checkpoint se marca failed = "huerfano tras cierre".
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_agents (
    worker_id     TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id       TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    worker_type   TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT,
    state         TEXT NOT NULL DEFAULT 'offline',
    attempt       INTEGER NOT NULL DEFAULT 1,
    pid           INTEGER,
    session_id    TEXT,
    worktree_path TEXT,
    branch        TEXT,
    error         TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_agents_state ON worker_agents(state);
CREATE INDEX IF NOT EXISTS idx_worker_agents_task ON worker_agents(task_id);


-- ---------------------------------------------------------------------
-- worker_contracts: WorkerTaskContract entregado a cada trabajador.
-- Un trabajador puede reintentarse una vez en worktree nuevo (spec 15):
-- por eso la clave natural incluye attempt.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_contracts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    worker_id              TEXT NOT NULL,
    attempt                INTEGER NOT NULL DEFAULT 1,
    worker_type            TEXT NOT NULL,
    provider               TEXT NOT NULL,
    model                  TEXT,
    objective              TEXT NOT NULL,
    context_files          TEXT NOT NULL DEFAULT '[]',
    context_summaries      TEXT NOT NULL DEFAULT '[]',
    allowed_paths          TEXT NOT NULL DEFAULT '[]',
    forbidden_paths        TEXT NOT NULL DEFAULT '[]',
    permission_mode        TEXT NOT NULL DEFAULT 'read_only',
    token_budget           INTEGER NOT NULL DEFAULT 8000,
    time_limit_seconds     INTEGER NOT NULL DEFAULT 300,
    maximum_files          INTEGER NOT NULL DEFAULT 8,
    maximum_tool_calls     INTEGER NOT NULL DEFAULT 20,
    can_spawn_agents       INTEGER NOT NULL DEFAULT 0,
    expected_output_schema TEXT NOT NULL DEFAULT '{}',
    created_at             TEXT NOT NULL,
    UNIQUE (task_id, worker_id, attempt)
);


-- ---------------------------------------------------------------------
-- worker_results: WorkerResult (spec seccion 10). findings/evidence
-- serializados; la salida CRUDA va a archive/outputs/, no aqui.
-- raw_output_path apunta a ese archivo para poder auditar sin duplicar.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    worker_id        TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL,
    error            TEXT,
    summary          TEXT NOT NULL DEFAULT '',
    findings         TEXT NOT NULL DEFAULT '[]',
    evidence         TEXT NOT NULL DEFAULT '[]',
    files_read       TEXT NOT NULL DEFAULT '[]',
    files_changed    TEXT NOT NULL DEFAULT '[]',
    tests            TEXT NOT NULL DEFAULT '[]',
    risks            TEXT NOT NULL DEFAULT '[]',
    requests         TEXT NOT NULL DEFAULT '[]',
    confidence       REAL NOT NULL DEFAULT 0.0,
    tokens_estimated INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    raw_output_path  TEXT,
    UNIQUE (task_id, worker_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_worker_results_status ON worker_results(status);


-- ---------------------------------------------------------------------
-- git_worktrees: worktrees abiertos (spec seccion 18).
-- Alimenta open_worktrees del checkpoint y el paso 3 de la
-- reconciliacion (seccion 25): worktree ausente -> warning y tareas a
-- blocked; presente con cambios sin commit -> mostrar diff.
-- owner es el coordinador (fable|sol) o el worker_id (F-H01).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS git_worktrees (
    path            TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner           TEXT NOT NULL,
    branch          TEXT NOT NULL,
    task_id         TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    base_commit     TEXT,
    has_uncommitted INTEGER NOT NULL DEFAULT 0,
    merged          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    removed_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_worktrees_open ON git_worktrees(removed_at);


-- ---------------------------------------------------------------------
-- user_rules: modelo UserRule. Fuente unica de USER_RULES.md.
-- Comparten la prioridad 1 con la instruccion actual (spec 4.3).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_rules_active ON user_rules(active, id);


-- ---------------------------------------------------------------------
-- handoffs: modelo Handoff. Fuente unica de HANDOFF.json, que agrupa
-- {"fable": ..., "sol": ...} (spec 10.1).
-- "Un registro por coordinador y fase" (spec 20): lo impone UNIQUE, y
-- database.py hace UPSERT sobre esa clave.
-- Ademas alimenta LATEST_SNAPSHOT.next_steps (in_progress +
-- suggestions_for_other), que no es un campo libre.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS handoffs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    written_by            TEXT NOT NULL,
    phase                 TEXT NOT NULL,
    session_id            TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    done                  TEXT NOT NULL DEFAULT '[]',
    in_progress           TEXT NOT NULL DEFAULT '[]',
    blocked_on            TEXT NOT NULL DEFAULT '[]',
    warnings              TEXT NOT NULL DEFAULT '[]',
    suggestions_for_other TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL,
    UNIQUE (project_id, written_by, phase)
);

CREATE INDEX IF NOT EXISTS idx_handoffs_writer ON handoffs(written_by, created_at DESC);


-- ---------------------------------------------------------------------
-- context_requests: modelo ContextRequest con estado y resolucion
-- (spec secciones 12 y 20).
-- granted_items registra QUE se entrego: sin eso no se puede auditar
-- por que un agente vio un fragmento concreto.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS context_requests (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id    TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    requested_by  TEXT NOT NULL,
    type          TEXT NOT NULL,
    topic         TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    maximum_items INTEGER NOT NULL DEFAULT 3,
    priority      TEXT NOT NULL DEFAULT 'normal',
    granted_items TEXT NOT NULL DEFAULT '[]',
    resolved_by   TEXT,
    resolved_at   TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_requests_status
    ON context_requests(status, created_at);


-- =====================================================================
-- FTS5 (spec seccion 11)
-- =====================================================================
-- tokenize='unicode61 remove_diacritics 2' fijado EXPLICITAMENTE en las
-- tres tablas: el objetivo del usuario llega en espanol con tildes y el
-- codigo indexado esta en ingles. Sin remove_diacritics 2, "sesion" no
-- encuentra "sesión" y la busqueda devuelve cero.
-- Las tres son external content sobre su tabla base (content=...), y se
-- mantienen sincronizadas por triggers, en la MISMA transaccion que el
-- INSERT/UPDATE/DELETE de la fila base (spec seccion 11).
-- =====================================================================

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    path,
    content,
    tags,
    summary,
    content='files',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS files_fts_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, path, content, tags, summary)
    VALUES (new.rowid, new.path, new.content, new.tags, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS files_fts_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, path, content, tags, summary)
    VALUES ('delete', old.rowid, old.path, old.content, old.tags, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS files_fts_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, path, content, tags, summary)
    VALUES ('delete', old.rowid, old.path, old.content, old.tags, old.summary);
    INSERT INTO files_fts(rowid, path, content, tags, summary)
    VALUES (new.rowid, new.path, new.content, new.tags, new.summary);
END;


CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
    topic,
    keywords,
    content,
    content='summaries',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS summaries_fts_ai AFTER INSERT ON summaries BEGIN
    INSERT INTO summaries_fts(rowid, topic, keywords, content)
    VALUES (new.rowid, new.topic, new.keywords, new.content);
END;

CREATE TRIGGER IF NOT EXISTS summaries_fts_ad AFTER DELETE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, topic, keywords, content)
    VALUES ('delete', old.rowid, old.topic, old.keywords, old.content);
END;

CREATE TRIGGER IF NOT EXISTS summaries_fts_au AFTER UPDATE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, topic, keywords, content)
    VALUES ('delete', old.rowid, old.topic, old.keywords, old.content);
    INSERT INTO summaries_fts(rowid, topic, keywords, content)
    VALUES (new.rowid, new.topic, new.keywords, new.content);
END;


CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message,
    content='messages',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, message) VALUES (new.rowid, new.message);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, message)
    VALUES ('delete', old.rowid, old.message);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, message)
    VALUES ('delete', old.rowid, old.message);
    INSERT INTO messages_fts(rowid, message) VALUES (new.rowid, new.message);
END;
