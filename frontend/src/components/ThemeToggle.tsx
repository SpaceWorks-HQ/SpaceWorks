import { useEffect, useState } from "react";
import { readStorage, writeStorage } from "../lib/safeStorage";
import { MoonIcon, SunIcon } from "./icons";
import { IconButton } from "./ui/IconButton";

const THEME_KEY = "makerspace.theme";

function applyTheme(theme: "light" | "dark") {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function ThemeToggle({ variant = "text" }: { variant?: "text" | "icon" }) {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = readStorage(THEME_KEY);
    return stored === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    applyTheme(theme);
    writeStorage(THEME_KEY, theme);
  }, [theme]);

  if (variant === "icon") {
    return (
      <IconButton
        label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
      >
        {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      </IconButton>
    );
  }

  return (
    <button
      className="desk-button"
      type="button"
      onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
