// Two small project rules for the compact one-declaration-per-rule stylesheets.
import stylelint from 'stylelint'

const {createPlugin, utils: {report, ruleMessages}} = stylelint

// The at-rules a declaration sits in, so two rules only clash when they apply in the same context.
function context(node) {
  const parts = []
  for (let parent = node.parent; parent && parent.type !== 'root'; parent = parent.parent) {
    if (parent.type === 'atrule') parts.unshift(`@${parent.name} ${parent.params}`)
  }
  return parts.join(' ')
}

const selectors = (rule) => rule.selector.split(',').map((part) => part.trim().replace(/\s+/g, ' '))

const duplicateName = 'pokesim/no-duplicate-declarations'
const duplicateMessages = ruleMessages(duplicateName, {
  rejected: (property, line) => `"${property}" is set again for every selector here on line ${line} in the same context, so this one is dead code.`,
})
const duplicates = createPlugin(duplicateName, (enabled) => (root, result) => {
  if (!enabled) return
  const latest = new Map()
  const overridden = new Map()
  root.walkDecls((decl) => {
    const rule = decl.parent
    if (rule.type !== 'rule' || decl.prop.startsWith('--')) return
    for (const selector of selectors(rule)) {
      const key = `${context(rule)}|${selector}|${decl.prop}|${decl.important}`
      const earlier = latest.get(key)
      // A repeated property in one block with a different value is a deliberate fallback.
      if (earlier && !(earlier.parent === rule && earlier.value !== decl.value)) {
        if (!overridden.has(earlier)) overridden.set(earlier, {selectors: new Set(), line: decl.source.start.line})
        overridden.get(earlier).selectors.add(selector)
      }
      latest.set(key, decl)
    }
  })
  // Only a declaration overridden for every selector in its list is dead. A group rule
  // that one selector later overrides still does its job for the rest.
  for (const [decl, {selectors: hit, line}] of overridden) {
    if (selectors(decl.parent).every((selector) => hit.has(selector))) {
      report({ruleName: duplicateName, result, node: decl, message: duplicateMessages.rejected(decl.prop, line)})
    }
  }
})
duplicates.ruleName = duplicateName

// Nothing may demand more width than the narrowest supported phone, 320px, unless it only
// applies once the window is wider, a narrower window overrides it, or min() or clamp() caps it.
// Only floors count: the upper end of minmax() and a flex basis that may shrink demand nothing.
const NARROWEST = 320
const fitName = 'pokesim/fits-narrowest-phone'
const fitMessages = ruleMessages(fitName, {
  rejected: (prop, value) => `"${prop}: ${value}" needs more than ${NARROWEST}px. Cap it with min() or clamp(), override it in a max-width query, or set it inside a min-width query.`,
})
const FLOOR = /\bmin-width:\s*(\d+)px/
const CEILING = /\bmax-width:\s*(\d+)px/
const SIZING = /^(width|min-width|inline-size|min-inline-size|flex|grid-template-columns)$/

function widest(prop, value) {
  if (/\b(min|clamp)\(/.test(value)) return 0
  let floors = value.replace(/minmax\(\s*([^,]+),[^)]*\)/g, '$1')
  if (prop === 'flex') {
    const [, shrink = '1', basis = ''] = value.trim().split(/\s+/)
    if (shrink !== '0') return 0
    floors = basis
  }
  const pixels = (text) => [...text.matchAll(/(?<![\w.-])(\d+(?:\.\d+)?)px/g)].map((m) => Number(m[1]))
  if (prop !== 'grid-template-columns') return Math.max(0, ...pixels(floors))
  // Fixed tracks add up, so repeat(3, 200px) demands 600px.
  const repeated = floors.replace(/repeat\(\s*(\d+)\s*,([^)]*)\)/g, (_, count, tracks) => `${tracks} `.repeat(Number(count)))
  return pixels(repeated).reduce((sum, n) => sum + n, 0)
}

function queries(decl) {
  const found = []
  for (let parent = decl.parent; parent && parent.type !== 'root'; parent = parent.parent) {
    if (parent.type === 'atrule' && ['media', 'container'].includes(parent.name)) found.push(parent)
  }
  return found
}

const fits = createPlugin(fitName, (enabled) => (root, result) => {
  if (!enabled) return
  const narrowed = new Set()
  root.walkDecls(SIZING, (decl) => {
    if (decl.parent.type !== 'rule') return
    if (queries(decl).some((query) => query.name === 'media' && CEILING.test(query.params))) {
      for (const selector of selectors(decl.parent)) narrowed.add(`${selector}|${decl.prop}`)
    }
  })
  root.walkDecls(SIZING, (decl) => {
    if (decl.parent.type !== 'rule' || widest(decl.prop, decl.value) <= NARROWEST) return
    const wideOnly = queries(decl).some((query) => {
      const floor = FLOOR.exec(query.params)
      return floor && Number(floor[1]) > NARROWEST
    })
    if (wideOnly || selectors(decl.parent).every((selector) => narrowed.has(`${selector}|${decl.prop}`))) return
    report({ruleName: fitName, result, node: decl, message: fitMessages.rejected(decl.prop, decl.value)})
  })
})
fits.ruleName = fitName

export default [duplicates, fits]
