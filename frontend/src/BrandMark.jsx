// Default brand mark, used wherever brand_logo_url is not set.
//
// Replaces the hard-coded letter "D" that stood in for a logo. The mark reads
// as a document whose lower half becomes a decision graph — the document is
// the subject, the branching is what the planner does to it. Kept to a handful
// of thick strokes because it has to stay legible at 28px in the sidebar.
//
// A tenant that sets brand_logo_url still overrides this everywhere.

export default function BrandMark({ size = 28, color = "#0d7c66", className = "" }) {
  const inner = Math.round(size * 0.64);
  return (
    <div
      className={"rounded flex items-center justify-center flex-shrink-0 " + className}
      style={{ background: color, width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" width={inner} height={inner} fill="none"
           stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {/* sheet with a folded corner */}
        <path d="M5.5 21V3h8l5 5v3" />
        <path d="M13 3v5.5h5.5" />
        {/* decision graph growing out of the document */}
        <circle cx="12.5" cy="15" r="1.9" fill="#ffffff" stroke="none" />
        <circle cx="19" cy="19.5" r="1.9" fill="#ffffff" stroke="none" />
        <circle cx="10" cy="20.5" r="1.9" fill="#ffffff" stroke="none" />
        <path d="M14 16.3 17.4 18.6" />
        <path d="M11.7 16.8 10.7 18.7" />
      </svg>
    </div>
  );
}
