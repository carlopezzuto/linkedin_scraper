"""Person/Profile scraper for LinkedIn.

Rewritten 2026-03-13: switched from CSS class selectors
to innerText-based extraction. LinkedIn now uses obfuscated
hash class names that change every deploy, making CSS
selectors unreliable. Text structure (h2 headings, newline-
delimited fields) is stable.
"""

import logging
import re
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import Page

from .base import BaseScraper
from ..models import (
    Person,
    Experience,
    Education,
    Accomplishment,
    Interest,
    Contact,
)
from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError
from ..core.throttle import ThrottleConfig

logger = logging.getLogger(__name__)

# --- Parsing patterns ---

# Language-agnostic date range:
# Matches "<word>[.] <year> - <word>[.] <year>"
# or "<word>[.] <year> - <present-equivalent>"
# Works for any language (Jan/janv/Gen/ene/etc.)
_DATE_RE = re.compile(
    r"\S+\.?\s+(?:19|20)\d{2}\s*[-–]\s*"
    r"(?:\S+\.?\s+(?:19|20)\d{2}|\S+)",
)

# Year-only range for education: "2019 - 2021"
# Multi-language "Present" equivalents
_YEAR_RANGE_RE = re.compile(
    r"^\d{4}\s*[-–]\s*(?:\d{4}|\S+)$"
)

# Standalone duration: "2 yrs 3 mos" or multi-language
# EN: yr/yrs/mo/mos, FR: an/ans/mois,
# DE: Jahr/Jahre/Monat/Monate,
# ES: año/años/mes/meses, IT: anno/anni/mese/mesi,
# NL: jr/mnd, SV: år/mån
_DURATION_RE = re.compile(
    r"^(?:\d+\s*(?:yr|yrs|mo|mos"
    r"|an|ans|mois"
    r"|Jahr|Jahre|Monat|Monate"
    r"|año|años|mes|meses"
    r"|anno|anni|mese|mesi"
    r"|jr|mnd"
    r"|år|mån"
    r")\s*)+$",
    re.IGNORECASE,
)

_EMPLOYMENT_TYPES = frozenset(
    {
        # EN
        "Full-time", "Part-time", "Contract",
        "Self-employed", "Freelance", "Internship",
        "Temporary", "Apprenticeship", "Seasonal",
        # FR
        "Temps plein", "Temps partiel", "Contrat",
        "Indépendant", "Freelance", "Stage",
        "Intérimaire", "Apprentissage", "Saisonnier",
        # DE
        "Vollzeit", "Teilzeit", "Vertrag",
        "Selbstständig", "Freiberuflich", "Praktikum",
        "Zeitarbeit", "Ausbildung",
        # ES
        "Jornada completa", "Media jornada", "Contrato",
        "Autónomo", "Freelance", "Prácticas",
        "Temporal", "Aprendizaje",
        # IT
        "Tempo pieno", "Part-time", "Contratto",
        "Lavoratore autonomo", "Freelance", "Stage",
        "Temporaneo", "Apprendistato",
        # NL
        "Voltijd", "Deeltijd", "Contract",
        "Zelfstandig", "Freelance", "Stage",
        "Tijdelijk",
        # SV
        "Heltid", "Deltid", "Kontrakt",
        "Egenföretagare", "Frilans", "Praktik",
        # FR abbreviations
        "CDD", "CDI",
        # PT
        "Tempo integral", "Meio período",
    }
)

# Lines to ignore when parsing section text
_NOISE_PHRASES = frozenset(
    {
        "… more",
        "see more",
        "show all",
        "show credentials",
        "show certificate",
    }
)


