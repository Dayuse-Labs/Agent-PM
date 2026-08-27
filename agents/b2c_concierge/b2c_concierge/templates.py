"""Deterministic, code-owned turn answers of the b2c-concierge spine (zero LLM).

Every template has a table entry for each of the 7 languages triage
recognizes (`triage.LANGUAGES`) — UX2, 2026-08-27. `_pick`/every table lookup
below falls back to English on a genuinely unrecognized language, never a
KeyError: the fallback stays reachable even though, as of UX2, every
recognized language has a real translation (`TEMPLATE_LANGUAGES ==
LANGUAGES`). No template ever invents a hotel, a price, a policy, or a link —
honest-degradation posture: when a capability is missing or a leaf is
unreachable, SAY it and stop.

Style source for the 5 languages added in UX2 (es/it/de/pt/nl): the widget's
`web/vendor/static/js/chat/i18n.js`, whose 7 blocks fix the register (tu/du/je
informal except pt which stays formal — pt-PT, not pt-BR) and the vocabulary
("franja"/"fascia oraria"/"Zeitfenster"/"horário"/"tijdslot" for "créneau",
"búsqueda"/"ricerca"/"Suche"/"pesquisa"/"zoekopdracht" for "search").
"""
from __future__ import annotations


def _pick(language: str, table: dict[str, str]) -> str:
    """Language-table lookup with an EN fallback (`table["en"]` must always be
    present) — a language recognized by triage whose table entry is somehow
    missing degrades cleanly to English rather than raising."""
    return table.get(language, table["en"])


_ACK_RESPONSE: dict[str, str] = {
    "fr": (
        "Bonjour ! Je suis le concierge Dayuse : dites-moi la ville (et la date si vous "
        "l'avez) et je vous trouve un hôtel en journée. Vous pouvez aussi me poser une "
        "question sur le fonctionnement de Dayuse."
    ),
    "en": (
        "Hello! I'm the Dayuse concierge: tell me the city (and the date if you have one) "
        "and I'll find you a day-use hotel. You can also ask me how Dayuse works."
    ),
    "es": (
        "¡Hola! Soy el conserje de Dayuse: dime la ciudad (y la fecha si la tienes) y te "
        "encuentro un hotel de día. También puedes preguntarme cómo funciona Dayuse."
    ),
    "it": (
        "Ciao! Sono il concierge Dayuse: dimmi la città (e la data se la conosci) e ti "
        "trovo un hotel per il giorno. Puoi anche chiedermi come funziona Dayuse."
    ),
    "de": (
        "Hallo! Ich bin der Dayuse-Concierge: Sag mir die Stadt (und das Datum, falls du "
        "es hast), und ich finde ein Tageshotel für dich. Du kannst mich auch fragen, wie "
        "Dayuse funktioniert."
    ),
    "pt": (
        "Olá! Sou o concierge da Dayuse: diga-me a cidade (e a data, se já a tiver) e "
        "encontro um hotel de dia para si. Também me pode perguntar como funciona a Dayuse."
    ),
    "nl": (
        "Hallo! Ik ben de Dayuse-concierge: vertel me de stad (en de datum als je die al "
        "weet) en ik vind een daghotel voor je. Je kunt me ook vragen hoe Dayuse werkt."
    ),
}


def ack_response(language: str) -> str:
    return _pick(language, _ACK_RESPONSE)


# --- S07: inline tools (real MCP wiring) — zero-LLM honest degradation ------

