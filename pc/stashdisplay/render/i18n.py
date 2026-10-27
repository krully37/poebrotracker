"""Text drawn on the screen, in English and French, and language-aware number and date formats.

Each French string notes where its wording comes from, so drafts can be told apart:
    GAME   the Path of Exile French client: poedb.tw/fr (extracted from the game) and
           fr.pathofexile.com. Stash = "Réserve", stash tab = "onglet de réserve",
           stack = "ensemble" ("Taille de l'ensemble"), league = "Ligue",
           item = "objet", Divine Orb = "Orbe divin".
    TOOLS  French translations of other PoE tools: PoE-Overlay (src/assets/i18n/french.json)
           and Sidekick (Sidekick.Localization/*.fr.resx): "Prix", "Valeur",
           "Aucune donnée disponible".
    STD    ordinary French conventions (day and month names, "min", "j", "%" spacing).
    DRAFT  no existing source: written for this app, to be reviewed.

Item names stay in English everywhere: they come from WealthyExile and poe.ninja in English.
"""

from datetime import datetime

LANGUAGES = ["en", "fr"]

# French puts a no-break space before "%" and between thousands. Fontin has U+00A0
# but not the thinner U+202F, so U+00A0 it is.
NBSP = " "

GAME, TOOLS, STD, DRAFT = "game", "tools", "std", "draft"

# key: (English, French, source of the French)
TEXT: dict[str, tuple[str, str, str]] = {
    # Metric names: value labels, slot titles, the editor's metric list.
    "metric.total": ("Stash value", "Valeur de la réserve", GAME + "+" + TOOLS),
    "metric.rate": ("Per hour", "Par heure", DRAFT),
    "metric.session": ("Session", "Session", DRAFT),
    "metric.today": ("Today", "Aujourd'hui", DRAFT),
    "metric.best_hour": ("Best hour today", "Meilleure heure du jour", DRAFT),
    "metric.league_gain": ("Since league start", "Depuis le début de la ligue", GAME + "+" + DRAFT),
    "metric.div_price": ("Divine price", "Prix de l'Orbe divin", GAME + "+" + TOOLS),
    # Page header, right side.
    "header.waiting": ("waiting for data", "en attente de données", DRAFT),
    "header.synced_now": ("synced just now", "synchronisé à l'instant", DRAFT),
    "header.synced": ("synced {ago} ago", "synchronisé il y a {ago}", DRAFT),
    "header.stale": ("stale · {ago} ago", "pas à jour · il y a {ago}", DRAFT),
    # Widgets with nothing to show.
    "empty.collecting": ("Collecting data…", "Collecte des données…", DRAFT),
    "empty.no_data": ("No data yet", "Aucune donnée disponible", TOOLS),
    "empty.no_items": ("No items chosen", "Aucun objet choisi", GAME + "+" + DRAFT),
    # Default titles of the list widgets.
    "title.top_items": ("Top stacks", "Meilleurs ensembles", GAME + "+" + DRAFT),
    "title.tab_totals": ("Tabs", "Onglets", GAME),
    "title.item_price": ("Prices", "Prix", TOOLS),
    # Durations and the {synced} placeholder.
    "duration.now": ("now", "à l'instant", STD),
    "duration.minutes": ("{n}m", "{n} min", STD),
    "duration.days": ("{n}d", "{n} j", STD),
    "never": ("never", "jamais", STD),
    # Preset pages (pages.preset). Labels equal to a metric name are left empty there instead.
    "preset.page.total": ("Total", "Total", DRAFT),
    "preset.page.top": ("Top", "Top", DRAFT),
    "preset.page.session": ("Session", "Session", DRAFT),
    "preset.page.league": ("League", "Ligue", GAME),
    "preset.session_gain": ("Session gain", "Gain de la session", DRAFT),
    "preset.divine": ("Divine", "Orbe divin", GAME),
    "preset.best_hour": ("Best hour", "Meilleure heure", DRAFT),
    "preset.total_footer": ("Session {session}  ·  Today {today}  ·  {league}",
                            "Session {session}  ·  Aujourd'hui {today}  ·  {league}", DRAFT),
    "preset.session_sub": ("since {session_since} ({session_duration})",
                           "depuis {session_since} ({session_duration})", DRAFT),
    "preset.session_footer": ("Best hour today {best_hour}  ·  Rate {rate}",
                              "Meilleure heure {best_hour}  ·  Rythme {rate}", DRAFT),
}

DAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}
DAYS_SHORT = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
}
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"],
}
MONTHS_SHORT = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
}


def lang_or_default(lang: str | None) -> str:
    return lang if lang in LANGUAGES else "en"


def t(key: str, lang: str = "en", **values) -> str:
    en, fr, _ = TEXT[key]
    text = fr if lang == "fr" else en
    return text.format(**values) if values else text


def both(key: str) -> dict[str, str]:
    """{"en": ..., "fr": ...}, for the settings page."""
    return {lang: t(key, lang) for lang in LANGUAGES}


def number(text: str, lang: str) -> str:
    """Turn an English-formatted number ("1,180.5") into the language's style ("1 180,5")."""
    if lang != "fr":
        return text
    return text.translate({ord(","): NBSP, ord("."): ","})


def percent(value: float, lang: str) -> str:
    text = f"{value:+.0f}"
    return text + (NBSP + "%" if lang == "fr" else "%")


def long_date(when: datetime, lang: str) -> str:
    """"Tuesday 27 October" / "mardi 27 octobre"."""
    return f"{DAYS[lang][when.weekday()]} {when.day} {MONTHS[lang][when.month - 1]}"


def short_date(when: datetime, lang: str) -> str:
    """"Tue 27 Oct" / "mar. 27 oct."."""
    return f"{DAYS_SHORT[lang][when.weekday()]} {when.day} {MONTHS_SHORT[lang][when.month - 1]}"