class PersonScraper(BaseScraper):
    """Async scraper for LinkedIn person profiles.

    Uses innerText parsing for resilience against
    LinkedIn DOM class name changes.
    """

    def __init__(
        self,
        page: Page,
        callback: Optional[ProgressCallback] = None,
        throttle_config: Optional[ThrottleConfig] = None,
    ):
        super().__init__(
            page, callback or SilentCallback(), throttle_config
        )

    async def scrape(self, linkedin_url: str) -> Person:
        """Scrape a LinkedIn person profile.

        Navigates to the main profile, then to detail
        sub-pages for experience, education, accomplishments,
        and contact info.
        """
        await self.callback.on_start("person", linkedin_url)

        try:
            await self.navigate_and_wait(linkedin_url)
            await self.callback.on_progress(
                "Navigated to profile", 10
            )
            await self.ensure_logged_in()
            # AIDEV-NOTE: 10s wait for main element to appear
            await self.page.wait_for_selector(
                "main", timeout=10000
            )
            await self.wait_and_focus(1)

            name, location = (
                await self._get_name_and_location()
            )
            await self.callback.on_progress(
                f"Got name: {name}", 20
            )

            open_to_work = await self._check_open_to_work()
            about = await self._get_about()
            await self.callback.on_progress(
                "Got about section", 30
            )

            experiences = await self._get_experiences(
                linkedin_url
            )
            await self.callback.on_progress(
                f"Got {len(experiences)} experiences", 50
            )

            educations = await self._get_educations(
                linkedin_url
            )
            await self.callback.on_progress(
                f"Got {len(educations)} educations", 60
            )

            accomplishments = (
                await self._get_accomplishments(linkedin_url)
            )
            await self.callback.on_progress(
                f"Got {len(accomplishments)} accomplishments",
                80,
            )

            contacts = await self._get_contacts(
                linkedin_url
            )
            await self.callback.on_progress(
                f"Got {len(contacts)} contacts", 90
            )

            # Interests skipped: low value, fragile tabs
            interests: list[Interest] = []

            person = Person(
                linkedin_url=linkedin_url,
                name=name,
                location=location,
                about=about,
                open_to_work=open_to_work,
                experiences=experiences,
                educations=educations,
                interests=interests,
                accomplishments=accomplishments,
                contacts=contacts,
            )

            await self.callback.on_progress(
                "Scraping complete", 100
            )
            await self.callback.on_complete("person", person)
            return person

        except Exception as e:
            await self.callback.on_error(e)
            raise ScrapingError(
                f"Failed to scrape person profile: {e}"
            )

    # --------------------------------------------------
    # Header: name, location, open-to-work
    # --------------------------------------------------

    async def _get_name_and_location(
        self,
    ) -> tuple[str, Optional[str]]:
        """Extract name and location from main text.

        LinkedIn renders: line 0 = name, line 1 = headline,
        line 2 = location. But the headline can span multiple
        lines, so location follows "Contact info" or ends
        before a separator.
        """
        try:
            lines = await self.page.evaluate(
                """() => {
                    const m = document.querySelector(
                        'main');
                    if (!m) return [];
                    return m.innerText.split('\\n')
                        .map(l => l.trim())
                        .filter(l => l.length > 0)
                        .slice(0, 15);
                }"""
            )

            name = lines[0] if lines else "Unknown"

            # Find location: the line right before
            # "Contact info" or "·"
            location = None
            for idx, line in enumerate(lines[1:], 1):
                if line in ("Contact info", "·"):
                    # Location is the line before this
                    location = lines[idx - 1]
                    # Don't use name or headline as loc
                    if location == name:
                        location = None
                    break

            # Fallback: line 2 if short enough
            if not location and len(lines) > 2:
                candidate = lines[2]
                # AIDEV-NOTE: 80 char heuristic for location
                if len(candidate) < 80:
                    location = candidate

            if not name or name == "Unknown":
                title = await self.page.title()
                if " | LinkedIn" in title:
                    name = title.split(
                        " | LinkedIn"
                    )[0].strip()

            return name, location

        except Exception as e:
            logger.warning(
                f"Error getting name/location: {e}"
            )
            return "Unknown", None

    async def _check_open_to_work(self) -> bool:
        """Check main page text for open-to-work badge.

        Multi-language: checks EN/ES/FR/DE/IT/NL variants
        and the language-neutral #OPEN_TO_WORK hashtag.
        """
        try:
            text = await self.page.locator(
                "main"
            ).inner_text()
            upper = text.upper()
            badges = [
                "OPEN TO WORK",
                "#OPEN_TO_WORK",
                "DISPONIBLE",
                "DISPONIBILE",
                "OUVERT AUX OPPORTUNITÉS",
                "OFFEN FÜR",
                "BESCHIKBAAR",
            ]
            return any(b in upper for b in badges)
        except Exception:
            return False

    # --------------------------------------------------
    # About
    # --------------------------------------------------

    async def _get_about(self) -> Optional[str]:
        """Extract about section via h2 anchor.

        Multi-language: matches About/Acerca de/Info/
        Informazioni/Over/etc. Walks up to find container
        with substantial text.
        """
        try:
            return await self.page.evaluate(
                """() => {
                    // Multi-language about headings
                    const aboutSet = new Set([
                        'About', 'Acerca de', 'Info',
                        'Infos', 'Informazioni',
                        'Over', 'Über',
                        'Extracto', 'Résumé', 'Profil',
                        'Sommario',
                    ]);
                    const h2s = document.querySelectorAll(
                        'h2');
                    let aboutH2 = null;
                    let aboutText = '';
                    for (const h of h2s) {
                        const ht = h.innerText.trim();
                        if (!aboutSet.has(ht)) continue;
                        aboutH2 = h;
                        aboutText = ht;
                        break;
                    }
                    if (!aboutH2) return null;

                    // Walk up to find section container
                    let box = aboutH2;
                    for (let d = 0; d < 8; d++) {
                        box = box.parentElement;
                        if (!box) break;
                        const t = box.innerText || '';
                        if (t.length < 100) continue;
                        const lines = t.split('\\n')
                            .map(l => l.trim())
                            .filter(l => l.length > 0);
                        const idx = lines.findIndex(
                            l => aboutSet.has(l));
                        if (idx < 0) continue;

                        // Multi-language section stops
                        const stop = new Set([
                            'Top skills',
                            'Principales compétences',
                            'Wichtigste Kenntnisse',
                            'Competencias principales',
                            'Competenze principali',
                            'Belangrijkste vaardigheden',
                            'Featured', 'Destacados',
                            'À la une', 'Im Fokus',
                            'In evidenza', 'Uitgelicht',
                            'Activity', 'Actividad',
                            'Activité', 'Aktivitäten',
                            'Attività', 'Activiteit',
                            'Experience', 'Experiencia',
                            'Expérience', 'Berufserfahrung',
                            'Esperienza', 'Ervaring',
                            'Education', 'Educación',
                            'Formation', 'Ausbildung',
                            'Formazione', 'Opleiding',
                            'Suggested for you',
                            'Sugerencias para ti',
                            'Suggestions pour vous',
                            'Vorschläge für Sie',
                            'Analytics', 'Estadísticas',
                            'Analyse', 'Statistiken',
                        ]);
                        const rest = [];
                        for (let k = idx + 1;
                            k < lines.length; k++) {
                            const ln = lines[k];
                            if (stop.has(ln)) break;
                            if (ln === '\\u2026 more'
                                || ln === 'see more'
                                || ln === '\\u2026see more'
                                || ln === 'Show more'
                                || ln === 'Más información'
                                || ln === 'Voir plus'
                                || ln === 'Mehr anzeigen'
                                || ln === 'Mostra altro'
                                || ln === 'Meer weergeven')
                                continue;
                            rest.push(ln);
                        }
                        if (rest.length > 0)
                            return rest.join('\\n');
                    }
                    return null;
                }"""
            )
        except Exception as e:
            logger.debug(f"Error getting about: {e}")
            return None

    # --------------------------------------------------
    # Experiences
    # --------------------------------------------------

    async def _get_experiences(
        self, base_url: str
    ) -> list[Experience]:
        """Navigate to /details/experience/ and parse."""
        try:
            exp_url = urljoin(
                base_url, "details/experience/"
            )
            await self.navigate_and_wait(exp_url)
            # AIDEV-NOTE: 10s timeout for main selector
            await self.page.wait_for_selector(
                "main", timeout=10000
            )
            await self.wait_and_focus(1.5)
            await self.scroll_page_to_bottom(
                pause_time=0.5, max_scrolls=5
            )

            text = await self.page.locator(
                "main"
            ).inner_text()
            return self._parse_experience_text(text)

        except Exception as e:
            logger.warning(
                f"Error getting experiences: {e}"
            )
            return []

    def _parse_experience_text(
        self, text: str
    ) -> list[Experience]:
        """Parse structured text into Experience objects.

        Entry patterns:
        - Simple: Title, Company · Type, Date · Dur, Loc
        - Grouped: Company, Duration, Loc, then nested
          positions (Title, Type, Date · Dur, Loc, Desc)
        """
        lines = _clean_lines(text)
        # Strip page header (multi-language)
        exp_headers = {
            "experience",
            "berufserfahrung",
            "expérience",
            "esperienza",
            "experiencia",
            "ervaring",
            "erfarenhet",
            "experiência",
        }
        if lines and lines[0].lower() in exp_headers:
            lines = lines[1:]

        experiences: list[Experience] = []
        company_group: Optional[str] = None
        i = 0

        while i < len(lines):
            line = lines[i]

            # Date range line = entry anchor
            if _DATE_RE.search(line):
                exp, skip_to = self._build_experience(
                    lines, i, company_group
                )
                if exp:
                    experiences.append(exp)
                i = skip_to
                continue

            # Company group: line followed by duration
            if (
                i + 1 < len(lines)
                and _DURATION_RE.match(lines[i + 1])
                and not _DATE_RE.search(line)
            ):
                raw = line.split(" · ")[0].strip()
                company_group = raw if raw else line
                i += 1  # skip duration line

            i += 1

        return experiences

    def _build_experience(
        self,
        lines: list[str],
        date_idx: int,
        company_group: Optional[str],
    ) -> tuple[Optional[Experience], int]:
        """Build one Experience from a date-range line.

        Returns (Experience, next_index_to_process).
        """
        date_str, duration = _split_date_duration(
            lines[date_idx]
        )
        from_date, to_date = _split_date_range(date_str)

        position = None
        company = None

        # Walk backward up to 4 lines for context
        # AIDEV-NOTE: 4 is max lookback for position info
        j = date_idx - 1
        while j >= 0 and (date_idx - j) <= 4:
            prev = lines[j]
            if _DATE_RE.search(prev):
                break
            if prev in _EMPLOYMENT_TYPES:
                pass  # Skip employment type lines
            elif " · " in prev and not company:
                parts = prev.split(" · ", 1)
                company = parts[0].strip()
            elif _DURATION_RE.match(prev):
                break
            elif not position:
                position = prev
                break
            j -= 1

        if not company and company_group:
            company = company_group

        # Walk forward for location + description
        location = None
        desc_parts: list[str] = []
        # AIDEV-NOTE: 60 chars max for location heuristic
        loc_max = 60
        k = date_idx + 1
        while k < len(lines):
            nxt = lines[k]
            if _is_entry_boundary(nxt, lines, k):
                break
            if not location and len(nxt) < loc_max:
                location = nxt
            elif len(nxt) > 20:
                desc_parts.append(nxt)
            k += 1

        desc = (
            "\n".join(desc_parts) if desc_parts else None
        )

        exp = Experience(
            position_title=position or "",
            institution_name=company or "",
            linkedin_url=None,
            from_date=from_date,
            to_date=to_date,
            duration=duration,
            location=location,
            description=desc,
        )
        return exp, k

    # --------------------------------------------------
    # Education
    # --------------------------------------------------

    async def _get_educations(
        self, base_url: str
    ) -> list[Education]:
        """Navigate to /details/education/ and parse."""
        try:
            edu_url = urljoin(
                base_url, "details/education/"
            )
            await self.navigate_and_wait(edu_url)
            # AIDEV-NOTE: 10s timeout for main selector
            await self.page.wait_for_selector(
                "main", timeout=10000
            )
            await self.wait_and_focus(1.5)

            text = await self.page.locator(
                "main"
            ).inner_text()
            return self._parse_education_text(text)

        except Exception as e:
            logger.warning(
                f"Error getting educations: {e}"
            )
            return []

    def _parse_education_text(
        self, text: str
    ) -> list[Education]:
        """Parse education entries from page text.

        Handles two patterns:
        - With dates: Institution, Degree, Date range
        - Without dates: Institution, Degree only
        """
        lines = _clean_lines(text)
        # Strip page header (multi-language)
        edu_headers = {
            "education",
            "ausbildung",
            "formation",
            "formazione",
            "educación",
            "opleiding",
            "utbildning",
            "educação",
        }
        if lines and lines[0].lower() in edu_headers:
            lines = lines[1:]

        # Trim footer noise
        lines = _trim_at_noise(lines)

        educations: list[Education] = []

        # First pass: date-anchored entries
        used_lines: set[int] = set()
        for i, line in enumerate(lines):
            is_date = (
                _DATE_RE.search(line)
                or _YEAR_RANGE_RE.match(line)
            )
            if is_date:
                edu = self._build_education_from_date(
                    lines, i
                )
                if edu:
                    educations.append(edu)
                    # Mark used lines
                    for k in range(max(0, i - 2), i + 1):
                        used_lines.add(k)

        # Second pass: entries without dates
        if not educations and lines:
            educations = self._build_education_no_dates(
                lines
            )

        return educations

    def _build_education_from_date(
        self, lines: list[str], date_idx: int
    ) -> Optional[Education]:
        """Build Education from a date line."""
        raw = lines[date_idx].split("·")[0].strip()
        from_date, to_date = _split_date_range(raw)

        institution = None
        degree = None

        j = date_idx - 1
        while j >= 0 and (date_idx - j) <= 3:
            prev = lines[j]
            if (
                _DATE_RE.search(prev)
                or _YEAR_RANGE_RE.match(prev)
            ):
                break
            if not degree:
                degree = prev
            elif not institution:
                institution = prev
                break
            j -= 1

        if degree and not institution:
            institution = degree
            degree = None

        description = None
        k = date_idx + 1
        if k < len(lines):
            nxt = lines[k]
            if (
                not _DATE_RE.search(nxt)
                and not _YEAR_RANGE_RE.match(nxt)
                and len(nxt) > 30
            ):
                description = nxt

        return Education(
            institution_name=institution or "",
            degree=degree,
            linkedin_url=None,
            from_date=from_date,
            to_date=to_date,
            description=description,
        )

    def _build_education_no_dates(
        self, lines: list[str]
    ) -> list[Education]:
        """Build Education entries without date ranges.

        Handles profiles where education has no dates.
        Pattern: Institution name, then degree/field.
        """
        results: list[Education] = []
        i = 0
        while i < len(lines):
            institution = lines[i]
            # AIDEV-NOTE: 150 char cap = reasonable name
            if len(institution) > 150:
                i += 1
                continue

            degree = None
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if not _is_footer_line(nxt):
                    degree = nxt
                    i += 2
                else:
                    i += 1
            else:
                i += 1

            results.append(
                Education(
                    institution_name=institution,
                    degree=degree,
                    linkedin_url=None,
                    from_date=None,
                    to_date=None,
                    description=None,
                )
            )
        return results

    # --------------------------------------------------
    # Accomplishments
    # --------------------------------------------------

    async def _get_accomplishments(
        self, base_url: str
    ) -> list[Accomplishment]:
        """Navigate to each /details/{section}/ page."""
        accomplishments: list[Accomplishment] = []

        sections = [
            ("certifications", "certification"),
            ("honors", "honor"),
            ("publications", "publication"),
            ("patents", "patent"),
            ("courses", "course"),
            ("projects", "project"),
            ("languages", "language"),
            ("organizations", "organization"),
        ]

        for url_path, category in sections:
            try:
                url = urljoin(
                    base_url, f"details/{url_path}/"
                )
                await self.navigate_and_wait(url)
                # AIDEV-NOTE: 10s timeout for main
                await self.page.wait_for_selector(
                    "main", timeout=10000
                )
                await self.wait_and_focus(1)

                text = await self.page.locator(
                    "main"
                ).inner_text()

                # Multi-language empty page check
                empty = [
                    "Nothing to see for now",
                    "No hay nada que ver",
                    "Niets te zien",
                    "Nichts zu sehen",
                    "Rien à voir",
                    "Niente da vedere",
                    "Noch keine Informationen",
                    "Keine Informationen",
                    "Pas d'informations",
                    "Geen informatie",
                    "Inget att visa",
                ]
                if any(e in text for e in empty):
                    continue

                items = self._parse_accomplishment_text(
                    text, category, url_path
                )
                accomplishments.extend(items)

            except Exception as e:
                logger.debug(
                    f"Error getting {category}s: {e}"
                )

        return accomplishments

    def _parse_accomplishment_text(
        self, text: str, category: str, section: str
    ) -> list[Accomplishment]:
        """Parse accomplishment entries from page text."""
        lines = _clean_lines(text)

        # Strip header line (multi-language)
        headers = {
            section.lower(),
            section.capitalize().lower(),
            "licenses & certifications",
            "lizenzen & zertifizierungen",
            "licences et certifications",
            "licenze e certificazioni",
            "licenties en certificeringen",
            "licencias y certificaciones",
            "licenser och certifikat",
            "certyfikaty i licencje",
            "patente",
            "kurse",
            "cursussen",
            "cours",
            "cursos",
            "corsi",
            "kurser",
            "projekte",
            "projets",
            "progetti",
            "proyectos",
            "sprachen",
            "langues",
            "lingue",
            "idiomas",
            "talen",
            "organisationen",
            "organisaties",
            "organisations",
            "organizzazioni",
            "organizaciones",
            "projecten",
        }
        if lines and lines[0].lower() in headers:
            lines = lines[1:]

        # Trim noise after main content
        lines = _trim_at_noise(lines)

        if category == "language":
            return self._parse_languages(lines)
        return self._parse_generic_accomplishments(
            lines, category
        )

    def _parse_languages(
        self, lines: list[str]
    ) -> list[Accomplishment]:
        """Parse language entries: name then proficiency."""
        results: list[Accomplishment] = []
        i = 0
        while i < len(lines):
            title = lines[i]
            proficiency = None
            if i + 1 < len(lines) and _is_proficiency(
                lines[i + 1]
            ):
                proficiency = lines[i + 1]
                i += 2
            else:
                i += 1

            # AIDEV-NOTE: 100 char cap filters noise lines
            if title and len(title) < 100:
                results.append(
                    Accomplishment(
                        category="language",
                        title=title,
                        issuer=proficiency,
                        issued_date=None,
                        credential_id=None,
                        credential_url=None,
                    )
                )
        return results

    def _parse_generic_accomplishments(
        self, lines: list[str], category: str
    ) -> list[Accomplishment]:
        """Parse cert/honor/pub/etc entries.

        Language-agnostic: uses structural patterns to
        detect noise lines (credential IDs, issued dates,
        UI buttons) rather than hardcoded translations.
        """
        results: list[Accomplishment] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Skip noise lines
            if _is_accomplishment_noise(line):
                i += 1
                continue

            # This line is a potential title
            title = line
            issuer = None
            issued_date = None

            # Scan forward for metadata (max 6 lines)
            j = i + 1
            while j < len(lines) and (j - i) <= 6:
                meta = lines[j]
                # Extract date from "Issued ..." lines
                # before noise check skips them
                if _has_month_name(meta) and not issued_date:
                    issued_date = re.sub(
                        r"^(?:Issued|Émise|Utfärdad"
                        r"|Ausgegeben|Emitido"
                        r"|Rilasciato|Uitgegeven"
                        r"|Member)"
                        r"\s*(?:le\s+|el\s+|·\s*)?",
                        "", meta,
                    ).strip()
                    j += 1
                    continue
                if _is_accomplishment_noise(meta):
                    j += 1
                    continue
                # Non-noise, non-date line
                if not issuer and len(meta) < 100:
                    # First = issuer
                    issuer = meta
                    j += 1
                    continue
                # Already have issuer: this is the next
                # entry's title. Stop consuming.
                break

            # Only add if title doesn't look like noise
            if len(title) >= 3:
                results.append(
                    Accomplishment(
                        category=category,
                        title=title,
                        issuer=issuer,
                        issued_date=issued_date,
                        credential_id=None,
                        credential_url=None,
                    )
                )
            i = j if j > i + 1 else i + 1

        return results

    # --------------------------------------------------
    # Contacts
    # --------------------------------------------------

    async def _get_contacts(
        self, base_url: str
    ) -> list[Contact]:
        """Extract contacts from overlay dialog text."""
        contacts: list[Contact] = []

        try:
            url = urljoin(
                base_url, "overlay/contact-info/"
            )
            await self.navigate_and_wait(url)
            await self.wait_and_focus(1)

            dialog = self.page.locator(
                'dialog, [role="dialog"]'
            ).first
            if await dialog.count() == 0:
                logger.warning("Contact dialog not found")
                return contacts

            links_data = await dialog.evaluate(
                """el => Array.from(
                    el.querySelectorAll('a')
                ).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || '').trim(),
                }))"""
            )

            dialog_text = await dialog.inner_text()

            contacts.extend(
                self._parse_contact_links(links_data)
            )
            contacts.extend(
                self._parse_contact_text(dialog_text)
            )

        except Exception as e:
            logger.warning(f"Error getting contacts: {e}")

        return contacts

    def _parse_contact_links(
        self, links: list[dict]
    ) -> list[Contact]:
        """Map dialog links to Contact objects."""
        results: list[Contact] = []
        for link in links:
            href = link.get("href", "")
            text = link.get("text", "")
            if not href or not text:
                continue
            if "edit" in href.lower():
                continue

            if "linkedin.com/in/" in href:
                results.append(
                    Contact(
                        type="linkedin",
                        value=href,
                        label=None,
                    )
                )
            elif "mailto:" in href:
                results.append(
                    Contact(
                        type="email",
                        value=href.replace("mailto:", ""),
                        label=None,
                    )
                )
            elif "twitter.com" in href or "x.com" in href:
                results.append(
                    Contact(
                        type="twitter",
                        value=text,
                        label=None,
                    )
                )
            elif href.startswith("http"):
                # Generic website link
                label = None
                if "(" in text and ")" in text:
                    label = text.split("(")[1].rstrip(")")
                    text = text.split("(")[0].strip()
                results.append(
                    Contact(
                        type="website",
                        value=text,
                        label=label,
                    )
                )
        return results

    def _parse_contact_text(
        self, text: str
    ) -> list[Contact]:
        """Parse non-link contacts from dialog text."""
        results: list[Contact] = []
        text_lines = [
            ln.strip()
            for ln in text.split("\n")
            if ln.strip()
        ]

        # Map section headings to contact types
        section_map = {
            "birthday": "birthday",
            "phone": "phone",
            "address": "address",
            "verjaardag": "birthday",
            "telefoon": "phone",
            "adres": "address",
            "geburtstag": "birthday",
            "telefon": "phone",
            "adresse": "address",
        }

        for idx, raw_line in enumerate(text_lines):
            lower = raw_line.lower()
            for keyword, ctype in section_map.items():
                if lower == keyword:
                    if idx + 1 < len(text_lines):
                        val = text_lines[idx + 1]
                        # Skip if it's another heading
                        if (
                            val
                            and val.lower()
                            not in section_map
                            and "edit" not in val.lower()
                        ):
                            results.append(
                                Contact(
                                    type=ctype,
                                    value=val,
                                    label=None,
                                )
                            )
                    break

        return results


