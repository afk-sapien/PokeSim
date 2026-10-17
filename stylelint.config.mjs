// Correctness checks for the web stylesheets. Formatting rules stay off: the compact
// one-declaration-per-rule style is deliberate and this config never reformats it.
import breakpoints from './tools/stylelint/breakpoints.mjs'
import plugins from './tools/stylelint/plugins.mjs'

export default {
  plugins,
  rules: {
    // Every media query uses one of the shared breakpoints. A one-off width fails here.
    'media-feature-name-value-allowed-list': breakpoints.allowed,
    'media-feature-name-no-unknown': true,
    'property-no-unknown': true,
    'unit-no-unknown': true,
    'color-no-invalid-hex': true,
    'function-calc-no-unspaced-operator': true,
    'declaration-block-no-duplicate-properties': [true, {ignore: ['consecutive-duplicates-with-different-syntaxes']}],
    'declaration-block-no-shorthand-property-overrides': true,
    'selector-pseudo-class-no-unknown': true,
    'selector-pseudo-element-no-unknown': true,
    'selector-type-no-unknown': [true, {ignore: ['custom-elements']}],
    'at-rule-no-unknown': true,
    'block-no-empty': true,
    'no-invalid-double-slash-comments': true,
    'no-invalid-position-at-import-rule': true,
    'string-no-newline': true,
    // The stylesheets repeat a selector once per declaration on purpose, so the plain
    // no-duplicate-selectors rule would flag every line. This one flags the same property
    // set twice for the same selector in the same context, where the first is dead code.
    'pokesim/no-duplicate-declarations': true,
    'pokesim/fits-narrowest-phone': true,
  },
}
