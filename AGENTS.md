# Product Rules

Every new end-user-visible capability must be adapted for the mobile web interface.

New UI must match the existing visual style of the website.

**Do not use gradients and shadow in the UI** unless the user explicitly asks for gradients or other in the current request.

# i18n Rule

**Every new text must use i18n.**

Do not hardcode text in components, screens, buttons, alerts, errors, placeholders, modals, settings, or menus.

Do not add new hardcoded text in these locations. Existing hardcoded text may remain unchanged unless you are modifying that area as part of the current change.

Use the existing i18n structure in the project.

# Platforms Rule

Any new end-user-visible capability must be implemented in all platforms.

If some platfor does not exist or cannot be updated in project, stop and report the missing path before proceeding; do not claim the iOS rule has been satisfied.

## IOS Rules

ReMind has iOS version. The project is located here: `IOS/`

## MacOS Rules

ReMind has macos version **by WebView**. The project is located here: `macos/`.