# --------------------------------------------------
# Module-level helpers
# --------------------------------------------------


def _clean_lines(text: str) -> list[str]:
    """Split text into non-empty, trimmed lines."""
    return [
        line.strip()
        for line in text.split("\n")
        if line.strip()
        and line.strip().lower() not in _NOISE_PHRASES
    ]


def _trim_at_noise(lines: list[str]) -> list[str]:
    """Cut lines at footer/sidebar noise."""
    result = []
    _skip = {
        "show credential",
        "show more",
        "afficher le diplôme",
        "zertifikat anzeigen",
        "nachweis anzeigen",
        "mostra credenziale",
        "mostrar credencial",
        "certificering weergeven",
    }
    for line in lines:
        if _is_footer_line(line):
            break
        if line.lower() in _skip:
            continue
        result.append(line)
    return result


# Regex for credential ID lines (any language).
# Matches: "Credential ID xxx", "Identifiant du
# diplôme : xxx", "Legitimerings-ID xxx", etc.
# Structure: 1-3 words + colon/space + alphanumeric ID
_CREDENTIAL_ID_RE = re.compile(
    r"^.{0,40}\b(?:ID|Id|id)\s*:?\s*\w+",
)
# Regex for "show credential" UI buttons (any lang).
# These are short lines (< 25 chars) with 2-3 words.
_SHOW_CREDENTIAL_RE = re.compile(
    r"^(?:Show|Afficher|Visa|Anzeigen|Mostra"
    r"|Mostrar|Weergeven|Ver)\b"
    r"|anzeigen$",
    re.IGNORECASE,
)


