# Cahier des charges — Plateforme SaaS RH & Assistant Copilot de Recrutement

> **Document de référence du projet.** Le texte original du cahier des charges commence à la section « Texte original » et n'a pas été modifié. Les données et le code des sections 4, 5 et 6 sont à reprendre **tels quels**.

## Sommaire

1. Exigences fonctionnelles & piliers LLM
2. Synthèse des API & envois attendus
3. Critères d'évaluation
4. Jeu de données : base RAG (politiques RH) — `POLITIQUES_RH`
5. Jeu de données : offre de poste & candidats — `OFFRE_POSTE_DEV_PYTHON`, `CANDIDAT_EXEMPLE_1`, `CANDIDAT_EXEMPLE_2`
6. Outils de l'agent — `AGENDA_RECRUTEUR`, `rechercher_creneaux_entretien`, `reserver_entretien`
7. Conseils d'architecture (Tips 1 à 4)
8. Tests de validation

## Résumé des exigences (checklist)

| ID | Exigence | Source |
|---|---|---|
| EX-01 | `POST /api/candidates/parse` : PDF ou texte → JSON validé (compétences, années d'expérience, niveau d'études, score 0-100, points de vigilance) | §1, §2 |
| EX-02 | Parsing : schéma strict, score numérique + liste de justifications, température 0.0 | §7 Tip 2 |
| EX-03 | `POST /api/rag/ask` : réponse sourcée avec extraits retrouvés | §2 |
| EX-04 | `POLITIQUES_RH` indexées dans la base vectorielle au démarrage de l'application | §4 |
| EX-05 | RAG : si l'information n'est pas dans le contexte, répondre que la politique interne ne précise pas ce point | §7 Tip 3 |
| EX-06 | `POST /api/agent/chat` : tool calling + streaming SSE (flux texte + événements d'outils) | §1, §2 |
| EX-07 | Outils `rechercher_creneaux_entretien` et `reserver_entretien` implémentés comme fournis | §6 |
| EX-08 | Agent : vérifier la disponibilité avant de réserver, historique des messages avec résultats d'outils | §7 Tip 4 |
| EX-09 | Agent : envoi d'invitations et mise à jour des statuts candidats | §1 |
| EX-10 | `GET /api/interviews/slots` : ID candidat / date → créneaux disponibles | §2 |
| EX-11 | Interface : streaming mot à mot + affichage des outils déclenchés + dashboard | §1, §3 |
| EX-12 | Les 3 tests de validation passent | §8 |

---

## Texte original

Ce projet vise à concevoir une solution complète de **Recrutement Intelligent et Gestion RH** intégrant les fonctionnalités clés des LLM modernes. L'application doit permettre aux équipes RH d'évaluer automatiquement des profils, d'interroger la politique interne via un système RAG, et d'interagir avec un agent interactif capable d'exécuter des actions métiers.

---

## 1. EXIGENCES FONCTIONNELLES & PILIERS LLM

### 1. Extraction Structurée (Parsing CV) — `Structured Output`

Analyse automatique de CVs bruts. Extraction garantie sous format JSON : compétences clés, années d'expérience, niveau d'études, adéquation avec un poste (score de 0 à 100) et points de vigilance.

### 2. Assistant RH RAG — `Vector DB / RAG`

Moteur de recherche documentaire sémantique sur les politiques internes RH (congés, télétravail, avantages). Réponses strictes et factuelles fondées sur le contexte interne (anti-hallucination).

### 3. Agent de Qualification — `Function Calling`

Agent conversationnel capable d'appeler des fonctions système : recherche de créneaux d'entretien, réservation automatique, envoi d'invitations et mise à jour des statuts candidats.

### 4. Interface Conversationnelle — `Streaming SSE`

Chat interactif fluide avec restitution de la réponse en streaming mot à mot. Affichage visuel clair des outils déclenchés par l'agent pendant la conversation.

---

## 2. SYNTHÈSE DES API & ENVOIS ATTENDUS

| Endpoint / Composant | Entrée | Mécanisme LLM | Sortie Attendue |
|---|---|---|---|
| `POST /api/candidates/parse` | Fichier PDF ou Texte du CV | Pydantic / Schema Strict | JSON validé avec score & compétences |
| `POST /api/rag/ask` | Question sur politiques RH | Embedding + Vector Search | Réponse sourcée avec extraits retrouvés |
| `POST /api/agent/chat` | Message utilisateur / Prompt | Tool Calling & Streaming SSE | Flux texte + événements d'exécution d'outils |
| `GET /api/interviews/slots` | ID Candidat / Date | Fonction locale / Mock DB | Liste des créneaux disponibles |

---

## 3. CRITÈRES D'ÉVALUATION

- **Robustesse de l'extraction :** Garantie du format JSON sans rupture de schéma même sur des CVs atypiques.
- **Étanchéité du RAG :** Incapacité démontrée de l'assistant à inventer des règles de gestion RH non documentées.
- **Autonomie de l'Agent :** Capacité à enchaîner plusieurs appels d'outils si nécessaire pour planifier un entretien.
- **Qualité de l'Expérience Utilisateur :** Fluidité du flux de streaming et clarté du dashboard.

---

## 4. JEU DE DONNÉES : BASE RAG (POLITIQUES RH INTERNES)

> ⚠️ Données à copier telles quelles dans le projet.


Ces données doivent être indexées dans votre base vectorielle (Vector Database) au démarrage de l'application :

```python
POLITIQUES_RH = [
    {
        "id": "rh_doc_01",
        "titre": "Charte Télétravail & Flexibilité",
        "texte": "Chaque collaborateur en CDI ayant passé la période d'essai bénéficie de 2 jours de télétravail par semaine (mardi et jeudi ou lundi et vendredi). Une allocation forfaitaire de 30€/mois est versée pour couvrir les frais de connexion et d'électricité. Tout jour de télétravail supplémentaire nécessite l'accord explicite du N+1."
    },
    {
        "id": "rh_doc_02",
        "titre": "Politique de Congés & RTT",
        "texte": "L'entreprise accorde 25 jours de congés payés et 10 jours de RTT par an. La pose de plus de 2 semaines consécutives en période estivale (juillet-août) doit être validée avant le 30 avril. Un solde de 5 RTT non pris peut être placé sur le Compte Épargne Temps (CET) à la fin de l'exercice annuel."
    },
    {
        "id": "rh_doc_03",
        "titre": "Budget Formation & Développement",
        "texte": "Un budget annuel de 1 500 € HT par salarié est alloué pour les formations externes ou certifiantes (Cloud, IA, Management). Les demandes s'effectuent via l'outil interne RH avec l'aval du responsable d'équipe. La participation à deux conférences techniques par an est prise en charge à 100% hors budget individuel."
    },
    {
        "id": "rh_doc_04",
        "titre": "Grille de Rémunération & Avantages",
        "texte": "Les avantages sociaux incluent une mutuelle prise en charge à 80% par l'employeur, des tickets restaurant d'une valeur faciale de 10 € (prise en charge à 60%), et un abonnement d'assistance sportive. Les révisions salariales se déroulent une fois par an lors de l'entretien annuel d'évaluation en décembre."
    }
]
```

---

## 5. JEU DE DONNÉES : OFFRES DE POSTE & CANDIDATS MOCKS

> ⚠️ Données à copier telles quelles dans le projet.


```python
OFFRE_POSTE_DEV_PYTHON = """
Poste : Lead Developer Python / IA
Expérience requise : Minimum 5 ans.
Compétences obligatoires : Python 3.11+, FastAPI, Pydantic, architectures RAG, Docker, bases vectorielles (ChromaDB/Qdrant), API OpenAI/Gemini.
Salaire indicatif : 55k - 65k € selon profil.
Modalités : CDI, Télétravail partiel.
"""

CANDIDAT_EXEMPLE_1 = """
Jean Dupont - Développeur Fullstack & Data
Email: jean.dupont@email.com | Tél: 06 12 34 56 78
Résumé: Développeur passionné avec 6 ans d'expérience en Python et JavaScript.
Expérience:
- 2021 - Présent: Senior Python Dev chez TechCorp. Développement d'API FastAPI, intégration de modèles LLM avec Pydantic et ChromaDB. Mise en place de pipelines CI/CD Docker.
- 2018 - 2021: Développeur Backend chez SoftSolutions. Django, PostgreSQL, Redis.
Formation: Master en Informatique, Université de Lyon (2018).
Compétences: Python, FastAPI, Docker, ChromaDB, OpenAI API, SQL, Git, React.
"""

CANDIDAT_EXEMPLE_2 = """
Sophie Martin - Développeuse Front-End Junior
Email: sophie.m@email.com | Tél: 06 98 76 54 32
Résumé: Développeuse Web spécialisée en interfaces réactives avec 1 an d'expérience.
Expérience:
- 2023 - Présent: Développeuse Front-End chez WebAgency. React.js, TailwindCSS, HTML/CSS.
Formation: Bootcamp Développement Web (2023).
Compétences: JavaScript, React, CSS, HTML, Git. Notion de Python de base.
"""
```

---

## 6. API & MOCKS POUR LE TOOL CALLING (OUTILS AGENT)

> ⚠️ Code à reprendre tel quel : mêmes noms, paramètres et docstrings.


Implémentez ces fonctions dans votre code métier pour servir d'outils (tools) à votre agent :

```python
# BDD de créneaux mockés
AGENDA_RECRUTEUR = {
    "2026-10-15": ["09:00", "11:00", "14:30", "16:00"],
    "2026-10-16": ["10:00", "15:00"]
}

def rechercher_creneaux_entretien(date: str) -> list[str]:
    """Retourne la liste des heures disponibles pour un entretien à une date donnée (format YYYY-MM-DD)."""
    return AGENDA_RECRUTEUR.get(date, [])

def reserver_entretien(candidat_nom: str, date: str, heure: str, email: str) -> dict:
    """Réserve un créneau d'entretien pour un candidat et confirme la réservation."""
    if date in AGENDA_RECRUTEUR and heure in AGENDA_RECRUTEUR[date]:
        AGENDA_RECRUTEUR[date].remove(heure)
        return {"statut": "SUCCES", "message": f"Entretien confirmé pour {candidat_nom} le {date} à {heure}. Invitation envoyée à {email}."}
    return {"statut": "ERREUR", "message": "Créneau indisponible."}
```

---

## 7. CONSEILS D'ARCHITECTURE & TIPS TECHNIQUES

### 💡 Tip 1 : Traitement des Fichiers PDF (Parsing CV)

Pour analyser un CV au format PDF, vous avez 2 approches classiques :

1. **Extraction de texte (Recommandé) :** Utilisez une bibliothèque de votre langage (ex: `pypdf`, `pdfplumber` en Python, `pdf-parse` en JS) pour extraire le texte brut du PDF, puis injectez ce texte dans le prompt du LLM.
2. **Approche Multimodale :** Si votre modèle accepte le format vision/document (comme Gemini), vous pouvez lui passer directement les octets du PDF ou une conversion en image page par page.

### 💡 Tip 2 : Structured Outputs & Validation

Définissez un schéma rigoureux (ex: Pydantic en Python ou type-check strict en TypeScript). Exigez que l'IA retourne un score de pertinence numérique et une liste de justification explicite. Fixez la température à `0.0` pour assurer la consistance des extractions.

### 💡 Tip 3 : RAG & Anti-Hallucination

Dans le system prompt de votre service RAG, donnez une consigne impérative : *"Si l'information demandée ne figure pas explicitement dans le contexte fourni ci-dessus, réponds obligatoirement que la politique interne ne précise pas ce point."*

### 💡 Tip 4 : Boucle d'Agent & Multi-Tools

Lors de la réservation d'un entretien, l'agent doit idéalement d'abord vérifier la disponibilité via `rechercher_creneaux_entretien` avant de déclencher `reserver_entretien`. N'oubliez pas de gérer le tableau d'historique des messages pour transmettre les résultats de chaque outil au LLM.

---

## 8. DÉROULÉ DES TESTS DE VALIDATION

1. **Test 1 (Parsing) :** Soumettre `CANDIDAT_EXEMPLE_1` et vérifier la bonne extraction du score (qui doit être élevé > 80%) et des compétences FastAPI/RAG. Soumettre `CANDIDAT_EXEMPLE_2` (score faible < 40%).
2. **Test 2 (RAG) :** Poser la question *"Combien de jours de RTT ai-je droit et puis-je les placer sur un CET ?"* (Succès attendu) puis *"Quelle est la prime de naissance accordée par l'entreprise ?"* (Refus attendu par manque de contexte).
3. **Test 3 (Agent) :** Demander dans le chat *"Trouve-moi un créneau le 2026-10-15 pour réserver un entretien avec Jean Dupont (jean.dupont@email.com)"*. Vérifier que l'agent effectue la recherche et réserve la plage horaire.
