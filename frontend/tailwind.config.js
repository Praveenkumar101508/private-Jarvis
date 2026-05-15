/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ira: {
          saffron: "#FF9933",
          green: "#138808",
          navy: "#000080",
          warm: "#FFF5E6",
          accent: "#E8671A",
        },
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans", "sans-serif"],
        devanagari: ["Noto Sans Devanagari", "sans-serif"],
      },
    },
  },
  plugins: [],
};
