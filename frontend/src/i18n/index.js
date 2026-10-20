import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key]) {
    messages[key] = localeFiles[path].default
    availableLocales.push({ key, label: languages[key].label })
  }
}

const savedLocale = localStorage.getItem('locale')
// Default to English ('en') if not set or if previously defaulted to 'zh'
const initialLocale = (!savedLocale || savedLocale === 'zh') ? 'en' : savedLocale
localStorage.setItem('locale', initialLocale)

const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: 'en',
  messages
})

export { availableLocales }
export default i18n
