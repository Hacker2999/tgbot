-- Миграция для добавления поддержки мультичатовости
-- Выполните этот скрипт для обновления существующей базы данных

-- 1. Добавляем chat_id в таблицу ban_list
ALTER TABLE ban_list ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE ban_list SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE ban_list ALTER COLUMN chat_id SET NOT NULL;

-- 2. Добавляем chat_id в таблицу text
ALTER TABLE text ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE text SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE text ALTER COLUMN chat_id SET NOT NULL;

-- 3. Добавляем chat_id в таблицу anek_list
ALTER TABLE anek_list ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE anek_list SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE anek_list ALTER COLUMN chat_id SET NOT NULL;

-- 4. Добавляем chat_id в таблицу user_list
ALTER TABLE user_list ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE user_list SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE user_list ALTER COLUMN chat_id SET NOT NULL;

-- 5. Добавляем chat_id в таблицу button_list
ALTER TABLE button_list ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE button_list SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE button_list ALTER COLUMN chat_id SET NOT NULL;

-- 6. Добавляем chat_id в таблицу size_list
ALTER TABLE size_list ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE size_list SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE size_list ALTER COLUMN chat_id SET NOT NULL;

-- 7. Добавляем chat_id в таблицу credits_history
ALTER TABLE credits_history ADD COLUMN IF NOT EXISTS chat_id BIGINT;
UPDATE credits_history SET chat_id = 0 WHERE chat_id IS NULL;
ALTER TABLE credits_history ALTER COLUMN chat_id SET NOT NULL;

-- Удаляем старые уникальные ограничения (constraints), которые больше не нужны
ALTER TABLE anek_list DROP CONSTRAINT IF EXISTS anek_list_user_id_key;
ALTER TABLE user_list DROP CONSTRAINT IF EXISTS user_list_user_id_key;
ALTER TABLE size_list DROP CONSTRAINT IF EXISTS size_list_user_id_key;

-- Создаем новые составные индексы для мультичатовости
CREATE INDEX IF NOT EXISTS idx_anek_list_chat_user ON anek_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_list_chat_user ON user_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_size_list_chat_user ON size_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_size_list_chat_date ON size_list(chat_id, date);
CREATE INDEX IF NOT EXISTS idx_button_list_chat ON button_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_text_chat_target ON text(chat_id, target);
CREATE INDEX IF NOT EXISTS idx_ban_list_chat_user ON ban_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_credits_history_chat_user ON credits_history(chat_id, user_id);

-- Создаем уникальные индексы для предотвращения дублирования
CREATE UNIQUE INDEX IF NOT EXISTS idx_anek_list_chat_user_unique ON anek_list(chat_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_list_chat_user_unique ON user_list(chat_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_size_list_chat_user_date_unique ON size_list(chat_id, user_id, date);

-- Обновляем комментарии
COMMENT ON COLUMN ban_list.chat_id IS 'ID чата, где произошел бан';
COMMENT ON COLUMN text.chat_id IS 'ID чата, для которого создан текст';
COMMENT ON COLUMN anek_list.chat_id IS 'ID чата, где запрашивались анекдоты';
COMMENT ON COLUMN user_list.chat_id IS 'ID чата, где зарегистрирован пользователь';
COMMENT ON COLUMN button_list.chat_id IS 'ID чата, для которого создана кнопка';
COMMENT ON COLUMN size_list.chat_id IS 'ID чата, где измерялся размер';
COMMENT ON COLUMN credits_history.chat_id IS 'ID чата, где выдавались кредиты'; 