def _is_accomplishment_noise(line: str) -> bool:
    """Detect noise lines in accomplishment sections.

    Uses structural patterns rather than hardcoded
    translations. Noise patterns:
    1. Credential ID lines (any language)
    2. "Show credential" buttons (any language)
    3. Connection/message buttons
    4. Lines that are just degree separators
    5. Very short generic UI text
    """
    if not line or len(line) > 200:
        return True
    lower = line.lower().strip()

    # Connection/message indicators
    if lower in (
        "message", "connect",
        "· 1st", "· 2nd", "· 3rd",
        "· 1°", "· 2°", "· 3°",
        "· 1er", "· 2e", "· 3e",
        "· 1.", "· 2.", "· 3.",
    ):
        return True

    # "Load more" variants
    if _is_footer_line(line):
        return True

    # Credential ID pattern (language-agnostic)
    if _CREDENTIAL_ID_RE.match(line):
        return True

    # "Show credential" buttons (short + starts with
    # show/afficher/etc.)
    if len(line) < 30 and _SHOW_CREDENTIAL_RE.match(line):
        return True

    # "Issued <date>" lines - handled separately as dates
    # but skip as noise for title detection
    if re.match(
        r"^(?:Issued|Émise|Utfärdad|Ausgegeben"
        r"|Emitido|Rilasciato|Uitgegeven)\s",
        line,
    ):
        return True

    return False


