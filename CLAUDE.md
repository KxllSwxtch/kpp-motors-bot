# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KPP Motors Telegram Bot - calculates total import costs for Korean vehicles (from Encar.com) to Russia, including customs duties, fees, and currency conversion.

## Tech Stack

- **Language:** Python 3.10.12
- **Bot Framework:** pyTelegramBotAPI 4.25.0
- **Database:** PostgreSQL (Heroku Postgres)
- **Deployment:** Heroku (worker dyno)
- **External APIs:** Encar.com (car data), CBR (currency rates), calcus.ru (customs fees)

## Commands

```bash
# Run the bot locally (requires BOT_TOKEN in .env)
python3 main.py

# Deploy to Heroku (configured via Procfile)
git push heroku main
```

## Architecture

### File Structure

- `main.py` - Main bot logic: handlers, API calls, cost calculation (901 lines)
- `utils.py` - Helper functions: number formatting, age calculation, customs API, photo URLs
- `get_currency_rates.py` - Standalone currency rate function (appears unused)
- `Procfile` - Heroku worker configuration
- `runtime.txt` - Python version specification

### Key Components in main.py

**Global State:** The bot uses global variables for session data (`car_data`, `vehicle_id`, `vehicle_no`, currency rates, etc.)

**External API Integrations:**
- `get_car_info(url)` - Fetches vehicle data from Encar.com API
- `get_currency_rates()` - CBR rates with 2% dealer margin
- `get_insurance_total()` - Vehicle accident/insurance history from Encar
- `get_customs_fees()` (in utils.py) - Russian customs calculation via calcus.ru

**Cost Calculation Formula (calculate_cost):**
Car price + Agent fees (Korea/Russia) + Delivery + Customs duty + Customs fee + Recycling fee + Registration

### Bot Commands/Menu

- `/start` - Main menu with inline buttons
- `/cbr` - Current currency exchange rates
- Text handlers: "Рассчитать стоимость", "Менеджер", "О компании", social links
- Callback handlers: "details", "tech_report", "calculate_another"

## Environment Variables

Required in `.env`:
- `BOT_TOKEN` - Telegram bot token

Database connection string is currently hardcoded in main.py.

## Code Conventions

- Comments and some variable names are in Russian
- Procedural style with global state management
- No type hints or formal docstrings
- Error handling via try/except with Telegram message feedback