_INLINE_UNRESOLVED: dict[str, dict[str, str]] = {
    "fr": {
        "get_hotel_details": (
            "Je n'ai pas retrouvé cet hôtel — pouvez-vous me redonner son nom, ou "
            "me demander de chercher d'abord ?"
        ),
        "compare_hotels": (
            "Il me faut au moins deux hôtels à comparer — lesquels souhaitez-vous "
            "comparer ?"
        ),
        "generate_booking_link": (
            "Je n'arrive pas à préparer cette réservation pour le moment — pouvez-vous "
            "préciser l'hôtel, ou réessayer dans un instant ?"
        ),
    },
    "en": {
        "get_hotel_details": (
            "I couldn't find that hotel — could you give me its name again, or ask "
            "me to search first?"
        ),
        "compare_hotels": "I need at least two hotels to compare — which ones would you like?",
        "generate_booking_link": (
            "I can't prepare that booking right now — could you specify the hotel, "
            "or try again in a moment?"
        ),
    },
    "es": {
        "get_hotel_details": (
            "No he encontrado ese hotel — ¿puedes darme su nombre de nuevo, o "
            "pedirme que busque primero?"
        ),
        "compare_hotels": "Necesito al menos dos hoteles para comparar — ¿cuáles quieres comparar?",
        "generate_booking_link": (
            "No puedo preparar esa reserva ahora mismo — ¿puedes indicarme el hotel, "
            "o intentarlo de nuevo en un momento?"
        ),
    },
    "it": {
        "get_hotel_details": (
            "Non ho trovato questo hotel — puoi ridarmi il suo nome, o chiedermi di "
            "cercare prima?"
        ),
        "compare_hotels": "Mi servono almeno due hotel da confrontare — quali vuoi confrontare?",
        "generate_booking_link": (
            "Non riesco a preparare questa prenotazione al momento — puoi specificare "
            "l'hotel, o riprovare tra un istante?"
        ),
    },
    "de": {
        "get_hotel_details": (
            "Ich konnte dieses Hotel nicht finden — kannst du mir den Namen noch "
            "einmal nennen, oder mich bitten, zuerst zu suchen?"
        ),
        "compare_hotels": (
            "Ich brauche mindestens zwei Hotels zum Vergleichen — welche möchtest du "
            "vergleichen?"
        ),
        "generate_booking_link": (
            "Ich kann diese Buchung gerade nicht vorbereiten — kannst du das Hotel "
            "angeben, oder es gleich noch einmal versuchen?"
        ),
    },
    "pt": {
        "get_hotel_details": (
            "Não encontrei esse hotel — pode indicar-me o nome novamente, ou "
            "pedir-me para procurar primeiro?"
        ),
        "compare_hotels": "Preciso de pelo menos dois hotéis para comparar — quais gostaria de comparar?",
        "generate_booking_link": (
            "Não consigo preparar essa reserva neste momento — pode especificar o "
            "hotel, ou tentar novamente daqui a pouco?"
        ),
    },
    "nl": {
        "get_hotel_details": (
            "Ik kon dat hotel niet vinden — kun je me de naam nog een keer geven, "
            "of me vragen om eerst te zoeken?"
        ),
        "compare_hotels": "Ik heb minstens twee hotels nodig om te vergelijken — welke wil je vergelijken?",
        "generate_booking_link": (
            "Ik kan die boeking nu niet voorbereiden — kun je het hotel aangeven, "
            "of het zo meteen opnieuw proberen?"
        ),
    },
}


def inline_unresolved_response(target: str, language: str) -> str:
    """Honest degradation for an inline MCP tool call that could not resolve
    (hotel not found, fewer than 2 to compare, MCP unreachable, no bookable
    offer) — zero LLM, never invents a hotel/link that isn't there."""
    table = _INLINE_UNRESOLVED.get(language, _INLINE_UNRESOLVED["en"])
    return table[target]


def _format_time_slot(start_time: str | None, end_time: str | None) -> str | None:
    """S-G6: `start_time`/`end_time` are already-formatted "HH:MM" strings
    (the offer's real minutes, e.g. offer.startMinute/endMinute) — no longer
    forces ":00" on every offer regardless of its actual minutes."""
    if not start_time or not end_time:
        return None
    return f"{start_time}–{end_time}"


