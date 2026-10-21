// Layout audit: walks the visible DOM and reports geometry that looks broken.
// The browser tests evaluate this file as one function. It takes
// {allow: [{types, selector}], tapMin, checkTaps} and returns a list of violations,
// each {type, selector, detail, ...measurements}. It never changes the page.
(options) => {
  const {allow = [], tapMin = 40, checkTaps = false, root = null} = options || {}
  const scope = (root && document.querySelector(root)) || document.body
  const SLACK = 1
  const viewport = document.documentElement.clientWidth
  const found = []

  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'BR', 'WBR', 'OPTION', 'OPTGROUP', 'HEAD', 'META', 'LINK',
                             'TITLE', 'NOSCRIPT', 'SOURCE', 'TRACK', 'DATALIST'])
  const styles = new Map()
  const style = (el) => {
    let value = styles.get(el)
    if (!value) { value = getComputedStyle(el); styles.set(el, value) }
    return value
  }
  const round = (n) => Math.round(n * 10) / 10

  function path(el) {
    const parts = []
    for (let node = el; node && node.nodeType === 1 && node !== document.documentElement; node = node.parentElement) {
      if (node.id) { parts.unshift('#' + CSS.escape(node.id)); break }
      let part = node.tagName.toLowerCase()
      const classes = [...node.classList].slice(0, 2).map((name) => '.' + CSS.escape(name)).join('')
      part += classes
      const parent = node.parentElement
      if (parent) {
        const twins = [...parent.children].filter((child) => child.tagName === node.tagName
          && (!classes || child.matches(classes)))
        if (twins.length > 1) part += `:nth-of-type(${[...parent.children].filter((c) => c.tagName === node.tagName).indexOf(node) + 1})`
      }
      parts.unshift(part)
      if (parts.length >= 5) break
    }
    return parts.join(' > ')
  }

  function allowed(type, el) {
    return allow.some((entry) => entry.types.includes(type) && el.matches(entry.selector))
  }

  function report(type, el, detail, extra = {}) {
    if (allowed(type, el)) return
    found.push({type, selector: path(el), detail, ...extra})
  }

  // Hidden things, screen-reader-only text and closed dialogs have no layout to judge.
  function visible(el) {
    if (SKIP_TAGS.has(el.tagName)) return false
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') return false
    if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false
    const box = el.getBoundingClientRect()
    if (box.width <= 1 && box.height <= 1) return false
    const css = style(el)
    if (css.display === 'contents') return false
    if (css.clip === 'rect(0px, 0px, 0px, 0px)' || css.clipPath === 'inset(50%)') return false
    return true
  }

  const out = (css) => css.position === 'absolute' || css.position === 'fixed'
  const clips = (value) => value === 'hidden' || value === 'clip'
  const scrolls = (value) => value === 'auto' || value === 'scroll'

  // The element a child's box is laid out in, stepping through display: contents.
  function layoutParent(el) {
    let parent = el.parentElement
    while (parent && style(parent).display === 'contents') parent = parent.parentElement
    return parent
  }

  function layoutChildren(el) {
    const kids = []
    for (const child of el.children) {
      if (style(child).display === 'contents') kids.push(...layoutChildren(child))
      else kids.push(child)
    }
    return kids
  }

  // The padding box, which is where a clipping parent draws its children.
  function paddingBox(el) {
    const box = el.getBoundingClientRect()
    const css = style(el)
    const left = box.left + parseFloat(css.borderLeftWidth)
    const top = box.top + parseFloat(css.borderTopWidth)
    return {left, top, right: left + el.clientWidth, bottom: top + el.clientHeight}
  }

  // Inside a deliberate scroller, children may run past its edge. That is scrolling, not spilling.
  function insideScroller(el, axis) {
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const css = style(node)
      if (scrolls(axis === 'x' ? css.overflowX : css.overflowY)) return true
    }
    return false
  }

  const all = [...(scope === document.body ? [] : [scope]), ...scope.querySelectorAll('*')].filter(visible)
  const shown = new Set(all)

  // 1. The page itself scrolls sideways.
  const pageWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)
  if (pageWidth > viewport + SLACK) {
    const widest = all.filter((el) => el.getBoundingClientRect().right > viewport + SLACK && !insideScroller(el, 'x'))
      .filter((el) => !all.some((other) => other !== el && el.contains(other) && other.getBoundingClientRect().right > viewport + SLACK
        && !insideScroller(other, 'x')))
      .slice(0, 5).map(path)
    found.push({type: 'page-scroll', selector: 'html', detail: `page is ${pageWidth}px wide in a ${viewport}px window`,
                culprits: widest})
  }

  for (const el of all) {
    const css = style(el)
    const box = el.getBoundingClientRect()
    const parent = layoutParent(el)

    // 2a. A scroller that scrolls sideways without being meant to.
    if (scrolls(css.overflowX) && el.scrollWidth > el.clientWidth + SLACK && el.tagName !== 'TEXTAREA') {
      report('scroller', el, `scrolls sideways: content ${el.scrollWidth}px in ${el.clientWidth}px`,
             {content: el.scrollWidth, client: el.clientWidth})
    }

    // 2b. A child's box runs past its parent: clipped if the parent clips, visibly outside otherwise.
    if (parent && parent !== document.body && shown.has(parent) && !out(css) && css.display !== 'inline') {
      const pcss = style(parent)
      if (pcss.display !== 'inline') {
        const clipX = clips(pcss.overflowX), clipY = clips(pcss.overflowY)
        const frame = clipX || clipY ? paddingBox(parent) : parent.getBoundingClientRect()
        const scrollX = scrolls(pcss.overflowX) || insideScroller(el, 'x')
        const scrollY = scrolls(pcss.overflowY) || insideScroller(el, 'y')
        const spill = {
          left: scrollX ? 0 : frame.left - box.left,
          right: scrollX ? 0 : box.right - frame.right,
          top: scrollY ? 0 : frame.top - box.top,
          bottom: scrollY ? 0 : box.bottom - frame.bottom,
        }
        const sides = Object.entries(spill).filter(([, amount]) => amount > SLACK)
        if (sides.length) {
          const clipped = sides.some(([side]) => side === 'left' || side === 'right' ? clipX : clipY)
          report(clipped ? 'clipped' : 'spill', el,
                 `${clipped ? 'cut off by' : 'runs outside'} ${path(parent)} on the ${sides.map(([s, n]) => `${s} by ${round(n)}px`).join(', ')}`,
                 {box: {x: round(box.left), y: round(box.top), w: round(box.width), h: round(box.height)},
                  parent: {x: round(frame.left), y: round(frame.top), w: round(frame.right - frame.left), h: round(frame.bottom - frame.top)}})
        }
      }
    }

    // 3. Text that does not fit its own box.
    const text = [...el.childNodes].filter((node) => node.nodeType === 3 && node.textContent.trim())
    if (text.length && !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) {
      const ellipsis = css.textOverflow === 'ellipsis'
      const clamped = css.webkitLineClamp && css.webkitLineClamp !== 'none'
      if (!ellipsis && !clamped && el.scrollWidth > el.clientWidth + SLACK && css.display !== 'inline') {
        report('text', el, `text is ${el.scrollWidth}px wide in a ${el.clientWidth}px box`,
               {text: el.textContent.trim().slice(0, 40), content: el.scrollWidth, client: el.clientWidth})
      } else if (!clamped && clips(css.overflowY) && css.display !== 'inline'
                 // Glyph overhang past a tight line height is not lost text. A hidden part of a line is.
                 && el.scrollHeight > el.clientHeight + Math.max(SLACK, parseFloat(css.fontSize) * 0.3)) {
        report('text', el, `text is ${el.scrollHeight}px tall in a ${el.clientHeight}px box`,
               {text: el.textContent.trim().slice(0, 40), content: el.scrollHeight, client: el.clientHeight})
      } else if (!ellipsis && css.display !== 'inline') {
        const range = document.createRange()
        let worst = 0
        for (const node of text) {
          range.selectNodeContents(node)
          for (const line of range.getClientRects()) {
            worst = Math.max(worst, line.right - box.right, box.left - line.left)
          }
        }
        if (worst > SLACK) report('text', el, `text runs ${round(worst)}px outside its box`, {text: el.textContent.trim().slice(0, 40)})
      }
    }

    // Sibling checks run once per container.
    const kids = layoutChildren(el).filter((child) => shown.has(child))
    if (kids.length < 2) continue

    // 4. Siblings in normal flow, grid or flex that sit on top of each other. A sticky header
    // or footer is meant to ride over the content scrolling beneath it, so it is left out.
    const flow = kids.filter((child) => {
      const c = style(child)
      return !out(c) && c.float === 'none' && c.display !== 'inline'
    })
    const stacked = flow.filter((child) => style(child).position !== 'sticky')
    const boxes = flow.map((child) => child.getBoundingClientRect())
    const stackedBoxes = stacked.map((child) => child.getBoundingClientRect())
    for (let i = 0; i < stacked.length; i++) {
      for (let j = i + 1; j < stacked.length; j++) {
        const a = stackedBoxes[i], b = stackedBoxes[j]
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (x > SLACK && y > SLACK && !allowed('overlap', stacked[j])) {
          report('overlap', stacked[i], `overlaps ${path(stacked[j])} by ${round(x)}x${round(y)}px`,
                 {other: path(stacked[j]), overlap: {w: round(x), h: round(y)}})
        }
      }
    }

    // 5. Cards in one grid or flex row that should match but do not. Conservative: only rows of
    // two or more siblings with the same classes in a container that stretches its items.
    const grid = css.display.includes('grid')
    const flexRow = css.display.includes('flex') && css.flexDirection.startsWith('row')
    if ((grid || flexRow) && ['normal', 'stretch'].includes(css.alignItems)) {
      const rows = new Map()
      flow.forEach((child, index) => {
        const c = style(child)
        if (!['auto', 'normal', 'stretch'].includes(c.alignSelf) || !child.className) return
        if (grid && c.gridRowEnd.startsWith('span') && c.gridRowEnd !== 'span 1') return
        const key = Math.round(boxes[index].top) + '|' + child.className
        if (!rows.has(key)) rows.set(key, [])
        rows.get(key).push(child)
      })
      for (const members of rows.values()) {
        if (members.length < 2) continue
        // A plain wrapper stretches, so the card people see is its only visible child.
        const faces = members.map((member) => {
          const inner = layoutChildren(member).filter((child) => shown.has(child))
          const plain = style(member).backgroundColor === 'rgba(0, 0, 0, 0)' && style(member).borderTopWidth === '0px'
          return plain && inner.length === 1 ? inner[0] : member
        })
        const heights = faces.map((face) => face.getBoundingClientRect().height)
        if (Math.max(...heights) - Math.min(...heights) > 2) {
          report('uneven', members[0], `cards in one row are ${heights.map(round).join(', ')}px tall`,
                 {heights: heights.map(round), members: members.length})
        }
      }
    }
  }

  // 6. Tap targets on phones. Links inside running text are exempt, as in WCAG 2.5.8.
  if (checkTaps) {
    const targets = scope.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, summary, '
      + '[role=button], [role=tab], [role=menuitem], [role=link], [role=checkbox], [role=switch]')
    for (const el of targets) {
      if (!visible(el) || el.closest('[inert]')) continue
      let target = el
      // A checkbox or radio is tapped through its whole label.
      if (el.matches('input[type=checkbox], input[type=radio]')) target = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || el
      // A stretched link: an absolute ::after at inset 0 makes the nearest
      // positioned ancestor, often a whole card, the tap target.
      const after = getComputedStyle(el, '::after')
      if (target === el && after.content !== 'none' && after.position === 'absolute'
          && ['top', 'right', 'bottom', 'left'].every((side) => after[side] === '0px')) {
        let host = el.parentElement
        while (host && host !== document.body && style(host).position === 'static') host = host.parentElement
        if (host) target = host
      }
      const box = target.getBoundingClientRect()
      if (el.tagName === 'A' && style(el).display === 'inline') {
        const host = el.parentElement
        const words = [...host.childNodes].some((node) => node !== el && node.nodeType === 3 && node.textContent.trim())
        if (words) continue
      }
      if (box.width < tapMin - 0.5 || box.height < tapMin - 0.5) {
        report('tap', el, `tap target is ${round(box.width)}x${round(box.height)}px, under ${tapMin}x${tapMin}`,
               {w: round(box.width), h: round(box.height)})
      }
    }
  }
  return found
}
