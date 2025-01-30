import telebot
import psycopg2
import os
import re
import requests
import locale
import datetime
import logging
import urllib.parse

from telebot import types
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

CALCULATE_CAR_TEXT = "Расчёт Автомобиля"
DEALER_COMMISSION = 0.02  # 2%


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
usd_rate = 0
users = set()
admins = [7311593407, 728438182]
car_month = None
car_year = None

vehicle_id = None
vehicle_no = None


def print_message(message):
    print("\n\n##############")
    print(f"{message}")
    print("##############\n\n")
    return None


# Функция для установки команд меню
def set_bot_commands():
    commands = [
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("cbr", "Курсы валют"),
        # types.BotCommand("stats", "Статистика"),
    ]
    bot.set_my_commands(commands)


# Функция для получения курсов валют с API
def get_currency_rates():
    global usd_rate

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


# Обработчик команды /currencyrates
@bot.message_handler(commands=["currencyrates"])
def currencyrates_command(message):
    bot.send_message(message.chat.id, "Актуальные курсы валют: ...")


# Main menu creation function
def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(
        types.KeyboardButton(CALCULATE_CAR_TEXT),
        types.KeyboardButton("Написать менеджеру"),
        types.KeyboardButton("О нас"),
        types.KeyboardButton("Telegram-канал"),
        types.KeyboardButton("Написать в WhatsApp"),
        types.KeyboardButton("Instagram"),
        types.KeyboardButton("Tik-Tok"),
        types.KeyboardButton("Facebook"),
    )
    return keyboard


