// The shared breakpoints. Plain CSS cannot read a variable inside a media query, so this
// list is the single source and Stylelint rejects any other width.
//   small phone    up to 400px
//   phone          up to 640px
//   tablet         up to 860px
//   laptop         up to 1100px
//   wide           1280px and up, where an adventure's tabs share the rail
// panel.js matches the phone width for the pinned tab strip, and tests/test_stylelint.py checks it.
export const widths = {smallPhone: 400, phone: 640, tablet: 860, laptop: 1100, wide: 1280}

const steps = [widths.smallPhone, widths.phone, widths.tablet, widths.laptop]
const max = [...steps, widths.wide - 1].map((n) => `${n}px`)
const min = [...steps.map((n) => n + 1), widths.wide].map((n) => `${n}px`)

export default {
  widths,
  allowed: {
    'max-width': max,
    'min-width': min,
    // A phone on its side: short enough that only the tab strip stays pinned.
    'max-height': ['500px'],
  },
}
