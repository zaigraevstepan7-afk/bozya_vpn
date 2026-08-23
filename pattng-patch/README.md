# PattNG patch: AmneziaWG BS / WARP via Finalmask

Исходники: https://github.com/patterniha/PattNG

PattNG = форк v2rayNG на Xray. Схема `awg://` и ядро AmneziaWG 2.0 **не поддерживаются**.
Зато есть **Finalmask** (UDP noise) на WireGuard outbound — им мы имитируем `I1` + `Jc`.

## Без пересборки APK (рекомендуется)

Полная подписка (БС сверху + обычные узлы):

```
https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-full.json
```

Только белый список:

```
https://raw.githubusercontent.com/zaigraevstepan7-afk/bozya_vpn/main/output/pattng-bs.json
```

В PattNG: подписки → добавить URL → обновить.
Имена БС: **Белый список | 🇩🇪 Германия** / **🇫🇮 Финляндия** / **🇵🇱 Польша**.

## С пересборкой (awg:// и импорт .conf)

Скопируй поверх исходников PattNG:

| Файл | Куда |
|------|------|
| `WireguardFmt.kt` | `V2rayNG/app/src/main/java/com/v2ray/ang/fmt/` |
| `AngConfigManager.kt` | `V2rayNG/app/src/main/java/com/v2ray/ang/handler/` |
| `AppConfig.kt` | `V2rayNG/app/src/main/java/com/v2ray/ang/` |

Что даёт патч:

1. `awg://` → тот же парсер, что `wireguard://`
2. `fm` / `i1` / `jc` / `jmin` / `jmax` → `ProfileItem.finalMask`
3. Импорт Amnezia `.conf` с `I1`/`Jc` → Finalmask noise

Сборка: Android Studio или `./gradlew :app:assembleFdroidRelease`.

## Важно

Finalmask ≈ маскировка до handshake, это **не полный AmneziaWG 2.0**.
Если в stock PattNG всё ещё не коннектится — используй приложение AmneziaWG и файлы `output/LTE*WARPv2_*.conf`.
