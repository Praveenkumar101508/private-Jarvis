import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        saffron: {
          50:  "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          300: "#fdba74",
          400: "#fb923c",
          500: "#f97316",
          600: "#ea580c",
          700: "#c2410c",
          800: "#9a3412",
          900: "#7c2d12",
          950: "#431407",
        },
      },
      boxShadow: {
        // Depth for cards/modals on the dark canvas
        "panel": "0 8px 32px rgba(0, 0, 0, 0.45)",
        // Saffron halo for primary CTAs
        "glow-saffron": "0 4px 24px rgba(249, 115, 22, 0.25)",
      },
      keyframes: {
        "pulse-ring": {
          "0%":   { transform: "scale(1)",   opacity: "0.6" },
          "100%": { transform: "scale(1.8)", opacity: "0"   },
        },
        "float-soft": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-4px)" },
        },
        "cursor-blink": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)"   },
        },
      },
      animation: {
        "pulse-ring":   "pulse-ring 1.5s ease-out infinite",
        "pulse-ring-d": "pulse-ring 1.5s ease-out infinite 0.5s",
        "cursor-blink": "cursor-blink 1s step-end infinite",
        "fade-in":      "fade-in 0.2s ease-out",
        "float-soft":   "float-soft 5s ease-in-out infinite",
      },
    },
  },
  plugins: [
    require("@tailwindcss/typography"),
  ],
};

export default config;
