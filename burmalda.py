import asyncio
import random
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from peewee import fn

from model import User_listModel, CreditsHistoryModel
from utils import calculate_level, get_user_rank, award_exp_and_check_level_up

logger = logging.getLogger(__name__)

# Константы системы Burmalda
DAILY_CREDITS = 100  # Ежедневные кредиты
GAME_COST = 30  # Стоимость одной игры
GAME_ATTEMPTS = 3

# Награды за попытки (очки)
ATTEMPT_REWARDS = {
    1: 15,  # 1 выигрыш = 15 очков
    2: 35,  # 2 выигрыша = 35 очков
    3: 60   # 3 выигрыша = 60 очков
}

# Награды за победы (бонусный опыт)
VICTORY_BONUS_EXP = {
    1: 30,  # 1 победа = 30 бонусного опыта
    2: 60,  # 2 победы = 60 бонусного опыта
    3: 90   # 3 победы = 90 бонусного опыта
}

# Комиссия за обмен очков на опыт (уменьшается каждые 5 уровней)
BASE_COMMISSION = 0.20  # 20%
COMMISSION_REDUCTION_PER_5_LEVELS = 0.05  # 5%

# Стоимость снятия warn'а
WARN_REMOVAL_COST = 250

class GameType(Enum):
    ROULETTE = "roulette"
    SLOT = "slot"
    BLACKJACK = "blackjack"

@dataclass
class GameResult:
    won: bool
    message: str
    dice_value: Optional[int] = None
    condition: Optional[str] = None
    border: Optional[int] = None
    player_score: Optional[int] = None
    dealer_score: Optional[int] = None

