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

from b2c_common.clarification import Clarification


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


# mcp-dayuse#6 (Mathias 2026-10-06): a bare "oui"/"ok" that answers no
# question is never a greeting — the conversation is under way.
_AFFIRMATIVE_RELAUNCH: dict[str, str] = {
    "fr": "Dites-moi la ville et la date, et je vous cherche un hôtel en journée.",
    "en": "Tell me the city and the date, and I'll find you a day-use hotel.",
    "es": "Dime la ciudad y la fecha, y te busco un hotel de día.",
    "it": "Dimmi la città e la data, e ti cerco un hotel per il giorno.",
    "de": "Sag mir die Stadt und das Datum, und ich suche dir ein Tageshotel.",
    "pt": "Diga-me a cidade e a data, e procuro-lhe um hotel de dia.",
    "nl": "Vertel me de stad en de datum, dan zoek ik een daghotel voor je.",
}
_AFFIRMATIVE_REFINE: dict[str, str] = {
    "fr": "Très bien ! Je peux aussi chercher à une autre date, à un autre horaire, avec un budget ou ailleurs.",
    "en": "Great! I can also search another date, another time slot, with a budget or somewhere else.",
    "es": "¡Perfecto! También puedo buscar otra fecha, otra franja, con un presupuesto o en otro sitio.",
    "it": "Perfetto! Posso anche cercare un'altra data, un'altra fascia oraria, con un budget o altrove.",
    "de": "Gut! Ich kann auch ein anderes Datum, ein anderes Zeitfenster, mit Budget oder woanders suchen.",
    "pt": "Muito bem! Também posso pesquisar outra data, outro horário, com um orçamento ou noutro lugar.",
    "nl": "Prima! Ik kan ook zoeken op een andere datum, een ander tijdslot, met een budget of ergens anders.",
}


# mcp-dayuse#6: the profile expired mid-conversation (Redis TTL, RGPD
# retention) — said before the answer, which then starts from scratch.
_SESSION_EXPIRED: dict[str, str] = {
    "fr": "Notre conversation a expiré après {minutes} minutes d'inactivité : je repars de zéro.",
    "en": "Our conversation expired after {minutes} minutes of inactivity, so I'm starting over.",
    "es": "Nuestra conversación caducó tras {minutes} minutos de inactividad: empiezo de cero.",
    "it": "La nostra conversazione è scaduta dopo {minutes} minuti di inattività: riparto da zero.",
    "de": "Unser Gespräch ist nach {minutes} Minuten Inaktivität abgelaufen, ich fange von vorne an.",
    "pt": "A nossa conversa expirou após {minutes} minutos de inatividade: recomeço do zero.",
    "nl": "Ons gesprek is verlopen na {minutes} minuten inactiviteit, dus ik begin opnieuw.",
}


def session_expired_notice(language: str, minutes: int) -> str:
    return _pick(language, _SESSION_EXPIRED).format(minutes=minutes)


# mcp-dayuse#6: a follow-up that put back the very same offers says so.
_REFINEMENT_UNCHANGED: dict[str, str] = {
    "fr": "Ce changement ne modifie pas les résultats : ce sont les mêmes offres qu'avant.",
    "en": "That change does not alter the results: these are the same offers as before.",
    "es": "Este cambio no modifica los resultados: son las mismas ofertas que antes.",
    "it": "Questa modifica non cambia i risultati: sono le stesse offerte di prima.",
    "de": "Diese Änderung ändert nichts an den Ergebnissen: Es sind dieselben Angebote wie vorher.",
    "pt": "Esta alteração não muda os resultados: são as mesmas ofertas de antes.",
    "nl": "Deze wijziging verandert niets aan de resultaten: het zijn dezelfde aanbiedingen als eerder.",
}


def refinement_unchanged_notice(language: str) -> str:
    return _pick(language, _REFINEMENT_UNCHANGED)


def affirmative_relaunch_response(language: str, searched: bool) -> str:
    """The answer to a bare "oui" with no question pending: what to give next,
    or — once a search has run — how it can be refined."""
    return _pick(language, _AFFIRMATIVE_REFINE if searched else _AFFIRMATIVE_RELAUNCH)


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


