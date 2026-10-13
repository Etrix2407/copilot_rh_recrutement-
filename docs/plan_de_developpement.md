# Plan de développement — Plateforme SaaS RH & Assistant Copilot de Recrutement

Ce document découpe le projet en étapes à suivre dans l'ordre. Chaque étape produit quelque chose de testable avant de passer à la suivante. Aucune ligne de code ici : uniquement quoi faire, dans quel ordre, et comment savoir que c'est fini.

Il s'appuie sur le cahier des charges complet (sections 1 à 8). Les données fournies (politiques RH, offre de poste, candidats, agenda et outils) sont à reprendre **telles quelles**, sans les modifier.

## Vue d'ensemble

| # | Étape | Résultat visible |
|--------|-----------------------------------|-------------------------------------------------------------------|
| 0      | Choix techniques & préparation    | Projet vide qui démarre, clés API configurées                     |
| 1      | Socle backend & données du cahier | API qui répond, données fournies chargées                         |
| 2      | Pilier 1 : Parsing de CV          | POST /api/candidates/parse renvoie un JSON validé                 |
| 3      | Pilier 2 : Assistant RH (RAG)     | POST /api/rag/ask répond avec ses sources                         |
| 4      | Outils de l'agent & créneaux      | Les 2 outils fournis + statut candidat, GET /api/interviews/slots |
| 5      | Pilier 3 : Agent de qualification | L'agent cherche puis réserve un créneau seul                      |
| 6      | Pilier 4 : Streaming SSE          | POST /api/agent/chat diffuse mot à mot + événements               |
| 7      | Interface (dashboard + chat)      | Application utilisable dans le navigateur                         |
| 8      | Tests de validation & critères    | Les 3 tests officiels passent + preuves des 4 critères            |
| 9      | Finitions & démo                  | README, gestion d'erreurs, scénario de démo                       |

## Étape 0 — Choix techniques & préparation

### Décisions à prendre

- **Backend :** Python + FastAPI (gère nativement Pydantic, l'async et le streaming SSE).
- **LLM :** un fournisseur avec structured output et tool calling (Claude, OpenAI ou Gemini). Prévoir une couche d'abstraction pour pouvoir en changer.
- **Embeddings :** le modèle d'embedding du fournisseur, ou un modèle local (sentence-transformers) pour éviter les coûts.
- **Base vectorielle :** ChromaDB (le plus simple pour débuter) ou Qdrant.
- **Stockage des candidats :** optionnel. Un dictionnaire en mémoire suffit pour le cahier des charges ; SQLite seulement si tu veux un dashboard qui survit au redémarrage.
- **Frontend :** React (Vite) ou, plus simple, HTML + JavaScript. Streamlit est tentant mais gère mal le SSE personnalisé.

### Actions

- Créer le dépôt Git et une branche par étape.
- Créer le venv et noter les dépendances dans requirements.txt.
- Définir l'arborescence : api/ (routes), services/ (logique LLM, RAG, agent), models/ (schémas Pydantic), data/ (données du cahier des charges), tools/ (outils de l'agent), tests/, frontend/.
- Ranger le cahier des charges au format .md dans le projet comme document de référence.
- Créer un fichier .env (clés API, nom du modèle) et l'ajouter au .gitignore.

**✔ Terminé quand :**

- Le serveur démarre et une route /health répond « ok ».
- Un appel de test au LLM fonctionne depuis un petit script.

## Étape 1 — Socle backend & données du cahier des charges

