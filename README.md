# Bozya_vpn

Автоматический сбор и проверка VPN-подписок (VLESS / VMess / Trojan / Hysteria2).

Скрипт скачивает несколько источников, убирает дубликаты и российские узлы,
проверяет доступность серверов по TCP, сортирует узлы по качеству и публикует
готовые файлы в ветке main через GitHub Actions.

## Готовые файлы

- output/top30.txt - топ-30 рабочих зарубежных узлов
- output/top30.b64.txt - та же подписка в base64
- output/clash_royale.txt - 1 лучший узел для игр (Clash Royale)
- output/speed.txt - 1 лучший узел для максимальной скорости
- output/report.json - подробный отчёт по узлам
- output/summary.yaml - сводка по выборке

## Как обновить вручную

1. Откройте вкладку Actions.
2. Выберите workflow "Update Subscriptions".
3. Нажмите "Run workflow" -> "Run workflow".

## Локальный запуск

```
pip install -r requirements.txt
python checker.py
```

Необязательно: добавьте в Settings -> Secrets and variables -> Actions
секрет IPINFO_TOKEN - тогда страна узлов будет дополнительно определяться по IP.

## Итоговая ссылка на подписку

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/top30.txt

Только серверы белого списка (WireGuard для Happ):

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/bs.txt

В начале `top30.txt` всегда идут 3 сервера белого списка (`BS DE` / `BS FI` / `BS PL`)
в формате `wireguard://` — без пинга и без сортировки.

Для реального AmneziaWG (как в приложении AmneziaWG) импортируй файлы
`output/LTE*WARPv2_*.conf` — Happ не понимает схему `awg://` и ядро Xray
не поднимает AmneziaWG 2.0 с пакетом `I1`.

## Расписание

GitHub Actions обновляет файлы каждый день в 06:00 и 19:30 по Москве (UTC+3),
а также по кнопке "Run workflow".
