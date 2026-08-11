(function () {
  "use strict";

  const firebaseConfig = {
    apiKey: "AIzaSyButgD2N77doaabtGf-uzffjA5Xc4lh_sU",
    authDomain: "nptelportalteam.firebaseapp.com",
    projectId: "nptelportalteam",
    storageBucket: "nptelportalteam.firebasestorage.app",
    messagingSenderId: "574729426785",
    appId: "1:574729426785:web:12c57aa54179167eeb1720"
  };

  const TOOL_URL = "https://01234santhoshprabhu.github.io/Tool/";
  const WATERMARK_URL = "https://01234santhoshprabhu.github.io/NPTEL-Watermark/";
  const ALLOWED_EMAILS = [];
  const $ = id => document.getElementById(id);
  let auth;
  let currentUser;

  function setMessage(text) {
    const el = $("auth-message");
    if (el) el.textContent = text;
  }

  function setError(text) {
    const el = $("auth-error");
    if (el) el.textContent = text || "";
  }

  function setBusy(isBusy) {
    const btn = $("auth-google-btn");
    if (btn) {
      btn.disabled = false;
      btn.setAttribute("aria-busy", isBusy ? "true" : "false");
    }
  }

  function isAllowed(user) {
    if (!user || !user.email) return false;
    if (!ALLOWED_EMAILS.length) return true;
    return ALLOWED_EMAILS.includes(user.email.toLowerCase());
  }

  function showLocked(message) {
    document.body.classList.remove("auth-ready", "auth-chooser");
    document.body.classList.add("auth-locked");
    setMessage(message || "Sign in with your Google account to continue.");
    const pill = $("auth-user-pill");
    if (pill) pill.style.display = "none";
  }

  function showChooser(user) {
    currentUser = user;
    if (localStorage.getItem("nptel_last_app") === "count") {
      showCount();
      return;
    }
    document.body.classList.remove("auth-pending", "auth-locked", "auth-ready");
    document.body.classList.add("auth-chooser");
    setError("");
    const choiceEmail = $("auth-choice-email");
    if (choiceEmail) choiceEmail.textContent = user.email || user.displayName || "Signed in";
  }

  function showCount() {
    if (!currentUser) return;
    document.body.classList.remove("auth-pending", "auth-locked", "auth-chooser");
    document.body.classList.add("auth-ready");
    const email = $("auth-user-email");
    if (email) email.textContent = currentUser.email || currentUser.displayName || "Signed in";
    const pill = $("auth-user-pill");
    if (pill) pill.style.display = "inline-flex";
    window.dispatchEvent(new CustomEvent("nptel-auth-ready", { detail: { user: currentUser } }));
  }

  function googleProvider() {
    const provider = new firebase.auth.GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    return provider;
  }

  async function signIn() {
    if (!auth) {
      setError("Firebase Authentication is still loading. Please try again.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("Choose your Google account in the popup window.");
    try {
      await auth.setPersistence(firebase.auth.Auth.Persistence.LOCAL);
      const result = await auth.signInWithPopup(googleProvider());
      if (!result || !result.user) throw new Error("Google sign-in did not return an account.");
      if (!isAllowed(result.user)) {
        showLocked("This Google account is not approved for this dashboard.");
        setError((result.user.email || "This account") + " is not in the allowed list.");
        await auth.signOut();
        return;
      }
      showChooser(result.user);
    } catch (err) {
      if (err && err.code === "auth/popup-blocked") {
        setError("Chrome blocked the Google popup. Allow pop-ups for this site, then click Sign in again.");
      } else if (err && err.code === "auth/popup-closed-by-user") {
        setError("Google sign-in was closed before finishing. Click Sign in again.");
      } else {
        setError((err && err.message) ? err.message : "Google sign-in failed. Please try again.");
      }
      setMessage("Sign in with your Google account to continue.");
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    if (!auth) return;
    await auth.signOut();
  }

  function initAuth() {
    const signInBtn = $("auth-google-btn");
    const signOutBtn = $("auth-signout-btn");
    const countBtn = $("auth-count-btn");
    const toolBtn = $("auth-tool-btn");
    const watermarkBtn = $("auth-watermark-btn");
    if (signInBtn) signInBtn.addEventListener("click", signIn);
    if (signOutBtn) signOutBtn.addEventListener("click", () => { localStorage.removeItem("nptel_last_app"); signOut(); });
    if (countBtn) countBtn.addEventListener("click", () => { localStorage.setItem("nptel_last_app", "count"); showCount(); });
    if (toolBtn) toolBtn.addEventListener("click", () => { localStorage.setItem("nptel_last_app", "tool"); window.location.href = TOOL_URL; });
    if (watermarkBtn) watermarkBtn.addEventListener("click", () => { localStorage.setItem("nptel_last_app", "watermark"); window.location.href = WATERMARK_URL; });

    if (!window.firebase || !firebase.initializeApp || !firebase.auth) {
      showLocked("Firebase Authentication did not load. Check your internet connection and refresh.");
      setError("Unable to load Firebase Auth SDK.");
      return;
    }

    if (!firebase.apps.length) firebase.initializeApp(firebaseConfig);
    auth = firebase.auth();    auth.onAuthStateChanged(user => {
      setBusy(false);
      if (!user) {
        currentUser = null;
        showLocked("Sign in with your Google account to continue.");
        return;
      }
      if (!isAllowed(user)) {
        showLocked("This Google account is not approved for this dashboard.");
        setError(user.email + " is not in the allowed list.");
        auth.signOut();
        return;
      }
      showChooser(user);
    }, err => {
      showLocked("Authentication check failed. Please refresh and try again.");
      setError(err.message || "Authentication failed.");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initAuth);
  else initAuth();
})();
