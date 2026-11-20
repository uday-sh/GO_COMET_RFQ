import { signOut } from "./utils/session.js";

document.querySelector("#admin-logout")?.addEventListener("click", () => signOut());
