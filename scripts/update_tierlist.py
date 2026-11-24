#!/usr/bin/env python3
"""
Met à jour data/tierlist.json à partir de l'export open data de BenchLeader.

Uniquement la bibliothèque standard de Python : aucune dépendance à installer.

Règles :
- Un modèle = sa meilleure configuration (la mieux classée au BenchLeader Index).
  Si cette configuration n'a pas de score dans une catégorie, on prend celui
  de la configuration suivante du même modèle.
- On garde le top 30 au classement général, plus les meilleurs modèles open source.
- Score absent -> null (jamais 0).
- L'export ne contient pas l'Elo LMArena : la catégorie "chat" est reprise telle
  quelle du fichier existant (mise à jour à la main).
- Les catégories (et leurs seuils "gaps") sont reprises du fichier existant :
  on peut les ajuster à la main sans toucher au script.
- Si quoi que ce soit échoue (réseau, format, valeurs aberrantes), le fichier
  existant n'est PAS modifié et le script se termine en erreur.

Usage :
    python3 scripts/update_tierlist.py                 # télécharge depuis BenchLeader
    python3 scripts/update_tierlist.py --source f.json # utilise un fichier local (tests)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = "https://www.benchleader.com/data/leaderboard.json"
SORTIE = Path(__file__).resolve().parent.parent / "data" / "tierlist.json"

TOP_GENERAL = 30
TOP_OPEN = 8
MIN_MODELES = 10

# Clé de catégorie dans tierlist.json -> champ dans l'export BenchLeader
CHAMPS = {"global": "index", "code": "coding", "agents": "agentic"}

CATEGORIES_PAR_DEFAUT = [
    {"key": "global", "label": "Global", "desc": "Intelligence générale", "unit": "/100", "gaps": [2, 5, 9, 14]},
    {"key": "code", "label": "Code", "desc": "Programmation", "unit": "/100", "gaps": [3, 8, 15, 25]},
    {"key": "agents", "label": "Agents", "desc": "Agents autonomes, outils", "unit": "/100", "gaps": [3, 8, 15, 25]},
    {"key": "chat", "label": "Chat", "desc": "Préférence humaine (votes)", "unit": "Elo", "gaps": [10, 25, 40, 60]},
]

# Plages plausibles : au-delà, on considère que le format a changé et on s'arrête.
PLAGES = {"global": (0, 100), "code": (0, 100), "agents": (0, 100), "chat": (800, 2000)}


class DonneesInvalides(Exception):
    pass


def telecharger(url: str) -> dict:
    requete = urllib.request.Request(url, headers={"User-Agent": "Tierslist-ai (github.com/Jordaneuh/Tierslist-ai)"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse)


def slug(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")


def nombre(valeur):
    """Convertit en float arrondi à 1 décimale, ou None si absent / non numérique."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return round(float(valeur), 1)


def effort_inconnu(ligne: dict) -> bool:
    effort = str(ligne.get("effort") or "").strip().lower()
    return effort in ("", "not stated", "unknown", "n/a")


def regrouper_par_modele(lignes: list[dict]) -> list[dict]:
    """Une entrée par modèle, à partir de sa configuration la mieux classée."""
    par_modele: dict[str, list[dict]] = {}
    for ligne in sorted(lignes, key=lambda l: l.get("rank") or 10**9):
        nom = ligne.get("model")
        if not isinstance(nom, str) or not nom.strip():
            continue
        par_modele.setdefault(nom.strip(), []).append(ligne)

    modeles = []
    for nom, configs in par_modele.items():
        # Les lignes "effort non précisé" agrègent souvent quelques résultats isolés :
        # leurs scores sont très incertains (ex. index ±7,6 contre ±3 pour les autres).
        # On ne les utilise que si le modèle n'a aucune configuration à effort connu.
        precises = [c for c in configs if not effort_inconnu(c)]
        configs = precises or configs
        meilleure = configs[0]
        scores = {}
        for cle, champ in CHAMPS.items():
            # Valeur de la meilleure configuration, sinon de la suivante qui en a une.
            scores[cle] = next((nombre(c.get(champ)) for c in configs if nombre(c.get(champ)) is not None), None)
        identifiant = str(meilleure.get("configuration_id") or "").split("@")[0] or slug(nom)
        modeles.append({
            "id": slug(identifiant),
            "name": nom,
            "lab": str(meilleure.get("provider") or "Inconnu"),
            "open": meilleure.get("open_weights") is True,
            "price": nombre(meilleure.get("price_blended_usd_per_mtok")),
            "scores": scores,
        })
    return modeles