# mcp-dayuse#8 (QA trace 9bc5feb6): the search service ANSWERED and refused
# this request — "retry in a moment" would only fail the same way.
_SEARCH_REJECTED: dict[str, str] = {
    "fr": "Je n'ai pas pu lancer cette recherche telle quelle. Pouvez-vous la reformuler "
    "(ville, date, créneau) ?",
    "en": "I couldn't run that search as it stands. Could you rephrase it (city, date, time slot)?",
    "es": "No he podido lanzar esta búsqueda tal cual. ¿Puedes reformularla (ciudad, fecha, franja horaria)?",
    "it": "Non sono riuscito a lanciare questa ricerca così com'è. Puoi riformularla "
    "(città, data, fascia oraria)?",
    "de": "Ich konnte diese Suche so nicht starten. Kannst du sie umformulieren (Stadt, Datum, Zeitfenster)?",
    "pt": "Não consegui fazer esta pesquisa assim. Pode reformulá-la (cidade, data, horário)?",
    "nl": "Ik kon deze zoekopdracht zo niet uitvoeren. Kun je hem anders formuleren (stad, datum, tijdslot)?",
}


def search_rejected_response(language: str) -> str:
    return _pick(language, _SEARCH_REJECTED)


_NAMED_NOT_FOUND: dict[str, str] = {
    "fr": "Je n'ai pas trouvé l'hôtel « {name} » sur Dayuse : voici d'autres hôtels{where}.",
    "en": "I couldn't find the hotel \"{name}\" on Dayuse: here are other hotels{where}.",
    "es": "No he encontrado el hotel «{name}» en Dayuse: aquí tienes otros hoteles{where}.",
    "it": "Non ho trovato l'hotel «{name}» su Dayuse: ecco altri hotel{where}.",
    "de": "Ich habe das Hotel „{name}“ auf Dayuse nicht gefunden: Hier sind andere Hotels{where}.",
    "pt": "Não encontrei o hotel «{name}» na Dayuse: aqui estão outros hotéis{where}.",
    "nl": "Ik heb het hotel \"{name}\" niet gevonden op Dayuse: hier zijn andere hotels{where}.",
}


_NAMED_NOT_FOUND_ALONE: dict[str, str] = {
    "fr": "Je n'ai pas trouvé l'hôtel « {name} » sur Dayuse. Vérifiez son nom, ou dites-moi "
    "la ville et je vous propose d'autres hôtels.",
    "en": "I couldn't find the hotel \"{name}\" on Dayuse. Check its name, or tell me the city "
    "and I'll suggest other hotels.",
    "es": "No he encontrado el hotel «{name}» en Dayuse. Comprueba su nombre o dime la ciudad "
    "y te propongo otros hoteles.",
    "it": "Non ho trovato l'hotel «{name}» su Dayuse. Controlla il nome, oppure dimmi la città "
    "e ti propongo altri hotel.",
    "de": "Ich habe das Hotel „{name}“ auf Dayuse nicht gefunden. Prüfe den Namen oder nenne mir "
    "die Stadt, dann schlage ich andere Hotels vor.",
    "pt": "Não encontrei o hotel «{name}» na Dayuse. Verifique o nome ou diga-me a cidade "
    "e proponho outros hotéis.",
    "nl": "Ik heb het hotel \"{name}\" niet gevonden op Dayuse. Controleer de naam, of noem de stad "
    "en ik stel andere hotels voor.",
}


def named_hotel_not_found_response(name: str, language: str) -> str:
    """The named hotel was not found and nothing else was searched."""
    return _pick(language, _NAMED_NOT_FOUND_ALONE).format(name=name)


def named_hotel_not_found_notice(name: str, language: str, city: str | None) -> str:
    """mcp-dayuse#8 (QA trace 6ef04c80): a named hotel was not found and the
    turn shows other hotels — said first, never left implicit."""
    return _pick(language, _NAMED_NOT_FOUND).format(name=name, where=_where(language, city))