# (date phrase, slot phrase, sentence — {hotel}/{details} placeholders in the
# sentence, {date}/{slot} in the two phrases).
_OFFER_SUMMARY: dict[str, tuple[str, str, str]] = {
    "fr": (
        "le {date}", "créneau {slot}",
        "Voici l'offre pour {hotel} {details}. Confirmez-vous cette réservation ? "
        "Je ne génère le lien qu'après votre confirmation explicite.",
    ),
    "en": (
        "on {date}", "{slot} slot",
        "Here is the offer for {hotel} {details}. Do you confirm this booking? "
        "I'll only generate the link after your explicit confirmation.",
    ),
    "es": (
        "el {date}", "franja {slot}",
        "Aquí tienes la oferta de {hotel} {details}. ¿Confirmas esta reserva? "
        "Solo genero el enlace después de tu confirmación explícita.",
    ),
    "it": (
        "il {date}", "fascia oraria {slot}",
        "Ecco l'offerta per {hotel} {details}. Confermi questa prenotazione? "
        "Genero il link solo dopo la tua conferma esplicita.",
    ),
    "de": (
        "am {date}", "Zeitfenster {slot}",
        "Hier ist das Angebot für {hotel} {details}. Bestätigst du diese Buchung? "
        "Ich erstelle den Link erst nach deiner ausdrücklichen Bestätigung.",
    ),
    "pt": (
        "no dia {date}", "horário {slot}",
        "Aqui está a oferta para {hotel} {details}. Confirma esta reserva? "
        "Só gero o link depois da sua confirmação explícita.",
    ),
    "nl": (
        "op {date}", "tijdslot {slot}",
        "Hier is het aanbod voor {hotel} {details}. Bevestig je deze boeking? "
        "Ik maak de link pas aan na jouw uitdrukkelijke bevestiging.",
    ),
}


def booking_offer_summary_response(
    *,
    hotel_name: str,
    date: str,
    start_time: str | None,
    end_time: str | None,
    price: str | None,
    language: str,
) -> str:
    """R9 (guard #12), step 1: presents the offer and asks for explicit
    confirmation — deterministic, zero LLM (a booking confirmation is
    security-sensitive: it must never depend on an LLM's phrasing)."""
    slot = _format_time_slot(start_time, end_time)
    date_fmt, slot_fmt, sentence_fmt = _OFFER_SUMMARY.get(language, _OFFER_SUMMARY["en"])
    details = date_fmt.format(date=date)
    if slot:
        details += ", " + slot_fmt.format(slot=slot)
    if price:
        details += f", {price}"
    return sentence_fmt.format(hotel=hotel_name, details=details)


_BOOKING_LINK: dict[str, str] = {
    "fr": "Voici votre lien de réservation pour {hotel_name} — il reste à finaliser sur la page Dayuse : {url}",
    "en": "Here's your booking link for {hotel_name} — you'll finalize on the Dayuse page: {url}",
    "es": "Aquí tienes tu enlace de reserva para {hotel_name} — lo terminas en la página de Dayuse: {url}",
    "it": "Ecco il tuo link di prenotazione per {hotel_name} — lo finalizzi sulla pagina Dayuse: {url}",
    "de": "Hier ist dein Buchungslink für {hotel_name} — du schließt die Buchung auf der Dayuse-Seite ab: {url}",
    "pt": "Aqui está o seu link de reserva para {hotel_name} — falta finalizar na página da Dayuse: {url}",
    "nl": "Hier is je boekingslink voor {hotel_name} — je rondt het af op de Dayuse-pagina: {url}",
}


def booking_link_response(*, hotel_name: str, url: str | None, language: str) -> str:
    """R9 (guard #12), the authorized-link turn.

    S-CX5 considered dropping the URL from the text whenever a `booking_card`
    ships alongside it, and REVERTED that: the card rides an internal marker
    the facade turns into a payload key, so an A2A consumer (the eval harness,
    smoke_e2e) only ever sees this text — stripping the URL there made the
    answer useless off the widget path. It costs nothing to keep: the widget
    already removes raw URLs from the prose when a card is present
    (handlers/send.js), so the button is the only link the user sees."""
    if not url:
        return booking_needs_selection_response(None, None, language)
    template = _BOOKING_LINK.get(language, _BOOKING_LINK["en"])
    return template.format(hotel_name=hotel_name, url=url)


_NEEDS_SELECTION_LIST_INTRO: dict[str, str] = {
    "fr": "Quel hôtel de cette liste souhaitez-vous réserver ? Dites-moi son nom :\n",
    "en": "Which hotel from this list would you like to book? Tell me its name:\n",
    "es": "¿Qué hotel de esta lista quieres reservar? Dime su nombre:\n",
    "it": "Quale hotel di questa lista vuoi prenotare? Dimmi il suo nome:\n",
    "de": "Welches Hotel aus dieser Liste möchtest du buchen? Sag mir seinen Namen:\n",
    "pt": "Qual hotel desta lista gostaria de reservar? Diga-me o nome:\n",
    "nl": "Welk hotel uit deze lijst wil je boeken? Vertel me de naam:\n",
}

