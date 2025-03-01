import telebot
import os
import re
import requests
import locale
import logging
import urllib.parse

from io import BytesIO
from telebot import types
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs
from utils import (
    generate_encar_photo_url,
    clean_number,
    get_customs_fees,
    calculate_age,
    format_number,
)

CALCULATE_CAR_TEXT = "Расчёт Автомобиля"
DEALER_COMMISSION = 0.02  # 2%

PROXY_URL = "http://B01vby:GBno0x@45.118.250.2:8000"
proxies = {"http": PROXY_URL, "https": PROXY_URL}


# Настройка БД
DATABASE_URL = "postgres://uea5qru3fhjlj:p44343a46d4f1882a5ba2413935c9b9f0c284e6e759a34cf9569444d16832d4fe@c97r84s7psuajm.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d9pr93olpfl9bj"


# Configure logging
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Load keys from .env file
load_dotenv()
bot_token = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(bot_token)

# Set locale for number formatting
locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

# Storage for the last error message ID
last_error_message_id = {}

# global variables
car_data = {}
car_id_external = ""
total_car_price = 0
krw_rub_rate = 0
rub_to_krw_rate = 0
usd_rate = 0
users = set()

admins = []
CHANNEL_USERNAME = "@bazarish_auto"  # Юзернейм канала

car_month = None
car_year = None

vehicle_id = None
vehicle_no = None


def print_message(message):
    print("\n\n##############")
    print(f"{message}")
    print("##############\n\n")
    return None


def is_subscribed(user_id):
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False  # Если ошибка, считаем, что не подписан


# Функция для установки команд меню
def set_bot_commands():
    commands = [
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("cbr", "Курсы валют"),
        # types.BotCommand("stats", "Статистика"),
    ]
    bot.set_my_commands(commands)


def get_rub_to_krw_rate():
    global rub_to_krw_rate

    url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/rub.json"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Проверяем, что запрос успешный (код 200)
        data = response.json()

        rub_to_krw = data["rub"]["krw"]  # Достаем курс рубля к воне
        rub_to_krw_rate = rub_to_krw

    except requests.RequestException as e:
        print(f"Ошибка при получении курса: {e}")
        return None


# Пример вызова
rate = get_rub_to_krw_rate()
if rate:
    print(f"Текущий курс RUB → KRW: {rate:.2f} ₩")
else:
    print("Не удалось получить курс.")


# Функция для получения курсов валют с API
def get_currency_rates():
    global usd_rate, krw_rub_rate

    print_message("ПОЛУЧАЕМ КУРС ЦБ")

    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    response = requests.get(url)
    data = response.json()

    eur = data["Valute"]["EUR"]["Value"] + (
        data["Valute"]["EUR"]["Value"] * DEALER_COMMISSION
    )
    usd = data["Valute"]["USD"]["Value"] + (
        data["Valute"]["USD"]["Value"] * DEALER_COMMISSION
    )
    krw = (
        data["Valute"]["KRW"]["Value"]
        + (data["Valute"]["KRW"]["Value"] * DEALER_COMMISSION)
    ) / data["Valute"]["KRW"]["Nominal"]
    cny = data["Valute"]["CNY"]["Value"] + (
        data["Valute"]["CNY"]["Value"] * DEALER_COMMISSION
    )

    usd_rate = usd
    krw_rub_rate = krw

    rates_text = (
        f"EUR: <b>{eur:.2f} ₽</b>\n"
        f"USD: <b>{usd:.2f} ₽</b>\n"
        f"KRW: <b>{krw:.2f} ₽</b>\n"
        f"CNY: <b>{cny:.2f} ₽</b>"
    )

    return rates_text


