# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `main` | Yes |
| Older snapshots / forks | No |

## Reporting a Vulnerability

Если вы нашли уязвимость, пожалуйста, не публикуйте ее в открытом issue.

Используйте ответственный процесс раскрытия:

1. Откройте приватный vulnerability report через GitHub Security Advisories (если доступно в репозитории).
2. Если это недоступно, создайте issue с минимальной публичной информацией и пометкой `security`, без proof-of-concept и exploit-деталей.
3. Дождитесь подтверждения от мейнтейнеров перед любым публичным раскрытием.

Что включить в отчет:

- тип и краткое описание уязвимости;
- затронутые файлы/эндпоинты;
- шаги воспроизведения;
- оценка потенциального ущерба;
- возможный вариант исправления (если есть).

## Response Targets

- Первичное подтверждение получения: до 72 часов.
- Предварительная оценка и triage: до 7 календарных дней.
- План исправления: по результатам severity-оценки.

Срок фактического исправления зависит от критичности и сложности изменений.

## Severity Priorities

Наивысший приоритет:

- обход аутентификации/авторизации;
- RCE, SSRF, path traversal, SQL injection;
- утечка персональных данных или секретов;
- CSRF/XSS уязвимости с реальной эксплуатацией.

## Security Best Practices for Contributors

- Не коммитьте секреты (`.env`, ключи, сертификаты).
- Не ослабляйте существующие проверки валидации/CSRF/rate-limit без обоснования.
- Обязательно описывайте security-риск в PR при изменении auth/session/upload logic.

## Interactive Visualization Boundary

Интерактивные визуализации из ответов модели считаются недоверенным кодом. Они должны выполняться только в `iframe` с opaque origin и `sandbox="allow-scripts"`; `allow-same-origin`, формы, popups, top navigation и доступ к устройствам запрещены.

Runtime использует deny-by-default CSP: сетевые API и вложенные frame запрещены, а статические скрипты и шрифты ограничены явным allowlist CDN. В iframe передаются только визуальные настройки ReMind; история чата, профиль, персонализация, cookies, storage, credentials и DOM приложения не передаются.

Сообщение из визуализации не может автоматически запустить новый запрос к модели. Host проверяет `event.source` и уникальный для экземпляра channel id, ограничивает длину данных и показывает пользователю подтверждение перед отправкой follow-up сообщения.

## Python Runner Boundary

Canvas запускает Python только через авторизованный `POST /api/python/execute` с общей CSRF-защитой. Эндпоинт принимает исключительно строку кода до 24 000 символов, не принимает пути к файлам Canvas и не сохраняет артефакты из этого режима; все ограничения изолированного runner-а и пользовательский rate limit остаются обязательными.

Код, сгенерированный моделью, считается полностью недоверенным и никогда не запускается процессом Flask/Celery. Приложение передаёт job через отдельный volume в `python-runner`; runner не подключён ни к одной Docker network, не получает `.env`, database/Redis credentials, Docker socket, host paths или пользовательское хранилище. Root filesystem read-only, `/tmp` одноразовый, `/dev/shm` закрыт, package manager удалён из runtime image.

Trusted supervisor работает отдельно от job UID и перед запуском оставляет дочернему процессу UID/GID `65532`, пустой supplemental-groups list, нулевые effective capabilities и минимальный allowlist environment. Для job применяются wall/CPU/RAM/file/PID/FD/output limits; после каждого запуска supervisor убивает все процессы sandbox UID, включая fork/setsid descendants, и удаляет рабочую директорию. Контейнер дополнительно использует `no-new-privileges`, `cap_drop: ALL`, read-only rootfs, `pids_limit`, memory/CPU quotas и только минимальные capabilities supervisor (`SETUID`, `SETGID`, `KILL`, `CHOWN`, `DAC_OVERRIDE`).

Очередь недоступна job UID. Входы копируются только из уже проверенных upload-файлов текущего запроса. Выходы принимаются только из top-level output directory по allowlist расширений и повторно проверяются приложением по размеру, MIME и структуре изображения/JSON/text перед сохранением. Артефакты становятся доступны только как вложения истории владельца; anonymous tool execution отключён. На пользователя действует отдельный rate limit, одновременно допускается один job, а Telegram и временные чаты не получают сохраняемые артефакты.

Журнал выполнения показывает владельцу чата точный переданный скрипт, но не environment, внутренние пути, stdout/stderr или данные supervisor. Payload имеет ограниченный размер, кодируется как структурированные данные, проверяется по типу/status/id на клиенте и выводится React только как текст внутри `<pre>`, без `dangerouslySetInnerHTML`. Поэтому содержимое скрипта не может стать HTML/JavaScript приложения; журнал сохраняется с теми же правилами доступа, что и ответ чата.

Эта граница реализует defence in depth, но не является доказательством абсолютной безопасности. Production deployment должен регулярно обновлять base image, прогонять vulnerability scans для образа и зависимостей и при повышенной модели угроз размещать runner на отдельном rootless container host или microVM runtime (например, gVisor/Firecracker/Kata), не разделяющем kernel с основным приложением.
