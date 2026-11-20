export const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

export const money = (value) =>
  value == null ? "—" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(Number(value));

export const dateTime = (value) =>
  new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export const dateOnly = (value) =>
  value ? new Date(`${value}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : "Date not set";

export const statusLabel = (value) => String(value || "").replaceAll("_", " ");