_LANDMARK_UNRESOLVED: dict[str, str] = {
    "fr": "Je n'ai pas réussi à situer « {place} » : voici des hôtels{where}.",
    "en": "I couldn't locate \"{place}\": here are hotels{where}.",
    "es": "No he conseguido situar «{place}»: aquí tienes hoteles{where}.",
    "it": "Non sono riuscito a localizzare «{place}»: ecco degli hotel{where}.",
    "de": "Ich konnte „{place}“ nicht finden: Hier sind Hotels{where}.",
    "pt": "Não consegui localizar «{place}»: aqui estão hotéis{where}.",
    "nl": "Ik kon \"{place}\" niet vinden: hier zijn hotels{where}.",
}


def landmark_unresolved_notice(place: str, language: str, city: str | None) -> str:
    """2026-10-28 (prod session b4703f31, Paris + « l'unesco »): the spot the
    user named could not be placed, the city was searched instead — said
    first, never left implicit."""
    return _pick(language, _LANDMARK_UNRESOLVED).format(place=place, where=_where(language, city))


_NAMED_AMBIGUOUS: dict[str, str] = {
    "fr": "Plusieurs hôtels correspondent à « {name} » : {options}. Lequel souhaitez-vous ?",
    "en": "Several hotels match \"{name}\": {options}. Which one do you mean?",
    "es": "Varios hoteles coinciden con «{name}»: {options}. ¿Cuál quieres?",
    "it": "Diversi hotel corrispondono a «{name}»: {options}. Quale desideri?",
    "de": "Mehrere Hotels passen zu „{name}“: {options}. Welches meinst du?",
    "pt": "Vários hotéis correspondem a «{name}»: {options}. Qual deseja?",
    "nl": "Meerdere hotels passen bij \"{name}\": {options}. Welk bedoel je?",
}


def _city_label(slug: str) -> str:
    """`london` → London, `paris-10` → Paris 10 (the index carries slugs)."""
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def named_hotel_ambiguous_response(
    name: str, candidates: list[dict[str, str]], language: str
) -> str:
    """mcp-dayuse#7: several hotels match the name — ask, never pick one."""
    options = ", ".join(
        f"{c['name']} ({_city_label(c['city'])})" if c.get("city") else c["name"]
        for c in candidates
    )
    return _pick(language, _NAMED_AMBIGUOUS).format(name=name, options=options)


# QA14707 (decision DQ2): a question about a place is rendered here, from the
# search leaf's `Clarification`, and never by the synthesis. The only words
# that vary are the object's own `subject` and option `label`s, so no option
# the geocoder did not return can reach the user (the synthesis invented
# « Bruxelles » and « Versailles (78) » on trace C1). Three steps when the
# SAME question (same kind, same subject) comes back on the following turns:
# the question, then a reworded one, then no question at all.

#: How many turns in a row the same place question is asked; the next one
#: answers without a question. The free-question anti-loop (Q28) uses the
#: same bound on its own count (`pending_search.asked`).
CLARIFICATION_MAX_ASKS = 2

_CLARIFY_CITY_NEEDED: dict[str, str] = {
    "fr": "Près de « {subject} », dans quelle ville cherchez-vous ?",
    "en": "Near \"{subject}\" — in which city are you looking?",
    "es": "Cerca de «{subject}», ¿en qué ciudad buscas?",
    "it": "Vicino a «{subject}», in quale città stai cercando?",
    "de": "In der Nähe von „{subject}“ – in welcher Stadt suchst du?",
    "pt": "Perto de «{subject}», em que cidade procura?",
    "nl": "In de buurt van \"{subject}\" – in welke stad zoek je?",
}

