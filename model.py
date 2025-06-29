from peewee import *
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Конфигурация базы данных
db = PostgresqlDatabase(database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)

class BaseModel(Model):
    class Meta:
        database = db

class BanList(BaseModel):
    id = BigAutoField(primary_key=True)  # bigint, генерируется по умолчанию как identity
    created_at = TimestampField(constraints=[SQL('DEFAULT now()')])  # временная метка с часовым поясом
    user_id = BigIntegerField(null=True)  # bigint, может быть пустым
    ban_start = TimestampField(null=False)  # временная метка без часового пояса
    ban_end = TimestampField(null=False)  # временная метка без часового пояса
    reason = TextField(null=False)  # текст, не может быть пустым
    ban_from = TextField(null=False)  # текст, не может быть пустым

    class Meta:
        table_name = 'ban_list'

class TextModel(BaseModel):
    id = BigAutoField(primary_key=True)  # bigint, генерируется по умолчанию как identity
    edited_at = TimestampField(null=True)  # временная метка без часового пояса, может быть пустой
    target = TextField(null=False)  # текст, не может быть пустым
    text_of = TextField(null=False)  # текст, не может быть пустым

    class Meta:
        table_name = 'text'

class AnekModel(BaseModel):
    id = BigAutoField(primary_key=True)
    created_at = TimestampField(constraints=[SQL('DEFAULT now()')])
    user_id = BigIntegerField(null=False,unique=True)
    count = BigIntegerField(default=0)

    class Meta:
        table_name = 'anek_list'

class User_listModel(BaseModel):
    id = BigAutoField(primary_key=True)
    created_at = TimestampField(constraints=[SQL('DEFAULT now()')])
    user_id = BigIntegerField(null=False,unique=True)
    message_count = BigIntegerField(default=0)
    is_verified = BooleanField(default=False)  # Прошел ли пользователь капчу
    level_exp = BigIntegerField(default=0)
    bonus_exp = BigIntegerField(default=0)
    warn_count = BigIntegerField(default=0)  # Количество предупреждений
    last_visit = TimestampField(null=True)  # Дата последнего посещения
    visit_streak = BigIntegerField(default=0)  # Текущий винстрик посещений
    rank = BigIntegerField(null=False,default=1)  # Текущий уровень
    # Новые поля для системы Burmalda
    credits = BigIntegerField(default=0)  # Кредиты "отвальчики"
    last_credits_date = DateField(null=True)  # Дата последней выдачи кредитов

    class Meta:
        table_name = 'user_list'

class Chat_listModel(BaseModel):
    id = BigAutoField(primary_key=True)
    created_at = TimestampField(constraints=[SQL('DEFAULT now()')])
    chat_id = BigIntegerField(null=False,unique=True)

    class Meta:
        table_name = 'chat_list'

class Button_listModel(BaseModel):
    id = BigAutoField(primary_key=True)  # bigint, генерируется по умолчанию как identity
    button_name = TextField(null=False)  # текст, не может быть пустым
    button_link = TextField(null=False)  # текст, не может быть пустым

    class Meta:
        table_name = 'button_list'

class SizeModel(BaseModel):
    id = BigAutoField(primary_key=True)
    user_id = BigIntegerField(null=False, unique=True)
    size = IntegerField(null=False)
    date = DateField(null=False)  # Дата, когда был установлен размер

    class Meta:
        table_name = 'size_list'

class CreditsHistoryModel(BaseModel):
    """История выдачи кредитов для отслеживания ежедневных начислений"""
    id = BigAutoField(primary_key=True)
    user_id = BigIntegerField(null=False)
    credits_amount = BigIntegerField(null=False)  # Количество выданных кредитов
    issued_date = DateField(null=False)  # Дата выдачи
    created_at = TimestampField(null=True)  # Убираем DEFAULT now()

    class Meta:
        table_name = 'credits_history'