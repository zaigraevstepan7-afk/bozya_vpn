# Bozya_vpn

Автоматический сбор и проверка VPN-подписок (VLESS / VMess / Trojan / Hysteria2).

Скрипт скачивает несколько источников, убирает дубликаты и российские узлы,
проверяет доступность сначала по TCP, затем реальной загрузкой HTTP через Xray
(сокс → generate_204). В подписку попадают только узлы, которые реально проксируют
трафик. Три Cloudflare AWG (🇩🇪/🇫🇮/🇵🇱) всегда остаются, даже если порт не отвечает.

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

В начале подписки всегда:
- 3 Cloudflare AWG (`Белый список | 🇩🇪/🇫🇮/🇵🇱`) — даже если TCP/HTTP не отвечает
- живые закреплённые: `🇨🇭 Швейцария`, `🇫🇮 Лютый обход | VIP LTE Финляндия`, `🇫🇷 Франция` (мёртвые снимаются)
- `🇪🇺 Автовыбор` (leastPing по живым нодам Nebula Curse, если подписка жива)
- минимум 5 БС из Nebula Curse не из России (`Белый список | LTE-N · страна`), если они отвечают
- все **рабочие** сервера addsub.site **кроме Германии** (автовыбор без DE + NL/PL/EE)

Источники автопарсера:
- Griffon `https://cdn.griffon-guard.com/sub/HaJY2J3e4hUzVaCc` (HWID)
- Nebula Curse `https://sub.nebulacurse.space/W83--xXdonEXYRBB/`
- addsub `https://addsub.site/api/sub/ZkHKDZtBFh_D9rNF` (без Германии)

GitHub Actions обновляет подписку каждые 4 часа.

Happ/Xray не умеют AmneziaWG 2.0. PattNG получает маскировку через Finalmask.
Для полного AWG импортируй `output/LTE*WARPv2_*.conf` в AmneziaWG.
Исходники/патч для PattNG — в `pattng-patch/`.

## Расписание

GitHub Actions обновляет файлы каждый день в 06:00 и 19:30 по Москве (UTC+3),
а также по кнопке "Run workflow".
