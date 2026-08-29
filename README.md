# Bozya_vpn

Автоматический сбор и проверка VPN-подписок (VLESS / VMess / Trojan / Hysteria2).

Скрипт скачивает указанные источники, убирает российские узлы, проверяет
доступность по TCP и HTTP через Xray. В начале всегда три Cloudflare AWG.

## Готовые файлы

- output/top30.txt - смешанная подписка (AWG + новые сервера)
- output/top30.b64.txt - та же подписка в base64
- output/report.json - подробный отчёт по узлам
- output/summary.yaml - сводка по выборке

## Итоговая ссылка на подписку

Для **PattNG**:

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-full.json

Только БС:

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-bs.json

Happ (WireGuard BS):

https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/happ-bs.txt

В начале подписки всегда:
- 3 Cloudflare AWG (`Белый список | 🇩🇪/🇫🇮/🇵🇱`) — даже если TCP/HTTP не отвечает
- Нидерланды из Akonit с именем `🇳🇱 СЕРВЕРА СУПЕР СТАБИЛЬНЫЕ ДЛЯ НИКИТЫ И ПОЛИНЫ` (пинг не фильтруется)
- сервера из Happ/Fixcord (без РФ)
- 6 самых быстрых серверов с aska.lol

Всего до 40 конфигов. Старые источники (Griffon, Nebula, addsub, connliberty, vlessfo) больше не собираются.

GitHub Actions обновляет подписку каждые 4 часа.