- **Données fournies :** copier sans modification dans le dossier data/ : POLITIQUES_RH (section 4), OFFRE_POSTE_DEV_PYTHON, CANDIDAT_EXEMPLE_1 et CANDIDAT_EXEMPLE_2 (section 5), AGENDA_RECRUTEUR (section 6).
- **Agenda :** il reste en mémoire comme dans le cahier des charges. Il se remet à zéro à chaque redémarrage, ce qui est normal pour un mock et pratique pour rejouer les tests.
- **Candidats :** prévoir où ranger chaque candidat analysé (identité, email, JSON d'analyse, score, statut).
- Définir les statuts possibles d'un candidat : nouveau → analysé → entretien planifié → retenu / refusé.
- Mettre en place la configuration centralisée (lecture du .env) et la journalisation (logs).
- Ajouter le middleware CORS pour que le frontend puisse appeler l'API.

**✔ Terminé quand :**

- Les données du cahier des charges sont importables depuis n'importe quel module.
- La documentation automatique de FastAPI (/docs) s'affiche.

## Étape 2 — Pilier 1 : Extraction structurée de CV

### Données de test

- **Base officielle :** OFFRE_POSTE_DEV_PYTHON comme poste visé, CANDIDAT_EXEMPLE_1 (Jean Dupont) et CANDIDAT_EXEMPLE_2 (Sophie Martin).
- **En complément, pour le critère de robustesse :** 5 à 8 CVs atypiques (en anglais, en deux colonnes, très court, reconversion, trous dans le parcours, PDF scanné, texte collé brut).

### Construction

- **Lecture du fichier :** approche recommandée, extraire le texte du PDF (pypdf ou pdfplumber) ou accepter du texte brut. Alternative : envoyer directement le PDF à un modèle multimodal. Prévoir un message d'erreur clair si le PDF est une image sans texte.
- **Schéma Pydantic :** compétences clés (liste), années d'expérience (nombre), niveau d'études (valeurs fixes : bac, bac+2, bac+3, bac+5, doctorat, autre), score d'adéquation (entier 0 à 100), **liste de justifications du score**, points de vigilance (liste).
- **Prompt :** donner le CV + l'offre de poste, et demander une analyse factuelle. Préciser quoi faire si une info est absente (valeur nulle plutôt qu'inventée). Les compétences implicites comptent : Jean Dupont n'écrit pas « RAG », mais LLM + ChromaDB en relèvent.
- **Réglages :** température à 0.0 pour des extractions constantes, et mode structured output / tool forcé du fournisseur pour imposer le schéma.
- **Validation + relance :** valider la réponse avec Pydantic ; en cas d'échec, renvoyer l'erreur au LLM et réessayer (2 tentatives max), puis renvoyer une erreur propre.
- **Endpoint :** POST /api/candidates/parse → enregistre le candidat, passe son statut à « analysé » et renvoie le JSON.

**✔ Terminé quand :**

- Jean Dupont obtient un score supérieur à 80, avec FastAPI et RAG dans ses compétences.
- Sophie Martin obtient un score inférieur à 40.
- Tous les CVs atypiques produisent un JSON valide, score toujours entre 0 et 100.

## Étape 3 — Pilier 2 : Assistant RH avec RAG

### Le corpus

- Utiliser uniquement les 4 documents de POLITIQUES_RH : télétravail, congés & RTT, formation, rémunération & avantages.
- Les textes étant courts, garder un document = un morceau, sans découpage.

### L'indexation au démarrage

- Indexer les 4 documents dans la base vectorielle au lancement de l'application (événement de démarrage / lifespan de FastAPI), comme l'exige le cahier des charges.
- Utiliser l'id fourni (rh_doc_01…) comme identifiant dans la base : un redémarrage met à jour les documents au lieu de créer des doublons.
- Conserver le titre en métadonnée pour l'afficher dans les sources.

### La réponse

- Transformer la question en embedding et récupérer les 2 ou 3 documents les plus proches.
- **Prompt système impératif :** répondre uniquement à partir du contexte fourni et, si l'information n'y figure pas explicitement, répondre obligatoirement que **la politique interne ne précise pas ce point**.
- Optionnel : un seuil de similarité qui, en dessous, renvoie directement cette même phrase sans appeler le LLM.
- Endpoint POST /api/rag/ask → renvoie la réponse + la liste des extraits utilisés (id, titre, texte).

**✔ Terminé quand :**

- « Combien de jours de RTT ai-je droit et puis-je les placer sur un CET ? » → 10 RTT par an, et un solde de 5 RTT non pris peut aller sur le CET, avec la source rh_doc_02.
- « Quelle est la prime de naissance accordée par l'entreprise ? » → réponse indiquant que la politique interne ne précise pas ce point.
- D'autres questions pièges (prime de cooptation, jours pour un mariage…) reçoivent le même refus.

