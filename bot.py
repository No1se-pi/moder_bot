import telebot
import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
CONFIG_FILE = 'config.json'

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# Планировщик задач
scheduler = BackgroundScheduler(timezone='Europe/Moscow')


# ==================== РАБОТА С КОНФИГУРАЦИЕЙ ====================
def load_config():
    """Загрузить конфигурацию из файла"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"chats": {}}

def get_global_admins():
    """Глобальный список админов (из config.json + .env на первый запуск)."""
    config = load_config()
    admins = config.get('admins')

    if admins is None:
        # Первый запуск: инициализируем из .env
        admins = ADMIN_IDS.copy()
        config['admins'] = admins
        save_config(config)

    return admins

def remove_topic_id(chat_id: int, topic_id: int):
    """Удалить ID ветки из конфига (только из настроек бота)."""
    config = load_config()
    chat_str = str(chat_id)

    if chat_str not in config['chats']:
        return

    topic_ids = config['chats'][chat_str].get('topic_ids', [])
    if topic_id in topic_ids:
        topic_ids.remove(topic_id)
        config['chats'][chat_str]['topic_ids'] = topic_ids
        save_config(config)


def save_global_admins(admins):
    """Сохранить глобальный список админов."""
    config = load_config()
    config['admins'] = admins
    save_config(config)


def save_config(config):
    """Сохранить конфигурацию в файл"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_chat_config(chat_id):
    """Получить конфигурацию чата"""
    config = load_config()
    return config['chats'].get(str(chat_id), {})

def add_topic_id_manual(chat_id: int, topic_id: int):
    """Ручное добавление ID ветки в конфиг."""
    config = load_config()
    chat_str = str(chat_id)
    if chat_str not in config['chats']:
        config['chats'][chat_str] = {}
    if 'topic_ids' not in config['chats'][chat_str]:
        config['chats'][chat_str]['topic_ids'] = []
    if topic_id not in config['chats'][chat_str]['topic_ids']:
        config['chats'][chat_str]['topic_ids'].append(topic_id)
        save_config(config)

def get_topic_ids(chat_id: int):
    config = load_config()
    return config['chats'].get(str(chat_id), {}).get('topic_ids', [])


def save_chat_config(chat_id, chat_config):
    """Сохранить конфигурацию чата"""
    config = load_config()
    config['chats'][str(chat_id)] = chat_config
    save_config(config)


def get_all_topic_ids(chat_id):
    """Получить список ID всех топиков для чата"""
    config = load_config()
    chat_str = str(chat_id)
    if chat_str in config['chats'] and 'topics' in config['chats'][chat_str]:
        return config['chats'][chat_str]['topics']
    return {}


def add_topic(chat_id, topic_id, topic_name):
    """Добавить топик в список"""
    config = load_config()
    chat_str = str(chat_id)
    
    if chat_str not in config['chats']:
        config['chats'][chat_str] = {}
    
    if 'topics' not in config['chats'][chat_str]:
        config['chats'][chat_str]['topics'] = {}
    
    config['chats'][chat_str]['topics'][str(topic_id)] = topic_name
    save_config(config)
    logger.info(f"Добавлен топик '{topic_name}' (ID: {topic_id}) для чата {chat_id}")


# ==================== ФУНКЦИИ УПРАВЛЕНИЯ ВЕТКАМИ ====================
def reset_all_data():
    """Полная очистка config.json (ветки, настройки, админы)."""
    data = {
        "chats": {},
        "admins": ADMIN_IDS.copy()  # сохраняем базовых админов из .env
    }
    save_config(data)


