export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Palette: #fc4c9c #e67eb6 #a73178 #542b5c #4b86a6 (the same as sworkr.com, site/style.css)
        sworkr: {
          50: '#fff0f7',
          100: '#ffd9eb',
          200: '#fbb3d5',
          300: '#f08cc3',
          400: '#e67eb6',
          500: '#fc4c9c',
          600: '#a73178',
          700: '#7d2d69',
          800: '#542b5c',
          900: '#3b1f40',
          accent: '#4b86a6',
        },
        // sworkr.com's warm, plum-tinted greys instead of Tailwind's cool ones, so every text-gray-*,
        // border-gray-* and bg-gray-* in the app matches the site: 200 is its --line, 500 its --muted, 800 its --ink.
        gray: {
          50: '#fff7fb',
          100: '#fbedf4',
          200: '#f1dbe7',
          300: '#dfc6d4',
          400: '#a8919f',
          500: '#6b5d70',
          600: '#5a4c5f',
          700: '#45394b',
          800: '#2b2230',
          900: '#1e1722',
        },
        night: '#3b1f40',   // headings
        ink: '#2b2230',     // text
        muted: '#6b5d70',   // quieter text
        line: '#f1dbe7',    // borders
        blush: '#fff3f8',   // soft backgrounds
      },
    },
  },
  plugins: [],
};
