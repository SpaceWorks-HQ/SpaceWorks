import { useId } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
  legend?: string;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function channelHex(value: number) {
  return Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
}

function rgbFromHex(value: string) {
  const hex = /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000";
  return {
    red: Number.parseInt(hex.slice(1, 3), 16),
    green: Number.parseInt(hex.slice(3, 5), 16),
    blue: Number.parseInt(hex.slice(5, 7), 16),
  };
}

export function PoolColourSwatchControl({ value, onChange, legend = "Display swatch (optional)" }: Props) {
  const id = useId();
  const activeHex = /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : "";
  const pickerHex = activeHex || "#000000";
  const rgb = rgbFromHex(pickerHex);
  const updateChannel = (channel: keyof typeof rgb, next: number) => {
    const updated = { ...rgb, [channel]: next };
    onChange(`#${channelHex(updated.red)}${channelHex(updated.green)}${channelHex(updated.blue)}`);
  };

  return (
    <fieldset className="grid gap-3 rounded-xl border border-line p-3">
      <legend className="eyebrow px-1">{legend}</legend>
      <div className="flex flex-wrap items-end gap-3">
        <label className="eyebrow grid gap-1" htmlFor={`${id}-picker`}>
          Colour picker
          <input
            className={`min-h-11 w-20 cursor-pointer rounded-md border border-line bg-bg p-1 ${focusRing}`}
            id={`${id}-picker`}
            type="color"
            value={pickerHex}
            onChange={(event) => onChange(event.target.value.toLowerCase())}
          />
        </label>
        <output className="min-h-11 content-center font-mono text-sm text-ink" htmlFor={`${id}-picker`}>
          Display hex: {activeHex || "Not set"}
        </output>
        {activeHex ? (
          <button className="desk-button-ghost" type="button" onClick={() => onChange("")}>
            Clear display colour
          </button>
        ) : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {(["red", "green", "blue"] as const).map((channel) => (
          <label className="eyebrow grid gap-1" htmlFor={`${id}-${channel}`} key={channel}>
            {channel.slice(0, 1).toUpperCase()} ({rgb[channel]})
            <input
              aria-label={`${channel} channel`}
              className={`min-h-11 w-full cursor-pointer accent-accent ${focusRing}`}
              id={`${id}-${channel}`}
              max="255"
              min="0"
              type="range"
              value={rgb[channel]}
              onChange={(event) => updateChannel(channel, Number(event.target.value))}
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
