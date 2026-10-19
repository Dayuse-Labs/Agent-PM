/**
 * Motion preference — Dayuse fondations, loi 11 : « Reduced motion falls back to Instant ».
 * Module sans dépendance (importable partout, y compris sous node).
 */

/** true si l'utilisateur a demandé moins de mouvement. */
export function prefersReducedMotion() {
    return typeof window !== 'undefined'
        && typeof window.matchMedia === 'function'
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Valeur `behavior` pour scrollTo / scrollBy / scrollIntoView : 'smooth', ou 'auto' (instantané). */
export function scrollBehavior() {
    return prefersReducedMotion() ? 'auto' : 'smooth';
}
