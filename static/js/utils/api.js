// Keep the bearer token scoped to this browser tab. Older versions used
// localStorage, which caused a new tab to inherit the previous user's account.
localStorage.removeItem("rfq_token");

export const state = {
  token: sessionStorage.getItem("rfq_token"),
  me: null,
};

export async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    let body = {};
    try {
      body = await response.json();
    } catch {
      // Keep a useful status message when the server response is not JSON.
    }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg || "Invalid value").join("; ")
      : body.detail || `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