_NEEDS_SELECTION_NO_OFFER: dict[str, str] = {
    "fr": (
        "Cet hôtel n'a pas d'offre en journée réservable pour cette date — "
        "voulez-vous essayer une autre date ou un autre hôtel ?"
    ),
    "en": (
        "That hotel has no bookable day-use offer for this date — want to try "
        "another date or another hotel?"
    ),
    "es": (
        "Ese hotel no tiene una oferta de día reservable para esta fecha — "
        "¿quieres probar otra fecha u otro hotel?"
    ),
    "it": (
        "Questo hotel non ha un'offerta per il giorno prenotabile per questa data — "
        "vuoi provare un'altra data o un altro hotel?"
    ),
    "de": (
        "Dieses Hotel hat für dieses Datum kein buchbares Tagesangebot — möchtest "
        "du ein anderes Datum oder ein anderes Hotel versuchen?"
    ),
    "pt": (
        "Esse hotel não tem uma oferta de dia reservável para esta data — quer "
        "tentar outra data ou outro hotel?"
    ),
    "nl": (
        "Dit hotel heeft voor deze datum geen boekbaar dagaanbod — wil je een "
        "andere datum of een ander hotel proberen?"
    ),
}

_NEEDS_SELECTION_NO_LIST: dict[str, str] = {
    "fr": (
        "Je n'ai pas encore de liste d'hôtels à réserver — dites-moi d'abord la ville "
        "(et la date) et je cherche pour vous."
    ),
    "en": (
        "I don't have a hotel list to book from yet — tell me the city (and date) "
        "first and I'll search for you."
    ),
    "es": (
        "Todavía no tengo una lista de hoteles para reservar — dime primero la "
        "ciudad (y la fecha) y busco por ti."
    ),
    "it": (
        "Non ho ancora una lista di hotel da prenotare — dimmi prima la città (e "
        "la data) e cerco per te."
    ),
    "de": (
        "Ich habe noch keine Hotelliste zum Buchen — sag mir zuerst die Stadt (und "
        "das Datum), dann suche ich für dich."
    ),
    "pt": (
        "Ainda não tenho uma lista de hotéis para reservar — diga-me primeiro a "
        "cidade (e a data) e eu procuro por si."
    ),
    "nl": (
        "Ik heb nog geen hotellijst om uit te boeken — vertel me eerst de stad (en "
        "de datum), dan zoek ik voor je."
    ),
}


def booking_needs_selection_response(
    shortlist: list[dict] | None, reason: str | None, language: str
) -> str:
    """Booking couldn't resolve WHICH hotel — never dead-end. When a shortlist is
    on screen, LIST it so the user just picks; otherwise say what's missing,
    worded from the inline-tool reason (no hotel reference / hotel not found / no
    bookable offer). Zero LLM, never invents a hotel."""
    names = [str(h.get("name")) for h in (shortlist or []) if isinstance(h, dict) and h.get("name")]
    if names:
        listing = "\n".join(f"{i}. {name}" for i, name in enumerate(names, 1))
        intro = _NEEDS_SELECTION_LIST_INTRO.get(language, _NEEDS_SELECTION_LIST_INTRO["en"])
        return intro + listing
    if reason and "no bookable offer" in reason:
        return _NEEDS_SELECTION_NO_OFFER.get(language, _NEEDS_SELECTION_NO_OFFER["en"])
    return _NEEDS_SELECTION_NO_LIST.get(language, _NEEDS_SELECTION_NO_LIST["en"])


# "Where" clause per language ("" when no city) — shared by search_exhausted_
# response and leaf_degraded_response.
_WHERE: dict[str, str] = {
    "fr": " à {city}",
    "en": " in {city}",
    "es": " en {city}",
    "it": " a {city}",
    "de": " in {city}",
    "pt": " em {city}",
    "nl": " in {city}",
}


def _where(language: str, city: str | None) -> str:
    if not city:
        return ""
    return _WHERE.get(language, _WHERE["en"]).format(city=city)


