import logging
import os
import asyncio
from io import BytesIO
from dotenv import load_dotenv
import requests
from ping3 import ping
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,  # Логи в stdout для Docker
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Загрузка переменных из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CAMERA_LOGIN = os.getenv('CAMERA_LOGIN')
CAMERA_PASSWORD = os.getenv('CAMERA_PASSWORD')
CAMERA_FILE = os.getenv('CAMERA_FILE')
AUTHORIZED_USERS = set(os.getenv('AUTHORIZED_USERS', '').split(',')) if os.getenv('AUTHORIZED_USERS') else set()

# Инициализация бота
tb = telebot.TeleBot(TELEGRAM_TOKEN)

# Шаблоны URL для разных типов камер
CAMERA_URL_TEMPLATES = {
    'hikvision': 'http://{login}:{password}@{ip}/ISAPI/Streaming/channels/101/picture',
    'dahua': 'http://{login}:{password}@{ip}/cgi-bin/snapshot.cgi',
    'axis': 'http://{login}:{password}@{ip}/axis-cgi/jpg/image.cgi?camera=1'
}

# Загрузка данных о камерах из файла
def load_cameras():
    cameras = {}
    try:
        if not os.path.exists(CAMERA_FILE):
            logging.error(f"Файл {CAMERA_FILE} не найден")
            return cameras
        with open(CAMERA_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    parts = line.strip().split(',', 3)
                    if len(parts) < 3:
                        logging.warning(f"Некорректная строка в {CAMERA_FILE}: {line.strip()}")
                        continue
                    num, ip, name = parts[:3]
                    camera_type = parts[3] if len(parts) > 3 else 'hikvision'  # По умолчанию Hikvision
                    cameras[num] = {'ip': ip, 'name': name, 'type': camera_type}
        logging.info(f"Загружено {len(cameras)} камер")
        return cameras
    except Exception as e:
        logging.error(f"Ошибка при загрузке камер: {e}")
        return cameras

CAMERAS = load_cameras()

# Проверка авторизации
def is_authorized(chat_id):
    authorized = str(chat_id) in AUTHORIZED_USERS
    if not authorized:
        logging.warning(f"Несанкционированная попытка доступа: chat_id={chat_id}")
    return authorized

# Проверка доступности камеры
def check_camera(ip):
    try:
        result = ping(ip, timeout=2)
        logging.info(f"Пинг камеры {ip}: {'успешен' if result is not None else 'неуспешен'}")
        return result is not None
    except Exception as e:
        logging.error(f"Ошибка пинга {ip}: {e}")
        return False

# Получение изображения с камеры
def get_camera_image(ip, camera_type):
    logging.info(f"Начало обработки камеры: IP={ip}, тип={camera_type}")
    print(f"DEBUG: Начало обработки камеры: IP={ip}, тип={camera_type}")
    try:
        # Если camera_type — это URL-шаблон, используем его напрямую
        if camera_type.startswith('http://') or camera_type.startswith('https://'):
            url = camera_type.format(login=CAMERA_LOGIN, password=CAMERA_PASSWORD, ip=ip)
        else:
            # Иначе используем предопределенный шаблон
            template = CAMERA_URL_TEMPLATES.get(camera_type, CAMERA_URL_TEMPLATES['hikvision'])
            url = template.format(login=CAMERA_LOGIN, password=CAMERA_PASSWORD, ip=ip)
        
        # Логируем URL (маскируем пароль для безопасности)
        log_url = url.replace(CAMERA_PASSWORD, '****') if CAMERA_PASSWORD else url
        logging.info(f"Запрос изображения с камеры: {log_url}")
        print(f"DEBUG: Запрос изображения с камеры: {log_url}")
        
        response = requests.get(url, stream=True, timeout=5)
        logging.info(f"Ответ от камеры {ip}: HTTP {response.status_code}")
        print(f"DEBUG: Ответ от камеры {ip}: HTTP {response.status_code}")
        if response.status_code == 200:
            return response.content
        logging.error(f"Ошибка загрузки изображения с {ip}: HTTP {response.status_code}")
        return None
    except requests.RequestException as e:
        logging.error(f"Ошибка соединения с {ip}: {e}")
        print(f"DEBUG: Ошибка соединения с {ip}: {e}")
        return None
    except Exception as e:
        logging.error(f"Неожиданная ошибка при обработке камеры {ip}: {e}")
        print(f"DEBUG: Неожиданная ошибка при обработке камеры {ip}: {e}")
        return None

# Обработчик команды /start
@tb.message_handler(commands=['start'])
def start_message(message):
    if not is_authorized(message.chat.id):
        tb.send_message(message.chat.id, f"Тебе сюда нельзя. Твой ID: {message.chat.id}")
        tb.send_sticker(message.chat.id, 'CAACAgIAAxkBAAEGEGVjRkZO8wK7cGg2YHscqJpqb3TKawACJAAD6dgTKJJE18Us7DO7KgQ')
        return
    user_name = message.from_user.first_name
    tb.send_message(
        message.chat.id,
        f'Привет, {user_name}! Какую камеру показать?\n'
        'Список камер: /list\n'
        'Недоступные камеры: /offline\n'
        'Текущая дата и время: /time'
    )
    tb.send_sticker(message.chat.id, 'CAACAgIAAxkBAAEGEGNjRkY1HRsxlx7cgx54ArCUG7vqawACJgAD6dgTKKrQDHZ0QgghKgQ')

# Обработчик команд для камер (/1, /2, ..., /92)
@tb.message_handler(regexp=r'^/[1-9][0-9]?$')
def camera_message(message):
    if not is_authorized(message.chat.id):
        tb.send_message(message.chat.id, 'Тебе сюда нельзя.')
        return

    camera_number = message.text[1:]
    if camera_number not in CAMERAS:
        tb.send_message(message.chat.id, f'Камера {camera_number} не найдена.')
        return

    camera = CAMERAS[camera_number]
    ip = camera['ip']
    camera_type = camera['type']
    
    try:
        logging.info(f"Запрос снимка с камеры {camera_number} ({camera['name']})")
        # Временно отключаем проверку пинга для отладки
        tb.send_message(message.chat.id, f"Фото с камеры {camera_number} ({camera['name']})")
        image_data = get_camera_image(ip, camera_type)
        if image_data:
            tb.send_photo(message.chat.id, BytesIO(image_data))
        else:
            tb.send_message(message.chat.id, "Не удалось получить изображение.")
    except telebot.apihelper.ApiException as e:
        logging.error(f"Ошибка Telegram API: {e}")
        tb.send_message(message.chat.id, "Ошибка при отправке данных.")
    except Exception as e:
        logging.error(f"Неизвестная ошибка для камеры {camera_number}: {e}")
        tb.send_message(message.chat.id, "Произошла ошибка.")

# Обработчик команды /list
@tb.message_handler(commands=['list'])
def list_cameras(message):
    if not is_authorized(message.chat.id):
        tb.send_message(message.chat.id, 'Тебе сюда нельзя.')
        return

    per_page = 10
    page = 1

    def gen_markup(page):
        markup = InlineKeyboardMarkup()
        start = (page - 1) * per_page
        end = start + per_page
        for num, cam in list(CAMERAS.items())[start:end]:
            markup.add(InlineKeyboardButton(
                f"Камера {num}: {cam['name']}",
                callback_data=f"cam_{num}"
            ))
        if start > 0:
            markup.add(InlineKeyboardButton("<< Назад", callback_data=f"page_{page-1}"))
        if end < len(CAMERAS):
            markup.add(InlineKeyboardButton("Вперед >>", callback_data=f"page_{page+1}"))
        return markup

    tb.send_message(message.chat.id, "Список камер:", reply_markup=gen_markup(page))

# Обработчик кнопок для /list
@tb.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if not is_authorized(call.message.chat.id):
        tb.answer_callback_query(call.id, "Тебе сюда нельзя.")
        return

    if call.data.startswith('page_'):
        page = int(call.data.split('_')[1])
        tb.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=gen_markup(page)
        )
    elif call.data.startswith('cam_'):
        camera_number = call.data.split('_')[1]
        if camera_number in CAMERAS:
            camera = CAMERAS[camera_number]
            ip = camera['ip']
            camera_type = camera['type']
            try:
                logging.info(f"Запрос снимка с камеры {camera_number} ({camera['name']}) через callback")
                # Временно отключаем проверку пинга для отладки
                image_data = get_camera_image(ip, camera_type)
                if image_data:
                    tb.send_photo(call.message.chat.id, BytesIO(image_data))
                else:
                    tb.send_message(call.message.chat.id, "Не удалось получить изображение.")
            except Exception as e:
                logging.error(f"Ошибка при обработке камеры {camera_number}: {e}")
                tb.send_message(call.message.chat.id, "Произошла ошибка.")
        tb.answer_callback_query(call.id)