_CLARIFY_CITY_NEEDED_AGAIN: dict[str, str] = {
    "fr": "Je ne peux pas situer « {subject} » sans la ville. Répondez simplement par le nom "
    "de la ville : un seul mot suffit.",
    "en": "I can't place \"{subject}\" without the city. Just reply with the city's name: "
    "one word is enough.",
    "es": "No puedo situar «{subject}» sin la ciudad. Responde solo con el nombre de la "
    "ciudad: basta una palabra.",
    "it": "Non riesco a individuare «{subject}» senza la città. Rispondi solo con il nome "
    "della città: basta una parola.",
    "de": "Ohne die Stadt kann ich „{subject}“ nicht finden. Antworte einfach mit dem Namen "
    "der Stadt: Ein Wort genügt.",
    "pt": "Não consigo situar «{subject}» sem a cidade. Responda apenas com o nome da "
    "cidade: basta uma palavra.",
    "nl": "Zonder de stad kan ik \"{subject}\" niet vinden. Antwoord gewoon met de naam van "
    "de stad: één woord is genoeg.",
}

_CLARIFY_HOMONYM: dict[str, str] = {
    "fr": "Plusieurs lieux s'appellent « {subject} ». Lequel voulez-vous dire ?",
    "en": "Several places are called \"{subject}\". Which one do you mean?",
    "es": "Hay varios lugares llamados «{subject}». ¿Cuál quieres decir?",
    "it": "Ci sono diversi luoghi chiamati «{subject}». Quale intendi?",
    "de": "Mehrere Orte heißen „{subject}“. Welchen meinst du?",
    "pt": "Há vários lugares chamados «{subject}». Qual deles quer dizer?",
    "nl": "Er zijn meerdere plaatsen die \"{subject}\" heten. Welke bedoel je?",
}

_CLARIFY_HOMONYM_AGAIN: dict[str, str] = {
    "fr": "Il me faut encore savoir de quel « {subject} » il s'agit. Voici ceux que j'ai trouvés :",
    "en": "I still need to know which \"{subject}\" you mean. These are the ones I found:",
    "es": "Todavía necesito saber a qué «{subject}» te refieres. Estos son los que encontré:",
    "it": "Devo ancora sapere quale «{subject}» intendi. Ecco quelli che ho trovato:",
    "de": "Ich muss noch wissen, welches „{subject}“ du meinst. Diese habe ich gefunden:",
    "pt": "Ainda preciso de saber a que «{subject}» se refere. Estes são os que encontrei:",
    "nl": "Ik moet nog weten welk \"{subject}\" je bedoelt. Deze heb ik gevonden:",
}

# 2026-10-27: the geocoder answered, but nothing it gave is the place the user
# named (prod: Galveston, Ojai, Cuneo). Said as such, with what would help —
# never the "search unavailable" line, which is for real outages.
_CLARIFY_UNRESOLVED: dict[str, str] = {
    "fr": "Je n'ai pas réussi à situer « {subject} ». Vous pouvez préciser la ville ou le pays ?",
    "en": "I couldn't place \"{subject}\". Could you tell me the city or the country?",
    "es": "No he conseguido ubicar «{subject}». ¿Puedes indicarme la ciudad o el país?",
    "it": "Non sono riuscito a localizzare «{subject}». Puoi indicarmi la città o il paese?",
    "de": "Ich konnte „{subject}“ nicht finden. Kannst du mir die Stadt oder das Land nennen?",
    "pt": "Não consegui localizar «{subject}». Pode indicar a cidade ou o país?",
    "nl": "Ik kon \"{subject}\" niet plaatsen. Kun je de stad of het land noemen?",
}
_CLARIFY_UNRESOLVED_AGAIN: dict[str, str] = {
    "fr": "« {subject} » reste introuvable de mon côté. Donnez-moi la ville la plus proche, "
    "avec son pays si possible.",
    "en": "I still can't find \"{subject}\". Give me the nearest city, with its country if "
    "you can.",
    "es": "Sigo sin encontrar «{subject}». Dime la ciudad más cercana, con su país si puedes.",
    "it": "Non trovo ancora «{subject}». Dimmi la città più vicina, con il suo paese se puoi.",
    "de": "„{subject}“ finde ich immer noch nicht. Nenn mir die nächste Stadt, wenn möglich "
    "mit dem Land.",
    "pt": "Continuo sem encontrar «{subject}». Indique a cidade mais próxima, com o país se "
    "possível.",
    "nl": "Ik kan \"{subject}\" nog steeds niet vinden. Noem de dichtstbijzijnde stad, met het "
    "land als dat kan.",
}
_CLARIFY_GIVE_UP: dict[str, str] = {
    "fr": "Je n'arrive toujours pas à situer « {subject} », alors je ne vous repose pas la "
    "question. Indiquez-moi simplement une ville et je lance la recherche avec le reste de "
    "votre demande.",
    "en": "I still can't place \"{subject}\", so I won't ask again. Just name a city and I'll "
    "run the search with the rest of your request.",
    "es": "Sigo sin poder situar «{subject}», así que no te lo vuelvo a preguntar. Dime "
    "simplemente una ciudad y lanzo la búsqueda con el resto de tu petición.",
    "it": "Non riesco ancora a individuare «{subject}», quindi non te lo richiedo. Dimmi "
    "semplicemente una città e avvio la ricerca con il resto della tua richiesta.",
    "de": "Ich kann „{subject}“ immer noch nicht zuordnen, deshalb frage ich nicht noch "
    "einmal. Nenn mir einfach eine Stadt, und ich starte die Suche mit dem Rest deiner Anfrage.",
    "pt": "Continuo sem conseguir situar «{subject}», por isso não volto a perguntar. "
    "Indique-me simplesmente uma cidade e lanço a pesquisa com o resto do seu pedido.",
    "nl": "Ik kan \"{subject}\" nog steeds niet plaatsen, dus ik vraag het niet nog een keer. "
    "Noem gewoon een stad en ik start de zoekopdracht met de rest van je vraag.",
}


