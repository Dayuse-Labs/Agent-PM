"""Verify and render paired current-production evidence without model calls.

The output contains real dialogue. Keep it private under an ignored directory.
Hotel counts are descriptive; this report does not assign a quality winner.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from evals.production_replay import digest


def load_verified_pairs(directory: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((directory / "pilot-manifest.json").read_text())
    inputs = json.loads((directory / "pilot-inputs.json").read_text())["cases"]
    if not manifest.get("complete"):
        raise ValueError("paired pilot is incomplete")
    if len(inputs) != manifest["expected_sessions_per_variant"]:
        raise ValueError("source session coverage mismatch")
    ids = [c["id"] for c in inputs]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate source conversation")
    if sum(len(c["turns"]) for c in inputs) != manifest["expected_turns_per_variant"]:
        raise ValueError("source turn coverage mismatch")
    for variant in ("production", "new_main"):
        if {p.stem for p in (directory / variant).glob("*.json")} != set(ids):
            raise ValueError(f"{variant} has missing or extra output conversations")
    pairs, seen_sessions = [], set()
    for source in inputs:
        pair = {"source": source, "outputs": {}, "output_sha256": {}}
        for variant in ("production", "new_main"):
            raw = (directory / variant / f"{source['id']}.json").read_bytes()
            result = json.loads(raw)
            if result.get("case_id") != source["id"] or result.get("input_hash") != digest(source):
                raise ValueError("output input identity mismatch")
            if not result.get("complete") or result.get("error"):
                raise ValueError("output conversation is incomplete or errored")
            sid = result.get("session_id")
            if not isinstance(sid, str) or not sid.startswith("codex-") or sid in seen_sessions:
                raise ValueError("sessions must be fresh distinct synthetic identities")
            seen_sessions.add(sid)
            turns = result["turns"]
            if len(turns) != len(source["turns"]):
                raise ValueError("output turn coverage mismatch")
            for index, (original, actual) in enumerate(zip(source["turns"], turns, strict=True), 1):
                if actual.get("index") != index or actual.get("row_id") != original["row_id"]:
                    raise ValueError("output turn order or source row mismatch")
                response = actual.get("response")
                if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                    raise ValueError("missing actual assistant response")
                if response.get("session_id") != sid:
                    raise ValueError("response belongs to another session")
                if response.get("duplicate_of_previous_turn"):
                    raise ValueError("server deduplication replaced a real user turn")
            pair["outputs"][variant] = result
            pair["output_sha256"][variant] = hashlib.sha256(raw).hexdigest()
        pairs.append(pair)
    return manifest, pairs


def _text(value: object) -> str:
    return html.escape(str(value if value is not None else "non renseigné"))


def _cards(response: dict) -> str:
    cards = response.get("hotels") or []
    if not cards:
        return '<p class="muted">Aucune carte affichée — ni succès ni échec automatique.</p>'
    items = []
    for card in cards:
        slots = card.get("timeslots") or []
        times = ", ".join(f"{s.get('start', '?')}–{s.get('end', '?')}" for s in slots if isinstance(s, dict))
        amenities = card.get("amenities") or []
        equipment = ", ".join(str(a) for a in amenities) if amenities else "non renseignés dans la carte"
        items.append(
            f"<li><strong>{_text(card.get('name'))}</strong> · {_text(card.get('city'))}"
            f"<br>{_text(card.get('price'))} · horaires : {_text(times or None)}"
            f"<details><summary>Équipements déclarés</summary><p>{_text(equipment)}</p></details></li>"
        )
    return f'<details class="cards"><summary>{len(cards)} cartes affichées</summary><ul>{"".join(items)}</ul></details>'


def render(directory: Path, output: Path) -> dict:
    manifest, pairs = load_verified_pairs(directory)
    review = json.loads((directory / "pilot-review.json").read_text())
    if not review.get("deployment_verified_before_run") or not review.get("deployment_verified_after_run"):
        raise ValueError("production deployment was not verified around the run")
    if review.get("reference") != manifest["reference"] or review.get("new_agent") != manifest["new_agent"]:
        raise ValueError("review refers to different agent versions")
    scope = review.get("scope_note", "Lot ciblé de diagnostic, pas un taux global de qualité.")
    findings = review.get("findings", [])
    if not isinstance(scope, str) or not isinstance(findings, list) or any(not isinstance(f, str) for f in findings):
        raise ValueError("review scope and findings must be plain text")
    findings_html = "<ul>" + "".join(f"<li>{_text(f)}</li>" for f in findings) + "</ul>" if findings else ""
    reference_label = ("Code de production · support isolé" if manifest["reference"].get("mode")
                       else "Production aujourd’hui")
    sections = []
    for number, pair in enumerate(pairs, 1):
        source = pair["source"]
        turns = []
        for index, turn in enumerate(source["turns"]):
            columns = []
            for variant, label in (("production", reference_label), ("new_main", "Nouvel AgentB2C + MCP")):
                actual = pair["outputs"][variant]["turns"][index]
                response = actual["response"]
                columns.append(
                    f'<article><h4>{label}</h4><p class="answer">{_text(response["message"])}</p>'
                    f'{_cards(response)}<p class="muted">Exécuté : {_text(actual.get("executed_at"))}</p></article>'
                )
            turns.append(
                f'<section class="turn"><h3>Tour {index + 1}</h3><blockquote>{_text(turn["body"]["message"])}</blockquote>'
                f'<div class="pair">{"".join(columns)}</div></section>'
            )
        sections.append(
            f'<details class="conversation" open><summary>Conversation {number} · {len(source["turns"])} tours</summary>'
            f'{"".join(turns)}<p class="muted">Identifiant d’audit : {_text(source["id"])}</p></details>'
        )
    page = f'''<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dayuse — production actuelle contre nouvel agent</title>
<style>body{{font:16px/1.5 system-ui;color:#192b26;background:#f6f5f1;max-width:1300px;margin:36px auto;padding:0 24px}}h1{{font-size:32px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}article{{background:white;padding:20px;border:1px solid #d3dbd5;border-radius:8px;min-width:0}}.answer{{white-space:pre-wrap;overflow-wrap:anywhere}}blockquote{{margin:0 0 18px;padding:12px 18px;background:#e6eee8;border-left:4px solid #356f52;white-space:pre-wrap}}.muted{{color:#647169;font-size:13px}}.conversation{{margin:32px 0;border-top:1px solid #becbc2;padding-top:16px}}summary{{cursor:pointer;font-weight:650}}li{{margin:12px 0}}.turn{{margin:28px 0}}.notice{{background:#fff0cc;padding:16px}}@media(max-width:800px){{.pair{{grid-template-columns:1fr}}}}</style>
<h1>{_text(reference_label)} ↔ nouvel AgentB2C avec MCP</h1>
<p>{len(pairs)} conversations réelles · {manifest['expected_turns_per_variant']} tours par agent · réponses réellement obtenues lors du même pilote.</p>
<p class="muted">Exécution : {_text(manifest.get('created_at'))} — {_text(manifest.get('finished_at'))}.</p>
<p><b>{_text(reference_label)} :</b> {_text(manifest['reference'].get('endpoint'))} · {_text(manifest['reference']['sha'][:8])} · {_text(manifest['reference']['model_config'])}.<br>
<b>Nouveau :</b> révision {_text(manifest['new_agent']['sha'][:8])} · {_text(manifest['new_agent']['model'])} · MCP live.</p>
<p class="notice">{_text(scope)} Un modèle, des sources d’inventaire et des environnements différents sont comparés. La production a également des erreurs et ne constitue pas une réponse de référence parfaite.</p>
{findings_html}
<p>Les messages sont ceux des conversations historiques, mais les deux agents répondent au temps courant dans des sessions neuves. Les suivis ont parfois été écrits en réaction à une autre réponse historique. Aucun GPS ni compte client d’origine n’a été reconstitué. Un équipement déclaré sur l’hôtel ne prouve pas son inclusion dans chaque offre.</p>
<p class="muted">Document privé contenant des messages réels. Aucun score de conversion ou de satisfaction client n’est déduit de ces sorties. L’analyse n’ajoute aucun appel modèle.</p>
{''.join(sections)}</html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page)
    output.chmod(0o600)
    return {"sessions": len(pairs), "turns_per_agent": manifest["expected_turns_per_variant"],
            "output": str(output), "release_approved": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.run, args.output)))


if __name__ == "__main__":
    main()
