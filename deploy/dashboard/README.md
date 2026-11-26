# Дашборд NTR на сервере компании

Дашборд — статический сайт из трёх файлов (`index.html`, `data.json`, `STATUS.md`). GitHub Actions пересобирает его при каждой выгрузке и раз в 30 минут и кладёт в ветку `gh-pages` этого репозитория. Серверу остаётся раз в несколько минут забирать эту ветку и отдавать её по HTTPS за логином и паролем.

На сервер ничего не ставится, кроме git и веб-сервера. Исходящий доступ нужен только к `github.com`.

## Вариант А — Linux и nginx

1. Пакеты: `nginx`, `git`, `apache2-utils` (утилита `htpasswd`).
2. Первая загрузка сайта:
   ```sh
   sudo install -d -o www-data -g www-data /var/www/ntr-dashboard
   sudo cp update.sh /usr/local/bin/ntr-dashboard-update && sudo chmod +x /usr/local/bin/ntr-dashboard-update
   sudo -u www-data /usr/local/bin/ntr-dashboard-update
   ```
3. Логин и пароль (команда спросит пароль; повторить для каждого пользователя без `-c`):
   ```sh
   sudo htpasswd -c /etc/nginx/ntr-dashboard.htpasswd ntr
   ```
4. Сайт: скопировать `nginx.conf` в `/etc/nginx/sites-available/ntr-dashboard`, заменить `dashboard.example.ru` на свой адрес и пути к сертификату, включить сайт, `sudo nginx -t && sudo systemctl reload nginx`.
5. Обновление каждые 5 минут — строка в `sudo crontab -u www-data -e`:
   ```
   */5 * * * * /usr/local/bin/ntr-dashboard-update >/dev/null 2>&1
   ```

## Вариант Б — Docker

Подходит для любого сервера с Docker, включая Windows Server.

```sh
docker run --rm httpd:2.4-alpine htpasswd -nbB ntr 'ПАРОЛЬ' > htpasswd
docker compose up -d
```

Сайт поднимется на порту 8080 по HTTP — HTTPS добавляется на существующем обратном прокси компании.

## Если репозиторий станет приватным

Сейчас репозиторий публичный, поэтому логин на дашборде закрывает только страницу: те же данные читаются на GitHub. Чтобы закрыть их полностью, репозиторий переводится в приватный, а серверу выдаётся ключ только на чтение:

1. На сервере: `ssh-keygen -t ed25519 -f ~/.ssh/ntr_dashboard -N ''`.
2. Открытую часть (`.pub`) добавить в GitHub: Settings → Deploy keys, без права записи.
3. В `update.sh` (или в `docker-compose.yml`) заменить адрес на `git@github.com:agnstrv/NTR_AI.git`.

## Проверка

- Без пароля сервер отвечает `401`.
- После входа открывается страница «NTR · ИИ в производстве», в шапке — время «данные от …» не старше 30–40 минут.
- Бейдж «автообновление не сработало» означает, что сервер больше двух часов не получал новых данных: проверить cron и доступ к `github.com`.
