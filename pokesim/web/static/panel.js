// Page chrome for the Bench Instrument pages: the theme switch, and how much of
// the rail stays pinned. Loaded in <head> so the saved theme applies before the
// first paint instead of flashing the system one.
(() => {
  const KEY = 'pokesim-panel-theme'
  const root = document.documentElement
  const read = () => { try { return localStorage.getItem(KEY) } catch (_) { return null } }
  const apply = (theme) => { root.dataset.theme = ['light', 'dark'].includes(theme) ? theme : 'auto' }
  apply(read())

  function wireTheme() {
    const buttons = document.querySelectorAll('[data-theme-choice]')
    const mark = () => buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeChoice === root.dataset.theme)))
    buttons.forEach((button) => button.addEventListener('click', () => {
      apply(button.dataset.themeChoice)
      try { localStorage.setItem(KEY, root.dataset.theme) } catch (_) {}
      mark()
    }))
    mark()
  }

  // On a phone the rail stacks to three rows. Pinning all of it would cost a
  // fifth of the screen, so it sticks at a negative offset that leaves only the
  // tab strip showing. Sticky column headers read --rail-h to sit below it.
  function wireRail() {
    const rail = document.querySelector('.rail')
    // The first nav on a game page is the Library breadcrumb, not the tab strip.
    const nav = rail?.querySelector('nav:not(.breadcrumb)')
    if (!rail || !nav) return
    const measure = () => {
      const stacked = nav.offsetTop > 0 && nav.offsetWidth >= rail.offsetWidth - 1
      const phone = matchMedia('(max-width: 640px)').matches
      const hidden = phone && stacked ? nav.offsetTop : 0
      root.style.setProperty('--rail-top', `${-hidden}px`)
      // 4px is the machined lip under the rail.
      root.style.setProperty('--rail-h', `${rail.offsetHeight - hidden + 4}px`)
    }
    new ResizeObserver(measure).observe(rail)
    addEventListener('resize', measure)
    measure()
  }

  // Portraits come in two sizes: 56px art read from the owner's cartridge, and
  // 96px packs that are usually that same 56px art centred on a bigger canvas.
  // A pack whose drawing stays inside the centred 56px square is scaled as the
  // 56px picture it is, so it is not shown at half size. Either way the scale is
  // the largest whole number that fits the frame, so a pixel is always a square
  // of pixels, and every species keeps its size relative to the others.
  const GB_PORTRAIT = 56
  const spriteCells = new Map()
  function spriteCell(img) {
    const w = img.naturalWidth
    const h = img.naturalHeight
    const natural = Math.max(w, h)
    if (natural <= GB_PORTRAIT) return natural
    if (spriteCells.has(img.src)) return spriteCells.get(img.src)
    let cell = natural
    try {
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const context = canvas.getContext('2d', {willReadFrequently: true})
      context.drawImage(img, 0, 0)
      const alpha = context.getImageData(0, 0, w, h).data
      const left = Math.floor((w - GB_PORTRAIT) / 2)
      const top = Math.floor((h - GB_PORTRAIT) / 2)
      let outside = false
      for (let y = 0; y < h && !outside; y++) for (let x = 0; x < w; x++) {
        if (alpha[(y * w + x) * 4 + 3] < 16) continue
        if (x < left || x >= left + GB_PORTRAIT || y < top || y >= top + GB_PORTRAIT) { outside = true; break }
      }
      if (!outside) cell = GB_PORTRAIT
    } catch (_) {}
    spriteCells.set(img.src, cell)
    return cell
  }
  // A plate can be hidden or still settling its size when its image loads, so
  // each plate is watched and its portrait refitted whenever the plate resizes.
  const plates = new ResizeObserver((entries) => entries.forEach(({target}) => {
    target.querySelectorAll('img').forEach((img) => { if (img.complete) fitSprite(img) })
  }))
  const watched = new WeakSet()
  function fitSprite(img) {
    const frame = img.closest('.plate')
    if (!frame || !img.naturalWidth) return
    if (!watched.has(frame)) { watched.add(frame); plates.observe(frame) }
    if (!frame.clientWidth) return
    const scale = Math.max(1, Math.floor(Math.min(frame.clientWidth, frame.clientHeight) / spriteCell(img)))
    img.style.maxWidth = 'none'
    img.style.maxHeight = 'none'
    img.style.width = `${img.naturalWidth * scale}px`
    img.style.height = `${img.naturalHeight * scale}px`
  }
  function fitSprites(root) {
    root?.querySelectorAll?.('.plate img').forEach((img) => { if (img.complete) fitSprite(img) })
  }
  document.addEventListener('load', (event) => {
    if (event.target instanceof HTMLImageElement) fitSprite(event.target)
  }, true)
  window.Panel = {fitSprite, fitSprites}

  document.addEventListener('DOMContentLoaded', () => { wireTheme(); wireRail() })
})()
