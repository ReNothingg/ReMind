import { expect, test } from '@playwright/test';

test('login -> chat -> session history', async ({ page }) => {
    await page.goto('/');

    await page.locator('#guestAuthButtons .guest-login-btn').click();
    await page.fill('#loginEmail', 'e2e@example.com');
    await page.fill('#loginPassword', 'Password1!');
    await page.locator('.auth-form button[type="submit"]').click();

    await expect(page.locator('#promptInput')).toBeVisible();

    await page.locator('.model-btn-trigger').first().click();
    await page.locator('.model-option-name', { hasText: 'Echo' }).click();

    const message = 'e2e smoke message';
    await page.fill('#promptInput', message);
    await page.click('#sendButton');

    await expect(page.locator('.user-message .message-text').last()).toContainText(message);
    await expect(page.locator('.ai-message .message-text').last()).toContainText(message);

    const historyItem = page.locator('#chatHistoryList .chat-history-item').first();
    await expect(historyItem).toBeVisible();
    await expect(historyItem).toContainText('e2e');

    await historyItem.click();
    await expect(page.locator('.user-message .message-text').last()).toContainText(message);
});

test('privacy delete without CSRF is forbidden', async ({ page }) => {
    await page.goto('/');

    await page.locator('#guestAuthButtons .guest-login-btn').click();
    await page.fill('#loginEmail', 'e2e@example.com');
    await page.fill('#loginPassword', 'Password1!');
    await page.locator('.auth-form button[type="submit"]').click();

    await expect(page.locator('#promptInput')).toBeVisible();

    const response = await page.request.post('/api/privacy/delete', {
        data: { delete_account: false },
    });

    expect(response.status()).toBe(403);
    const payload = await response.json();
    expect(payload.ok).toBeFalsy();
});