# Обработчик команды /cbr
@bot.message_handler(commands=["cbr"])
def cbr_command(message):
    user_id = message.from_user.id

    if not is_subscribed(user_id):
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔗 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Проверить подписку", callback_data="check_subscription"
            )
        )

        bot.send_message(
            message.chat.id,
            f"🚫 Доступ ограничен! Подпишитесь на наш канал {CHANNEL_USERNAME}, чтобы пользоваться ботом.",
            reply_markup=keyboard,
        )
        return  # Прерываем выполнение, если не подписан

    try:
        rates_text = get_currency_rates()

        # Создаем клавиатуру с кнопкой для расчета автомобиля
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "Рассчитать стоимость автомобиля", callback_data="calculate_another"
            )
        )

        # Отправляем сообщение с курсами и клавиатурой
        bot.send_message(
            message.chat.id, rates_text, reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(
            message.chat.id, "Не удалось получить курсы валют. Попробуйте позже."
        )
        print(f"Ошибка при получении курсов валют: {e}")


# Main menu creation function
def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(types.KeyboardButton(CALCULATE_CAR_TEXT))
    keyboard.add(
        types.KeyboardButton("Написать менеджеру"),
        types.KeyboardButton("О нас"),
        types.KeyboardButton("Telegram-канал"),
        types.KeyboardButton("Написать в WhatsApp"),
        types.KeyboardButton("Instagram"),
        types.KeyboardButton("Tik-Tok"),
        types.KeyboardButton("Facebook"),
    )
    return keyboard


@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription(call):
    user_id = call.from_user.id

    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ Вы подписаны!")
        bot.send_message(
            call.message.chat.id,
            "✅ Спасибо за подписку! Теперь вы можете пользоваться ботом.",
            reply_markup=main_menu(),
        )
    else:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔗 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Проверить подписку", callback_data="check_subscription"
            )
        )

        bot.send_message(
            call.message.chat.id,
            "🚫 Вы ещё не подписались! Подпишитесь и нажмите кнопку 🔄 Проверить подписку.",
            reply_markup=keyboard,
        )


# Start command handler
@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id

    if not is_subscribed(user_id):
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔗 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Проверить подписку", callback_data="check_subscription"
            )
        )

        bot.send_message(
            message.chat.id,
            f"🚫 Доступ ограничен! Подпишитесь на наш канал {CHANNEL_USERNAME}, чтобы пользоваться ботом.",
            reply_markup=keyboard,
        )
        return  # Прерываем выполнение, если не подписан

    get_currency_rates()

    user_first_name = message.from_user.first_name
    welcome_message = (
        f"Здравствуйте, {user_first_name}!\n\n"
        "Я бот компании Bazarish Auto. Я помогу вам рассчитать стоимость понравившегося вам автомобиля из Южной Кореи до Владивостока.\n\n"
        "Выберите действие из меню ниже."
    )
    bot.send_message(message.chat.id, welcome_message, reply_markup=main_menu())


# Error handling function
def send_error_message(message, error_text):
    global last_error_message_id

    # Remove previous error message if it exists
    if last_error_message_id.get(message.chat.id):
        try:
            bot.delete_message(message.chat.id, last_error_message_id[message.chat.id])
        except Exception as e:
            logging.error(f"Error deleting message: {e}")

    # Send new error message and store its ID
    error_message = bot.reply_to(message, error_text, reply_markup=main_menu())
    last_error_message_id[message.chat.id] = error_message.id
    logging.error(f"Error sent to user {message.chat.id}: {error_text}")


def get_car_info(url):
    global car_id_external, vehicle_no, vehicle_id, car_year, car_month

    # driver = create_driver()

    car_id_match = re.findall(r"\d+", url)
    car_id = car_id_match[0]
    car_id_external = car_id

    url = f"https://api.encar.com/v1/readside/vehicle/{car_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "http://www.encar.com/",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
    }

    response = requests.get(url, headers=headers).json()

    # Информация об автомобиле
    car_make = response["category"]["manufacturerEnglishName"]  # Марка
    car_model = response["category"]["modelGroupEnglishName"]  # Модель
    car_trim = response["category"]["gradeDetailEnglishName"] or ""  # Комплектация

    car_title = f"{car_make} {car_model} {car_trim}"  # Заголовок

    # Получаем все необходимые данные по автомобилю
    car_price = str(response["advertisement"]["price"])
    car_date = response["category"]["yearMonth"]
    year = car_date[2:4]
    month = car_date[4:]
    car_year = year
    car_month = month

    # Пробег (форматирование)
    mileage = response["spec"]["mileage"]
    formatted_mileage = f"{mileage:,} км"

    # Тип КПП
    transmission = response["spec"]["transmissionName"]
    formatted_transmission = "Автомат" if "오토" in transmission else "Механика"

    car_engine_displacement = str(response["spec"]["displacement"])
    car_type = response["spec"]["bodyName"]

    # Список фотографий (берем первые 10)
    car_photos = [
        generate_encar_photo_url(photo["path"]) for photo in response["photos"][:10]
    ]
    car_photos = [url for url in car_photos if url]

    # Дополнительные данные
    vehicle_no = response["vehicleNo"]
    vehicle_id = response["vehicleId"]

    # Форматируем
    formatted_car_date = f"01{month}{year}"
    formatted_car_type = "crossover" if car_type == "SUV" else "sedan"

    print_message(
        f"ID: {car_id}\nType: {formatted_car_type}\nDate: {formatted_car_date}\nCar Engine Displacement: {car_engine_displacement}\nPrice: {car_price} KRW"
    )

    return [
        car_price,
        car_engine_displacement,
        formatted_car_date,
        car_title,
        formatted_mileage,
        formatted_transmission,
        car_photos,
        year,
        month,
    ]