def _split_date_duration(
    text: str,
) -> tuple[str, Optional[str]]:
    """Split 'Jan 2024 - Apr 2025 · 1 yr 4 mos'."""
    parts = text.split("·")
    date_str = parts[0].strip()
    duration = parts[1].strip() if len(parts) > 1 else None
    return date_str, duration


def _split_date_range(
    date_str: str,
) -> tuple[str, str]:
    """Split 'Jan 2024 - Apr 2025' into tuple."""
    # Handle both regular hyphen and en-dash
    for sep in (" - ", " – "):
        if sep in date_str:
            parts = date_str.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return date_str, ""


def _is_entry_boundary(
    line: str, lines: list[str], idx: int
) -> bool:
    """Check if a line starts a new entry."""
    if _DATE_RE.search(line):
        return True
    if line in _EMPLOYMENT_TYPES:
        return True
    if _DURATION_RE.match(line):
        return True
    # Company group: line followed by duration-only
    if (
        idx + 1 < len(lines)
        and _DURATION_RE.match(lines[idx + 1])
    ):
        return True
    # Short line followed by emp type or company·type
    if (
        idx + 1 < len(lines)
        # AIDEV-NOTE: 60 char cap = title length heuristic
        and len(line) < 60
        and (
            lines[idx + 1] in _EMPLOYMENT_TYPES
            or " · " in lines[idx + 1]
        )
    ):
        return True
    # Footer / sidebar noise
    if _is_footer_line(line):
        return True
    return False


