import { getApps, initializeApp } from "https://www.gstatic.com/firebasejs/11.0.2/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup } from "https://www.gstatic.com/firebasejs/11.0.2/firebase-auth.js";

const faceform = window.Faceform;
const form = document.getElementById("auth-form");
const mode = form?.dataset.authMode;

function nextPage(claimed = 0) {
  const requested = new URLSearchParams(location.search).get("next");
  if (requested && requested.startsWith("/") && !requested.startsWith("//")) return requested;
  if (claimed > 0 || sessionStorage.getItem("faceform_return_after_auth")) {
    sessionStorage.removeItem("faceform_return_after_auth");
    return "/gallery";
  }
  return "/dashboard";
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = document.getElementById("auth-submit");
  const data = new FormData(form);
  const payload = {
    email: String(data.get("email")).trim(),
    password: String(data.get("password")),
  };
  if (mode === "register") payload.name = String(data.get("name")).trim();
  const guestToken = faceform.getGuestToken();
  if (guestToken) payload.guest_token = guestToken;
  submit.disabled = true;
  submit.textContent = mode === "login" ? "Signing you in…" : "Creating your account…";
  try {
    const result = await faceform.api(`/auth/${mode}`, { method: "POST", body: JSON.stringify(payload) });
    faceform.setToken(result.access_token);
    if (result.claimed_generations) faceform.clearGuestToken();
    location.href = nextPage(result.claimed_generations);
  } catch (error) {
    faceform.toast(error.message, "error");
    submit.disabled = false;
    submit.innerHTML = mode === "login" ? "Sign in <span>→</span>" : "Create my account <span>→</span>";
  }
});

document.querySelector(".password-toggle")?.addEventListener("click", (event) => {
  const button = event.currentTarget;
  const password = document.getElementById("auth-password");
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  button.textContent = visible ? "Hide" : "Show";
  button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
});

document.getElementById("google-login")?.addEventListener("click", async (event) => {
  const config = window.FACEFORM?.firebase;
  if (!config) {
    faceform.toast("Google sign-in is not configured yet. Add the Firebase web app values to your environment.", "error");
    return;
  }
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const app = getApps().length ? getApps()[0] : initializeApp(config);
    const result = await signInWithPopup(getAuth(app), new GoogleAuthProvider());
    const idToken = await result.user.getIdToken();
    const guestToken = faceform.getGuestToken();
    const response = await faceform.api("/auth/firebase", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken, ...(guestToken ? { guest_token: guestToken } : {}) }),
    });
    faceform.setToken(response.access_token);
    if (response.claimed_generations) faceform.clearGuestToken();
    location.href = nextPage(response.claimed_generations);
  } catch (error) {
    faceform.toast(error.message, "error");
    button.disabled = false;
  }
});