# QA14707 (Q28): the anti-loop on FREE questions (any question the search leaf
# or the synthesis wrote, not a place question). Past CLARIFICATION_MAX_ASKS
# turns in a row without a search, the reply asks nothing; when the
# synthesis left nothing but its question, this fixed text answers instead.
_NO_QUESTION: dict[str, str] = {
    "fr": "Je ne vous repose pas la question. Dès que vous m'indiquez ce qui vous convient, "
    "je lance la recherche avec le reste de votre demande.",
    "en": "I won't ask again. As soon as you tell me what suits you, I'll run the search "
    "with the rest of your request.",
    "es": "No te lo vuelvo a preguntar. En cuanto me digas lo que te conviene, lanzo la "
    "búsqueda con el resto de tu petición.",
    "it": "Non te lo richiedo. Appena mi dici cosa ti va bene, avvio la ricerca con il resto "
    "della tua richiesta.",
    "de": "Ich frage nicht noch einmal. Sobald du mir sagst, was dir passt, starte ich die "
    "Suche mit dem Rest deiner Anfrage.",
    "pt": "Não volto a perguntar. Assim que me indicar o que lhe convém, lanço a pesquisa "
    "com o resto do seu pedido.",
    "nl": "Ik vraag het niet nog een keer. Zodra je me vertelt wat je wilt, start ik de "
    "zoekopdracht met de rest van je vraag.",
}


def no_question_response(language: str) -> str:
    """The reply of a turn the free-question anti-loop corrected when the
    synthesis wrote nothing but a question: it asks nothing."""
    return _pick(language, _NO_QUESTION)


# 2026-10-28 (Victor, prod data of 2026-10-27/28): the day is never asked in
# a message of its own. The isolated question of 2026-10-20 (Fabien) ended 12
# of 13 conversations that stopped on it after one turn, and doubled the
# questions when the place was missing too (the day, then the city). Now:
# - place missing → ONE question for the place AND, when it is still open,
#   the day (`place_question`), with the day chips;
# - place known, day missing → the search runs on today (tomorrow past the
#   same-day cutoff, the leaf's D+1 probe) and the answer says which day,
#   with the chips to change it (`date_retained_notice`).
# The chips are words `requested_date.parse_requested_date` reads in every
# language (today, +1, +2), so a click comes back as a dated reply.
_DATE_CHIPS: dict[str, tuple[str, str, str]] = {
    "fr": ("Aujourd'hui", "Demain", "Après-demain"),
    "en": ("Today", "Tomorrow", "The day after tomorrow"),
    "es": ("Hoy", "Mañana", "Pasado mañana"),
    "it": ("Oggi", "Domani", "Dopodomani"),
    "de": ("Heute", "Morgen", "Übermorgen"),
    "pt": ("Hoje", "Amanhã", "Depois de amanhã"),
    "nl": ("Vandaag", "Morgen", "Overmorgen"),
}