# AIDEV-NOTE: phrases that signal end of content area
_FOOTER_PHRASES = [
    "uw bezoekers",
    "autres pages",
    "other pages",
    "who your viewers",
    "people you may know",
    "people also viewed",
    "you might like",
    "privacy & terms",
    "linkedin corporation",
    "show more",
    "show all",
    "load more",
    "profile language",
    "langue du profil",
    "profilsprache",
    "lingua del profilo",
    "idioma del perfil",
    "noch keine informationen",
    "no hay nada que ver",
    "nothing to see for now",
    "no information available",
    "show project",
    "mehr anzeigen",
    "alle anzeigen",
    "plus afficher",
    "charger plus",
    "carica altro",
    "cargar más",
    "meer laden",
    "community-richtlinien",
    "anzeigenauswahl",
    "kleinunternehmen",
    "carrières",
    "careers",
    "talent solutions",
    "ad choices",
    "advertising",
    "safety center",
    "accessibility",
    "questions?",
    "visit our help",
    "manage your account",
    "select language",
    "recommended content",
    "· 1st",
    "· 2nd",
    "· 3rd",
    "· 1er",
    "· 2e",
    "· 3e",
    "· 1.",
    "· 2.",
    "· 3.",
    "private to you",
    "privé",
    "nur für sie",
    "nachricht",
    "vernetzen",
    "message",
    "connect",
    "ihre besucher",
    "besucher:innen",
    "vos visiteurs",
    "sus visitantes",
    "uw bezoekers",
    "i tuoi visitatori",
    "altri profili consultati",
    "visibile solo a te",
    "invia messaggio",
    "collegati",
    "visualizza altro",
    "informazioni",
    "accessibilità",
    "andra profiler",
    "skicka meddelande",
    "anslut",
    "visa mer",
    "tillgänglighet",
    "other profiles viewed",
    "andere profile",
    "nachricht senden",
    "otros perfiles",
    "enviar mensaje",
    "conectar",
    "autres profils consultés",
    "envoyer un message",
    "se connecter",
]


