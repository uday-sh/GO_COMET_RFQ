export async function signOut({ redirect = "/" } = {}) {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } finally {
    sessionStorage.removeItem("rfq_token");
    window.location.assign(redirect);
  }
}
