## Product Rules

Every new end-user-visible capability must be adapted for the mobile web interface.

New UI must match the existing visual style of the website.

Do not use gradients in the UI unless the user explicitly asks for gradients in the current request.

## i18n Rule

Every new text must use i18n.

Do not hardcode text in components, screens, buttons, alerts, errors, placeholders, modals, settings, or menus.

Do not add new hardcoded text in these locations. Existing hardcoded text may remain unchanged unless you are modifying that area as part of the current change.

Use the existing i18n structure in the project.

## IOS Rules

ReMind has a web version and an iOS version.

The iOS project is located here: `IOS/`

If `IOS/` does not exist or cannot be updated, stop and report the missing path before proceeding; do not claim the iOS rule has been satisfied.

Any new end-user-visible capability (new screen, button, modal, alert, menu item, setting, or workflow) must be implemented in `IOS/`.