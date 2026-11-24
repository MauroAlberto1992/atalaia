// ESLint flat config: TypeScript rules with type information, plus the
// React hooks rules (effects, dependencies, purity), which catch a class of
// bugs tsc cannot see.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked, reactHooks.configs.flat.recommended],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      // `${n}` with a number is fine and common in UI strings.
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // Style-only: forbids `() => doSomething()` returning void. Off to keep
      // handlers short; it doesn't catch bugs.
      "@typescript-eslint/no-confusing-void-expression": "off",
      // Allow `_name` for values that are intentionally unused (e.g. when
      // destructuring a key out of an object).
      "@typescript-eslint/no-unused-vars": ["error", { varsIgnorePattern: "^_" }],
    },
  },
);
