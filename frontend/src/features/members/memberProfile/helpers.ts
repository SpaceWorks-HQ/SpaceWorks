export const tagsToText = (values: string[]) => values.join(", ");
export const textToTags = (value: string) =>
  value.split(",").map((item) => item.trim()).filter(Boolean);

const PROFILE_TONES = [
  "border-accent bg-accent/15",
  "border-secondary bg-secondary/15",
  "border-success bg-success/15",
  "border-warn bg-warn/15",
] as const;

export function profileToneForIdentity(identity: string | number | undefined) {
  if (identity === undefined || identity === "") return "border-secondary bg-secondary/15";
  const total = [...String(identity)].reduce((sum, character) => sum + character.codePointAt(0)!, 0);
  return PROFILE_TONES[total % PROFILE_TONES.length];
}