## Étape 4 — Outils de l'agent & créneaux d'entretien

### Les outils fournis

- **rechercher_creneaux_entretien(date)** : renvoie la liste des heures libres pour une date au format YYYY-MM-DD, ou une liste vide.
- **reserver_entretien(candidat_nom, date, heure, email)** : retire le créneau de l'agenda et renvoie SUCCES avec la confirmation (l'invitation est incluse dans le message), ou ERREUR « Créneau indisponible ».
- Les reprendre exactement comme dans le cahier des charges : mêmes noms, mêmes paramètres, mêmes docstrings, qui serviront de description aux outils.

### À ajouter toi-même

- **mettre_a_jour_statut_candidat** (nom ou id, nouveau statut) : exigé par le pilier 3 mais sans fonction fournie. Vérifier que la transition est autorisée.

### Exposition

- Endpoint GET /api/interviews/slots (paramètres : identifiant candidat, date) qui appelle rechercher_creneaux_entretien.
- Décrire chaque outil pour le LLM : nom, description, paramètres et leurs types.

**✔ Terminé quand :**

- Chaque fonction est testée sans LLM.
- Réserver deux fois le même créneau renvoie ERREUR la seconde fois.
- Une date absente de l'agenda renvoie une liste vide.

## Étape 5 — Pilier 3 : Agent de qualification

- Écrire le prompt système de l'agent : son rôle, ses outils, et deux règles clés :
  - toujours vérifier la disponibilité avec **rechercher_creneaux_entretien** avant d'appeler **reserver_entretien** ;
  - quand la demande est explicite (candidat, email et date donnés), réserver directement sans redemander confirmation ; ne poser une question que s'il manque une information (email absent, date floue).
- Construire la boucle d'agent : envoyer le message → si le LLM demande un outil, l'exécuter → ajouter le résultat à l'historique des messages → recommencer jusqu'à une réponse finale.
- Fixer une limite d'itérations (ex. 8) pour éviter les boucles infinies.
- Gérer les retours d'erreur : si la réservation renvoie ERREUR, l'agent relance une recherche et propose ou prend un autre créneau.
- Après une réservation réussie, passer le statut du candidat à « entretien planifié ».
- Conserver l'historique de conversation et journaliser chaque appel d'outil (nom, arguments, résultat, durée).

**✔ Terminé quand :**

- « Trouve-moi un créneau le 2026-10-15 pour réserver un entretien avec Jean Dupont (jean.dupont@email.com) » déclenche la recherche puis la réservation, sans intervention.
- Le créneau réservé disparaît de l'agenda ; une deuxième demande identique réserve le créneau suivant.

## Étape 6 — Pilier 4 : Streaming SSE

- Définir les types d'événements envoyés au frontend :
  - **token** : un morceau de texte de la réponse.
  - **tool_start** : un outil est lancé (nom + arguments).
  - **tool_result** : résultat résumé de l'outil.
  - **done** et **error** : fin ou problème.
- Transformer la boucle d'agent de l'étape 5 pour qu'elle produise ces événements au fil de l'eau (streaming du fournisseur LLM).
- Endpoint POST /api/agent/chat en réponse SSE (StreamingResponse, type text/event-stream).
- Gérer la déconnexion du client (arrêter la génération) et un message d'erreur propre en fin de flux.

**✔ Terminé quand :**

- Avec un outil comme curl, on voit les mots arriver un par un et les événements d'outils dans l'ordre.

## Étape 7 — Interface utilisateur

- **Page Analyse de CV :** dépôt du fichier ou collage du texte, affichage du résultat (score en jauge, compétences en étiquettes, justifications, points de vigilance mis en évidence).
- **Dashboard candidats :** tableau triable par score et statut.
- **Assistant RH :** champ de question, réponse + encadré « Sources » avec les extraits.
- **Chat agent :** affichage mot à mot, et pour chaque outil une carte « 🔧 Recherche de créneaux… » qui passe à « ✔ 4 créneaux trouvés ».
- Lire le flux SSE côté navigateur avec fetch + lecture du flux (EventSource ne gère pas le POST).
- Prévoir les états de chargement, d'erreur et de liste vide sur chaque page.