def _is_footer_line(line: str) -> bool:
    """Detect LinkedIn footer/sidebar noise."""
    lower = line.lower()
    return any(p in lower for p in _FOOTER_PHRASES)


def _is_proficiency(text: str) -> bool:
    """Check if text is a language proficiency level.

    Matches English, German, French, Italian, Spanish,
    Dutch proficiency terms used by LinkedIn.
    """
    lower = text.lower()
    terms = [
        # EN
        "proficiency",
        # DE
        "fließend",
        "muttersprache",
        "zweisprachig",
        "grundkenntnisse",
        "gute kenntnisse",
        "verhandlungssicher",
        # FR
        "capacité professionnelle",
        "bilingue",
        "langue maternelle",
        "notions",
        "compétence professionnelle",
        # IT
        "competenza professionale",
        "madrelingua",
        "competenza limitata",
        # ES
        "competencia profesional",
        "competencia nativa",
        "competencia básica",
        # NL
        "professionele vaardigheid",
        "moedertaal",
        "tweetalig",
        "basiskennis",
    ]
    return any(t in lower for t in terms)


def _has_month_name(text: str) -> bool:
    """Check if text contains a month + year pattern.

    Uses year presence as confirmation to avoid false
    positives on short month abbreviations.
    """
    return bool(re.search(
        r"(?:19|20)\d{2}", text
    ))
