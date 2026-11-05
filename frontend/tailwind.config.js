/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: "#172033",
        violet: {
          50: "#f5f3ff",
          600: "#7c3aed",
          700: "#6d28d9"
        }
      }
    }
  },
  plugins: []
};