# #170's question (Fabien, prod session 7e296e4b), kept word for word: one
# turn instead of a day question, then a city question. Here it is asked when
# the leaf finds no place (`destination_missing`), with the day chips.
_DATE_PLACE_QUESTION: dict[str, str] = {
    "fr": "Où et pour quel jour souhaitez-vous réserver ?",
    "en": "Where and for which day would you like to book?",
    "es": "¿Dónde y para qué día quieres reservar?",
    "it": "Dove e per quale giorno vuoi prenotare?",
    "de": "Wo und für welchen Tag möchtest du buchen?",
    "pt": "Onde e para que dia pretende reservar?",
    "nl": "Waar en voor welke dag wil je boeken?",
}

_PLACE_QUESTION: dict[str, str] = {
    "fr": "Dans quelle ville (ou quel quartier) cherchez-vous ?",
    "en": "Which city (or neighbourhood) are you looking in?",
    "es": "¿En qué ciudad (o barrio) buscas?",
    "it": "In quale città (o quartiere) cerchi?",
    "de": "In welcher Stadt (oder welchem Viertel) suchst du?",
    "pt": "Em que cidade (ou bairro) procura?",
    "nl": "In welke stad (of wijk) zoek je?",
}

# The « près de moi » chip was clicked and no position came back (permission
# refused, no fix): said first, as the fact it is.
_NO_DEVICE_LOCATION: dict[str, str] = {
    "fr": "Je n'ai pas accès à votre position.",
    "en": "I can't access your location.",
    "es": "No tengo acceso a tu ubicación.",
    "it": "Non ho accesso alla tua posizione.",
    "de": "Ich habe keinen Zugriff auf deinen Standort.",
    "pt": "Não tenho acesso à sua localização.",
    "nl": "Ik heb geen toegang tot je locatie.",
}

# Appended to the leaf's own place question (a zone without its city, a place
# not found) when the day is still open: still one message.
_AND_WHICH_DAY: dict[str, str] = {
    "fr": "Et pour quel jour ?",
    "en": "And for which day?",
    "es": "¿Y para qué día?",
    "it": "E per quale giorno?",
    "de": "Und für welchen Tag?",
    "pt": "E para que dia?",
    "nl": "En voor welke dag?",
}

_DATE_RETAINED: dict[str, str] = {
    "fr": "Vous n'avez pas indiqué de jour : j'ai cherché pour {date}.",
    "en": "You didn't mention a day, so I searched for {date}.",
    "es": "No has indicado ningún día, así que he buscado para el {date}.",
    "it": "Non hai indicato un giorno, quindi ho cercato per {date}.",
    "de": "Du hast keinen Tag genannt, also habe ich für {date} gesucht.",
    "pt": "Não indicou nenhum dia, por isso pesquisei para {date}.",
    "nl": "Je hebt geen dag genoemd, dus ik heb gezocht voor {date}.",
}

_OTHER_DAY_CHIPS: dict[str, str] = {
    "fr": "Pour un autre jour, choisissez ci-dessous ou dites-le-moi.",
    "en": "For another day, pick one below or just tell me.",
    "es": "Para otro día, elige abajo o dímelo.",
    "it": "Per un altro giorno, scegli qui sotto o dimmelo.",
    "de": "Für einen anderen Tag wähle unten oder sag es mir.",
    "pt": "Para outro dia, escolha abaixo ou diga-me.",
    "nl": "Voor een andere dag, kies hieronder of laat het me weten.",
}

