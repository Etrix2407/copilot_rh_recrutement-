---
name: fin-etape
description: Clôture une étape de docs/plan_de_developpement.md avant la revue — lance pytest, vérifie un à un les critères « ✔ Terminé quand », contrôle les règles à ne jamais enfreindre, puis produit le résumé de revue et propose le commit. À utiliser quand l'utilisateur tape /fin-etape ou dit que l'étape en cours est finie, prête à relire ou à valider. Ne pas utiliser en cours d'étape ni pour démarrer l'étape suivante.
---

# Fin d'étape

But : donner à l'utilisateur tout ce qu'il faut pour relire et valider l'étape, sans qu'il ait à le reconstituer. Le rapport dit ce qui est **prouvé**, pas ce qui est espéré.

## 1. Identifier l'étape

- Déduis le numéro d'étape de la branche (`git branch --show-current`), des derniers commits et des fichiers modifiés.
- Si c'est ambigu, demande-le avant d'aller plus loin.
- Relis la section correspondante de `docs/plan_de_developpement.md`, en particulier le bloc **« ✔ Terminé quand »**.

## 2. Lancer les tests

- Active le venv et lance `pytest` (toute la suite, pas seulement les nouveaux tests).
- Si quelque chose casse : corrige, relance, et note la correction dans le résumé.
- Rapporte le résultat exact (nombre de tests passés / échoués / ignorés). Un test ignoré ou marqué `xfail` doit être justifié.

## 3. Vérifier chaque critère « Terminé quand »

Pour **chaque** critère de l'étape, donne un statut et sa preuve :

| Statut | Signification |
|---|---|
| ✅ Vérifié | Preuve concrète : test qui passe, commande lancée et sa sortie, réponse d'API observée |
| ⚠️ Non vérifiable ici | Ex. : clé API absente, appel LLM réel nécessaire. Dire précisément ce que l'utilisateur doit lancer pour le vérifier |
| ❌ Non atteint | Dire ce qui manque |

Ne coche jamais un critère sur la seule base du code écrit. Si un des 3 tests officiels (CLAUDE.md) est concerné par l'étape, il fait partie des critères.

## 4. Contrôler les règles à ne jamais enfreindre

Sur `git diff` depuis le début de l'étape (ou `git diff main...HEAD` + modifications non commitées) :

- Données du cahier des charges (POLITIQUES_RH, OFFRE_POSTE_DEV_PYTHON, CANDIDAT_EXEMPLE_1/2, AGENDA_RECRUTEUR) : inchangées par rapport à `docs/cahier_des_charges.md`.
- `search_interview_slots` et `book_interview` (noms traduits de `rechercher_creneaux_entretien` et `reserver_entretien`) : docstrings, comportement et valeurs de retour identiques au cahier des charges.
- Aucune clé API ni secret dans le diff ; `.env` toujours ignoré par Git.
- Aucun log qui écrit le contenu complet d'un CV.
- Selon l'étape : parsing à température 0.0 + validation Pydantic + 2 appels max (1 appel + 1 relance) ; refus RAG formulé « la politique interne ne précise pas ce point » ; agent qui recherche avant de réserver.

Ne cite que les règles qui concernent l'étape, et signale toute violation en tête du rapport.

## 5. Se relire

Applique le skill `code-review` à ton propre diff. Ne garde que ce qui a un coût réel ; corrige ce qui doit l'être maintenant et liste le reste.

## 6. Rapport de revue

Réponds en français, dans cet ordre :

1. **Étape N — titre** : terminée / pas terminée (une ligne).
2. **Tests** : résultat de `pytest`.
3. **Critères** : le tableau de l'étape 3.
4. **Fichiers modifiés** : liste avec liens, une ligne par fichier sur ce qu'il fait.
5. **Choix faits et pourquoi** : uniquement les décisions qu'un relecteur pourrait contester.
6. **À vérifier en priorité** : 1 à 4 points, les plus risqués d'abord.
7. **Notes & décisions** : propose les lignes à ajouter dans la section du même nom de `.claude/CLAUDE.md` (pièges rencontrés, choix durables). Ne les écris qu'après accord.
8. **Commit proposé** : message de commit suggéré. Ne commite pas sans accord explicite.

## Ce qu'il ne faut pas faire

- Ne pas commencer l'étape suivante, même partiellement, ni l'annoncer comme imminente : l'utilisateur décide.
- Ne pas déclarer l'étape terminée si un critère est ❌.
- Ne pas masquer un échec de test ou un critère non vérifié dans un résumé positif.