**✔ Terminé quand :**

- Le parcours complet se fait sans toucher à /docs : analyser le CV de Jean Dupont → voir son score → demander à l'agent de planifier l'entretien → voir son statut changer.

## Étape 8 — Tests de validation & critères d'évaluation

### Les 3 tests officiels (section 8 du cahier des charges)

| Test | Action | Résultat attendu |
|-------------|-------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| 1 — Parsing | Soumettre CANDIDAT_EXEMPLE_1 puis CANDIDAT_EXEMPLE_2 face à l'offre Lead Developer Python / IA              | Jean Dupont \> 80 avec FastAPI / RAG extraits ; Sophie Martin \< 40                 |
| 2 — RAG     | Question sur les RTT et le CET, puis question sur la prime de naissance                                     | Réponse juste et sourcée, puis refus : la politique interne ne précise pas ce point |
| 3 — Agent   | « Trouve-moi un créneau le 2026-10-15 pour réserver un entretien avec Jean Dupont (jean.dupont@email.com) » | Recherche des créneaux puis réservation effectuée                                   |

- Automatiser ces 3 tests (pytest) pour pouvoir les rejouer après chaque modification. Redémarrer l'agenda entre deux exécutions du test 3.

### Les 4 critères d'évaluation

| Critère | Comment le prouver |
|----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| Robustesse de l'extraction | Test automatique sur les 2 candidats officiels + tous les CVs atypiques : 100 % de JSON valides. Tableau des résultats dans le README.        |
| Étanchéité du RAG          | La question officielle sur la prime de naissance + une dizaine de questions pièges (règles plausibles mais absentes) : aucune règle inventée. |
| Autonomie de l'agent       | Test 3 + scénarios supplémentaires (créneau déjà pris, date sans créneau) ; vérifier dans les logs l'enchaînement des outils.                 |
| Expérience utilisateur     | Mesurer le délai avant le premier mot affiché, tester sur mobile, faire tester par quelqu'un qui ne connaît pas le projet.                    |

- Ajouter des tests unitaires sur les outils et les schémas, et des tests d'intégration sur les endpoints.

## Étape 9 — Finitions & démo

- README : installation, lancement, architecture (schéma), choix techniques justifiés, résultats des tests officiels.
- Gestion d'erreurs homogène : format d'erreur commun pour toute l'API.
- Données personnelles : ne pas journaliser le contenu complet des CVs, prévoir la suppression d'un candidat (RGPD).
- Limiter la taille des fichiers envoyés et le nombre de requêtes.
- Préparer un scénario de démo de 5 minutes qui rejoue les 3 tests officiels dans l'interface.

## Correspondance avec le cahier des charges

| Section du cahier des charges | Étape du plan |
|--------------------------------------------|------------------------------------------------|
| 1\. Exigences fonctionnelles & piliers LLM | Étapes 2, 3, 5 et 6                            |
| 2\. Synthèse des API                       | Étapes 2, 3, 4 et 6                            |
| 3\. Critères d'évaluation                  | Étape 8                                        |
| 4\. Base RAG (politiques RH)               | Étapes 1 et 3                                  |
| 5\. Offre de poste & candidats mocks       | Étapes 1 et 2                                  |
| 6\. Outils de l'agent                      | Étapes 1 et 4                                  |
| 7\. Conseils d'architecture (Tips 1 à 4)   | Étapes 2 (Tips 1 et 2), 3 (Tip 3) et 5 (Tip 4) |
| 8\. Tests de validation                    | Étapes 2, 3, 5 et 8                            |

## Conseils de méthode

- Finir chaque étape complètement avant la suivante : les étapes 5 et 6 réutilisent tout ce qui précède.
- Toujours tester un pilier en ligne de commande (/docs ou curl) avant de construire son interface.
- Garder les prompts dans des fichiers séparés pour les ajuster sans toucher au code.
- Commencer avec un petit modèle peu coûteux pour développer, puis passer au modèle final pour les tests de validation.
