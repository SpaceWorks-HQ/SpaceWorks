// Explicit opt-in projection only, never a persisted QueryClient or API cache.
const key = `spaceworks.member-card:${location.pathname.replace(/\/$/, "")}`;
const panel = document.getElementById("card");
const loansKey = `spaceworks.member-loans:${location.pathname.replace(/\/$/, "")}`;
const loansPanel = document.getElementById("loans");
try {
  const snapshot = JSON.parse(localStorage.getItem(loansKey) || "null");
  if (snapshot && snapshot.owner && snapshot.owner === localStorage.getItem("spaceworks.offline-card-owner") && Array.isArray(snapshot.loans) && snapshot.loans.length <= 200 && Number.isFinite(Date.parse(snapshot.savedAt))) {
    loansPanel.replaceChildren();
    const checked = document.createElement("p"); checked.textContent = `Last saved ${new Date(snapshot.savedAt).toLocaleString()}`; loansPanel.append(checked);
    const list = document.createElement("ul");
    for (const loan of snapshot.loans) {
      if (typeof loan.label !== "string" || !Number.isFinite(Date.parse(loan.checked_out_at)) || (loan.due_at !== null && !Number.isFinite(Date.parse(loan.due_at)))) continue;
      const item = document.createElement("li"); item.textContent = `${loan.label} · ${loan.due_at ? `Due ${new Date(loan.due_at).toLocaleString()}` : "No due date"}`; list.append(item);
    }
    loansPanel.append(list);
    if (!snapshot.loans.length) { const empty = document.createElement("p"); empty.textContent = "No active loans at the last check."; loansPanel.append(empty); }
  }
} catch { /* Disabled or corrupt local storage keeps the empty state. */ }
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
  try { localStorage.removeItem(key); localStorage.removeItem(loansKey); } catch { /* Storage may be disabled. */ }
  panel.textContent = "Saved card forgotten.";
  loansPanel.textContent = "Saved loans forgotten.";
};
document.getElementById("retry").onclick = () => location.reload();
// Logout or an account switch in another tab must also erase the displayed copy.
window.addEventListener("storage", event => {
  if (event.key === null || event.key === key || event.key === loansKey || event.key === "spaceworks.offline-card-owner") {
    panel.textContent = "Saved card changed or forgotten. Connect to check your account again.";
    loansPanel.textContent = "Saved loans changed or forgotten. Connect to check your account again.";
  }
});
