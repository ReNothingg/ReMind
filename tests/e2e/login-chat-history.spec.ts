import { expect, test } from '@playwright/test';

async function loginAsE2EUser(page) {
    await page.locator('#guestAuthButtons .guest-login-btn').click();
    await page.fill('#loginEmail', 'e2e@example.com');
    await page.fill('#loginPassword', 'Password1!');

    const loginResponsePromise = page.waitForResponse(
        (response) =>
            response.url().includes('/api/auth/login') && response.request().method() === 'POST'
    );
    await page.locator('.auth-form button[type="submit"]').click();
    const loginResponse = await loginResponsePromise;
    expect(loginResponse.status()).toBe(200);

    await expect(page.locator('#appRail')).toBeVisible();
    await expect(page.locator('#guestAuthButtons')).toHaveCount(0);
}

test('login -> chat -> session history', async ({ page }) => {
    await page.goto('/?model=echo');

    await loginAsE2EUser(page);
    await expect(page.locator('#promptInput')).toBeVisible();

    const message = 'e2e smoke message';
    await page.fill('#promptInput', message);
    await page.click('#sendButton');

    await expect(page.locator('.user-message .message-text').last()).toContainText(message);
    await expect(page.locator('.ai-message .message-text').last()).toContainText(message);

    await page.reload();
    await expect(page.locator('#appRail')).toBeVisible();

    const historyItem = page.locator('#chatHistoryList .chat-history-item').first();
    await expect(historyItem).toBeVisible();
    await expect(historyItem).toContainText('e2e');

    await historyItem.click();
    await expect(page.locator('.user-message .message-text').last()).toContainText(message);
});

test('privacy delete without CSRF is forbidden', async ({ page }) => {
    await page.goto('/');

    await loginAsE2EUser(page);

    const response = await page.request.post('/api/privacy/delete', {
        data: { delete_account: false },
    });

    expect(response.status()).toBe(403);
    const payload = await response.json();
    expect(payload.ok).toBeFalsy();
});
