# Tierslist-ai

Données de la **tier list des modèles d'IA** affichée dans l'app Dyme.

L'app lit un seul fichier, sans token :

```
https://raw.githubusercontent.com/Jordaneuh/Tierslist-ai/main/data/tierlist.json
```

## Mise à jour

Chaque lundi à 6h UTC, l'action `Mise à jour des données` :

1. télécharge l'export open data de BenchLeader (`/data/leaderboard.json`) ;
2. garde une ligne par modèle (sa meilleure configuration), le top 30 et les meilleurs modèles open source ;
3. vérifie le résultat (au moins 10 modèles, scores dans des plages plausibles) ;
4. commite `data/tierlist.json` seulement s'il a changé.

En cas d'échec, le fichier n'est pas modifié et le job apparaît en rouge.
On peut aussi la lancer à la main : onglet **Actions → Mise à jour des données → Run workflow**.

### À savoir

- **Catégorie Chat** : l'export BenchLeader ne contient pas l'Elo LMArena. Les valeurs `chat`
  sont reprises du fichier existant et se mettent à jour à la main.
- **Seuils des tiers** (`gaps`) : modifiables directement dans `data/tierlist.json`, ils sont conservés
  par le script. L'app les relit sans être recompilée.
- Tester en local : `python3 -m unittest discover tests`, puis `python3 scripts/update_tierlist.py`.

## Source et licence

Scores : [BenchLeader](https://www.benchleader.com), sous licence
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (index et scores de catégorie calculés par BenchLeader).
BenchLeader agrège des benchmarks publics ; chaque résultat reste attribué à son éditeur.
Les prix sont des tarifs publics des fournisseurs et ne sont pas couverts par cette licence.