_DEGRADED: dict[str, dict[str, str]] = {
    "fr": {
        "search": "Je n'arrive pas à joindre la recherche d'hôtels{where}",
        "faq": "Je n'arrive pas à consulter les conditions Dayuse",
    },
    "en": {
        "search": "I can't reach the hotel search{where}",
        "faq": "I can't look up the Dayuse conditions",
    },
    "es": {
        "search": "No consigo conectar con la búsqueda de hoteles{where}",
        "faq": "No consigo consultar las condiciones de Dayuse",
    },
    "it": {
        "search": "Non riesco a raggiungere la ricerca hotel{where}",
        "faq": "Non riesco a consultare le condizioni Dayuse",
    },
    "de": {
        "search": "Ich kann die Hotelsuche{where} gerade nicht erreichen",
        "faq": "Ich kann die Dayuse-Bedingungen gerade nicht abrufen",
    },
    "pt": {
        "search": "Não consigo aceder à pesquisa de hotéis{where}",
        "faq": "Não consigo consultar as condições da Dayuse",
    },
    "nl": {
        "search": "Ik kan de hotelzoekfunctie{where} niet bereiken",
        "faq": "Ik kan de Dayuse-voorwaarden niet raadplegen",
    },
}

# Suffix appended after the (already `{where}`-resolved) degraded clause above
# — never contains its own `{where}`: German/Dutch need the location INSIDE
# the base clause (verb-final word order), so it is consumed there instead.
_DEGRADED_SUFFIX: dict[str, str] = {
    "fr": " pour le moment, et je préfère ne rien inventer. Pouvez-vous réessayer dans un instant ?",
    "en": " right now, and I'd rather not make anything up. Could you try again in a moment?",
    # "ahora mismo", not "en este momento": leaf_degraded_response's `{where}`
    # already ends in "en {city}" right before this suffix — avoids stacking
    # "en Paris en este momento" back to back. Matches _SERVICE_DEGRADED's ES
    # phrasing for the same "right now" slot.
    "es": " ahora mismo, y prefiero no inventar nada. ¿Puedes intentarlo de nuevo en un momento?",
    "it": " in questo momento, e preferisco non inventare nulla. Puoi riprovare tra un istante?",
    "de": ", und ich möchte mir nichts ausdenken. Kannst du es in einem Moment noch einmal versuchen?",
    "pt": " neste momento, e prefiro não inventar nada. Pode tentar novamente daqui a pouco?",
    "nl": " op dit moment, en ik wil liever niets verzinnen. Kun je het over een moment opnieuw proberen?",
}


def leaf_degraded_response(family: str, language: str, city: str | None = None) -> str:
    """Honest degradation when a leaf leg timed out or failed: say it — naming the
    destination when known so the user sees what was attempted — invent nothing,
    no retry (the 10 s budget is spent)."""
    where = _where(language, city) if family == "search" else ""
    deg_table = _DEGRADED.get(language, _DEGRADED["en"])
    degraded = deg_table.get(family, deg_table["search"]).format(where=where)
    suffix = _DEGRADED_SUFFIX.get(language, _DEGRADED_SUFFIX["en"])
    return degraded + suffix


_SEARCH_EXHAUSTED_PAGINATION: dict[str, str] = {
    "fr": (
        "Vous avez vu tous les hôtels correspondant à vos critères{where}. Voulez-vous "
        "que j'élargisse le budget, la zone, ou que je retire un filtre ?"
    ),
    "en": (
        "You've now seen every hotel matching your criteria{where}. Want me to widen "
        "the budget, the area, or drop a filter?"
    ),
    "es": (
        "Ya has visto todos los hoteles que coinciden con tus criterios{where}. "
        "¿Quieres que amplíe el presupuesto, la zona, o que quite un filtro?"
    ),
    "it": (
        "Hai visto tutti gli hotel che corrispondono ai tuoi criteri{where}. Vuoi che "
        "amplii il budget, la zona, o che rimuova un filtro?"
    ),
    "de": (
        "Du hast jetzt jedes Hotel{where} gesehen, das zu deinen Kriterien passt. Soll "
        "ich das Budget erweitern, das Gebiet vergrößern, oder einen Filter entfernen?"
    ),
    "pt": (
        "Já viu todos os hotéis que correspondem aos seus critérios{where}. Quer que "
        "eu aumente o orçamento, alargue a zona, ou retire um filtro?"
    ),
    "nl": (
        "Je hebt nu elk hotel{where} gezien dat aan je criteria voldoet. Wil je dat ik "
        "het budget verruim, het gebied vergroot, of een filter verwijder?"
    ),
}

