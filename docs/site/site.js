const themeButton = document.querySelector('#theme-toggle')
const colorScheme = matchMedia('(prefers-color-scheme: dark)')
let savedTheme
try {
  savedTheme = localStorage.getItem('adzero-docs-theme')
} catch {
  /* Reading is optional in private browsers. */
}
function updateTheme(theme) {
  document.documentElement.dataset.theme = theme
  themeButton.setAttribute('aria-pressed', String(theme === 'dark'))
  themeButton.setAttribute('aria-label', theme === 'dark' ? '切换到浅色主题' : '切换到深色主题')
}
updateTheme(['light', 'dark'].includes(savedTheme) ? savedTheme : colorScheme.matches ? 'dark' : 'light')
themeButton.addEventListener('click', () => {
  savedTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'
  updateTheme(savedTheme)
  try {
    localStorage.setItem('adzero-docs-theme', savedTheme)
  } catch {
    /* The theme still works without storage. */
  }
})
colorScheme.addEventListener('change', () => {
  if (!savedTheme) updateTheme(colorScheme.matches ? 'dark' : 'light')
})

const menuButton = document.querySelector('#menu-toggle')
const sidebar = document.querySelector('#sidebar')
function closeMenu() {
  sidebar.classList.remove('is-open')
  menuButton.setAttribute('aria-expanded', 'false')
}
menuButton.addEventListener('click', () => {
  const open = sidebar.classList.toggle('is-open')
  menuButton.setAttribute('aria-expanded', String(open))
})
document.addEventListener('click', (event) => {
  if (!sidebar.contains(event.target) && !menuButton.contains(event.target)) closeMenu()
})
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
    closeMenu()
    menuButton.focus()
  }
})

for (const block of document.querySelectorAll('pre')) {
  const code = block.querySelector('code')
  if (!code) continue
  const button = document.createElement('button')
  button.className = 'copy-button'
  button.type = 'button'
  button.textContent = '复制'
  button.setAttribute('aria-label', '复制这段命令或配置')
  button.setAttribute('aria-live', 'polite')
  button.addEventListener('click', async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(code.textContent)
      } else {
        const selection = window.getSelection()
        const range = document.createRange()
        range.selectNodeContents(code)
        selection.removeAllRanges()
        selection.addRange(range)
        if (!document.execCommand('copy')) throw new Error('clipboard unavailable')
        selection.removeAllRanges()
      }
      button.textContent = '已复制'
    } catch {
      button.textContent = '请选中文本复制'
    }
    setTimeout(() => {
      button.textContent = '复制'
    }, 2200)
  })
  block.prepend(button)
}

const dialog = document.querySelector('#search-dialog')
const searchInput = document.querySelector('#search-input')
const results = document.querySelector('#search-results')
const status = document.querySelector('#search-status')
let indexPromise
let searchVersion = 0
function loadIndex() {
  if (!indexPromise) {
    indexPromise = fetch('search-index.json')
      .then((response) => {
        if (!response.ok) throw new Error('search download failed')
        return response.json()
      })
      .catch((error) => {
        indexPromise = undefined
        throw error
      })
  }
  return indexPromise
}
function openSearch() {
  closeMenu()
  if (!dialog.open) dialog.showModal()
  searchInput.focus()
  if (searchInput.value) search()
}
for (const button of document.querySelectorAll('[data-search-open]')) button.addEventListener('click', openSearch)
document.querySelector('#search-close').addEventListener('click', () => dialog.close())
dialog.addEventListener('click', (event) => {
  if (event.target === dialog) {
    const bounds = dialog.getBoundingClientRect()
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    )
      dialog.close()
  }
})
document.addEventListener('keydown', (event) => {
  const editing =
    event.target instanceof HTMLElement &&
    (event.target.isContentEditable || event.target.closest('input,textarea,select'))
  if (
    (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) ||
    (event.key === '/' && !editing && !dialog.open)
  ) {
    event.preventDefault()
    openSearch()
  }
})

function normalize(text) {
  return text.normalize('NFKC').toLowerCase()
}
function tokens(query) {
  const phrases = normalize(query).match(/[\p{L}\p{N}]+/gu) || []
  const pairs = phrases.flatMap((phrase) => {
    const chars = Array.from(phrase)
    return /\p{Script=Han}/u.test(phrase) && chars.length > 2
      ? chars.slice(0, -1).map((char, i) => char + chars[i + 1])
      : [phrase]
  })
  return { phrases, pairs: [...new Set(pairs)] }
}
async function search() {
  const current = ++searchVersion
  const query = searchInput.value.trim()
  results.replaceChildren()
  if (!query) {
    status.textContent = '输入功能名称或问题关键词'
    return
  }
  status.textContent = '正在搜索…'
  try {
    const index = await loadIndex()
    if (current !== searchVersion) return
    const { phrases, pairs } = tokens(query)
    const matches = index
      .map((item) => {
        const title = normalize(`${item.title} ${item.section}`)
        const pageTitle = normalize(item.title)
        const sectionTitle = normalize(item.section)
        const body = normalize(item.text)
        const score =
          phrases.reduce(
            (sum, word) =>
              sum +
              (pageTitle.includes(word) ? 20 : 0) +
              (sectionTitle.includes(word) ? 32 : body.includes(word) ? 10 : 0),
            0,
          ) + pairs.reduce((sum, word) => sum + (title.includes(word) ? 3 : body.includes(word) ? 1 : 0), 0)
        return { item, score }
      })
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
    status.textContent = matches.length
      ? `找到 ${matches.length} 个相关章节`
      : '没有找到结果，试试“订阅”“兼容性”“测试”等更短的关键词。'
    for (const { item } of matches) {
      const link = document.createElement('a')
      link.className = 'search-result'
      link.href = item.url
      const page = document.createElement('small')
      page.textContent = item.title
      const heading = document.createElement('strong')
      heading.textContent = item.section
      const excerpt = document.createElement('p')
      const haystack = normalize(item.text)
      const position = Math.max(0, ...phrases.map((word) => haystack.indexOf(word)).filter((pos) => pos >= 0))
      const start = Math.max(0, position - 25)
      excerpt.textContent =
        (start ? '…' : '') + item.text.slice(start, start + 110) + (item.text.length > start + 110 ? '…' : '')
      link.append(page, heading, excerpt)
      results.append(link)
    }
  } catch {
    if (current === searchVersion) status.textContent = '搜索索引加载失败，请重新输入重试，或使用左侧目录。'
  }
}
searchInput.addEventListener('input', search)
dialog.addEventListener('keydown', (event) => {
  const links = [...results.querySelectorAll('a')]
  const position = links.indexOf(document.activeElement)
  if (event.key === 'ArrowDown' && links.length) {
    event.preventDefault()
    links[(position + 1) % links.length].focus()
  } else if (event.key === 'ArrowUp' && links.length) {
    event.preventDefault()
    if (position <= 0) searchInput.focus()
    else links[position - 1].focus()
  } else if (event.key === 'Enter' && document.activeElement === searchInput && links.length) {
    event.preventDefault()
    links[0].click()
  }
})
