// Example briefs for the two demo goals (data in the owner's language, not UI strings).
// Must match backend/app/presets.py (preset_brief) and fixtures/briefs.json (same competitors), otherwise the
// designed round-4 outcomes (e.g. the ProteoMax collab counting as a competitor) do not happen.

import type { Brief, Competitor, Lang } from '../types'

export type PresetName = 'bakery' | 'fitness'
export const PRESET_NAMES: PresetName[] = ['bakery', 'fitness']

const BAKERY_COMPETITORS: Competitor[] = [
  { name: 'Pekárna B', handles: ['pekarna_b'] },
  { name: 'Chlebárna Vlnka', handles: ['chlebarna_vlnka'] },
]
const FITNESS_COMPETITORS: Competitor[] = [
  { name: 'FitZone Brno', handles: ['fitzone_brno'] },
  { name: 'ProteoMax', handles: ['proteomax'] },
]

export const PRESETS: Record<PresetName, Record<Lang, Brief>> = {
  fitness: {
    cs: {
      business_type: 'fitness studio',
      city: 'Brno',
      audience: 'lidé v Brně, kteří chtějí začít cvičit',
      goal: 'víc přihlášek na zkušební lekci',
      budget_hint: 'do 30 tisíc Kč',
      competitors: FITNESS_COMPETITORS,
      lang: 'cs',
    },
    en: {
      business_type: 'fitness studio',
      city: 'Brno',
      audience: 'people in Brno who want to start exercising',
      goal: 'more sign-ups for a trial class',
      budget_hint: 'up to CZK 30,000',
      competitors: FITNESS_COMPETITORS,
      lang: 'en',
    },
  },
  bakery: {
    cs: {
      business_type: 'pekárna',
      city: 'Brno',
      audience: 'rodiny a mladí lidé v Brně',
      goal: 'víc lidí v prodejně, představit nový kváskový chléb',
      budget_hint: 'do 20 tisíc Kč',
      competitors: BAKERY_COMPETITORS,
      lang: 'cs',
    },
    en: {
      business_type: 'bakery',
      city: 'Brno',
      audience: 'families and young people in Brno',
      goal: 'more people in the shop, launch a new sourdough bread',
      budget_hint: 'up to CZK 20,000',
      competitors: BAKERY_COMPETITORS,
      lang: 'en',
    },
  },
}

const BAKERY_WORDS = /pek[aá]r|bakery|chleb|bread|cukr[aá]r|pastry|kav[aá]r|caf[eé]/i
const FITNESS_WORDS = /fitness|gym|posilovn|studio|cvi[cč]|workout|yoga|jóga|trenin|tréning/i

/** Which preset a brief is (by business type keywords), or null for any other goal. */
export function presetOf(brief: Brief | null | undefined): PresetName | null {
  const b = `${brief?.business_type ?? ''}`
  if (!b) return null
  if (FITNESS_WORDS.test(b)) return 'fitness'
  if (BAKERY_WORDS.test(b)) return 'bakery'
  return null
}
