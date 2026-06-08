// Flat ESLint config (ESLint 9+/10) for the SUBSIDE React portal.
//
// `npm run lint` catches what `vite build` does not: unused vars/imports, broken
// hook deps, and accidental non-component exports that defeat React Fast Refresh.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  { ignores: ['dist/**', '.vite/**', 'node_modules/**', 'public/**'] },

  // App source: browser runtime, JSX, React hooks + Fast Refresh rules.
  {
    files: ['src/**/*.{js,jsx}'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      // The two classic hook checks. We deliberately do NOT pull in
      // react-hooks v7's `recommended-latest`, whose React-Compiler-era rules
      // (set-state-in-effect, purity, …) flag working patterns this app relies
      // on. Revisit if/when we adopt the compiler.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Ignore intentionally-unused caps/underscore identifiers (e.g. unused
      // imported components kept for clarity, or `_` throwaways). ignoreRestSiblings
      // allows the destructure-to-omit pattern (`const { drop, ...rest } = props`).
      'no-unused-vars': ['error', {
        varsIgnorePattern: '^[A-Z_]',
        argsIgnorePattern: '^_',
        ignoreRestSiblings: true,
      }],
    },
  },

  // Build/tooling config files run under Node.
  {
    files: ['*.config.js', 'eslint.config.js'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.node,
    },
  },
]