_OTHER_DAY: dict[str, str] = {
    "fr": "Pour un autre jour, dites-le-moi.",
    "en": "For another day, just tell me.",
    "es": "Para otro día, dímelo.",
    "it": "Per un altro giorno, dimmelo.",
    "de": "Für einen anderen Tag sag es mir.",
    "pt": "Para outro dia, diga-me.",
    "nl": "Voor een andere dag, laat het me weten.",
}


def date_chips(language: str) -> list[str]:
    return list(_DATE_CHIPS.get(language, _DATE_CHIPS["en"]))


def later_date_chips(language: str, served_offset: int) -> list[str]:
    """The day chips for the days AFTER the one searched (`served_offset` days
    from today): today's chip is no use once today was searched, nor once the
    same-day window closed and the search moved to tomorrow."""
    chips = _DATE_CHIPS.get(language, _DATE_CHIPS["en"])
    return [chip for offset, chip in enumerate(chips) if offset > served_offset]


# 2026-10-29 (prod after #173, 97 conversations): 45 opened on « Où et pour
# quel jour ? » with day chips only, the visitor clicked a day and got a bare
# « Dans quelle ville ? », 16 never saw a hotel. The question is now about the
# place only, restates the wish the triage read (agent-usa: « Sure — a
# discreet hotel. Which city are you looking in? »), and its chips answer it:
# « près de moi » and the market's cities (`place_chips`). The day falls back
# on today (tomorrow past the cutoff) and the answer with the hotels says
# which, with the day chips (`date_retained_notice`).
_WISH_PLACE_QUESTION: dict[str, str] = {
    "fr": "D'accord — {wish}. Dans quelle ville cherchez-vous ?",
    "en": "Sure — {wish}. Which city are you looking in?",
    "es": "Claro — {wish}. ¿En qué ciudad buscas?",
    "it": "Certo — {wish}. In quale città stai cercando?",
    "de": "Gerne — {wish}. In welcher Stadt suchst du?",
    "pt": "Claro — {wish}. Em que cidade procura?",
    "nl": "Zeker — {wish}. In welke stad zoek je?",
}

#: The « près de moi » chip of the place question. The payload names it
#: (`near_me`), so the widget asks for the device's position when it is
#: clicked, as for the hero chip (#173).
_NEAR_ME_CHIP: dict[str, str] = {
    "fr": "Près de moi",
    "en": "Near me",
    "es": "Cerca de mí",
    "it": "Vicino a me",
    "de": "In meiner Nähe",
    "pt": "Perto de mim",
    "nl": "Bij mij in de buurt",
}

# The visitor answered the place question without a place (a day, « peu
# importe »): the search ran on the market's main city, said first.
_DEFAULT_PLACE: dict[str, str] = {
    "fr": "Sans ville indiquée, voici des hôtels à {city}. Pour une autre ville, dites-la-moi.",
    "en": "With no city named, here are hotels in {city}. For another city, just tell me.",
    "es": "Sin ciudad indicada, aquí tienes hoteles en {city}. Para otra ciudad, dímela.",
    "it": "Senza una città indicata, ecco degli hotel a {city}. Per un'altra città, dimmela.",
    "de": "Ohne genannte Stadt hier Hotels in {city}. Für eine andere Stadt sag sie mir einfach.",
    "pt": "Sem cidade indicada, aqui estão hotéis em {city}. Para outra cidade, diga-ma.",
    "nl": "Zonder stad hier hotels in {city}. Voor een andere stad, laat het me weten.",
}


def near_me_chip(language: str) -> str:
    return _pick(language, _NEAR_ME_CHIP)


def place_chips(language: str, cities: list[str], *, near_me: bool = True) -> list[str]:
    """The chips of a place question: « près de moi » (unless the position was
    just refused), then the visitor market's cities (`market_cities`)."""
    chips = [near_me_chip(language)] if near_me else []
    return chips + [city for city in cities if city]


