// Explicit opt-in projection only, never a persisted QueryClient or API cache.
const key = `spaceworks.member-card:${location.pathname.replace(/\/$/, "")}`;
const panel = document.getElementById("card");
try {
  const card = JSON.parse(localStorage.getItem(key) || "null");
  if (card && typeof card.name === "string" && typeof card.qr === "string" && typeof card.savedAt === "string") {
    panel.replaceChildren();
    for (const text of [card.space, card.name, `Card ${card.number}`, `Last checked ${new Date(card.savedAt).toLocaleString()}`]) {
      const paragraph = document.createElement("p"); paragraph.textContent = text; panel.append(paragraph);
    }
    if (card.qr.startsWith("data:image/png;base64,")) {
      const image = document.createElement("img"); image.src = card.qr; image.alt = "Last-known member card QR; staff must verify online"; panel.append(image);
    }
  }
} catch { /* Unavailable storage leaves the useful empty state. */ }
document.getElementById("forget").onclick = () => {
  try { localStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
  panel.textContent = "Saved card forgotten.";
};
document.getElementById("retry").onclick = () => location.reload();
// Logout or an account switch in another tab must also erase the displayed copy.
window.addEventListener("storage", event => {
  if (event.key === null || event.key === key || event.key === "spaceworks.offline-card-owner") {
    panel.textContent = "Saved card changed or forgotten. Connect to check your account again.";
  }
});