# Function to calculate the total cost
def calculate_cost(link, message):
    global car_data, car_id_external, car_month, car_year, krw_rub_rate, eur_rub_rate, rub_to_krw_rate, usd_rate

    print_message("ЗАПРОС НА РАСЧЁТ АВТОМОБИЛЯ")

    # Отправляем сообщение и сохраняем его ID
    processing_message = bot.send_message(
        message.chat.id, "Обрабатываю данные. Пожалуйста подождите ⏳"
    )

    car_id = None

    # Проверка ссылки на мобильную версию
    if "fem.encar.com" in link:
        car_id_match = re.findall(r"\d+", link)
        if car_id_match:
            car_id = car_id_match[0]  # Use the first match of digits
            car_id_external = car_id
            link = f"https://fem.encar.com/cars/detail/{car_id}"
        else:
            send_error_message(message, "🚫 Не удалось извлечь carid из ссылки.")
            return
    else:
        # Извлекаем carid с URL encar
        parsed_url = urlparse(link)
        query_params = parse_qs(parsed_url.query)
        car_id = query_params.get("carid", [None])[0]

    result = get_car_info(link)
    (
        car_price,
        car_engine_displacement,
        formatted_car_date,
        car_title,
        formatted_mileage,
        formatted_transmission,
        car_photos,
        year,
        month,
    ) = result

    if not car_price and car_engine_displacement and formatted_car_date:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "Написать менеджеру", url="https://t.me@BAZARISH_KPP"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Рассчитать стоимость другого автомобиля",
                callback_data="calculate_another",
            )
        )
        bot.send_message(
            message.chat.id, "Ошибка", parse_mode="Markdown", reply_markup=keyboard
        )
        bot.delete_message(message.chat.id, processing_message.message_id)
        return

    # Если есть новая ссылка
    if car_price and car_engine_displacement and formatted_car_date:
        car_engine_displacement = int(car_engine_displacement)

        # Форматирование данных
        formatted_car_year = f"20{car_year}"
        engine_volume_formatted = f"{format_number(car_engine_displacement)} cc"
        age = calculate_age(int(formatted_car_year), car_month)

        age_formatted = (
            "до 3 лет"
            if age == "0-3"
            else (
                "от 3 до 5 лет"
                if age == "3-5"
                else "от 5 до 7 лет" if age == "5-7" else "от 7 лет"
            )
        )

        # Конвертируем стоимость авто в рубли
        price_krw = int(car_price) * 10000

        response = get_customs_fees(
            car_engine_displacement,
            price_krw,
            int(f"20{car_year}"),
            car_month,
            engine_type=1,
        )

        # Таможенный сбор
        customs_fee = clean_number(response["sbor"])
        customs_duty = clean_number(response["tax"])
        recycling_fee = clean_number(response["util"])

        # Расчет итоговой стоимости автомобиля в рублях
        total_cost = (
            50000
            + (price_krw * krw_rub_rate)
            + (440000 * krw_rub_rate)
            + (100000 * krw_rub_rate)
            + (350000 * krw_rub_rate)
            + (600 * usd_rate)
            + customs_duty
            + customs_fee
            + recycling_fee
            + (346 * usd_rate)
            + 50000
            + 30000
            + 8000
        )

        total_cost_krw = (
            (50000 / krw_rub_rate)
            + (price_krw)
            + 440000
            + 100000
            + 350000
            + ((600 * usd_rate) / krw_rub_rate)
            + (customs_duty / krw_rub_rate)
            + (customs_fee / krw_rub_rate)
            + (recycling_fee / krw_rub_rate)
            + ((346 * usd_rate) / krw_rub_rate)
            + 50000 / krw_rub_rate
            + 30000 / krw_rub_rate
            + 8000 / krw_rub_rate
        )
        total_cost_usd = total_cost / usd_rate

        car_data["total_cost_usd"] = total_cost_usd
        car_data["total_cost_krw"] = total_cost_krw
        car_data["total_cost_rub"] = total_cost

        car_data["agent_korea_rub"] = 50000
        car_data["agent_korea_usd"] = 50000 / usd_rate
        car_data["agent_korea_krw"] = 50000 / krw_rub_rate

        car_data["advance_rub"] = 1000000 * krw_rub_rate
        car_data["advance_usd"] = (1000000 * krw_rub_rate) / usd_rate
        car_data["advance_krw"] = 1000000

        car_data["car_price_krw"] = price_krw
        car_data["car_price_usd"] = (price_krw) * krw_rub_rate / usd_rate
        car_data["car_price_rub"] = (price_krw) * krw_rub_rate

        car_data["dealer_korea_usd"] = 440000 * krw_rub_rate / usd_rate
        car_data["dealer_korea_krw"] = 440000
        car_data["dealer_korea_rub"] = 440000 * krw_rub_rate

        car_data["delivery_korea_usd"] = 100000 * krw_rub_rate / usd_rate
        car_data["delivery_korea_krw"] = 100000
        car_data["delivery_korea_rub"] = 100000 * krw_rub_rate

        car_data["transfer_korea_usd"] = 350000 * krw_rub_rate / usd_rate
        car_data["transfer_korea_krw"] = 350000
        car_data["transfer_korea_rub"] = 350000 * krw_rub_rate

        car_data["freight_korea_usd"] = 600
        car_data["freight_korea_krw"] = 600 * usd_rate / krw_rub_rate
        car_data["freight_korea_rub"] = 600 * usd_rate

        car_data["korea_total_usd"] = (
            (50000 / usd_rate)
            + (440000 * krw_rub_rate / usd_rate)
            + (100000 * krw_rub_rate / usd_rate)
            + (350000 * krw_rub_rate / usd_rate)
            + (600)
        )

        car_data["korea_total_krw"] = (
            (50000 / krw_rub_rate)
            + (440000)
            + (100000)
            + 350000
            + (600 * usd_rate / krw_rub_rate)
        )

        car_data["korea_total_rub"] = (
            (50000)
            + (440000 * krw_rub_rate)
            + (100000 * krw_rub_rate)
            + (350000 * krw_rub_rate)
            + (600 * usd_rate)
        )

        car_data["korea_total_plus_car_usd"] = (
            (50000 / usd_rate)
            + ((price_krw) * krw_rub_rate / usd_rate)
            + (440000 * krw_rub_rate / usd_rate)
            + (100000 * krw_rub_rate / usd_rate)
            + (350000 * krw_rub_rate / usd_rate)
            + (600)
        )
        car_data["korea_total_plus_car_krw"] = (
            (50000 / krw_rub_rate)
            + (price_krw)
            + (440000)
            + (100000)
            + 350000
            + (600 * usd_rate / krw_rub_rate)
        )
        car_data["korea_total_plus_car_rub"] = (
            (50000)
            + (price_krw * krw_rub_rate)
            + (440000 * krw_rub_rate)
            + (100000 * krw_rub_rate)
            + (350000 * krw_rub_rate)
            + (600 * usd_rate)
        )

        # Расходы Россия
        car_data["customs_duty_usd"] = customs_duty / usd_rate
        car_data["customs_duty_krw"] = customs_duty * rub_to_krw_rate
        car_data["customs_duty_rub"] = customs_duty

        car_data["customs_fee_usd"] = customs_fee / usd_rate
        car_data["customs_fee_krw"] = customs_fee / krw_rub_rate
        car_data["customs_fee_rub"] = customs_fee

        car_data["util_fee_usd"] = recycling_fee / usd_rate
        car_data["util_fee_krw"] = recycling_fee / krw_rub_rate
        car_data["util_fee_rub"] = recycling_fee

        car_data["broker_russia_usd"] = 346
        car_data["broker_russia_krw"] = 346 * usd_rate / krw_rub_rate
        car_data["broker_russia_rub"] = 346 * usd_rate

        car_data["svh_russia_usd"] = 50000 / usd_rate
        car_data["svh_russia_krw"] = 50000 / krw_rub_rate
        car_data["svh_russia_rub"] = 50000

        car_data["lab_russia_usd"] = 30000 / usd_rate
        car_data["lab_russia_krw"] = 30000 / krw_rub_rate
        car_data["lab_russia_rub"] = 30000

        car_data["perm_registration_russia_usd"] = 8000 / usd_rate
        car_data["perm_registration_russia_krw"] = 8000 / krw_rub_rate
        car_data["perm_registration_russia_rub"] = 8000

        car_data["russia_total_usd"] = (
            (customs_duty / usd_rate)
            + (customs_fee / usd_rate)
            + (recycling_fee / usd_rate)
            + (346)
            + (50000 / usd_rate)
            + (8000 / usd_rate)
        )
        car_data["russia_total_krw"] = (
            (customs_duty / krw_rub_rate)
            + (customs_fee / krw_rub_rate)
            + (recycling_fee / krw_rub_rate)
            + (346 * usd_rate / krw_rub_rate)
            + (50000 / krw_rub_rate)
            + (8000 / krw_rub_rate)
        )
        car_data["russia_total_rub"] = (
            customs_duty + customs_fee + recycling_fee + (346 * usd_rate) + 50000 + 8000
        )

        preview_link = f"https://fem.encar.com/cars/detail/{car_id}"

        # Формирование сообщения результата
        result_message = (
            f"{car_title}\n\n"
            f"Возраст: {age_formatted} (дата регистрации: {month}/{year})\n"
            f"Пробег: {formatted_mileage}\n"
            f"Объём двигателя: {engine_volume_formatted}\n"
            f"КПП: {formatted_transmission}\n\n"
            f"Стоимость автомобиля в Корее: ₩{format_number(price_krw)}\n"
            f"Стоимость автомобиля под ключ до Владивостока: \n<b>${format_number(total_cost_usd)} </b> | <b>₩{format_number(total_cost_krw)} </b> | <b>{format_number(total_cost)} ₽</b>\n\n"
            f"🔗 <a href='{preview_link}'>Ссылка на автомобиль</a>\n\n"
            "Если данное авто попадает под санкции, пожалуйста уточните возможность отправки в вашу страну у менеджера @BAZARISH_KPP\n\n"
            "🔗 <a href='https://t.me/bazarish_auto'>Официальный телеграм канал</a>\n"
        )

        # Клавиатура с дальнейшими действиями
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("Детали расчёта", callback_data="detail")
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Выплаты по ДТП",
                callback_data="technical_report",
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Написать менеджеру", url="https://t.me/BAZARISH_KPP"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Расчёт другого автомобиля",
                callback_data="calculate_another",
            )
        )

        # Отправляем до 10 фотографий
        media_group = []
        for photo_url in sorted(car_photos):
            try:
                response = requests.get(photo_url)
                if response.status_code == 200:
                    photo = BytesIO(response.content)  # Загружаем фото в память
                    media_group.append(
                        types.InputMediaPhoto(photo)
                    )  # Добавляем в список

                    # Если набрали 10 фото, отправляем альбом
                    if len(media_group) == 10:
                        bot.send_media_group(message.chat.id, media_group)
                        media_group.clear()  # Очищаем список для следующей группы
                else:
                    print(f"Ошибка загрузки фото: {photo_url} - {response.status_code}")
            except Exception as e:
                print(f"Ошибка при обработке фото {photo_url}: {e}")

        # Отправка оставшихся фото, если их меньше 10
        if media_group:
            bot.send_media_group(message.chat.id, media_group)

        bot.send_message(
            message.chat.id,
            result_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        bot.delete_message(
            message.chat.id, processing_message.message_id
        )  # Удаляем сообщение о передаче данных в обработку

    else:
        send_error_message(
            message,
            "🚫 Произошла ошибка при получении данных. Проверьте ссылку и попробуйте снова.",
        )
        bot.delete_message(message.chat.id, processing_message.message_id)


# Function to get insurance total
def get_insurance_total():
    global car_id_external, vehicle_no, vehicle_id

    print_message("[ЗАПРОС] ТЕХНИЧЕСКИЙ ОТЧËТ ОБ АВТОМОБИЛЕ")

    formatted_vehicle_no = urllib.parse.quote(str(vehicle_no).strip())
    url = f"https://api.encar.com/v1/readside/record/vehicle/{str(vehicle_id)}/open?vehicleNo={formatted_vehicle_no}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "http://www.encar.com/",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

        response = requests.get(url, headers)
        json_response = response.json()

        # Форматируем данные
        damage_to_my_car = json_response["myAccidentCost"]
        damage_to_other_car = json_response["otherAccidentCost"]

        print(
            f"Выплаты по представленному автомобилю: {format_number(damage_to_my_car)}"
        )
        print(f"Выплаты другому автомобилю: {format_number(damage_to_other_car)}")

        return [format_number(damage_to_my_car), format_number(damage_to_other_car)]

    except Exception as e:
        print(f"Произошла ошибка при получении данных: {e}")
        return ["", ""]


# Callback query handler
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    global car_data, car_id_external, usd_rate

    if call.data.startswith("detail"):
        print_message("[ЗАПРОС] ДЕТАЛИЗАЦИЯ РАСЧËТА")

        detail_message = (
            f"<i>ПЕРВАЯ ЧАСТЬ ОПЛАТЫ</i>:\n\n"
            f"Агентские услуги по договору:\n<b>${format_number(car_data['agent_korea_usd'])}</b> | <b>₩{format_number(car_data['agent_korea_krw'])}</b> | <b>50000 ₽</b>\n\n"
            f"Задаток (бронь авто):\n<b>${format_number(car_data['advance_usd'])}</b> | <b>₩1,000,000</b> | <b>{format_number(car_data['advance_rub'])} ₽</b>\n\n\n"
            f"<i>ВТОРАЯ ЧАСТЬ ОПЛАТЫ</i>:\n\n"
            # f"Стоимость автомобиля (за вычетом задатка):\n<b>${format_number(car_data['car_price_usd'])}</b> | <b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
            f"Диллерский сбор:\n<b>${format_number(car_data['dealer_korea_usd'])}</b> | <b>₩{format_number(car_data['dealer_korea_krw'])}</b> | <b>{format_number(car_data['dealer_korea_rub'])} ₽</b>\n\n"
            f"Доставка, снятие с учёта, оформление:\n<b>${format_number(car_data['delivery_korea_usd'])}</b> | <b>₩{format_number(car_data['delivery_korea_krw'])}</b> | <b>{format_number(car_data['delivery_korea_rub'])} ₽</b>\n\n"
            f"Транспортировка авто в порт:\n<b>${format_number(car_data['transfer_korea_usd'])}</b> | <b>₩{format_number(car_data['transfer_korea_krw'])}</b> | <b>{format_number(car_data['transfer_korea_rub'])} ₽</b>\n\n"
            f"Фрахт (Паром до Владивостока):\n<b>${format_number(car_data['freight_korea_usd'])}</b> | <b>₩{format_number(car_data['freight_korea_krw'])}</b> | <b>{format_number(car_data['freight_korea_rub'])} ₽</b>\n\n\n"
            f"<b>Итого расходов по Корее</b>:\n<b>${format_number(car_data['korea_total_usd'])}</b> | <b>₩{format_number(car_data['korea_total_krw'])}</b> | <b>{format_number(car_data['korea_total_rub'])} ₽</b>\n\n"
            f"<b>Стоимость автомобиля</b>:\n<b>${format_number(car_data['car_price_usd'])}</b> | <b>₩{format_number(car_data['car_price_krw'])}</b> | <b>{format_number(car_data['car_price_rub'])} ₽</b>\n\n"
            f"<b>Итого</b>:\n<b>${format_number(car_data['korea_total_plus_car_usd'])}</b> | <b>₩{format_number(car_data['korea_total_plus_car_krw'])}</b> | <b>{format_number(car_data['korea_total_plus_car_rub'])} ₽</b>\n\n\n"
            f"<i>РАСХОДЫ РОССИЯ</i>:\n\n\n"
            f"Единая таможенная ставка:\n<b>${format_number(car_data['customs_duty_usd'])}</b> | <b>₩{format_number(car_data['customs_duty_krw'])}</b> | <b>{format_number(car_data['customs_duty_rub'])} ₽</b>\n\n"
            f"Таможенное оформление:\n<b>${format_number(car_data['customs_fee_usd'])}</b> | <b>₩{format_number(car_data['customs_fee_krw'])}</b> | <b>{format_number(car_data['customs_fee_rub'])} ₽</b>\n\n"
            f"Утилизационный сбор:\n<b>${format_number(car_data['util_fee_usd'])}</b> | <b>₩{format_number(car_data['util_fee_krw'])}</b> | <b>{format_number(car_data['util_fee_rub'])} ₽</b>\n\n\n"
            f"Брокер-Владивосток:\n<b>${format_number(car_data['broker_russia_usd'])}</b> | <b>₩{format_number(car_data['broker_russia_krw'])}</b> | <b>{format_number(car_data['broker_russia_rub'])} ₽</b>\n\n"
            f"СВХ-Владивосток:\n<b>${format_number(car_data['svh_russia_usd'])}</b> | <b>₩{format_number(car_data['svh_russia_krw'])}</b> | <b>{format_number(car_data['svh_russia_rub'])} ₽</b>\n\n"
            f"Лаборатория, СБКТС, ЭПТС:\n<b>${format_number(car_data['lab_russia_usd'])}</b> | <b>₩{format_number(car_data['lab_russia_krw'])}</b> | <b>{format_number(car_data['lab_russia_rub'])} ₽</b>\n\n"
            f"Временная регистрация-Владивосток:\n<b>${format_number(car_data['perm_registration_russia_usd'])}</b> | <b>₩{format_number(car_data['perm_registration_russia_krw'])}</b> | <b>{format_number(car_data['perm_registration_russia_rub'])} ₽</b>\n\n"
            f"Итого расходов по России: \n<b>${format_number(car_data['russia_total_usd'])}</b> | <b>₩{format_number(car_data['russia_total_krw'])}</b> | <b>{format_number(car_data['russia_total_rub'])} ₽</b>\n\n\n"
            f"Итого под ключ во Владивостоке: \n<b>${format_number(car_data['total_cost_usd'])}</b> | <b>₩{format_number(car_data['total_cost_krw'])}</b> | <b>{format_number(car_data['total_cost_rub'])} ₽</b>\n\n"
            f"<b>Доставку до вашего города уточняйте у менеджера @BAZARISH_KPP</b>\n"
        )

        # Inline buttons for further actions
        keyboard = types.InlineKeyboardMarkup()

        if call.data.startswith("detail_manual"):
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another_manual",
                )
            )
        else:
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )

        keyboard.add(
            types.InlineKeyboardButton(
                "Связаться с менеджером", url="https://t.me/BAZARISH_KPP"
            )
        )

        bot.send_message(
            call.message.chat.id,
            detail_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    elif call.data == "technical_report":
        bot.send_message(
            call.message.chat.id,
            "Запрашиваю отчёт по ДТП. Пожалуйста подождите ⏳",
        )

        # Retrieve insurance information
        insurance_info = get_insurance_total()

        # Проверка на наличие ошибки
        if (
            insurance_info is None
            or "Нет данных" in insurance_info[0]
            or "Нет данных" in insurance_info[1]
        ):
            error_message = (
                "Не удалось получить данные о страховых выплатах. \n\n"
                f'<a href="https://fem.encar.com/cars/report/accident/{car_id_external}">🔗 Посмотреть страховую историю вручную 🔗</a>\n\n\n'
                f"<b>Найдите две строки:</b>\n\n"
                f"보험사고 이력 (내차 피해) - Выплаты по представленному автомобилю\n"
                f"보험사고 이력 (타차 가해) - Выплаты другим участникам ДТП"
            )

            # Inline buttons for further actions
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/BAZARISH_KPP"
                )
            )

            # Отправка сообщения об ошибке
            bot.send_message(
                call.message.chat.id,
                error_message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            current_car_insurance_payments = (
                "0" if len(insurance_info[0]) == 0 else insurance_info[0]
            )
            other_car_insurance_payments = (
                "0" if len(insurance_info[1]) == 0 else insurance_info[1]
            )

            # Construct the message for the technical report
            tech_report_message = (
                f"Страховые выплаты по представленному автомобилю: \n<b>{current_car_insurance_payments} ₩</b>\n\n"
                f"Страховые выплаты другим участникам ДТП: \n<b>{other_car_insurance_payments} ₩</b>\n\n"
                f'<a href="https://fem.encar.com/cars/report/inspect/{car_id_external}">🔗 Ссылка на схему повреждений кузовных элементов 🔗</a>'
            )

            # Inline buttons for further actions
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "Рассчитать стоимость другого автомобиля",
                    callback_data="calculate_another",
                )
            )
            keyboard.add(
                types.InlineKeyboardButton(
                    "Связаться с менеджером", url="https://t.me/BAZARISH_KPP"
                )
            )

            bot.send_message(
                call.message.chat.id,
                tech_report_message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    elif call.data == "calculate_another":
        bot.send_message(
            call.message.chat.id,
            "Пожалуйста, введите ссылку на автомобиль с сайта www.encar.com:",
        )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_message = message.text.strip()

    # Проверяем нажатие кнопки "Рассчитать автомобиль"
    if user_message == CALCULATE_CAR_TEXT:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, введите ссылку на автомобиль с сайта www.encar.com:",
        )

    # Проверка на корректность ссылки
    elif re.match(r"^https?://(www|fem)\.encar\.com/.*", user_message):
        calculate_cost(user_message, message)

    # Проверка на другие команды
    elif user_message == "Написать менеджеру":
        bot.send_message(
            message.chat.id, "Вы можете связаться с менеджером по ссылке: @BAZARISH_KPP"
        )
    elif user_message == "Написать в WhatsApp":
        contacts = [
            {"name": "Константин", "phone": "+82 10-7650-3034"},
            # {"name": "Владимир", "phone": "+82 10-7930-2218"},
            # {"name": "Илья", "phone": "+82 10-3458-2205"},
        ]

        message_text = "\n".join(
            [
                f"[{contact['name']}](https://wa.me/{contact['phone'].replace('+', '')})"
                for contact in contacts
            ]
        )
        bot.send_message(message.chat.id, message_text, parse_mode="Markdown")

    elif user_message == "О нас":
        about_message = "Bazarish Auto\nЮжнокорейская экспортная компания.\nСпециализируемся на поставках автомобилей из Южной Кореи в страны СНГ.\nОпыт работы более 5 лет.\n\nПочему выбирают нас?\n• Надежность и скорость доставки.\n• Индивидуальный подход к каждому клиенту.\n• Полное сопровождение сделки.\n\n💬 Ваш путь к надежным автомобилям начинается здесь!"
        bot.send_message(message.chat.id, about_message)
    elif user_message == "Telegram-канал":
        channel_link = "https://t.me/bazarish_auto"
        bot.send_message(
            message.chat.id, f"Подписывайтесь на наш Telegram-канал: {channel_link}"
        )
    elif user_message == "Instagram":
        instagram_link = "https://www.instagram.com/bazarish_auto/"
        bot.send_message(
            message.chat.id,
            f"Посетите наш Instagram: {instagram_link}",
        )
    elif user_message == "Tik-Tok":
        tiktok_link = "https://www.tiktok.com/@kpp_motors"
        bot.send_message(
            message.chat.id,
            f"Следите за свежим контентом на нашем TikTok: {tiktok_link}",
        )
    elif user_message == "Facebook":
        facebook_link = "https://www.facebook.com/share/1D8bg2xL1i/?mibextid=wwXIfr"
        bot.send_message(
            message.chat.id,
            f"KPP Motors на Facebook: {facebook_link}",
        )
    else:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, введите корректную ссылку на автомобиль с сайта www.encar.com или fem.encar.com.",
        )


# Run the bot
if __name__ == "__main__":
    # initialize_db()
    set_bot_commands()
    get_rub_to_krw_rate()
    get_currency_rates()
    bot.polling(non_stop=True)
