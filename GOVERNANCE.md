# Governance

Этот документ описывает модель управления проектом ReMind.

## Roles

### Maintainers

Мейнтейнеры:

- принимают архитектурные и продуктовые решения;
- проводят code review и принимают/отклоняют PR;
- управляют релизами, security triage и roadmap;
- поддерживают качество документации и процессов.

### Contributors

Контрибьюторы:

- предлагают изменения через issues/PR;
- следуют `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`;
- участвуют в обсуждениях решений и улучшений.

## Decision Making

Принципы принятия решений:

1. Security first.
2. Backward compatibility by default.
3. Документируемые решения лучше неявных.
4. Пользовательская ценность важнее внутренней сложности.

Для спорных изменений используется процесс:

1. Описание проблемы в issue.
2. Предложение решения и trade-offs.
3. Обсуждение с мейнтейнерами.
4. Финальное решение через PR + review.

## Change Categories

- Minor: локальные исправления без влияния на публичный контракт.
- Moderate: изменения поведения API/UI без breaking changes.
- Major: breaking changes, security model changes, migration-required changes.

Для `Major` изменений требуется явная пометка в PR и запись в changelog.

## Security and Escalation

- Security-инциденты обрабатываются приоритетно по `SECURITY.md`.
- Публичное раскрытие уязвимостей до исправления не допускается.

## Inactive Maintainer Policy

Если мейнтейнер недоступен длительное время, активные мейнтейнеры могут перераспределить обязанности по review/release/security triage.