def selectionner(modeles: list[dict]) -> list[dict]:
    """Top général + meilleurs open source, triés par score global décroissant."""
    classes = sorted(
        (m for m in modeles if m["scores"]["global"] is not None),
        key=lambda m: m["scores"]["global"],
        reverse=True,
    )
    retenus = classes[:TOP_GENERAL]
    ids = {m["id"] for m in retenus}
    for m in [m for m in classes if m["open"] and m["id"] not in ids][:TOP_OPEN]:
        retenus.append(m)
    return sorted(retenus, key=lambda m: m["scores"]["global"], reverse=True)


def reporter_chat(modeles: list[dict], existant: dict | None) -> None:
    """Reprend l'Elo "chat" du fichier existant (par id, sinon par nom)."""
    anciens = (existant or {}).get("models", [])
    par_id = {m.get("id"): m for m in anciens}
    par_nom = {str(m.get("name", "")).lower(): m for m in anciens}
    for m in modeles:
        ancien = par_id.get(m["id"]) or par_nom.get(m["name"].lower())
        chat = (ancien or {}).get("scores", {}).get("chat")
        m["scores"]["chat"] = chat if isinstance(chat, (int, float)) and not isinstance(chat, bool) else None


def valider(donnees: dict) -> None:
    modeles = donnees["models"]
    if len(modeles) < MIN_MODELES:
        raise DonneesInvalides(f"seulement {len(modeles)} modèles (minimum {MIN_MODELES})")
    ids = [m["id"] for m in modeles]
    if len(ids) != len(set(ids)):
        raise DonneesInvalides("identifiants de modèles en double")
    cles = {c["key"] for c in donnees["categories"]}
    for c in donnees["categories"]:
        gaps = c.get("gaps")
        if not (isinstance(gaps, list) and len(gaps) == 4 and gaps == sorted(gaps)):
            raise DonneesInvalides(f"seuils invalides pour {c.get('key')}: {gaps}")
    for m in modeles:
        if set(m["scores"]) != cles:
            raise DonneesInvalides(f"catégories incohérentes pour {m['name']}")
        for cle, valeur in m["scores"].items():
            if valeur is None:
                continue
            bas, haut = PLAGES.get(cle, (float("-inf"), float("inf")))
            if not bas <= valeur <= haut:
                raise DonneesInvalides(f"{m['name']} : score {cle}={valeur} hors de [{bas}, {haut}]")
        if m["price"] is not None and not 0 <= m["price"] <= 1000:
            raise DonneesInvalides(f"{m['name']} : prix aberrant {m['price']}")


def construire(source: dict, existant: dict | None) -> dict:
    lignes = source.get("rows")
    if not isinstance(lignes, list) or not lignes:
        raise DonneesInvalides("champ 'rows' absent ou vide : le format de l'export a peut-être changé")
    date = str(source.get("as_of") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise DonneesInvalides(f"date 'as_of' invalide : {date!r}")

    modeles = selectionner(regrouper_par_modele(lignes))
    reporter_chat(modeles, existant)
    categories = (existant or {}).get("categories") or CATEGORIES_PAR_DEFAUT

    donnees = {
        "updatedAt": date,
        "source": {"name": "BenchLeader", "url": "https://www.benchleader.com", "license": "CC BY 4.0"},
        "categories": categories,
        "models": modeles,
    }
    valider(donnees)
    return donnees


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, help="fichier leaderboard.json local au lieu du téléchargement")
    parser.add_argument("--sortie", type=Path, default=SORTIE)
    args = parser.parse_args()

    existant = None
    if args.sortie.exists():
        existant = json.loads(args.sortie.read_text(encoding="utf-8"))

    try:
        source = json.loads(args.source.read_text(encoding="utf-8")) if args.source else telecharger(SOURCE_URL)
        donnees = construire(source, existant)
    except Exception as erreur:  # réseau, JSON, format… : on ne touche à rien
        print(f"ÉCHEC, fichier inchangé : {erreur}", file=sys.stderr)
        return 1

    texte = json.dumps(donnees, ensure_ascii=False, indent=2) + "\n"
    if args.sortie.exists() and args.sortie.read_text(encoding="utf-8") == texte:
        print("Aucun changement.")
        return 0

    # Écriture atomique : fichier temporaire puis renommage.
    temporaire = args.sortie.with_suffix(".tmp")
    temporaire.write_text(texte, encoding="utf-8")
    temporaire.replace(args.sortie)
    print(f"Mis à jour : {len(donnees['models'])} modèles, données du {donnees['updatedAt']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
