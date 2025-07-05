-- Полный скрипт создания базы данных для Telegram бота с поддержкой мультичатовости
-- Выполните этот скрипт для создания всей базы данных с нуля

-- Создаем базу данных (раскомментируйте если нужно создать БД)
-- CREATE DATABASE tgbot_db;

-- Подключаемся к базе данных
-- \c tgbot_db;

-- Создаем расширение для UUID (если нужно)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Таблица для списка пользователей (мультичатовая)
CREATE TABLE IF NOT EXISTS user_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    message_count BIGINT DEFAULT 0,
    is_verified BOOLEAN DEFAULT FALSE,
    level_exp BIGINT DEFAULT 0,
    bonus_exp BIGINT DEFAULT 0,
    warn_count BIGINT DEFAULT 0,
    last_visit TIMESTAMP WITH TIME ZONE,
    visit_streak BIGINT DEFAULT 0,
    rank BIGINT NOT NULL DEFAULT 1,
    -- Поля для системы Burmalda
    credits BIGINT DEFAULT 0,
    last_credits_date DATE,
    -- Уникальный индекс для комбинации чат+пользователь
    UNIQUE(chat_id, user_id)
);

-- Таблица для списка чатов
CREATE TABLE IF NOT EXISTS chat_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_id BIGINT NOT NULL UNIQUE
);

-- Таблица для анекдотов (мультичатовая)
CREATE TABLE IF NOT EXISTS anek_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    count BIGINT DEFAULT 0,
    -- Уникальный индекс для комбинации чат+пользователь
    UNIQUE(chat_id, user_id)
);

-- Таблица для размеров (мультичатовая)
CREATE TABLE IF NOT EXISTS size_list (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    size INTEGER NOT NULL,
    date DATE NOT NULL,
    -- Уникальный индекс для комбинации чат+пользователь+дата
    UNIQUE(chat_id, user_id, date)
);

-- Таблица для кнопок/ссылок (мультичатовая)
CREATE TABLE IF NOT EXISTS button_list (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    button_name TEXT NOT NULL,
    button_link TEXT NOT NULL,
    -- Уникальный индекс для комбинации чат+ссылка
    UNIQUE(chat_id, button_link)
);

-- Таблица для текстовых сообщений (мультичатовая)
CREATE TABLE IF NOT EXISTS text (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    edited_at TIMESTAMP WITH TIME ZONE,
    target TEXT NOT NULL,
    text_of TEXT NOT NULL,
    -- Уникальный индекс для комбинации чат+тип текста
    UNIQUE(chat_id, target)
);

-- Таблица для банов (мультичатовая)
CREATE TABLE IF NOT EXISTS ban_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_id BIGINT NOT NULL,
    user_id BIGINT,
    ban_start TIMESTAMP WITH TIME ZONE NOT NULL,
    ban_end TIMESTAMP WITH TIME ZONE NOT NULL,
    reason TEXT NOT NULL,
    ban_from TEXT NOT NULL
);

