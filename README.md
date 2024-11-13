# Telegram Бот с Интеграцией OpenAI Ассистента

Данный Telegram бот использует OpenAI Ассистента для ответа на сообщения пользователей. Он поддерживает аутентификацию пользователей, историю сообщений и может быть развёрнут с помощью Docker Compose.

## Функциональность

- Использует OpenAI Ассистента для генерации ответов.
- Работает через пулинг Telegram (не использует webhook).
- Контроль доступа пользователей через переменные окружения.
- Поддерживает историю диалогов с настраиваемой глубиной.
- Простое развёртывание с помощью Docker Compose.

## Предварительные требования

- Установленные Docker и Docker Compose.
- API ключ OpenAI.
- Токен Telegram бота, полученный через BotFather.

## Инструкции по установке

### 1. Клонируйте репозиторий

```
git clone https://github.com/artwist-polyakov/OpenAIAssistantBot.git
cd OpenAIAssistantBot
```

### 2. Создайте файл .env

```

cp .env.example .env
nano .env

```

Создайте файл .env в корневой директории со следующими переменными:

```
BOT_TOKEN=ваш_токен_телеграм_бота
OPENAI_API_KEY=ваш_openai_api_key
ASSISTANT_ID=ваш_assistant_id
USERS=список_разрешенных_имен_пользователей_через_запятую_или_*
```

- BOT_TOKEN: Токен вашего Telegram бота.
- OPENAI_API_KEY: Ваш API ключ OpenAI.
- ASSISTANT_ID: ID вашего ассистента OpenAI.
- USERS: Список имён пользователей Telegram, которым разрешён доступ к боту. Используйте *, чтобы снять ограничения.

### 3. Соберите и запустите Docker контейнер

Убедитесь, что Docker и Docker Compose установлены, затем выполните:

```
docker compose up -d --build
```

Эта команда соберёт Docker образ и запустит бота.

## Использование

- Начните диалог с вашим ботом в Telegram.
- Отправьте сообщение боту. Если ваше имя пользователя авторизовано, бот обработает ваше сообщение с помощью OpenAI Ассистента и отправит ответ.
- Если вы ответите на сообщение бота, он включит предыдущую историю диалога в контекст, до установленной глубины HISTORY_DEPTH.

## Заметки

- Бот использует оперативную память для хранения истории пользователей. При перезапуске бота история будет потеряна.
- Обеспечьте безопасность вашего API ключа OpenAI и токена Telegram бота. Не делитесь ими публично.
- При необходимости измените значение HISTORY_DEPTH в файле .env.

## Лицензия

Этот проект распространяется под лицензией MIT.