# Обработчик команды /offline
@tb.message_handler(commands=['offline'])
def offline_cameras(message):
    if not is_authorized(message.chat.id):
        tb.send_message(message.chat.id, 'Тебе сюда нельзя.')
        return

    tb.send_message(message.chat.id, "Проверка камер, подождите...")
    tb.send_sticker(message.chat.id, 'CAACAgIAAxkBAAEGEGdjRkZocpivYQwPcl3HlQ2g2mVvNAACKAAD6dgTKKN6LQd0Ey7nKgQ')

    async def check_camera_async(ip, num):
        return num, check_camera(ip)

    async def main():
        tasks = [check_camera_async(cam['ip'], num) for num, cam in CAMERAS.items()]
        return await asyncio.gather(*tasks)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(main())
        finally:
            loop.close()

        offline = [f"/{num} {CAMERAS[num]['name']}" for num, is_online in results if not is_online]

        from datetime import datetime
        current_dt = datetime.now().strftime("%d.%m.%y %H:%M:%S")
        msg = f"Список недоступных камер на {current_dt}:\n" + (
            "\n".join(offline) if offline else "Все камеры доступны!"
        )
        tb.send_message(message.chat.id, msg)
    except Exception as e:
        logging.error(f"Ошибка при проверке камер: {e}")
        tb.send_message(message.chat.id, "Ошибка при проверке камер.")

# Обработчик команды /time
@tb.message_handler(commands=['time'])
def time_message(message):
    if not is_authorized(message.chat.id):
        tb.send_message(message.chat.id, 'Тебе сюда нельзя.')
        return

    from datetime import datetime
    current_dt = datetime.now().strftime("%d.%m.%y %H:%M:%S")
    c_date, c_time = current_dt.split()
    msg = f"Текущая дата: {c_date}\nТекущее время: {c_time}"
    tb.send_message(message.chat.id, msg)

# Запуск бота
if __name__ == '__main__':
    logging.info("Бот запущен")
    try:
        tb.polling(none_stop=True)
    except Exception as e:
        logging.critical(f"Критическая ошибка: {e}")