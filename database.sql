-- Полный скрипт создания базы данных для Telegram бота
-- Выполните этот скрипт для создания всей базы данных с нуля

-- Создаем базу данных (раскомментируйте если нужно создать БД)
-- CREATE DATABASE tgbot_db;

-- Подключаемся к базе данных
-- \c tgbot_db;

-- Создаем расширение для UUID (если нужно)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Таблица для списка пользователей
CREATE TABLE IF NOT EXISTS user_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id BIGINT NOT NULL UNIQUE,
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
    last_credits_date DATE
);

-- Таблица для списка чатов
CREATE TABLE IF NOT EXISTS chat_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chat_id BIGINT NOT NULL UNIQUE
);

-- Таблица для анекдотов
CREATE TABLE IF NOT EXISTS anek_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id BIGINT NOT NULL UNIQUE,
    count BIGINT DEFAULT 0
);

-- Таблица для размеров
CREATE TABLE IF NOT EXISTS size_list (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    date DATE NOT NULL
);

-- Таблица для кнопок/ссылок
CREATE TABLE IF NOT EXISTS button_list (
    id BIGSERIAL PRIMARY KEY,
    button_name TEXT NOT NULL,
    button_link TEXT NOT NULL
);

-- Таблица для текстовых сообщений
CREATE TABLE IF NOT EXISTS text (
    id BIGSERIAL PRIMARY KEY,
    edited_at TIMESTAMP WITH TIME ZONE,
    target TEXT NOT NULL,
    text_of TEXT NOT NULL
);

-- Таблица для банов
CREATE TABLE IF NOT EXISTS ban_list (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id BIGINT,
    ban_start TIMESTAMP WITH TIME ZONE NOT NULL,
    ban_end TIMESTAMP WITH TIME ZONE NOT NULL,
    reason TEXT NOT NULL,
    ban_from TEXT NOT NULL
);

-- Таблица для истории кредитов (система Burmalda)
CREATE TABLE IF NOT EXISTS credits_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    credits_amount BIGINT NOT NULL,
    issued_date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Таблица для RP-действий
