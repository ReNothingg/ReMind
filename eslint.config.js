import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'build', '.git', 'public'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  prettier,

  {
    files: ['**/*.{ts,tsx,js,jsx}'],
    settings: {
      react: {
        version: 'detect', // Автоматически определять версию React
      },
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: {
          jsx: true, // Разрешаем JSX
        },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      react: reactPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'no-console': 'off',
      'no-debugger': 'warn',
      'prefer-const': 'warn',
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/ban-ts-comment': 'off',
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      'react/jsx-props-no-spreading': 'off',
      ...reactHooks.configs.recommended.rules,
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
);
