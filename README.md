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

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/happ-bs.txt

Для **PattNG** — полная подписка (БС сверху + обычные):

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-full.json

Только БС для PattNG:

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-bs.json

Во всех подписках только серверы Fixcord и Akonit. Старые узлы удалены.
Имена по стране с номером: `🇳🇱 Нидерланды 1`, `🇳🇱 Нидерланды 2`.

Источники:
- Fixcord (ссылка Happ crypt5)
- Akonit `https://akonit.tech/sub/f9afd2d3-3858-403e-bbc9-9a720420c188`

GitHub Actions обновляет подписку каждые 4 часа.

Happ/Xray не умеют AmneziaWG 2.0. PattNG получает маскировку через Finalmask.
Для полного AWG импортируй `output/LTE*WARPv2_*.conf` в AmneziaWG.
Исходники/патч для PattNG — в `pattng-patch/`.

## Расписание

GitHub Actions обновляет файлы каждый день в 06:00 и 19:30 по Москве (UTC+3),
а также по кнопке "Run workflow".