-- Таблица для истории кредитов (система Burmalda, мультичатовая)
CREATE TABLE IF NOT EXISTS credits_history (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    credits_amount BIGINT NOT NULL,
    issued_date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица для RP-действий (мультичатовая)
CREATE TABLE IF NOT EXISTS rp_actions (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    trigger_word TEXT NOT NULL,
    action_text TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Уникальный индекс для комбинации чат+триггер
    UNIQUE(chat_id, trigger_word)
);

-- Создаем индексы для оптимизации запросов
CREATE INDEX IF NOT EXISTS idx_user_list_chat_id ON user_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_user_list_user_id ON user_list(user_id);
CREATE INDEX IF NOT EXISTS idx_user_list_chat_user ON user_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_list_last_visit ON user_list(last_visit);
CREATE INDEX IF NOT EXISTS idx_user_list_rank ON user_list(rank);
CREATE INDEX IF NOT EXISTS idx_user_list_credits ON user_list(credits);
CREATE INDEX IF NOT EXISTS idx_user_list_last_credits_date ON user_list(last_credits_date);

CREATE INDEX IF NOT EXISTS idx_chat_list_chat_id ON chat_list(chat_id);

CREATE INDEX IF NOT EXISTS idx_anek_list_chat_id ON anek_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_anek_list_user_id ON anek_list(user_id);
CREATE INDEX IF NOT EXISTS idx_anek_list_chat_user ON anek_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_anek_list_created_at ON anek_list(created_at);

CREATE INDEX IF NOT EXISTS idx_size_list_chat_id ON size_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_size_list_user_id ON size_list(user_id);
CREATE INDEX IF NOT EXISTS idx_size_list_chat_user ON size_list(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_size_list_date ON size_list(date);

CREATE INDEX IF NOT EXISTS idx_button_list_chat_id ON button_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_button_list_name ON button_list(button_name);

CREATE INDEX IF NOT EXISTS idx_text_chat_id ON text(chat_id);
CREATE INDEX IF NOT EXISTS idx_text_target ON text(target);
CREATE INDEX IF NOT EXISTS idx_text_chat_target ON text(chat_id, target);

CREATE INDEX IF NOT EXISTS idx_ban_list_chat_id ON ban_list(chat_id);
CREATE INDEX IF NOT EXISTS idx_ban_list_user_id ON ban_list(user_id);
CREATE INDEX IF NOT EXISTS idx_ban_list_ban_start ON ban_list(ban_start);
CREATE INDEX IF NOT EXISTS idx_ban_list_ban_end ON ban_list(ban_end);

CREATE INDEX IF NOT EXISTS idx_credits_history_chat_id ON credits_history(chat_id);
CREATE INDEX IF NOT EXISTS idx_credits_history_user_id ON credits_history(user_id);
CREATE INDEX IF NOT EXISTS idx_credits_history_chat_user ON credits_history(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_credits_history_issued_date ON credits_history(issued_date);

CREATE INDEX IF NOT EXISTS idx_rp_actions_chat_id ON rp_actions(chat_id);
CREATE INDEX IF NOT EXISTS idx_rp_actions_trigger_word ON rp_actions(trigger_word);
CREATE INDEX IF NOT EXISTS idx_rp_actions_chat_trigger ON rp_actions(chat_id, trigger_word);

-- Добавляем комментарии к таблицам и полям
COMMENT ON TABLE user_list IS 'Основная таблица пользователей с информацией о статистике, уровне и игровой системе (мультичатовая)';
COMMENT ON COLUMN user_list.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN user_list.user_id IS 'ID пользователя в Telegram';
COMMENT ON COLUMN user_list.message_count IS 'Количество сообщений пользователя';
COMMENT ON COLUMN user_list.is_verified IS 'Прошел ли пользователь капчу';
COMMENT ON COLUMN user_list.level_exp IS 'Опыт для уровня';
COMMENT ON COLUMN user_list.bonus_exp IS 'Бонусный опыт';
COMMENT ON COLUMN user_list.warn_count IS 'Количество предупреждений';
COMMENT ON COLUMN user_list.last_visit IS 'Дата последнего посещения';
COMMENT ON COLUMN user_list.visit_streak IS 'Текущий винстрик посещений';
COMMENT ON COLUMN user_list.rank IS 'Текущий уровень пользователя';
COMMENT ON COLUMN user_list.credits IS 'Кредиты "отвальчики" для игр в Burmalda';
COMMENT ON COLUMN user_list.last_credits_date IS 'Дата последней выдачи ежедневных кредитов';

COMMENT ON TABLE chat_list IS 'Список чатов где работает бот';
COMMENT ON COLUMN chat_list.chat_id IS 'ID чата в Telegram';

COMMENT ON TABLE anek_list IS 'Статистика запросов анекдотов пользователями (мультичатовая)';
COMMENT ON COLUMN anek_list.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN anek_list.user_id IS 'ID пользователя';
COMMENT ON COLUMN anek_list.count IS 'Количество запрошенных анекдотов';

COMMENT ON TABLE size_list IS 'Результаты игры "размер" (мультичатовая)';
COMMENT ON COLUMN size_list.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN size_list.user_id IS 'ID пользователя';
COMMENT ON COLUMN size_list.size IS 'Размер в сантиметрах';
COMMENT ON COLUMN size_list.date IS 'Дата измерения';

COMMENT ON TABLE button_list IS 'Кнопки/ссылки для команды /links (мультичатовая)';
COMMENT ON COLUMN button_list.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN button_list.button_name IS 'Название кнопки';
COMMENT ON COLUMN button_list.button_link IS 'Ссылка кнопки';

COMMENT ON TABLE text IS 'Текстовые сообщения (правила, приветствия, прощания) (мультичатовая)';
COMMENT ON COLUMN text.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN text.target IS 'Тип текста (rules, welcome_message, bye_message)';
COMMENT ON COLUMN text.text_of IS 'Содержимое текста';

COMMENT ON TABLE ban_list IS 'История банов пользователей (мультичатовая)';
COMMENT ON COLUMN ban_list.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN ban_list.user_id IS 'ID забаненного пользователя';
COMMENT ON COLUMN ban_list.ban_start IS 'Начало бана';
COMMENT ON COLUMN ban_list.ban_end IS 'Конец бана';
COMMENT ON COLUMN ban_list.reason IS 'Причина бана';
COMMENT ON COLUMN ban_list.ban_from IS 'Кто забанил';

COMMENT ON TABLE credits_history IS 'История выдачи кредитов пользователям (мультичатовая)';
COMMENT ON COLUMN credits_history.chat_id IS 'ID чата в Telegram';
COMMENT ON COLUMN credits_history.user_id IS 'ID пользователя';
COMMENT ON COLUMN credits_history.credits_amount IS 'Количество выданных кредитов';
COMMENT ON COLUMN credits_history.issued_date IS 'Дата выдачи';

COMMENT ON TABLE rp_actions IS 'Таблица для хранения RP-действий в чатах (мультичатовая)';
COMMENT ON COLUMN rp_actions.chat_id IS 'ID чата, где создано действие';
COMMENT ON COLUMN rp_actions.trigger_word IS 'Слово-триггер для активации действия';
COMMENT ON COLUMN rp_actions.action_text IS 'Текст действия, который будет отображаться';
COMMENT ON COLUMN rp_actions.created_by IS 'ID пользователя, создавшего действие';
COMMENT ON COLUMN rp_actions.created_at IS 'Дата и время создания действия';

-- Вставляем начальные данные (глобальные настройки по умолчанию)
-- Примечание: для мультичатовости эти записи будут создаваться для каждого чата отдельно
-- Здесь создаем только базовые шаблоны
INSERT INTO text (chat_id, target, text_of) VALUES 
    (0, 'welcome_message', 'Добро пожаловать в наш чат!'),
    (0, 'bye_message', 'До свидания! Надеемся увидеть вас снова!')
ON CONFLICT (chat_id, target) DO NOTHING;

-- Создаем представления для удобства
CREATE OR REPLACE VIEW user_stats AS
SELECT 
    u.chat_id,
    u.user_id,
    u.message_count,
    u.level_exp,
    u.bonus_exp,
    u.warn_count,
    u.rank,
    u.credits,
    u.last_visit,
    u.visit_streak,
    (u.level_exp + u.bonus_exp) as total_exp
FROM user_list u;

CREATE OR REPLACE VIEW top_users AS
SELECT 
    chat_id,
    user_id,
    message_count,
    level_exp,
    bonus_exp,
    rank,
    credits,
    (level_exp + bonus_exp) as total_exp
FROM user_list
ORDER BY (level_exp + bonus_exp) DESC, message_count DESC;

CREATE OR REPLACE VIEW chat_rp_actions AS
SELECT 
    chat_id,
    trigger_word,
    action_text,
    created_by,
    created_at
FROM rp_actions
ORDER BY chat_id, trigger_word;

-- Создаем функции для работы с данными
CREATE OR REPLACE FUNCTION get_user_stats(p_chat_id BIGINT, p_user_id BIGINT)
RETURNS TABLE(
    chat_id BIGINT,
    user_id BIGINT,
    message_count BIGINT,
    level_exp BIGINT,
    bonus_exp BIGINT,
    warn_count BIGINT,
    rank BIGINT,
    credits BIGINT,
    total_exp BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.chat_id,
        u.user_id,
        u.message_count,
        u.level_exp,
        u.bonus_exp,
        u.warn_count,
        u.rank,
        u.credits,
        (u.level_exp + u.bonus_exp) as total_exp
    FROM user_list u
    WHERE u.chat_id = p_chat_id AND u.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_top_users_by_exp(p_chat_id BIGINT, limit_count INTEGER DEFAULT 10)
RETURNS TABLE(
    user_id BIGINT,
    message_count BIGINT,
    level_exp BIGINT,
    bonus_exp BIGINT,
    rank BIGINT,
    total_exp BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.user_id,
        u.message_count,
        u.level_exp,
        u.bonus_exp,
        u.rank,
        (u.level_exp + u.bonus_exp) as total_exp
    FROM user_list u
    WHERE u.chat_id = p_chat_id
    ORDER BY (u.level_exp + u.bonus_exp) DESC, u.message_count DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_top_users_by_credits(p_chat_id BIGINT, limit_count INTEGER DEFAULT 10)
RETURNS TABLE(
    user_id BIGINT,
    credits BIGINT,
    rank BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.user_id,
        u.credits,
        u.rank
    FROM user_list u
    WHERE u.chat_id = p_chat_id
    ORDER BY u.credits DESC, u.rank DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Функция для обновления общего опыта (если нужно)
CREATE OR REPLACE FUNCTION update_total_exp()
RETURNS TRIGGER AS $$
BEGIN
    -- В данном случае общий опыт вычисляется на лету
    -- Эта функция может быть использована для дополнительной логики
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггер для автоматического обновления общего опыта
CREATE TRIGGER trigger_update_total_exp
    AFTER UPDATE OF level_exp, bonus_exp ON user_list
    FOR EACH ROW
    EXECUTE FUNCTION update_total_exp();

-- Функция для получения RP-действий чата
CREATE OR REPLACE FUNCTION get_chat_rp_actions(p_chat_id BIGINT)
RETURNS TABLE(
    trigger_word TEXT,
    action_text TEXT,
    created_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ra.trigger_word,
        ra.action_text,
        ra.created_by,
        ra.created_at
    FROM rp_actions ra
    WHERE ra.chat_id = p_chat_id
    ORDER BY ra.trigger_word;
END;
$$ LANGUAGE plpgsql;

-- Функция для очистки старых данных (опционально)
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
BEGIN
    -- Удаляем записи о банах старше 1 года
    DELETE FROM ban_list 
    WHERE ban_end < NOW() - INTERVAL '1 year';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Удаляем историю кредитов старше 6 месяцев
    DELETE FROM credits_history 
    WHERE created_at < NOW() - INTERVAL '6 months';
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Создаем индексы для представлений (если нужно)
CREATE INDEX IF NOT EXISTS idx_user_stats_chat_user ON user_stats(chat_id, user_id);
CREATE INDEX IF NOT EXISTS idx_top_users_chat_id ON top_users(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_rp_actions_chat_id ON chat_rp_actions(chat_id);

-- Добавляем комментарии к функциям
COMMENT ON FUNCTION get_user_stats(BIGINT, BIGINT) IS 'Получает статистику пользователя в конкретном чате';
COMMENT ON FUNCTION get_top_users_by_exp(BIGINT, INTEGER) IS 'Получает топ пользователей по опыту в конкретном чате';
COMMENT ON FUNCTION get_top_users_by_credits(BIGINT, INTEGER) IS 'Получает топ пользователей по кредитам в конкретном чате';
COMMENT ON FUNCTION get_chat_rp_actions(BIGINT) IS 'Получает все RP-действия для конкретного чата';
COMMENT ON FUNCTION cleanup_old_data() IS 'Очищает старые данные из базы';

-- Создаем права доступа (настройте под ваши нужды)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO your_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO your_user;

-- Проверяем создание таблиц
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_schema = 'public' 
AND table_name IN ('user_list', 'chat_list', 'anek_list', 'size_list', 'button_list', 'text', 'ban_list', 'credits_history')
ORDER BY table_name, ordinal_position;

-- Выводим информацию о созданных индексах
SELECT 
    indexname,
    tablename,
    indexdef
FROM pg_indexes 
WHERE schemaname = 'public' 
AND tablename IN ('user_list', 'chat_list', 'anek_list', 'size_list', 'button_list', 'text', 'ban_list', 'credits_history')
ORDER BY tablename, indexname; 