# Start command handler
@bot.message_handler(commands=["start"])
def send_welcome(message):
    get_currency_rates()

    user = message.from_user
    user_first_name = user.first_name

    welcome_message = (
        f"Здравствуйте, {user_first_name}!\n\n"
        "Я бот компании KPP Motors. Я помогу вам расчитать стоимость понравившегося вам автомобиля из Южной Кореи до Владивостока\n\n"
        "Выберите действие из меню ниже"
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

    # Получаем все необходимые данные по автомобилю
    car_price = str(response["advertisement"]["price"])
    car_date = response["category"]["yearMonth"]

    year = car_date[2:4]
    month = car_date[4:]

    car_year = year
    car_month = month

    car_engine_displacement = str(response["spec"]["displacement"])
    car_type = response["spec"]["bodyName"]

    # Для получения данных по страховым выплатам
    vehicle_no = response["vehicleNo"]
    vehicle_id = response["vehicleId"]

    # Форматируем
    formatted_car_date = f"01{month}{year}"
    formatted_car_type = "crossover" if car_type == "SUV" else "sedan"

    print_message(
        f"ID: {car_id}\nType: {formatted_car_type}\nDate: {formatted_car_date}\nCar Engine Displacement: {car_engine_displacement}\nPrice: {car_price} KRW"
    )

    # Сохранение данных в базу
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO car_info (car_id, date, engine_volume, price, car_type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (car_id) DO NOTHING
        """,
        (
            car_id,
            formatted_car_date,
            car_engine_displacement,
            car_price,
            formatted_car_type,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()
    print("Автомобиль был сохранён в базе данных")

    new_url = f"https://plugin-back-versusm.amvera.io/car-ab-korea/{car_id}?price={car_price}&date={formatted_car_date}&volume={car_engine_displacement}"

    return [new_url, "", formatted_car_date]


# Function to calculate the total cost
def calculate_cost(link, message):
    global car_data, car_id_external, car_month, car_year

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
    new_url, car_title, formatted_car_date = result

    if not new_url and car_title:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "Написать менеджеру", url="https://t.me/KPP_Motorss"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Рассчитать стоимость другого автомобиля",
                callback_data="calculate_another",
            )
        )
        bot.send_message(
            message.chat.id, car_title, parse_mode="Markdown", reply_markup=keyboard
        )
        bot.delete_message(message.chat.id, processing_message.message_id)
        return

    # Если есть новая ссылка
    if new_url:
        try:
            response = requests.get(new_url)
            json_response = response.json()
        except requests.RequestException as e:
            logging.error(f"Ошибка при запросе данных: {e}")
            send_error_message(
                message,
                "🚫 Произошла ошибка при получении данных. Проверьте ссылку и попробуйте снова.",
            )
            bot.delete_message(message.chat.id, processing_message.message_id)
            return
        except ValueError:
            logging.error("Получен некорректный JSON.")
            send_error_message(
                message,
                "🚫 Неверный формат данных. Проверьте ссылку или повторите попытку.",
            )
            bot.delete_message(message.chat.id, processing_message.message_id)
            return

        car_data = json_response

        result = json_response.get("result", {})
        car = result.get("car", {})
        price = result.get("price", {}).get("car", {}).get("krw", 0)

        engine_volume_raw = car.get("engineVolume", None)
        engine_volume = re.sub(r"\D+", "", engine_volume_raw)

        if not (car_year and engine_volume and price):
            logging.warning("Не удалось извлечь все необходимые данные из JSON.")
            bot.send_message(
                message.chat.id,
                "🚫 Не удалось извлечь все необходимые данные. Проверьте ссылку.",
            )
            bot.delete_message(message.chat.id, processing_message.message_id)
            return

        # Форматирование данных
        formatted_car_year = f"20{car_year}"
        engine_volume_formatted = f"{format_number(int(engine_volume))} cc"
        age_formatted = calculate_age(int(formatted_car_year), car_month)

        grand_total = result.get("price", {}).get("grandTotal", 0)
        recycling_fee = (
            result.get("price", {})
            .get("russian", {})
            .get("recyclingFee", {})
            .get("rub", 0)
        )
        duty_cleaning = (
            result.get("price", {})
            .get("korea", {})
            .get("dutyCleaning", {})
            .get("rub", 0)
        )

        total_cost = (
            int(grand_total) - int(recycling_fee) - int(duty_cleaning)
        ) + 110000
        total_cost_formatted = format_number(
            total_cost + (total_cost * DEALER_COMMISSION)
        )
        price_formatted = format_number(price)

        current_rub_krw_rate = (
            json_response.get("result", {}).get("rates", {}).get("rub", 0)
        )

        preview_link = f"https://fem.encar.com/cars/detail/{car_id}"

        # Формирование сообщения результата
        result_message = (
            f"Возраст автомобиля: {age_formatted}\n"
            f"Стоимость в Южной Корее (в корейских вонах): {price_formatted} ₩\n"
            f"Объём двигателя: {engine_volume_formatted}\n\n"
            f"Стоимость автомобиля под ключ до Владивостока на текущий момент: <b>{total_cost_formatted} ₽</b>\n\n"
            f"Так же принимаем оплату по <b>USDT</b>.\nДля более подробной информации напишите нашему менеджеру @KPP_Motorss\n\n"
            f"Текущий курс рубля к корейской воне: \n<b>{current_rub_krw_rate} ₩</b>\n"
            f"Для просмотра текущего курса ЦБ нажмите сюда /cbr \n\n"
            f"🔗 <a href='{preview_link}'>Ссылка на автомобиль</a>\n\n"
            f"Если данное авто попадает под санкции, пожалуйста уточните возможность отправки в вашу страну у менеджера @KPP_Motorss\n\n"
            "🔗 <a href='https://t.me/TELEGRAM_CHANNEL'>Официальный телеграм канал</a>\n"
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
                "Написать менеджеру", url="https://t.me/KPP_Motorss"
            )
        )
        keyboard.add(
            types.InlineKeyboardButton(
                "Расчёт другого автомобиля",
                callback_data="calculate_another",
            )
        )

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

        details = {
            "car_price_korea": car_data.get("result")["price"]["car"]["rub"],
            "dealer_fee": car_data.get("result")["price"]["korea"]["ab"]["rub"],
            "korea_logistics": car_data.get("result")["price"]["korea"]["logistic"][
                "rub"
            ],
            "customs_fee": car_data.get("result")["price"]["korea"]["dutyCleaning"][
                "rub"
            ],
            "delivery_fee": car_data.get("result")["price"]["korea"]["delivery"]["rub"],
            "dealer_commission": car_data.get("result")["price"]["korea"][
                "dealerCommission"
            ]["rub"],
            "russiaDuty": car_data.get("result")["price"]["russian"]["duty"]["rub"],
            "recycle_fee": car_data.get("result")["price"]["russian"]["recyclingFee"][
                "rub"
            ],
            "registration": car_data.get("result")["price"]["russian"]["registration"][
                "rub"
            ],
            "sbkts": car_data.get("result")["price"]["russian"]["sbkts"]["rub"],
            "svhAndExpertise": car_data.get("result")["price"]["russian"][
                "svhAndExpertise"
            ]["rub"],
            "delivery": car_data.get("result")["price"]["russian"]["delivery"]["rub"],
        }

        car_price_formatted = format_number(
            int(details["car_price_korea"])
            + (int(details["car_price_korea"] * DEALER_COMMISSION))
        )
        dealer_fee_formatted = format_number(35000)
        delivery_fee_formatted = format_number((750 * usd_rate) + 10000)
        dealer_commission_formatted = format_number(
            int(details["dealer_commission"]) + 30000
        )
        recycling_fee_formatted = format_number(details["recycle_fee"])
        russia_duty_formatted = format_number(
            int(details["russiaDuty"]) - int(details["recycle_fee"])
        )

        detail_message = (
            f"Стоимость авто: <b>{car_price_formatted} ₽</b>\n\n"
            f"Услуги Брокера (СВХ, СБКТС): <b>{format_number(115000)} ₽</b>\n\n"
            f"Доставка до Владивостока: <b>{delivery_fee_formatted} ₽</b>\n\n"
            f"Экспотная декларация и логистика по Южной Корее: <b>{dealer_commission_formatted} ₽</b>\n\n"
            f"Единая таможенная ставка (ЕТС): <b>{russia_duty_formatted} ₽</b>\n\n"
            f"Утилизационный сбор: <b>{recycling_fee_formatted} ₽</b>\n\n"
            f"<b>Доставку до вашего города уточняйте у менеджера @KPP_Motorss</b>\n\n"
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
                "Связаться с менеджером", url="https://t.me/KPP_Motorss"
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
                    "Связаться с менеджером", url="https://t.me/KPP_Motorss"
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
                    "Связаться с менеджером", url="https://t.me/KPP_Motorss"
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
            message.chat.id, "Вы можете связаться с менеджером по ссылке: @KPP_Motorss"
        )
    elif user_message == "Написать в WhatsApp":
        whatsapp_link = "https://wa.me/821076503034"  # Костя 1
        whatsapp_link_second = "https://wa.me/821072911701"  # Костя 2
        whatsapp_link_third = "https://wa.me/821035041522"  # Елена

        message_text = f"{whatsapp_link} - Константин\n{whatsapp_link_second} - Константин 2\n{whatsapp_link_third} - Елена (English, 한국어)"

        bot.send_message(
            message.chat.id,
            message_text,
        )
    elif user_message == "О нас":
        about_message = "KPP Motors\nЮжнокорейская экспортная компания.\nСпециализируемся на поставках автомобилей из Южной Кореи в страны СНГ.\nОпыт работы более 5 лет.\n\nПочему выбирают нас?\n• Надежность и скорость доставки.\n• Индивидуальный подход к каждому клиенту.\n• Полное сопровождение сделки.\n\n💬 Ваш путь к надежным автомобилям начинается здесь!"
        bot.send_message(message.chat.id, about_message)
    elif user_message == "Telegram-канал":
        channel_link = "https://t.me/TELEGRAM CHANNEL"
        bot.send_message(
            message.chat.id, f"Подписывайтесь на наш Telegram-канал: {channel_link}"
        )
    elif user_message == "Instagram":
        instagram_link = "https://www.instagram.com/kpp_motors"
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


# Utility function to calculate the age category
def calculate_age(year, month):
    # Убираем ведущий ноль у месяца, если он есть
    month = int(month.lstrip("0")) if isinstance(month, str) else int(month)

    current_date = datetime.datetime.now()
    car_date = datetime.datetime(year=int(year), month=month, day=1)

    age_in_months = (
        (current_date.year - car_date.year) * 12 + current_date.month - car_date.month
    )

    if age_in_months < 36:
        return f"До 3 лет"
    elif 36 <= age_in_months < 60:
        return f"от 3 до 5 лет"
    else:
        return f"от 5 лет"


def format_number(number):
    return locale.format_string("%d", number, grouping=True)


# Run the bot
if __name__ == "__main__":
    # initialize_db()
    set_bot_commands()
    bot.polling(non_stop=True)
