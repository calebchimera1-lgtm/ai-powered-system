# Website audit and improvements

Audit of the React web app (every route, as Super Administrator and as Cashier, at
375 px phone, 768 px tablet and 1440 px desktop widths), followed by fixes. Everything below
was checked against the production Docker build (nginx + API + PostgreSQL), not only the dev
server.

## How it was tested

| Check | Tool | Result |
|---|---|---|
| Every route × 2 roles × 3 viewports (198 page loads): horizontal overflow, console errors, failed API calls, dead/empty links, images without `alt`, failed images, unlabelled buttons, placeholder text, footer, page titles, `tel:`/`mailto:` | Playwright audit script | 0 problems after the fixes (see before/after below) |
| Keyboard and mobile-menu behaviour, skip link, logo, 404, titles, footer links, contact links, product thumbnails | Playwright scripted checks (32) | 32 pass |
| Mark-as-read failure path (forced HTTP 500) | Playwright with network interception | error toast shown, button disabled while saving, double-click sends one request |
| Type safety | `tsc -b` | pass |
| Frontend unit/component tests | Vitest | 77 pass |
| Backend tests | pytest (PostgreSQL) | full suite pass, incl. new thumbnail assertions |
| Production build | `vite build` | pass |
| Response headers | `curl` against nginx | security + `X-Robots-Tag` present on HTML, assets and API |

### Before / after (phone, 375 px wide)

| Page | Page width before | After |
|---|---|---|
| Stock adjustments | 705 px | 375 px |
| Users | 520 px | 375 px |
| Expenses | 550 px | 375 px |
| Profit and sales | 512 px | 375 px |
| Categories | 427 px | 375 px |
| Point of sale | 399 px | 375 px |
| Returns | 394 px | 375 px |
| Product detail | 376 px | 375 px |

At 768 px, Stock adjustments (842 px) and Users (847 px) also overflowed; both are now 768 px.

## The 20 tasks

| # | Task | Status | What was done |
|---|---|---|---|
| 1 | Horizontal scrolling | Fixed | Root cause: visually-hidden (`sr-only`) table captions inside scrollable table wrappers escaped to the page and widened it. Scroll wrappers are now `relative`. Grid children get `min-width: 0` so long content can't push columns wider than the screen. |
| 2 | Broken links | Verified, none | No internal link points at a route that doesn't exist; no `href="#"`/empty links. |
| 3 | Mobile navigation | Improved | Drawer closes on navigation and on Escape, traps Tab focus, locks page scroll, returns focus to the menu button; the menu button reports `aria-expanded`/`aria-controls`; larger close/menu tap targets; "Skip to content" link added. |
| 4 | Favicon | Done | Existing SVG favicon kept; added 32 px PNG, Apple touch icon (180 px), 192/512 px icons and a web app manifest, all rendered from the same SVG. |
| 5 | Page titles | Done | Every page sets a unique tab title, "Page · Smart Inventory" (detail pages use the record, e.g. "Receipt RCPT-2026-000001"); shared through `PageHeader`, so new pages get it automatically. The till and the "no access" screen gained a screen-reader `<h1>`. |
| 6 | Meta descriptions | Done | `index.html` has a factual description. This is a sign-in-only staff tool with a single HTML document, so per-page descriptions would never be seen by a search engine. |
| 7 | Footer links | Done | New footer: copyright and links to *My account* and *Notifications* (pages every signed-in user can open). Sign-in screens show the copyright line only. No invented legal or social links. |
| 8 | Custom 404 | Done | Unknown addresses inside the app now show a branded "Page not found" page with *Go to home* and *Go back*, instead of silently redirecting to Home. |
| 9 | Copyright year | Done | Computed from the current date (`new Date().getFullYear()`). |
| 10 | Image compression | Improved | Uploads were already re-encoded to WebP (≤ 800 px, metadata stripped). Added a 160 px WebP thumbnail served for lists and previews (made on first request, so existing photos get one too); `<img>` now has `width`/`height`, `decoding="async"`, and `loading="lazy"` in lists. Measured: 548 KB JPEG upload → 78 KB full WebP → 4.2 KB thumbnail. |
| 11 | Broken buttons | Verified, none | Every button audited has an accessible name and an action; tap targets enlarged where they were under 32 px on phones. |
| 12 | Success messages | Verified | All create/update/delete flows already confirm with a toast or inline message. |
| 13 | Error messages | Fixed one gap | "Mark as read" / "Mark all as read" (page and bell) called the API without handling failure; they now show an error toast and are disabled while saving. All other forms already showed validation and server errors. |
| 14 | Placeholder content | Verified, none | No lorem ipsum / TODO / "coming soon" text on any page. Demo records are already labelled "(Demo)". |
| 15 | Unused navigation | Verified | Every sidebar item leads to a working page and is shown only to roles that can open it. |
| 16 | Mobile overflow | Fixed | See task 1; also the Returns receipt field was collapsing to 19 px tall on phones. |
| 17 | Clickable logo | Done | Sidebar/drawer logo links to Home. |
| 18 | `tel:` links | Done | Supplier and staff phone numbers dial when tapped (shared `PhoneLink`). |
| 19 | `mailto:` links | Done | Staff, account and supplier emails open the mail app (shared `EmailLink`). |
| 20 | Full mobile optimisation | Done | 0 overflowing pages at 375/768/1440 px; tap targets enlarged; reduced-motion respected; first-load JavaScript cut by 64% (below). |

## Additional checks

- **Accessibility:** skip link; focus trap and focus return in the mobile menu; every page has one `<h1>`; images have `alt`; all icon buttons have labels; `prefers-reduced-motion` honoured.
- **SEO / indexing:** this is a private, sign-in-only tool, so it is deliberately kept *out* of search engines: `<meta name="robots" content="noindex, nofollow">`, `robots.txt` disallowing everything, and an `X-Robots-Tag` header from nginx.
- **Performance:** every page is now loaded on demand. First-load JavaScript went from 1,088 KB (305 KB gzipped) to 394 KB (123 KB gzipped); the charting library and barcode scanner download only on pages that use them.
- **Security headers (bug fixed):** nginx drops server-level `add_header` lines in any `location` that sets its own, so HTML pages were being served without `Referrer-Policy` and `Permissions-Policy`. They are now repeated in that block and verified with `curl`.
- **Secrets:** no keys, passwords or tokens in the frontend source or build; the frontend reads no environment variables; `.env` is git-ignored and `.env.example` contains only `CHANGE_ME` placeholders.
- **Console / API:** 0 console errors and 0 failed API requests across all 198 page loads.

## Not done, and why

- **AVIF images:** WebP is already used and supported by every current browser; AVIF would add encode time on upload for a few KB on 4 KB thumbnails.
- **Per-page meta descriptions / structured data:** pages are behind sign-in and marked `noindex`, so search engines never see them.
- **Inline links in tables and sentences** (e.g. receipt numbers) stay text-height; WCAG 2.5.8 exempts inline links, and rows are spaced well apart.
- **No ESLint/Prettier config exists in the frontend**, so no lint step could be run; type checking and tests were.

## Recommendations

1. Add ESLint (with `jsx-a11y`) and Prettier to CI so these checks stay enforced.
2. Run the audit script in CI against the Docker stack to catch layout regressions.
3. Serve the API's `/media` images through nginx's cache (or a CDN) if product photos grow.
4. Consider a service worker for the till so the POS page loads on flaky shop Wi-Fi.
