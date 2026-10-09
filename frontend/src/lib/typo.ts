// Czech typography (ČSN 01 6910) applied at render time, to UI strings and to backend text alike.
// See docs/design/smer-designu.md section 3.3. Only runs for lang === 'cs'.

const NBSP = ' '

/** Instagram business categories arrive in English; in Czech text they are shown in Czech. */
const CATEGORIES: Record<string, string> = {
  'Digital creator': 'digitální tvůrce',
  'Video creator': 'tvůrce videí',
  'Blogger': 'bloger',
  'Personal blog': 'osobní blog',
  'Bakery': 'pekárna',
  'Café': 'kavárna',
  'Cafe': 'kavárna',
  'Coffee shop': 'kavárna',
  'Restaurant': 'restaurace',
  'Brand': 'značka',
  'Gym/Physical Fitness Center': 'posilovna a fitness centrum',
  'Fitness trainer': 'fitness trenér',
  'Fitness Trainer': 'fitness trenér',
  'Sports & recreation': 'sport a rekreace',
  'Athlete': 'sportovec',
  'Public figure': 'veřejná osobnost',
  'Artist': 'umělec',
  'Musician/band': 'hudebník nebo kapela',
  'Photographer': 'fotograf',
  'Chef': 'kuchař',
  'Entrepreneur': 'podnikatel',
  'Local business': 'místní podnik',
  'Community': 'komunita',
  'Product/service': 'produkt nebo služba',
  'Shopping & retail': 'obchod',
  'Health/beauty': 'zdraví a krása',
  'Food & beverage': 'jídlo a pití',
  'Media/news company': 'médium',
  'News & media website': 'zpravodajský web',
  'Education': 'vzdělávání',
  'Gamer': 'hráč',
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
const CAT_RE = new RegExp(
  `(^|„|"|\\(|: |· )(${Object.keys(CATEGORIES)
    .sort((a, b) => b.length - a.length)
    .map(escapeRe)
    .join('|')})(?=“|"|\\)|,|\\.|;| ·|$)`,
  'g',
)

/** Czech plural: 1 / 2–4 / 0 and 5+. */
export function csPlural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one
  if (n >= 2 && n <= 4) return few
  return many
}

export function categoryCs(cat: string | null | undefined): string {
  if (!cat) return ''
  return CATEGORIES[cat] ?? cat
}

/** Small grammar fixes for backend phrases that are known to come out wrong (see section 7 of the
 *  design doc, "Předat backendu"). Harmless when the backend already says it right. */
function fixPhrases(s: string): string {
  return (
    s
      .replace(/(\d+) reels\b/g, (_, n) => `${n} ${csPlural(+n, 'reel', 'reely', 'reelů')}`)
      .replace(/(\d+) fotky\b/g, (_, n) => `${n} ${csPlural(+n, 'fotka', 'fotky', 'fotek')}`)
      .replace(/(\d+) karusely\b/g, (_, n) => `${n} ${csPlural(+n, 'karusel', 'karusely', 'karuselů')}`)
      .replace(/(\d+) videa\b/g, (_, n) => `${n} ${csPlural(+n, 'video', 'videa', 'videí')}`)
      .replace(/nejvýš 0 neoznačených (spoluprac|reklam)\p{L}*/gu, (_, w: string) => (w === 'reklam' ? 'žádná neoznačená reklama' : 'žádná neoznačená spolupráce'))
      // "krátká videa, videa": the same word twice in a row
      .replace(/(^|[\s(])(\p{L}{3,}), \2(?!\p{L})/gu, '$1$2')
      // "žádná spolupráce s: Pekárna B, …": the names cannot be declined here, say what the list is
      .replace(/spolupráce s: /g, 'spolupráce s těmito firmami: ')
      .replace(/\((\d+) analyzováno\)/g, (_, n) => `(analyzováno ${n} ${csPlural(+n, 'komentář', 'komentáře', 'komentářů')})`)
      // spaced hyphen between words is a dash in Czech
      .replace(/(\S) - (\S)/g, '$1 – $2')
      .replace(CAT_RE, (_, pre: string, cat: string) => `${pre}${CATEGORIES[cat] ?? cat}`)
  )
}

/** Non-breaking spaces per ČSN 01 6910. Idempotent. */
export function csTypo(input: string): string {
  if (!input) return input
  let s = fixPhrases(input)
  // single-letter prepositions and conjunctions: k s v z o u a i (any case), also after another one
  s = s.replace(/(^|[\s(„"'[–—/])([ksvzouaiKSVZOUAI]) +/g, `$1$2${NBSP}`)
  // run it twice so "a v Brně" binds both (the first pass consumed the separator)
  s = s.replace(/(^|[\s(„"'[–—/])([ksvzouaiKSVZOUAI]) +/g, `$1$2${NBSP}`)
  // dates: "9. 10. 2026"
  s = s.replace(/(\d{1,2})\. (?=\d)/g, `$1.${NBSP}`)
  // digit groups: "23 400"
  s = s.replace(/(\d) (?=\d{3}(?!\d))/g, `$1${NBSP}`)
  // number and unit / counted word: "65 %", "10 tis.", "30 dní", "5 finalistů"
  s = s.replace(/(\d) (?=[\p{L}%‰€$×])/gu, `$1${NBSP}`)
  // ≥ ≤ and similar operators bind to what follows
  s = s.replace(/([≥≤±~→]) /g, `$1${NBSP}`)
  // "č. 9", "tj. ", short abbreviations before numbers
  s = s.replace(/\b(č|čl|s|str|tel)\. (?=\d)/g, `$1.${NBSP}`)
  return s
}
