/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary:   '#6366f1',
        secondary: '#0ea5e9',
        // Brand background tones (3 tiers only — see BRAND.md)
        'bg-base':     '#0B0B14',
        'bg-surface':  '#131321',
        'bg-elevated': '#1A1A2E',
      },
      fontFamily: {
        display: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
