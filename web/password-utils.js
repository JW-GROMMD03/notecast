// Shared helpers for every auth page: a dependency-free password strength
// meter, a show/hide toggle, and inline confirm-password matching. Kept
// in one file so login/signup/reset all look and behave identically.

const COMMON_PASSWORDS = new Set([
  "password", "12345678", "123456789", "qwerty123", "password1",
  "letmein123", "welcome123", "iloveyou1", "admin1234", "changeme",
]);

/** Returns {score: 0-4, label, hint}. Deliberately simple (length +
- character-class variety + a small denylist) rather than a full
- zxcvbn-style model — good enough to nudge students toward a decent
- password without shipping a large JS dependency for it. */
export function scorePassword(pw) {
  if (!pw) return { score: 0, label: "", hint: "" };
  if (COMMON_PASSWORDS.has(pw.toLowerCase())) {
    return { score: 0, label: "Too common", hint: "That's one of the most-used passwords — pick something more unique." };
  }

  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  score = Math.min(score, 4);

  const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"];
  const hints = [
    "At least 8 characters, please.",
    "Try adding a number or symbol.",
    "Getting there — mix upper and lower case too.",
    "Solid password.",
    "Great password.",
  ];
  return { score, label: labels[score], hint: hints[score] };
}

/** Wires a password <input>, a meter <div> (containing a .bar child),
- and a label <span> to update live as the user types. */
export function wireStrengthMeter(inputEl, barEl, labelEl) {
  const update = () => {
    const { score, label } = scorePassword(inputEl.value);
    const pct = inputEl.value ? (score / 4) * 100 : 0;
    barEl.style.width = `${pct}%`;
    barEl.dataset.level = String(score);
    labelEl.textContent = inputEl.value ? label : "";
  };
  inputEl.addEventListener("input", update);
  update();
}

/** Wires a show/hide toggle button next to a password input. */
export function wireVisibilityToggle(inputEl, toggleEl) {
  toggleEl.addEventListener("click", () => {
    const showing = inputEl.type === "text";
    inputEl.type = showing ? "password" : "text";
    toggleEl.textContent = showing ? "Show" : "Hide";
    toggleEl.setAttribute("aria-label", showing ? "Show password" : "Hide password");
  });
}

/** Wires live "passwords match" validation between a password input and
- a confirm-password input, showing/hiding an error element. */
export function wireConfirmMatch(pwEl, confirmEl, errorEl) {
  const update = () => {
    const mismatch = confirmEl.value.length > 0 && confirmEl.value !== pwEl.value;
    errorEl.classList.toggle("hidden", !mismatch);
  };
  pwEl.addEventListener("input", update);
  confirmEl.addEventListener("input", update);
}

export function passwordsAreValid(pw) {
  return pw.length >= 8;
}