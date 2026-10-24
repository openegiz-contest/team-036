# OpenPit Twin — цифровой двойник открытого карьера

Проект конкурса OpenEgiz: цифровой двойник карьера для диспетчеризации шести самосвалов, балансировки двух экскаваторов и сокращения ожидания. Объекты представлены двойниками Eclipse Ditto; телеметрия идёт по штатному пути OpenEgiz через MQTT.

## Требования

- Ubuntu 22.04/24.04 или другая поддерживаемая Linux-среда
- Docker Engine с Compose v2, `git`, `make`
- Не менее 6 ГБ памяти Docker
- Свободные порты платформы (в частности Grafana 3000, MQTT 1883 и Ditto API 8080)

## Запуск с нуля

Из корня репозитория:

```bash
sudo apt update
sudo apt install -y make
make openpit-twin
```

Первый запуск скачивает образы и собирает сервисы, поэтому может занять несколько минут. Команда запускает платформу OpenEgiz, создаёт двойники и включает симулятор и дашборд.

В конце откройте адрес Grafana, напечатанный командой (обычно `http://localhost:3000`). Логин `admin`; пароль указан в выводе `make up`. Затем перейдите в **Dashboards → OpenEgiz Examples → OpenPit Twin — Dispatch Control**. Живая пространственная схема доступна по адресу `http://localhost:8091/`. Сами объекты доступны в приложении **OpenEgiz → Twins**.

## Сценарии «что если»

По умолчанию используется обычный режим. Для проверки сценариев остановите только симулятор и запустите его с нужной переменной:

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/docker-compose.yml -f team/openpit/compose.yml stop openpit-simulator
OPENPIT_SCENARIO=road_closure docker compose --env-file deploy/compose/.env -f deploy/compose/docker-compose.yml -f team/openpit/compose.yml up -d --force-recreate openpit-simulator
```

Варианты `OPENPIT_SCENARIO`: `normal`, `road_closure`, `excavator_failure`. Вернуть обычный режим — повторить команду запуска с `OPENPIT_SCENARIO=normal`.

## Проверка

```bash
make ps
make smoke
docker compose --env-file deploy/compose/.env -f deploy/compose/docker-compose.yml -f team/openpit/compose.yml logs --tail=100 openpit-simulator
```

Остановить платформу и удалить данные можно командой `make clean`. Она удаляет локальные данные платформы и пароли — используйте осторожно.

## Архитектура

`team/openpit/twins.json` → `setup_twins.py` → Eclipse Ditto; `simulator.py` → MQTT → Ditto → Telegraf → InfluxDB → Grafana. `scene.py` читает актуальные двойники через Ditto API и отображает пространственную схему карьера. Симуляция использует синтетические параметры и предназначена для демонстрации, а не для реального управления техникой.

Дополнительное описание и ограничения — в `SUBMISSION.md`.