CREATE TABLE IF NOT EXISTS rp_actions (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    trigger_word TEXT NOT NULL,
    action_text TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Создаем индексы для оптимизации запросов
CREATE INDEX IF NOT EXISTS idx_user_list_user_id ON user_list(user_id);
CREATE INDEX IF NOT EXISTS idx_user_list_last_visit ON user_list(last_visit);
CREATE INDEX IF NOT EXISTS idx_user_list_rank ON user_list(rank);
CREATE INDEX IF NOT EXISTS idx_user_list_credits ON user_list(credits);
CREATE INDEX IF NOT EXISTS idx_user_list_last_credits_date ON user_list(last_credits_date);

CREATE INDEX IF NOT EXISTS idx_chat_list_chat_id ON chat_list(chat_id);

CREATE INDEX IF NOT EXISTS idx_anek_list_user_id ON anek_list(user_id);
CREATE INDEX IF NOT EXISTS idx_anek_list_created_at ON anek_list(created_at);

CREATE INDEX IF NOT EXISTS idx_size_list_user_id ON size_list(user_id);
CREATE INDEX IF NOT EXISTS idx_size_list_date ON size_list(date);

CREATE INDEX IF NOT EXISTS idx_button_list_name ON button_list(button_name);

CREATE INDEX IF NOT EXISTS idx_text_target ON text(target);

CREATE INDEX IF NOT EXISTS idx_ban_list_user_id ON ban_list(user_id);
CREATE INDEX IF NOT EXISTS idx_ban_list_ban_start ON ban_list(ban_start);
CREATE INDEX IF NOT EXISTS idx_ban_list_ban_end ON ban_list(ban_end);

CREATE INDEX IF NOT EXISTS idx_credits_history_user_id ON credits_history(user_id);
CREATE INDEX IF NOT EXISTS idx_credits_history_issued_date ON credits_history(issued_date);

CREATE INDEX IF NOT EXISTS idx_rp_actions_chat_id ON rp_actions(chat_id);
CREATE INDEX IF NOT EXISTS idx_rp_actions_trigger_word ON rp_actions(trigger_word);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rp_actions_chat_trigger ON rp_actions(chat_id, trigger_word);

-- Добавляем комментарии к таблицам и полям
COMMENT ON TABLE user_list IS 'Основная таблица пользователей с информацией о статистике, уровне и игровой системе';
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

COMMENT ON TABLE anek_list IS 'Статистика запросов анекдотов пользователями';
COMMENT ON COLUMN anek_list.user_id IS 'ID пользователя';
COMMENT ON COLUMN anek_list.count IS 'Количество запрошенных анекдотов';

COMMENT ON TABLE size_list IS 'Результаты игры "размер"';
COMMENT ON COLUMN size_list.user_id IS 'ID пользователя';
COMMENT ON COLUMN size_list.size IS 'Размер в сантиметрах';
COMMENT ON COLUMN size_list.date IS 'Дата измерения';

COMMENT ON TABLE button_list IS 'Кнопки/ссылки для команды /links';
COMMENT ON COLUMN button_list.button_name IS 'Название кнопки';
COMMENT ON COLUMN button_list.button_link IS 'Ссылка кнопки';

COMMENT ON TABLE text IS 'Текстовые сообщения (правила, приветствия, прощания)';
COMMENT ON COLUMN text.target IS 'Тип текста (rules, welcome_message, bye_message)';
COMMENT ON COLUMN text.text_of IS 'Содержимое текста';

COMMENT ON TABLE ban_list IS 'История банов пользователей';
COMMENT ON COLUMN ban_list.user_id IS 'ID забаненного пользователя';
COMMENT ON COLUMN ban_list.ban_start IS 'Начало бана';
COMMENT ON COLUMN ban_list.ban_end IS 'Конец бана';
COMMENT ON COLUMN ban_list.reason IS 'Причина бана';
COMMENT ON COLUMN ban_list.ban_from IS 'Кто забанил';

COMMENT ON TABLE credits_history IS 'История выдачи кредитов пользователям';
COMMENT ON COLUMN credits_history.user_id IS 'ID пользователя';
COMMENT ON COLUMN credits_history.credits_amount IS 'Количество выданных кредитов';
COMMENT ON COLUMN credits_history.issued_date IS 'Дата выдачи';

COMMENT ON TABLE rp_actions IS 'Таблица для хранения RP-действий в чатах';
COMMENT ON COLUMN rp_actions.chat_id IS 'ID чата, где создано действие';
COMMENT ON COLUMN rp_actions.trigger_word IS 'Слово-триггер для активации действия';
COMMENT ON COLUMN rp_actions.action_text IS 'Текст действия, который будет отображаться';
COMMENT ON COLUMN rp_actions.created_by IS 'ID пользователя, создавшего действие';
COMMENT ON COLUMN rp_actions.created_at IS 'Дата и время создания действия';

-- Вставляем начальные данные
INSERT INTO text (target, text_of) VALUES 
    ('welcome_message', 'Добро пожаловать в наш чат!'),
    ('bye_message', 'До свидания! Надеемся увидеть вас снова!')
ON CONFLICT (target) DO NOTHING;

-- Создаем представления для удобства
CREATE OR REPLACE VIEW user_stats AS
SELECT 
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
    user_id,
    message_count,
    rank,
    total_exp
FROM user_stats
ORDER BY total_exp DESC, message_count DESC;

CREATE OR REPLACE VIEW chat_rp_actions AS
SELECT 
    chat_id,
    trigger_word,
    action_text,
    created_by,
    created_at
FROM rp_actions
ORDER BY chat_id, trigger_word;

-- Создаем функции для удобства

-- Функция для получения статистики пользователя
CREATE OR REPLACE FUNCTION get_user_stats(p_user_id BIGINT)
RETURNS TABLE(
    user_id BIGINT,
    message_count BIGINT,
    level_exp BIGINT,
    bonus_exp BIGINT,
    total_exp BIGINT,
    rank BIGINT,
    credits BIGINT,
    warn_count BIGINT,
    last_visit TIMESTAMP WITH TIME ZONE,
    visit_streak BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.user_id,
        u.message_count,
        u.level_exp,
        u.bonus_exp,
        (u.level_exp + u.bonus_exp) as total_exp,
        u.rank,
        u.credits,
        u.warn_count,
        u.last_visit,
        u.visit_streak
    FROM user_list u
    WHERE u.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

-- Функция для получения топ игроков по опыту
CREATE OR REPLACE FUNCTION get_top_users_by_exp(limit_count INTEGER DEFAULT 10)
RETURNS TABLE(
    user_id BIGINT,
    total_exp BIGINT,
    rank BIGINT,
    message_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.user_id,
        (u.level_exp + u.bonus_exp) as total_exp,
        u.rank,
        u.message_count
    FROM user_list u
    ORDER BY (u.level_exp + u.bonus_exp) DESC, u.message_count DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Функция для получения топ игроков по кредитам
CREATE OR REPLACE FUNCTION get_top_users_by_credits(limit_count INTEGER DEFAULT 10)
RETURNS TABLE(
    user_id BIGINT,
    credits BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.user_id,
        u.credits
    FROM user_list u
    ORDER BY u.credits DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Создаем триггеры для автоматического обновления

-- Триггер для автоматического обновления total_exp
CREATE OR REPLACE FUNCTION update_total_exp()
RETURNS TRIGGER AS $$
BEGIN
    -- Эта функция может быть расширена для дополнительной логики
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

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

-- Создаем права доступа (настройте под ваши нужды)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO your_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO your_user;

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