def place_question(
    language: str, *, wish: str | None = None, location_refused: bool = False,
    ask_day: bool = False,
) -> str:
    """The one question of a search that has no place yet: the place only,
    restating the `wish` the triage read when there is one. `location_refused`:
    the visitor asked for a search around them and no position came back.
    `ask_day` keeps the question of #170 (« Où et pour quel jour ? ») for a
    caller that still wants it; the spine no longer asks the day (2026-10-29)."""
    if ask_day:
        question = _pick(language, _DATE_PLACE_QUESTION)
    elif wish:
        question = _pick(language, _WISH_PLACE_QUESTION).format(wish=wish)
    else:
        question = _pick(language, _PLACE_QUESTION)
    if location_refused:
        return f"{_pick(language, _NO_DEVICE_LOCATION)} {question}"
    return question


def default_place_notice(city: str, language: str) -> str:
    """Said first when the search ran on the market's main city because the
    answer to the place question named none."""
    return _pick(language, _DEFAULT_PLACE).format(city=city)


def date_place_question(language: str) -> str:
    return _pick(language, _DATE_PLACE_QUESTION)


def with_day_question(question: str, language: str) -> str:
    """The leaf's place question, with the day asked in the same message."""
    return f"{question.rstrip()} {_pick(language, _AND_WHICH_DAY)}"


def date_retained_notice(human_date: str, language: str, *, with_chips: bool) -> str:
    """Said when the search ran on a day the user never named: which day it
    was, and how to change it (the chips below, when there are any)."""
    tail = _pick(language, _OTHER_DAY_CHIPS if with_chips else _OTHER_DAY)
    return f"{_pick(language, _DATE_RETAINED).format(date=human_date)} {tail}"


def clarification_response(clarification: Clarification, language: str, asked: int = 1) -> str:
    """The place question of the search leaf, in the conversation's language.

    `asked` is how many turns in a row this same question has come back
    (1 = first time). Past `CLARIFICATION_MAX_ASKS` there is no question any
    more: the answer offers to search by city instead. Options are listed one
    per line, numbered in the object's order, each exactly its `label`."""
    subject = clarification.subject
    if asked > CLARIFICATION_MAX_ASKS:
        return _pick(language, _CLARIFY_GIVE_UP).format(subject=subject)
    if clarification.kind == "city_needed":
        table = _CLARIFY_CITY_NEEDED if asked == 1 else _CLARIFY_CITY_NEEDED_AGAIN
        return _pick(language, table).format(subject=subject)
    if clarification.kind == "unresolved":
        table = _CLARIFY_UNRESOLVED if asked == 1 else _CLARIFY_UNRESOLVED_AGAIN
        return _pick(language, table).format(subject=subject)
    table = _CLARIFY_HOMONYM if asked == 1 else _CLARIFY_HOMONYM_AGAIN
    lines = [f"{n}. {option.label}" for n, option in enumerate(clarification.options, start=1)]
    return "\n".join([_pick(language, table).format(subject=subject), *lines])


_NAMED_NOT_OFFERED: dict[str, str] = {
    "fr": "{name} n'a pas d'offre disponible {when} : voici les hôtels les plus proches.",
    "en": "{name} has no offer available {when}: here are the nearest hotels.",
    "es": "{name} no tiene ofertas disponibles {when}: aquí tienes los hoteles más cercanos.",
    "it": "{name} non ha offerte disponibili {when}: ecco gli hotel più vicini.",
    "de": "{name} hat {when} kein verfügbares Angebot: Hier sind die nächstgelegenen Hotels.",
    "pt": "{name} não tem ofertas disponíveis {when}: aqui estão os hotéis mais próximos.",
    "nl": "{name} heeft {when} geen beschikbaar aanbod: hier zijn de dichtstbijzijnde hotels.",
}

_ON_DATE: dict[str, str] = {
    "fr": "le {date}", "en": "on {date}", "es": "el {date}", "it": "il {date}",
    "de": "am {date}", "pt": "em {date}", "nl": "op {date}",
}


def named_hotel_not_offered_notice(name: str, human_date: str, language: str) -> str:
    """mcp-dayuse#7: the named hotel exists but has nothing to book that day —
    the cards are its neighbours, and the answer says so first."""
    when = _pick(language, _ON_DATE).format(date=human_date)
    return _pick(language, _NAMED_NOT_OFFERED).format(name=name, when=when)


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
