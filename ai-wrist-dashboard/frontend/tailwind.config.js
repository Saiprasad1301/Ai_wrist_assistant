/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        dashboard: "#070b1d",
        panel: "#11142f",
        surface: "#080d22",
        line: "#27304f"
      }
    }
  },
  plugins: []
};
