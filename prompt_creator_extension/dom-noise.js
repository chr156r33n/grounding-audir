/**
 * Chrome-injected noise selectors for boilerplate chrome.
 *
 * Prefer exact class tokens / specific prefixes over bare substring matches.
 * Substring rules like [class*="sidebar"], [class*="newsletter"], and
 * [class*="header"] false-positive on WordPress `no-sidebar`, Substack
 * `newsletter-post`, and `post-header`, discarding the whole article.
 */
export const NOISE_SELECTOR_PARTS = [
  "script",
  "style",
  "noscript",
  "svg",
  "nav",
  "footer",
  "form",
  "header",
  "aside",
  "dialog",
  "[hidden]",
  '[aria-hidden="true"]',
  '[role="navigation"]',
  '[role="banner"]',
  '[role="contentinfo"]',
  '[role="dialog"]',
  '[class*="breadcrumb" i]',
  '[class~="cookie" i]',
  '[class*="cookie-" i]',
  '[class*="cookies" i]',
  '[class~="consent" i]',
  '[class*="consent-" i]',
  '[class~="footer" i]',
  '[class*="site-footer" i]',
  '[class*="page-footer" i]',
  '[class~="header" i]',
  '[class*="site-header" i]',
  '[class*="page-header" i]',
  '[class*="global-header" i]',
  '[class~="menu" i]',
  '[class*="menu-" i]',
  '[class~="modal" i]',
  '[class*="modal-" i]',
  '[class*="nav-" i]',
  '[class~="navigation" i]',
  '[class*="navigation-" i]',
  '[class~="newsletter" i]',
  '[class*="newsletter-signup" i]',
  '[class*="newsletter-form" i]',
  '[class*="newsletter-widget" i]',
  '[class~="sidebar" i]',
  '[class*="sidebar-" i]',
  '[class~="social" i]',
  '[class*="social-" i]',
  '[class*="socialShare" i]',
  '[id~="cookie" i]',
  '[id*="cookie-" i]',
  '[id~="consent" i]',
  '[id*="consent-" i]',
  '[id~="footer" i]',
  '[id*="footer-" i]',
  '[id~="menu" i]',
  '[id*="menu-" i]',
  '[id~="navigation" i]',
  '[id*="navigation-" i]',
  '[id~="sidebar" i]',
  '[id*="sidebar-" i]',
];

export const NOISE_SELECTOR = NOISE_SELECTOR_PARTS.join(",");

/** True if a space-separated class list should be treated as page chrome. */
export function classListLooksLikeNoise(className) {
  const tokens = String(className || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => token.toLowerCase());
  if (!tokens.length) return false;

  const exact = new Set([
    "cookie",
    "cookies",
    "consent",
    "footer",
    "header",
    "menu",
    "modal",
    "navigation",
    "newsletter",
    "sidebar",
    "social",
  ]);
  if (tokens.some((token) => exact.has(token))) return true;

  const prefixes = [
    "breadcrumb",
    "cookie-",
    "consent-",
    "site-footer",
    "page-footer",
    "site-header",
    "page-header",
    "global-header",
    "menu-",
    "modal-",
    "nav-",
    "navigation-",
    "newsletter-signup",
    "newsletter-form",
    "newsletter-widget",
    "sidebar-",
    "social-",
  ];
  if (
    tokens.some((token) =>
      prefixes.some((prefix) => token.includes(prefix.toLowerCase())),
    )
  ) {
    return true;
  }
  if (tokens.some((token) => token.includes("socialshare"))) return true;
  return false;
}