class BurmaldaGame:
    """Класс для управления игровой системой Burmalda"""
    
    def __init__(self):
        self.active_games: Dict[int, Dict] = {}  # user_id -> game_state
        
    async def check_and_give_daily_credits(self, user_id: int) -> int:
        """
        Проверяет и выдает ежедневные кредиты пользователю.
        Возвращает количество выданных кредитов.
        """
        try:
            today = date.today()
            
            # Получаем пользователя
            q = (
                User_listModel
                .select()
                .where(User_listModel.user_id == user_id)
                .first()
            )
            
            if not q:
                # Создаем нового пользователя
                (
                    User_listModel
                    .insert({
                        User_listModel.created_at: fn.now(),
                        User_listModel.user_id: user_id,
                        User_listModel.credits: DAILY_CREDITS,
                        User_listModel.last_credits_date: today,
                        User_listModel.rank: 1
                    })
                ).execute()
                return DAILY_CREDITS
            
            # Проверяем, выдавались ли кредиты сегодня
            if q.last_credits_date != today:
                # Выдаем кредиты
                (
                    User_listModel
                    .update({
                        User_listModel.credits: User_listModel.credits + DAILY_CREDITS,
                        User_listModel.last_credits_date: today
                    })
                    .where(User_listModel.user_id == user_id)
                ).execute()
                
                # Записываем в историю
                (
                    CreditsHistoryModel
                    .insert({
                        CreditsHistoryModel.user_id: user_id,
                        CreditsHistoryModel.credits_amount: DAILY_CREDITS,
                        CreditsHistoryModel.issued_date: today
                    })
                ).execute()
                
                return DAILY_CREDITS
            else:
                return 0
                
        except Exception as e:
            logger.error(f"Ошибка при выдаче ежедневных кредитов для user_id {user_id}: {e}")
            return 0
    
    def get_user_credits(self, user_id: int) -> int:
        """Получает количество кредитов пользователя"""
        try:
            q = (
                User_listModel
                .select(User_listModel.credits)
                .where(User_listModel.user_id == user_id)
                .first()
            )
            return q.credits if q else 0
        except Exception as e:
            logger.error(f"Ошибка при получении кредитов для user_id {user_id}: {e}")
            return 0
    
    def spend_credits(self, user_id: int, amount: int) -> bool:
        """Тратит кредиты пользователя. Возвращает True если успешно"""
        try:
            q = (
                User_listModel
                .select(User_listModel.credits)
                .where(User_listModel.user_id == user_id)
                .first()
            )
            if not q or q.credits < amount:
                return False
            
            (
                User_listModel
                .update({
                    User_listModel.credits: User_listModel.credits - amount
                })
                .where(User_listModel.user_id == user_id)
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Ошибка при трате кредитов для user_id {user_id}: {e}")
            return False
    
    def add_bonus_exp(self, user_id: int, amount: int) -> bool:
        """Добавляет бонусный опыт пользователю"""
        try:
            (
                User_listModel
                .update({
                    User_listModel.bonus_exp: User_listModel.bonus_exp + amount
                })
                .where(User_listModel.user_id == user_id)
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении бонусного опыта для user_id {user_id}: {e}")
            return False
    
    def get_commission_rate(self, user_level: int) -> float:
        """Рассчитывает комиссию за обмен отвальчиков на опыт в зависимости от уровня"""
        commission = BASE_COMMISSION
        level_reductions = user_level // 5
        commission -= level_reductions * COMMISSION_REDUCTION_PER_5_LEVELS
        return max(commission, 0.05)  # Минимальная комиссия 5%
    
    async def play_roulette_game(self, user_id: int, dice_value: int = None) -> GameResult:
        """Игра в рулетку (переделанная под очки)"""
        try:
            # Бот выбирает условие
            condition = random.choice(["больше", "меньше"])
            border = random.randint(2, 5)
            
            # Используем переданное значение или генерируем случайное
            if dice_value is None:
                dice_value = random.randint(1, 6)
            
            # Проверяем результат
            won = (dice_value > border) if condition == "больше" else (dice_value < border)
            
            message = (
                f"🎲 <b>Рулетка</b>\n\n"
                f"Условие: {condition} {border}\n"
                f"Выпало: {dice_value}\n\n"
                f"{'🎉 Победа!' if won else '❌ Проигрыш'}"
            )
            
            return GameResult(
                won=won,
                message=message,
                dice_value=dice_value,
                condition=condition,
                border=border
            )
            
        except Exception as e:
            logger.error(f"Ошибка в игре рулетка для user_id {user_id}: {e}")
            return GameResult(won=False, message="❌ Ошибка в игре")
    
    async def play_slot_game(self, user_id: int, slot_value: int = None) -> GameResult:
        """Игра в слоты"""
        try:
            symbols = ["🍎", "🍊", "🍇", "🍒", "🍓", "🍉"]
            
            if slot_value is None:
                # Генерируем случайные значения
                reels = [random.choice(symbols) for _ in range(3)]
            else:
                # Используем переданное значение для первого барабана, остальные случайные
                # slot_value от 1 до 6, преобразуем в индекс 0-5
                first_symbol = symbols[slot_value - 1] if 1 <= slot_value <= 6 else random.choice(symbols)
                reels = [first_symbol] + [random.choice(symbols) for _ in range(2)]
            
            # Победа если все символы одинаковые
            won = len(set(reels)) == 1
            
            message = (
                f"🎰 <b>Слоты</b>\n\n"
                f"[{' | '.join(reels)}]\n\n"
                f"{'🎉 Джекпот!' if won else '❌ Попробуйте еще раз'}"
            )
            
            return GameResult(
                won=won,
                message=message
            )
            
        except Exception as e:
            logger.error(f"Ошибка в игре слоты для user_id {user_id}: {e}")
            return GameResult(won=False, message="❌ Ошибка в игре")
    
    async def play_blackjack_game(self, user_id: int) -> GameResult:
        """Игра в Блэкджек"""
        try:
            # Колода карт (2-10, J, Q, K, A)
            cards = list(range(2, 11)) + [10, 10, 10]  # 2-10, J, Q, K = 10
            aces = [11]  # Туз = 11 (будем корректировать при необходимости)
            
            # Раздаем карты игроку
            player_cards = [random.choice(cards), random.choice(cards)]
            if random.random() < 0.25:  # 25% шанс получить туза
                player_cards.append(random.choice(aces))
            
            # Раздаем карты дилеру
            dealer_cards = [random.choice(cards), random.choice(cards)]
            if random.random() < 0.25:  # 25% шанс получить туза
                dealer_cards.append(random.choice(aces))
            
            # Рассчитываем очки
            player_score = sum(player_cards)
            dealer_score = sum(dealer_cards)
            
            # Корректируем тузы если нужно (если больше 21, то туз = 1)
            while player_score > 21 and 11 in player_cards:
                player_cards[player_cards.index(11)] = 1
                player_score = sum(player_cards)
            
            while dealer_score > 21 and 11 in dealer_cards:
                dealer_cards[dealer_cards.index(11)] = 1
                dealer_score = sum(dealer_cards)
            
            # Определяем победителя
            won = False
            if player_score <= 21:
                if dealer_score > 21 or player_score > dealer_score:
                    won = True
            
            # Формируем сообщение
            player_cards_str = ", ".join(map(str, player_cards))
            dealer_cards_str = ", ".join(map(str, dealer_cards))
            
            message = (
                f"🃏 <b>Блэкджек</b>\n\n"
                f"Ваши карты: {player_cards_str}\n"
                f"Ваши очки: <b>{player_score}</b>\n\n"
                f"Карты дилера: {dealer_cards_str}\n"
                f"Очки дилера: <b>{dealer_score}</b>\n\n"
                f"{'🎉 Победа!' if won else '❌ Проигрыш'}"
            )
            
            return GameResult(
                won=won,
                message=message,
                player_score=player_score,
                dealer_score=dealer_score
            )
            
        except Exception as e:
            logger.error(f"Ошибка в игре Блэкджек для user_id {user_id}: {e}")
            return GameResult(won=False, message="❌ Ошибка в игре")
    
    def create_main_menu(self, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Создает главное меню Burmalda"""
        credits = self.get_user_credits(user_id)
        
        text = (
            f"🎮 <b>Burmalda - Игровая система</b>\n\n"
            f"💰 Отвальчики: <b>{credits}</b>\n"
            f"🎯 Стоимость игры: <b>{GAME_COST}</b> отвальчиков за 3 попытки\n\n"
            f"🏅 <b>Награды за победы:</b>\n"
            f"• 1 победа: {ATTEMPT_REWARDS[1]} отвальчиков\n"
            f"• 2 победы: {ATTEMPT_REWARDS[2]} отвальчиков\n"
            f"• 3 победы: {ATTEMPT_REWARDS[3]} отвальчиков\n\n"
            f"Выберите игру или действие:"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🎲 Рулетка", callback_data=f"burmalda_game_roulette_{user_id}")
        builder.button(text="🎰 Слоты", callback_data=f"burmalda_game_slot_{user_id}")
        builder.button(text="🃏 Блэкджек", callback_data=f"burmalda_game_blackjack_{user_id}")
        builder.button(text="🏪 Магазин", callback_data=f"burmalda_shop_{user_id}")
        builder.adjust(2, 1, 1)
        
        return text, builder.as_markup()
    
    def create_shop_menu(self, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Создает меню магазина"""
        credits = self.get_user_credits(user_id)
        
        q = (
            User_listModel
            .select(User_listModel.warn_count, User_listModel.rank)
            .where(User_listModel.user_id == user_id)
            .first()
        )
        
        warn_count = q.warn_count if q else 0
        level = q.rank if q else 1
        
        commission = self.get_commission_rate(level)
        exchange_rate = int(1 / commission)  # Сколько отвальчиков за 1 опыт
        
        text = (
            f"🏪 <b>Магазин Burmalda</b>\n\n"
            f"💰 Ваши отвальчики: <b>{credits}</b>\n"
            f"⚠️ Предупреждения: <b>{warn_count}</b>\n"
            f"📊 Уровень: <b>{level}</b>\n"
            f"💱 Комиссия: <b>{commission*100:.0f}%</b>\n"
            f"🔄 Курс обмена: <b>{exchange_rate}</b> отвальчиков = 1 опыт\n\n"
            f"Выберите товар:"
        )
        
        builder = InlineKeyboardBuilder()
        if warn_count > 0:
            builder.button(text=f"⚠️ Снять предупреждение ({WARN_REMOVAL_COST} отвальчиков)", 
                          callback_data=f"burmalda_remove_warn_{user_id}")
        builder.button(text=f"⭐ Обменять 100 отвальчиков на опыт", 
                      callback_data=f"burmalda_exchange_exp_{user_id}")
        builder.button(text="🔙 Назад", callback_data=f"burmalda_main_{user_id}")
        builder.adjust(1)
        
        return text, builder.as_markup()
    
    def get_user_points(self, user_id: int) -> int:
        """Получает количество очков пользователя (используем отвальчики)"""
        return self.get_user_credits(user_id)
    
    def add_points(self, user_id: int, amount: int) -> bool:
        """Добавляет очки пользователю (используем отвальчики)"""
        try:
            (
                User_listModel
                .update({
                    User_listModel.credits: User_listModel.credits + amount
                })
                .where(User_listModel.user_id == user_id)
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении очков для user_id {user_id}: {e}")
            return False
    
    def spend_points(self, user_id: int, amount: int) -> bool:
        """Тратит очки пользователя (используем отвальчики). Возвращает True если успешно"""
        return self.spend_credits(user_id, amount)

# Глобальный экземпляр игровой системы
burmalda_game = BurmaldaGame() 