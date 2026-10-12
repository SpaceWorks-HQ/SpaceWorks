import { useSyncExternalStore } from "react";
import { chooseTheme, currentTheme, subscribeTheme } from "../lib/theme";
import { MoonIcon, SunIcon } from "./icons";
import { IconButton } from "./ui/IconButton";

export function ThemeToggle({ variant = "text" }: { variant?: "text" | "icon" }) {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme);

  if (variant === "icon") {
    return (
      <IconButton
        label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        onClick={() => chooseTheme(theme === "dark" ? "light" : "dark")}
      >
        {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      </IconButton>
    );
  }

  return (
    <button
      className="desk-button"
      type="button"
      onClick={() => chooseTheme(theme === "dark" ? "light" : "dark")}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
