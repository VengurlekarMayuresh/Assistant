/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        dark: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
        brand: {
          50: '#f4f5ff',
          100: '#ebeeff',
          200: '#dce0ff',
          300: '#c2caff',
          400: '#9da7ff',
          500: '#757cff',
          600: '#5356fa',
          700: '#4140e6',
          800: '#3534bd',
          900: '#2f2e99',
          950: '#1c1b59',
        },
      },
      fontFamily: {
        sans: ['Outfit', 'Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