def close_forum_topics(chat_id: int):
    """Закрыть General + все вручную добавленные ветки."""
    # General
    try:
        bot.close_general_forum_topic(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при закрытии General: {e}")

    # Остальные
    for topic_id in get_topic_ids(chat_id):
        try:
            bot.close_forum_topic(chat_id, topic_id)
        except Exception as e:
            logger.error(f"Ошибка при закрытии топика {topic_id}: {e}")


def open_forum_topics(chat_id: int):
    """Открыть General + все вручную добавленные ветки."""
    try:
        bot.reopen_general_forum_topic(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при открытии General: {e}")

    for topic_id in get_topic_ids(chat_id):
        try:
            bot.reopen_forum_topic(chat_id, topic_id)
        except Exception as e:
            logger.error(f"Ошибка при открытии топика {topic_id}: {e}")


# ==================== ПЛАНИРОВЩИК ====================

def setup_schedule_for_chat(chat_id, close_time, open_time):
    """Настроить расписание для чата"""
    close_hour, close_minute = map(int, close_time.split(':'))
    open_hour, open_minute = map(int, open_time.split(':'))
    
    # Удаляем старые задачи для этого чата
    for job in scheduler.get_jobs():
        if job.id in [f'close_{chat_id}', f'open_{chat_id}']:
            job.remove()
    
    # Добавляем новые задачи
    scheduler.add_job(
        func=close_forum_topics,
        trigger=CronTrigger(hour=close_hour, minute=close_minute),
        args=[chat_id],
        id=f'close_{chat_id}',
        replace_existing=True
    )
    
    scheduler.add_job(
        func=open_forum_topics,
        trigger=CronTrigger(hour=open_hour, minute=open_minute),
        args=[chat_id],
        id=f'open_{chat_id}',
        replace_existing=True
    )
    
    logger.info(f"Расписание для чата {chat_id} настроено: закрытие {close_time}, открытие {open_time}")


def load_all_schedules():
    """Загрузить все расписания из конфига"""
    config = load_config()
    for chat_id, chat_config in config['chats'].items():
        if chat_config.get('enabled'):
            setup_schedule_for_chat(
                int(chat_id),
                chat_config['close_time'],
                chat_config['open_time']
            )


# ==================== ПРОВЕРКА ПРАВ ====================

def is_admin(user_id):
    """Проверка, является ли пользователь администратором."""
    admins = get_global_admins()
    return int(user_id) in admins



# ==================== ОБРАБОТЧИКИ СОБЫТИЙ ====================

@bot.message_handler(func=lambda message: message.forum_topic_created is not None)
def handle_topic_created(message):
    """Обработка создания новой ветки"""
    chat_id = message.chat.id
    topic_id = message.message_thread_id
    topic_name = message.forum_topic_created.name
    
    add_topic(chat_id, topic_id, topic_name)
    logger.info(f"Новая ветка создана: '{topic_name}' (ID: {topic_id}) в чате {chat_id}")


@bot.message_handler(func=lambda message: message.forum_topic_edited is not None)
def handle_topic_edited(message):
    """Обработка редактирования ветки"""
    chat_id = message.chat.id
    topic_id = message.message_thread_id
    
    if message.forum_topic_edited.name:
        topic_name = message.forum_topic_edited.name
        add_topic(chat_id, topic_id, topic_name)
        logger.info(f"Ветка отредактирована: '{topic_name}' (ID: {topic_id}) в чате {chat_id}")


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@bot.message_handler(commands=['start'])
def start_command(message):
    """Приветственное сообщение"""
    bot.reply_to(
        message,
        "👋 Привет! Я бот для управления ветками в группах.\n\n"
        "📋 Доступные команды:\n"
        "/myid - Узнать свой ID\n"
        "/help - Помощь"
    )


@bot.message_handler(commands=['myid'])
def myid_command(message):
    """Получить ID пользователя"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = message.from_user.username or "Не установлен"
    
    # Используем HTML вместо Markdown для избежания проблем с @
    response = (
        f"👤 <b>Ваша информация:</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"💬 Chat ID: <code>{chat_id}</code>\n"
        f"👨‍💻 Username: {username if username == 'Не установлен' else '@' + username}"
    )
    
    bot.reply_to(message, response, parse_mode='HTML')


@bot.message_handler(commands=['help'])
def help_command(message):
    """Справка по командам"""
    help_text = (
        "📋 <b>Доступные команды:</b>\n\n"
        "👤 <b>Для всех пользователей:</b>\n"
        "/start - Начало работы\n"
        "/myid - Узнать свой ID\n"
        "/help - Эта справка\n\n" \
        "/register_topic - Зарегистрировать текущую ветку для автозакрытия (только админы)" \
        "/addadmin - Добавить администратора\n"
        "/admins - Показать список администраторов\n"
        "/deladmin - Удалить администратора\n"
    )
    
    if is_admin(message.from_user.id):
        help_text += (
            "👑 <b>Для администраторов:</b>\n"
            "/setup - Настроить расписание закрытия веток\n"
            "/status - Текущие настройки\n"
            "/topics - Показать отслеживаемые ветки\n"
            "/disable - Отключить автозакрытие\n"
            "/closenow - Закрыть все ветки сейчас\n"
            "/opennow - Открыть все ветки сейчас\n"
            "/resetdata - Полностью очистить данные бота"
            "/del_topic - Удалить текущую ветку из автозакрытия"
        )
    
    bot.reply_to(message, help_text, parse_mode='HTML')

@bot.message_handler(commands=['addadmin'])
def add_admin_command(message):
    """Добавить нового админа (только для текущих админов)."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    text = message.text.split(maxsplit=1)
    if len(text) == 1:
        bot.reply_to(
            message,
            "Использование:\n"
            "/addadmin <user_id>\n\n"
            "user_id можно узнать командой /myid."
        )
        return

    try:
        new_admin_id = int(text[1].strip())
    except ValueError:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return

    admins = get_global_admins()
    if new_admin_id in admins:
        bot.reply_to(message, "ℹ️ Этот пользователь уже является админом.")
        return

    admins.append(new_admin_id)
    save_global_admins(admins)

    bot.reply_to(
        message,
        f"✅ Пользователь с ID <code>{new_admin_id}</code> добавлен в админы.",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['admins'])
def admins_command(message):
    """Показать список админов."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    admins = get_global_admins()
    if not admins:
        bot.reply_to(message, "ℹ️ Список админов пуст.")
        return

    lines = [f"• <code>{aid}</code>" for aid in admins]
    bot.reply_to(
        message,
        "👑 <b>Текущие админы:</b>\n\n" + "\n".join(lines),
        parse_mode='HTML'
    )

@bot.message_handler(commands=['deladmin'])
def del_admin_command(message):
    """Удалить админа (только для админов)."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    text = message.text.split(maxsplit=1)
    if len(text) == 1:
        bot.reply_to(
            message,
            "Использование:\n"
            "/deladmin <user_id>"
        )
        return

    try:
        del_id = int(text[1].strip())
    except ValueError:
        bot.reply_to(message, "❌ ID должен быть числом.")
        return

    admins = get_global_admins()
    if del_id not in admins:
        bot.reply_to(message, "ℹ️ Этот пользователь не является админом.")
        return

    # Защитимся от удаления последнего админа и самого себя (по желанию)
    if len(admins) == 1:
        bot.reply_to(message, "❌ Нельзя удалить последнего администратора.")
        return

    admins.remove(del_id)
    save_global_admins(admins)

    bot.reply_to(
        message,
        f"✅ Пользователь с ID <code>{del_id}</code> удалён из админов.",
        parse_mode='HTML'
    )


@bot.message_handler(commands=['topics'])
def topics_command(message):
    """Показать список отслеживаемых веток"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    topics = get_all_topic_ids(chat_id)
    
    if not topics:
        bot.reply_to(
            message,
            "ℹ️ Нет отслеживаемых веток.\n\n"
            "💡 Бот автоматически отслеживает ветки при их создании или редактировании.\n"
            "Создайте новую ветку, и она будет добавлена в список."
        )
    else:
        topics_list = "\n".join([f"• {name} (ID: <code>{tid}</code>)" for tid, name in topics.items()])
        bot.reply_to(
            message,
            f"📋 <b>Отслеживаемые ветки ({len(topics)}):</b>\n\n{topics_list}\n\n"
            f"ℹ️ Эти ветки будут автоматически закрываться и открываться по расписанию.",
            parse_mode='HTML'
        )

@bot.message_handler(commands=['del_topic'])
def delete_topic_command(message):
    """Удалить текущую ветку из списка автозакрытия (не удаляет тему в Telegram)."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    if message.message_thread_id is None:
        bot.reply_to(
            message,
            "Эту команду нужно вызывать *внутри ветки форума*.",
            parse_mode='Markdown'
        )
        return

    chat_id = message.chat.id
    topic_id = message.message_thread_id

    remove_topic_id(chat_id, topic_id)

    bot.reply_to(
        message,
        f"✅ Ветка удалена из настроек автозакрытия.\n"
        f"ID: `{topic_id}`",
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['register_topic'])
def register_topic(message):
    """Ручная регистрация текущей ветки."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    if message.message_thread_id is None:
        bot.reply_to(
            message,
            "Эту команду нужно вызывать внутри ветки форума."
        )
        return

    chat_id = message.chat.id
    topic_id = message.message_thread_id
    add_topic_id_manual(chat_id, topic_id)

    bot.reply_to(
        message,
        f"✅ Ветка зарегистрирована.\nID: {topic_id}\n"
        f"Теперь она будет закрываться/открываться по расписанию."
    )

@bot.message_handler(commands=['resetdata'])
def resetdata_command(message):
    """Полная очистка всех данных бота (только для админов)."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return

    text = message.text.strip()
    if text == "/resetdata":
        bot.reply_to(
            message,
            "⚠️ ВНИМАНИЕ!\n"
            "Эта команда полностью очистит все данные бота:\n"
            "• все ветки и расписания\n"
            "• динамический список админов\n\n"
            "Останутся только админы из .env.\n\n"
            "Для подтверждения отправьте:\n"
            "`/resetdata YES`",
            parse_mode='Markdown'
        )
        return

    if text != "/resetdata YES":
        bot.reply_to(
            message,
            "❌ Неверный формат подтверждения.\n"
            "Отправьте `/resetdata` для инструкции.",
            parse_mode='Markdown'
        )
        return

    reset_all_data()

    for job in scheduler.get_jobs():
        job.remove()

    bot.reply_to(
        message,
        "✅ Все данные бота очищены.\n"
        "Админы сброшены к значениям из .env, расписания удалены.",
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['setup'])
def setup_command(message):
    """Настройка расписания закрытия веток"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    
    # Проверка, что это группа с ветками
    try:
        chat = bot.get_chat(chat_id)
        if not hasattr(chat, 'is_forum') or not chat.is_forum:
            bot.reply_to(
                message,
                "❌ Эта команда работает только в группах с включёнными ветками (форумах)"
            )
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке типа чата: {e}")
        bot.reply_to(message, "❌ Не удалось проверить тип чата")
        return
    
    msg = bot.reply_to(
        message,
        "⏰ Введите время закрытия веток в формате <b>ЧЧ:ММ</b> (например, 22:00):",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_close_time_step)


def process_close_time_step(message):
    """Обработка времени закрытия"""
    try:
        close_time = message.text.strip()
        hours, minutes = map(int, close_time.split(':'))
        
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError("Неверное время")
        
        # Сохраняем во временное хранилище
        chat_id = message.chat.id
        if not hasattr(bot, 'temp_data'):
            bot.temp_data = {}
        bot.temp_data[chat_id] = {'close_time': close_time}
        
        msg = bot.reply_to(
            message,
            f"✅ Время закрытия установлено: <b>{close_time}</b>\n\n"
            f"⏰ Теперь введите время открытия веток (например, 07:00):",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_open_time_step)
        
    except (ValueError, AttributeError):
        msg = bot.reply_to(
            message,
            "❌ Неверный формат времени. Используйте <b>ЧЧ:ММ</b> (например, 22:00)",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_close_time_step)


def process_open_time_step(message):
    """Обработка времени открытия"""
    try:
        open_time = message.text.strip()
        hours, minutes = map(int, open_time.split(':'))
        
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError("Неверное время")
        
        chat_id = message.chat.id
        close_time = bot.temp_data.get(chat_id, {}).get('close_time')
        
        if not close_time:
            bot.reply_to(message, "❌ Ошибка: время закрытия не найдено. Начните заново с /setup")
            return
        
        # Сохранение конфигурации
        chat_config = get_chat_config(chat_id)
        chat_config['enabled'] = True
        chat_config['close_time'] = close_time
        chat_config['open_time'] = open_time
        save_chat_config(chat_id, chat_config)
        
        # Настройка планировщика
        setup_schedule_for_chat(chat_id, close_time, open_time)
        
        # Очистка временных данных
        if hasattr(bot, 'temp_data') and chat_id in bot.temp_data:
            del bot.temp_data[chat_id]
        
        topic_count = len(get_all_topic_ids(chat_id))
        
        bot.reply_to(
            message,
            f"✅ <b>Настройка завершена!</b>\n\n"
            f"🕐 Ветки будут закрываться: <code>{close_time}</code>\n"
            f"🕐 Ветки будут открываться: <code>{open_time}</code>\n"
            f"🌍 Часовой пояс: <code>Europe/Moscow</code>\n"
            f"📋 Отслеживается веток: <b>{topic_count}</b>\n\n"
            f"💡 Бот будет автоматически добавлять новые ветки при их создании.",
            parse_mode='HTML'
        )
        
    except (ValueError, AttributeError):
        msg = bot.reply_to(
            message,
            "❌ Неверный формат времени. Используйте <b>ЧЧ:ММ</b> (например, 07:00)",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_open_time_step)


@bot.message_handler(commands=['status'])
def status_command(message):
    """Показать текущие настройки"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    chat_config = get_chat_config(chat_id)
    
    if not chat_config:
        bot.reply_to(
            message,
            "⚠️ Расписание не настроено. Используйте /setup"
        )
        return
    
    topic_count = len(get_all_topic_ids(chat_id))
    
    status_text = (
        f"📊 <b>Текущие настройки:</b>\n\n"
        f"🔄 Статус: {'✅ Включено' if chat_config.get('enabled') else '❌ Выключено'}\n"
        f"🕐 Закрытие веток: <code>{chat_config.get('close_time', 'не установлено')}</code>\n"
        f"🕐 Открытие веток: <code>{chat_config.get('open_time', 'не установлено')}</code>\n"
        f"🌍 Часовой пояс: <code>Europe/Moscow</code>\n"
        f"📋 Отслеживается веток: <b>{topic_count}</b>"
    )
    
    bot.reply_to(message, status_text, parse_mode='HTML')


@bot.message_handler(commands=['disable'])
def disable_command(message):
    """Отключить автоматическое закрытие веток"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    chat_config = get_chat_config(chat_id)
    
    if chat_config:
        chat_config['enabled'] = False
        save_chat_config(chat_id, chat_config)
        
        # Удаление задач из планировщика
        for job in scheduler.get_jobs():
            if job.id in [f'close_{chat_id}', f'open_{chat_id}']:
                job.remove()
        
        bot.reply_to(message, "✅ Автоматическое закрытие веток отключено")
    else:
        bot.reply_to(message, "⚠️ Расписание не было настроено")


@bot.message_handler(commands=['closenow'])
def close_now_command(message):
    """Закрыть все ветки немедленно"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    try:
        close_forum_topics(chat_id)
        topic_count = len(get_all_topic_ids(chat_id))
        bot.reply_to(message, f"✅ Закрыто веток: {topic_count + 1} (включая главную)")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")


@bot.message_handler(commands=['opennow'])
def open_now_command(message):
    """Открыть все ветки немедленно"""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав администратора")
        return
    
    chat_id = message.chat.id
    try:
        open_forum_topics(chat_id)
        topic_count = len(get_all_topic_ids(chat_id))
        bot.reply_to(message, f"✅ Открыто веток: {topic_count + 1} (включая главную)")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")


# ==================== ЗАПУСК БОТА ====================

def main():
    """Главная функция запуска бота"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен в .env файле")
        return
    
    if not ADMIN_IDS:
        logger.error("ADMIN_IDS не установлен в .env файле")
        return
    
    logger.info("Запуск бота...")
    
    # Запуск планировщика
    scheduler.start()
    
    # Загрузка всех сохранённых расписаний
    load_all_schedules()
    
    logger.info("Бот готов к работе!")
    
    # Запуск бота
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except KeyboardInterrupt:
        logger.info("Остановка бота...")
        scheduler.shutdown()


if __name__ == '__main__':
    main()
