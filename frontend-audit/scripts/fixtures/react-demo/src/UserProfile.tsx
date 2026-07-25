import React, { useEffect } from "react";
import { sanitize } from "dompurify";

// SEC-REACT-001: non-literal __html from props (XSS)
export function UserProfile({ bio }: { bio: string }) {
  return <div dangerouslySetInnerHTML={{ __html: bio }} />;
}

// SEC-REACT-001 (safe variant): value passed through a recognized sanitizer.
// The regex tier suppresses this finding because sanitize() is a known净化点.
export function SafeProfile({ bio }: { bio: string }) {
  return <div dangerouslySetInnerHTML={{ __html: sanitize(bio) }} />;
}

// SEC-JS-001: eval with non-literal
export function runDynamic(code: string) {
  return eval(code);
}

// SEC-JS-003: innerHTML from non-literal
export function setHtml(el: HTMLElement, html: string) {
  el.innerHTML = html;
}

// SEC-JS-004: open redirect
export function redirect(url: string) {
  window.location = url;
}

// RELI-JS-001: async callback passed to useEffect
export function useAsyncEffect() {
  useEffect(async () => {
    await fetch("/api");
  }, []);
}

// RELI-JS-002: addEventListener without removeEventListener
export function attach(el: Element) {
  el.addEventListener("click", () => {});
}

// SEC-SECRET-001: hardcoded AWS key
const AWS_KEY = "AKIAIOSFODNN7EXAMPLE";

// SEC-SECRET-002: hardcoded GitHub token
const GH_TOKEN = "ghp_0123456789abcdefghij0123456789abcdefghij";
