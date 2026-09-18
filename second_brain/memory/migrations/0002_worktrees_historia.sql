-- =====================================================================
-- 0002: git_worktrees con historia real (bug hallado por QA en Fase 5).
--
-- path era PRIMARY KEY, pero el directorio de worktree se REUTILIZA por
-- coordinador entre ciclos (.agent_worktrees/<owner>, spec 18): la fila
-- historica ya retirada (removed_at poblado) chocaba con el INSERT del
-- ciclo siguiente y un proyecto no podia ejecutar un segundo ciclo para
-- el mismo coordinador (sqlite3.IntegrityError en create()).
--
-- La unicidad correcta es "UN worktree ABIERTO por ruta": indice UNICO
-- PARCIAL sobre path WHERE removed_at IS NULL. La historia se acumula
-- (las filas jamas se borran, contrato de WorktreeManager); todas las
-- consultas de vcs/ y del orquestador ya filtran removed_at IS NULL.
-- =====================================================================

CREATE TABLE git_worktrees_nueva (
    path            TEXT NOT NULL,
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

INSERT INTO git_worktrees_nueva
    (path, project_id, owner, branch, task_id, base_commit,
     has_uncommitted, merged, created_at, removed_at)
SELECT path, project_id, owner, branch, task_id, base_commit,
       has_uncommitted, merged, created_at, removed_at
FROM git_worktrees;

DROP TABLE git_worktrees;
ALTER TABLE git_worktrees_nueva RENAME TO git_worktrees;

CREATE UNIQUE INDEX IF NOT EXISTS idx_worktrees_ruta_abierta
    ON git_worktrees(path) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_worktrees_open ON git_worktrees(removed_at);
