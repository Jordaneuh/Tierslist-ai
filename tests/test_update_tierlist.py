"""Tests du script de mise à jour (bibliothèque standard : python3 -m unittest discover tests)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import update_tierlist as u  # noqa: E402


def ligne(rang, modele, effort, labo="Labo", ouvert=False, index=60.0, coding=60.0, agentic=60.0, prix=1.0):
    return {
        "rank": rang, "model": modele, "effort": effort,
        "configuration_id": f"{u.slug(modele)}@{effort}", "provider": labo,
        "open_weights": ouvert, "index": index, "coding": coding, "agentic": agentic,
        "price_blended_usd_per_mtok": prix,
    }


def source(lignes):
    return {"as_of": "2026-11-24", "rows": lignes}


class Tests(unittest.TestCase):
    def setUp(self):
        self.lignes = [ligne(i + 1, f"Modèle {i}", "high", index=80.0 - i) for i in range(12)]

    def test_une_ligne_par_modele_avec_meilleure_config(self):
        lignes = [
            ligne(1, "Alpha", "max", index=70.0, agentic=None),
            ligne(2, "Alpha", "low", index=65.0, agentic=55.0),
        ] + self.lignes
        donnees = u.construire(source(lignes), None)
        alpha = [m for m in donnees["models"] if m["name"] == "Alpha"]
        self.assertEqual(len(alpha), 1)
        self.assertEqual(alpha[0]["scores"]["global"], 70.0)
        # agentic absent de la meilleure config -> repris de la suivante
        self.assertEqual(alpha[0]["scores"]["agents"], 55.0)
        self.assertEqual(alpha[0]["id"], "alpha")

    def test_effort_non_precise_ignore_si_autre_config(self):
        # Cas réel Claude Fable 5.1 : la ligne "not stated" (peu de résultats) est mieux classée.
        lignes = [
            ligne(1, "Delta", "not stated", index=67.0, coding=88.6),
            ligne(2, "Delta", "max", index=66.7, coding=69.2),
            ligne(3, "Epsilon", "not stated", index=61.0, coding=60.0),  # seule config : gardée
        ] + self.lignes
        modeles = {m["name"]: m for m in u.construire(source(lignes), None)["models"]}
        self.assertEqual(modeles["Delta"]["scores"]["code"], 69.2)
        self.assertEqual(modeles["Delta"]["scores"]["global"], 66.7)
        self.assertEqual(modeles["Epsilon"]["scores"]["code"], 60.0)

    def test_details_et_lien(self):
        l = ligne(1, "Zeta", "max", labo="Anthropic")
        l.update({"reasoning": 70.0, "output_tokens_per_second": 85, "url": "https://www.benchleader.com/models/zeta"})
        donnees = u.construire(source([l] + self.lignes), None)
        zeta = next(m for m in donnees["models"] if m["name"] == "Zeta")
        self.assertEqual(zeta["details"]["reasoning"], 70.0)
        self.assertEqual(zeta["details"]["speed"], 85.0)
        self.assertIsNone(zeta["details"]["math"])
        self.assertEqual(zeta["effort"], "max")
        self.assertEqual(zeta["url"], "https://www.benchleader.com/models/zeta")
        self.assertEqual(donnees["labs"], {"Anthropic": "https://www.anthropic.com/news"})

    def test_lien_hors_benchleader_ignore(self):
        l = ligne(1, "Eta", "max")
        l["url"] = "https://exemple.com/piege"
        eta = next(m for m in u.construire(source([l] + self.lignes), None)["models"] if m["name"] == "Eta")
        self.assertIsNone(eta["url"])

    def test_changements_entre_deux_versions(self):
        avant = u.construire(source(self.lignes), None)
        # Modèle 11 bondit en tête, un nouveau modèle arrive, Modèle 10 disparaît.
        lignes = [l for l in self.lignes if l["model"] != "Modèle 10"]
        lignes = [dict(l, index=99.0) if l["model"] == "Modèle 11" else l for l in lignes]
        lignes.append(ligne(50, "Nouveau", "high", index=50.0))
        apres = u.construire(source(lignes), avant)
        items = apres["changes"]["items"]
        types = {(i["type"], i["name"]) for i in items}
        self.assertIn(("nouveau", "Nouveau"), types)
        self.assertIn(("retire", "Modèle 10"), types)
        monte = next(i for i in items if i["name"] == "Modèle 11" and i["category"] == "global")
        self.assertEqual((monte["type"], monte["to"]), ("monte", "S"))
        self.assertEqual(apres["changes"]["since"], "2026-11-24")

    def test_sans_changement_on_garde_les_derniers(self):
        precedent = u.construire(source(self.lignes), None)
        precedent["changes"] = {"date": "2026-11-17", "since": "2026-11-10", "items": [{"type": "nouveau", "id": "x", "name": "X"}]}
        apres = u.construire(source(self.lignes), precedent)
        self.assertEqual(apres["changes"]["date"], "2026-11-17")

    def test_score_absent_reste_null(self):
        lignes = [ligne(1, "Beta", "high", coding=None)] + self.lignes
        beta = next(m for m in u.construire(source(lignes), None)["models"] if m["name"] == "Beta")
        self.assertIsNone(beta["scores"]["code"])

    def test_chat_repris_du_fichier_existant(self):
        existant = {"models": [{"id": "modele-0", "name": "Modèle 0", "scores": {"chat": 1500}}]}
        donnees = u.construire(source(self.lignes), existant)
        self.assertEqual(donnees["models"][0]["scores"]["chat"], 1500)
        self.assertIsNone(donnees["models"][1]["scores"]["chat"])

    def test_open_source_ajoutes_hors_top(self):
        lignes = [ligne(i + 1, f"Fermé {i}", "high", index=90.0 - i) for i in range(35)]
        lignes.append(ligne(36, "Libre", "high", ouvert=True, index=40.0))
        noms = [m["name"] for m in u.construire(source(lignes), None)["models"]]
        self.assertIn("Libre", noms)
        self.assertEqual(len(noms), 31)

    def test_trop_peu_de_modeles_refuse(self):
        with self.assertRaises(u.DonneesInvalides):
            u.construire(source(self.lignes[:5]), None)

    def test_score_aberrant_refuse(self):
        lignes = [ligne(1, "Gamma", "high", index=900.0)] + self.lignes
        with self.assertRaises(u.DonneesInvalides):
            u.construire(source(lignes), None)

    def test_format_inattendu_refuse(self):
        with self.assertRaises(u.DonneesInvalides):
            u.construire({"as_of": "2026-11-24", "data": []}, None)

    def test_fichier_initial_valide(self):
        import json
        donnees = json.loads((Path(__file__).resolve().parent.parent / "data" / "tierlist.json").read_text())
        u.valider(donnees)


if __name__ == "__main__":
    unittest.main()
