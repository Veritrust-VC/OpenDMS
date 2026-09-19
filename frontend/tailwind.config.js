/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Fira Sans covers Latvian diacritics (ā ē ī ū ļ ķ ņ ģ š ž č) properly —
        // several otherwise-good UI faces render them as fallback glyphs.
        sans: ['"Fira Sans"', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"Fira Code"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        // Admin-density scale. Base is 14px: this is a desktop workspace, not
        // an article. Line heights are generous to keep dense tables readable.
        '2xs':  ['0.6875rem', { lineHeight: '1rem',     letterSpacing: '0.01em' }],
        xs:     ['0.75rem',   { lineHeight: '1.125rem' }],
        sm:     ['0.8125rem', { lineHeight: '1.25rem' }],
        base:   ['0.875rem',  { lineHeight: '1.375rem' }],
        lg:     ['1rem',      { lineHeight: '1.5rem' }],
        xl:     ['1.1875rem', { lineHeight: '1.625rem', letterSpacing: '-0.01em' }],
        '2xl':  ['1.5rem',    { lineHeight: '1.875rem', letterSpacing: '-0.02em' }],
      },
      colors: {
        // Brand teal, kept from the existing identity and extended into a real
        // scale so states stop being ad-hoc emerald-50/emerald-700 guesses.
        brand: {
          50:'#eefbf6', 100:'#d4f5e8', 200:'#abe9d3', 300:'#74d7b8',
          400:'#3dbd99', 500:'#17a07e', 600:'#0d7c66', 700:'#0c6353',
          800:'#0d4f44', 900:'#0c4139',
        },
        ink: {
          50:'#f7f8f8', 100:'#eef0f1', 200:'#dde1e3', 300:'#c0c7ca',
          400:'#8e989d', 500:'#69747a', 600:'#4f5a60', 700:'#3d464b',
          800:'#2b3236', 900:'#1a1f22',
        },
      },
      borderRadius: { DEFAULT: '6px', md: '8px', lg: '10px', xl: '14px' },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,28,.04), 0 1px 3px rgba(16,24,28,.06)',
        pop:  '0 4px 12px rgba(16,24,28,.08), 0 1px 3px rgba(16,24,28,.06)',
      },
      transitionDuration: { DEFAULT: '160ms' },
    },
  },
  plugins: [],
};
