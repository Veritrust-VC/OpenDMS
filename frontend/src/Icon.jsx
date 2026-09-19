// Line icons, one consistent set.
//
// Replaces the emoji that were doing icon duty in the sidebar. Emoji render as
// a different picture on every OS, carry colour we don't control, sit on a
// baseline instead of a grid, and cannot inherit the active state — so an
// "active" nav item had a coloured background and a full-colour emoji fighting
// it. These are 24px-grid strokes on currentColor: they inherit, they align,
// and they look the same on Windows, macOS and Linux.
//
// Drawn in the Lucide idiom (1.75 stroke, round caps) for consistency, not
// imported, so the bundle gains nothing and the set stays exactly as large as
// the app needs.

const P = {
  agent: (
    <>
      <rect x="4" y="7.5" width="16" height="12" rx="3" />
      <path d="M12 7.5V4M9.5 13h.01M14.5 13h.01M9.5 16.5h5" />
      <path d="M1.5 12.5v2M22.5 12.5v2" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7.5" height="8" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
      <rect x="3" y="14" width="7.5" height="7" rx="1.5" />
      <rect x="13.5" y="11" width="7.5" height="10" rx="1.5" />
    </>
  ),
  document: (
    <>
      <path d="M6 2.5h7l5 5V21a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 21V3a.5.5 0 0 1 .5-.5z" />
      <path d="M13 2.5V8h5M9.5 13h5M9.5 16.5h5" />
    </>
  ),
  insight: (
    <>
      <path d="M12 3a6 6 0 0 0-3.5 10.9V17h7v-3.1A6 6 0 0 0 12 3z" />
      <path d="M9.5 20h5M10.5 17v3M13.5 17v3" />
    </>
  ),
  process: (
    <>
      <rect x="2.5" y="3" width="7" height="5" rx="1.5" />
      <rect x="14.5" y="3" width="7" height="5" rx="1.5" />
      <rect x="8.5" y="16" width="7" height="5" rx="1.5" />
      <path d="M6 8v3.5h12V8M12 11.5V16" />
    </>
  ),
  plug: (
    <>
      <path d="M9 2.5v5M15 2.5v5" />
      <path d="M6 7.5h12v3a6 6 0 0 1-6 6 6 6 0 0 1-6-6v-3z" />
      <path d="M12 16.5v5" />
    </>
  ),
  prompt: (
    <>
      <path d="M3.5 5.5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5.5 4v-4a2 2 0 0 1 0-.5z" />
      <path d="M8 8.5h8M8 12h5" />
    </>
  ),
  folder: (
    <>
      <path d="M2.5 6.5a2 2 0 0 1 2-2h4l2 2.5h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z" />
    </>
  ),
  tag: (
    <>
      <path d="M3.5 11.2V4.5a1 1 0 0 1 1-1h6.7a1 1 0 0 1 .7.3l8.3 8.3a1 1 0 0 1 0 1.4l-6.7 6.7a1 1 0 0 1-1.4 0L3.8 11.9a1 1 0 0 1-.3-.7z" />
      <path d="M7.8 7.8h.01" />
    </>
  ),
  archive: (
    <>
      <rect x="2.5" y="3.5" width="19" height="5" rx="1.5" />
      <path d="M4.5 8.5V19a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V8.5" />
      <path d="M9.5 12.5h5" />
    </>
  ),
  audit: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.4 15.4 21 21" />
      <path d="M7.8 10.5h5.4M10.5 7.8v5.4" />
    </>
  ),
  building: (
    <>
      <path d="M4 21V5.5a1.5 1.5 0 0 1 1.5-1.5h7A1.5 1.5 0 0 1 14 5.5V21" />
      <path d="M14 10h4.5A1.5 1.5 0 0 1 20 11.5V21" />
      <path d="M2.5 21h19M7.5 8h3M7.5 12h3M7.5 16h3M17 14h.01M17 17.5h.01" />
    </>
  ),
  users: (
    <>
      <circle cx="9.5" cy="8" r="3.5" />
      <path d="M3 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16.5 5.2a3.5 3.5 0 0 1 0 5.6M18 20a6.6 6.6 0 0 0-1.6-4.3" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h10M18 7h2M4 12h2M10 12h10M4 17h8M16 17h4" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="12" r="2" />
      <circle cx="14" cy="17" r="2" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" />
    </>
  ),
  chevron: <path d="M9 5l7 7-7 7" />,
};

export default function Icon({ name, size = 18, className = "", strokeWidth = 1.75 }) {
  const d = P[name];
  if (!d) return null;
  return (
    <svg
      viewBox="0 0 24 24" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
      className={"shrink-0 " + className} aria-hidden="true" focusable="false"
    >
      {d}
    </svg>
  );
}
