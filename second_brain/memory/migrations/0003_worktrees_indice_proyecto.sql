-- =====================================================================
-- 0003: el indice unico de worktrees abiertos incluye project_id
-- (auditoria F5, H9).
--
-- La 0002 dejo la unicidad en path a secas: dos proyectos con
-- .agent_worktrees/fable abiertos chocarian si la base fuera alguna vez
-- multi-proyecto. Hoy la base es por-vault (un solo proyecto), asi que
-- el cambio es preventivo y gratis: la clave correcta del contrato "UN
-- worktree ABIERTO por ruta y proyecto" es (project_id, path).
-- =====================================================================

DROP INDEX IF EXISTS idx_worktrees_ruta_abierta;
CREATE UNIQUE INDEX idx_worktrees_ruta_abierta
    ON git_worktrees(project_id, path) WHERE removed_at IS NULL;

-- Ademas (auditoria F5, critico F1): el checkpoint persiste el estado
-- guardado de PAUSED. Sin el, una maquina restaurada en PAUSED no tenia
-- ninguna transicion legal y el proyecto quedaba atascado para siempre.
ALTER TABLE checkpoints ADD COLUMN paused_from TEXT;