_SEARCH_EXHAUSTED_BUDGET: dict[str, str] = {
    "fr": (
        "Même après avoir élargi le budget, je ne trouve toujours rien{where}. Essayez "
        "une autre ville, ou dites-moi ce que je peux ajuster (date, quartier)."
    ),
    "en": (
        "Even after widening the budget, I still couldn't find anything{where}. Try a "
        "different city, or tell me what I should adjust (date, area)."
    ),
    "es": (
        "Incluso después de ampliar el presupuesto, sigo sin encontrar nada{where}. "
        "Prueba con otra ciudad, o dime qué puedo ajustar (fecha, zona)."
    ),
    "it": (
        "Anche dopo aver ampliato il budget, non trovo ancora nulla{where}. Prova "
        "un'altra città, o dimmi cosa posso modificare (data, zona)."
    ),
    "de": (
        "Auch nach Erweiterung des Budgets finde ich immer noch nichts{where}. Versuch "
        "es mit einer anderen Stadt, oder sag mir, was ich anpassen soll (Datum, Gegend)."
    ),
    "pt": (
        "Mesmo depois de aumentar o orçamento, continuo sem encontrar nada{where}. "
        "Tente outra cidade, ou diga-me o que posso ajustar (data, zona)."
    ),
    "nl": (
        "Zelfs na het verruimen van het budget vind ik nog steeds niets{where}. "
        "Probeer een andere stad, of vertel me wat ik moet aanpassen (datum, buurt)."
    ),
}


def search_exhausted_response(
    language: str, city: str | None = None, *, reason: str = "budget"
) -> str:
    """Terminal, zero-LLM message once the search is exhausted — reuses the
    SAME `profile.search_exhausted` flag/gate for two distinct triggers
    (extend, never a parallel mechanism):
    - "budget" (S12, audit 2026-07-20 — prod session 034c97c4, Rimini: an
      uncapped widen loop never told the user it had given up) — auto-widening
      was tried and still came back empty;
    - "pagination" (S-G5) — an "other options" request came back with zero
      NEW hotels: every match for the current filters has already been shown,
      so the message proposes relaxing ONE named constraint instead of the
      generic "try another city".
    Never a retry; the spine's pre-leaf gate only reaches here on a bare
    affirmative — a new constraint clears the flag and searches again instead.
    """
    where = _where(language, city)
    table = _SEARCH_EXHAUSTED_PAGINATION if reason == "pagination" else _SEARCH_EXHAUSTED_BUDGET
    text = table.get(language, table["en"])
    return text.format(where=where)


_SERVICE_DEGRADED: dict[str, str] = {
    "fr": (
        "Un souci technique m'empêche de répondre pour le moment, et je préfère "
        "ne rien inventer. Pouvez-vous réessayer dans un instant ?"
    ),
    "en": (
        "A technical issue is stopping me from answering right now, and I'd "
        "rather not make anything up. Could you try again in a moment?"
    ),
    "es": (
        "Un problema técnico me impide responder ahora mismo, y prefiero no "
        "inventar nada. ¿Puedes intentarlo de nuevo en un momento?"
    ),
    "it": (
        "Un problema tecnico mi impedisce di rispondere in questo momento, e "
        "preferisco non inventare nulla. Puoi riprovare tra un istante?"
    ),
    "de": (
        "Ein technisches Problem hindert mich gerade daran zu antworten, und "
        "ich möchte mir nichts ausdenken. Kannst du es in einem Moment noch "
        "einmal versuchen?"
    ),
    "pt": (
        "Um problema técnico impede-me de responder neste momento, e prefiro "
        "não inventar nada. Pode tentar novamente daqui a pouco?"
    ),
    "nl": (
        "Een technisch probleem verhindert dat ik nu kan antwoorden, en ik wil "
        "liever niets verzinnen. Kun je het over een moment opnieuw proberen?"
    ),
}


def service_degraded_response(language: str) -> str:
    """Last-resort facade shield (S-CX1): an unexpected error escaped every
    inner degradation net, so the step that failed is unknown — generic
    honest wording, invents nothing, never a raw 500/dead stream."""
    return _pick(language, _SERVICE_DEGRADED)
