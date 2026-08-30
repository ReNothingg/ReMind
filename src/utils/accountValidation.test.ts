import { describe, expect, it, vi } from 'vitest';

import {
    getAccountPasswordRequirements,
    getAccountPasswordStrength,
    localizeAccountError,
    validateAccountPassword,
} from './accountValidation';

const t = vi.fn((key: string) => key);

describe('account password validation', () => {
    it('rejects a long mixed-case password when it has no special character', () => {
        expect(getAccountPasswordRequirements('PashaSob2009')).toEqual({
            hasMinimumLength: true,
            hasDigit: true,
            hasSpecialCharacter: false,
        });
        expect(validateAccountPassword('PashaSob2009', t)).toBe(
            'authModal.messages.passwordSpecialRequired'
        );
        expect(getAccountPasswordStrength('PashaSob2009')).toEqual({
            score: 1,
            level: 'weak',
        });
    });

    it('accepts a password that meets every server registration requirement', () => {
        expect(validateAccountPassword('PashaSob2009!', t)).toBeUndefined();
    });

    it('localizes password validation errors returned by the server', () => {
        expect(localizeAccountError(
            'Password must contain at least one special character',
            'password',
            t
        )).toEqual({
            fieldErrors: { password: 'authModal.messages.passwordSpecialRequired' },
            message: 'authModal.messages.passwordSpecialRequired',
        });
    });
});
